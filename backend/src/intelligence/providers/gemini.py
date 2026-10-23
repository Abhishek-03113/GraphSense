"""Google Gemini implementations of the provider protocols (``google-genai`` async client).

Failures are translated into the provider-neutral errors of ``base`` so the
pipeline never sees an SDK exception.  The API key is read from a ``SecretStr``
and is not kept anywhere except inside the SDK client.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

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

_EMBED_BATCH = 100
_TASK_TYPES = {"document": "RETRIEVAL_DOCUMENT", "query": "RETRIEVAL_QUERY"}


def _client(api_key: SecretStr):
    key = api_key.get_secret_value()
    if not key:
        raise NotConfigured("GEMINI_API_KEY is not set")
    from google import genai

    return genai.Client(api_key=key)


def _translate(exc: BaseException) -> Exception:
    """Map an SDK or transport failure to a provider error (the original stays as ``__cause__``)."""
    from google.genai import errors

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return ProviderUnavailable("the request timed out")
    if isinstance(exc, errors.APIError):
        code = getattr(exc, "code", None)
        if code == 429:
            return RateLimited("the provider throttled the request")
        if code in (400, 404, 413, 422):
            return InvalidRequest(f"the provider rejected the request (HTTP {code})")
        return ProviderUnavailable(f"the provider answered HTTP {code}")
    return ProviderUnavailable(f"{type(exc).__name__} while calling the provider")


def _decode_json(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


class GeminiLLM:
    name = "gemini"

    def __init__(self, api_key: SecretStr, model: str, *, default_timeout_s: float = 30.0) -> None:
        self.model = model
        self._api_key = api_key
        self._default_timeout_s = default_timeout_s
        self._client_instance = None

    def _get_client(self):
        if self._client_instance is None:
            self._client_instance = _client(self._api_key)
        return self._client_instance

    async def generate(self, req: LLMRequest) -> LLMResponse:
        from google.genai import types

        client = self._get_client()
        timeout = req.timeout_s or self._default_timeout_s
        config_args: dict[str, Any] = {
            "temperature": req.temperature,
            "http_options": types.HttpOptions(timeout=int(timeout * 1000)),
        }
        if req.system:
            config_args["system_instruction"] = req.system
        if req.max_output_tokens:
            config_args["max_output_tokens"] = req.max_output_tokens
        if req.json_schema is not None:
            config_args["response_mime_type"] = "application/json"
            config_args["response_json_schema"] = req.json_schema
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=self.model,
                    contents=req.prompt,
                    config=types.GenerateContentConfig(**config_args),
                ),
                timeout=timeout + 5,
            )
        except Exception as exc:
            raise _translate(exc) from exc

        try:
            text = (response.text or "").strip()
        except Exception:  # noqa: BLE001 - blocked or empty candidates
            text = ""
        usage_meta = getattr(response, "usage_metadata", None)
        usage = Usage(
            input_tokens=int(getattr(usage_meta, "prompt_token_count", 0) or 0),
            output_tokens=int(getattr(usage_meta, "candidates_token_count", 0) or 0),
            llm_calls=1,
        )
        finish = None
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            finish = str(getattr(candidates[0], "finish_reason", "") or "") or None
        parsed = _decode_json(text) if req.json_schema is not None else None
        return LLMResponse(text=text, parsed=parsed, usage=usage, finish_reason=finish)


class GeminiEmbedder:
    name = "gemini"

    def __init__(self, api_key: SecretStr, model: str, *, dims: int | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._dims = dims
        self._client_instance = None

    @property
    def dims(self) -> int | None:
        return self._dims

    def _get_client(self):
        if self._client_instance is None:
            self._client_instance = _client(self._api_key)
        return self._client_instance

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> list[list[float]]:
        from google.genai import types

        if not texts:
            return []
        client = self._get_client()
        config_args: dict[str, Any] = {"task_type": _TASK_TYPES[task]}
        if self._dims:
            config_args["output_dimensionality"] = self._dims
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _EMBED_BATCH):
            batch = list(texts[start : start + _EMBED_BATCH])
            try:
                response = await asyncio.wait_for(
                    client.aio.models.embed_content(
                        model=self.model,
                        contents=batch,
                        config=types.EmbedContentConfig(**config_args),
                    ),
                    timeout=60,
                )
            except Exception as exc:
                raise _translate(exc) from exc
            embeddings = getattr(response, "embeddings", None) or []
            if len(embeddings) != len(batch):
                raise ProviderUnavailable("the provider returned a different number of embeddings")
            vectors.extend([list(map(float, e.values)) for e in embeddings])
        if vectors and self._dims is None:
            self._dims = len(vectors[0])
        return vectors
