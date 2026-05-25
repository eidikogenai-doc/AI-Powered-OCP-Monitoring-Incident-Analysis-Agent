"""
reporter.py — HTML report builder for the OCP AI Monitoring Agent.

Converts a fully-populated ClusterState into a styled, self-contained HTML
email body. The report is designed to be readable both in email clients and
in a browser (dashboard embed).

Report sections (always rendered, even when healthy):
  1. Header          — Cluster name, status badge, cycle timestamp, LLM summary
  2. Nodes           — Ready status, disk/memory/PID pressure, color-coded rows
  3. Cluster Operators — Available / Degraded / Progressing with message excerpts
  4. MachineConfigPools — Machine counts: total, updated, ready, unavailable, degraded
  5. etcd Health     — Member count, per-endpoint health
  6. PVCs            — Pending / Lost PVCs (empty section shown when none)
  7. Failing Pods    — CrashLoopBackOff / OOMKilled / Error pods across system namespaces
  8. TLS Certificates — Expiring within 30 days with days-remaining badge
  9. CP4I Endpoints  — HTTP health-check results per endpoint
 10. Failures & Resolutions — LLM failures with severity badge, root cause,
                              ordered steps, copy-paste oc commands, docs link
 11. RAG Panel       — Similar historical incidents per failure (when available)
 12. Footer          — Run metadata, generation timestamp

Design decisions:
  - Fully inline CSS — no external stylesheets; works in Gmail / Outlook
  - No JavaScript — pure HTML tables; safe for all email clients
  - Color palette: green=#2E7D32, amber=#E65100, red=#C62828, blue=#1565C0
  - All sections render even when empty so the report shape is predictable
  - build_html_report(state) is the only public function
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent.config import get_settings
from agent.logger import get_logger
from agent.state import ClusterState

log = get_logger(__name__)
cfg = get_settings()


# ──────────────────────────────────────────────────────────────────────────────
# Colour / style constants
# ──────────────────────────────────────────────────────────────────────────────

_C = {
    "green":       "#2E7D32",
    "green_bg":    "#E8F5E9",
    "amber":       "#E65100",
    "amber_bg":    "#FFF3E0",
    "red":         "#C62828",
    "red_bg":      "#FFEBEE",
    "blue":        "#1565C0",
    "blue_bg":     "#E3F2FD",
    "grey":        "#616161",
    "grey_bg":     "#F5F5F5",
    "header_bg":   "#1A237E",
    "border":      "#CFD8DC",
    "white":       "#FFFFFF",
    "text":        "#212121",
    "subtext":     "#757575",
}

_FONT = "font-family: Arial, Helvetica, sans-serif;"
_BASE = f"margin:0;padding:0;{_FONT}color:{_C['text']};"


# ──────────────────────────────────────────────────────────────────────────────
# Low-level HTML helpers
# ──────────────────────────────────────────────────────────────────────────────

def _e(text: Any) -> str:
    """HTML-escape a value safely."""
    return html.escape(str(text)) if text is not None else ""


def _badge(label: str, color: str, bg: str) -> str:
    style = (
        f"display:inline-block;padding:2px 10px;border-radius:12px;"
        f"background:{bg};color:{color};font-weight:bold;"
        f"font-size:12px;{_FONT}"
    )
    return f'<span style="{style}">{_e(label)}</span>'


def _severity_badge(severity: str) -> str:
    s = severity.upper()
    if s == "CRITICAL":
        return _badge("● CRITICAL", _C["red"], _C["red_bg"])
    if s == "WARNING":
        return _badge("▲ WARNING", _C["amber"], _C["amber_bg"])
    return _badge("ℹ INFO", _C["blue"], _C["blue_bg"])


def _status_badge(ok: bool, true_label: str = "OK", false_label: str = "FAIL") -> str:
    if ok:
        return _badge(f"✔ {true_label}", _C["green"], _C["green_bg"])
    return _badge(f"✘ {false_label}", _C["red"], _C["red_bg"])


def _bool_cell(val: Any, invert: bool = False) -> str:
    """
    Render a table cell with a coloured indicator.
    invert=True means True is bad (e.g. disk_pressure=True → red).
    """
    is_true = bool(val)
    good = (not is_true) if invert else is_true
    color = _C["green"] if good else _C["red"]
    symbol = "✔" if good else "✘"
    label = str(val) if val is not None else "—"
    return f'<td style="text-align:center;color:{color};font-weight:bold;">{symbol} {_e(label)}</td>'


def _section(title: str, content: str, icon: str = "") -> str:
    return f"""
