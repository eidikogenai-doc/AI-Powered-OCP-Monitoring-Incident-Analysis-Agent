"""
dashboard.py — FastAPI web dashboard for the OCP AI Monitoring Agent.

Serves a real-time monitoring UI backed by the PostgreSQL agent database.

Routes:
  GET  /              → Main dashboard (last N runs, live status)
  GET  /run/{run_id}  → Full detail page for a single agent run
  GET  /incidents     → RAG knowledge base viewer (incidents table)
  POST /incidents     → Add a new incident to the knowledge base
  GET  /health        → JSON health check (DB connectivity)
  GET  /api/runs      → JSON: list of recent AgentRun summaries
  GET  /api/run/{id}  → JSON: full AgentRun with failures + resolutions
  GET  /api/stats     → JSON: 24h trend stats for the header metrics
  GET  /api/incidents → JSON: paginated incidents list

Design decisions:
  - Jinja2 templates in agent/templates/ — single HTML file, self-contained CSS
  - All DB queries use the existing get_session() context manager
  - Async FastAPI routes with sync DB calls (acceptable for low-QPS dashboard)
  - No auth — deploy behind OpenShift OAuth proxy or ingress for protection
  - HTMX-friendly JSON endpoints for partial refreshes
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func

from agent.config import get_settings
from agent.db import get_session, health_check
from agent.logger import configure_logging, get_logger
from agent.models import AgentRun, Failure, Resolution, Incident

cfg = get_settings()
configure_logging(log_level=cfg.log_level, log_format=cfg.log_format)
log = get_logger(__name__)

app = FastAPI(
    title="OCP AI Monitoring Dashboard",
    description="Real-time OpenShift cluster health monitoring powered by LLM + LangGraph",
    version="1.0.0",
    docs_url="/api/docs",
)

templates = Jinja2Templates(directory="agent/templates")


# ──────────────────────────────────────────────────────────────────────────────
# Template helpers
# ──────────────────────────────────────────────────────────────────────────────

def _run_to_dict(run: AgentRun) -> Dict[str, Any]:
    return {
        "id": str(run.id),
        "cluster_name": run.cluster_name,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "status": run.status,
        "failure_count": run.failure_count,
        "summary": run.summary or "",
        "email_sent": run.email_sent,
        "collection_errors": run.collection_errors or {},
        "duration_s": (
            int((run.completed_at - run.started_at).total_seconds())
            if run.completed_at and run.started_at else None
        ),
    }


def _failure_to_dict(f: Failure) -> Dict[str, Any]:
    res = f.resolution
    return {
        "id": str(f.id),
        "failure_ref": f.failure_ref,
        "component": f.component,
        "resource_name": f.resource_name or "",
        "severity": f.severity,
        "message": f.message,
        "detected_at": f.detected_at.isoformat() if f.detected_at else None,
        "resolution": {
            "root_cause": res.root_cause or "",
            "steps": res.steps or [],
            "commands": res.commands or [],
            "docs_ref": res.docs_ref or "",
        } if res else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# HTML routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Main dashboard — recent runs, live status strip, trend chart data."""
    with get_session() as session:
        runs = (
            session.query(AgentRun)
            .order_by(desc(AgentRun.started_at))
            .limit(cfg.dashboard_history_limit)
            .all()
        )
        runs_data = [_run_to_dict(r) for r in runs]

        # 24-hour stats
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        total_24h = session.query(func.count(AgentRun.id)).filter(
            AgentRun.started_at >= since
        ).scalar() or 0
        critical_24h = session.query(func.count(AgentRun.id)).filter(
            AgentRun.started_at >= since,
            AgentRun.status == "CRITICAL",
        ).scalar() or 0
        warning_24h = session.query(func.count(AgentRun.id)).filter(
            AgentRun.started_at >= since,
            AgentRun.status == "WARNING",
        ).scalar() or 0

        # Latest run overall status
        latest = runs[0] if runs else None
        latest_status = latest.status if latest else "UNKNOWN"

        # Total incidents in RAG kb
        incident_count = session.query(func.count(Incident.id)).scalar() or 0
        indexed_count = session.query(func.count(Incident.id)).filter(
            Incident.indexed == True  # noqa
        ).scalar() or 0

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "runs": runs_data,
            "cluster_name": cfg.cluster_name,
            "latest_status": latest_status,
            "total_24h": total_24h,
            "critical_24h": critical_24h,
            "warning_24h": warning_24h,
            "healthy_24h": total_24h - critical_24h - warning_24h,
            "incident_count": incident_count,
            "indexed_count": indexed_count,
            "interval_minutes": cfg.interval_minutes,
            "page": "home",
        },
    )


@app.get("/run/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str):
    """Full detail view for a single monitoring cycle."""
    try:
        uid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run ID format")

    with get_session() as session:
        run = session.query(AgentRun).filter(AgentRun.id == uid).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        failures = (
            session.query(Failure)
            .filter(Failure.run_id == uid)
            .order_by(Failure.severity)
            .all()
        )
        failures_data = [_failure_to_dict(f) for f in failures]
        run_data = _run_to_dict(run)
        raw = run.raw_snapshot or {}

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "run": run_data,
            "failures": failures_data,
            "raw": raw,
            "cluster_name": cfg.cluster_name,
            "page": "run_detail",
        },
    )


