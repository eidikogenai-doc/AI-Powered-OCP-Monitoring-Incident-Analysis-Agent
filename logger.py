"""
llm_chains.py — LLM prompt chains for failure analysis and remediation.

Two chains using Groq (llama-3.3-70b-versatile):

  run_analysis(state)        → (failures: list, summary: str)
    Receives the full cluster snapshot and returns a structured JSON
    failure list with severity classification + 2-3 sentence summary.

  run_resolution(failures)   → resolutions: list
    Receives only the failures list and returns runbook-quality
    remediation steps for each failure. Only invoked when failures exist.

Design decisions:
  - temperature=0 for deterministic, reproducible JSON output
  - Retry on Groq rate-limit / transient errors via tenacity
  - Output is always valid JSON — enforced by output parser + fallback
  - Snapshot is pre-filtered to UNHEALTHY items only before sending (~80% token reduction)
  - Both chains use a structured system prompt + user prompt pattern
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from agent.config import get_settings
from agent.logger import get_logger
from agent.state import ClusterState

log = get_logger(__name__)
cfg = get_settings()


# ──────────────────────────────────────────────────────────────────────────────
# LLM client (singleton)
# ──────────────────────────────────────────────────────────────────────────────

def _get_llm() -> ChatGroq:
    """Return a configured ChatGroq instance."""
    return ChatGroq(
        api_key=cfg.groq_api_key,
        model=cfg.llm_model,
        temperature=cfg.llm_temperature,
        max_tokens=cfg.llm_max_tokens,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Unhealthy-only filters — one function per resource type
# ──────────────────────────────────────────────────────────────────────────────

def _is_node_unhealthy(n: Dict[str, Any]) -> bool:
    """Return True if the node has any problem condition."""
    if "error" in n:
        return True
    return (
        not n.get("ready", True)
        or n.get("disk_pressure", False)
        or n.get("memory_pressure", False)
        or n.get("pid_pressure", False)
        or n.get("network_unavailable", False)
    )


def _is_operator_unhealthy(op: Dict[str, Any]) -> bool:
    """Return True if the operator is degraded, unavailable, or stuck progressing."""
    if "error" in op:
        return True
    return (
        not op.get("available", True)
        or op.get("degraded", False)
        or op.get("progressing", False)
    )


def _is_pod_unhealthy(pod: Dict[str, Any]) -> bool:
    """Return True if the pod phase is abnormal or any container is restarting / errored."""
    if "error" in pod:
        return True
    bad_phases = {"Failed", "Unknown", "Pending"}
    if pod.get("phase") in bad_phases:
        return True
    for c in pod.get("containers") or []:
        reason = c.get("reason", "")
        restart_count = c.get("restart_count", 0) or 0
        if reason in {"CrashLoopBackOff", "OOMKilled", "Error", "ImagePullBackOff", "ErrImagePull"}:
            return True
        if restart_count > 5:
            return True
    return False


def _is_pvc_unhealthy(pvc: Dict[str, Any]) -> bool:
    """Return True if the PVC is not bound."""
    if "error" in pvc:
        return True
    return pvc.get("phase", "Bound") != "Bound"


def _is_mcpool_unhealthy(mcp: Dict[str, Any]) -> bool:
    """Return True if the MachineConfigPool is degraded or updating."""
    if "error" in mcp:
        return True
    return mcp.get("degraded", False) or mcp.get("updating", False)


def _is_cert_unhealthy(cert: Dict[str, Any]) -> bool:
    """Return True if the cert is expiring within 30 days or already expired."""
    if "error" in cert:
        return True
    days = cert.get("days_remaining")
    if days is None:
        return False
    return days < 30


def _is_endpoint_unhealthy(ep: Dict[str, Any]) -> bool:
    """Return True if the CP4I endpoint returned a non-2xx status."""
    if "error" in ep:
        return True
    status = ep.get("status_code", 200)
    return status is None or status >= 400


def _is_etcd_unhealthy(etcd: Dict[str, Any]) -> bool:
    """Return True if etcd has any unhealthy members or errors."""
    if not etcd or "error" in etcd:
        return bool(etcd)
    members = etcd.get("members") or []
    return any(
        not m.get("healthy", True) for m in members
    ) or etcd.get("alarm_count", 0) > 0


# ──────────────────────────────────────────────────────────────────────────────
# Snapshot builder — unhealthy items only
# ──────────────────────────────────────────────────────────────────────────────

def _trim_snapshot(state: ClusterState) -> Dict[str, Any]:
    """
    Build a concise snapshot from ClusterState for the analysis prompt.

    KEY CHANGE: Only UNHEALTHY resources are included in each section.
    Healthy items are counted and reported as a single integer so the LLM
    knows they exist but doesn't waste tokens on them.

    This typically reduces payload size by ~80 % on a healthy cluster and
    still surfaces every problem on a degraded one.
    """
    def _trim_str(s: str, max_len: int = 200) -> str:
        return s[:max_len] + "..." if len(s) > max_len else s

    # ── Nodes ────────────────────────────────────────────────────────────────
    all_nodes = state.get("nodes", [])
    unhealthy_nodes = []
    for n in all_nodes:
        if _is_node_unhealthy(n):
            if "error" in n:
                unhealthy_nodes.append(n)
            else:
                unhealthy_nodes.append({
                    "name":               n.get("name"),
                    "role":               n.get("role"),
                    "ready":              n.get("ready"),
                    "disk_pressure":      n.get("disk_pressure"),
                    "memory_pressure":    n.get("memory_pressure"),
                    "pid_pressure":       n.get("pid_pressure"),
                    "network_unavailable": n.get("network_unavailable"),
                })
    healthy_node_count = len(all_nodes) - len(unhealthy_nodes)

    # ── Operators ────────────────────────────────────────────────────────────
    all_operators = state.get("operators", [])
    unhealthy_operators = []
    for op in all_operators:
        if _is_operator_unhealthy(op):
            if "error" in op:
                unhealthy_operators.append(op)
            else:
                unhealthy_operators.append({
                    "name":                op.get("name"),
                    "available":           op.get("available"),
                    "degraded":            op.get("degraded"),
                    "progressing":         op.get("progressing"),
                    "degraded_message":    _trim_str(op.get("degraded_message", "")),
                    "progressing_message": _trim_str(op.get("progressing_message", "")),
                })
    healthy_operator_count = len(all_operators) - len(unhealthy_operators)

    # ── Pods ─────────────────────────────────────────────────────────────────
    all_pods = state.get("pods", [])
    unhealthy_pods = []
    for pod in all_pods:
        if _is_pod_unhealthy(pod):
            if "error" in pod:
                unhealthy_pods.append(pod)
            else:
                unhealthy_pods.append({
                    "name":      pod.get("name"),
                    "namespace": pod.get("namespace"),
                    "phase":     pod.get("phase"),
                    "containers": [
                        {
                            "name":          c.get("name"),
                            "reason":        c.get("reason"),
                            "restart_count": c.get("restart_count"),
                            "message":       _trim_str(c.get("message", ""), 150),
                        }
                        for c in (pod.get("containers") or [])
                    ],
                })
    healthy_pod_count = len(all_pods) - len(unhealthy_pods)

    # ── PVCs ─────────────────────────────────────────────────────────────────
    all_pvcs = state.get("pvcs", [])
    unhealthy_pvcs = [p for p in all_pvcs if _is_pvc_unhealthy(p)]
    healthy_pvc_count = len(all_pvcs) - len(unhealthy_pvcs)

    # ── MachineConfigPools ────────────────────────────────────────────────────
    all_mcpools = state.get("mcpools", [])
    unhealthy_mcpools = [m for m in all_mcpools if _is_mcpool_unhealthy(m)]
    healthy_mcp_count = len(all_mcpools) - len(unhealthy_mcpools)

    # ── Certificates ─────────────────────────────────────────────────────────
    all_certs = state.get("certs", [])
    unhealthy_certs = [c for c in all_certs if _is_cert_unhealthy(c)]
    healthy_cert_count = len(all_certs) - len(unhealthy_certs)

    # ── CP4I Endpoints ────────────────────────────────────────────────────────
    all_endpoints = state.get("cp4i_endpoints", [])
    unhealthy_endpoints = [e for e in all_endpoints if _is_endpoint_unhealthy(e)]
    healthy_endpoint_count = len(all_endpoints) - len(unhealthy_endpoints)

    # ── etcd ─────────────────────────────────────────────────────────────────
    etcd = state.get("etcd", {})
    etcd_payload = etcd if _is_etcd_unhealthy(etcd) else {"status": "healthy"}

    # ── Assemble ──────────────────────────────────────────────────────────────
    snapshot = {
        "cluster_name":      state.get("cluster_name", cfg.cluster_name),
        "timestamp":         state.get("timestamp", ""),
        "collection_errors": state.get("collection_errors", {}),

        # Healthy summaries (counts only — no token waste)
        "healthy_counts": {
            "nodes":      healthy_node_count,
            "operators":  healthy_operator_count,
            "pods":       healthy_pod_count,
            "pvcs":       healthy_pvc_count,
            "mcpools":    healthy_mcp_count,
            "certs":      healthy_cert_count,
            "endpoints":  healthy_endpoint_count,
        },

        # Unhealthy details (full data)
        "unhealthy_nodes":     unhealthy_nodes,
        "unhealthy_operators": unhealthy_operators,
        "unhealthy_pods":      unhealthy_pods,
        "unhealthy_pvcs":      unhealthy_pvcs,
        "unhealthy_mcpools":   unhealthy_mcpools,
        "unhealthy_certs":     unhealthy_certs,
        "unhealthy_endpoints": unhealthy_endpoints,
        "etcd":                etcd_payload,
    }

    return snapshot


# ──────────────────────────────────────────────────────────────────────────────
# JSON extraction helper
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Dict[str, Any]:
    """
    Extract and parse JSON from an LLM response string.

    Handles both:
      - Raw JSON responses
      - Responses wrapped in ```json ... ``` code fences
    """
    # Strip markdown code fences if present
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        text = match.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        log.error("json_parse_failed", error=str(exc), raw_preview=text[:200])
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc


# ──────────────────────────────────────────────────────────────────────────────
# Chain 1: Analysis
# ──────────────────────────────────────────────────────────────────────────────

_ANALYSIS_SYSTEM = """You are a senior OpenShift / Kubernetes Site Reliability Engineer (SRE) with production experience.