<div style="margin-bottom:28px;">
  <h2 style="{_FONT}font-size:16px;font-weight:bold;color:{_C['header_bg']};
             border-bottom:2px solid {_C['header_bg']};padding-bottom:6px;
             margin-bottom:12px;">
    {icon + ' ' if icon else ''}{_e(title)}
  </h2>
  {content}
</div>"""


def _table(headers: List[str], rows: List[List[str]], col_widths: Optional[List[str]] = None) -> str:
    th_style = (
        f"background:{_C['header_bg']};color:{_C['white']};"
        f"padding:8px 12px;text-align:left;{_FONT}font-size:13px;"
    )
    td_style = f"padding:7px 12px;border-bottom:1px solid {_C['border']};{_FONT}font-size:13px;"

    header_html = "".join(
        f'<th style="{th_style}{"width:"+w+";" if col_widths and i < len(col_widths) else ""}">{_e(h)}</th>'
        for i, (h, w) in enumerate(zip(headers, col_widths or [""]*len(headers)))
    )

    rows_html = ""
    for i, row in enumerate(rows):
        row_bg = _C["grey_bg"] if i % 2 == 0 else _C["white"]
        cells = ""
        for cell in row:
            # cells that are pre-rendered HTML (badges) are passed as-is
            if isinstance(cell, str) and ("<span" in cell or "<td" in cell or "<code" in cell):
                if cell.startswith("<td"):
                    cells += cell
                else:
                    cells += f'<td style="{td_style}">{cell}</td>'
            else:
                cells += f'<td style="{td_style}">{_e(cell) if cell is not None else "—"}</td>'
        rows_html += f'<tr style="background:{row_bg};">{cells}</tr>'

    return f"""
<table style="width:100%;border-collapse:collapse;border:1px solid {_C['border']};margin-bottom:8px;">
  <thead><tr>{header_html}</tr></thead>
  <tbody>{rows_html}</tbody>
</table>"""


def _empty_notice(message: str = "No issues detected.") -> str:
    return (
        f'<p style="{_FONT}font-size:13px;color:{_C["green"]};'
        f'padding:10px;background:{_C["green_bg"]};'
        f'border-radius:4px;">✔ {_e(message)}</p>'
    )


def _code_block(commands: List[str]) -> str:
    if not commands:
        return ""
    lines = "\n".join(_e(c) for c in commands)
    return (
        f'<pre style="background:#263238;color:#ECEFF1;padding:12px;'
        f'border-radius:4px;font-size:12px;overflow-x:auto;'
        f'font-family:\'Courier New\',monospace;margin:8px 0;">'
        f'{lines}</pre>'
    )


# ──────────────────────────────────────────────────────────────────────────────
# Section builders
# ──────────────────────────────────────────────────────────────────────────────

def _build_header(state: ClusterState) -> str:
    failures = state.get("failures", [])
    severities = {f.get("severity", "").upper() for f in failures}
    cluster = _e(state.get("cluster_name", cfg.cluster_name))
    timestamp = _e(state.get("timestamp", "")[:19].replace("T", " ") + " UTC")
    collected_at = state.get("collected_at", "")
    summary = _e(state.get("summary", "No summary available."))
    run_id = _e(state.get("run_id", "—"))

    if "CRITICAL" in severities:
        status_label, status_color, status_bg = "🔴 CRITICAL", _C["red"], _C["red_bg"]
    elif "WARNING" in severities or failures:
        status_label, status_color, status_bg = "🟡 WARNING", _C["amber"], _C["amber_bg"]
    else:
        status_label, status_color, status_bg = "🟢 HEALTHY", _C["green"], _C["green_bg"]

    collection_note = ""
    errors = state.get("collection_errors", {})
    if errors:
        err_list = ", ".join(_e(k) for k in errors.keys())
        collection_note = (
            f'<p style="{_FONT}font-size:12px;color:{_C["red"]};margin-top:6px;">'
            f'⚠ Collection errors in: {err_list}</p>'
        )

    return f"""
