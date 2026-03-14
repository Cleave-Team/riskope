from __future__ import annotations

import logging
import re
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from riskope.api.db.models import AnalysisJob, Company, Filing, RiskFactor
from riskope.config import Settings, get_settings
from riskope.dart.client import DartClient
from riskope.pipeline.orchestrator import RiskExtractionPipeline
from riskope.storage.s3 import upload_markdown

logger = logging.getLogger(__name__)

_REPORT_YEAR_RE = re.compile(r"\((\d{4})\.?\d{0,2}\)")


def extract_report_year(report_nm: str, rcept_dt: str) -> int:
    match = _REPORT_YEAR_RE.search(report_nm)
    if match:
        return int(match.group(1))
    filing_month = int(rcept_dt[4:6])
    filing_year = int(rcept_dt[:4])
    return filing_year - 1 if filing_month <= 3 else filing_year


def is_annual_report(report_nm: str) -> bool:
    return "사업보고서" in report_nm and "반기" not in report_nm and "분기" not in report_nm


async def get_or_create_company(db: AsyncSession, corp_code: str, corp_name: str, stock_code: str = "") -> Company:
    result = await db.execute(select(Company).where(Company.corp_code == corp_code))
    company = result.scalar_one_or_none()
    if company:
        if company.corp_name != corp_name:
            company.corp_name = corp_name
            await db.flush()
        return company

    company = Company(corp_code=corp_code, corp_name=corp_name, stock_code=stock_code or None)
    db.add(company)
    await db.flush()
    return company


async def find_cached_filing(db: AsyncSession, company_id: int, report_year: int) -> Filing | None:
    result = await db.execute(
        select(Filing)
        .options(selectinload(Filing.risk_factors))
        .where(Filing.company_id == company_id, Filing.report_year == report_year, Filing.status == "completed")
        .order_by(Filing.rcept_dt.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def check_latest_filing_on_dart(dart: DartClient, corp_code: str) -> dict | None:
    reports = await dart.find_annual_reports(corp_code=corp_code)
    annual = [r for r in reports if is_annual_report(r.get("report_nm", ""))]
    if not annual:
        return None
    annual.sort(key=lambda r: r.get("rcept_dt", ""), reverse=True)
    return annual[0]


async def is_cache_fresh(db: AsyncSession, company_id: int, dart_latest: dict) -> bool:
    rcept_no = dart_latest.get("rcept_no", "")
    result = await db.execute(
        select(Filing).where(Filing.company_id == company_id, Filing.rcept_no == rcept_no, Filing.status == "completed")
    )
    return result.scalar_one_or_none() is not None


async def get_filings_for_company(db: AsyncSession, company_id: int, years: int | None = None) -> list[Filing]:
    stmt = (
        select(Filing)
        .options(selectinload(Filing.risk_factors))
        .where(Filing.company_id == company_id, Filing.status == "completed")
        .order_by(Filing.report_year.desc())
    )
    if years:
        stmt = stmt.limit(years)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def run_analysis(
    db: AsyncSession,
    job: AnalysisJob,
    company: Company,
    dart_report: dict,
    settings: Settings,
) -> Filing:
    job.status = "running"
    job.started_at = datetime.now()
    await db.flush()

    rcept_no = dart_report["rcept_no"]
    rcept_dt_str = dart_report.get("rcept_dt", "")
    report_nm = dart_report.get("report_nm", "")
    report_year = extract_report_year(report_nm, rcept_dt_str)
    rcept_dt = date(int(rcept_dt_str[:4]), int(rcept_dt_str[4:6]), int(rcept_dt_str[6:8]))

    filing = Filing(
        company_id=company.id,
        rcept_no=rcept_no,
        rcept_dt=rcept_dt,
        report_year=report_year,
        report_nm=report_nm,
        status="processing",
    )
    db.add(filing)
    await db.flush()
    job.filing_id = filing.id
    job.progress = 10
    await db.flush()

    dart_client = DartClient(api_key=settings.dart_api_key)
    risk_text = await dart_client.fetch_risk_section(rcept_no)

    if not risk_text:
        filing.status = "failed"
        filing.error_message = "위험 섹션 추출 실패"
        job.status = "failed"
        job.error_message = filing.error_message
        await db.flush()
        raise ValueError(filing.error_message)

    filing.raw_text_length = len(risk_text)
    job.progress = 20
    await db.flush()

    try:
        s3_path = upload_markdown(risk_text, company.corp_code, report_year, rcept_no)
        filing.s3_md_path = s3_path
    except Exception:
        logger.warning("S3 업로드 실패, 계속 진행: rcept_no=%s", rcept_no)

    job.progress = 30
    await db.flush()

    pipeline = RiskExtractionPipeline(settings)
    profile = await pipeline.run_for_report(
        risk_text=risk_text,
        corp_name=company.corp_name,
        rcept_no=rcept_no,
    )

    if not profile or not profile.risk_factors:
        filing.status = "failed"
        filing.error_message = "리스크 팩터 추출 결과 없음"
        job.status = "failed"
        job.error_message = filing.error_message
        await db.flush()
        raise ValueError(filing.error_message)

    job.progress = 90
    filing.total_extracted = profile.total_extracted
    filing.total_validated = profile.total_validated
    await db.flush()

    for rf in profile.risk_factors:
        db.add(
            RiskFactor(
                filing_id=filing.id,
                primary_category=rf.primary,
                secondary_category=rf.secondary,
                tertiary_category=rf.tertiary,
                supporting_quote=rf.supporting_quote,
                original_tag=rf.original_tag,
                quality_score=rf.quality_score,
                similarity_score=rf.similarity_score,
                reasoning=rf.reasoning,
            )
        )

    filing.status = "completed"
    filing.processed_at = datetime.now()
    job.status = "completed"
    job.progress = 100
    job.completed_at = datetime.now()
    await db.commit()

    result = await db.execute(select(Filing).options(selectinload(Filing.risk_factors)).where(Filing.id == filing.id))
    return result.scalar_one()
