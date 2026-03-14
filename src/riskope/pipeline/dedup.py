"""중복제거 — 동일 택소노미 카테고리에 매핑된 리스크 중 최고 품질만 유지.

논문 설계:
- 같은 tertiary 카테고리에 여러 리스크가 매핑될 수 있음
- 품질 점수가 가장 높은 매핑만 유지
- 동점 시 유사도 점수가 높은 것 우선
"""

from __future__ import annotations

import logging

from riskope.models import JudgeResult, ValidatedRiskFactor

logger = logging.getLogger(__name__)


def deduplicate_and_finalize(results: list[JudgeResult]) -> list[ValidatedRiskFactor]:
    """검증된 결과를 카테고리별 중복제거 후 최종 ValidatedRiskFactor로 변환.

    Args:
        results: Stage 3에서 통과한 JudgeResult 목록.

    Returns:
        중복제거된 최종 리스크 팩터 목록.
    """
    # 카테고리 key 기준으로 그룹핑, 최고 품질 유지
    best_by_category: dict[str, JudgeResult] = {}

    for result in results:
        key = result.mapping.category.key
        existing = best_by_category.get(key)

        if existing is None:
            best_by_category[key] = result
        elif _is_better(result, existing):
            best_by_category[key] = result

    # ValidatedRiskFactor로 변환
    factors: list[ValidatedRiskFactor] = []
    for result in best_by_category.values():
        factors.append(
            ValidatedRiskFactor(
                primary=result.mapping.category.primary,
                secondary=result.mapping.category.secondary,
                tertiary=result.mapping.category.tertiary,
                supporting_quote=result.mapping.extracted_risk.supporting_quote,
                original_tag=result.mapping.extracted_risk.tag,
                quality_score=result.quality_score.value,
                reasoning=result.reasoning,
                similarity_score=result.mapping.similarity_score,
            )
        )

    logger.info("중복제거: %d → %d 리스크 팩터", len(results), len(factors))
    return factors


def _is_better(candidate: JudgeResult, existing: JudgeResult) -> bool:
    """candidate가 existing보다 나은지 판단."""
    if candidate.quality_score > existing.quality_score:
        return True
    if (
        candidate.quality_score == existing.quality_score
        and candidate.mapping.similarity_score > existing.mapping.similarity_score
    ):
        return True
    return False
