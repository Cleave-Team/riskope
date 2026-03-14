"""Section 4.3 — 산업 클러스터링 검증.

택소노미가 경제적으로 의미 있는 구조를 포착하는지 검증한다.
동일 산업 기업 간 리스크 프로필 유사도가 다른 산업 대비 유의하게 높은지 통계적으로 테스트한다.
"""

from __future__ import annotations

import logging
from itertools import combinations

import numpy as np

from riskope.models import ClusteringResult, CompanyRiskProfile

logger = logging.getLogger(__name__)

_TAXONOMY_LEVEL_FIELDS = {
    "primary": ("primary",),
    "secondary": ("primary", "secondary"),
    "tertiary": ("primary", "secondary", "tertiary"),
}


class IndustryClusteringValidator:
    def __init__(self, taxonomy_level: str = "tertiary") -> None:
        if taxonomy_level not in _TAXONOMY_LEVEL_FIELDS:
            msg = f"taxonomy_level must be one of {list(_TAXONOMY_LEVEL_FIELDS)}"
            raise ValueError(msg)
        self._taxonomy_level = taxonomy_level

    # ------------------------------------------------------------------
    # Step A: binary risk matrix
    # ------------------------------------------------------------------

    def build_risk_matrix(
        self,
        profiles: list[CompanyRiskProfile],
        level: str | None = None,
    ) -> tuple[np.ndarray, list[str], list[str]]:
        """R ∈ {0,1}^(n×k).  Returns (matrix, company_names, category_keys)."""
        level = level or self._taxonomy_level
        fields = _TAXONOMY_LEVEL_FIELDS[level]

        all_keys: set[str] = set()
        per_company: list[set[str]] = []
        company_names: list[str] = []

        for profile in profiles:
            keys: set[str] = set()
            for rf in profile.risk_factors:
                key = "/".join(getattr(rf, f) for f in fields)
                keys.add(key)
            per_company.append(keys)
            all_keys.update(keys)
            company_names.append(profile.corp_name)

        sorted_keys = sorted(all_keys)
        key_to_idx = {k: i for i, k in enumerate(sorted_keys)}

        n, k = len(profiles), len(sorted_keys)
        matrix = np.zeros((n, k), dtype=np.float64)
        for i, keys in enumerate(per_company):
            for key in keys:
                matrix[i, key_to_idx[key]] = 1.0

        return matrix, company_names, sorted_keys

    # ------------------------------------------------------------------
    # Step B: IDF weighting — w_j = log(n / (df_j + 1))
    # ------------------------------------------------------------------

    def apply_idf_weights(self, matrix: np.ndarray) -> np.ndarray:
        n = matrix.shape[0]
        doc_freq = matrix.sum(axis=0)
        idf = np.log(n / (doc_freq + 1))
        return matrix * idf

    # ------------------------------------------------------------------
    # Step C: pairwise cosine similarity
    # ------------------------------------------------------------------

    @staticmethod
    def compute_pairwise_similarity(weighted_matrix: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(weighted_matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = weighted_matrix / norms
        return normalized @ normalized.T

    # ------------------------------------------------------------------
    # Step D–F: full validation pipeline
    # ------------------------------------------------------------------

    def validate(
        self,
        profiles: list[CompanyRiskProfile],
        industry_codes: dict[str, str],
        level: str | None = None,
    ) -> ClusteringResult:
        level = level or self._taxonomy_level

        if len(profiles) < 2:
            msg = "At least 2 company profiles are required"
            raise ValueError(msg)

        matrix, company_names, category_keys = self.build_risk_matrix(profiles, level)
        weighted = self.apply_idf_weights(matrix)
        sim_matrix = self.compute_pairwise_similarity(weighted)

        same_sims: list[float] = []
        diff_sims: list[float] = []

        for i, j in combinations(range(len(company_names)), 2):
            name_i, name_j = company_names[i], company_names[j]
            code_i = industry_codes.get(name_i, "")
            code_j = industry_codes.get(name_j, "")

            if not code_i or not code_j:
                logger.warning("산업 코드 누락: %s 또는 %s — 해당 쌍 건너뜀", name_i, name_j)
                continue

            similarity = float(sim_matrix[i, j])
            if code_i == code_j:
                same_sims.append(similarity)
            else:
                diff_sims.append(similarity)

        same_arr = np.array(same_sims, dtype=np.float64)
        diff_arr = np.array(diff_sims, dtype=np.float64)

        if len(same_arr) == 0 or len(diff_arr) == 0:
            msg = "동일 산업 또는 다른 산업 쌍이 없음 — 최소 2개 산업에 각 2개 이상 기업 필요"
            raise ValueError(msg)

        same_mean = float(same_arr.mean())
        diff_mean = float(diff_arr.mean())
        rel_increase = (same_mean - diff_mean) / diff_mean * 100 if diff_mean != 0 else 0.0

        d = _cohens_d(same_arr, diff_arr)
        p = _welch_ttest_p(same_arr, diff_arr)
        auc = _compute_auc(
            np.concatenate([np.ones(len(same_arr)), np.zeros(len(diff_arr))]),
            np.concatenate([same_arr, diff_arr]),
        )

        return ClusteringResult(
            n_companies=len(profiles),
            n_categories=len(category_keys),
            same_industry_mean_similarity=same_mean,
            diff_industry_mean_similarity=diff_mean,
            relative_increase_pct=rel_increase,
            cohens_d=d,
            auc_score=auc,
            p_value=p,
            taxonomy_level=level,
            industry_granularity="",
        )


# ======================================================================
# Statistics helpers (numpy only — no scipy dependency)
# ======================================================================


def _cohens_d(same: np.ndarray, diff: np.ndarray) -> float:
    n1, n2 = len(same), len(diff)
    var1, var2 = float(same.var(ddof=1)), float(diff.var(ddof=1))
    pooled_std = np.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
    if pooled_std == 0:
        return 0.0
    return float((same.mean() - diff.mean()) / pooled_std)


def _welch_ttest_p(a: np.ndarray, b: np.ndarray) -> float:
    """Welch's t-test (unequal variance) — returns two-sided p-value."""
    n1, n2 = len(a), len(b)
    m1, m2 = float(a.mean()), float(b.mean())
    v1, v2 = float(a.var(ddof=1)), float(b.var(ddof=1))

    se = np.sqrt(v1 / n1 + v2 / n2)
    if se == 0:
        return 0.0

    t_stat = (m1 - m2) / se

    # Welch–Satterthwaite degrees of freedom
    num = (v1 / n1 + v2 / n2) ** 2
    denom = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    if denom == 0:
        return 0.0
    df = num / denom

    # two-sided p-value via regularised incomplete beta function
    return float(_t_cdf_two_sided(abs(t_stat), df))


def _t_cdf_two_sided(t: float, df: float) -> float:
    """P(|T| >= t) for Student's t with *df* degrees of freedom.

    Uses the relationship: p = I_{df/(df+t^2)}(df/2, 1/2)  (regularised
    incomplete beta).  The incomplete beta is evaluated via a continued-fraction
    expansion accurate to ~1e-12.
    """
    x = df / (df + t * t)
    p = _regularised_beta(x, df / 2.0, 0.5)
    return p


def _regularised_beta(x: float, a: float, b: float) -> float:
    """I_x(a, b) via Lentz continued-fraction (DLMF 8.17.22)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0

    # Use log-space for the prefactor to avoid overflow
    ln_prefactor = _ln_beta_prefactor(x, a, b)

    # Lentz continued fraction
    cf = _beta_cf(x, a, b)
    val = np.exp(ln_prefactor) * cf / a

    # decide which branch gives better convergence
    if x < (a + 1) / (a + b + 2):
        return val
    return 1.0 - _regularised_beta(1.0 - x, b, a)


def _ln_beta_prefactor(x: float, a: float, b: float) -> float:
    """log( x^a * (1-x)^b / B(a,b) )"""
    from math import lgamma

    return a * np.log(x) + b * np.log(1 - x) - (lgamma(a) + lgamma(b) - lgamma(a + b))


def _beta_cf(x: float, a: float, b: float, max_iter: int = 200, eps: float = 1e-14) -> float:
    """Continued-fraction evaluation for I_x(a,b)."""
    tiny = 1e-30
    f = tiny
    c = tiny
    d = 0.0

    for m in range(max_iter):
        if m == 0:
            alpha_m = 1.0
        else:
            k = m
            if k % 2 == 0:
                half = k // 2
                alpha_m = (half * (b - half) * x) / ((a + 2 * half - 1) * (a + 2 * half))
            else:
                half = (k - 1) // 2
                alpha_m = -((a + half) * (a + b + half) * x) / ((a + 2 * half) * (a + 2 * half + 1))

        d = 1.0 + alpha_m * d
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d

        c = 1.0 + alpha_m / c
        if abs(c) < tiny:
            c = tiny

        f *= d * c
        if abs(d * c - 1.0) < eps:
            break

    return f


def _compute_auc(labels: np.ndarray, scores: np.ndarray) -> float:
    """AUC-ROC via Mann–Whitney U statistic (O(n log n))."""
    n_pos = int(labels.sum())
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.0

    # Sort by score descending, break ties by label descending (positive first)
    order = np.lexsort((labels, -scores))

    tp = 0
    fp = 0
    prev_score = scores[order[0]] + 1.0
    tpr_points = [0.0]
    fpr_points = [0.0]

    for idx in order:
        score = scores[idx]
        if score != prev_score:
            tpr_points.append(tp / n_pos)
            fpr_points.append(fp / n_neg)
            prev_score = score
        if labels[idx] == 1:
            tp += 1
        else:
            fp += 1

    tpr_points.append(tp / n_pos)
    fpr_points.append(fp / n_neg)

    return float(np.trapezoid(tpr_points, fpr_points))
