"""
rag.py — LlamaIndex RAG pipeline for the OCP AI Monitoring Agent.

Provides semantic search over historical incidents stored in PostgreSQL,
surfacing similar past incidents and their resolution steps when a new
failure is detected.

Architecture:
  - Embedding model : HuggingFace sentence-transformer (BAAI/bge-small-en-v1.5)
                      Runs locally — no external API call for embeddings.
  - Vector store    : PGVectorStore (llama-index-vector-stores-postgres)
                      Reuses the same PostgreSQL instance as the agent DB.
                      Stores embeddings in a dedicated table: "incident_vectors".
  - Index           : VectorStoreIndex — wraps the PGVector store and exposes
                      a retriever for top-K semantic search.
  - Source of truth : agent.models.Incident table — the canonical store.
                      Incidents are only embedded once (indexed=False → True).

Public API:
    query_similar_incidents(query_text, top_k?) → List[Dict]
        Called by rag_node() in nodes.py for each detected failure.

    index_new_incidents()
        Call this at startup or via a background job to embed any Incident
        rows where indexed=False. Safe to call repeatedly — idempotent.

    add_incident(incident: Incident)
        Embed and index a single new Incident immediately after saving it.

Design decisions:
  - Index and embedding model are module-level singletons (lazy-initialised)
    so the heavy HuggingFace model loads only once per process.
  - PGVectorStore uses a separate connection string (same DB, different table)
    so it doesn't interfere with the SQLAlchemy session pool.
  - query_similar_incidents() never raises — returns [] on any error so
    rag_node() always completes and the report renders without RAG context.
  - Incident text for embedding is built by Incident.to_rag_text() in models.py,
    which includes component, severity, description, root cause, and steps.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

from agent.config import get_settings
from agent.logger import get_logger

log = get_logger(__name__)
cfg = get_settings()


# ──────────────────────────────────────────────────────────────────────────────
# Lazy singletons — loaded once per process on first use
# ──────────────────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_embed_model():
    """
    Load the HuggingFace sentence-transformer embedding model.
    Cached — the model weights (~130 MB for bge-small-en-v1.5) load once.
    """
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding

    log.info("rag_embed_model_loading", model=cfg.embedding_model)
    model = HuggingFaceEmbedding(model_name=cfg.embedding_model)
    log.info("rag_embed_model_ready", model=cfg.embedding_model)
    return model


@lru_cache(maxsize=1)
def _get_vector_store():
    """
    Create the PGVectorStore connected to the agent's PostgreSQL instance.
    Uses a dedicated table 'incident_vectors' so it doesn't clash with ORM tables.
    """
    from llama_index.vector_stores.postgres import PGVectorStore

    log.info("rag_vector_store_init", db=cfg.postgres_db)

    # PGVectorStore needs the raw psycopg2 DSN (no SQLAlchemy driver prefix)
    connection_string = (
        f"postgresql://{cfg.postgres_user}:{cfg.postgres_password}"
        f"@{cfg.postgres_host}:{cfg.postgres_port}/{cfg.postgres_db}"
    )

    store = PGVectorStore.from_params(
        host=cfg.postgres_host,
        port=str(cfg.postgres_port),
        database=cfg.postgres_db,
        user=cfg.postgres_user,
        password=cfg.postgres_password,
        table_name="incident_vectors",
        embed_dim=384,          # bge-small-en-v1.5 output dimension
        hybrid_search=False,    # pure vector search — no BM25 index needed
    )

    log.info("rag_vector_store_ready", table="incident_vectors")
    return store


@lru_cache(maxsize=1)
def _get_index():
    """
    Build or load the VectorStoreIndex backed by PGVectorStore.
    Used ONLY for query/retrieval. Writes go through _insert_documents_to_store()
    which calls vector_store.add() directly — the reliable write path for PGVector.
    """
    from llama_index.core import VectorStoreIndex
    from llama_index.core import Settings as LlamaSettings
    from llama_index.core.storage.storage_context import StorageContext

    embed_model  = _get_embed_model()
    vector_store = _get_vector_store()

    LlamaSettings.embed_model = embed_model
    LlamaSettings.llm = None  # We manage the LLM ourselves

    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    index = VectorStoreIndex.from_vector_store(
        vector_store=vector_store,
        storage_context=storage_context,
        embed_model=embed_model,
    )

    log.info("rag_index_ready")
    return index


# ──────────────────────────────────────────────────────────────────────────────
# Document builder
# ──────────────────────────────────────────────────────────────────────────────

def _incident_to_document(incident) -> Any:
    """
    Convert an agent.models.Incident ORM object into a LlamaIndex Document.

    Metadata is stored alongside the vector so it can be returned in results
    without a separate DB round-trip.
    """
    from llama_index.core import Document

    return Document(
        text=incident.to_rag_text(),
        doc_id=str(incident.id),
        metadata={
            "incident_id":   incident.incident_id,
            "title":         incident.title,
            "component":     incident.component or "",
            "severity":      incident.severity or "",
            "root_cause":    incident.root_cause or "",
            "resolution_steps": incident.resolution_steps or [],
            "commands":      incident.commands or [],
            "docs_ref":      incident.docs_ref or "",
            "occurred_at":   str(incident.occurred_at) if incident.occurred_at else "",
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Indexing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _insert_documents_to_store(docs: list) -> None:
    """
    Insert LlamaIndex Document objects directly into the PGVectorStore.

    Uses the low-level pipeline:
      Document → TextNode (with embedding) → vector_store.add()

    This is the reliable path for PGVectorStore. Using index.insert() on a
    VectorStoreIndex loaded via from_vector_store() does NOT reliably persist
    vectors back to Postgres — it bypasses the storage context write path.
    """
    from llama_index.core.schema import TextNode
    from llama_index.core.node_parser import SentenceSplitter

    embed_model   = _get_embed_model()
    vector_store  = _get_vector_store()

    # Build nodes from documents
    splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=50)
    nodes = splitter.get_nodes_from_documents(docs)

    if not nodes:
        log.warning("rag_no_nodes_from_docs", doc_count=len(docs))
        return

    # Embed all nodes in a single batch call (much faster than one-by-one)
    texts = [node.get_content() for node in nodes]
    embeddings = embed_model.get_text_embedding_batch(texts, show_progress=False)

    for node, embedding in zip(nodes, embeddings):
        node.embedding = embedding

    # Write directly to PGVectorStore — this is what actually hits the DB
    vector_store.add(nodes)
    log.info("rag_nodes_written_to_store", node_count=len(nodes))


def index_new_incidents() -> int:
    """
    Embed and store all incidents where indexed=False.
    Marks them indexed=True only after successful vector store write.
    Safe to call repeatedly — idempotent.
    """
    try:
        from agent.db import get_session
        from agent.models import Incident

        log.info("rag_index_sync_check")

        with get_session() as session:
            pending = (
                session.query(Incident)
                .filter(Incident.indexed == False)  # noqa: E712
                .all()
            )

        if not pending:
            log.info("rag_index_sync", pending=0)
            return 0

        log.info("rag_index_sync_start", pending=len(pending))

        # Build documents
        docs = []
        for inc in pending:
            try:
                docs.append(_incident_to_document(inc))
            except Exception as e:
                log.error("rag_doc_build_failed", incident_id=inc.incident_id, error=str(e))

        if not docs:
            return 0

        # Write to vector store (single batched call)
        _insert_documents_to_store(docs)

        # Mark all as indexed ONLY after successful store write
        indexed_ids = [inc.id for inc in pending]
        with get_session() as session:
            session.query(Incident).filter(
                Incident.id.in_(indexed_ids)
            ).update({"indexed": True}, synchronize_session=False)

        count = len(pending)
        log.info("rag_index_sync_done", indexed=count)
        return count

    except Exception as exc:
        log.error("rag_index_sync_failed", error=str(exc), exc_info=True)
        return 0


def add_incident(incident) -> bool:
    """
    Embed and index a single Incident immediately after it is created.

    Args:
        incident: An agent.models.Incident ORM instance (already committed,
                  with incident.id populated after session.flush()).

    Returns:
        True on success, False on failure.
    """
    try:
        from agent.db import get_session
        from agent.models import Incident

        doc = _incident_to_document(incident)
        _insert_documents_to_store([doc])

        with get_session() as session:
            session.query(Incident).filter(
                Incident.id == incident.id
            ).update({"indexed": True}, synchronize_session=False)

        log.info("rag_incident_added", incident_id=incident.incident_id)
        return True

    except Exception as exc:
        log.error(
            "rag_incident_add_failed",
            incident_id=getattr(incident, "incident_id", "?"),
            error=str(exc),
            exc_info=True,
        )
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Public query API
# ──────────────────────────────────────────────────────────────────────────────

def query_similar_incidents(
    query_text: str,
    top_k: Optional[int] = None,
) -> List[Dict]:
    """
    Retrieve the most semantically similar historical incidents for a query.

    Called by rag_node() in nodes.py for each detected failure. The query
    text is typically: "{component} {failure_message}".

    Args:
        query_text: Free-form text describing the current failure.
        top_k:      Number of results to return. Defaults to cfg.rag_top_k.

    Returns:
        List of incident dicts (metadata + similarity score), ordered by
        relevance. Empty list on any error or when no incidents are indexed.

    Never raises.
    """
    if not query_text or not query_text.strip():
        return []

    k = top_k if top_k is not None else cfg.rag_top_k

    try:
        index     = _get_index()
        retriever = index.as_retriever(similarity_top_k=k)
        nodes     = retriever.retrieve(query_text)

        if not nodes:
            log.debug("rag_query_empty", query_preview=query_text[:80])
            return []

        results: List[Dict] = []
        for node in nodes:
            meta  = node.metadata or {}
            score = node.score if hasattr(node, "score") else None
            results.append({
                "incident_id":      meta.get("incident_id", ""),
                "title":            meta.get("title", ""),
                "component":        meta.get("component", ""),
                "severity":         meta.get("severity", ""),
                "root_cause":       meta.get("root_cause", ""),
                "resolution_steps": meta.get("resolution_steps", []),
                "commands":         meta.get("commands", []),
                "docs_ref":         meta.get("docs_ref", ""),
                "occurred_at":      meta.get("occurred_at", ""),
                "similarity_score": round(float(score), 4) if score is not None else None,
            })

        log.info(
            "rag_query_done",
            query_preview=query_text[:80],
            results=len(results),
            top_score=results[0]["similarity_score"] if results else None,
        )
        return results

    except Exception as exc:
        log.error("rag_query_failed", query_preview=query_text[:80], error=str(exc))
        return []
