from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_coder.llm import LLMClient, LLMResponse

# ---------- вспомогательные объекты, имитирующие ChatCompletion ----------

@dataclass
class FakeMessage:
    content: str


@dataclass
class FakeChoice:
    message: FakeMessage
    finish_reason: str | None = "stop"


def _fake_response(
    content: str = "hello",
    finish_reason: str | None = "stop",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    total_tokens: int = 150,
    cache_hit: int | None = None,
    cache_miss: int | None = None,
) -> SimpleNamespace:
    """Собирает объект, похожий на ChatCompletion, с usage."""
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        model_extra={},
    )
    if cache_hit is not None:
        usage.model_extra["prompt_cache_hit_tokens"] = cache_hit
    if cache_miss is not None:
        usage.model_extra["prompt_cache_miss_tokens"] = cache_miss

    return SimpleNamespace(
        usage=usage,
        choices=[FakeChoice(message=FakeMessage(content=content), finish_reason=finish_reason)],
    )


# ---------- LLMClient с мок-клиентом ----------

@pytest.fixture
def llm_client(minimal_cfg, monkeypatch):
    """LLMClient с подменённым _client (не идёт в сеть и не требует реального ключа)."""
    monkeypatch.setenv(minimal_cfg.api.api_key_env, "sk-test-dummy")

    with patch("ai_coder.llm.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = MagicMock()
        client = LLMClient(minimal_cfg.api)
        yield client

# ---------- _build_response ----------

def test_build_response_with_cache_fields(llm_client):
    resp = _fake_response(
        content="answer",
        prompt_tokens=200,
        completion_tokens=60,
        total_tokens=260,
        cache_hit=150,
        cache_miss=50,
    )
    started = time.monotonic()
    llm = llm_client._build_response(resp, "test-model", started)

    assert llm.content == "answer"
    assert llm.prompt_tokens == 200
    assert llm.prompt_cache_hit_tokens == 150
    assert llm.prompt_cache_miss_tokens == 50
    assert llm.completion_tokens == 60
    assert llm.total_tokens == 260
    assert llm.finish_reason == "stop"
    assert llm.duration_ms >= 0


def test_build_response_without_cache_falls_back_to_miss(llm_client):
    """Если API не вернул cache-поля — весь prompt = miss."""
    resp = _fake_response(prompt_tokens=100)
    llm = llm_client._build_response(resp, "test-model", time.monotonic())

    assert llm.prompt_cache_hit_tokens == 0
    assert llm.prompt_cache_miss_tokens == 100


def test_build_response_empty_content(llm_client):
    resp = _fake_response(content="")
    llm = llm_client._build_response(resp, "test-model", time.monotonic())
    assert llm.content == ""


def test_build_response_none_content(llm_client):
    """Если content = None — превращается в пустую строку."""
    resp = _fake_response()
    resp.choices[0].message.content = None
    llm = llm_client._build_response(resp, "test-model", time.monotonic())
    assert llm.content == ""


def test_build_response_finish_reason_length(llm_client):
    resp = _fake_response(finish_reason="length")
    llm = llm_client._build_response(resp, "test-model", time.monotonic())
    assert llm.finish_reason == "length"


# ---------- chat ----------

def test_chat_success(llm_client):
    llm_client._client.chat.completions.create.return_value = _fake_response(content="ok")

    result = llm_client.chat(system="sys", user="usr", model="test-model")

    assert result.content == "ok"
    # проверяем, что create вызван с правильными аргументами
    call_kwargs = llm_client._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["messages"][0]["role"] == "system"
    assert call_kwargs["messages"][0]["content"] == "sys"
    assert call_kwargs["messages"][1]["role"] == "user"


def test_chat_json_mode_adds_response_format(llm_client):
    llm_client._client.chat.completions.create.return_value = _fake_response(content='{"a":1}')

    llm_client.chat(system="s", user="u", model="m", json_mode=True)

    call_kwargs = llm_client._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}


def test_chat_overrides_temperature_and_max_tokens(llm_client):
    llm_client._client.chat.completions.create.return_value = _fake_response()
    llm_client.chat(system="s", user="u", model="m", temperature=0.9, max_tokens=1234)

    call_kwargs = llm_client._client.chat.completions.create.call_args.kwargs
    assert call_kwargs["temperature"] == 0.9
    assert call_kwargs["max_tokens"] == 1234


def test_chat_retries_on_rate_limit(minimal_cfg, monkeypatch):
    """Первый вызов падает с RateLimitError, второй — успех."""
    from unittest.mock import MagicMock, patch

    from openai import RateLimitError

    from ai_coder.llm import LLMClient

    # нужен retries >= 2
    minimal_cfg.api.retries = 2
    monkeypatch.setenv(minimal_cfg.api.api_key_env, "sk-test-dummy")

    with patch("ai_coder.llm.OpenAI") as MockOpenAI:
        MockOpenAI.return_value = MagicMock()
        client = LLMClient(minimal_cfg.api)

    fake_err = RateLimitError("rate limited", response=MagicMock(), body=None)
    client._client.chat.completions.create.side_effect = [
        fake_err,
        _fake_response(content="ok after retry"),
    ]

    with patch("ai_coder.llm.time.sleep"):
        result = client.chat(system="s", user="u", model="m")

    assert result.content == "ok after retry"
    assert client._client.chat.completions.create.call_count == 2
