"""Langfuse 기반 LLM 호출 추적 모듈.

환경변수 LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_BASE_URL이
설정되어 있으면 자동으로 활성화된다. 미설정 시 no-op.
"""

from __future__ import annotations

import logging

from google.genai import types as genai_types
from langfuse import get_client, observe  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


async def traced_gemini_generate(
    gemini_client,
    *,
    model: str,
    contents: list,
    config: genai_types.GenerateContentConfig,
    name: str = "gemini-generation",
):
    """Gemini generate_content 호출을 Langfuse Generation으로 기록."""
    langfuse = get_client()

    trace_input = [
        {
            "role": "system",
            "content": str(config.system_instruction) if config.system_instruction else "",
        },
        {
            "role": "user",
            "content": contents[0] if len(contents) == 1 else str(contents),
        },
    ]

    with langfuse.start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input=trace_input,
        model_parameters={
            "temperature": config.temperature,
            "response_mime_type": config.response_mime_type,
        },
    ) as gen:
        try:
            response = await gemini_client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as e:
            gen.update(level="ERROR", status_message=str(e))
            raise

        usage_details = {}
        if response.usage_metadata:
            usage_details = {
                "input": response.usage_metadata.prompt_token_count or 0,
                "output": response.usage_metadata.candidates_token_count or 0,
            }

        gen.update(
            output=response.text,
            usage_details=usage_details,
        )
        return response


def flush_traces() -> None:
    """버퍼된 Langfuse 이벤트를 서버로 전송."""
    try:
        get_client().flush()
    except Exception:
        logger.debug("Langfuse flush 실패 (미설정 상태일 수 있음)")
