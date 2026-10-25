"""Phase 1 SQLAlchemy models — foundation schema per PRD §8."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


def _uuid_str() -> str:
    return str(uuid.uuid4())


class ApiKey(Base):
    """API key records. Phase 1 auth uses env API_KEY; table reserved for later."""

    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Corpus(Base):
    __tablename__ = "corpora"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    versions: Mapped[list[CorpusVersion]] = relationship(back_populates="corpus")


class CorpusVersion(Base):
    __tablename__ = "corpus_versions"
    __table_args__ = (
        UniqueConstraint(
            "corpus_id",
            "corpus_hash",
            "chunking_config_hash",
            "embedding_model",
            "embedding_revision",
            name="uq_corpus_version_identity",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    corpus_id: Mapped[str] = mapped_column(
        Text, ForeignKey("corpora.id"), nullable=False, index=True
    )
    corpus_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chunking_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    chunking_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_revision: Mapped[str] = mapped_column(Text, nullable=False)
    vector_collection: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="CREATED", server_default="CREATED"
    )
    status_message: Mapped[str | None] = mapped_column(Text)
    document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    corpus: Mapped[Corpus] = relationship(back_populates="versions")
    documents: Mapped[list[Document]] = relationship(back_populates="corpus_version")
    chunks: Mapped[list[Chunk]] = relationship(back_populates="corpus_version")


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("corpus_version_id", "id", name="uq_document_per_version"),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(Text, nullable=False)
    corpus_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("corpus_versions.id"), nullable=False, index=True
    )
    source_uri: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)

    corpus_version: Mapped[CorpusVersion] = relationship(back_populates="documents")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("corpus_version_id", "id", name="uq_chunk_id_per_version"),
        UniqueConstraint(
            "corpus_version_id",
            "document_id",
            "ordinal",
            name="uq_chunk_ordinal",
        ),
    )

    pk: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    corpus_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("corpus_versions.id"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    text_hash: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    chunk_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB)

    corpus_version: Mapped[CorpusVersion] = relationship(back_populates="chunks")


class Suite(Base):
    __tablename__ = "suites"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[str] = mapped_column(Text, primary_key=True)
    suite_hash: Mapped[str] = mapped_column(Text, nullable=False)
    corpus_id: Mapped[str] = mapped_column(
        Text, ForeignKey("corpora.id"), nullable=False
    )
    taxonomy_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["suite_id", "suite_version"],
            ["suites.id", "suites.version"],
        ),
    )

    case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    suite_id: Mapped[str] = mapped_column(Text, primary_key=True)
    suite_version: Mapped[str] = mapped_column(Text, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    name: Mapped[str | None] = mapped_column(Text)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("api_keys.id")
    )
    corpus_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("corpus_versions.id"), nullable=False
    )
    suite_id: Mapped[str | None] = mapped_column(Text)
    suite_version: Mapped[str | None] = mapped_column(Text)
    suite_hash: Mapped[str | None] = mapped_column(Text)
    git_commit: Mapped[str | None] = mapped_column(Text)
    pipeline: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_experiment_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("experiments.id")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_uri: Mapped[str | None] = mapped_column(Text)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    experiment_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("experiments.id"), index=True
    )
    case_id: Mapped[str | None] = mapped_column(Text)
    execution_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("execution_traces.id"), nullable=True, index=True
    )
    request_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text)
    abstained: Mapped[bool | None] = mapped_column(Boolean)
    generator_raw: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[dict | None] = mapped_column(JSONB)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RunChunk(Base):
    __tablename__ = "run_chunks"

    run_id: Mapped[str] = mapped_column(
        Text, ForeignKey("runs.id"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    chunk_id: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)


class JudgeResult(Base):
    __tablename__ = "judge_results"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "judge_type",
            "input_hash",
            name="uq_judge_result_execution",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    run_id: Mapped[str | None] = mapped_column(Text, ForeignKey("runs.id"), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("execution_traces.id"), nullable=True, index=True
    )
    judge_type: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    input_hash: Mapped[str] = mapped_column(Text, nullable=False)
    output: Mapped[dict | None] = mapped_column(JSONB)
    schema_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class Diagnosis(Base):
    __tablename__ = "diagnoses"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    run_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("runs.id"), unique=True, nullable=True
    )
    execution_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("execution_traces.id"), unique=True, nullable=True, index=True
    )
    taxonomy_version: Mapped[str] = mapped_column(Text, nullable=False)
    primary_code: Mapped[str] = mapped_column(Text, nullable=False)
    secondary_codes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    layer: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis_confidence: Mapped[str | None] = mapped_column(Text)
    diagnosis_score: Mapped[float | None] = mapped_column(Float)
    recommendation_code: Mapped[str | None] = mapped_column(Text)
    signals: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DiagnosisEvidence(Base):
    __tablename__ = "diagnosis_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    diagnosis_id: Mapped[str] = mapped_column(
        Text, ForeignKey("diagnoses.id"), nullable=False, index=True
    )
    evidence_type: Mapped[str] = mapped_column(Text, nullable=False)
    ref: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)


class ExperimentMetric(Base):
    __tablename__ = "experiment_metrics"

    experiment_id: Mapped[str] = mapped_column(
        Text, ForeignKey("experiments.id"), primary_key=True
    )
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confusion_matrix: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BaselineArtifact(Base):
    __tablename__ = "baseline_artifacts"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    experiment_id: Mapped[str] = mapped_column(
        Text, ForeignKey("experiments.id"), nullable=False
    )
    suite_id: Mapped[str] = mapped_column(Text, nullable=False)
    suite_version: Mapped[str] = mapped_column(Text, nullable=False)
    suite_hash: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExperimentCaseResult(Base):
    """Per-case evaluation outcome for an experiment (Phase 6)."""

    __tablename__ = "experiment_case_results"
    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "case_id", name="uq_experiment_case_result"
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    experiment_id: Mapped[str] = mapped_column(
        Text, ForeignKey("experiments.id"), nullable=False, index=True
    )
    case_id: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    expected_failure_code: Mapped[str] = mapped_column(Text, nullable=False)
    expected_rule_id: Mapped[str | None] = mapped_column(Text)
    predicted_failure_code: Mapped[str] = mapped_column(Text, nullable=False)
    predicted_rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis_confidence: Mapped[str | None] = mapped_column(Text)
    expected_evidence_refs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    predicted_evidence_refs: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    evidence_valid: Mapped[bool | None] = mapped_column(Boolean)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    execution_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("execution_traces.id")
    )
    diagnosis_id: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[dict | None] = mapped_column(JSONB)
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    cost: Mapped[float | None] = mapped_column(Float)
    error: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RetrievalTrace(Base):
    """Raw retrieval evidence for later diagnosis (Phase 2)."""

    __tablename__ = "retrieval_traces"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    request_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    corpus_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("corpus_versions.id"), nullable=False, index=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_chunk_ids: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    scores: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExecutionTrace(Base):
    """Full RAG execution evidence for later diagnosis (Phase 3)."""

    __tablename__ = "execution_traces"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=_uuid_str)
    request_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    corpus_version_id: Mapped[str] = mapped_column(
        Text, ForeignKey("corpus_versions.id"), nullable=False, index=True
    )
    query: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_trace_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("retrieval_traces.id"), index=True
    )
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    retrieved_chunks: Mapped[list | None] = mapped_column(JSONB)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_revision: Mapped[str | None] = mapped_column(Text)
    generation_model: Mapped[str | None] = mapped_column(Text)
    generation_temperature: Mapped[float | None] = mapped_column(Float)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    answer_text: Mapped[str | None] = mapped_column(Text)
    abstained: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    retrieval_latency_ms: Mapped[float | None] = mapped_column(Float)
    generation_latency_ms: Mapped[float | None] = mapped_column(Float)
    total_latency_ms: Mapped[float | None] = mapped_column(Float)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
