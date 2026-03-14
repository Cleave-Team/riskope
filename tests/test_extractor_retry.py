from unittest.mock import AsyncMock, MagicMock

import pytest

from riskope.pipeline.extractor import RiskExtractor


def test_max_retries_parameter_stored():
    client = MagicMock()
    extractor = RiskExtractor(client=client, model="gpt-4o", max_retries=5)
    assert extractor._max_retries == 5


def test_max_retries_default():
    client = MagicMock()
    extractor = RiskExtractor(client=client)
    assert extractor._max_retries == 3


@pytest.mark.asyncio
async def test_extract_retries_on_empty_response():
    mock_tool_call = MagicMock()
    mock_tool_call.function.arguments = '{"risks": []}'

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_usage.total_tokens = 15

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=mock_response)

    extractor = RiskExtractor(client=client, model="gpt-4o", max_retries=2)

    import asyncio
    original_sleep = asyncio.sleep
    asyncio.sleep = AsyncMock()
    try:
        result = await extractor.extract("test text")
    finally:
        asyncio.sleep = original_sleep

    assert result.risks == []
    assert client.chat.completions.create.call_count == 3


@pytest.mark.asyncio
async def test_extract_retries_on_api_error():
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=Exception("API error"))

    extractor = RiskExtractor(client=client, model="gpt-4o", max_retries=1)

    import asyncio
    original_sleep = asyncio.sleep
    asyncio.sleep = AsyncMock()
    try:
        result = await extractor.extract("test text")
    finally:
        asyncio.sleep = original_sleep

    assert result.risks == []
    assert result.model == "gpt-4o"
    assert client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_extract_succeeds_without_retry():
    mock_tool_call = MagicMock()
    mock_tool_call.function.arguments = (
        '{"risks": [{"tag": "테스트", "supporting_quote": "인용문"}]}'
    )

    mock_message = MagicMock()
    mock_message.tool_calls = [mock_tool_call]

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 5
    mock_usage.total_tokens = 15

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage

    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=mock_response)

    extractor = RiskExtractor(client=client, model="gpt-4o", max_retries=3)
    result = await extractor.extract("test text")

    assert len(result.risks) == 1
    assert result.risks[0].tag == "테스트"
    assert client.chat.completions.create.call_count == 1
