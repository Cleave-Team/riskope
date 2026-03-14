"""Stage 3: LLM-as-Judge 검증.

논문 설계:
- 별도 LLM 인스턴스로 매핑 품질 평가 (1-5점)
- 점수 + 1문장 reasoning
- 임계값(≥4) 이상만 최종 결과에 포함
- 저품질 매핑은 택소노미 개선 피드백으로 로깅
- 동시 평가 (asyncio + semaphore)
"""

from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI

from riskope.models import JudgeResult, QualityScore, TaxonomyMapping

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM_PROMPT_KR = """\
당신은 리스크 분류의 품질을 평가하는 전문 심사관입니다.

주어진 텍스트 인용문이 할당된 리스크 택소노미 카테고리에 얼마나 잘 매칭되는지 평가하세요.

평가 기준 (1-5):
5 = 완벽한 매칭: 텍스트와 카테고리가 정확히 일치
4 = 좋은 매칭: 사소한 차이만 있음
3 = 적절한 매칭: 합리적이지만 일부 격차 있음
2 = 부적절한 매칭: 상당한 불일치
1 = 매우 부적절: 명백히 잘못된 분류

중요: 인용문이 해당 카테고리의 리스크를 직접적으로 언급해야 합니다.
맥락상 추론만으로는 4점 이상을 줄 수 없습니다.

반드시 점수와 함께 한 문장으로 이유를 설명하세요.
"""

_JUDGE_SYSTEM_PROMPT_EN = """\
You are an expert evaluator assessing the quality of risk classification mappings.

Evaluate how well the given text quote matches the assigned risk taxonomy category.

Rating scale (1-5):
5 = Excellent fit: Perfect match between text and classification
4 = Good fit: Appropriate with only minor issues
3 = Adequate fit: Reasonable but some gaps
2 = Poor fit: Significant misalignment
1 = Very poor fit: Clearly wrong classification

Important: The quote must directly reference the risk described by the category.
Do not give 4 or above based on contextual inference alone.

You must provide both a numerical score and a concise one-sentence reasoning.
"""

_JUDGE_SYSTEM_PROMPTS = {"kr": _JUDGE_SYSTEM_PROMPT_KR, "en": _JUDGE_SYSTEM_PROMPT_EN}

_JUDGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_mapping",
            "description": "리스크-택소노미 매핑의 품질을 평가합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "quality_score": {
                        "type": "integer",
                        "description": "품질 점수 (1-5)",
                        "enum": [1, 2, 3, 4, 5],
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "점수 판단 근거 (한 문장)",
                    },
                },
                "required": ["quality_score", "reasoning"],
            },
        },
    }
]


class MappingJudge:
    """Stage 3: LLM-as-Judge로 매핑 품질 검증."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "gpt-4o-mini",
        threshold: int = 4,
        max_concurrent: int = 10,
        locale: str = "kr",
    ) -> None:
        self._client = client
        self._model = model
        self._threshold = threshold
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._locale = locale
        self._system_prompt = _JUDGE_SYSTEM_PROMPTS.get(locale, _JUDGE_SYSTEM_PROMPT_KR)
        self.total_usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def evaluate_all(self, mappings: list[TaxonomyMapping]) -> list[JudgeResult]:
        """모든 매핑을 동시 평가.

        Args:
            mappings: Stage 2에서 생성된 매핑 목록.

        Returns:
            모든 매핑에 대한 평가 결과 (필터링 전).
        """
        tasks = [self._evaluate_one(m) for m in mappings]
        results = await asyncio.gather(*tasks)
        valid_results = [r for r in results if r is not None]

        passed = sum(1 for r in valid_results if r.quality_score >= self._threshold)
        logger.info(
            "Stage 3 완료: %d/%d 통과 (threshold=%d)",
            passed,
            len(valid_results),
            self._threshold,
        )

        return valid_results

    def filter_passed(self, results: list[JudgeResult]) -> list[JudgeResult]:
        """임계값 이상 점수만 필터링."""
        return [r for r in results if r.quality_score >= self._threshold]

    async def _evaluate_one(self, mapping: TaxonomyMapping) -> JudgeResult | None:
        """단일 매핑 평가."""
        async with self._semaphore:
            user_message = self._build_user_message(mapping)

            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    tools=_JUDGE_TOOLS,
                    tool_choice={"type": "function", "function": {"name": "evaluate_mapping"}},
                    temperature=0.0,
                )
            except Exception:
                logger.exception("Judge 호출 실패")
                return None

            if response.usage:
                self.total_usage["prompt_tokens"] += response.usage.prompt_tokens
                self.total_usage["completion_tokens"] += response.usage.completion_tokens
                self.total_usage["total_tokens"] += response.usage.total_tokens

            message = response.choices[0].message
            if not message.tool_calls:
                return None

            try:
                args = json.loads(message.tool_calls[0].function.arguments)
                return JudgeResult(
                    mapping=mapping,
                    quality_score=QualityScore(args["quality_score"]),
                    reasoning=args["reasoning"],
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                logger.warning("Judge 응답 파싱 실패")
                return None

    def _build_user_message(self, mapping: TaxonomyMapping) -> str:
        cat = mapping.category
        risk = mapping.extracted_risk

        if self._locale == "en":
            return (
                f"## Supporting Quote\n{risk.supporting_quote}\n\n"
                f"## Original Risk Tag\n{risk.tag}\n\n"
                f"## Assigned Category\n"
                f"- Primary: {cat.primary}\n"
                f"- Secondary: {cat.secondary}\n"
                f"- Tertiary: {cat.tertiary}\n"
                f"- Description: {cat.description}\n"
            )

        desc_section = f"- 설명 (EN): {cat.description}"
        if cat.description_kr:
            desc_section += f"\n- 설명 (KR): {cat.description_kr}"

        return (
            f"## 인용문 (원문)\n{risk.supporting_quote}\n\n"
            f"## 원본 리스크 태그\n{risk.tag}\n\n"
            f"## 할당된 카테고리\n"
            f"- Primary: {cat.primary}\n"
            f"- Secondary: {cat.secondary}\n"
            f"- Tertiary: {cat.tertiary}\n"
            f"{desc_section}\n"
        )
