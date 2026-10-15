# Thinking Mode — DeepSeek API

Источник: https://api-docs.deepseek.com/guides/thinking_mode

## Что это

Модель **перед финальным ответом** выдаёт **chain-of-thought reasoning** (CoT).
Повышает **точность** ответа.

## Default

- **Thinking mode — включён по умолчанию** (default effort `high`).
- **Мы его НЕ отключаем** — значит, reasoning **работает** во всех вызовах.
- **Reasoning оплачивается** как **output-токены** (см. `docs/pricing.md`).

## Управление

### Toggle

- **OpenAI Format:** `extra_body={"thinking": {"type": "enabled/disabled"}}`.
- **Anthropic:** `{"reasoning": {"effort": "none/low/high/max"}}` (`none` — disable).

### Effort

- **OpenAI:** `reasoning_effort="low/high/max"`.
- **Mapping:** `minimal`/`low` -> `low`; `medium`/`high`/`xhigh` -> `high`;
  `max`/`ultra` -> `max`.

### Ограничения

- **`temperature`, `presence_penalty`, `frequency_penalty` — НЕ работают**
  в thinking mode. Установка — **без ошибки**, но **без эффекта**.
- **`top_p`** — только в thinking, диапазон **0.95-1.0** (ниже — clamp).

## Reasoning в ответе

- **`reasoning_content`** — отдельное поле, **на одном уровне** с `content`.
- **С `tools`:** `reasoning_content` **передавать обратно** в контекст
  (иначе **400 error**).
- **Без `tools`:** `reasoning_content` **игнорируется** (не конкатенируется).

## Наблюдение

- **`usage.completion_tokens_details.reasoning_tokens`** — сколько
  токенов ушло на reasoning.
- **`completion_tokens`** — **включает** reasoning + видимый ответ.

## Что взять в ai-coder

### 1. **Reasoning logging** — 💎

- **API отдаёт** `reasoning_content`.
- **Сейчас:** `LLMResponse.content` — только финальный ответ.
  Reasoning **теряется**.
- **Что:** добавить `LLMResponse.reasoning_content` + логировать в `step-N.md`.
- **Плюс:** отладка, оценка, эксперименты (сравнение промптов).

### 2. **`reasoning_tokens` — наблюдение** — 💎

- **API отдаёт** `usage.completion_tokens_details.reasoning_tokens`.
- **Что:** читать в `_build_response` + логировать в `usage.jsonl`.
- **Плюс:** **видеть**, сколько платим за reasoning.

### 3. **`reasoning_effort` — управление** — 💎

- **Что:** параметр в `chat` + config + CLI (`--reasoning-effort low|high|max`).
- **Плюс:** `low` для простых (`greet`, `inventory`) — быстрее, дешевле.

### 4. **`--no-thinking` — toggle** — 💎

- **Что:** флаг в CLI -> `extra_body={"thinking": {"type": "disabled"}}`.
- **Плюс:** для простых задач — **не тратить** output на reasoning.

## Ссылки

- https://api-docs.deepseek.com/guides/thinking_mode
- См. `docs/pricing.md` (стоимость).
