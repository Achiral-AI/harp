"""Thin async wrapper over the OpenAI SDK pointed at the local LiteLLM proxy."""

from __future__ import annotations

import logging
from typing import AsyncIterator

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from .settings import Settings

logger = logging.getLogger(__name__)


class LiteLLMClient:
    """Streams text deltas from a LiteLLM-fronted model group."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = AsyncOpenAI(
            base_url=settings.litellm_base_url,
            api_key=settings.litellm_master_key,
        )

    async def stream_chat(
        self,
        messages: list[ChatCompletionMessageParam],
        *,
        model: str | None = None,
        temperature: float = 0.4,
    ) -> AsyncIterator[str]:
        """Yield successive content deltas from a streaming chat completion."""

        target = model or self._settings.local_primary_model
        try:
            stream = await self._client.chat.completions.create(
                model=target,
                messages=messages,
                temperature=temperature,
                stream=True,
            )
        except Exception:
            logger.exception("LiteLLM chat completion failed for model=%s", target)
            raise

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    async def aclose(self) -> None:
        await self._client.close()
