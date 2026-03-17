"""Stage 4: 자율 택소노미 개선 (Autonomous Taxonomy Refinement).

논문 Section 4.2 구현:
- 문제 카테고리 식별 (Judge 저품질 매핑 분석)
- 실패 패턴 LLM 분석
- 후보 description 생성
- 임베딩 기반 분리도 테스트로 최적 description 선택
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter

import numpy as np
from google import genai
from google.genai import types
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from riskope.models import (
    JudgeResult,
    LowQualityMapping,
    RefinementResult,
    RefinementTestCase,
    TaxonomyMapping,
)
from riskope.tracing import observe, traced_gemini_generate

logger = logging.getLogger(__name__)

_TASK_INSTRUCTION = "한국어 기업 사업보고서의 리스크 텍스트를 가장 적합한 택소노미 카테고리로 분류하세요."

_FAILURE_ANALYSIS_SYSTEM_PROMPT = """\
당신은 리스크 분류 시스템의 품질 분석 전문가입니다.

아래에 특정 택소노미 카테고리에 매핑되었으나 Judge가 낮은 점수(1-3)를 부여한 매핑들이 제공됩니다.
이 매핑들의 실패 패턴을 분석하여 카테고리 description의 어떤 부분이 오분류를 유발하는지 식별하세요.

각 패턴에 대해 간결한 설명과 대략적인 비율(%)을 제공하세요.
"""

_DESCRIPTION_GEN_SYSTEM_PROMPT = """\
당신은 리스크 택소노미 카테고리의 description을 개선하는 전문가입니다.

