import numpy as np
import pytest

from riskope.clustering.validator import (
    IndustryClusteringValidator,
    _cohens_d,
    _compute_auc,
    _welch_ttest_p,
)
from riskope.models import CompanyRiskProfile, ValidatedRiskFactor


def _make_profile(
    name: str,
    risk_keys: list[tuple[str, str, str]],
) -> CompanyRiskProfile:
    return CompanyRiskProfile(
        corp_code="",
        corp_name=name,
        rcept_no="test",
        report_year="2023",
        risk_factors=[
            ValidatedRiskFactor(
                primary=p,
                secondary=s,
                tertiary=t,
                supporting_quote="q",
                original_tag="tag",
                quality_score=5,
                reasoning="r",
                similarity_score=0.9,
            )
            for p, s, t in risk_keys
        ],
    )


class TestBuildRiskMatrix:
    def test_basic_matrix(self):
        profiles = [
            _make_profile("A", [("P1", "S1", "T1"), ("P1", "S1", "T2")]),
            _make_profile("B", [("P1", "S1", "T1")]),
        ]
        validator = IndustryClusteringValidator()
        matrix, names, keys = validator.build_risk_matrix(profiles)

        assert names == ["A", "B"]
        assert len(keys) == 2
        assert matrix.shape == (2, 2)
        assert matrix.sum() == 3

    def test_empty_profile(self):
        profiles = [
            _make_profile("A", [("P", "S", "T")]),
            _make_profile("B", []),
        ]
        validator = IndustryClusteringValidator()
        matrix, names, keys = validator.build_risk_matrix(profiles)
        assert matrix[1].sum() == 0

    def test_primary_level(self):
        profiles = [
            _make_profile("A", [("P1", "S1", "T1"), ("P1", "S2", "T2")]),
        ]
        validator = IndustryClusteringValidator(taxonomy_level="primary")
        matrix, _, keys = validator.build_risk_matrix(profiles, level="primary")
        assert len(keys) == 1


class TestIdfWeighting:
    def test_rare_risk_higher_weight(self):
        validator = IndustryClusteringValidator()
        matrix = np.array(
            [
                [1, 1],
                [0, 1],
                [0, 1],
                [0, 1],
            ],
            dtype=np.float64,
        )
        weighted = validator.apply_idf_weights(matrix)
        assert weighted[0, 0] > weighted[0, 1]

    def test_zero_column_stays_zero(self):
        validator = IndustryClusteringValidator()
        matrix = np.array([[0, 1], [0, 1]], dtype=np.float64)
        weighted = validator.apply_idf_weights(matrix)
        assert weighted[0, 0] == 0.0
        assert weighted[1, 0] == 0.0


class TestPairwiseSimilarity:
    def test_identical_vectors(self):
        matrix = np.array([[1.0, 2.0], [1.0, 2.0]])
        sim = IndustryClusteringValidator.compute_pairwise_similarity(matrix)
        np.testing.assert_almost_equal(sim[0, 1], 1.0)

    def test_orthogonal_vectors(self):
        matrix = np.array([[1.0, 0.0], [0.0, 1.0]])
        sim = IndustryClusteringValidator.compute_pairwise_similarity(matrix)
        np.testing.assert_almost_equal(sim[0, 1], 0.0)

    def test_zero_vector(self):
        matrix = np.array([[1.0, 0.0], [0.0, 0.0]])
        sim = IndustryClusteringValidator.compute_pairwise_similarity(matrix)
        assert sim[0, 1] == 0.0


class TestCohensD:
    def test_large_effect(self):
        same = np.array([0.5, 0.6, 0.7, 0.8])
        diff = np.array([0.1, 0.2, 0.15, 0.05])
        d = _cohens_d(same, diff)
        assert d > 0.8

    def test_no_effect(self):
        vals = np.array([0.5, 0.5, 0.5])
        d = _cohens_d(vals, vals)
        assert d == 0.0

    def test_zero_std(self):
        a = np.array([1.0, 1.0, 1.0])
        b = np.array([1.0, 1.0, 1.0])
        d = _cohens_d(a, b)
        assert d == 0.0


class TestWelchTTest:
    def test_significantly_different(self):
        a = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
        b = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        p = _welch_ttest_p(a, b)
        assert p < 0.01

    def test_identical_means(self):
        a = np.array([5.0, 5.0, 5.0])
        b = np.array([5.0, 5.0, 5.0])
        p = _welch_ttest_p(a, b)
        assert p == 0.0


class TestComputeAuc:
    def test_perfect_classifier(self):
        labels = np.array([1, 1, 0, 0])
        scores = np.array([0.9, 0.8, 0.2, 0.1])
        auc = _compute_auc(labels, scores)
        assert auc == pytest.approx(1.0, abs=0.01)

    def test_random_classifier(self):
        np.random.seed(42)
        n = 1000
        labels = np.concatenate([np.ones(n // 2), np.zeros(n // 2)])
        scores = np.random.rand(n)
        auc = _compute_auc(labels, scores)
        assert 0.4 < auc < 0.6

    def test_no_positives(self):
        assert _compute_auc(np.array([0, 0]), np.array([0.5, 0.5])) == 0.0

    def test_no_negatives(self):
        assert _compute_auc(np.array([1, 1]), np.array([0.5, 0.5])) == 0.0


class TestValidate:
    def test_minimum_valid_input(self):
        profiles = [
            _make_profile("A", [("P1", "S1", "T1"), ("P1", "S1", "T2"), ("P1", "S1", "T3")]),
            _make_profile("B", [("P1", "S1", "T1"), ("P1", "S1", "T2")]),
            _make_profile("C", [("P2", "S2", "T4"), ("P2", "S2", "T5"), ("P2", "S2", "T6")]),
            _make_profile("D", [("P2", "S2", "T4"), ("P2", "S2", "T5")]),
        ]
        industry_codes = {"A": "26", "B": "26", "C": "63", "D": "63"}

        validator = IndustryClusteringValidator()
        result = validator.validate(profiles, industry_codes)

        assert result.n_companies == 4
        assert result.same_industry_mean_similarity > result.diff_industry_mean_similarity
        assert result.auc_score > 0.5

    def test_too_few_companies(self):
        profiles = [_make_profile("A", [("P", "S", "T")])]
        with pytest.raises(ValueError, match="At least 2"):
            IndustryClusteringValidator().validate(profiles, {"A": "26"})

    def test_invalid_taxonomy_level(self):
        with pytest.raises(ValueError, match="taxonomy_level"):
            IndustryClusteringValidator(taxonomy_level="invalid")
