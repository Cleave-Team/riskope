from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from riskope.api.db.models import AnalysisJob, Company, Filing
from riskope.api.db.session import get_db
from riskope.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CompanyResponse,
    FilingResponse,
    FilingWithRiskFactors,
    RiskFactorResponse,
    RiskFactorsQueryResponse,
    RiskProfileResponse,
)
from riskope.api.service import (
    check_latest_filing_on_dart,
    extract_report_year,
    find_cached_filing,
    get_filings_for_company,
    get_or_create_company,
    is_cache_fresh,
    run_analysis,
)
from riskope.config import get_settings
from riskope.dart.client import DartClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


def _filing_to_response(filing: Filing) -> FilingResponse:
    return FilingResponse(
        rcept_no=filing.rcept_no,
        rcept_dt=filing.rcept_dt,
        report_year=filing.report_year,
        report_nm=filing.report_nm,
        status=filing.status,
        raw_text_length=filing.raw_text_length,
        total_extracted=filing.total_extracted,
        total_validated=filing.total_validated,
        risk_factor_count=len(filing.risk_factors),
        processed_at=filing.processed_at,
        s3_md_path=filing.s3_md_path,
    )


def _risk_factors_to_response(filing: Filing) -> list[RiskFactorResponse]:
    return [
        RiskFactorResponse(
            primary_category=rf.primary_category,
            secondary_category=rf.secondary_category,
            tertiary_category=rf.tertiary_category,
            supporting_quote=rf.supporting_quote,
            original_tag=rf.original_tag,
            quality_score=rf.quality_score,
            similarity_score=rf.similarity_score,
            reasoning=rf.reasoning,
        )
        for rf in filing.risk_factors
    ]


