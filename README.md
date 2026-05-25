# 🤖 OCP AI Monitoring & Incident Analysis Agent

> An AI-powered, agentic monitoring system for OpenShift clusters — autonomous log analysis, anomaly detection, root-cause resolution, and incident reporting using LangGraph, LangChain, LlamaIndex, and Groq LLMs.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Agent Pipeline](#agent-pipeline)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Agent](#running-the-agent)
- [Dashboard](#dashboard)
- [Email Alerts](#email-alerts)
- [RAG Pipeline](#rag-pipeline)
- [OpenShift Deployment](#openshift-deployment)
- [Environment Variables Reference](#environment-variables-reference)

---

## Overview

The **OCP AI Monitoring Agent** continuously monitors OpenShift clusters every N minutes (configurable). It collects real-time data across nodes, operators, etcd, PVCs, pods, TLS certificates, and CP4I endpoints — then feeds this data through a multi-step LangGraph agentic pipeline that:

1. **Analyses** the cluster state with an LLM to detect failures and anomalies
2. **Resolves** each failure with AI-generated root-cause analysis and remediation steps
3. **Enriches** resolutions using a RAG pipeline over historical incidents (LlamaIndex + PostgreSQL vectors)
4. **Renders** a formatted HTML incident report
5. **Emails** the report to the ops team (SMTP or SendGrid)
6. **Persists** every run to PostgreSQL for the dashboard and future RAG retrieval

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DATA SOURCES                                      │
│  oc CLI / Kubernetes API  │  Historical Incidents  │  OpenShift AI  │
└────────────┬──────────────┴──────────┬─────────────┴───────┬───────┘
             │                         │                     │
             ▼                         ▼                     ▼
     ┌───────────────┐        ┌──────────────┐      ┌──────────────────┐
     │  PostgreSQL   │        │    Qdrant /  │      │   Groq LLM API   │
     │ (Cluster Data)│        │  PGVector    │      │ llama-3.3-70b    │
     └───────┬───────┘        └──────┬───────┘      └────────┬─────────┘
             │                       │                       │
             └───────────────────────┼───────────────────────┘
                                     ▼
                        ┌────────────────────────┐
                        │   LangGraph Pipeline   │
                        │  (8 parallel collectors│
                        │   + 6 processing nodes)│
                        └────────────┬───────────┘
                                     ▼
                        ┌────────────────────────┐
                        │  Monitoring Dashboard  │
                        │  (FastAPI + HTML)      │
                        └────────────────────────┘
```

---

## Agent Pipeline

The LangGraph `StateGraph` runs the following topology every monitoring cycle:

```
START
  │
  ├──► collect_nodes_node      ─┐
  ├──► collect_operators_node  ─┤
  ├──► collect_mcp_node        ─┤
  ├──► collect_etcd_node       ─┤──► aggregate_node
  ├──► collect_pvcs_node       ─┤         │
  ├──► collect_pods_node       ─┤         ▼
  ├──► collect_certs_node      ─┤    analyze_node
  └──► collect_cp4i_node       ─┘         │
                                   ┌──────┴──────┐
                              failures?       no failures
                                   │               │
                                   ▼               │
                             resolve_node          │
                                   │               │
                                   ▼               ▼
                               rag_node ◄──────────┘
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
                                  END
```

**Key design decisions:**
- All 8 collection nodes run **in parallel** via LangGraph's fan-out, drastically reducing cycle time
- `aggregate_node` acts as the join barrier — waits for all collectors to finish
- Every node is **fault-tolerant** — errors flow through state, never crashing the pipeline
- Conditional routing: if no failures are detected, `resolve_node` is skipped entirely
- The compiled graph is **cached** for the process lifetime (`@lru_cache`)

---

## Features

### 🔍 Cluster Data Collection (8 Parallel Tools)
| Tool | What it collects |
|------|-----------------|
| `get_node_status` | Node health, conditions (Ready, DiskPressure, MemoryPressure, PIDPressure, NetworkUnavailable) |
| `get_cluster_operators` | ClusterOperator availability and degraded status |
| `get_machine_config_pools` | MachineConfigPool readiness and degraded state |
| `get_etcd_health` | etcd endpoint health and connectivity |
| `get_pvc_issues` | PVCs stuck in Pending or Lost phase |
| `get_failing_pods` | Failing pods across monitored namespaces (CrashLoopBackOff, OOMKilled, etc.) |
| `get_expiring_certs` | TLS certificates expiring within the configured warning window (default: 30 days) |
| `check_cp4i_endpoints` | HTTP health checks for CP4I API gateway endpoints |

### 🧠 AI Analysis & Resolution
- **LLM-powered failure detection** — Groq `llama-3.3-70b-versatile` analyses raw cluster state and outputs structured failure objects (`id`, `component`, `resource_name`, `severity`, `message`, `detected_at`)
- **Automated remediation** — for each failure, the LLM generates: `root_cause`, `steps[]`, `commands[]`, `docs_ref`
- **Severity classification** — CRITICAL / WARNING / INFO, used for email subject and dashboard colouring

### 📚 RAG Pipeline (LlamaIndex)
- Historical incidents are embedded using **BAAI/bge-small-en-v1.5** (local HuggingFace model — no API call for embeddings)
- Vectors stored in **PostgreSQL via PGVectorStore** (same DB, separate table `incident_vectors`)
- On each cycle, `rag_node` queries similar past incidents for each detected failure (top-K configurable)
- Similar incidents and their resolution steps are included in the HTML report for context
- New incidents are embedded and indexed automatically after each run — **fully self-improving**

### 📊 Monitoring Dashboard
- Built with **FastAPI + Jinja2 + HTML**
- Shows cluster health status, last N run summaries, failure trends, and AI-generated insights
- Accessible at `http://<host>:8080` (configurable)

### 📧 Email Alerts
- Supports **SMTP** (Gmail, corporate) and **SendGrid**
- Rich **HTML email** with cluster summary, failure table, resolution steps, and RAG context
- Configurable recipient list (JSON array)
- Option to send on healthy runs too (`EMAIL_ON_HEALTHY=true`)

---

## Tech Stack

| Category | Technology |
|----------|-----------|
| Agent Orchestration | LangGraph 0.2.53 |
| LLM Framework | LangChain 0.3.13 |
| LLM Provider | Groq (`llama-3.3-70b-versatile`) |
| RAG Pipeline | LlamaIndex 0.12.5 |
| Embeddings | HuggingFace `BAAI/bge-small-en-v1.5` |
| Vector Store | LlamaIndex PGVectorStore (PostgreSQL) |
| Kubernetes Client | `kubernetes` Python SDK 31.0.0 |
| Database | PostgreSQL + SQLAlchemy 2.0 + Alembic |
| Scheduler | APScheduler 3.10.4 (BlockingScheduler) |
| Dashboard | FastAPI 0.115.6 + Uvicorn + Jinja2 |
| Email | SMTP / SendGrid 6.11.0 |
| Config & Validation | Pydantic v2 + pydantic-settings |
| TLS Parsing | `cryptography` 43.0.3 |
| Logging | structlog 24.4.0 |
| Platform | OpenShift / Kubernetes |
| Containerisation | Docker |

---

## Project Structure

```
ocp-monitor/
├── scheduler.py                  # Entry point — APScheduler process
├── requirements.txt
├── .env.example                  # Copy to .env and fill in values
│
└── agent/
    ├── __init__.py
    ├── agent.py                  # LangGraph StateGraph definition & run_cycle()
    ├── config.py                 # Pydantic BaseSettings — all config from env
    ├── state.py                  # ClusterState TypedDict — shared pipeline memory
    ├── nodes.py                  # All LangGraph node functions (collection + processing)
    ├── tools.py                  # LangChain @tool functions — Kubernetes API wrappers
    ├── llm_chains.py             # LangChain chains — analysis, resolution, summarisation
    ├── rag.py                    # LlamaIndex RAG pipeline — embed, index, query
    ├── reporter.py               # HTML report builder
    ├── dashboard.py              # FastAPI dashboard app
    ├── db.py                     # SQLAlchemy engine, session, health check
    ├── models.py                 # SQLAlchemy ORM models (AgentRun, Incident)
    ├── emailer.py                # SMTP / SendGrid email dispatcher
    ├── logger.py                 # structlog configuration
    └── templates/
        └── dashboard.html        # Jinja2 dashboard template
```

---

## Prerequisites

- **Python 3.10+**
- **PostgreSQL 14+** (with pgvector extension for RAG)
- **OpenShift / Kubernetes cluster** access (via kubeconfig or in-cluster ServiceAccount)
- **Groq API key** — [get one free at console.groq.com](https://console.groq.com)
- **Docker** (optional, for containerised deployment)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/eidiko/ocp-monitor.git
cd ocp-monitor
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up PostgreSQL

```sql
-- Run as postgres superuser
CREATE DATABASE ocp_monitor;
CREATE USER ocp_agent WITH PASSWORD 'your_strong_password';
GRANT ALL PRIVILEGES ON DATABASE ocp_monitor TO ocp_agent;

-- Enable pgvector extension (required for RAG embeddings)
\c ocp_monitor
CREATE EXTENSION IF NOT EXISTS vector;
```

### 5. Configure environment

```bash
cp .env.example .env
# Edit .env with your actual values (see Configuration section)
```

### 6. Run the agent

```bash
python scheduler.py
```

The agent will:
1. Validate PostgreSQL connectivity
2. Initialise the database schema
3. Fire the first monitoring cycle **immediately**
4. Continue running every `INTERVAL_MINUTES` minutes

---

## Configuration

All configuration is via environment variables (`.env` file for local dev).

### Required Variables

| Variable | Description |
|----------|-------------|
| `GROQ_API_KEY` | Your Groq API key |
| `POSTGRES_PASSWORD` | PostgreSQL password |

### Key Optional Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLUSTER_NAME` | `OCP-PROD` | Display name shown in reports and dashboard |
| `KUBECONFIG_PATH` | *(empty)* | Path to kubeconfig. Leave empty for in-cluster auto-detect |
| `INTERVAL_MINUTES` | `15` | How often the monitoring cycle runs |
| `MONITORED_NAMESPACES` | `openshift-etcd,...` | Comma-separated namespaces to scan for failing pods |
| `NODE_CPU_THRESHOLD` | `80` | CPU % above which a node alert is raised |
| `NODE_MEMORY_THRESHOLD` | `80` | Memory % threshold |
| `CERT_EXPIRY_WARNING_DAYS` | `30` | Warn when TLS cert expires within this many days |
| `EMAIL_BACKEND` | `smtp` | `smtp` or `sendgrid` |
| `EMAIL_ON_HEALTHY` | `true` | Send email even when cluster is healthy |
| `DASHBOARD_PORT` | `8080` | Dashboard listening port |
| `LOG_FORMAT` | `json` | `json` (for log aggregators) or `console` (human-readable) |
| `RAG_TOP_K` | `3` | Number of similar past incidents to retrieve per failure |

See `.env.example` for the full list with comments.

---

## Running the Agent

### Local (external cluster access)

```bash
# Set KUBECONFIG_PATH in .env, then:
python scheduler.py
```

### In-cluster (OpenShift Pod)

Leave `KUBECONFIG_PATH` empty — the agent auto-detects the ServiceAccount token and in-cluster config.

```bash
# Start scheduler
python scheduler.py

# Start dashboard separately (optional)
uvicorn agent.dashboard:app --host 0.0.0.0 --port 8080
```

### Running a single cycle manually

```python
from agent.agent import run_cycle
state = run_cycle()
print(state["summary"])
print(f"Failures: {len(state['failures'])}")
```

---

## Dashboard

The dashboard is a FastAPI app served at `http://0.0.0.0:8080` (configurable).

**Start it:**
```bash
uvicorn agent.dashboard:app --host 0.0.0.0 --port ${DASHBOARD_PORT:-8080}
```

**Shows:**
- Current cluster health status (HEALTHY / WARNING / CRITICAL)
- Last N run summaries (configurable via `DASHBOARD_HISTORY_LIMIT`)
- Per-run failure breakdown with severity badges
- AI-generated cluster health summary per run
- Trend of failures over time

---

## Email Alerts

### SMTP (Gmail example)

```env
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-specific-password   # Use App Password, not account password
SMTP_USE_TLS=true
EMAIL_FROM=ocp-monitor@yourcompany.com
EMAIL_TO=["ops-team@yourcompany.com","platform-admin@yourcompany.com"]
```

### SendGrid

```env
EMAIL_BACKEND=sendgrid
SENDGRID_API_KEY=SG.xxxxxxxx
EMAIL_FROM=ocp-monitor@yourcompany.com
EMAIL_TO=["ops@yourcompany.com"]
```

---

## RAG Pipeline

The RAG pipeline automatically improves over time as incidents are resolved and stored.

**How it works:**

1. After each cycle, detected incidents are saved to PostgreSQL (`Incident` table)
2. Each `Incident` is embedded using `BAAI/bge-small-en-v1.5` (local — no API cost)
3. Embeddings stored in PostgreSQL via PGVectorStore (`incident_vectors` table)
4. On the next cycle, when new failures are detected, `rag_node` queries the top-K semantically similar past incidents
5. Similar incidents (including their root cause and resolution steps) are included in the email report

**Manual re-indexing** (if needed):
```python
from agent.rag import index_new_incidents
index_new_incidents()  # Embeds all incidents where indexed=False
```

---

## OpenShift Deployment

### Build the Docker image

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "scheduler.py"]
```

```bash
docker build -t ocp-monitor:latest .
docker push your-registry/ocp-monitor:latest
```

### Deploy to OpenShift

```bash
# Create the project
oc new-project ocp-monitor

# Create secret from .env
oc create secret generic ocp-monitor-env --from-env-file=.env

# Apply deployment YAML
oc apply -f deploy/deployment.yaml
oc apply -f deploy/service.yaml
oc apply -f deploy/route.yaml

# Check logs
oc logs -f deployment/ocp-monitor
```

**Minimum ServiceAccount permissions needed:**
```yaml
rules:
  - apiGroups: [""]
    resources: ["nodes", "pods", "persistentvolumeclaims", "endpoints"]
    verbs: ["get", "list"]
  - apiGroups: ["config.openshift.io"]
    resources: ["clusteroperators"]
    verbs: ["get", "list"]
  - apiGroups: ["machineconfiguration.openshift.io"]
    resources: ["machineconfigpools"]
    verbs: ["get", "list"]
```

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | ✅ | — | Groq API key |
| `POSTGRES_PASSWORD` | ✅ | — | PostgreSQL password |
| `POSTGRES_HOST` | | `postgres-svc` | PostgreSQL host |
| `POSTGRES_PORT` | | `5432` | PostgreSQL port |
| `POSTGRES_DB` | | `ocp_monitor` | Database name |
| `POSTGRES_USER` | | `ocp_agent` | Database user |
| `LLM_MODEL` | | `llama-3.3-70b-versatile` | Groq model to use |
| `LLM_TEMPERATURE` | | `0` | LLM temperature (0 = deterministic) |
| `LLM_MAX_TOKENS` | | `4096` | Max tokens per LLM call |
| `CLUSTER_NAME` | | `OCP-PROD` | Cluster display name |
| `KUBECONFIG_PATH` | | *(empty)* | Kubeconfig path (empty = in-cluster) |
| `OCP_CONTEXT` | | *(empty)* | kubeconfig context override |
| `INTERVAL_MINUTES` | | `15` | Monitoring interval |
| `TIMEZONE` | | `Asia/Kolkata` | Scheduler timezone |
| `NODE_CPU_THRESHOLD` | | `80` | CPU alert threshold (%) |
| `NODE_MEMORY_THRESHOLD` | | `80` | Memory alert threshold (%) |
| `CERT_EXPIRY_WARNING_DAYS` | | `30` | TLS cert expiry warning window |
| `MONITORED_NAMESPACES` | | `openshift-etcd,...` | Namespaces to scan for pods |
| `CP4I_HEALTH_ENDPOINTS` | | — | CP4I health URLs (comma-separated) |
| `EMAIL_BACKEND` | | `smtp` | `smtp` or `sendgrid` |
| `SMTP_HOST` | | `smtp.gmail.com` | SMTP server host |
| `SMTP_PORT` | | `587` | SMTP port |
| `SMTP_USER` | | — | SMTP username |
| `SMTP_PASSWORD` | | — | SMTP password |
| `SMTP_USE_TLS` | | `true` | Enable TLS for SMTP |
| `SENDGRID_API_KEY` | | — | SendGrid API key |
| `EMAIL_FROM` | | — | Sender address |
| `EMAIL_TO` | | — | Recipients (JSON array) |
| `EMAIL_ON_HEALTHY` | | `true` | Email even on healthy runs |
| `EMBEDDING_MODEL` | | `BAAI/bge-small-en-v1.5` | HuggingFace embedding model |
| `RAG_TOP_K` | | `3` | Similar incidents to retrieve |
| `DASHBOARD_HOST` | | `0.0.0.0` | Dashboard bind address |
| `DASHBOARD_PORT` | | `8080` | Dashboard port |
| `DASHBOARD_HISTORY_LIMIT` | | `20` | Past runs shown on dashboard |
| `LOG_LEVEL` | | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_FORMAT` | | `json` | `json` or `console` |

---

## Built With

- [LangGraph](https://github.com/langchain-ai/langgraph) — Stateful multi-agent orchestration
- [LangChain](https://github.com/langchain-ai/langchain) — LLM chains and tool calling
- [LlamaIndex](https://github.com/run-llama/llama_index) — RAG pipeline and vector search
- [Groq](https://groq.com) — Ultra-fast LLM inference
- [APScheduler](https://apscheduler.readthedocs.io) — Background job scheduling
- [FastAPI](https://fastapi.tiangolo.com) — Dashboard web framework

---

## License

Internal project — Eidiko Systems Integrators Pvt. Ltd. · AIML Center of Excellence
