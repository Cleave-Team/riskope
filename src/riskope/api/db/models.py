from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(6))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    filings: Mapped[list[Filing]] = relationship(back_populates="company")


class Filing(Base):
    __tablename__ = "filings"
    __table_args__ = (
        Index("idx_filings_lookup", "company_id", "report_year"),
        CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed')", name="valid_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    rcept_no: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
    rcept_dt: Mapped[datetime] = mapped_column(Date, nullable=False)
    report_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    report_nm: Mapped[str | None] = mapped_column(String(200))
    s3_md_path: Mapped[str | None] = mapped_column(Text)
    raw_text_length: Mapped[int | None] = mapped_column(Integer)
    total_extracted: Mapped[int | None] = mapped_column(Integer)
    total_validated: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="filings")
    risk_factors: Mapped[list[RiskFactor]] = relationship(back_populates="filing", cascade="all, delete-orphan")


class RiskFactor(Base):
    __tablename__ = "risk_factors"
    __table_args__ = (
        Index("idx_risk_factors_filing", "filing_id"),
        Index("idx_risk_factors_category", "tertiary_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filing_id: Mapped[int] = mapped_column(ForeignKey("filings.id", ondelete="CASCADE"), nullable=False)
    primary_category: Mapped[str] = mapped_column(String(50), nullable=False)
    secondary_category: Mapped[str] = mapped_column(String(50), nullable=False)
    tertiary_category: Mapped[str] = mapped_column(String(100), nullable=False)
    supporting_quote: Mapped[str | None] = mapped_column(Text)
    original_tag: Mapped[str | None] = mapped_column(String(200))
    quality_score: Mapped[int | None] = mapped_column(Integer)
    similarity_score: Mapped[float | None] = mapped_column()
    reasoning: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    filing: Mapped[Filing] = relationship(back_populates="risk_factors")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    filing_id: Mapped[int | None] = mapped_column(ForeignKey("filings.id"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    progress: Mapped[int] = mapped_column(SmallInteger, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
