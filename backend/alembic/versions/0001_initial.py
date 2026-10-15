"""Initial schema: jobs and clips tables.

Revision ID: 0001_initial
Revises: None
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_filename", sa.String(512), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "current_stage", sa.String(64), nullable=False, server_default="queued"
        ),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("num_shorts", sa.Integer(), nullable=False),
        sa.Column("clip_duration_min", sa.Integer(), nullable=False),
        sa.Column("clip_duration_max", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "clips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start_time", sa.Float(), nullable=False),
        sa.Column("end_time", sa.Float(), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("title", sa.String(512), nullable=True),
        sa.Column("hook", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(1024), nullable=False),
    )
    op.create_index("ix_clips_job_id", "clips", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_clips_job_id", table_name="clips")
    op.drop_table("clips")
    op.drop_table("jobs")
