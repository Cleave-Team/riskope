"""Use corp_code as companies PK, replace company_id FK with corp_code FK

Revision ID: 002
Revises: 001
Create Date: 2026-03-16
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "002"
down_revision: Union[str, Sequence[str], None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_jobs_status", table_name="analysis_jobs")
    op.drop_table("analysis_jobs")
    op.drop_index("idx_risk_factors_filing", table_name="risk_factors")
    op.drop_index("idx_risk_factors_category", table_name="risk_factors")
    op.drop_table("risk_factors")
    op.drop_index("idx_filings_lookup", table_name="filings")
    op.drop_table("filings")
    op.drop_table("companies")

    op.create_table(
        "companies",
        sa.Column("corp_code", sa.String(8), primary_key=True),
        sa.Column("corp_name", sa.String(200), nullable=False),
        sa.Column("stock_code", sa.String(6), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "filings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("corp_code", sa.String(8), sa.ForeignKey("companies.corp_code"), nullable=False),
        sa.Column("rcept_no", sa.String(14), unique=True, nullable=False),
        sa.Column("rcept_dt", sa.Date(), nullable=False),
        sa.Column("report_year", sa.SmallInteger(), nullable=False),
        sa.Column("report_nm", sa.String(200), nullable=True),
        sa.Column("s3_md_path", sa.Text(), nullable=True),
        sa.Column("raw_text_length", sa.Integer(), nullable=True),
        sa.Column("total_extracted", sa.Integer(), nullable=True),
        sa.Column("total_validated", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="valid_status"),
    )
    op.create_index("idx_filings_lookup", "filings", ["corp_code", "report_year"])

    op.create_table(
        "risk_factors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filing_id", sa.Integer(), sa.ForeignKey("filings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("primary_category", sa.String(50), nullable=False),
        sa.Column("secondary_category", sa.String(50), nullable=False),
        sa.Column("tertiary_category", sa.String(100), nullable=False),
        sa.Column("supporting_quote", sa.Text(), nullable=True),
        sa.Column("original_tag", sa.String(200), nullable=True),
        sa.Column("quality_score", sa.Integer(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_risk_factors_filing", "risk_factors", ["filing_id"])
    op.create_index("idx_risk_factors_category", "risk_factors", ["tertiary_category"])

    op.create_table(
        "analysis_jobs",
        sa.Column(
            "id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("corp_code", sa.String(8), sa.ForeignKey("companies.corp_code"), nullable=False),
        sa.Column("filing_id", sa.Integer(), sa.ForeignKey("filings.id"), nullable=True),
        sa.Column("status", sa.String(20), server_default="queued", nullable=False),
        sa.Column("progress", sa.SmallInteger(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_jobs_status", "analysis_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("analysis_jobs")
    op.drop_table("risk_factors")
    op.drop_table("filings")
    op.drop_table("companies")