<div style="background:{_C['header_bg']};padding:24px 28px;border-radius:6px 6px 0 0;margin-bottom:0;">
  <table style="width:100%;border-collapse:collapse;">
    <tr>
      <td style="vertical-align:top;">
        <div style="color:{_C['white']};font-size:22px;font-weight:bold;{_FONT}">
          OpenShift Cluster Health Report
        </div>
        <div style="color:#90CAF9;font-size:14px;margin-top:4px;{_FONT}">
          {cluster} &nbsp;|&nbsp; {timestamp}
        </div>
        {f'<div style="color:#B0BEC5;font-size:12px;margin-top:2px;{_FONT}">Run ID: {run_id}</div>' if run_id != '—' else ''}
      </td>
      <td style="text-align:right;vertical-align:top;">
        <div style="background:{status_bg};color:{status_color};
                    font-size:18px;font-weight:bold;padding:10px 20px;
                    border-radius:6px;{_FONT}display:inline-block;">
          {status_label}
        </div>
        <div style="color:#B0BEC5;font-size:12px;margin-top:6px;{_FONT}">
          {len(failures)} failure(s) detected
        </div>
      </td>
    </tr>
  </table>
</div>
<div style="background:#E8EAF6;padding:14px 28px;border-left:4px solid {_C['header_bg']};
            margin-bottom:24px;">
  <p style="{_FONT}font-size:14px;color:{_C['text']};margin:0;line-height:1.6;">
    <strong>LLM Summary:</strong> {summary}
  </p>
  {collection_note}
</div>"""


def _build_nodes_section(state: ClusterState) -> str:
    nodes = state.get("nodes", [])
    if not nodes or (len(nodes) == 1 and "error" in nodes[0]):
        err = nodes[0].get("error", "Unknown") if nodes else "No data"
        return _section("Cluster Nodes", f'<p style="color:{_C["red"]};">⚠ Collection error: {_e(err)}</p>', "🖥️")

    headers = ["Node Name", "Role", "Ready", "Disk Pressure", "Memory Pressure", "PID Pressure", "Network"]
    rows = []
    for n in nodes:
        ready = n.get("ready", False)
        rows.append([
            n.get("name", "—"),
            n.get("role", "—"),
            _status_badge(ready, "Ready", "NotReady"),
            _bool_cell(n.get("disk_pressure", False), invert=True),
            _bool_cell(n.get("memory_pressure", False), invert=True),
            _bool_cell(n.get("pid_pressure", False), invert=True),
            _bool_cell(not n.get("network_unavailable", False), invert=False),
        ])

    healthy = sum(1 for n in nodes if n.get("ready") and not any([
        n.get("disk_pressure"), n.get("memory_pressure"), n.get("pid_pressure"), n.get("network_unavailable")
    ]))
    summary_line = (
        f'<p style="{_FONT}font-size:13px;color:{_C["subtext"]};margin-bottom:8px;">'
        f'{healthy}/{len(nodes)} nodes fully healthy</p>'
    )
    return _section("Cluster Nodes", summary_line + _table(headers, rows), "🖥️")


def _build_operators_section(state: ClusterState) -> str:
    operators = state.get("operators", [])
    if not operators or (len(operators) == 1 and "error" in operators[0]):
        err = operators[0].get("error", "Unknown") if operators else "No data"
        return _section("Cluster Operators", f'<p style="color:{_C["red"]};">⚠ Collection error: {_e(err)}</p>', "⚙️")

    headers = ["Operator Name", "Available", "Degraded", "Progressing", "Message"]
    rows = []
    for op in operators:
        available = op.get("available", False)
        degraded  = op.get("degraded", False)
        progressing = op.get("progressing", False)
        msg = op.get("degraded_message") or op.get("progressing_message") or ""
        msg_short = (msg[:120] + "…") if len(msg) > 120 else msg
        rows.append([
            op.get("name", "—"),
            _status_badge(available, "Yes", "No"),
            _status_badge(not degraded, "No", "Yes"),
            _badge("Yes", _C["amber"], _C["amber_bg"]) if progressing else _badge("No", _C["green"], _C["green_bg"]),
            f'<span style="font-size:12px;color:{_C["subtext"]};">{_e(msg_short)}</span>' if msg_short else "—",
        ])

    degraded_count = sum(1 for op in operators if op.get("degraded") or not op.get("available"))
    notice = ""
    if degraded_count == 0:
        notice = _empty_notice(f"All {len(operators)} operators available and healthy.")
    return _section("Cluster Operators", notice + _table(headers, rows), "⚙️")


def _build_mcpools_section(state: ClusterState) -> str:
    mcpools = state.get("mcpools", [])
    if not mcpools or (len(mcpools) == 1 and "error" in mcpools[0]):
        err = mcpools[0].get("error", "Unknown") if mcpools else "No data"
        return _section("MachineConfigPools", f'<p style="color:{_C["red"]};">⚠ Collection error: {_e(err)}</p>', "🔧")

    headers = ["Pool Name", "Machine Count", "Ready", "Updated", "Unavailable", "Degraded", "Status"]
    rows = []
    for pool in mcpools:
        total    = pool.get("machine_count", pool.get("machineCount", "—"))
        ready    = pool.get("ready_machine_count", pool.get("readyMachineCount", "—"))
        updated  = pool.get("updated_machine_count", pool.get("updatedMachineCount", "—"))
        unavail  = pool.get("unavailable_machine_count", pool.get("unavailableMachineCount", 0))
        degraded = pool.get("degraded_machine_count", pool.get("degradedMachineCount", 0))
        is_ok = (int(unavail) == 0 and int(degraded) == 0) if str(unavail).isdigit() and str(degraded).isdigit() else True
        rows.append([
            pool.get("name", "—"),
            str(total),
            str(ready),
            str(updated),
            _badge(str(unavail), _C["red"], _C["red_bg"]) if str(unavail) not in ("0", "—") else str(unavail),
            _badge(str(degraded), _C["red"], _C["red_bg"]) if str(degraded) not in ("0", "—") else str(degraded),
            _status_badge(is_ok, "Healthy", "Degraded"),
        ])
    return _section("MachineConfigPools", _table(headers, rows), "🔧")


def _build_etcd_section(state: ClusterState) -> str:
    etcd = state.get("etcd", {})
    if not etcd or "error" in etcd:
        err = etcd.get("error", "No data") if etcd else "No data"
        return _section("etcd Health", f'<p style="color:{_C["red"]};">⚠ Collection error: {_e(err)}</p>', "💾")

    healthy     = etcd.get("healthy", False)
    member_count = etcd.get("member_count", "—")
    endpoints   = etcd.get("endpoints", [])

    summary_html = f"""