@app.get("/incidents", response_class=HTMLResponse)
async def incidents_page(request: Request, page: int = 1, component: str = ""):
    """RAG knowledge base viewer — list and add incidents."""
    per_page = 20
    offset = (page - 1) * per_page

    with get_session() as session:
        q = session.query(Incident)
        if component:
            q = q.filter(Incident.component == component)
        total = q.count()
        incidents = (
            q.order_by(desc(Incident.created_at))
            .offset(offset)
            .limit(per_page)
            .all()
        )
        components = [
            r[0] for r in session.query(Incident.component).distinct().all() if r[0]
        ]
        incidents_data = [
            {
                "id": str(inc.id),
                "incident_id": inc.incident_id,
                "title": inc.title,
                "component": inc.component or "",
                "severity": inc.severity or "",
                "description": inc.description[:200] + "..." if len(inc.description) > 200 else inc.description,
                "root_cause": inc.root_cause or "",
                "indexed": inc.indexed,
                "occurred_at": inc.occurred_at.strftime("%Y-%m-%d") if inc.occurred_at else "",
                "created_at": inc.created_at.strftime("%Y-%m-%d %H:%M") if inc.created_at else "",
            }
            for inc in incidents
        ]

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "incidents": incidents_data,
            "components": components,
            "component_filter": component,
            "total": total,
            "page": "incidents",
            "current_page": page,
            "total_pages": (total + per_page - 1) // per_page,
            "cluster_name": cfg.cluster_name,
        },
    )


@app.post("/incidents")
async def add_incident(
    incident_id: str = Form(...),
    title: str = Form(...),
    component: str = Form(...),
    severity: str = Form(...),
    description: str = Form(...),
    root_cause: str = Form(default=""),
    occurred_at: str = Form(default=""),
):
    """Add a new incident to the RAG knowledge base."""
    try:
        occurred = None
        if occurred_at:
            occurred = datetime.fromisoformat(occurred_at).replace(tzinfo=timezone.utc)

        with get_session() as session:
            inc = Incident(
                incident_id=incident_id,
                title=title,
                component=component,
                severity=severity,
                description=description,
                root_cause=root_cause or None,
                occurred_at=occurred,
            )
            session.add(inc)

        # Trigger async indexing
        try:
            from agent.rag import add_incident as rag_add
            rag_add(inc)
        except Exception as e:
            log.warning("dashboard_rag_index_failed", error=str(e))

    except Exception as e:
        log.error("dashboard_add_incident_failed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

    return RedirectResponse(url="/incidents", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# JSON API routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    db_ok = health_check()
    return JSONResponse(
        content={"status": "ok" if db_ok else "degraded", "db": db_ok},
        status_code=200 if db_ok else 503,
    )


@app.get("/api/runs")
async def api_runs(limit: int = 20):
    with get_session() as session:
        runs = (
            session.query(AgentRun)
            .order_by(desc(AgentRun.started_at))
            .limit(min(limit, 100))
            .all()
        )
        return [_run_to_dict(r) for r in runs]


@app.get("/api/run/{run_id}")
async def api_run_detail(run_id: str):
    try:
        uid = uuid.UUID(run_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid run ID")

    with get_session() as session:
        run = session.query(AgentRun).filter(AgentRun.id == uid).first()
        if not run:
            raise HTTPException(status_code=404, detail="Not found")
        failures = session.query(Failure).filter(Failure.run_id == uid).all()
        data = _run_to_dict(run)
        data["failures"] = [_failure_to_dict(f) for f in failures]
        data["raw_snapshot"] = run.raw_snapshot
        return data


@app.get("/api/stats")
async def api_stats():
    """24-hour trend: run counts by status per hour (for sparkline chart)."""
    with get_session() as session:
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        runs = (
            session.query(AgentRun)
            .filter(AgentRun.started_at >= since)
            .order_by(AgentRun.started_at)
            .all()
        )
        by_hour: Dict[int, Dict[str, int]] = {}
        for r in runs:
            h = r.started_at.replace(minute=0, second=0, microsecond=0).isoformat()
            if h not in by_hour:
                by_hour[h] = {"HEALTHY": 0, "WARNING": 0, "CRITICAL": 0, "ERROR": 0}
            by_hour[h][r.status] = by_hour[h].get(r.status, 0) + 1

        return {"hourly": by_hour, "total_runs": len(runs)}


@app.get("/api/incidents")
async def api_incidents(limit: int = 50, offset: int = 0):
    with get_session() as session:
        total = session.query(func.count(Incident.id)).scalar() or 0
        incidents = (
            session.query(Incident)
            .order_by(desc(Incident.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "total": total,
            "items": [
                {
                    "incident_id": i.incident_id,
                    "title": i.title,
                    "component": i.component,
                    "severity": i.severity,
                    "indexed": i.indexed,
                }
                for i in incidents
            ],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "agent.dashboard:app",
        host=cfg.dashboard_host,
        port=cfg.dashboard_port,
        reload=False,
        log_config=None,  # use structlog instead
    )
