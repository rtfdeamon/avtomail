from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import logger


@dataclass(slots=True)
class LLMRequest:
    messages: Sequence[dict[str, str]]
    temperature: float = 0.2
    max_tokens: int | None = None


@dataclass(slots=True)
class LLMResponse:
    content: str
    requires_human: bool
    raw: dict[str, Any] | None = None


class LLMService:
    """Wrapper around the Ollama chat API with confidence signalling support."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.settings.ollama_base_url, timeout=90)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


    async def generate_reply(self, request: LLMRequest) -> LLMResponse:
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self.settings.ollama_model,
            "messages": list(request.messages),
            "options": {
                "temperature": request.temperature,
            },
        }
        if request.max_tokens is not None:
            payload["options"]["num_predict"] = request.max_tokens

        try:
            data = await self._chat_or_generate(client, payload, request)
        except httpx.HTTPError as exc:  # pragma: no cover - network error path
            logger.exception("LLM request failed: %s", exc)
            return LLMResponse(content="", requires_human=True, raw={"error": str(exc)})

        content = data.get("message", {}).get("content")
        if content is None:
            content = data.get("response", "")
        marker = self.settings.llm_confidence_marker
        requires_human = False
        if marker and content.upper().startswith(marker.upper()):
            requires_human = True
            content = content[len(marker) :].lstrip()

        return LLMResponse(content=content, requires_human=requires_human, raw=data)

    async def _chat_or_generate(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        request: LLMRequest,
    ) -> dict[str, Any]:
        response = await client.post("/api/chat", json=payload)
        if response.status_code == 404:
            logger.warning("/api/chat returned 404; falling back to /api/generate")
            response = await self._fallback_generate(client, payload, request)
            return response
        response.raise_for_status()
        return response.json()

    async def _fallback_generate(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        request: LLMRequest,
    ) -> dict[str, Any]:
        parts: list[str] = []
        for message in payload["messages"]:
            role = message.get("role", "user").capitalize()
            content = message.get("content", "")
            parts.append(f"{role}: {content}")
        prompt = "\n".join(parts) + "\nAssistant:"

        generate_payload: dict[str, Any] = {
            "model": payload["model"],
            "prompt": prompt,
            "stream": False,
            "options": payload.get("options", {}),
        }
        response = await client.post("/api/generate", json=generate_payload)
        response.raise_for_status()
        data = response.json()
        if "message" not in data:
            data["message"] = {"role": "assistant", "content": data.get("response", "")}
        return data
