from unittest.mock import AsyncMock, MagicMock

import pytest

from riskope.pipeline.extractor import RiskExtractor


def _make_gemini_response(json_text: str):
    resp = MagicMock()
    resp.text = json_text
    resp.usage_metadata = MagicMock()
    resp.usage_metadata.prompt_token_count = 10
    resp.usage_metadata.candidates_token_count = 5
    resp.usage_metadata.total_token_count = 15
    return resp


def test_max_retries_parameter_stored():
    client = MagicMock()
    extractor = RiskExtractor(gemini_client=client, model="gemini-2.5-flash", max_retries=5)
    assert extractor._max_retries == 5


def test_max_retries_default():
    client = MagicMock()
    extractor = RiskExtractor(gemini_client=client)
    assert extractor._max_retries == 3


@pytest.mark.asyncio
async def test_extract_retries_on_empty_response():
    response = _make_gemini_response('{"risks": []}')

    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)

    extractor = RiskExtractor(gemini_client=client, model="gemini-2.5-flash", max_retries=2)

    import asyncio

    original_sleep = asyncio.sleep
    asyncio.sleep = AsyncMock()
    try:
        result = await extractor.extract("test text")
    finally:
        asyncio.sleep = original_sleep

    assert result.risks == []
    assert client.aio.models.generate_content.call_count == 3


@pytest.mark.asyncio
async def test_extract_retries_on_api_error():
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(side_effect=Exception("API error"))

    extractor = RiskExtractor(gemini_client=client, model="gemini-2.5-flash", max_retries=1)

    import asyncio

    original_sleep = asyncio.sleep
    asyncio.sleep = AsyncMock()
    try:
        result = await extractor.extract("test text")
    finally:
        asyncio.sleep = original_sleep

    assert result.risks == []
    assert result.model == "gemini-2.5-flash"
    assert client.aio.models.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_extract_succeeds_without_retry():
    response = _make_gemini_response('{"risks": [{"tag": "테스트", "supporting_quote": "인용문"}]}')

    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)

    extractor = RiskExtractor(gemini_client=client, model="gemini-2.5-flash", max_retries=3)
    result = await extractor.extract("test text")

    assert len(result.risks) == 1
    assert result.risks[0].tag == "테스트"
    assert client.aio.models.generate_content.call_count == 1
