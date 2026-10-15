# План улучшений на основе идей DeepSeek Harness

**Дата:** 2026-10-15
**Источник:** `deepseek-ai/deepseek-harness` (dsh), arxiv 2608.25512 (Cordis)
**Цель:** заимствовать 3 архитектурные идеи, не копируя `dsh` целиком.

**Основание:** анализ текущего состояния (460 тестов, 27 экспериментов,
монолит `agent.py` ~2900 строк, Python-only, coverage `gui/` omit).

---

## 0. Что уже есть (не трогать)

- **460 тестов**, CI зелёный (pytest ×3, ruff, mypy).
- **Учёт расходов:** `usage.jsonl`, курсы ЦБ, peak/off-peak.
- **Безопасность:** blacklist, mask_secrets, `shell=False`, whitelist.
- **Автономность:** decompose, replan, chain, split-goals, reverse-check.
- **GUI A.0–A.17:** FastAPI + Jinja2 + HTMX — **уже есть**, у `dsh` —
  из коробки, но у вас **богаче** (отчёты, статистика, справочник, chain).

**Вывод:** не переписывать. Заимствовать **3 идеи** — плагинность,
языко-нейтральность, реестр инструментов.

---

## 1. Плагинность (вместо монолита `agent.py`)

**Проблема:** `agent.py` ~2900 строк — всё в одном модуле
(ревью v4-pro п. 2.1, 2.3). Планировщик, tool loop, decompose,
autofix, reverse-check — в одном файле.

**Идея из `dsh`:** «всё есть плагин» — компоненты заменяемы без правки ядра.

**Что делать (минимально, без Cordis):**

1. **Разделить `agent.py` на модули:**
   - `agent/models.py` — dataclass'ы (`AgentStep`, `AgentPlan`,
     `ToolLoopResult`, `ReverseCheckResult`, `DecomposeResult`, ...).
   - `agent/planner.py` — `parse_agent_plan`, `run_planner`,
     `run_planner_phase1`, `run_planner_decompose`, `run_planner_replan`.
   - `agent/tool_loop.py` — `run_tool_loop`, `_save_tool_loop_history`,
     `_load_tool_loop_history`, `format_tool_history`.
   - `agent/decomposer.py` — `run_agent_decompose`, `parse_decompose_response`,
     `parse_split_goals_response`, `run_split_goals`.
   - `agent/autofix.py` — `run_auto_fix`, `_save_auto_fix_report`.
   - `agent/reverse.py` — `run_reverse_check`, `_collect_diff`.
   - `agent/__init__.py` — реэкспорт (обратная совместимость).

2. **Оценка:** ~1 день. **L**.
3. **Риск:** низкий — реэкспорт сохраняет `from ai_coder.agent import ...`.
4. **Связь:** ревью v4-pro п. 2.1, 2.3. TODO «agent.py — разделение монолита».