<table style="border-collapse:collapse;margin-bottom:12px;">
  <tr>
    <td style="padding:6px 16px 6px 0;{_FONT}font-size:13px;font-weight:bold;">Overall Health:</td>
    <td style="padding:6px 0;">{_status_badge(healthy, "Healthy", "Unhealthy")}</td>
  </tr>
  <tr>
    <td style="padding:6px 16px 6px 0;{_FONT}font-size:13px;font-weight:bold;">Member Count:</td>
    <td style="padding:6px 0;{_FONT}font-size:13px;">{_e(member_count)}</td>
  </tr>
</table>"""

    if endpoints:
        ep_headers = ["Endpoint", "Health", "Message"]
        ep_rows = []
        for ep in endpoints:
            ep_ok = ep.get("healthy", False)
            ep_rows.append([
                ep.get("endpoint", ep.get("name", "—")),
                _status_badge(ep_ok, "Healthy", "Unhealthy"),
                ep.get("message", ep.get("error", "—")),
            ])
        summary_html += _table(ep_headers, ep_rows)

    return _section("etcd Health", summary_html, "💾")


def _build_pvcs_section(state: ClusterState) -> str:
    pvcs = state.get("pvcs", [])
    if not pvcs:
        return _section("Persistent Volume Claims", _empty_notice("No Pending or Lost PVCs detected."), "💿")
    if len(pvcs) == 1 and "error" in pvcs[0]:
        return _section("Persistent Volume Claims", f'<p style="color:{_C["red"]};">⚠ {_e(pvcs[0]["error"])}</p>', "💿")

    headers = ["PVC Name", "Namespace", "Phase", "Storage Class", "Capacity"]
    rows = []
    for pvc in pvcs:
        phase = pvc.get("phase", "—")
        phase_badge = _badge(phase, _C["red"], _C["red_bg"]) if phase in ("Pending", "Lost") else phase
        rows.append([
            pvc.get("name", "—"),
            pvc.get("namespace", "—"),
            phase_badge,
            pvc.get("storage_class", pvc.get("storageClass", "—")),
            pvc.get("capacity", "—"),
        ])
    return _section("Persistent Volume Claims", _table(headers, rows), "💿")


def _build_pods_section(state: ClusterState) -> str:
    pods = state.get("pods", [])
    if not pods:
        return _section("Failing Pods", _empty_notice("No failing pods in monitored namespaces."), "📦")
    if len(pods) == 1 and "error" in pods[0]:
        return _section("Failing Pods", f'<p style="color:{_C["red"]};">⚠ {_e(pods[0]["error"])}</p>', "📦")

    headers = ["Pod Name", "Namespace", "Phase", "Container", "Reason", "Restarts", "Message"]
    rows = []
    for pod in pods:
        containers = pod.get("containers") or []
        if not containers:
            rows.append([
                pod.get("name", "—"), pod.get("namespace", "—"),
                pod.get("phase", "—"), "—", "—", "—", "—",
            ])
        for c in containers:
            reason = c.get("reason", "—")
            restart = c.get("restart_count", 0)
            msg = c.get("message", "")
            msg_short = (msg[:100] + "…") if len(msg) > 100 else msg
            restart_badge = (
                _badge(str(restart), _C["red"], _C["red_bg"]) if int(restart or 0) > 5
                else str(restart)
            )
            rows.append([
                pod.get("name", "—"),
                pod.get("namespace", "—"),
                pod.get("phase", "—"),
                c.get("name", "—"),
                _badge(reason, _C["amber"], _C["amber_bg"]) if reason not in ("—", None) else "—",
                restart_badge,
                f'<span style="font-size:12px;color:{_C["subtext"]};">{_e(msg_short)}</span>',
            ])
    return _section("Failing Pods", _table(headers, rows), "📦")


def _build_certs_section(state: ClusterState) -> str:
    certs = state.get("certs", [])
    if not certs:
        return _section("TLS Certificates", _empty_notice("No certificates expiring within 30 days."), "🔒")
    if len(certs) == 1 and "error" in certs[0]:
        return _section("TLS Certificates", f'<p style="color:{_C["red"]};">⚠ {_e(certs[0]["error"])}</p>', "🔒")

    headers = ["Secret Name", "Namespace", "Common Name", "Expires At", "Days Remaining"]
    rows = []
    for cert in certs:
        days = cert.get("days_remaining", cert.get("daysRemaining"))
        try:
            days_int = int(days)
            if days_int <= 7:
                days_badge = _badge(f"{days_int}d", _C["red"], _C["red_bg"])
            elif days_int <= 14:
                days_badge = _badge(f"{days_int}d", _C["amber"], _C["amber_bg"])
            else:
                days_badge = _badge(f"{days_int}d", _C["blue"], _C["blue_bg"])
        except (TypeError, ValueError):
            days_badge = str(days) if days is not None else "—"

        rows.append([
            cert.get("name", cert.get("secret_name", "—")),
            cert.get("namespace", "—"),
            cert.get("common_name", cert.get("commonName", "—")),
            cert.get("expires_at", cert.get("expiry", "—")),
            days_badge,
        ])
    return _section("TLS Certificates", _table(headers, rows), "🔒")


def _build_cp4i_section(state: ClusterState) -> str:
    endpoints = state.get("cp4i_endpoints", [])
    if not endpoints:
        return _section("CP4I Endpoints", _empty_notice("No CP4I health endpoints configured."), "🔗")
    if len(endpoints) == 1 and "error" in endpoints[0]:
        return _section("CP4I Endpoints", f'<p style="color:{_C["red"]};">⚠ {_e(endpoints[0]["error"])}</p>', "🔗")

    headers = ["Endpoint URL", "Status", "HTTP Code", "Response Time", "Message"]
    rows = []
    for ep in endpoints:
        ok = ep.get("healthy", False)
        http_code = ep.get("status_code", ep.get("http_code", "—"))
        resp_time = ep.get("response_time_ms", ep.get("responseTimeMs"))
        resp_str = f"{resp_time}ms" if resp_time is not None else "—"
        rows.append([
            ep.get("url", ep.get("endpoint", "—")),
            _status_badge(ok, "Healthy", "Unhealthy"),
            str(http_code),
            resp_str,
            ep.get("message", ep.get("error", "—")),
        ])

    healthy_count = sum(1 for ep in endpoints if ep.get("healthy"))
    notice = ""
    if healthy_count == len(endpoints):
        notice = _empty_notice(f"All {len(endpoints)} CP4I endpoints are healthy.")

    return _section("CP4I Endpoints", notice + _table(headers, rows), "🔗")


def _build_failures_section(state: ClusterState) -> str:
    failures   = state.get("failures", [])
    resolutions = state.get("resolutions", [])
    rag_results = state.get("rag_results", {})

    if not failures:
        return _section(
            "Failures & Resolutions",
            _empty_notice("No failures detected. Cluster is operating normally."),
            "🛡️"
        )

    # Map resolutions by failure_id for O(1) lookup
    res_map: Dict[str, Dict] = {}
    for r in resolutions:
        fid = r.get("failure_id", "")
        if fid:
            res_map[fid] = r

    cards = ""
    for f in failures:
        fid       = f.get("id", "")
        severity  = f.get("severity", "INFO")
        component = f.get("component", "—")
        resource  = f.get("resource_name", "—")
        message   = f.get("message", "—")
        detected  = f.get("detected_at", "—")

        sev_badge = _severity_badge(severity)
        res        = res_map.get(fid, {})
        root_cause = res.get("root_cause", "")
        steps      = res.get("steps", [])
        commands   = res.get("commands", [])
        docs_ref   = res.get("docs_ref", "")

        # Source badge — RAG or LLM
        source = res.get("source", "")
        rag_incident_ref = res.get("rag_incident", "")
        rag_score = res.get("rag_score")
        if source == "rag":
            score_str = f" ({round(float(rag_score)*100)}% match)" if rag_score else ""
            source_badge = (
                f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
                f'background:#E3F2FD;color:#1565C0;font-weight:bold;font-size:11px;{_FONT}">'
                f'⚡ FROM RAG{score_str} — {_e(rag_incident_ref)}</span>'
            )
        elif source == "llm":
            source_badge = (
                f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
                f'background:#F3E5F5;color:#6A1B9A;font-weight:bold;font-size:11px;{_FONT}">'
                f'🤖 FROM LLM</span>'
            )
        else:
            source_badge = ""

        # Numbered steps HTML
        steps_html = ""
        if steps:
            li_items = "".join(
                f'<li style="{_FONT}font-size:13px;margin-bottom:4px;line-height:1.5;">{_e(s)}</li>'
                for s in steps
            )
            steps_html = f'<ol style="margin:8px 0 8px 20px;padding:0;">{li_items}</ol>'

        docs_html = ""
        if docs_ref:
            docs_html = (
                f'<p style="{_FONT}font-size:12px;margin-top:6px;">'
                f'📖 <a href="{_e(docs_ref)}" style="color:{_C["blue"]};">{_e(docs_ref)}</a></p>'
            )

        # RAG similar incidents
        rag_html = ""
        similar = rag_results.get(fid, [])
        if similar:
            rag_items = ""
            for inc in similar[:3]:
                inc_id    = _e(inc.get("incident_id", inc.get("id", "—")))
                inc_title = _e(inc.get("title", "—"))
                inc_comp  = _e(inc.get("component", ""))
                rag_items += (
                    f'<div style="padding:6px 10px;border-left:3px solid {_C["blue"]};'
                    f'margin-bottom:6px;background:{_C["grey_bg"]};">'
                    f'<span style="{_FONT}font-size:12px;font-weight:bold;">{inc_id}</span> — '
                    f'<span style="{_FONT}font-size:12px;">{inc_title}</span>'
                    f'{f" <em>({inc_comp})</em>" if inc_comp else ""}'
                    f'</div>'
                )
            rag_html = (
                f'<div style="margin-top:10px;">'
                f'<div style="{_FONT}font-size:13px;font-weight:bold;color:{_C["blue"]};margin-bottom:6px;">'
                f'🔍 Similar Historical Incidents</div>'
                f'{rag_items}</div>'
            )

        border_color = _C["red"] if severity == "CRITICAL" else _C["amber"] if severity == "WARNING" else _C["blue"]
        cards += f"""
