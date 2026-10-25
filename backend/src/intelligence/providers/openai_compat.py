"""OpenAI-compatible implementations of the provider protocols (``/chat/completions``, ``/embeddings``).

One implementation serves OpenRouter, OpenAI and any server that speaks the same
API (vLLM, Ollama, LiteLLM, ...): only ``base_url``, the key and the model id differ.
Failures are translated into the provider-neutral errors of ``base``.  When a request
carries ``on_text`` the reply is streamed (server-sent events) and every text delta is
handed to the callback as it arrives.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from src.intelligence.models import Usage
from src.intelligence.providers.base import (
    EmbedTask,
    InvalidRequest,
    LLMRequest,
    LLMResponse,
    NotConfigured,
    ProviderUnavailable,
    RateLimited,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_EMBED_BATCH = 100
_TRANSIENT_STATUS = frozenset({500, 502, 503})
_RETRY_DELAYS_S = (0.6, 1.8)


def _translate_status(status: int) -> Exception:
    if status == 429:
        return RateLimited("the provider throttled the request")
    if status in (400, 404, 413, 422):
        return InvalidRequest(f"the provider rejected the request (HTTP {status})")
    if status in (401, 403):
        return NotConfigured(f"the provider refused the credentials (HTTP {status})")
    return ProviderUnavailable(f"the provider answered HTTP {status}")


def _translate(exc: BaseException) -> Exception:
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return ProviderUnavailable("the request timed out")
    if isinstance(exc, httpx.HTTPStatusError):
        return _translate_status(exc.response.status_code)
    return ProviderUnavailable(f"{type(exc).__name__} while calling the provider")


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _TRANSIENT_STATUS


def _decode_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class _Base:
    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        *,
        base_url: str,
        headers: Mapping[str, str] | None,
        retry_delays_s: Sequence[float],
        client: httpx.AsyncClient | None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._extra_headers = dict(headers or {})
        self._retry_delays_s = tuple(retry_delays_s)
        self._client = client

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    def _headers(self) -> dict[str, str]:
        key = self._api_key.get_secret_value()
        if not key:
            raise NotConfigured("the API key is not set")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json", **self._extra_headers}

    async def _retrying(self, call, what: str):
        for attempt, delay in enumerate((*self._retry_delays_s, None), start=1):
            try:
                return await call()
            except Exception as exc:
                if delay is None or not _is_transient(exc):
                    raise _translate(exc) from exc
                logger.info("%s attempt %d failed (%s); retrying", what, attempt, exc)
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class OpenAICompatLLM(_Base):
    name = "openai_compatible"

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        *,
        base_url: str = OPENROUTER_BASE_URL,
        default_timeout_s: float = 30.0,
        headers: Mapping[str, str] | None = None,
        reasoning_effort: str = "",
        retry_delays_s: Sequence[float] = _RETRY_DELAYS_S,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key, model, base_url=base_url, headers=headers, retry_delays_s=retry_delays_s, client=client
        )
        self._default_timeout_s = default_timeout_s
        self._reasoning_effort = reasoning_effort

    def _body(self, req: LLMRequest, *, stream: bool) -> dict[str, Any]:
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})
        body: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": req.temperature}
        if req.max_output_tokens:
            body["max_tokens"] = req.max_output_tokens
        if req.json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reply", "strict": False, "schema": req.json_schema},
            }
        if self._reasoning_effort:
            body["reasoning"] = {"effort": self._reasoning_effort}
        if stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        return body

    async def generate(self, req: LLMRequest) -> LLMResponse:
        timeout = req.timeout_s or self._default_timeout_s
        url = f"{self._base_url}/chat/completions"
        headers = self._headers()
        client = self._http()
        stream = req.on_text is not None

        async def once() -> LLMResponse:
            body = self._body(req, stream=stream)
            if stream:
                return await self._stream(client, url, headers, body, timeout, req)
            response = await client.post(url, headers=headers, json=body, timeout=timeout)
            response.raise_for_status()
            return self._parse(response.json(), req)

        return await self._retrying(once, "generation")

    def _parse(self, payload: dict[str, Any], req: LLMRequest) -> LLMResponse:
        if payload.get("error"):  # some gateways answer 200 with an error body
            raise ProviderUnavailable("the provider reported an error")
        choices = payload.get("choices") or []
        message = (choices[0].get("message") if choices else None) or {}
        text = (message.get("content") or "").strip()
        finish = (choices[0].get("finish_reason") if choices else None) or None
        return self._response(text, finish, payload.get("usage"), req)

    def _response(self, text: str, finish: str | None, usage_raw: Any, req: LLMRequest) -> LLMResponse:
        usage_raw = usage_raw or {}
        usage = Usage(
            input_tokens=int(usage_raw.get("prompt_tokens") or 0),
            output_tokens=int(usage_raw.get("completion_tokens") or 0),
            llm_calls=1,
        )
        details = usage_raw.get("completion_tokens_details") or {}
        logger.info(
            "generation finished: finish_reason=%s input_tokens=%d output_tokens=%d reasoning_tokens=%d reply_chars=%d",
            finish, usage.input_tokens, usage.output_tokens, int(details.get("reasoning_tokens") or 0), len(text),
        )
        parsed = _decode_json(text) if req.json_schema is not None else None
        return LLMResponse(text=text, parsed=parsed, usage=usage, finish_reason=finish)

    async def _stream(
        self, client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any],
        timeout: float, req: LLMRequest,
    ) -> LLMResponse:
        parts: list[str] = []
        finish: str | None = None
        usage_raw: Any = None
        async with client.stream("POST", url, headers=headers, json=body, timeout=timeout) as response:
            if response.status_code >= 400:
                await response.aread()
                response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue  # comments (": OPENROUTER PROCESSING") and blank lines
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = _decode_json(data)
                if chunk is None:
                    continue
                if chunk.get("error"):
                    raise ProviderUnavailable("the provider reported an error while streaming")
                usage_raw = chunk.get("usage") or usage_raw
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content") or ""
                    if delta:
                        parts.append(delta)
                        await req.on_text(delta)  # type: ignore[misc]
                    finish = choice.get("finish_reason") or finish
        return self._response("".join(parts).strip(), finish, usage_raw, req)


class OpenAICompatEmbedder(_Base):
    name = "openai_compatible"

    def __init__(
        self,
        api_key: SecretStr,
        model: str,
        *,
        base_url: str = OPENROUTER_BASE_URL,
        dims: int | None = None,
        headers: Mapping[str, str] | None = None,
        retry_delays_s: Sequence[float] = _RETRY_DELAYS_S,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key, model, base_url=base_url, headers=headers, retry_delays_s=retry_delays_s, client=client
        )
        self._dims = dims

    @property
    def dims(self) -> int | None:
        return self._dims

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> list[list[float]]:
        if not texts:
            return []
        headers = self._headers()
        client = self._http()
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = list(texts[start : start + _EMBED_BATCH])
            body: dict[str, Any] = {"model": self.model, "input": batch}
            if self._dims:
                body["dimensions"] = self._dims

            async def once(body=body) -> dict[str, Any]:
                response = await client.post(f"{self._base_url}/embeddings", headers=headers, json=body, timeout=60)
                response.raise_for_status()
                return response.json()

            payload = await self._retrying(once, "embedding")
            rows = sorted(payload.get("data") or [], key=lambda r: r.get("index", 0))
            if len(rows) != len(batch):
                raise ProviderUnavailable("the provider returned a different number of embeddings")
            vectors.extend([list(map(float, r["embedding"])) for r in rows])
        if vectors and self._dims is None:
            self._dims = len(vectors[0])
        return vectors
