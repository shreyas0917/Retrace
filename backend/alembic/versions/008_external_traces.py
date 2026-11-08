"""Bring-your-own-trace: external execution traces

Adds `execution_traces.source` ("internal" | "external") and a JSONB
`trace_metadata` column, and makes `corpus_version_id` nullable so traces
produced by someone else's RAG app can be stored without a Retrace corpus.

Revision ID: 008_external_traces
Revises: 007_telemetry_cost
Create Date: 2026-11-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008_external_traces"
down_revision: str | None = "007_telemetry_cost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "execution_traces",
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'internal'"),
        ),
    )
    op.add_column(
        "execution_traces",
        sa.Column("trace_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "ck_execution_traces_source",
        "execution_traces",
        "source IN ('internal', 'external')",
    )
    # Internal traces always reference a corpus version; only external ones may not.
    op.create_check_constraint(
        "ck_execution_traces_internal_has_corpus",
        "execution_traces",
        "source = 'external' OR corpus_version_id IS NOT NULL",
    )
    op.alter_column("execution_traces", "corpus_version_id", existing_type=sa.Text(), nullable=True)
    op.create_index("ix_execution_traces_source", "execution_traces", ["source"])


def downgrade() -> None:
    bind = op.get_bind()
    external = bind.execute(
        sa.text("SELECT count(*) FROM execution_traces WHERE source = 'external'")
    ).scalar_one()
    if external:
        raise RuntimeError(
            f"{external} external trace(s) exist; delete them (and their diagnoses) "
            "before downgrading, because corpus_version_id becomes NOT NULL again."
        )
    op.drop_index("ix_execution_traces_source", table_name="execution_traces")
    op.alter_column("execution_traces", "corpus_version_id", existing_type=sa.Text(), nullable=False)
    op.drop_constraint("ck_execution_traces_internal_has_corpus", "execution_traces", type_="check")
    op.drop_constraint("ck_execution_traces_source", "execution_traces", type_="check")
    op.drop_column("execution_traces", "trace_metadata")
    op.drop_column("execution_traces", "source")
