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

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

from riskope.models import ExtractedRisk, ExtractionResult
from riskope.tracing import observe, traced_gemini_generate

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT_KR = """\
당신은 기업 리스크 분석 전문가입니다. 투자은행, 신용평가사, 컨설팅 펌에서 10년 이상 경력을 가진 시니어 애널리스트로서, 기업 공시 문서에서 투자 의사결정에 영향을 미치는 실질적 리스크 요인을 식별하는 것이 당신의 전문 분야입니다.

주어진 텍스트는 한국 기업의 사업보고서 중 위험 관련 섹션입니다.

## 분석 프로세스

텍스트를 읽을 때 다음 7개 영역을 체계적으로 점검하세요:
1. 전략 및 경쟁: 시장 경쟁, 신규 진입자, 기술 파괴, 제품 개발, M&A, 가격 압력
2. 운영 및 실행: 공급망, 인력, 품질, 설비, 프로젝트 실행, 사업 연속성
3. 재무 및 시장: 금리, 환율, 신용, 유동성, 자본구조, 투자 포트폴리오
4. 기술 및 정보: 사이버보안, 데이터 유출, 시스템 장애, AI/자동화, 디지털 전환
5. 규제 및 컴플라이언스: 법규 변경, 인허가, 소송, 개인정보보호, 세무
6. 외부 환경: 경기 침체, 지정학, 자연재해, 팬데믹, 기후변화
7. 거버넌스 및 이해관계자: 리더십, 평판, ESG, 주주 관계, 내부통제

## 출력 형식

각 리스크에 대해:
1. tag: 리스크의 핵심을 요약하는 자유형 태그 (한국어, 10단어 이내)
2. supporting_quote: 해당 리스크를 가장 잘 뒷받침하는 원문 인용문 (원문 그대로, 1~3문장)

## 세분화 기준

하나의 리스크 = 하나의 원인 → 하나의 영향 경로.
- "환율 변동과 금리 상승"이 함께 언급 → 원인이 다르므로 별도 추출
- "사이버 공격으로 인한 데이터 유출과 평판 훼손" → 하나의 원인(사이버 공격)에서 파생되므로 하나로 추출
- 한 문단에 3개 이상의 독립적 리스크가 열거되면 각각 별도로 추출

## 인용문 품질 기준

좋은 인용문:
- 해당 리스크의 구체적 영향이나 메커니즘을 설명하는 문장
- 수치, 금액, 비율 등 정량적 정보가 포함된 문장
- "~할 수 있으며, 이로 인해 ~에 부정적 영향을 미칠 수 있습니다" 형태

피해야 할 인용문:
- "당사는 다양한 리스크에 노출되어 있습니다" 같은 일반적 서문
- 다른 섹션이나 주석을 참조하는 문장만으로 구성된 것

## 추출하지 않을 것

- 면책 조항이나 법적 고지 (safe harbor 문구)
- "전망에 관한 주의사항" 등 일반적 미래전망 면책
- 이미 해결된 과거 사건의 단순 언급
- 다른 리스크와 사실상 동일한 내용의 반복 기술

## 규칙

- 가능한 한 많은 개별 리스크를 식별하되, 양보다 질을 우선하세요
- 인용문은 반드시 원문에서 그대로 가져와야 합니다 (수정·요약 금지)
- 태그는 한국어로 작성하세요
"""

