"""Phase 5 evaluation suite: link runs to executions + experiment suite_hash

Revision ID: 005_phase5_evaluation_suite
Revises: 004_phase4_diagnosis
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_phase5_evaluation_suite"
down_revision: str | None = "004_phase4_diagnosis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("experiments", sa.Column("suite_hash", sa.Text(), nullable=True))
    op.add_column("runs", sa.Column("execution_id", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_runs_execution_id",
        "runs",
        "execution_traces",
        ["execution_id"],
        ["id"],
    )
    op.create_index("ix_runs_execution_id", "runs", ["execution_id"])


def downgrade() -> None:
    op.drop_index("ix_runs_execution_id", table_name="runs")
    op.drop_constraint("fk_runs_execution_id", "runs", type_="foreignkey")
    op.drop_column("runs", "execution_id")
    op.drop_column("experiments", "suite_hash")
