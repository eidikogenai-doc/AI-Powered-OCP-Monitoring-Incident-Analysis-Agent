"""
agent.py — LangGraph pipeline definition and single-cycle entry point.

Builds and compiles the StateGraph that wires all nodes together, then
exposes run_cycle() as the callable invoked by the scheduler every N minutes.

Pipeline topology
─────────────────
                         ┌─────────────────────────────────────────────────┐
                         │             PARALLEL COLLECTION FAN-OUT         │
  START                  │                                                 │
    │                    │  collect_nodes ──┐                              │
    ▼                    │  collect_operators─┐                            │
  [parallel collection]──┤  collect_mcp ──────┤──► aggregate_node         │
                         │  collect_etcd ─────┘         │                 │
                         │  collect_pvcs ──┐             │                 │
                         │  collect_pods ──┤             │                 │
                         │  collect_certs──┤             │                 │
                         │  collect_cp4i──┘              │                 │
                         └───────────────────────────────┼─────────────────┘
                                                         │
                                                         ▼
                                                   analyze_node
                                                         │
                                          ┌──────────────┴──────────────┐
                                   failures?                        no failures
                                          │                              │
                                          ▼                              │
                                    resolve_node                         │
                                          │                              │
                                          ▼                              │
                                      rag_node ◄───────────────────────┘
                                          │
                                          ▼
                                  build_report_node
                                          │
                                          ▼
                                    save_run_node
                                          │
                                          ▼
                                   send_email_node
                                          │
                                          ▼
                                         END

Conditional routing:
  - After analyze_node: if failures → resolve_node; else → rag_node
    (rag_node itself skips gracefully when failures=[])

Design decisions:
  - All 8 collection nodes run in parallel via LangGraph's Send API / fan-out
  - aggregate_node acts as the join barrier — it only runs after all collectors finish
  - Every node is fault-tolerant (never raises); errors flow through state
  - The compiled graph is cached for the process lifetime
  - run_cycle() is the only public API — scheduler.py calls nothing else here
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Literal

from langgraph.graph import END, START, StateGraph

from agent.config import get_settings
from agent.logger import get_logger
from agent.nodes import (
    aggregate_node,
    analyze_node,
    build_report_node,
    collect_certs_node,
    collect_cp4i_node,
    collect_etcd_node,
    collect_mcp_node,
    collect_nodes_node,
    collect_operators_node,
    collect_pods_node,
    collect_pvcs_node,
    rag_node,
    resolve_node,
    save_run_node,
    send_email_node,
)
from agent.state import ClusterState, initial_state

log = get_logger(__name__)
cfg = get_settings()


# ──────────────────────────────────────────────────────────────────────────────
# Conditional edge router
# ──────────────────────────────────────────────────────────────────────────────

def _route_after_analysis(
    state: ClusterState,
) -> Literal["resolve_node", "rag_node"]:
    """
    Route to resolve_node when the LLM found failures.
    Skip straight to rag_node (which also short-circuits) when cluster is healthy.
    """
    if state.get("failures"):
        log.debug("route_analysis", decision="resolve", failure_count=len(state["failures"]))
        return "resolve_node"
    log.debug("route_analysis", decision="skip_resolve_healthy")
    return "rag_node"


# ──────────────────────────────────────────────────────────────────────────────
# Graph builder (cached — built once per process)
# ──────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _build_graph():
    """
    Construct and compile the LangGraph StateGraph.

    Cached with lru_cache so the graph is compiled exactly once per process,
    regardless of how many monitoring cycles run.

    Returns:
        A compiled LangGraph runnable ready to invoke with a ClusterState.
    """
    builder = StateGraph(ClusterState)

    # ── Register all nodes ───────────────────────────────────────────────────
    builder.add_node("collect_nodes_node",     collect_nodes_node)
    builder.add_node("collect_operators_node", collect_operators_node)
    builder.add_node("collect_mcp_node",       collect_mcp_node)
    builder.add_node("collect_etcd_node",      collect_etcd_node)
    builder.add_node("collect_pvcs_node",      collect_pvcs_node)
    builder.add_node("collect_pods_node",      collect_pods_node)
    builder.add_node("collect_certs_node",     collect_certs_node)
    builder.add_node("collect_cp4i_node",      collect_cp4i_node)
    builder.add_node("aggregate_node",         aggregate_node)
    builder.add_node("analyze_node",           analyze_node)
    builder.add_node("resolve_node",           resolve_node)
    builder.add_node("rag_node",               rag_node)
    builder.add_node("build_report_node",      build_report_node)
    builder.add_node("save_run_node",          save_run_node)
    builder.add_node("send_email_node",        send_email_node)

    # ── Fan-out: START → all 8 collection nodes in parallel ─────────────────
    collection_nodes = [
        "collect_nodes_node",
        "collect_operators_node",
        "collect_mcp_node",
        "collect_etcd_node",
        "collect_pvcs_node",
        "collect_pods_node",
        "collect_certs_node",
        "collect_cp4i_node",
    ]
    for node_name in collection_nodes:
        builder.add_edge(START, node_name)

    # ── Fan-in: all 8 collectors → aggregate_node (join barrier) ────────────
    for node_name in collection_nodes:
        builder.add_edge(node_name, "aggregate_node")

    # ── Linear processing chain ──────────────────────────────────────────────
    builder.add_edge("aggregate_node", "analyze_node")

    # ── Conditional branch: failures present? ────────────────────────────────
    builder.add_conditional_edges(
        "analyze_node",
        _route_after_analysis,
        {
            "resolve_node": "resolve_node",
            "rag_node":     "rag_node",
        },
    )

    # resolve_node always feeds into rag_node (rag skips gracefully if needed)
    builder.add_edge("resolve_node", "rag_node")

    # ── Remaining linear chain ───────────────────────────────────────────────
    builder.add_edge("rag_node",          "build_report_node")
    builder.add_edge("build_report_node", "save_run_node")
    builder.add_edge("save_run_node",     "send_email_node")
    builder.add_edge("send_email_node",   END)

    compiled = builder.compile()
    log.info("graph_compiled", nodes=len(builder.nodes))
    return compiled


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def run_cycle() -> ClusterState:
    """
    Execute one full monitoring cycle and return the final ClusterState.

    This is the only function the scheduler needs to call.

    Workflow:
      1. Initialise a fresh ClusterState with the current UTC timestamp.
      2. Retrieve the compiled LangGraph pipeline (built once, reused).
      3. Invoke the graph — LangGraph handles parallel fan-out and fan-in.
      4. Log cycle summary and return the completed state.

    Returns:
        The fully-populated ClusterState after the cycle completes.

    Never raises — any unhandled exception is caught, logged, and a partial
    state is returned so the scheduler can continue to the next cycle.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    cluster_name = cfg.cluster_name

    log.info(
        "cycle_start",
        cluster=cluster_name,
        timestamp=timestamp,
        interval_minutes=cfg.interval_minutes,
    )

    state = initial_state(timestamp=timestamp, cluster_name=cluster_name)

    try:
        graph = _build_graph()
        final_state: ClusterState = graph.invoke(state)

        # ── Cycle summary log ────────────────────────────────────────────────
        failures = final_state.get("failures", [])
        severities = {f.get("severity", "").upper() for f in failures}

        if "CRITICAL" in severities:
            overall = "CRITICAL"
        elif "WARNING" in severities or failures:
            overall = "WARNING"
        else:
            overall = "HEALTHY"

        log.info(
            "cycle_complete",
            cluster=cluster_name,
            status=overall,
            failure_count=len(failures),
            run_id=final_state.get("run_id", ""),
            email_sent=final_state.get("email_sent", False),
            summary=final_state.get("summary", "")[:120],
        )

        return final_state

    except Exception as exc:
        log.error(
            "cycle_failed",
            cluster=cluster_name,
            timestamp=timestamp,
            error=str(exc),
            exc_info=True,
        )
        # Return the partial state so callers don't get None
        return state
