"""Phase 4 diagnosis linked to execution_traces

Revision ID: 004_phase4_diagnosis
Revises: 003_phase3_generation_trace
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_phase4_diagnosis"
down_revision: str | None = "003_phase3_generation_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # diagnoses: allow execution_id; make run_id optional
    op.alter_column("diagnoses", "run_id", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "diagnoses",
        sa.Column("execution_id", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_diagnoses_execution_id",
        "diagnoses",
        "execution_traces",
        ["execution_id"],
        ["id"],
    )
    op.create_index("ix_diagnoses_execution_id", "diagnoses", ["execution_id"])
    op.create_unique_constraint(
        "uq_diagnoses_execution_id", "diagnoses", ["execution_id"]
    )

    # judge_results: link to executions
    op.drop_constraint("uq_judge_result", "judge_results", type_="unique")
    op.alter_column("judge_results", "run_id", existing_type=sa.Text(), nullable=True)
    op.add_column(
        "judge_results",
        sa.Column("execution_id", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_judge_results_execution_id",
        "judge_results",
        "execution_traces",
        ["execution_id"],
        ["id"],
    )
    op.create_index(
        "ix_judge_results_execution_id", "judge_results", ["execution_id"]
    )
    op.create_unique_constraint(
        "uq_judge_result_execution",
        "judge_results",
        ["execution_id", "judge_type", "input_hash"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_judge_result_execution", "judge_results", type_="unique")
    op.drop_index("ix_judge_results_execution_id", table_name="judge_results")
    op.drop_constraint(
        "fk_judge_results_execution_id", "judge_results", type_="foreignkey"
    )
    op.drop_column("judge_results", "execution_id")
    op.alter_column("judge_results", "run_id", existing_type=sa.Text(), nullable=False)
    op.create_unique_constraint(
        "uq_judge_result",
        "judge_results",
        ["run_id", "judge_type", "input_hash"],
    )

    op.drop_constraint("uq_diagnoses_execution_id", "diagnoses", type_="unique")
    op.drop_index("ix_diagnoses_execution_id", table_name="diagnoses")
    op.drop_constraint("fk_diagnoses_execution_id", "diagnoses", type_="foreignkey")
    op.drop_column("diagnoses", "execution_id")
    op.alter_column("diagnoses", "run_id", existing_type=sa.Text(), nullable=False)
