from riskope.models import (
    ExtractedRisk,
    JudgeResult,
    QualityScore,
    TaxonomyCategory,
    TaxonomyMapping,
)
from riskope.pipeline.dedup import deduplicate_and_finalize


def _make_judge_result(
    category_key: str = "A/B/C",
    quality: int = 4,
    similarity: float = 0.9,
    tag: str = "test risk",
    quote: str = "test quote",
) -> JudgeResult:
    parts = category_key.split("/")
    cat = TaxonomyCategory(
        primary=parts[0],
        secondary=parts[1],
        tertiary=parts[2],
        description="desc",
        key=category_key,
    )
    risk = ExtractedRisk(tag=tag, supporting_quote=quote)
    mapping = TaxonomyMapping(
        extracted_risk=risk,
        category=cat,
        similarity_score=similarity,
    )
    return JudgeResult(
        mapping=mapping,
        quality_score=QualityScore(quality),
        reasoning="test reasoning",
    )


def test_empty_input():
    assert deduplicate_and_finalize([]) == []


def test_single_result():
    result = _make_judge_result(tag="solo risk", quote="solo quote")
    factors = deduplicate_and_finalize([result])
    assert len(factors) == 1
    assert factors[0].original_tag == "solo risk"
    assert factors[0].supporting_quote == "solo quote"
    assert factors[0].primary == "A"
    assert factors[0].secondary == "B"
    assert factors[0].tertiary == "C"
    assert factors[0].quality_score == 4
    assert factors[0].similarity_score == 0.9


def test_dedup_keeps_higher_quality():
    low = _make_judge_result(category_key="X/Y/Z", quality=2, similarity=0.9, tag="low")
    high = _make_judge_result(category_key="X/Y/Z", quality=5, similarity=0.8, tag="high")
    factors = deduplicate_and_finalize([low, high])
    assert len(factors) == 1
    assert factors[0].original_tag == "high"
    assert factors[0].quality_score == 5


def test_dedup_tiebreak_by_similarity():
    low_sim = _make_judge_result(category_key="X/Y/Z", quality=4, similarity=0.7, tag="low_sim")
    high_sim = _make_judge_result(category_key="X/Y/Z", quality=4, similarity=0.95, tag="high_sim")
    factors = deduplicate_and_finalize([low_sim, high_sim])
    assert len(factors) == 1
    assert factors[0].original_tag == "high_sim"
    assert factors[0].similarity_score == 0.95


def test_multiple_categories_preserved():
    r1 = _make_judge_result(category_key="A/B/C", tag="risk1")
    r2 = _make_judge_result(category_key="D/E/F", tag="risk2")
    r3 = _make_judge_result(category_key="G/H/I", tag="risk3")
    factors = deduplicate_and_finalize([r1, r2, r3])
    assert len(factors) == 3
    tags = {f.original_tag for f in factors}
    assert tags == {"risk1", "risk2", "risk3"}
