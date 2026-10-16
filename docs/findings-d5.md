# findings: E2E verify-подзадача + 3 subagents (D5)

**Источник:** D5 (`docs/dsh.md`), прогоны в `.worktrees/verify`
(ветка `test-verify-spawn`), 2026-10-16.
**Данные:** E2E-1 — 11.1805 RUB, 3 роли вызваны, `completed`;
E2E-2 — 10.5242 RUB, 0 spawn, `max_iterations`.
Артефакты: `.ai-out/dsh-d5/` (патчи, журналы, логи).

Это **backlog для нас**, не issue для агента.

---

## 🔴 Critical

### [🔴] 1. Verify не ловит mypy

**Симптом:** в E2E-1 агент сделал `step_type = None` при выведенном
`str` — pytest ✅, ruff ✅, verify прошёл, а `mypy ai_coder` падает:
`decomposer.py:353: Incompatible types in assignment`.
`agent.verify_commands` содержит **только** `python -m pytest -q`.

**Файлы:** `config/config.yaml` (`agent.verify_commands`),
`ai_coder/apply.py` (`run_verify_commands`).
⚠️ **Нюанс:** verify выполняется в **проекте-цели**, поэтому
`python -m mypy ai_coder` нельзя хардкодить в `config.yaml` — в чужом
проекте это упадёт. Нужен `--verify-commands` для self-hosted прогонов
или отдельный self-check профиль.

**Оценка:** ~2 ч. `python -m ruff check ai_coder/` и
`python -m mypy ai_coder` из venv работают (проверено).

**Acceptance:** self-hosted прогоны проверяют pytest + ruff + mypy;
прогоны в чужих проектах **не** ломаются (проверка не хардкодится).

### [🔴] 2. Validator в tool loop: default + момент срабатывания

**Симптом:** зелёные проверки ≠ правильный фикс (E2E-2 прошёл
pytest+ruff+mypy с неработающим `step_type=st.type`).
**Уточнение к ТЗ:** `--reverse-check` **уже работает** в tool loop
(`cli.py:1332-1337`, передаётся на `cli.py:1816`, RC-блок —
`tool_loop.py:747/766`). Проблема не в отсутствии флага, а в том, что
он **выключен по умолчанию** и срабатывает **один раз в конце**
(diff↔goal), а не по итерациям.
⚠️ Даже включённый RC мог **не** поймать фикс E2E-2: goal был
сформулирован как «пробрасывай type» — `step_type=st.type` формально
ему соответствует. То есть нужен не только RC, но и точные goal.

**Файлы:** `ai_coder/cli.py` (default флага), `ai_coder/agent/tool_loop.py`
(RC в `_tool_loop_finalize`, после success).

**Оценка:** ~1 ч (включить по умолчанию для `--apply`) / ~4-6 ч
(RC per-iteration + «verified» отдельно от «success»).

**Acceptance:** решение зафиксировано: либо RC по умолчанию для
self-hosted/`--apply`, либо per-iteration; в отчёте видно
«success, но RC нашёл проблемы».

### [🔴] 3. Модель не делегирует без подсказки

**Симптом:** E2E-2 — **0** `spawn_subagent` из 20 шагов, хотя 3 роли
в конфиге и правило 19 в промпте. Модель сделала всё сама
(8×`run_shell`, 8×`read_file`, 3×`edit_file`, 1×`read_symbol`) и
упёрлась в `max_iterations` (10.5242 RUB).

**Файлы:** `config/prompts.yaml` (правило 19, `{{subagents_section}}`),
`ai_coder/agent/spawn.py` (`build_subagents_section`),
`ai_coder/agent/tool_loop.py` (порядок рекламы инструментов).
**Гипотезы:** правило 19 — в самом конце длинного промпта; задача
«в 1-2 файла» выглядит решаемой самому; нет триггера «сначала разведка».

**Оценка:** ~3-4 ч (2-3 прогона × ~10 RUB ≈ 20-30 RUB).