You will be given a JSON snapshot of a production OpenShift cluster's health telemetry.

NOTE: The snapshot contains ONLY unhealthy resources. Healthy resources are summarised
as counts in the "healthy_counts" field — do NOT report them as failures.

Your job is to:
1. Detect all failures
2. Classify severity correctly
3. Provide consistent, structured output

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT (STRICT JSON ONLY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "failures": [
    {
      "id": "F-001",
      "component": "<nodes|operators|mcpools|etcd|pvcs|pods|certs|cp4i>",
      "resource_name": "<specific resource name>",
      "severity": "<CRITICAL|WARNING|INFO>",
      "message": "<clear, concise technical issue>",
      "detected_at": "<ISO-8601 UTC timestamp>"
    }
  ],
  "summary": "<2-3 sentences describing overall cluster health>",
  "root_cause": "<main underlying issue across failures>",
  "impact": "<business or system impact>"
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STRICT RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Output ONLY valid JSON (no markdown, no explanation).
2. Do NOT hallucinate — only use given data.
3. Always include detected_at timestamps.
4. Keep messages short, technical, and precise.
5. Generate consistent IDs: F-001, F-002, etc.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SEVERITY RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CRITICAL:
- Node NotReady
- etcd unhealthy
- Operator degraded/unavailable
- Pod CrashLoopBackOff
- Endpoint down (5xx)
- Missing telemetry (collection_errors)

WARNING:
- PVC Pending
- Pod restarts > 5
- Cert expiring < 14 days
- MCP degraded/updating

INFO:
- Cert expiring 14–30 days
- Minor config drift

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SMART ANALYSIS EXPECTATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Correlate issues when possible (e.g., etcd → node instability)
- Avoid duplicate failures for same issue
- Prefer meaningful failures over raw data dumps
- Summarize intelligently (not just list problems)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HEALTHY CASE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

If no issues:
{
  "failures": [],
  "summary": "All cluster components are healthy.",
  "root_cause": "None",
  "impact": "No impact"
}
"""

_ANALYSIS_USER = """Analyse this OpenShift cluster snapshot and return the JSON failure report:

{snapshot}"""


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _invoke_analysis_chain(snapshot_json: str) -> str:
    """Invoke the analysis LLM chain with retry on transient errors."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=_ANALYSIS_SYSTEM),
        HumanMessage(content=_ANALYSIS_USER.format(snapshot=snapshot_json)),
    ]
    response = llm.invoke(messages)
    return response.content


