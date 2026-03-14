import pytest

from riskope.evaluation.metrics import AggregateEvaluation, CompanyEvaluation
from riskope.evaluation.evaluator import (
    extract_categories_from_ground_truth,
    extract_categories_from_profile,
    evaluate_single,
)
from riskope.models import CompanyRiskProfile, ValidatedRiskFactor


class TestCompanyEvaluation:
    def test_perfect_match(self):
        cats = {"a", "b", "c"}
        ev = CompanyEvaluation(ticker="X", filing_date="", predicted_categories=cats, ground_truth_categories=cats)
        assert ev.precision == 1.0
        assert ev.recall == 1.0
        assert ev.f1 == 1.0
        assert ev.jaccard == 1.0

    def test_no_overlap(self):
        ev = CompanyEvaluation(
            ticker="X",
            filing_date="",
            predicted_categories={"a", "b"},
            ground_truth_categories={"c", "d"},
        )
        assert ev.precision == 0.0
        assert ev.recall == 0.0
        assert ev.f1 == 0.0
        assert ev.jaccard == 0.0

    def test_partial_overlap(self):
        ev = CompanyEvaluation(
            ticker="X",
            filing_date="",
            predicted_categories={"a", "b", "c"},
            ground_truth_categories={"b", "c", "d"},
        )
        assert ev.true_positives == {"b", "c"}
        assert ev.false_positives == {"a"}
        assert ev.false_negatives == {"d"}
        assert ev.precision == pytest.approx(2 / 3)
        assert ev.recall == pytest.approx(2 / 3)
        assert ev.jaccard == pytest.approx(2 / 4)

    def test_empty_predictions(self):
        ev = CompanyEvaluation(
            ticker="X",
            filing_date="",
            predicted_categories=set(),
            ground_truth_categories={"a"},
        )
        assert ev.precision == 0.0
        assert ev.recall == 0.0
        assert ev.f1 == 0.0

    def test_empty_ground_truth(self):
        ev = CompanyEvaluation(
            ticker="X",
            filing_date="",
            predicted_categories={"a"},
            ground_truth_categories=set(),
        )
        assert ev.precision == 0.0
        assert ev.recall == 0.0


class TestAggregateEvaluation:
    def test_macro_averages(self):
        ev1 = CompanyEvaluation(
            ticker="A",
            filing_date="",
            predicted_categories={"x", "y"},
            ground_truth_categories={"x", "y"},
        )
        ev2 = CompanyEvaluation(
            ticker="B",
            filing_date="",
            predicted_categories={"x"},
            ground_truth_categories={"x", "y"},
        )
        agg = AggregateEvaluation(companies=[ev1, ev2])
        assert agg.macro_precision == pytest.approx((1.0 + 1.0) / 2)
        assert agg.macro_recall == pytest.approx((1.0 + 0.5) / 2)

    def test_micro_averages(self):
        ev1 = CompanyEvaluation(
            ticker="A",
            filing_date="",
            predicted_categories={"x", "y"},
            ground_truth_categories={"x", "y", "z"},
        )
        ev2 = CompanyEvaluation(
            ticker="B",
            filing_date="",
            predicted_categories={"a", "b"},
            ground_truth_categories={"a"},
        )
        agg = AggregateEvaluation(companies=[ev1, ev2])
        assert agg.micro_precision == pytest.approx(3 / 4)
        assert agg.micro_recall == pytest.approx(3 / 4)

    def test_empty(self):
        agg = AggregateEvaluation()
        assert agg.macro_f1 == 0.0
        assert agg.micro_f1 == 0.0


class TestExtractCategories:
    def test_from_ground_truth_filters_by_date(self):
        results = [
            {"tertiary_category": "a", "filing_date": "2024-01-01"},
            {"tertiary_category": "b", "filing_date": "2024-01-01"},
            {"tertiary_category": "c", "filing_date": "2023-01-01"},
        ]
        cats = extract_categories_from_ground_truth(results, filing_date="2024-01-01")
        assert cats == {"a", "b"}

    def test_from_ground_truth_uses_latest_date(self):
        results = [
            {"tertiary_category": "a", "filing_date": "2024-01-01"},
            {"tertiary_category": "b", "filing_date": "2023-01-01"},
        ]
        cats = extract_categories_from_ground_truth(results)
        assert cats == {"a"}

    def test_from_ground_truth_empty(self):
        assert extract_categories_from_ground_truth([]) == set()

    def test_from_profile(self):
        profile = CompanyRiskProfile(
            corp_code="",
            corp_name="TEST",
            rcept_no="",
            report_year="",
            risk_factors=[
                ValidatedRiskFactor(
                    primary="p",
                    secondary="s",
                    tertiary="data_breaches_and_cyber_attacks",
                    supporting_quote="q",
                    original_tag="t",
                    quality_score=5,
                    reasoning="r",
                    similarity_score=0.9,
                ),
                ValidatedRiskFactor(
                    primary="p",
                    secondary="s",
                    tertiary="climate_change_and_environmental_impact",
                    supporting_quote="q",
                    original_tag="t",
                    quality_score=4,
                    reasoning="r",
                    similarity_score=0.8,
                ),
            ],
        )
        cats = extract_categories_from_profile(profile)
        assert cats == {"data_breaches_and_cyber_attacks", "climate_change_and_environmental_impact"}


class TestEvaluateSingle:
    def test_returns_company_evaluation(self):
        ev = evaluate_single(
            predicted={"a", "b"},
            ground_truth={"b", "c"},
            ticker="AAPL",
            filing_date="2024-11-01",
        )
        assert ev.ticker == "AAPL"
        assert ev.precision == pytest.approx(0.5)
        assert ev.recall == pytest.approx(0.5)
