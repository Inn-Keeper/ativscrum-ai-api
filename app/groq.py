import asyncio
import json
import random as random_module
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.errors import AppError


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class GroqResult(Generic[T]):
    value: T
    prompt_tokens: int | None
    completion_tokens: int | None
    retries: int


class GroqClient:
    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random: Callable[[], float] = random_module.random,
    ) -> None:
        self.settings = settings
        self.http_client = http_client
        self.sleep = sleep
        self.random = random

    async def generate(
        self,
        model: str,
        system_prompt: str,
        context: dict,
        output_type: type[T],
    ) -> GroqResult[T]:
        schema = output_type.model_json_schema()
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "PROJECT_DATA_START\n"
                        + json.dumps(context, separators=(",", ":"), ensure_ascii=False)
                        + "\nPROJECT_DATA_END"
                    ),
                },
            ],
            "max_completion_tokens": self.settings.ai_max_output_tokens,
            "tool_choice": "none",
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": output_type.__name__,
                    "strict": True,
                    "schema": schema,
                },
            },
        }

        retries = 0
        while True:
            try:
                response = await self._post(body)
            except httpx.TransportError as exc:
                if retries >= self.settings.ai_max_retries:
                    raise self._unavailable() from exc
                await self._retry_delay(retries)
                retries += 1
                continue

            if response.status_code == 429:
                raise AppError(429, "provider_limited", "The AI provider is rate limited.")
            if response.status_code >= 500:
                if retries >= self.settings.ai_max_retries:
                    raise self._unavailable()
                await self._retry_delay(retries)
                retries += 1
                continue
            if response.is_error:
                raise AppError(502, "provider_error", "The AI provider rejected the request.")

            try:
                payload = response.json()
                content = payload["choices"][0]["message"]["content"]
                value = output_type.model_validate_json(content)
                usage = payload.get("usage") or {}
                return GroqResult(
                    value=value,
                    prompt_tokens=self._token_count(usage.get("prompt_tokens")),
                    completion_tokens=self._token_count(usage.get("completion_tokens")),
                    retries=retries,
                )
            except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
                raise AppError(
                    502,
                    "invalid_model_response",
                    "The AI provider returned an invalid response.",
                ) from exc

    async def _post(self, body: dict) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self.settings.groq_api_key}"}
        url = "https://api.groq.com/openai/v1/chat/completions"
        if self.http_client is not None:
            return await self.http_client.post(
                url,
                headers=headers,
                json=body,
                timeout=self.settings.ai_timeout_seconds,
            )
        async with httpx.AsyncClient() as client:
            return await client.post(
                url,
                headers=headers,
                json=body,
                timeout=self.settings.ai_timeout_seconds,
            )

    async def _retry_delay(self, retries: int) -> None:
        delay = 0.1 * (2**retries) * (0.5 + self.random())
        await self.sleep(delay)

    @staticmethod
    def _token_count(value: object) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @staticmethod
    def _unavailable() -> AppError:
        return AppError(503, "provider_unavailable", "The AI provider is unavailable.")
