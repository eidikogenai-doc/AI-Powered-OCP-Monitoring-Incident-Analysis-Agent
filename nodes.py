"""
models.py — SQLAlchemy ORM models for the OCP monitoring agent.

Tables:
  agent_runs       — One record per 15-minute monitoring cycle.
  failures         — Individual failures detected in a run (FK → agent_runs).
  resolutions      — LLM-generated resolution steps per failure (FK → failures).
  incidents        — Historical incidents for the LlamaIndex RAG knowledge base.

Usage:
    from agent.models import Base, AgentRun, Failure, Resolution, Incident
    # Use with SQLAlchemy session from agent.db
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ──────────────────────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ──────────────────────────────────────────────────────────────────────────────
# AgentRun — one record per monitoring cycle
# ──────────────────────────────────────────────────────────────────────────────

class AgentRun(Base):
    """
    Top-level record for a single 15-minute monitoring cycle.

    status values: HEALTHY | WARNING | CRITICAL | ERROR
      - HEALTHY   : no failures detected
      - WARNING   : ≥1 WARNING-severity failure
      - CRITICAL  : ≥1 CRITICAL-severity failure
      - ERROR     : agent itself encountered a collection/processing error
    """

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cluster_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    collected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="HEALTHY", index=True
    )
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collection_errors: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # Full raw snapshot (nodes, operators, etc.) — useful for debugging
    raw_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Relationships
    failures: Mapped[List["Failure"]] = relationship(
        "Failure", back_populates="run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<AgentRun id={self.id} cluster={self.cluster_name} "
            f"status={self.status} failures={self.failure_count} "
            f"started_at={self.started_at}>"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Failure — individual failure detected by the LLM analysis chain
# ──────────────────────────────────────────────────────────────────────────────

class Failure(Base):
    """
    A single failure identified by the LLM analysis chain within one agent run.

    severity values: CRITICAL | WARNING | INFO
    component values: nodes | operators | mcpools | etcd | pvcs | pods | certs | cp4i
    """

    __tablename__ = "failures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # LLM-assigned failure ID within the run (e.g. "F-001") — used to link resolutions
    failure_ref: Mapped[str] = mapped_column(String(32), nullable=False)
    component: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    run: Mapped["AgentRun"] = relationship("AgentRun", back_populates="failures")
    resolution: Mapped[Optional["Resolution"]] = relationship(
        "Resolution", back_populates="failure", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:
        return (
            f"<Failure ref={self.failure_ref} component={self.component} "
            f"severity={self.severity}>"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Resolution — LLM-generated runbook steps for a failure
# ──────────────────────────────────────────────────────────────────────────────

class Resolution(Base):
    """
    LLM-generated remediation steps for a single Failure.
    Stored as JSONB arrays for flexible querying.
    """

    __tablename__ = "resolutions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    failure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("failures.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,    # one resolution per failure
        index=True,
    )
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    steps: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True, comment="Ordered list of human-readable resolution steps"
    )
    commands: Mapped[Optional[list]] = mapped_column(
        JSONB, nullable=True, comment="Exact oc/kubectl commands ready to copy-paste"
    )
    docs_ref: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="OpenShift documentation URL"
    )

    # Relationship
    failure: Mapped["Failure"] = relationship("Failure", back_populates="resolution")

    def __repr__(self) -> str:
        return f"<Resolution failure_id={self.failure_id}>"


# ──────────────────────────────────────────────────────────────────────────────
# Incident — historical incident knowledge base for LlamaIndex RAG
# ──────────────────────────────────────────────────────────────────────────────

class Incident(Base):
    """
    Historical incident record seeded into the LlamaIndex vector store.

    These records form the RAG knowledge base. When a new failure is detected,
    LlamaIndex searches this table for similar past incidents and surfaces
    their resolution steps as additional context.

    Populate this table by:
      1. Seeding from your existing runbook / incident management system.
      2. Automatically promoting resolved agent failures (via a background job).
    """

    __tablename__ = "incidents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Human-readable incident ID, e.g. "INC-2024-0042"
    incident_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    component: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    severity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Freeform description — this text is what LlamaIndex embeds and searches
    description: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolution_steps: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    commands: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    docs_ref: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    occurred_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Tracks whether this incident has been indexed into the vector store
    indexed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def to_rag_text(self) -> str:
        """
        Produce the plain-text document that will be embedded by LlamaIndex.
        Includes enough context for semantic search to match similar failures.
        """
        parts = [
            f"Incident: {self.incident_id}",
            f"Title: {self.title}",
            f"Component: {self.component or 'unknown'}",
            f"Severity: {self.severity or 'unknown'}",
            f"Description: {self.description}",
        ]
        if self.root_cause:
            parts.append(f"Root Cause: {self.root_cause}")
        if self.resolution_steps:
            steps_text = " ".join(
                f"{i + 1}. {s}" for i, s in enumerate(self.resolution_steps)
            )
            parts.append(f"Resolution Steps: {steps_text}")
        if self.commands:
            parts.append(f"Commands: {' | '.join(self.commands)}")
        return "\n".join(parts)

    def __repr__(self) -> str:
        return f"<Incident id={self.incident_id} component={self.component}>"