def run_analysis(state: ClusterState) -> Tuple[List[Dict], str]:
    log.info("llm_analysis_start", model=cfg.llm_model)
    try:
        snapshot = _trim_snapshot(state)

        # Log how much was filtered out vs sent
        total_unhealthy = sum(
            len(v) for k, v in snapshot.items()
            if k.startswith("unhealthy_") and isinstance(v, list)
        )
        total_healthy = sum(snapshot.get("healthy_counts", {}).values())
        log.info(
            "llm_analysis_filter",
            healthy_skipped=total_healthy,
            unhealthy_sent=total_unhealthy,
        )

        snapshot_json = json.dumps(snapshot, indent=2, default=str)
        log.debug("llm_analysis_payload_size", chars=len(snapshot_json))

        raw_response = _invoke_analysis_chain(snapshot_json)
        log.debug("llm_analysis_raw_response", preview=raw_response[:200])

        parsed = _extract_json(raw_response)

        failures = parsed.get("failures", [])
        summary = parsed.get("summary", "")

        # Add detected_at if missing
        now = datetime.now(timezone.utc).isoformat()
        for f in failures:
            if not f.get("detected_at"):
                f["detected_at"] = now

        log.info(
            "llm_analysis_done",
            failures=len(failures),
            summary=summary[:80],
        )

        return failures, summary

    except Exception as exc:
        log.error("llm_analysis_failed", error=str(exc))
        return [], f"LLM analysis failed: {str(exc)}"


