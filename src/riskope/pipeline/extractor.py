"""Stage 1: LLM 기반 리스크 추출.

논문 설계:
- LLM에게 택소노미를 제공하지 않음 (context bloat 방지)
- 자유형 태그 + 근거 인용문(supporting quote) 추출
- Structured Output(function calling)으로 안정적 파싱
"""

from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI

from riskope.models import ExtractedRisk, ExtractionResult

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_KR = """\
당신은 기업 공시 문서에서 리스크 요인을 식별하는 전문 분석가입니다.

주어진 텍스트는 한국 기업의 사업보고서 중 '사업의 위험' 섹션입니다.
텍스트에서 식별할 수 있는 모든 개별 리스크 요인을 추출하세요.

각 리스크에 대해:
1. tag: 리스크를 간결하게 요약하는 자유형 태그 (한국어, 10단어 이내)
2. supporting_quote: 해당 리스크를 뒷받침하는 원문 인용문 (원문 그대로, 1~3문장)

규칙:
- 가능한 한 많은 개별 리스크를 식별하세요
- 하나의 문단이 여러 리스크를 언급하면 각각 별도로 추출하세요
- 예: "금리 변동과 환율 리스크"가 함께 언급되면 금리와 환율을 별도 리스크로 추출
- 각 리스크는 구체적이고 구별 가능해야 합니다
- 인용문은 반드시 원문 텍스트에서 그대로 가져와야 합니다
- 태그는 한국어로 작성하세요
- 중복된 리스크를 추출하지 마세요
"""

_SYSTEM_PROMPT_EN = """\
You are an expert analyst identifying risk factors from corporate filings.

The given text is the Item 1A Risk Factors section from a 10-K annual report.
Extract every distinct risk factor you can identify from the text.

For each risk:
1. tag: A concise free-form label summarizing the risk (English, 10 words or fewer)
2. supporting_quote: A verbatim quote from the original text justifying the risk (1-3 sentences)

Rules:
- Identify as many individual risk factors as possible
- When a single paragraph mentions multiple distinct risks, extract each separately
- Example: "interest rate fluctuations and foreign exchange risks" should yield two separate risk factors
- Each risk must be specific and distinguishable
- Quotes must be copied verbatim from the source text
- Tags must be in English
- Do not extract duplicate risks
"""

_SYSTEM_PROMPTS = {"kr": _SYSTEM_PROMPT_KR, "en": _SYSTEM_PROMPT_EN}

_EXTRACTION_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "report_risk_factors",
            "description": "식별된 리스크 요인 목록을 보고합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "risks": {
                        "type": "array",
                        "description": "추출된 리스크 요인 목록",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tag": {
                                    "type": "string",
                                    "description": "리스크를 요약하는 자유형 태그 (한국어)",
                                },
                                "supporting_quote": {
                                    "type": "string",
                                    "description": "원문에서 가져온 근거 인용문",
                                },
                            },
                            "required": ["tag", "supporting_quote"],
                        },
                    },
                },
                "required": ["risks"],
            },
        },
    }
]


class RiskExtractor:
    """Stage 1: LLM을 사용하여 리스크 텍스트에서 구조화된 리스크 목록 추출."""

    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "gpt-4o",
        max_retries: int = 3,
        locale: str = "kr",
    ) -> None:
        self._client = client
        self._model = model
        self._max_retries = max_retries
        self._system_prompt = _SYSTEM_PROMPTS.get(locale, _SYSTEM_PROMPT_KR)

    async def extract(self, risk_text: str) -> ExtractionResult:
        """위험 섹션 텍스트에서 리스크 요인을 추출.

        Args:
            risk_text: '사업의 위험' 섹션 원문 텍스트.

        Returns:
            추출된 리스크 목록과 메타데이터.
        """
        for attempt in range(1 + self._max_retries):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": self._system_prompt},
                        {"role": "user", "content": risk_text},
                    ],
                    tools=_EXTRACTION_TOOLS,
                    tool_choice={
                        "type": "function",
                        "function": {"name": "report_risk_factors"},
                    },
                    temperature=0.0,
                )
            except Exception:
                logger.exception(
                    "LLM 추출 호출 실패 (attempt %d/%d)",
                    attempt + 1,
                    1 + self._max_retries,
                )
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    logger.info("재시도 대기 %ds...", backoff)
                    await asyncio.sleep(backoff)
                    continue
                return ExtractionResult(model=self._model)

            risks: list[ExtractedRisk] = []
            parse_failed = False
            message = response.choices[0].message

            if message.tool_calls:
                for tool_call in message.tool_calls:
                    try:
                        args = json.loads(tool_call.function.arguments)
                        for r in args.get("risks", []):
                            risks.append(
                                ExtractedRisk(
                                    tag=r["tag"],
                                    supporting_quote=r["supporting_quote"],
                                )
                            )
                    except (json.JSONDecodeError, KeyError):
                        logger.warning(
                            "tool call 파싱 실패: %s",
                            tool_call.function.arguments[:200],
                        )
                        parse_failed = True

            usage = {}
            if response.usage:
                usage = {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                }

            if risks:
                logger.info("Stage 1 완료: %d개 리스크 추출 (model=%s)", len(risks), self._model)
                return ExtractionResult(risks=risks, model=self._model, usage=usage)

            if attempt < self._max_retries:
                reason = "파싱 오류" if parse_failed else "빈 응답"
                backoff = 2**attempt
                logger.warning(
                    "Stage 1 %s — 재시도 %d/%d (대기 %ds)",
                    reason,
                    attempt + 1,
                    self._max_retries,
                    backoff,
                )
                await asyncio.sleep(backoff)
            else:
                logger.warning("Stage 1 재시도 소진 (%d회), 빈 결과 반환", 1 + self._max_retries)

        return ExtractionResult(model=self._model)