_SYSTEM_PROMPT_EN = """\
You are a corporate risk analysis expert. As a senior analyst with 10+ years of experience across investment banking, credit rating agencies, and consulting firms, your specialty is identifying material risk factors from corporate filings that impact investment decision-making.

The given text is from the Risk Factors section of a 10-K annual report.

## Analysis Process

Systematically scan the text across these 7 risk domains:
1. Strategic & Competitive: market competition, new entrants, disruption, product development, M&A, pricing pressure
2. Operational & Execution: supply chain, workforce, quality, facilities, project execution, business continuity
3. Financial & Market: interest rates, currency, credit, liquidity, capital structure, investment portfolio
4. Technology & Information: cybersecurity, data breaches, system failures, AI/automation, digital transformation
5. Regulatory & Compliance: regulatory changes, licensing, litigation, data privacy, tax
6. External Environment: recession, geopolitics, natural disasters, pandemics, climate change
7. Governance & Stakeholders: leadership, reputation, ESG, shareholder relations, internal controls

## Output Format

For each risk:
1. tag: A concise free-form label capturing the essence of the risk (English, 10 words or fewer)
2. supporting_quote: A verbatim quote from the original text that best supports the risk (1-3 sentences)

## Granularity Rules

One risk = one root cause → one impact pathway.
- "foreign exchange fluctuations and rising interest rates" mentioned together → different causes, extract separately
- "cyber attacks leading to data breaches and reputational harm" → single cause (cyber attack) with cascading effects, extract as one
- When a paragraph enumerates 3+ independent risks, extract each separately

## Quote Quality Standards

Good quotes:
- Sentences explaining the specific mechanism or impact of the risk
- Sentences containing quantitative data (amounts, percentages, ratios)
- "...could adversely affect our revenue, operating results, and financial condition" with specific context

Avoid:
- Generic preambles like "We are subject to various risks and uncertainties"
- Sentences that merely cross-reference other sections or footnotes

## Do NOT Extract

- Safe harbor statements or legal disclaimers
- General cautionary language about forward-looking statements
- Mere mentions of resolved past events
- Restatements of the same risk already captured in different words

## Rules

- Identify as many individual risk factors as possible, but prioritize quality over quantity
- Quotes must be copied verbatim from the source text (no paraphrasing or summarizing)
- Tags must be in English
"""

_SYSTEM_PROMPTS = {"kr": _SYSTEM_PROMPT_KR, "en": _SYSTEM_PROMPT_EN}


class _RiskItem(BaseModel):
    tag: str = Field(description="리스크를 요약하는 자유형 태그")
    supporting_quote: str = Field(description="원문에서 가져온 근거 인용문")


class _RiskList(BaseModel):
    risks: list[_RiskItem] = Field(description="추출된 리스크 요인 목록")


class RiskExtractor:
    def __init__(
        self,
        gemini_client: genai.Client,
        model: str = "gemini-2.5-flash",
        max_retries: int = 3,
        locale: str = "kr",
    ) -> None:
        self._client = gemini_client
        self._model = model
        self._max_retries = max_retries
        self._system_prompt = _SYSTEM_PROMPTS.get(locale, _SYSTEM_PROMPT_KR)

    @observe(name="stage1-risk-extraction")
    async def extract(self, risk_text: str) -> ExtractionResult:
        for attempt in range(1 + self._max_retries):
            try:
                response = await traced_gemini_generate(
                    self._client,
                    model=self._model,
                    contents=[risk_text],
                    config=types.GenerateContentConfig(
                        system_instruction=self._system_prompt,
                        response_mime_type="application/json",
                        response_schema=_RiskList,
                        temperature=0.0,
                    ),
                    name="gemini-risk-extraction",
                )
            except Exception:
                logger.exception(
                    "LLM 추출 호출 실패 (attempt %d/%d)",
                    attempt + 1,
                    1 + self._max_retries,
                )
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    await asyncio.sleep(backoff)
                    continue
                return ExtractionResult(model=self._model)

            risks: list[ExtractedRisk] = []
            parse_failed = False

            try:
                parsed = json.loads(response.text)
                for r in parsed.get("risks", []):
                    risks.append(
                        ExtractedRisk(
                            tag=r["tag"],
                            supporting_quote=r["supporting_quote"],
                        )
                    )
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("응답 파싱 실패: %s", (response.text or "")[:200])
                parse_failed = True

            usage = {}
            if response.usage_metadata:
                usage = {
                    "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                    "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                    "total_tokens": response.usage_metadata.total_token_count or 0,
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
