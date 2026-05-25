"""
config.py — Centralised configuration via Pydantic BaseSettings.

All settings are read from environment variables (or a .env file during
local development).  No secrets are ever hardcoded here.

In-cluster detection:
  When KUBECONFIG_PATH is empty the agent assumes it is running as a
  Kubernetes/OpenShift Pod and calls kubernetes.config.load_incluster_config().
  When running externally, set KUBECONFIG_PATH to your kubeconfig file path.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ──────────────────────────────────────────────────────────────────────────────
# Settings model
# ──────────────────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    """
    All runtime configuration for the OCP AI Monitoring Agent.
    Values are loaded from environment variables; defaults shown below.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",           # silently ignore unknown env vars
    )

    # ── LLM (Groq) ──────────────────────────────────────────────────────────
    groq_api_key: str = Field(..., description="Groq API key (required)")
    llm_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model identifier",
    )
    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="LLM sampling temperature (0 = deterministic)",
    )
    llm_max_tokens: int = Field(
        default=4096,
        gt=0,
        description="Maximum tokens in LLM response",
    )

    # ── OpenShift / Kubernetes ───────────────────────────────────────────────
    kubeconfig_path: Optional[str] = Field(
        default=None,
        description="Path to kubeconfig. Leave empty for in-cluster auto-detect.",
    )
    ocp_context: Optional[str] = Field(
        default=None,
        description="kubeconfig context name. None = use current-context.",
    )
    cluster_name: str = Field(
        default="OCP-PROD",
        description="Human-readable cluster name shown in reports.",
    )

    # ── PostgreSQL ───────────────────────────────────────────────────────────
    postgres_host: str = Field(default="postgres-svc")
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = Field(default="ocp_monitor")
    postgres_user: str = Field(default="ocp_agent")
    postgres_password: str = Field(..., description="PostgreSQL password (required)")
    # Optional: override the full DSN directly
    database_url: Optional[str] = Field(default=None)

    # ── Email ────────────────────────────────────────────────────────────────
    email_backend: str = Field(
        default="smtp",
        description="Email backend: 'smtp' or 'sendgrid'",
    )
    # SMTP
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: Optional[str] = Field(default=None)
    smtp_password: Optional[str] = Field(default=None)
    smtp_use_tls: bool = Field(default=True)
    # SendGrid
    sendgrid_api_key: Optional[str] = Field(default=None)
    # Common
    email_from: str = Field(default="ocp-monitor@company.com")
    # Stored as JSON string in env: '["a@b.com","c@d.com"]'
    email_to: str = Field(default='["ops@company.com"]')
    email_on_healthy: bool = Field(
        default=True,
        description="Send email report even when cluster is healthy.",
    )

    # ── Scheduler ────────────────────────────────────────────────────────────
    interval_minutes: int = Field(
        default=15,
        ge=1,
        le=1440,
        description="Polling interval in minutes.",
    )
    timezone: str = Field(default="Asia/Kolkata")

    # ── Health Check Thresholds ──────────────────────────────────────────────
    node_cpu_threshold: int = Field(
        default=80,
        ge=1,
        le=100,
        description="CPU usage % threshold. Alert if exceeded.",
    )
    node_memory_threshold: int = Field(
        default=80,
        ge=1,
        le=100,
        description="Memory usage % threshold. Alert if exceeded.",
    )
    cert_expiry_warning_days: int = Field(
        default=30,
        ge=1,
        description="Warn if TLS cert expires within this many days.",
    )

    # ── CP4I Specific ────────────────────────────────────────────────────────
    # Comma-separated list stored as a string in env
    monitored_namespaces: str = Field(
        default=(
            "openshift-etcd,openshift-kube-apiserver,"
            "openshift-kube-controller-manager,openshift-kube-scheduler,"
            "openshift-ingress,openshift-storage,cp4i,"
            "ibm-common-services,cms"
        ),
        description="Comma-separated namespaces to monitor for failing pods.",
    )
    cp4i_health_endpoints: str = Field(
        default="",
        description="Comma-separated CP4I HTTP health-check URLs.",
    )

    # ── LlamaIndex RAG ───────────────────────────────────────────────────────
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="HuggingFace sentence-transformer model for embeddings.",
    )
    rag_top_k: int = Field(
        default=3,
        ge=1,
        le=20,
        description="Number of similar past incidents to retrieve.",
    )

    # ── Dashboard (FastAPI) ──────────────────────────────────────────────────
    dashboard_host: str = Field(default="0.0.0.0")
    dashboard_port: int = Field(default=8080, ge=1, le=65535)
    dashboard_history_limit: int = Field(
        default=20,
        ge=1,
        description="Number of past agent runs shown on dashboard.",
    )

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO")
    log_format: str = Field(
        default="json",
        description="'json' for structured logging, 'console' for human-readable.",
    )

    # ── Derived / computed properties ────────────────────────────────────────

    @property
    def is_in_cluster(self) -> bool:
        """True when running as a Pod inside OpenShift/Kubernetes."""
        return not self.kubeconfig_path

    @property
    def db_url(self) -> str:
        """PostgreSQL DSN. Uses database_url override if set."""
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def email_recipients(self) -> List[str]:
        """Parse the JSON string EMAIL_TO into a Python list."""
        try:
            return json.loads(self.email_to)
        except (json.JSONDecodeError, TypeError):
            # Fall back: treat as single address
            return [self.email_to]

    @property
    def monitored_namespaces_list(self) -> List[str]:
        """Parse comma-separated namespaces into a list."""
        return [ns.strip() for ns in self.monitored_namespaces.split(",") if ns.strip()]

    @property
    def cp4i_endpoints_list(self) -> List[str]:
        """Parse comma-separated CP4I endpoints into a list."""
        if not self.cp4i_health_endpoints:
            return []
        return [ep.strip() for ep in self.cp4i_health_endpoints.split(",") if ep.strip()]

    # ── Validators ───────────────────────────────────────────────────────────

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return v.upper()

    @field_validator("email_backend")
    @classmethod
    def validate_email_backend(cls, v: str) -> str:
        allowed = {"smtp", "sendgrid"}
        if v.lower() not in allowed:
            raise ValueError(f"email_backend must be one of {allowed}")
        return v.lower()

    @model_validator(mode="after")
    def validate_email_config(self) -> "Settings":
        """Ensure the chosen email backend has its required credentials."""
        if self.email_backend == "smtp":
            if not self.smtp_user or not self.smtp_password:
                raise ValueError(
                    "SMTP_USER and SMTP_PASSWORD are required when EMAIL_BACKEND=smtp"
                )
        elif self.email_backend == "sendgrid":
            if not self.sendgrid_api_key:
                raise ValueError(
                    "SENDGRID_API_KEY is required when EMAIL_BACKEND=sendgrid"
                )
        return self

    @model_validator(mode="after")
    def validate_kubeconfig(self) -> "Settings":
        """If kubeconfig path is given, verify the file actually exists."""
        if self.kubeconfig_path:
            path = Path(self.kubeconfig_path)
            if not path.exists():
                raise ValueError(
                    f"KUBECONFIG_PATH '{self.kubeconfig_path}' does not exist. "
                    "Leave it empty to use in-cluster ServiceAccount auth."
                )
        return self


# ──────────────────────────────────────────────────────────────────────────────
# Singleton accessor — import this everywhere instead of instantiating directly
# ──────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the global Settings singleton.

    Using @lru_cache means Settings is instantiated exactly once per process.
    All environment variables are read and validated at first call.

    Usage:
        from agent.config import get_settings
        cfg = get_settings()
        print(cfg.cluster_name)
    """
    return Settings()
