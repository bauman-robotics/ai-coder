from __future__ import annotations

import time
from dataclasses import dataclass

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from .config import ApiConfig


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    completion_tokens: int
    total_tokens: int
    duration_ms: int
    finish_reason: str | None


class LLMClient:
    def __init__(self, cfg: ApiConfig):
        self.cfg = cfg
        self._client = OpenAI(
            api_key=cfg.api_key(),
            base_url=cfg.base_url,
            timeout=cfg.timeout_sec,
        )

    def chat(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        model = model or self.cfg.model
        started = time.monotonic()

        last_err: Exception | None = None
        for attempt in range(1, self.cfg.retries + 1):
            try:
                create_kwargs: dict = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature if temperature is not None else self.cfg.temperature,
                    "max_tokens": max_tokens
                    if max_tokens is not None
                    else self.cfg.max_output_tokens,
                }
                if json_mode:
                    create_kwargs["response_format"] = {"type": "json_object"}

                resp = self._client.chat.completions.create(**create_kwargs)  # type: ignore[call-overload]
                return self._build_response(resp, model, started)
            except (RateLimitError, APITimeoutError, APIError) as e:
                last_err = e
                if attempt < self.cfg.retries:
                    time.sleep(2 ** (attempt - 1))
                    continue
                raise

        raise RuntimeError(f"LLM error after retries: {last_err}")

    def _build_response(self, resp, model: str, started: float) -> LLMResponse:
        usage = resp.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or 0

        # DeepSeek возвращает эти поля; openai SDK пробрасывает их через model_extra
        extra = getattr(usage, "model_extra", None) or {}
        hit = int(extra.get("prompt_cache_hit_tokens", 0) or 0)
        miss = int(extra.get("prompt_cache_miss_tokens", 0) or 0)

        # фолбэк, если extra-полей нет: считаем весь промпт как miss
        if hit == 0 and miss == 0:
            miss = prompt_tokens

        content = resp.choices[0].message.content or ""
        finish = resp.choices[0].finish_reason

        return LLMResponse(
            content=content,
            model=model,
            prompt_tokens=prompt_tokens,
            prompt_cache_hit_tokens=hit,
            prompt_cache_miss_tokens=miss,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
            finish_reason=finish,
        )
