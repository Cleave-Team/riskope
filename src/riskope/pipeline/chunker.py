"""텍스트 청킹 모듈 — 긴 DART 위험 섹션을 겹침 청크로 분할.

한국 DART 사업보고서의 '사업의 위험' 섹션은 30,000자 이상일 수 있으며,
LLM 추출 품질은 입력이 길어질수록 저하됩니다.
이 모듈은 텍스트를 겹침 청크로 분할하여 각 청크에서 독립적으로
리스크를 추출한 뒤 결과를 병합합니다.
"""

from __future__ import annotations

import logging
import re

from riskope.models import ExtractionResult

logger = logging.getLogger(__name__)


class TextChunker:
    """긴 텍스트를 겹침 청크로 분할하고 추출 결과를 병합."""

    def __init__(self, max_chars: int = 12000, overlap_chars: int = 500) -> None:
        self._max_chars = max_chars
        self._overlap_chars = overlap_chars

    def chunk(self, text: str) -> list[str]:
        """텍스트를 겹침 청크 목록으로 분할.

        Args:
            text: 분할할 원문 텍스트.

        Returns:
            청크 문자열 목록. 짧은 텍스트는 [text] 그대로 반환.
        """
        if len(text) <= self._max_chars:
            return [text]

        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = start + self._max_chars

            # 마지막 청크면 나머지 전부 포함
            if end >= len(text):
                chunks.append(text[start:])
                break

            # 1. 문단 경계(\n\n)에서 분할 시도
            split_pos = self._find_paragraph_break(text, start, end)

            # 2. 문장 경계 폴백
            if split_pos is None:
                split_pos = self._find_sentence_break(text, start, end)

            # 3. 경계 없으면 하드 분할
            if split_pos is None:
                split_pos = end

            chunks.append(text[start:split_pos])

            # 다음 청크는 overlap만큼 앞에서 시작
            start = split_pos - self._overlap_chars
            # overlap이 너무 커서 후진하지 않도록
            if start < (split_pos - self._overlap_chars):
                start = split_pos - self._overlap_chars
            # 최소한 1자는 전진해야 무한루프 방지
            if start <= (split_pos - self._max_chars):
                start = split_pos

        logger.info("텍스트 청킹: %d개 청크 (원문 %d자)", len(chunks), len(text))
        return chunks

    def _find_paragraph_break(self, text: str, start: int, end: int) -> int | None:
        """[start, end) 범위의 후반 50% 내에서 마지막 \\n\\n 위치를 찾음."""
        search_from = start + (end - start) // 2
        pos = text.rfind("\n\n", search_from, end)
        if pos == -1:
            return None
        # \n\n 다음부터 새 청크
        return pos + 2

    def _find_sentence_break(self, text: str, start: int, end: int) -> int | None:
        """[start, end) 범위의 후반 50% 내에서 마지막 문장 종결을 찾음."""
        search_from = start + (end - start) // 2
        region = text[search_from:end]

        # '. ', '。', '\n' 패턴 검색 (마지막 매치 사용)
        matches = list(re.finditer(r"\. |。|\n", region))
        if not matches:
            return None

        last = matches[-1]
        # 구분자 다음부터 새 청크
        return search_from + last.end()

    def merge_extraction_results(
        self, results: list[ExtractionResult]
    ) -> ExtractionResult:
        """여러 청크의 추출 결과를 하나로 병합.

        Args:
            results: 각 청크에서 추출된 ExtractionResult 목록.

        Returns:
            병합된 단일 ExtractionResult. tag 기준 중복 제거.
        """
        if not results:
            return ExtractionResult()

        seen_tags: set[str] = set()
        merged_risks = []

        for result in results:
            for risk in result.risks:
                if risk.tag not in seen_tags:
                    seen_tags.add(risk.tag)
                    merged_risks.append(risk)

        # 토큰 사용량 합산
        merged_usage: dict[str, int] = {}
        for result in results:
            for key, value in result.usage.items():
                if isinstance(value, (int, float)):
                    merged_usage[key] = merged_usage.get(key, 0) + int(value)

        return ExtractionResult(
            risks=merged_risks,
            model=results[0].model,
            usage=merged_usage,
        )
