"""
scheduler.py — APScheduler entry point for the OCP AI Monitoring Agent.

This is the process entry point. Run it directly:
    python -m agent.scheduler
    # or
    python scheduler.py

Responsibilities:
  1. Configure structured logging (once, before anything else)
  2. Validate DB connectivity and initialise schema on first run
  3. Register run_cycle() as an interval job with APScheduler
  4. Fire the first cycle immediately on startup (no cold-start wait)
  5. Block the main thread and keep the scheduler alive

Scheduler properties:
  - Type        : BlockingScheduler — keeps the process alive without a loop
  - Trigger     : IntervalTrigger — fires every cfg.interval_minutes
  - First run   : next_run_time=now() — executes immediately on boot
  - Timezone    : cfg.timezone (default: Asia/Kolkata)
  - Job ID      : "ocp_monitor" — allows pause/resume via APScheduler API
  - Misfire grace: 60 seconds — if a cycle is delayed (e.g. slow LLM), the
                   next one still fires on schedule rather than being skipped
  - Max instances: 1 — prevents overlapping cycles if one runs long

Graceful shutdown:
  SIGINT (Ctrl-C) and SIGTERM both trigger scheduler.shutdown(wait=False),
  which stops the scheduler cleanly without waiting for a running cycle to finish.

Environment:
  All config is read from .env / environment variables via agent.config.
  See config.py for the full list of supported variables.
"""

from __future__ import annotations

import signal
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from agent.config import get_settings
from agent.db import health_check, init_db
from agent.logger import configure_logging, get_logger

cfg = get_settings()

# Configure logging before importing anything else that logs
configure_logging(log_level=cfg.log_level, log_format=cfg.log_format)
log = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Job function — thin wrapper so APScheduler stack traces are clean
# ──────────────────────────────────────────────────────────────────────────────

def _run_cycle_job() -> None:
    """
    APScheduler job target. Imports agent lazily to avoid circular imports
    at module load time and to keep scheduler startup fast.
    """
    from agent.agent import run_cycle

    log.info("scheduler_job_fired", interval_minutes=cfg.interval_minutes)
    try:
        final_state = run_cycle()
        failures    = final_state.get("failures", [])
        severities  = {f.get("severity", "").upper() for f in failures}

        if "CRITICAL" in severities:
            overall = "CRITICAL"
        elif "WARNING" in severities or failures:
            overall = "WARNING"
        else:
            overall = "HEALTHY"

        log.info(
            "scheduler_job_done",
            status=overall,
            failure_count=len(failures),
            run_id=final_state.get("run_id", ""),
            email_sent=final_state.get("email_sent", False),
            cluster=final_state.get("cluster_name", cfg.cluster_name),
        )

    except Exception as exc:
        # run_cycle() is designed never to raise, but guard here anyway
        log.error("scheduler_job_failed", error=str(exc), exc_info=True)


# ──────────────────────────────────────────────────────────────────────────────
# Startup checks
# ──────────────────────────────────────────────────────────────────────────────

def _startup_checks() -> None:
    """
    Run pre-flight checks before the scheduler starts.
    Exits the process with code 1 if any critical dependency is unavailable.
    """
    log.info(
        "agent_startup",
        cluster=cfg.cluster_name,
        interval_minutes=cfg.interval_minutes,
        timezone=cfg.timezone,
        log_level=cfg.log_level,
        email_backend=cfg.email_backend,
        llm_model=cfg.llm_model,
        in_cluster=cfg.is_in_cluster,
    )

    # Database connectivity
    log.info("startup_check", check="database")
    if not health_check():
        log.error(
            "startup_check_failed",
            check="database",
            reason="Cannot connect to PostgreSQL. Check POSTGRES_* env vars.",
        )
        sys.exit(1)
    log.info("startup_check_passed", check="database")

    # Initialise schema (CREATE TABLE IF NOT EXISTS — safe to repeat)
    log.info("startup_check", check="db_init")
    init_db()
    log.info("startup_check_passed", check="db_init")

    log.info("startup_checks_complete")


# ──────────────────────────────────────────────────────────────────────────────
# Scheduler setup and main entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """
    Start the OCP monitoring agent scheduler.

    1. Run startup checks (DB, schema).
    2. Register the monitoring job.
    3. Block the main thread via BlockingScheduler.start().
    """
    _startup_checks()

    scheduler = BlockingScheduler(timezone=cfg.timezone)

    trigger = IntervalTrigger(
        minutes=cfg.interval_minutes,
        timezone=cfg.timezone,
    )

    scheduler.add_job(
        _run_cycle_job,
        trigger=trigger,
        id="ocp_monitor",
        name=f"OCP Monitor — {cfg.cluster_name}",
        next_run_time=datetime.now(timezone.utc),   # fire immediately on boot
        misfire_grace_time=60,                       # tolerate up to 60s delay
        max_instances=1,                             # no overlapping cycles
        replace_existing=True,
    )

    # ── Graceful shutdown on SIGINT / SIGTERM ────────────────────────────────
    def _shutdown(signum, frame):
        sig_name = signal.Signals(signum).name
        log.info("shutdown_signal_received", signal=sig_name)
        scheduler.shutdown(wait=False)
        log.info("scheduler_stopped")
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    log.info(
        "scheduler_starting",
        job_id="ocp_monitor",
        cluster=cfg.cluster_name,
        interval_minutes=cfg.interval_minutes,
        timezone=cfg.timezone,
        first_run="immediate",
    )

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("scheduler_stopped")


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    main()
