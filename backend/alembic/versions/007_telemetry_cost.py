"""v1.0: durable telemetry events + execution cost accounting

Revision ID: 007_telemetry_cost
Revises: 006_phase6_experiments_baselines
Create Date: 2026-10-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007_telemetry_cost"
down_revision: str | None = "006_phase6_experiments_baselines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "metric_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(precision=53), nullable=False),
        sa.Column("labels", postgresql.JSONB(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
    )
    op.create_index("ix_metric_events_ts", "metric_events", ["ts"])
    op.create_index("ix_metric_events_name", "metric_events", ["name"])
    op.create_index("ix_metric_events_name_ts", "metric_events", ["name", "ts"])

    op.add_column(
        "execution_traces",
        sa.Column("cost_usd", sa.Float(precision=53), nullable=True),
    )
    op.add_column(
        "execution_traces",
        sa.Column("pricing_version", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("execution_traces", "pricing_version")
    op.drop_column("execution_traces", "cost_usd")
    op.drop_index("ix_metric_events_name_ts", table_name="metric_events")
    op.drop_index("ix_metric_events_name", table_name="metric_events")
    op.drop_index("ix_metric_events_ts", table_name="metric_events")
    op.drop_table("metric_events")