**Что это даёт:** тестируемость (можно мокать `tool_loop` без planner'а),
переиспользование (MCP-сервер, TUI), читаемость.

**Что НЕ делать:** Cordis. Это preview, сложно, не нужно для соло-проекта.

---

## 2. Языко-нейтральность (C/C++/JS через ctags)

**Проблема:** `ai-coder` заточен под Python. `read_symbol` — Python-only,
`run_shell` whitelist — без компиляторов, `check_python_files` — только `.py`.

**Идея из `dsh`:** harness не завязан на язык изначально.

**Что делать (уровень 1, ~4 ч):**

1. **`read_symbol` через `ctags`:**
   - Генерируем `tags` один раз (`ctags -R .`).
   - `read_symbol(name, path?, kind?)` — ищет в `tags`,
     читает тело из файла по `line_start`/`line_end`.
   - **C, C++, Python, JS, Go** — из коробки.
   - Fallback на regex, если `ctags` нет.
   - **Оценка:** ~2-4 ч.

2. **`run_shell` whitelist:** добавить `gcc`, `clang`, `make`, `cmake`,
   `ld`, `ar`, `nm`, `objdump`, `gdb`, `valgrind`. **~1 ч.**

3. **`verify_commands` автовыбор:** `Makefile` → `make`,
   `CMakeLists.txt` → `cmake --build`, `pyproject.toml` → `pytest`. **~2 ч.**

4. **`check_python_files` → `check_syntax_files`:**
   для `.c`/`.h` — `gcc -fsyntax-only`. **~2 ч.**

**Оценка:** ~1-2 дня (уровень 1).
**Связь:** roadmap направление 9, уровень 1A-1D.

---

## 3. Реестр инструментов (вместо статичного `TOOL_REGISTRY`)

**Проблема:** 6 инструментов жёстко в `tools.py` (`TOOL_REGISTRY`).
Добавить новый — правка кода.

**Идея из `dsh`:** инструменты — плагины, загружаются динамически.

**Что делать (минимально, ~4 ч):**

1. **Реестр через декоратор:**
   ```python
   @register_tool(spec=ToolSpec(name="my_tool", ...))
   def my_tool(args, project_root):
       ...
   ```
   - `TOOL_REGISTRY` наполняется при импорте.
   - `get_tool_specs()`, `execute_tool()` — без изменений API.

2. **Динамическая загрузка из `~/.ai-coder/plugins/`:**
   - `importlib.util.spec_from_file_location`.
   - Каждый плагин — `.py` с `@register_tool`.
   - Ошибки загрузки — warning, не падение.

3. **Оценка:** ~4 ч. **Связь:** TODO «Плагины действий — загрузка из
   `~/.ai-coder/actions/`».

**Что это даёт:** расширение без форка. `read_symbol` для C — плагин.
MCP-обёртка — плагин.

---

## 4. Coverage `gui/` (закрыть регрессии)

**Проблема:** `pyproject.toml` — `omit = ["ai_coder/gui/*"]`.
GUI тестируется вручную. A.12/A.14 откатывались.

**Идея из `dsh`:** Web UI — часть harness, тестируется.

**Что делать (~2-3 ч):**

1. **Smoke-тесты через FastAPI `TestClient`:**
   - `test_gui_smoke.py` — 10-15 тестов.
   - `GET /` → 200, содержит `id="build-form"`.
   - `GET /health` → `{"status":"ok"}`.
   - `POST /build` — 4 кейса (chain, tool-loop, run, пусто).
   - `GET /reports` → 200, таблица.
   - `GET /stats` → 200.
   - `GET /docs/cli` → 200, `/docs/cli/agent` → 200,
     `/docs/cli/nonexistent` → 404.
   - `POST /diff` — JSON `{diff, error}`.

2. **Убрать `omit gui/` из `pyproject.toml`.**
   Coverage упадёт с 73% — но GUI будет **реально** покрыт.

3. **Оценка:** ~2-3 ч. **Связь:** CHANGELOG 10.61 (omit gui/),
   TODO A.9/A.10.

---

## 5. Починить бюджет (E25/E26 показали баг)

**Проблема:** E25 (2.28 RUB при `--max-cost-rub 1`), E26 (0.47/0.85/0.68
при лимите 2.0 — не сработал). Фикс 10.54 закрыл precheck в tool loop,
но E26 показал, что лимит **не остановил**.

**Что делать (~2 ч):**

1. **Проверить `_estimate_next_cost_rub`** — грубая оценка по длине
   промпта. Возможно, **недооценивает** completion.
2. **Post-check оставить** (после `client.chat`).
3. **Проверить в `run_agent_decompose`** — `remaining` пересчитывается
   перед каждой подзадачей?
4. **E2E:** E26 повторить — 3 issue, `--max-cost-rub 2.0`.
   Ожидаем: стоп **до** 2.0 RUB, а не 2.01+.

5. **Оценка:** ~2 ч. **Приоритет:** 🔴 высокий (бюджет — критичен
   для автономности).

---

## Порядок (рекомендуемый)

| # | Направление | Оценка | Приоритет |
|---|---|---|---|
| 1 | Починить бюджет (E25/E26) | ~2 ч | 🔴 высокий |
| 2 | Smoke-тесты GUI + убрать omit | ~2-3 ч | 🔴 высокий |
| 3 | `read_symbol` через ctags | ~4 ч | 🟡 средний |
| 4 | Реестр инструментов + плагины | ~4 ч | 🟡 средний |
| 5 | Разделить `agent.py` | ~1 день | 🟡 средний |

**Итого:** ~2-3 дня — даст 80% выгоды `dsh` за 20% работы.

**Что НЕ делать:**
- Не мигрировать на `dsh` — preview, потеря контроля, потеря 460 тестов
  и 27 экспериментов.
- Не копировать Cordis — сложно, не нужно соло-проекту.
- Не переписывать GUI — он **богаче**, чем у `dsh` из коробки.

---

## Ссылки

- `docs/roadmap.md` — направление 9 (многоязычность).
- `docs/reviews/v4-pro-2026-10-09-full.md` — п. 2.1, 2.3 (монолит).
- `docs/experiments.md` → E25/E26 (баг бюджета).
- `docs/tools.md` — 6 инструментов (основа для реестра).
- CHANGELOG 10.61 — `omit gui/` (закрыть smoke-тестами).
- TODO.md — «Плагины действий», «agent.py — разделение монолита».
