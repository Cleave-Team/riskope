import json

from riskope.models import (
    CompanyRiskProfile,
    ExtractedRisk,
    ExtractionResult,
    QualityScore,
    ValidatedRiskFactor,
)


def test_extracted_risk_creation():
    risk = ExtractedRisk(tag="currency risk", supporting_quote="환율 변동에 따른 위험")
    assert risk.tag == "currency risk"
    assert risk.supporting_quote == "환율 변동에 따른 위험"


def test_extraction_result_defaults():
    result = ExtractionResult()
    assert result.risks == []
    assert result.model == ""
    assert result.usage == {}


def test_quality_score_enum():
    assert QualityScore.VERY_POOR == 1
    assert QualityScore.POOR == 2
    assert QualityScore.ADEQUATE == 3
    assert QualityScore.GOOD == 4
    assert QualityScore.EXCELLENT == 5

    assert QualityScore.VERY_POOR.name == "VERY_POOR"
    assert QualityScore.EXCELLENT.name == "EXCELLENT"

    assert list(QualityScore) == [1, 2, 3, 4, 5]


def test_validated_risk_factor():
    factor = ValidatedRiskFactor(
        primary="Strategic And Competitive",
        secondary="Market Position And Competition",
        tertiary="Competitive Pressure And Market Share Loss",
        supporting_quote="경쟁 심화로 시장점유율 하락",
        original_tag="competition risk",
        quality_score=4,
        reasoning="Strong alignment with taxonomy category",
        similarity_score=0.92,
    )
    assert factor.primary == "Strategic And Competitive"
    assert factor.quality_score == 4
    assert factor.similarity_score == 0.92


def test_company_risk_profile_serialization():
    profile = CompanyRiskProfile(
        corp_code="00126380",
        corp_name="삼성전자",
        rcept_no="20240315000123",
        report_year="2023",
        risk_factors=[
            ValidatedRiskFactor(
                primary="Financial",
                secondary="Market Risk",
                tertiary="Currency Risk",
                supporting_quote="환율 변동 위험",
                original_tag="fx risk",
                quality_score=5,
                reasoning="Direct match",
                similarity_score=0.95,
            )
        ],
        raw_text_length=50000,
        total_extracted=25,
        total_mapped=20,
        total_validated=15,
    )

    dumped = profile.model_dump()
    assert dumped["corp_code"] == "00126380"
    assert dumped["corp_name"] == "삼성전자"
    assert len(dumped["risk_factors"]) == 1
    assert dumped["total_validated"] == 15

    json_str = json.dumps(dumped, ensure_ascii=False)
    assert "삼성전자" in json_str
    assert "환율 변동 위험" in json_str


def test_company_risk_profile_new_fields():
    profile = CompanyRiskProfile(
        corp_code="00126380",
        corp_name="삼성전자",
        rcept_no="20240315000123",
        report_year="2023",
        filing_date="20240315",
        score_distribution={4: 10, 5: 15, 2: 5},
    )
    assert profile.filing_date == "20240315"
    assert profile.score_distribution[5] == 15

    dumped = profile.model_dump()
    assert dumped["filing_date"] == "20240315"
    assert dumped["score_distribution"] == {4: 10, 5: 15, 2: 5}


def test_company_risk_profile_defaults_backward_compat():
    profile = CompanyRiskProfile(
        corp_code="",
        corp_name="test",
        rcept_no="123",
        report_year="2023",
    )
    assert profile.filing_date == ""
    assert profile.score_distribution == {}
