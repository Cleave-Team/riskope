from unittest.mock import AsyncMock

import numpy as np
import pytest

from riskope.models import ExtractedRisk, QualityScore, TaxonomyCategory, TaxonomyMapping
from riskope.pipeline.extractor import RiskExtractor, _SYSTEM_PROMPTS
from riskope.pipeline.judge import MappingJudge, _JUDGE_SYSTEM_PROMPTS
from riskope.pipeline.mapper import TaxonomyMapper, _TASK_INSTRUCTIONS


class TestExtractorLocale:
    def test_default_locale_is_kr(self):
        extractor = RiskExtractor(client=AsyncMock(), locale="kr")
        assert extractor._system_prompt == _SYSTEM_PROMPTS["kr"]

    def test_en_locale_uses_english_prompt(self):
        extractor = RiskExtractor(client=AsyncMock(), locale="en")
        assert extractor._system_prompt == _SYSTEM_PROMPTS["en"]
        assert "10-K annual report" in extractor._system_prompt

    def test_kr_prompt_contains_korean(self):
        assert "사업보고서" in _SYSTEM_PROMPTS["kr"]

    def test_en_prompt_contains_english(self):
        assert "risk analysis expert" in _SYSTEM_PROMPTS["en"]


class TestMapperLocale:
    def test_en_task_instruction_matches_paper(self):
        assert _TASK_INSTRUCTIONS["en"] == (
            "Classify risk factor text from an annual report into the most appropriate taxonomy category."
        )

    def test_kr_task_instruction_is_korean(self):
        assert "한국어" in _TASK_INSTRUCTIONS["kr"]

    @pytest.mark.asyncio()
    async def test_en_locale_embeds_description_only(self, tmp_path):
        mock_client = AsyncMock()

        mock_response = AsyncMock()
        mock_response.data = [
            type("Emb", (), {"embedding": [0.1] * 1536})(),
            type("Emb", (), {"embedding": [0.2] * 1536})(),
        ]
        mock_client.embeddings.create.return_value = mock_response

        mapper = TaxonomyMapper(client=mock_client, locale="en", data_dir=tmp_path)
        categories = [
            TaxonomyCategory(
                primary="P",
                secondary="S",
                tertiary="T1",
                description="EN description",
                description_kr="KR설명",
                key="P/S/T1",
            ),
            TaxonomyCategory(
                primary="P",
                secondary="S",
                tertiary="T2",
                description="EN desc 2",
                description_kr="KR설명2",
                key="P/S/T2",
            ),
        ]

        await mapper.precompute_taxonomy(categories)

        call_args = mock_client.embeddings.create.call_args
        texts = call_args.kwargs["input"]
        for text in texts:
            assert "KR설명" not in text
            assert "EN desc" in text or "EN description" in text

    @pytest.mark.asyncio()
    async def test_kr_locale_includes_kr_description(self, tmp_path):
        mock_client = AsyncMock()

        mock_response = AsyncMock()
        mock_response.data = [
            type("Emb", (), {"embedding": [0.1] * 1536})(),
        ]
        mock_client.embeddings.create.return_value = mock_response

        mapper = TaxonomyMapper(client=mock_client, locale="kr", data_dir=tmp_path)
        categories = [
            TaxonomyCategory(
                primary="P",
                secondary="S",
                tertiary="T1",
                description="EN description",
                description_kr="KR설명",
                key="P/S/T1",
            ),
        ]

        await mapper.precompute_taxonomy(categories)

        call_args = mock_client.embeddings.create.call_args
        texts = call_args.kwargs["input"]
        assert "KR설명" in texts[0]

    def test_en_locale_changes_table_name(self):
        mapper_en = TaxonomyMapper(client=AsyncMock(), locale="en")
        mapper_kr = TaxonomyMapper(client=AsyncMock(), locale="kr")

        cats = [
            TaxonomyCategory(
                primary="P",
                secondary="S",
                tertiary="T",
                description="desc",
                key="P/S/T",
            ),
        ]

        assert mapper_en._table_name(cats) != mapper_kr._table_name(cats)


class TestJudgeLocale:
    def test_default_locale_is_kr(self):
        judge = MappingJudge(client=AsyncMock(), locale="kr")
        assert judge._system_prompt == _JUDGE_SYSTEM_PROMPTS["kr"]

    def test_en_locale_uses_english_prompt(self):
        judge = MappingJudge(client=AsyncMock(), locale="en")
        assert judge._system_prompt == _JUDGE_SYSTEM_PROMPTS["en"]
        assert "Excellent fit" in judge._system_prompt

    def test_en_user_message_format(self):
        judge = MappingJudge(client=AsyncMock(), locale="en")
        mapping = TaxonomyMapping(
            extracted_risk=ExtractedRisk(tag="interest rate risk", supporting_quote="Rising rates..."),
            category=TaxonomyCategory(
                primary="Financial",
                secondary="Market",
                tertiary="Interest Rate",
                description="Risk from interest rates",
                key="F/M/IR",
            ),
            similarity_score=0.85,
        )
        msg = judge._build_user_message(mapping)
        assert "## Supporting Quote" in msg
        assert "## Assigned Category" in msg
        assert "임베딩 유사도" not in msg

    def test_kr_user_message_format(self):
        judge = MappingJudge(client=AsyncMock(), locale="kr")
        mapping = TaxonomyMapping(
            extracted_risk=ExtractedRisk(tag="금리 리스크", supporting_quote="금리가 상승하여..."),
            category=TaxonomyCategory(
                primary="재무",
                secondary="시장",
                tertiary="금리",
                description="Risk from rates",
                description_kr="금리 변동 리스크",
                key="F/M/IR",
            ),
            similarity_score=0.85,
        )
        msg = judge._build_user_message(mapping)
        assert "## 인용문 (원문)" in msg
        assert "설명 (KR)" in msg
