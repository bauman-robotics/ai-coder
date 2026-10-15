# docs/dsh/ — сырые материалы dsh

Здесь — **сырые** материалы экспериментов с **DeepSeek Harness** (`dsh`):
trajectory, reasoning, answer. **Анализ** — в `docs/dsh.md`.

**Формат:** `docs/dsh/<DN>/` — одна папка на эксперимент.

**Что внутри:**

- `session.v4.jsonl` — сырой trajectory (event-sourced, append-only).
- `answer.md` — финальный ответ модели (то, что она показала).
- `reasoning-seqN.md` — внутренняя речь (thinking chunks) — то,
  что модель проговаривает перед ответом. Бесплатно, но ценно.

## D1 (2026-10-16) — dsh как архитектурный ревьюер

**Задача:** план Validator (адаптация `run_reverse_check` для
per-подзадача в `run_agent_decompose`).

**Метрики:**
- 15 шагов (steps), 24 tool calls, 1 turn.
- Reasoning: 6 из 15 шагов — с reasoning (2537-9821 chars).
- Cache read: 0 -> 48896 (эффективно).
- Total tokens: 55369.

**Файлы:**
- `D1/session.v4.jsonl` — сырой trajectory.
- `D1/answer.md` — финальный ответ (13813 chars).
- `D1/reasoning-seq109.md` — главный reasoning (9821 chars, план).
- `D1/reasoning-seq121.md` — финальный reasoning (2537 chars).

**Что нашёл dsh (см. `docs/dsh.md` -> D1):**
- diff-изоляция (baseline-снапшот),
- точка вставки после retry,
- политика `ok=False` (warn/fail/rollback),
- `verified` vs `success`,
- опасность rollback,
- стоимость RC (+v4-pro per подзадача).

**Стоимость:** ~1 RUB (Flash, off-peak).

## Как пополнять

В новой сессии с dsh:
1. Создать `docs/dsh/D<N>/`.
2. Скопировать `session.v4.jsonl` из `~/projects/tasks/<date>/`.
3. Извлечь `answer.md` (assistant/message с большим `text`).
4. Извлечь `reasoning-seqN.md` (reasoning chunks — топ по длине).
5. Обновить **анализ** в `docs/dsh.md` -> `D<N>`.
