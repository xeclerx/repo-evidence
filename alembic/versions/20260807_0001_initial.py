"""Create RepoEvidence tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260807_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repositories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("html_url", sa.String(500), nullable=False),
        sa.Column("default_branch", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("owner", "name", name="uq_repository_owner_name"),
    )
    op.create_table(
        "analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "repository_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("repositories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("commit_sha", sa.String(40), nullable=False),
        sa.Column("analyzer_version", sa.String(30), nullable=False),
        sa.Column("framework", sa.String(30)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("maturity", sa.String(50)),
        sa.Column("coverage", sa.Float()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "repository_id", "commit_sha", "analyzer_version", name="uq_analysis_identity"
        ),
    )
    op.create_index("ix_analysis_repository_created", "analyses", ["repository_id", "created_at"])
    op.create_table(
        "category_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("applicable_points", sa.Float(), nullable=False),
        sa.Column("registry_points", sa.Float(), nullable=False),
        sa.UniqueConstraint("analysis_id", "category", name="uq_analysis_category"),
    )
    op.create_table(
        "check_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "analysis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("analyses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_id", sa.String(100), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.Column("max_points", sa.Float(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.UniqueConstraint("analysis_id", "check_id", name="uq_analysis_check"),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "check_result_id",
            sa.Integer(),
            sa.ForeignKey("check_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column("path", sa.String(1000), nullable=False),
        sa.Column("line_start", sa.Integer()),
        sa.Column("line_end", sa.Integer()),
        sa.Column("message", sa.Text()),
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "check_result_id",
            sa.Integer(),
            sa.ForeignKey("check_results.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("text", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recommendations")
    op.drop_table("evidence")
    op.drop_table("check_results")
    op.drop_table("category_results")
    op.drop_index("ix_analysis_repository_created", table_name="analyses")
    op.drop_table("analyses")
    op.drop_table("repositories")
