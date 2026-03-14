import numpy as np
import pytest

from riskope.models import (
    ExtractedRisk,
    JudgeResult,
    LowQualityMapping,
    QualityScore,
    RefinementResult,
    RefinementTestCase,
    TaxonomyCategory,
    TaxonomyMapping,
)
from riskope.pipeline.refiner import TaxonomyRefiner


def _make_category(primary: str = "P", secondary: str = "S", tertiary: str = "T") -> TaxonomyCategory:
    return TaxonomyCategory(
        primary=primary,
        secondary=secondary,
        tertiary=tertiary,
        description="test description",
        key=f"{primary}/{secondary}/{tertiary}",
    )


def _make_judge_result(
    cat_key: str = "P/S/T",
    score: int = 5,
    quote: str = "test quote",
) -> JudgeResult:
    parts = cat_key.split("/")
    cat = _make_category(*parts)
    mapping = TaxonomyMapping(
        extracted_risk=ExtractedRisk(tag="tag", supporting_quote=quote),
        category=cat,
        similarity_score=0.8,
    )
    return JudgeResult(
        mapping=mapping,
        quality_score=QualityScore(score),
        reasoning="test",
    )


class TestIdentifyProblematicCategories:
    def test_empty_results(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        assert refiner.identify_problematic_categories([], top_n=5) == []

    def test_all_high_quality(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        results = [_make_judge_result(score=5), _make_judge_result(score=4)]
        assert refiner.identify_problematic_categories(results) == []

    def test_sorted_by_count_descending(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        results = [
            _make_judge_result("A/B/C", score=2),
            _make_judge_result("A/B/C", score=1),
            _make_judge_result("A/B/C", score=3),
            _make_judge_result("X/Y/Z", score=2),
            _make_judge_result("P/Q/R", score=1),
            _make_judge_result("P/Q/R", score=5),
        ]
        result = refiner.identify_problematic_categories(results, top_n=3)
        assert result[0] == ("A/B/C", 3)
        assert result[1][1] <= result[0][1]

    def test_top_n_limits(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        results = [_make_judge_result(f"cat{i}/S/T", score=1) for i in range(10)]
        assert len(refiner.identify_problematic_categories(results, top_n=3)) == 3

    def test_threshold_is_4(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        results = [
            _make_judge_result(score=3),
            _make_judge_result(score=4),
            _make_judge_result(score=5),
        ]
        problematic = refiner.identify_problematic_categories(results, top_n=5)
        assert len(problematic) == 1
        assert problematic[0][1] == 1


class TestComputeSeparation:
    def test_perfect_separation(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        desc_emb = np.array([1.0, 0.0, 0.0])
        tc_embs = np.array(
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        )
        test_cases = [
            RefinementTestCase(text="tp", is_true_positive=True),
            RefinementTestCase(text="fp", is_true_positive=False),
        ]
        sep = refiner.compute_separation(desc_emb, tc_embs, test_cases)
        assert sep > 0

    def test_no_test_cases(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        assert refiner.compute_separation(np.array([1, 0, 0]), np.array([]).reshape(0, 3), []) == 0.0

    def test_all_true_positives(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        desc_emb = np.array([1.0, 0.0])
        tc_embs = np.array([[1.0, 0.0], [0.9, 0.1]])
        test_cases = [
            RefinementTestCase(text="a", is_true_positive=True),
            RefinementTestCase(text="b", is_true_positive=True),
        ]
        sep = refiner.compute_separation(desc_emb, tc_embs, test_cases)
        assert sep > 0


class TestBuildTestCases:
    def test_builds_from_mappings(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        cat = _make_category()
        high_quality = [
            TaxonomyMapping(
                extracted_risk=ExtractedRisk(tag="t", supporting_quote="good"),
                category=cat,
                similarity_score=0.9,
            )
        ]
        low_quality = [
            LowQualityMapping(
                mapping=TaxonomyMapping(
                    extracted_risk=ExtractedRisk(tag="t", supporting_quote="bad"),
                    category=cat,
                    similarity_score=0.3,
                ),
                quality_score=2,
                reasoning="mismatch",
            )
        ]
        cases = refiner._build_test_cases(high_quality, low_quality)
        assert len(cases) == 2
        assert cases[0].is_true_positive is True
        assert cases[1].is_true_positive is False

    def test_filters_score_3_as_not_fp(self):
        refiner = TaxonomyRefiner.__new__(TaxonomyRefiner)
        cat = _make_category()
        low_quality = [
            LowQualityMapping(
                mapping=TaxonomyMapping(
                    extracted_risk=ExtractedRisk(tag="t", supporting_quote="ok"),
                    category=cat,
                    similarity_score=0.5,
                ),
                quality_score=3,
                reasoning="borderline",
            )
        ]
        cases = refiner._build_test_cases([], low_quality)
        assert len(cases) == 0


class TestRefinementModels:
    def test_refinement_result_creation(self):
        result = RefinementResult(
            category_key="P/S/T",
            original_description="old",
            refined_description="new",
            original_separation=0.064,
            refined_separation=0.132,
            improvement_pct=106.25,
            num_low_quality_mappings=10,
            failure_patterns=["pattern1", "pattern2"],
        )
        assert result.improvement_pct == 106.25
        assert len(result.failure_patterns) == 2

    def test_refinement_test_case(self):
        tc = RefinementTestCase(text="hello", is_true_positive=True, source="test")
        assert tc.text == "hello"
        assert tc.source == "test"