@router.post("/{corp_code}/analyze")
async def analyze_company(
    corp_code: str,
    body: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    dart = DartClient(api_key=settings.dart_api_key)

    dart_latest = await check_latest_filing_on_dart(dart, corp_code)
    if not dart_latest:
        raise HTTPException(status_code=404, detail=f"DART에서 {corp_code}의 사업보고서를 찾을 수 없습니다")

    corp_name = dart_latest.get("corp_name", corp_code)
    stock_code = dart_latest.get("stock_code", "")
    company = await get_or_create_company(db, corp_code, corp_name, stock_code)

    report_nm = dart_latest.get("report_nm", "")
    rcept_dt_str = dart_latest.get("rcept_dt", "")
    report_year = body.report_year or extract_report_year(report_nm, rcept_dt_str)

    if not body.force_refresh:
        cached = await find_cached_filing(db, company.id, report_year)
        if cached and await is_cache_fresh(db, company.id, dart_latest):
            return AnalyzeResponse(
                status="completed",
                result=RiskProfileResponse(
                    corp_code=company.corp_code,
                    corp_name=company.corp_name,
                    filing=_filing_to_response(cached),
                    risk_factors=_risk_factors_to_response(cached),
                ),
                cache_hit=True,
                filing_rcept_no=cached.rcept_no,
            )

    existing_job = await db.execute(
        select(AnalysisJob).where(
            AnalysisJob.company_id == company.id,
            AnalysisJob.status.in_(["queued", "running"]),
        )
    )
    if existing := existing_job.scalar_one_or_none():
        return AnalyzeResponse(
            status="accepted",
            job_id=str(existing.id),
            cache_hit=False,
            filing_rcept_no=dart_latest.get("rcept_no", ""),
        )

    job = AnalysisJob(company_id=company.id)
    db.add(job)
    await db.commit()

    background_tasks.add_task(_run_analysis_task, str(job.id), company.corp_code, dart_latest)

    return AnalyzeResponse(
        status="accepted",
        job_id=str(job.id),
        cache_hit=False,
        filing_rcept_no=dart_latest.get("rcept_no", ""),
    )


async def _run_analysis_task(job_id: str, corp_code: str, dart_report: dict):
    import uuid

    from riskope.api.db.session import _get_session_factory

    settings = get_settings()
    async with _get_session_factory()() as db:
        job = await db.get(AnalysisJob, uuid.UUID(job_id))
        if not job:
            return

        company = await db.execute(select(Company).where(Company.corp_code == corp_code))
        company_obj = company.scalar_one()

        try:
            await run_analysis(db, job, company_obj, dart_report, settings)
        except Exception as e:
            job.status = "failed"
            job.error_message = str(e)
            job.completed_at = datetime.now()
            await db.commit()
            logger.exception("Analysis failed: corp_code=%s", corp_code)


@router.get("/{corp_code}/risk-factors")
async def get_risk_factors(
    corp_code: str,
    years: int = 5,
    db: AsyncSession = Depends(get_db),
) -> RiskFactorsQueryResponse:
    company = await db.execute(select(Company).where(Company.corp_code == corp_code))
    company_obj = company.scalar_one_or_none()
    if not company_obj:
        raise HTTPException(status_code=404, detail=f"기업 {corp_code}을 찾을 수 없습니다")

    filings = await get_filings_for_company(db, company_obj.id, years=years)

    filing_results = [
        FilingWithRiskFactors(
            filing=_filing_to_response(f),
            risk_factors=_risk_factors_to_response(f),
        )
        for f in filings
    ]

    total = sum(len(fwr.risk_factors) for fwr in filing_results)

    return RiskFactorsQueryResponse(
        corp_code=company_obj.corp_code,
        corp_name=company_obj.corp_name,
        filings=filing_results,
        total_risk_factors=total,
    )


@router.get("/{corp_code}/risk-factors/{report_year}")
async def get_risk_factors_by_year(
    corp_code: str,
    report_year: int,
    db: AsyncSession = Depends(get_db),
) -> RiskProfileResponse:
    company = await db.execute(select(Company).where(Company.corp_code == corp_code))
    company_obj = company.scalar_one_or_none()
    if not company_obj:
        raise HTTPException(status_code=404, detail=f"기업 {corp_code}을 찾을 수 없습니다")

    filing = await find_cached_filing(db, company_obj.id, report_year)
    if not filing:
        raise HTTPException(status_code=404, detail=f"{report_year}년 분석 결과가 없습니다")

    return RiskProfileResponse(
        corp_code=company_obj.corp_code,
        corp_name=company_obj.corp_name,
        filing=_filing_to_response(filing),
        risk_factors=_risk_factors_to_response(filing),
    )


@router.get("/{corp_code}/filings")
async def list_filings(
    corp_code: str,
    db: AsyncSession = Depends(get_db),
) -> list[FilingResponse]:
    company = await db.execute(select(Company).where(Company.corp_code == corp_code))
    company_obj = company.scalar_one_or_none()
    if not company_obj:
        raise HTTPException(status_code=404, detail=f"기업 {corp_code}을 찾을 수 없습니다")

    filings = await get_filings_for_company(db, company_obj.id)
    return [_filing_to_response(f) for f in filings]


@router.get("/{corp_code}")
async def get_company(
    corp_code: str,
    db: AsyncSession = Depends(get_db),
) -> CompanyResponse:
    company = await db.execute(select(Company).where(Company.corp_code == corp_code))
    company_obj = company.scalar_one_or_none()
    if not company_obj:
        raise HTTPException(status_code=404, detail=f"기업 {corp_code}을 찾을 수 없습니다")

    filing_count = await db.execute(
        select(Filing).where(Filing.company_id == company_obj.id, Filing.status == "completed")
    )
    filings = list(filing_count.scalars().all())
    latest_year = max((f.report_year for f in filings), default=None)

    return CompanyResponse(
        corp_code=company_obj.corp_code,
        corp_name=company_obj.corp_name,
        stock_code=company_obj.stock_code,
        filing_count=len(filings),
        latest_report_year=latest_year,
    )
