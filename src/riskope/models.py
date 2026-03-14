"""파이프라인 전체에서 사용하는 데이터 모델."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


class TaxonomyCategory(BaseModel):
    """택소노미 3-tier 카테고리 하나."""

    primary: str = Field(description="1차 분류 (예: Strategic & Competitive)")
    secondary: str = Field(description="2차 분류 (예: Market Position And Competition)")
    tertiary: str = Field(description="3차 분류 (예: Interest Rate And Yield Curve Risk)")
    description: str = Field(description="카테고리 설명 (영문)")
    description_kr: str = Field(default="", description="카테고리 설명 (한국어)")
    key: str = Field(description="고유 키 (primary/secondary/tertiary 조합)")


# ---------------------------------------------------------------------------
# Stage 1 — LLM 추출 결과
# ---------------------------------------------------------------------------


class ExtractedRisk(BaseModel):
    """Stage 1에서 LLM이 추출한 개별 리스크."""

    tag: str = Field(description="리스크를 요약하는 자유형 태그")
    supporting_quote: str = Field(description="원문에서 가져온 근거 인용문")


class ExtractionResult(BaseModel):
    """Stage 1 전체 추출 결과."""

    risks: list[ExtractedRisk] = Field(default_factory=list)
    model: str = Field(default="", description="사용된 LLM 모델명")
    usage: dict[str, Any] = Field(default_factory=dict, description="토큰 사용량")


# ---------------------------------------------------------------------------
# Stage 2 — 임베딩 매핑 결과
# ---------------------------------------------------------------------------


class TaxonomyMapping(BaseModel):
    """Stage 2에서 임베딩 기반으로 매핑된 결과."""

    extracted_risk: ExtractedRisk
    category: TaxonomyCategory
    similarity_score: float = Field(description="코사인 유사도 점수")


# ---------------------------------------------------------------------------
# Stage 3 — LLM Judge 검증 결과
# ---------------------------------------------------------------------------


class QualityScore(IntEnum):
    """LLM Judge 품질 점수 (1-5)."""

    VERY_POOR = 1
    POOR = 2
    ADEQUATE = 3
    GOOD = 4
    EXCELLENT = 5


class JudgeResult(BaseModel):
    """Stage 3에서 LLM Judge가 평가한 결과."""

    mapping: TaxonomyMapping
    quality_score: QualityScore = Field(description="1-5 품질 점수")
    reasoning: str = Field(description="점수 판단 근거 (1문장)")


# ---------------------------------------------------------------------------
# 최종 출력
# ---------------------------------------------------------------------------


class ValidatedRiskFactor(BaseModel):
    """파이프라인 최종 출력 — 검증된 리스크 팩터 하나."""

    primary: str
    secondary: str
    tertiary: str
    supporting_quote: str
    original_tag: str
    quality_score: int
    reasoning: str
    similarity_score: float


class LowQualityMapping(BaseModel):
    """Judge에서 낮은 점수를 받은 매핑 (택소노미 개선 피드백용)."""

    mapping: TaxonomyMapping
    quality_score: int  # 1-3
    reasoning: str


class RefinementTestCase(BaseModel):
    """임베딩 분리 테스트 케이스."""

    text: str
    is_true_positive: bool
    source: str = ""  # where this test case came from


class RefinementResult(BaseModel):
    """택소노미 카테고리 하나에 대한 개선 결과."""

    category_key: str
    original_description: str
    refined_description: str
    original_separation: float  # avg_tp_sim - avg_fp_sim
    refined_separation: float
    improvement_pct: float
    num_low_quality_mappings: int
    failure_patterns: list[str]


class CompanyRiskProfile(BaseModel):
    """기업 하나의 리스크 프로필."""

    corp_code: str = Field(description="DART 고유번호")
    corp_name: str = Field(description="기업명")
    rcept_no: str = Field(description="접수번호")
    report_year: str = Field(description="보고서 연도")
    filing_date: str = Field(default="", description="공시일 YYYYMMDD")
    risk_factors: list[ValidatedRiskFactor] = Field(default_factory=list)
    raw_text_length: int = Field(default=0, description="원문 텍스트 길이")
    total_extracted: int = Field(default=0, description="Stage 1 추출 수")
    total_mapped: int = Field(default=0, description="Stage 2 매핑 수")
    total_validated: int = Field(default=0, description="Stage 3 통과 수")
    score_distribution: dict[int, int] = Field(
        default_factory=dict,
        description="Judge 점수 분포 {1: n, 2: n, ...}",
    )


# ---------------------------------------------------------------------------
# Section 4.3 — 산업 클러스터링 검증
# ---------------------------------------------------------------------------


class ClusteringResult(BaseModel):
    """산업 클러스터링 검증 결과."""

    n_companies: int = Field(description="분석 대상 기업 수")
    n_categories: int = Field(description="사용된 택소노미 카테고리 수")
    same_industry_mean_similarity: float = Field(description="동일 산업 평균 코사인 유사도")
    diff_industry_mean_similarity: float = Field(description="다른 산업 평균 코사인 유사도")
    relative_increase_pct: float = Field(description="상대적 증가율 (same - diff) / diff * 100")
    cohens_d: float = Field(description="Cohen's d 효과 크기")
    auc_score: float = Field(description="AUC-ROC 점수")
    p_value: float = Field(description="Welch t-test p-value")
    taxonomy_level: str = Field(default="tertiary", description="택소노미 레벨 (primary, secondary, tertiary)")
    industry_granularity: str = Field(default="", description="산업 분류 기준 (예: KSIC 2-digit)")