# ──────────────────────────────────────────────────────────────────────────────
# Chain 2: Resolution
# ──────────────────────────────────────────────────────────────────────────────

_RESOLUTION_SYSTEM = """You are a senior DevOps SRE.

You are given a list of cluster failures.

For EACH failure, generate:

1. Root cause (short)
2. Step-by-step fix (practical steps)
3. Exact kubectl/oc commands

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT (STRICT JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "solutions": [
    {
      "id": "F-001",
      "issue": "<short description>",
      "root_cause": "<why this happened>",
      "steps": [
        "Step 1",
        "Step 2"
      ],
      "commands": [
        "kubectl ...",
        "oc ..."
      ]
    }
  ]
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Output ONLY JSON
- No explanations outside JSON
- Commands must be real and executable
- Prefer safe commands (read logs before restart)
- Match IDs with failures

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXAMPLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CrashLoopBackOff:
- Check logs
- Fix config
- Restart deployment

Node NotReady:
- Check kubelet
- Restart node service

PVC Pending:
- Check storage class
- Verify PV binding
"""

_RESOLUTION_USER = """Generate runbook remediation for these OpenShift failures:

{failures_json}"""


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _invoke_resolution_chain(failures_json: str) -> str:
    """Invoke the resolution LLM chain with retry on transient errors."""
    llm = _get_llm()
    messages = [
        SystemMessage(content=_RESOLUTION_SYSTEM),
        HumanMessage(content=_RESOLUTION_USER.format(failures_json=failures_json)),
    ]
    response = llm.invoke(messages)
    return response.content


def run_resolution(failures: List[Dict]) -> List[Dict]:
    """
    Generate runbook-quality remediation steps for a list of failures.

    Args:
        failures: List of failure dicts from run_analysis().

    Returns:
        List of resolution dicts, one per failure.
    """
    if not failures:
        return []

    log.info("llm_resolution_start", failure_count=len(failures), model=cfg.llm_model)

    try:
        failures_json = json.dumps(failures, indent=2, default=str)

        raw_response = _invoke_resolution_chain(failures_json)
        log.debug("llm_resolution_raw_response", preview=raw_response[:200])

        parsed = _extract_json(raw_response)

        if isinstance(parsed, dict):
            resolutions = parsed.get("solutions") or parsed.get("resolutions") or []
        else:
            resolutions = parsed

        if not isinstance(resolutions, list):
            log.warning("llm_resolution_invalid_format")
            resolutions = []

        failure_map = {f.get("id"): f for f in failures}

        enriched = []
        for r in resolutions:
            fid = r.get("id") or r.get("failure_id")
            failure = failure_map.get(fid, {})
            enriched.append({
                "failure_id": fid,
                "issue":      r.get("issue", failure.get("message", "")),
                "severity":   failure.get("severity", "UNKNOWN"),
                "root_cause": r.get("root_cause", "Unknown"),
                "steps":      r.get("steps", []),
                "commands":   r.get("commands", []),
                "resource":   failure.get("resource_name", ""),
                "component":  failure.get("component", ""),
            })

        log.info("llm_resolution_done", resolution_count=len(enriched))
        return enriched

    except Exception as exc:
        log.error("llm_resolution_failed", error=str(exc))

        fallback = []
        for f in failures:
            fallback.append({
                "failure_id": f.get("id", ""),
                "issue":      f.get("message", ""),
                "severity":   f.get("severity", "UNKNOWN"),
                "root_cause": "LLM resolution failed.",
                "steps": [
                    "Check logs for detailed error",
                    "Verify configuration",
                    "Restart affected component",
                ],
                "commands": [
                    f"oc describe {f.get('component', 'pod')} {f.get('resource_name', '')}",
                    f"oc logs {f.get('resource_name', '')}",
                ],
                "resource":   f.get("resource_name", ""),
                "component":  f.get("component", ""),
            })

        return fallback
