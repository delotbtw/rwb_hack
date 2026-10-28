"""Smoke test of the LLM adapter (K0-T4, A-7). Live tests are skipped without a key."""

from __future__ import annotations

import json
import warnings

import pytest
from openai import APIStatusError

from app.agent.llm import LLMSettings, build_model_uri, chat

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_metric",
            "description": "Get a metric value grouped by a dimension.",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "description": "Metric code, e.g. revenue"},
                    "group_by": {"type": "string", "description": "Dimension code, e.g. customer_state"},
                },
                "required": ["metric"],
            },
        },
    }
]
MESSAGES = [
    {
        "role": "user",
        "content": "Show revenue by customer_state. You must call the query_metric tool.",
    }
]


@pytest.fixture(scope="module")
def settings() -> LLMSettings:
    cfg = LLMSettings.from_env()
    if not cfg.is_configured:
        pytest.skip("LLM is not configured: set YANDEX_AI_STUDIO_API_KEY, YANDEX_FOLDER_ID, LLM_BASE_URL, LLM_MODEL")
    return cfg


def test_build_model_uri_offline():
    assert build_model_uri("b1gabc", "deepseek-v4-flash") == "gpt://b1gabc/deepseek-v4-flash"


def test_settings_repr_hides_key():
    cfg = LLMSettings(api_key="secret-key", folder_id="f", base_url="u", model="m")
    assert "secret-key" not in repr(cfg)


def test_tool_call_returns_valid_json(settings):
    resp = chat(MESSAGES, TOOLS, settings=settings, temperature=0)
    message = resp.choices[0].message
    assert message.tool_calls, f"no tool_calls in response, model={resp.model}"
    call = message.tool_calls[0]
    assert call.function.name == "query_metric"
    args = json.loads(call.function.arguments)
    assert isinstance(args, dict) and "metric" in args


@pytest.mark.parametrize(
    "label, extra",
    [
        ("reasoning_effort", {"reasoning_effort": "low"}),
        ("thinking", {"extra_body": {"thinking": {"type": "disabled"}}}),
    ],
)
def test_thinking_parameters_probe(settings, label, extra):
    """The endpoint may reject thinking controls: a 400 is reported as a warning, not a failure."""
    try:
        resp = chat(MESSAGES, TOOLS, settings=settings, **extra)
    except APIStatusError as exc:
        if exc.status_code != 400:
            raise
        warnings.warn(f"{label} rejected by endpoint (HTTP 400): {exc.message}", stacklevel=1)
        pytest.skip(f"{label} not supported by endpoint (HTTP 400)")
    assert resp.choices