<div style="border:1px solid {border_color};border-left:5px solid {border_color};
            border-radius:4px;padding:16px;margin-bottom:16px;
            background:{_C['white']};">
  <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
    <tr>
      <td style="{_FONT}font-size:14px;font-weight:bold;">{_e(fid)} — {_e(component)} / {_e(resource)}</td>
      <td style="text-align:right;">{source_badge} &nbsp; {sev_badge}</td>
    </tr>
  </table>
  <p style="{_FONT}font-size:13px;margin:0 0 8px 0;color:{_C['text']};">{_e(message)}</p>
  <p style="{_FONT}font-size:11px;color:{_C['subtext']};margin:0 0 10px 0;">Detected: {_e(detected)}</p>
  {f'<div style="{_FONT}font-size:13px;font-weight:bold;margin-bottom:4px;">Root Cause</div><p style="{_FONT}font-size:13px;margin:0 0 10px 0;color:{_C["text"]};">{_e(root_cause)}</p>' if root_cause else ''}
  {f'<div style="{_FONT}font-size:13px;font-weight:bold;margin-bottom:4px;">Resolution Steps</div>{steps_html}' if steps else ''}
  {f'<div style="{_FONT}font-size:13px;font-weight:bold;margin-bottom:4px;">Commands</div>{_code_block(commands)}' if commands else ''}
  {docs_html}
  {rag_html}
