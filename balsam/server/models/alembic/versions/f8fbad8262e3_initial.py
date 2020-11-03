"""initial

Revision ID: f8fbad8262e3
Revises:
Create Date: 2020-07-09 13:31:25.600291

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "f8fbad8262e3"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=True),
        sa.Column("hashed_password", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("hostname", sa.String(length=100), nullable=True),
        sa.Column("path", sa.String(length=100), nullable=True),
        sa.Column("last_refresh", sa.DateTime(), nullable=True),
        sa.Column("creation_date", sa.DateTime(), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("globus_endpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("num_nodes", sa.Integer(), nullable=True),
        sa.Column("backfill_windows", sa.JSON(), nullable=True),
        sa.Column("queued_jobs", sa.JSON(), nullable=True),
        sa.Column("optional_batch_job_params", sa.JSON(), nullable=True),
        sa.Column("allowed_projects", sa.JSON(), nullable=True),
        sa.Column("allowed_queues", sa.JSON(), nullable=True),
        sa.Column(
            "transfer_locations", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hostname", "path"),
    )
    op.create_index(op.f("ix_sites_owner_id"), "sites", ["owner_id"], unique=False)
    op.create_table(
        "apps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("class_path", sa.String(length=200), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("transfers", sa.JSON(), nullable=True),
        sa.Column("last_modified", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "class_path"),
    )
    op.create_table(
        "batch_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("scheduler_id", sa.Integer(), nullable=True),
        sa.Column("project", sa.String(length=64), nullable=False),
        sa.Column("queue", sa.String(length=64), nullable=False),
        sa.Column("optional_params", sa.JSON(), nullable=True),
        sa.Column("num_nodes", sa.Integer(), nullable=False),
        sa.Column("wall_time_min", sa.Integer(), nullable=False),
        sa.Column("job_mode", sa.String(length=16), nullable=False),
        sa.Column(
            "filter_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("status_info", sa.JSON(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=True),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batch_jobs_state"), "batch_jobs", ["state"], unique=False)
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("heartbeat", sa.DateTime(), nullable=True),
        sa.Column("batch_job_id", sa.Integer(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["batch_job_id"], ["batch_jobs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workdir", sa.String(length=256), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("app_id", sa.Integer(), nullable=True),
        sa.Column("session_id", sa.Integer(), nullable=True),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("batch_job_id", sa.Integer(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=True),
        sa.Column("last_update", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("return_code", sa.Integer(), nullable=True),
        sa.Column("num_nodes", sa.Integer(), nullable=True),
        sa.Column("ranks_per_node", sa.Integer(), nullable=True),
        sa.Column("threads_per_rank", sa.Integer(), nullable=True),
        sa.Column("threads_per_core", sa.Integer(), nullable=True),
        sa.Column("gpus_per_rank", sa.Float(), nullable=True),
        sa.Column("node_packing_count", sa.Integer(), nullable=True),
        sa.Column("wall_time_min", sa.Integer(), nullable=True),
        sa.Column("launch_params", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["app_id"], ["apps.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["batch_job_id"], ["batch_jobs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_state"), "jobs", ["state"], unique=False)

    # Correct way of creating index on tags supporting fast @> (contains) lookups:
    op.create_index(
        op.f("ix_jobs_tags"),
        "jobs",
        [text("tags jsonb_path_ops")],
        postgresql_using="GIN",
        unique=False,
    )
    op.create_table(
        "job_deps",
        sa.Column("parent_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("parent_id", "child_id"),
    )
    op.create_index(
        op.f("ix_job_deps_child_id"), "job_deps", ["child_id"], unique=False
    )
    op.create_index(
        op.f("ix_job_deps_parent_id"), "job_deps", ["parent_id"], unique=False
    )
    op.create_table(
        "log_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=True),
        sa.Column("from_state", sa.String(length=32), nullable=True),
        sa.Column("to_state", sa.String(length=32), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "transfer_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column(
            "direction",
            sa.Enum("stage_in", "stage_out", name="transferdirection"),
            nullable=False,
        ),
        sa.Column("remote_path", sa.String(length=256), nullable=True),
        sa.Column("local_path", sa.String(length=256), nullable=True),
        sa.Column("recursive", sa.Boolean(), nullable=False),
        sa.Column("location_alias", sa.String(length=256), nullable=True),
        sa.Column(
            "state",
            sa.Enum(
                "awaiting_job",
                "pending",
                "active",
                "done",
                "error",
                name="transferitemstate",
            ),
            nullable=False,
        ),
        sa.Column("task_id", sa.String(length=100), nullable=True),
        sa.Column("transfer_info", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("transfer_items")
    op.drop_table("log_events")
    op.drop_index(op.f("ix_job_deps_parent_id"), table_name="job_deps")
    op.drop_index(op.f("ix_job_deps_child_id"), table_name="job_deps")
    op.drop_table("job_deps")
    op.drop_index(op.f("ix_jobs_tags"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_state"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("sessions")
    op.drop_table("batch_jobs")
    op.drop_table("apps")
    op.drop_index(op.f("ix_sites_owner_id"), table_name="sites")
    op.drop_table("sites")
    op.drop_table("users")
    # ### end Alembic commands ###
