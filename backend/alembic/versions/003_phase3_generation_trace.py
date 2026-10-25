"""Phase 3 execution traces for RAG generation

Revision ID: 003_phase3_generation_trace
Revises: 002_phase2_corpus_retrieval
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003_phase3_generation_trace"
down_revision: str | None = "002_phase2_corpus_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_traces",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column(
            "corpus_version_id",
            sa.Text(),
            sa.ForeignKey("corpus_versions.id"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column(
            "retrieval_trace_id",
            sa.Text(),
            sa.ForeignKey("retrieval_traces.id"),
            nullable=True,
        ),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("retrieved_chunks", postgresql.JSONB(), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=True),
        sa.Column("embedding_revision", sa.Text(), nullable=True),
        sa.Column("generation_model", sa.Text(), nullable=True),
        sa.Column("generation_temperature", sa.Float(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column(
            "abstained",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retrieval_latency_ms", sa.Float(), nullable=True),
        sa.Column("generation_latency_ms", sa.Float(), nullable=True),
        sa.Column("total_latency_ms", sa.Float(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_execution_traces_request_id", "execution_traces", ["request_id"]
    )
    op.create_index(
        "ix_execution_traces_corpus_version_id",
        "execution_traces",
        ["corpus_version_id"],
    )
    op.create_index(
        "ix_execution_traces_retrieval_trace_id",
        "execution_traces",
        ["retrieval_trace_id"],
    )
    op.create_index("ix_execution_traces_status", "execution_traces", ["status"])


def downgrade() -> None:
    op.drop_index("ix_execution_traces_status", table_name="execution_traces")
    op.drop_index(
        "ix_execution_traces_retrieval_trace_id", table_name="execution_traces"
    )
    op.drop_index(
        "ix_execution_traces_corpus_version_id", table_name="execution_traces"
    )
    op.drop_index("ix_execution_traces_request_id", table_name="execution_traces")
    op.drop_table("execution_traces")
