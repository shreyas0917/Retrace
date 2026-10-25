"""Phase 6: experiment case results + baseline active/suite_hash

Revision ID: 006_phase6_experiments_baselines
Revises: 005_phase5_evaluation_suite
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_phase6_experiments_baselines"
down_revision: str | None = "005_phase5_evaluation_suite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "baseline_artifacts",
        sa.Column("suite_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "baseline_artifacts",
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        "ix_baseline_artifacts_suite_active",
        "baseline_artifacts",
        ["suite_id", "suite_version", "is_active"],
    )

    op.create_table(
        "experiment_case_results",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Text(),
            sa.ForeignKey("experiments.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("case_id", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("expected_failure_code", sa.Text(), nullable=False),
        sa.Column("expected_rule_id", sa.Text(), nullable=True),
        sa.Column("predicted_failure_code", sa.Text(), nullable=False),
        sa.Column("predicted_rule_id", sa.Text(), nullable=False),
        sa.Column("diagnosis_confidence", sa.Text(), nullable=True),
        sa.Column(
            "expected_evidence_refs",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "predicted_evidence_refs",
            postgresql.ARRAY(sa.Text()),
            nullable=True,
        ),
        sa.Column("evidence_valid", sa.Boolean(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("execution_id", sa.Text(), sa.ForeignKey("execution_traces.id")),
        sa.Column("diagnosis_id", sa.Text(), nullable=True),
        sa.Column("latency_ms", postgresql.JSONB(), nullable=True),
        sa.Column("token_usage", postgresql.JSONB(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "experiment_id",
            "case_id",
            name="uq_experiment_case_result",
        ),
    )


def downgrade() -> None:
    op.drop_table("experiment_case_results")
    op.drop_index(
        "ix_baseline_artifacts_suite_active", table_name="baseline_artifacts"
    )
    op.drop_column("baseline_artifacts", "is_active")
    op.drop_column("baseline_artifacts", "suite_hash")
