"""Phase 1 foundation schema

Revision ID: 001_phase1_foundation
Revises:
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_phase1_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("key_hash"),
    )

    op.create_table(
        "corpora",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "corpus_versions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("corpus_id", sa.Text(), sa.ForeignKey("corpora.id"), nullable=False),
        sa.Column("corpus_hash", sa.Text(), nullable=False),
        sa.Column("chunking_config", postgresql.JSONB(), nullable=False),
        sa.Column("chunking_config_hash", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column("embedding_revision", sa.Text(), nullable=False),
        sa.Column("vector_collection", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "corpus_id",
            "corpus_hash",
            "chunking_config_hash",
            "embedding_model",
            "embedding_revision",
            name="uq_corpus_version_identity",
        ),
    )
    op.create_index("ix_corpus_versions_corpus_id", "corpus_versions", ["corpus_id"])
    op.create_index("ix_corpus_versions_corpus_hash", "corpus_versions", ["corpus_hash"])

    op.create_table(
        "documents",
        sa.Column("pk", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column(
            "corpus_version_id",
            sa.Text(),
            sa.ForeignKey("corpus_versions.id"),
            nullable=False,
        ),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "corpus_version_id", "id", name="uq_document_per_version"
        ),
    )
    op.create_index(
        "ix_documents_corpus_version_id", "documents", ["corpus_version_id"]
    )

    op.create_table(
        "chunks",
        sa.Column("pk", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column(
            "corpus_version_id",
            sa.Text(),
            sa.ForeignKey("corpus_versions.id"),
            nullable=False,
        ),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.UniqueConstraint(
            "corpus_version_id", "id", name="uq_chunk_id_per_version"
        ),
        sa.UniqueConstraint(
            "corpus_version_id",
            "document_id",
            "ordinal",
            name="uq_chunk_ordinal",
        ),
    )
    op.create_index("ix_chunks_corpus_version_id", "chunks", ["corpus_version_id"])
    op.create_index("ix_chunks_id", "chunks", ["id"])

    op.create_table(
        "suites",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("version", sa.Text(), primary_key=True),
        sa.Column("suite_hash", sa.Text(), nullable=False),
        sa.Column("corpus_id", sa.Text(), sa.ForeignKey("corpora.id"), nullable=False),
        sa.Column("taxonomy_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "cases",
        sa.Column("case_id", sa.Text(), primary_key=True),
        sa.Column("suite_id", sa.Text(), primary_key=True),
        sa.Column("suite_version", sa.Text(), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["suite_id", "suite_version"],
            ["suites.id", "suites.version"],
        ),
    )

    op.create_table(
        "experiments",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("api_keys.id"),
            nullable=True,
        ),
        sa.Column(
            "corpus_version_id",
            sa.Text(),
            sa.ForeignKey("corpus_versions.id"),
            nullable=False,
        ),
        sa.Column("suite_id", sa.Text(), nullable=True),
        sa.Column("suite_version", sa.Text(), nullable=True),
        sa.Column("git_commit", sa.Text(), nullable=True),
        sa.Column("pipeline", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "baseline_experiment_id",
            sa.Text(),
            sa.ForeignKey("experiments.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("artifact_uri", sa.Text(), nullable=True),
    )

    op.create_table(
        "runs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Text(),
            sa.ForeignKey("experiments.id"),
            nullable=True,
        ),
        sa.Column("case_id", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("abstained", sa.Boolean(), nullable=True),
        sa.Column("generator_raw", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", postgresql.JSONB(), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_runs_experiment_id", "runs", ["experiment_id"])

    op.create_table(
        "run_chunks",
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), primary_key=True),
        sa.Column("rank", sa.Integer(), primary_key=True),
        sa.Column("chunk_id", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
    )

    op.create_table(
        "judge_results",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column("judge_type", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("output", postgresql.JSONB(), nullable=True),
        sa.Column("schema_ok", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.UniqueConstraint(
            "run_id", "judge_type", "input_hash", name="uq_judge_result"
        ),
    )

    op.create_table(
        "diagnoses",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "run_id", sa.Text(), sa.ForeignKey("runs.id"), nullable=False, unique=True
        ),
        sa.Column("taxonomy_version", sa.Text(), nullable=False),
        sa.Column("primary_code", sa.Text(), nullable=False),
        sa.Column("secondary_codes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("rule_id", sa.Text(), nullable=False),
        sa.Column("layer", sa.Text(), nullable=False),
        sa.Column("diagnosis_confidence", sa.Text(), nullable=True),
        sa.Column("diagnosis_score", sa.Float(), nullable=True),
        sa.Column("recommendation_code", sa.Text(), nullable=True),
        sa.Column("signals", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "diagnosis_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "diagnosis_id", sa.Text(), sa.ForeignKey("diagnoses.id"), nullable=False
        ),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_diagnosis_evidence_diagnosis_id", "diagnosis_evidence", ["diagnosis_id"]
    )

    op.create_table(
        "experiment_metrics",
        sa.Column(
            "experiment_id",
            sa.Text(),
            sa.ForeignKey("experiments.id"),
            primary_key=True,
        ),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("confusion_matrix", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "baseline_artifacts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "experiment_id", sa.Text(), sa.ForeignKey("experiments.id"), nullable=False
        ),
        sa.Column("suite_id", sa.Text(), nullable=False),
        sa.Column("suite_version", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("baseline_artifacts")
    op.drop_table("experiment_metrics")
    op.drop_index("ix_diagnosis_evidence_diagnosis_id", table_name="diagnosis_evidence")
    op.drop_table("diagnosis_evidence")
    op.drop_table("diagnoses")
    op.drop_table("judge_results")
    op.drop_table("run_chunks")
    op.drop_index("ix_runs_experiment_id", table_name="runs")
    op.drop_table("runs")
    op.drop_table("experiments")
    op.drop_table("cases")
    op.drop_table("suites")
    op.drop_index("ix_chunks_id", table_name="chunks")
    op.drop_index("ix_chunks_corpus_version_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_index("ix_documents_corpus_version_id", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_corpus_versions_corpus_hash", table_name="corpus_versions")
    op.drop_index("ix_corpus_versions_corpus_id", table_name="corpus_versions")
    op.drop_table("corpus_versions")
    op.drop_table("corpora")
    op.drop_table("api_keys")
