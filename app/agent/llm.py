"""Thin LLM adapter: DeepSeek via Yandex AI Studio (OpenAI-compatible endpoint).

The provider is hidden behind three env variables (base URL, model, key);
agent logic (tools, history, validation) lives elsewhere. The API key is never logged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
_TIMEOUT_SEC = 30
# Thinking mode is off by default: faster, cheaper, and tool calls need no reasoning_content round-trip.
_DEFAULT_REASONING_EFFORT = "none"


@dataclass(frozen=True)
class LLMSettings:
    api_key: str = field(repr=False)
    folder_id: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> LLMSettings:
        """Read settings from the environment, loading `.env` (without overriding real env vars)."""
        load_dotenv(_ENV_PATH)
        return cls(
            api_key=os.environ.get("YANDEX_AI_STUDIO_API_KEY", "").strip(),
            folder_id=os.environ.get("YANDEX_FOLDER_ID", "").strip(),
            base_url=os.environ.get("LLM_BASE_URL", "").strip(),
            model=os.environ.get("LLM_MODEL", "").strip(),
        )

    @property
    def is_configured(self) -> bool:
        return all((self.api_key, self.folder_id, self.base_url, self.model))

    @property
    def model_uri(self) -> str:
        return build_model_uri(self.folder_id, self.model)


def build_model_uri(folder_id: str, model: str) -> str:
    return f"gpt://{folder_id}/{model}"


def get_client(settings: LLMSettings | None = None) -> OpenAI:
    settings = settings or LLMSettings.from_env()
    return OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        project=settings.folder_id,
        timeout=_TIMEOUT_SEC,
        max_retries=0,
    )


def chat(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    *,
    settings: LLMSettings | None = None,
    client: OpenAI | None = None,
    **kwargs: Any,
) -> Any:
    """One chat completion call; extra kwargs (temperature, reasoning_effort, extra_body, ...) pass through."""
    settings = settings or LLMSettings.from_env()
    client = client or get_client(settings)
    if tools:
        kwargs["tools"] = tools
    kwargs.setdefault("reasoning_effort", _DEFAULT_REASONING_EFFORT)
    return client.chat.completions.create(
        model=settings.model_uri,
        messages=messages,
        **kwargs,
    )
