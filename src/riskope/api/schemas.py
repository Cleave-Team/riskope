from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AnalyzeMode(str, Enum):
    """분석 실행 모드."""

    async_ = "async"
    sync = "sync"


class AnalyzeRequest(BaseModel):
    report_year: int | None = Field(default=None, description="사업연도 (미지정 시 최신)")
    force_refresh: bool = Field(default=False, description="캐시 무시하고 재분석")
    mode: AnalyzeMode = Field(default=AnalyzeMode.async_, description="async: 즉시 반환 후 폴링, sync: 분석 완료까지 대기 후 결과 반환")


class AnalyzeResponse(BaseModel):
    status: Literal["completed", "accepted"]
    job_id: str | None = None
    result: RiskProfileResponse | None = None
    cache_hit: bool = False
    filing_rcept_no: str = ""


class JobResponse(BaseModel):
    job_id: str
    status: str
    progress: int = 0
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class RiskFactorResponse(BaseModel):
    primary_category: str
    secondary_category: str
    tertiary_category: str
    primary_category_kr: str = ""
    secondary_category_kr: str = ""
    tertiary_category_kr: str = ""
    description_kr: str = ""
    supporting_quote: str | None = None
    original_tag: str | None = None
    quality_score: int | None = None
    similarity_score: float | None = None
    reasoning: str | None = None


class FilingResponse(BaseModel):
    rcept_no: str
    rcept_dt: date
    report_year: int
    report_nm: str | None = None
    status: str
    raw_text_length: int | None = None
    total_extracted: int | None = None
    total_validated: int | None = None
    risk_factor_count: int = 0
    processed_at: datetime | None = None
    s3_md_path: str | None = None


class RiskProfileResponse(BaseModel):
    corp_code: str
    corp_name: str
    filing: FilingResponse
    risk_factors: list[RiskFactorResponse]


class CompanyResponse(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: str | None = None
    filing_count: int = 0
    latest_report_year: int | None = None


class RiskFactorsQueryResponse(BaseModel):
    corp_code: str
    corp_name: str
    filings: list[FilingWithRiskFactors]
    total_risk_factors: int = 0


class FilingWithRiskFactors(BaseModel):
    filing: FilingResponse
    risk_factors: list[RiskFactorResponse]


class TaxonomyCategoryResponse(BaseModel):
    primary: str
    secondary: str
    tertiary: str
    description: str


# --- Corp Search ---


class CorpSearchMode(str, Enum):
    """기업 검색 모드."""

    fts = "fts"
    semantic = "semantic"
    hybrid = "hybrid"


class CorpSearchResult(BaseModel):
    corp_code: str
    corp_name: str
    corp_eng_name: str = ""
    stock_code: str = ""
    modify_date: str = ""
    score: float | None = None


class CorpSearchResponse(BaseModel):
    query: str
    mode: CorpSearchMode
    results: list[CorpSearchResult]
    total: int


class CorpUpdateResponse(BaseModel):
    total: int
    new: int
    changed: int
    deleted: int
    embedded: int


AnalyzeResponse.model_rebuild()
RiskFactorsQueryResponse.model_rebuild()