</div>"""

    return _section("Failures & Resolutions", cards, "🛡️")


def _build_footer(state: ClusterState) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    cluster      = _e(state.get("cluster_name", cfg.cluster_name))
    run_id       = _e(state.get("run_id", "—"))
    failure_count = len(state.get("failures", []))
    email_recipients = ", ".join(_e(r) for r in cfg.email_recipients)

    return f"""
<div style="margin-top:32px;padding:16px 20px;background:{_C['grey_bg']};
            border-top:2px solid {_C['border']};border-radius:0 0 6px 6px;">
  <table style="width:100%;border-collapse:collapse;">
    <tr>
      <td style="{_FONT}font-size:11px;color:{_C['subtext']};">
        Generated by <strong>OCP AI Monitoring Agent</strong> &nbsp;|&nbsp;
        Cluster: {cluster} &nbsp;|&nbsp;
        Failures: {failure_count} &nbsp;|&nbsp;
        Run ID: {run_id}
      </td>
      <td style="text-align:right;{_FONT}font-size:11px;color:{_C['subtext']};">
        {generated_at}
      </td>
    </tr>
    <tr>
      <td colspan="2" style="{_FONT}font-size:11px;color:{_C['subtext']};padding-top:4px;">
        Recipients: {email_recipients} &nbsp;|&nbsp;
        Powered by LangGraph · LangChain · LlamaIndex · Groq
      </td>
    </tr>
  </table>
