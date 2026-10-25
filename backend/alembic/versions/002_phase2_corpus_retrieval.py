"""Phase 2 corpus status, source_name, retrieval traces

Revision ID: 002_phase2_corpus_retrieval
Revises: 001_phase1_foundation
Create Date: 2026-09-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_phase2_corpus_retrieval"
down_revision: str | None = "001_phase1_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "corpus_versions",
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="CREATED",
        ),
    )
    op.add_column(
        "corpus_versions",
        sa.Column("status_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "corpus_versions",
        sa.Column(
            "document_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "corpus_versions",
        sa.Column(
            "chunk_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_corpus_versions_status", "corpus_versions", ["status"]
    )

    op.add_column(
        "documents",
        sa.Column("source_name", sa.Text(), nullable=True),
    )

    op.create_table(
        "retrieval_traces",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column(
            "corpus_version_id",
            sa.Text(),
            sa.ForeignKey("corpus_versions.id"),
            nullable=False,
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("retrieved_chunk_ids", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("scores", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("embedding_model", sa.Text(), nullable=False),
        sa.Column(
            "result_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_retrieval_traces_request_id", "retrieval_traces", ["request_id"]
    )
    op.create_index(
        "ix_retrieval_traces_corpus_version_id",
        "retrieval_traces",
        ["corpus_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retrieval_traces_corpus_version_id", table_name="retrieval_traces"
    )
    op.drop_index("ix_retrieval_traces_request_id", table_name="retrieval_traces")
    op.drop_table("retrieval_traces")
    op.drop_column("documents", "source_name")
    op.drop_index("ix_corpus_versions_status", table_name="corpus_versions")
    op.drop_column("corpus_versions", "chunk_count")
    op.drop_column("corpus_versions", "document_count")
    op.drop_column("corpus_versions", "status_message")
    op.drop_column("corpus_versions", "status")