**Acceptance:** в ≥1 из 3 прогонов на задаче такого размера модель
вызывает `spawn_subagent` **без** упоминания ролей в goal —
**или** осознанное решение «не поощрять делегирование на малых
задачах» зафиксировано в docs.

---

## 🟡 Medium

### [🟡] 4. `iterations` ≠ число LLM-вызовов

**Симптом:** digest code-explorer — «3 итер», а в `usage.jsonl` **4**
записи (`:tool0..:tool3`). E2E-1 родитель: 15 шагов / 16 записей.
**Причина:** `iterations=len(ctx.history)` (`tool_loop.py:797`), а
`_handle_finish` (`tool_loop.py:299`) в `history` **не** пишет.

**Файлы:** `ai_coder/agent/tool_loop.py` (`_handle_finish`,
`_tool_loop_finalize`).

**Оценка:** ~1 ч.

**Acceptance:** `iterations` == число LLM-вызовов == строк в
`usage.jsonl` для этого loop; тест. Отчёты/дайджесты не сломаны.

### [🟡] 5. test-runner: пустой summary при `max_iterations`

**Симптом:** digest `[subagent test-runner] ❌ max_iterations, 3 итер,
0.1599 RUB` и **пустой** `summary:` — родитель не знает, что упало.

**Файлы:** `ai_coder/agent/tool_loop.py` (ветка `for/else` — ставит
`stopped_reason`, но не `summary`), `ai_coder/agent/spawn.py`
(`summarize_subagent_result` — подстраховаться при пустом summary).

**Оценка:** ~1 ч.

**Acceptance:** digest **всегда** непустой: `stopped_reason` +
последний инструмент и его статус + `verify_errors`, если есть.

### [🟡] 6. markdown-writer превысил cap (2.4496 > 2.0)

**Симптом:** +22% к `cap` (последняя итерация v4-pro — 1.6470 RUB).
**Проверено:** перерасход «≤ 1 итерации» **уже задокументирован** —
`CHANGELOG.md:64-66`. В `docs/tools.md` §6 и `docs/state.md` — **нет**.
По правилу «уже в docs → не отдельный issue»: **отдельного issue на
перерасход не нужно.**

**Файлы:** `docs/tools.md` (§6 — дописать про перерасход);
`ai_coder/agent/planner.py` (`_estimate_next_cost_rub`),
`ai_coder/agent/tool_loop.py` (precheck) — опционально.

**Оценка:** ~15 мин (доки) / ~2 ч (precheck по типу инструмента, E37).

**Acceptance:** в `docs/tools.md` §6 явно сказано про возможный
перерасход ≤ 1 итерации; (опционально) precheck учитывает тип
предыдущего инструмента.

---

## 🟢 Low

### [🟢] 7. `.venv/bin/ai-coder` из worktree не существует

**Симптом:** venv живёт в main, поэтому из `.worktrees/verify` путь
`.venv/bin/ai-coder` не резолвится. Плюс editable-установка указывает
на main: без `PYTHONPATH` console script исполняет код **main**, а
`run_shell`-субагенты не находят `python`/`pytest` без `PATH=.venv/bin`.
**Это не баг ai-coder** — особенность worktree + editable install.

**Файлы:** `docs/tools.md` (новый раздел «Self-hosted E2E в worktree»).

**Оценка:** ~30 мин.

**Acceptance:** в docs есть рецепт: абсолютный путь к venv,
`PATH=<main>/.venv/bin`, `PYTHONPATH=<worktree>`,
`set -a; . <main>/.env; set +a` — и **зачем** каждое нужно.

---

## Не issue (подтверждения D5)

- **Вложенные журналы** `tool-loop-<ts>/spawn-<name>/tool-loop-<ts>/` —
  работают.
- **Allowlist и depth=1** — соблюдены (никто не вызвал лишнего).
- **Атрибуция расходов точна:** сумма `agent:spawn:code-explorer:*` =
  0.2000 RUB == digest 0.1999 RUB (2.81 RUB из 11.18 — subagents).