</div>"""


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def build_html_report(state: ClusterState) -> str:
    """
    Build a complete, self-contained HTML report from the full ClusterState.

    This is the only public function in this module. It is called by
    build_report_node() in nodes.py.

    Args:
        state: Fully-populated ClusterState after all pipeline nodes have run.

    Returns:
        A UTF-8 HTML string suitable for use as an email body or dashboard embed.

    Never raises — section-level exceptions are caught and rendered as error
    notices so the rest of the report still renders.
    """
    log.info("reporter_start", cluster=state.get("cluster_name"))

    def _safe(fn, label: str) -> str:
        try:
            return fn()
        except Exception as exc:
            log.error("reporter_section_failed", section=label, error=str(exc))
            return _section(label, f'<p style="color:{_C["red"]};">⚠ Report section failed: {_e(str(exc))}</p>')

    body = (
        _safe(lambda: _build_header(state),           "Header")
        + _safe(lambda: _build_nodes_section(state),      "Cluster Nodes")
        + _safe(lambda: _build_operators_section(state),  "Cluster Operators")
        + _safe(lambda: _build_mcpools_section(state),    "MachineConfigPools")
        + _safe(lambda: _build_etcd_section(state),       "etcd Health")
        + _safe(lambda: _build_pvcs_section(state),       "PVCs")
        + _safe(lambda: _build_pods_section(state),       "Failing Pods")
        + _safe(lambda: _build_certs_section(state),      "TLS Certificates")
        + _safe(lambda: _build_cp4i_section(state),       "CP4I Endpoints")
        + _safe(lambda: _build_failures_section(state),   "Failures & Resolutions")
        + _safe(lambda: _build_footer(state),             "Footer")
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>OCP Health Report — {_e(state.get("cluster_name", cfg.cluster_name))}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ {_BASE} background:#ECEFF1; }}
    a {{ color:{_C['blue']}; }}
  </style>
</head>
<body>
  <div style="max-width:900px;margin:20px auto;background:{_C['white']};
              border-radius:6px;box-shadow:0 2px 8px rgba(0,0,0,0.12);overflow:hidden;">
    <div style="padding:24px 28px;">
      {body}
    </div>
  </div>
</body>
</html>"""

    log.info(
        "reporter_done",
        cluster=state.get("cluster_name"),
        html_bytes=len(html_doc),
        sections=11,
    )
    return html_doc