주어진 실패 패턴들을 해결하면서 원래 의도를 보존하는 개선된 description 후보들을 생성하세요.
각 후보는 특정 실패 패턴을 해결하도록 설계되어야 합니다.
Description은 영문으로 작성하세요.
"""


class _FailurePatterns(BaseModel):
    patterns: list[str] = Field(description="식별된 실패 패턴 목록")


class _DescriptionCandidates(BaseModel):
    candidates: list[str] = Field(description="후보 description 목록 (3-5개)")


class TaxonomyRefiner:
    def __init__(
        self,
        gemini_client: genai.Client,
        openai_client: AsyncOpenAI,
        analysis_model: str = "gemini-2.5-flash",
        embedding_model: str = "text-embedding-3-small",
        embedding_dimensions: int = 1536,
        max_retries: int = 3,
    ) -> None:
        self._gemini = gemini_client
        self._openai = openai_client
        self._analysis_model = analysis_model
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._max_retries = max_retries

    def identify_problematic_categories(
        self,
        all_judge_results: list[JudgeResult],
        top_n: int = 5,
    ) -> list[tuple[str, int]]:
        low_quality_counts: Counter[str] = Counter()
        for jr in all_judge_results:
            if jr.quality_score < 4:
                low_quality_counts[jr.mapping.category.key] += 1
        return low_quality_counts.most_common(top_n)

    def _collect_low_quality_mappings(
        self,
        all_judge_results: list[JudgeResult],
        category_key: str,
    ) -> list[LowQualityMapping]:
        results: list[LowQualityMapping] = []
        for jr in all_judge_results:
            if jr.mapping.category.key == category_key and jr.quality_score < 4:
                results.append(
                    LowQualityMapping(
                        mapping=jr.mapping,
                        quality_score=int(jr.quality_score),
                        reasoning=jr.reasoning,
                    )
                )
        return results

    def _collect_high_quality_mappings(
        self,
        all_judge_results: list[JudgeResult],
        category_key: str,
    ) -> list[TaxonomyMapping]:
        return [
            jr.mapping for jr in all_judge_results if jr.mapping.category.key == category_key and jr.quality_score >= 4
        ]

    async def analyze_failure_patterns(
        self,
        category_description: str,
        low_quality_mappings: list[LowQualityMapping],
    ) -> list[str]:
        mapping_details = "\n\n".join(
            f"--- 매핑 {i + 1} (점수: {lqm.quality_score}) ---\n"
            f"인용문: {lqm.mapping.extracted_risk.supporting_quote}\n"
            f"Judge 판단: {lqm.reasoning}"
            for i, lqm in enumerate(low_quality_mappings)
        )

        user_message = (
            f"## 카테고리 Description\n{category_description}\n\n"
            f"## 저품질 매핑 목록 ({len(low_quality_mappings)}개)\n{mapping_details}"
        )

        for attempt in range(1 + self._max_retries):
            try:
                response = await traced_gemini_generate(
                    self._gemini,
                    model=self._analysis_model,
                    contents=[user_message],
                    config=types.GenerateContentConfig(
                        system_instruction=_FAILURE_ANALYSIS_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=_FailurePatterns,
                        temperature=0.0,
                    ),
                    name="gemini-failure-analysis",
                )
                parsed = json.loads(response.text)
                patterns = parsed.get("patterns", [])
                if patterns:
                    return patterns
            except Exception:
                logger.exception(
                    "실패 패턴 분석 호출 실패 (attempt %d/%d)",
                    attempt + 1,
                    1 + self._max_retries,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                return []

            if attempt < self._max_retries:
                await asyncio.sleep(2**attempt)

        return []

    async def generate_candidate_descriptions(
        self,
        original_description: str,
        failure_patterns: list[str],
    ) -> list[str]:
        patterns_text = "\n".join(f"- {p}" for p in failure_patterns)
        user_message = (
            f"## 원래 Description\n{original_description}\n\n"
            f"## 식별된 실패 패턴\n{patterns_text}\n\n"
            "위 실패 패턴을 해결하는 개선된 description 후보 3-5개를 생성하세요."
        )

        for attempt in range(1 + self._max_retries):
            try:
                response = await traced_gemini_generate(
                    self._gemini,
                    model=self._analysis_model,
                    contents=[user_message],
                    config=types.GenerateContentConfig(
                        system_instruction=_DESCRIPTION_GEN_SYSTEM_PROMPT,
                        response_mime_type="application/json",
                        response_schema=_DescriptionCandidates,
                        temperature=0.7,
                    ),
                    name="gemini-description-generation",
                )
                parsed = json.loads(response.text)
                candidates = parsed.get("candidates", [])
                if candidates:
                    return candidates
            except Exception:
                logger.exception(
                    "후보 description 생성 실패 (attempt %d/%d)",
                    attempt + 1,
                    1 + self._max_retries,
                )
                if attempt < self._max_retries:
                    await asyncio.sleep(2**attempt)
                    continue
                return []

            if attempt < self._max_retries:
                await asyncio.sleep(2**attempt)

        return []

    def _build_test_cases(
        self,
        high_quality_mappings: list[TaxonomyMapping],
        low_quality_mappings: list[LowQualityMapping],
    ) -> list[RefinementTestCase]:
        test_cases: list[RefinementTestCase] = []

        for m in high_quality_mappings:
            test_cases.append(
                RefinementTestCase(
                    text=m.extracted_risk.supporting_quote,
                    is_true_positive=True,
                    source="high_quality_mapping",
                )
            )

        for lqm in low_quality_mappings:
            if lqm.quality_score <= 2:
                test_cases.append(
                    RefinementTestCase(
                        text=lqm.mapping.extracted_risk.supporting_quote,
                        is_true_positive=False,
                        source="low_quality_mapping",
                    )
                )

        return test_cases

    async def _embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.array([])

        prefixed = [f"{_TASK_INSTRUCTION}\n\n{t}" for t in texts]
        all_embeddings: list[list[float]] = []
        batch_size = 100

        for i in range(0, len(prefixed), batch_size):
            batch = prefixed[i : i + batch_size]
            response = await self._openai.embeddings.create(
                model=self._embedding_model,
                input=batch,
                dimensions=self._embedding_dimensions,
            )
            all_embeddings.extend([item.embedding for item in response.data])

        return np.array(all_embeddings)

    def compute_separation(
        self,
        description_embedding: np.ndarray,
        test_case_embeddings: np.ndarray,
        test_cases: list[RefinementTestCase],
    ) -> float:
        if len(test_cases) == 0 or description_embedding.size == 0:
            return 0.0

        desc_norm = description_embedding / (np.linalg.norm(description_embedding) + 1e-10)
        tc_norms = test_case_embeddings / (np.linalg.norm(test_case_embeddings, axis=1, keepdims=True) + 1e-10)

        similarities = tc_norms @ desc_norm

        tp_sims = [similarities[i] for i, tc in enumerate(test_cases) if tc.is_true_positive]
        fp_sims = [similarities[i] for i, tc in enumerate(test_cases) if not tc.is_true_positive]

        avg_tp = float(np.mean(tp_sims)) if tp_sims else 0.0
        avg_fp = float(np.mean(fp_sims)) if fp_sims else 0.0

        return avg_tp - avg_fp

    async def evaluate_candidate(
        self,
        candidate_description: str,
        test_cases: list[RefinementTestCase],
        test_case_embeddings: np.ndarray,
    ) -> float:
        desc_emb = await self._embed_texts([candidate_description])
        if desc_emb.size == 0:
            return 0.0
        return self.compute_separation(desc_emb[0], test_case_embeddings, test_cases)

    @observe(name="stage4-taxonomy-refinement")
    async def refine_category(
        self,
        category_key: str,
        all_judge_results: list[JudgeResult],
    ) -> RefinementResult | None:
        low_quality = self._collect_low_quality_mappings(all_judge_results, category_key)
        high_quality = self._collect_high_quality_mappings(all_judge_results, category_key)

        if not low_quality:
            logger.info("카테고리 %s: 저품질 매핑 없음, 건너뜀", category_key)
            return None

        category = low_quality[0].mapping.category
        original_description = category.description

        failure_patterns = await self.analyze_failure_patterns(original_description, low_quality)
        if not failure_patterns:
            logger.warning("카테고리 %s: 실패 패턴 분석 실패", category_key)
            return None

        candidates = await self.generate_candidate_descriptions(original_description, failure_patterns)
        if not candidates:
            logger.warning("카테고리 %s: 후보 description 생성 실패", category_key)
            return None

        test_cases = self._build_test_cases(high_quality, low_quality)
        if not test_cases:
            logger.warning("카테고리 %s: 테스트 케이스 없음", category_key)
            return None

        test_case_embeddings = await self._embed_texts([tc.text for tc in test_cases])

        original_separation = await self.evaluate_candidate(original_description, test_cases, test_case_embeddings)

        best_description = original_description
        best_separation = original_separation

        for candidate in candidates:
            sep = await self.evaluate_candidate(candidate, test_cases, test_case_embeddings)
            if sep > best_separation:
                best_separation = sep
                best_description = candidate

        improvement_pct = (
            ((best_separation - original_separation) / abs(original_separation) * 100)
            if original_separation != 0
            else 0.0
        )

        result = RefinementResult(
            category_key=category_key,
            original_description=original_description,
            refined_description=best_description,
            original_separation=original_separation,
            refined_separation=best_separation,
            improvement_pct=improvement_pct,
            num_low_quality_mappings=len(low_quality),
            failure_patterns=failure_patterns,
        )

        logger.info(
            "카테고리 %s 개선 완료: 분리도 %.4f → %.4f (%.1f%%)",
            category_key,
            original_separation,
            best_separation,
            improvement_pct,
        )
        return result
