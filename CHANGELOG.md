# Changelog

Все значимые изменения проекта. Формат: `дата — итерация — краткое описание`.

---

































## [2026-10-09] iteration 10.14.14 — feat(tools): read_file с line_start/line_end

### Добавлено
- `tool_read_file`: параметры `line_start` / `line_end` (1-based,
  inclusive). Без параметров — как раньше (весь файл, обрезка 50K).
  С параметрами — только указанный диапазон строк, с заголовком
  `# path (lines X-Y of N)`. **Не обрезается** — работает для
  файлов любого размера.
- `ToolSpec read_file`: описаны новые args.
- `config/prompts.yaml`: правило 11 разделено на два сценария:
  - **A** (маленький файл, без `[обрезано]`) — как раньше:
    `read_file → edit_file → finish`;
  - **B** (большой файл, есть `[обрезано]`) — новый путь:
    `grep -n → read_file(line_start, line_end) → edit_file → finish`.
  - Явно разрешён `grep` для больших файлов (раньше правило
    запрещало grep после read_file — ловушка).

### Зачем
- Живой прогон агента на `agent.py` (2600 строк, ~90 KB) — **провал**:
  12 итераций, 0 правок (10.14.13). Причина — правило 11 не
  различало «весь файл в контексте» и «файл обрезан».
- Теперь: модель видит `[обрезано]` → идёт через grep + offset →
  правит точный участок. Правки в **любой** части файла
  (начало / середина / конец) становятся возможны.

### Тесты
- 6 новых тестов в `tests/test_tools.py`:
  `line_range`, `only_start`, `clamps_end`, `invalid_order`,
  `start_out_of_bounds`, `no_range_returns_full`.
- TODO п.18 (правило 11 — ловушка) — **закрыт**.

### Итого тестов
- 308 → 314 passed (+6).

---

## [2026-10-09] iteration 10.14.13 — fix(decompose): суммировать стоимость retry

### Исправлено
- `run_agent_decompose`: при retry через v4-pro стоимость первой
  (flash) попытки **терялась** — `subtask_results[-1]["cost_rub"]`
  перезаписывался стоимостью retry вместо суммирования.
- Фикс: `prev_cost = subtask_results[-1].get("cost_rub", 0.0)`;
  `"cost_rub": prev_cost + loop_result.total_cost_rub`.
- Найдено на живом прогоне `/tmp/agent-replan`:
  - flash-попытка подзадачи 1: **0.0608 RUB**;
  - retry v4-pro: **0.3796 RUB**;
  - в decompose-report было только 0.3796.
- Тест `test_run_agent_decompose_retry_cost_summation` — проверяет
  сумму 0.06 + 0.38 = 0.44.

### Побочный результат
- Живой прогон агента на правку `agent.py` (2600 строк) — **провал**:
  12 итераций, 0 правок. Причина — правило 11 не различает
  «весь файл в контексте» и «файл обрезан». Записано в TODO п.18.
- experiments.md: записи про провал на большом файле и про
  decompose-replan.

### Итого тестов
- 307 → 308 passed (+1).

---

## [2026-10-09] iteration 10.14.8 — test(llm): покрытие 100%

### Добавлено
- 3 теста в `tests/test_llm.py`:
  - `test_chat_raises_after_all_retries_exhausted` — все retry
    исчерпаны → наружу уходит оригинальное `RateLimitError`;
  - `test_chat_retries_on_timeout` — `APITimeoutError` тоже
    ловится и ретраится;
  - `test_chat_zero_retries_raises_runtime_error` — `retries=0`,
    цикл не выполняется → `RuntimeError("... after retries")`.
- Покрытие `ai_coder/llm.py` — **96% → 100%** (51/51 statements).

### Зачем
- `llm.py` — точка входа в API DeepSeek. Ошибка в разборе
  токенов/cache hit/miss → неверная стоимость; ошибка в retry →
  зависание или необработанное исключение.
- Непокрытыми оставались: `raise` после исчерпания retries;
  страховочный `RuntimeError` при `retries=0`;
  ветка `APITimeoutError`.

### Итого тестов
- 303 → 306 passed (+3).

---

## [2026-10-09] iteration 10.14.7 — test(decompose): replan покрыт unit-тестами

### Добавлено
- 3 теста `run_agent_decompose(replan=True)` в `tests/test_agent.py`:
  - `test_run_agent_decompose_replan_skip` — подзадача падает,
    replan=skip → цикл идёт дальше, `skipped_subtasks` заполнен;
  - `test_run_agent_decompose_replan_stop` — replan=stop →
    `parse_error` установлен, оркестратор останавливается;
  - `test_run_agent_decompose_replan_modify` — replan=modify →
    `subtasks` пересобирается, новая подзадача выполняется.
- Моки: `run_planner_decompose`, `run_tool_loop` (side_effect),
  `run_planner_replan`, `append_usage`.

### Зачем (проблема 15)
- Replan в оркестраторе `run_agent_decompose` **не был покрыт**
  тестами. Были только тесты на `run_planner_replan` (планировщик)
  и `parse_replan_response` (парсер).
- В E2E replan **не срабатывал** — правило 14 + `grep` при
  `'old' not found` предотвращали fail подзадачи.
- **Вывод:** replan не мёртвый код, а рабочий механизм.
  В E2E не срабатывал по объективным причинам.
  Оставляем в кодовой базе.

### Итого тестов
- 300 → 303 passed (+3).

---

## [2026-10-09] iteration 10.14.6 — fix(cache): хэш по отрендеренному промпту

### Исправлено (review 3.2)
- `actions.run_fix_action`: `cache_mod.compute_hash` получал
  синтетическую склейку `prompt_entry.system + "\nERRORS:\n" +
  errors + "\nPREV:\n" + previous_plan` и **сырой**
  `prompt_entry.user` (с плейсхолдерами `{{errors}}`, `{{files}}`,
  `{{tree}}`).
- Реальный промпт при этом рендерился через `render_prompt(...)`
  отдельно — хэш и промпт считались по разным формулам.
- **Фикс:** `compute_hash(prompt_system=system, prompt_user=user)` —
  по **уже отрендеренному** промпту. Хэш и запрос совпадают 1-в-1.

### Что это даёт
- Правка подстановок (`{{files}}`, `{{tree}}`, `{{depth_hint}}`) →
  инвалидация кэша (раньше — нет).
- Правка структуры шаблона вокруг `{{errors}}`/`{{previous_plan}}`
  → инвалидация (раньше — нет).
- Никаких «загадочных» cache hit'ов после правки промпта.

### Тесты
- `test_run_fix_action_prompt_change_invalidates_cache` — смена
  шаблона user → кэш промахивается, LLM зовётся снова.
- `test_run_fix_action_hash_uses_rendered_prompt` — регрессионный:
  в `compute_hash` уходит отрендеренный system/user **без**
  плейсхолдеров `{{...}}`.
- Всего: 298 → 300 passed (+2).

---

## [2026-10-09] iteration 10.14.5 — docs: сценарий fix

### Добавлено
- `docs/scenarios.md`: строка 11 в таблицу сценариев («Авто-починка»,
  `fix --max-attempts N`, 🟢, ~0.3–1.5 RUB).
- Раздел «11. Авто-починка ошибок» — что делает, команда, когда
  использовать, стоимость, флаги, итог, журнал, отличия
  от `agent --tool-loop`.

### Зачем
- Команда `fix` (10.14.1–10.14.4) не была отражена в обзоре
  сценариев. Таблица теперь полная: 11 сценариев от
  `run greet` до `fix`.

### Итого тестов
- 298 passed (без изменений — только доки).

---

## [2026-10-09] iteration 10.14.4 — fix: max_cost_rub в run_auto_fix

### Добавлено
- `run_auto_fix(max_cost_rub: float | None = None)` — бюджет всего
  цикла auto-fix.
- Проброс остатка бюджета в каждый `run_tool_loop`:
  `remaining_budget = max(0.0, max_cost_rub - result.total_cost_rub)`.
- После каждой попытки: если `total_cost_rub >= max_cost_rub` —
  `stopped_reason="max_cost"`, следующая попытка не запускается.
- CLI `fix`: флаг `--max-cost-rub N`, строка «Лимит: X RUB» в панели.
- Тест `test_run_auto_fix_max_cost`: дорогая попытка (5 RUB) при
  лимите 1 RUB → `stopped_reason="max_cost"`, `attempts=1`.

### Зачем
- `ai-coder fix` — цикл verify → fix → verify. Каждая попытка — это
  полный tool loop (деньги). Раньше лимита не было.
- Теперь: страховка от неожиданного счёта, как у `agent --tool-loop`.

### Итого тестов
- 297 → 298 passed (+1).

---

## [2026-10-09] iteration 10.14.1–10.14.3 — feat: auto-fix cycle

### Добавлено (10.14.1 — run_auto_fix)
- `AutoFixResult` — dataclass: `success`, `attempts`,
  `total_cost_rub/cny/usd`, `initial_errors`, `final_errors`,
  `journal_dir`, `stopped_reason`.
- `run_auto_fix` в `ai_coder/agent.py`: цикл
  `verify_commands → (fail) → run_tool_loop(goal='исправь ошибки: ...')
  → verify → ...` до `success` или `max_attempts`.
- `_save_auto_fix_report` — `report.md` с начальными и финальными
  ошибками, списком проверок, стоимостью.
- `stopped_reason`: `completed` | `max_attempts` | `loop_failed`
  | `no_verify_commands`.

### Добавлено (10.14.2 — CLI `fix`)
- Команда `ai-coder fix .` — цикл verify → fix → verify.
- Флаги: `--verify 'pytest -q;ruff check .'` (переопределяет
  `config.agent.verify_commands`), `--max-attempts N`,
  `--interactive`, `--journal/--no-journal`, `--model`, `--depth`,
  `--exclude`.
- Итог: `attempts`, `stopped_reason`, `total_cost_rub`,
  `final_errors`, путь к журналу.
- Валидация: `--interactive` требует TTY; если verify-команд нет —
  выход с ошибкой.

### Добавлено (10.14.3 — тесты)
- `test_run_auto_fix_no_errors` — verify сразу OK, 1 попытка.
- `test_run_auto_fix_loop_success` — ошибки → LLM fix → success.
- `test_run_auto_fix_max_attempts` — лимит, `stopped_reason=max_attempts`.
- 294 → **297 passed**.

### E2E
- `ai-coder fix . --verify "python -m pytest -q"`:
  цикл работает, отчёт `autofix-<ts>/report.md`,
  `attempt-N/tool-loop-<ts>/` — журналы попыток.

### Известное ограничение
- `run_auto_fix` **не прокидывает** `max_cost_rub` в `run_tool_loop` —
  бюджет попыток не ограничен (TODO 10.14.x).

### Итого тестов
- 294 → 297 passed (+3).

---

## [2026-10-09] iteration 10.13 — feat: verify_commands в tool loop

### Добавлено
- `ToolLoopResult.verify_errors: list[str]`.
- `run_tool_loop`: после `finish(success=true)` — автоматический
  запуск `cfg.agent.verify_commands` (pytest, ruff, mypy и т.п.).
- Если verify_errors — `success=False`,
  `stopped_reason="verify_failed"`.
- CLI: показать `verify_errors` в итоге tool loop.

### Зачем
- Раньше: агент говорил «готово» — но никто не проверял.
- Теперь: после каждой tool loop — автоматическая проверка.
- Ошибки сразу видны, а не через день.

### E2E
- Задача «2 поля в config.py + config.yaml»: 4 итерации,
  **0.19 RUB**, `✅ успех`.
- **`Проверка: python -m pytest -q`** → **`✅ Проверка пройдена`**.

### Как настроить
`config.yaml`:

    agent:
      verify_commands:
        - "python -m pytest -q"
      verify_timeout_sec: 60

Или через CLI:

    ai-coder agent "..." . --tool-loop --apply --verify-commands "pytest -q;ruff check ."

### Итого тестов
- 292 → 294 passed.

---

## [2026-10-09] iteration 10.11.6–10.12 — feat: replan + журнал decompose

### Документация `--decompose` (10.11.6)
- `docs/tools.md`: раздел «Декомпозиция задач».
- README: ссылка на раздел.

### Replan при fail v4-pro (10.11.8)
- `ReplanResult` — dataclass (action, explanation, new_subtasks,
  llm, cost, parse_error).
- `parse_replan_response` — устойчивый парсер (markdown, raw_decode,
  валидация action ∈ {skip, modify, stop}).
- `run_planner_replan` — планировщик: собирает контекст (goal,
  completed, failed, error, remaining), вызывает v4-pro.
- `--decompose-replan` (opt-in) — при fail подзадачи (после retry
  v4-pro) перепланировать: skip / modify / stop.
- `DecomposeResult.skipped_subtasks`.
- Цикл `for` → `while` (для `modify`).
- 3 теста `parse_replan_response` + 1 тест `run_planner_replan_skip`.
- `conftest.py`: `agent_plan_json`, `agent_decompose_json`,
  `agent_replan_json` в `prompts_cfg`.

### Журнал decompose + откат (10.12)
- `run_tool_loop(journal_subdir=None)` — журнал в указанную
  директорию.
- `run_agent_decompose` — создаёт `decompose-<ts>/`, передаёт
  `subtask-N/` в каждый `run_tool_loop`.
- `DecomposeResult`: `journal_dir`, `subtask_results`, `rolled_back`.
- `AgentConfig.decompose_rollback_on_fail: bool = False`.
- CLI: `--decompose-rollback-on-fail/--no-decompose-rollback-on-fail`.
- При fail (после retry + replan) — **откат всех успешных**
  подзадач (если флаг).
- `_save_decompose_report`: `report.md` с таблицей подзадач,
  статусами, стоимостью, ссылками на поджурналы.

### Структура журнала decompose

    .ai-out/<project>/decompose-<ts>/
    ├── report.md
    ├── subtask-1/
    │   └── tool-loop-<ts>/
    │       ├── history.json
    │       ├── report.md
    │       └── step-N.md
    └── subtask-2/
        └── tool-loop-<ts>/
            └── ...

### E2E
- 2 подзадачи (config.py + config.yaml): ✅ успех, 0.56 RUB.
- `decompose-<ts>/report.md` — таблица подзадач.
- `decompose-<ts>/subtask-N/tool-loop-<ts>/` — журналы подзадач.

### Итого тестов
- 288 → 292 (+4).

---

## [2026-10-09] iteration 10.11.7 — prompt + retry v4-pro

### Добавлено
- **Правило 14** в `agent_tool_json`: «если изменение уже есть —
  `finish(success=true, summary='уже сделано')`, без `edit_file`».
- Заодно: **`12. ПРИМЕРЫ` → `13. ПРИМЕРЫ`** (было два правила 12).

### Добавлено (retry)
- В `run_agent_decompose`: при fail подзадачи (flash) —
  **повтор через `cfg.agent.decompose_model`** (v4-pro).
- Не работает в `dry_run`.
- Retry только если `fallback_model != model`.
- Стоимость **суммируется** (обе попытки).

### E2E
- Задача «2 поля в config.py + config.yaml»: **1 подзадача**,
  2 `edit_file`, ✅ успех, **0.54 RUB**.

### Метрика
- Тестов: **288**.

### TODO
- Закрыт п.12 (подзадачи не знают про 'уже сделано').

---

## [2026-10-09] iteration 10.11.4 + 10.11.5 — тесты + retry

### Добавлено (10.11.4 — тесты)
- `test_parse_decompose_valid` — 2 подзадачи, поля goal/files.
- `test_parse_decompose_markdown_wrapper` — обёртка ```json.
- `test_parse_decompose_invalid_json` — parse_error.
- 283 → 286 passed.

### Исправлено (10.11.5 — проблема 11)
- **`parse_error` → retry (до 2 попыток)** в `run_tool_loop`.
- Раньше: `parse_error` → стоп. В decompose E2E подзадача 2
  упала, потому что flash вернула `{}` на 3-й итерации.
- Теперь: при `parse_error` — добавляем в `history` сообщение
  «верни СТРОГО JSON», `continue`. Счётчик `parse_retries` (max 2).
  После 2 retry — `stopped_reason="parse_error"`.
- `test_run_tool_loop_parse_error_retry` — retry → успех.
- `test_run_tool_loop_parse_error_exhausted` — 2 retry → стоп.
- 286 → 288 passed.

### Метрика
- Тестов: 283 → **288** (+5).
- Decompose E2E: подзадача 2 больше не падает на `parse_error`.

### TODO
- Закрыт п.11 (parse_error при {}).

---

## [2026-10-09] iteration 10.11.2 — feat: run_agent_decompose

### Добавлено
- `Subtask`, `DecomposeResult` — dataclass'ы в `agent.py`.
- `parse_decompose_response` — устойчивый парсер JSON.
- `run_planner_decompose` — планировщик-декомпозитор (LLM → подзадачи).
- `run_agent_decompose` — оркестратор: последовательно `run_tool_loop`
  для каждой подзадачи. Стоп при первом неуспехе.
- CLI-флаг `--decompose` (работает вместе с `--tool-loop`).
- `AgentConfig.decompose_model: str | None = None`.
- `config.yaml`: `decompose_model: "deepseek-v4-pro"`.
- Промпт `agent_decompose_json`.

### E2E (два прогона)
1. **2 файла** (`config.py` + `config.yaml`):
   - декомпозиция: **2 подзадачи** (по 1 файлу);
   - каждая — `run_tool_loop`, `edit_file`, ✅;
   - **✅ успех**, стоимость **0.64 RUB**.
2. **5 подзадач** (задача 10.8):
   - декомпозиция: **5 подзадач** (по 1 файлу);
   - подзадача 1 ✅ (поля уже есть);
   - подзадача 2 ❌ (`parse_error` — flash вернула `{}`);
   - **❌ неуспех**, стоимость **1.22 RUB**.

### Метрики
- Декомпозиция v4-pro — точная: 5 подзадач × 1 файл.
- Стоимость 2 файлов: **0.64 RUB** (в 8× дороже прямого tool loop).
- Стоимость 5 подзадач (неуспех): **1.22 RUB** (в 6× дешевле ❌ 7.74 RUB
  в 10.8 без decompose).

### Итого тестов
- 283 passed (без новых тестов для decompose — в 10.11.4).

---

## [2026-10-08] iteration 10.10 — feat: предупреждение про backticks

### Добавлено
- В `agent_cmd`: **предупреждение**, если в `goal` есть обратные
  кавычки (backticks).
- Подсказка «передать задачу через файл:
  `cat > /tmp/task.txt <<'TASK' ...`» — с примером.
- Проверка стоит **до** валидации `project_root` — срабатывает
  **при любом** пути.

### Зачем
- Bash выполняет содержимое backticks как **command substitution**.
  Модель получает **обрезанный** промпт.
- Пример (10.8): в промпте были backticks — `old` оказался без
  `transcript.jsonl` → модель искала несуществующую строку.

### Что это даёт
- Пользователь **видит проблему** сразу.
- Есть **готовая команда** — передать задачу через файл.

### Итого тестов
- 283 passed.

---

## [2026-10-08] iteration 10.8 — fix: format_tool_history для больших файлов

### Исправлено
- **`format_tool_history` обрезал `read_file` до 3000 символов.**
  Файл `docs/tools.md` (~8000 символов) не влезал → модель
  шла в `grep` → зацикливалась (14× `read_file` подряд).

### Добавлено
- `AgentConfig.tool_loop_history_max_chars = 10_000`
  (конфигурируемо) — лимит `read_file` в истории.
- `AgentConfig.tool_loop_history_other_max_chars = 500` — для
  остальных инструментов.
- `format_tool_history(read_file_max_chars=10_000, other_max_chars=500)`.
- `run_tool_loop` передаёт `cfg.agent.*`.
- При обрезке — пометка «Используй `run_shell grep` для точного поиска».
- `config.yaml`: те же поля в секции `agent:`.
- **Правило 12** в `agent_tool_json`:
  при `'old' not found` — использовать `grep`, не повторять `edit`.

### Тесты
- `test_format_tool_history_read_file_large_file`
- `test_format_tool_history_read_file_small_file`
- `test_format_tool_history_edit_file_uses_500`

### Метрика E2E
| | До 10.8 | После 10.8 |
|---|---:|---:|
| Итераций | 15 (max_iterations) | **1** |
| `read_file` | 14× (зацикливание) | **1×** |
| Результат | ❌ неуспех | **✅ успех** |
| Стоимость | 1.82 RUB | **0.10 RUB** |

**15× быстрее, 18× дешевле.**

### Итого тестов
- 283 passed (было 280, +3).

---


## [2026-10-08] iteration 10.5–B — docs, промпт, тесты

### Добавлено (10.5 — промпт + format_tool_history)
- `agent_tool_json`: примеры `edit_file` для YAML/Markdown/Python
  (уникальность `old`, контекст 2-3 строки).
- Пункт 11 «ЭФФЕКТИВНОСТЬ»: целевая последовательность
  `read → edit → finish` (3 итерации), не перечитывать.
- `format_tool_history`: `read_file` в истории — до **3000 символов**
  (было 200). Многострочный вывод (не схлопывается).
- **Метрика:** 5 → **2 итерации** на атомарную задачу,
  0.0709 → 0.0643 RUB.

### Добавлено (docs — `docs/tools.md`)
- **Агент создал `docs/tools.md`** через tool loop (`write_file`),
  за 1 запуск: ~280 строк — 5 инструментов, безопасность,
  CLI-флаги, журнал, примеры, troubleshooting.
- Python-скрипт докрутил 3 неточности (max-iterations, структура
  журнала, whitelist).
- README: ссылка на `docs/tools.md`.

### Добавлено (A — известные проблемы tool loop)
- `TODO.md`: раздел «Известные проблемы tool loop» — 10 проблем
  (backticks, dry-run, format_tool_history, 'old not found',
  flash-модель, 5+ файлов, промпт 55 строк, и т.п.).
- `state.md`: краткая сводка проблем.
- 2 проблемы закрыты в 10.8 (format_tool_history, 'old not found').

### Добавлено (B — «Как формулировать задачу агенту»)
- `docs/tools.md`: раздел «Как формулировать задачу агенту» —
  7 правил + чек-лист:
  - промпт < 15 строк;
  - без обратных кавычек в CLI (или через файл);
  - 1-2 файла на задачу;
  - `--dry-run` только для 1-2 итераций;
  - «найди + замени, если есть» — 1-2 итерации;
  - flash для простого, v4-pro для сложного;
  - 3+ точечных замен — Python/sed.
- README: ссылка на раздел.

### Метрика — динамика tool loop за сессию

| Задача | Итераций | Стоимость | Результат |
|---|---:|---:|---|
| До 10.5 | 5 | 0.0709 RUB | ✅ |
| После 10.5 | **2** | 0.0643 RUB | ✅ |
| 10.8 (провал) | 15 | 1.82 RUB | ❌ |
| **10.8 (fix)** | **1** | **0.10 RUB** | **✅** |

**15× быстрее, 18× дешевле** — за счёт `read_file` в истории
до 10000 символов.

### Итого тестов
- 280 → **283 passed** (+3).

---

## [2026-10-08] iteration 10.1–10.4 — feat: tool loop — автономность

### Добавлено (10.1 — автокоммит tool loop)
- `run_tool_loop(auto_commit=False)`: после `finish(success=true)`
  и `not dry_run` — `git add -A` + `git commit`.
- Сообщение: `ai-coder: <goal> (N ops, X.XX RUB)` — совместимо
  с `run_agent --commit`.
- `ToolLoopResult.commit_hash` — поле.
- CLI: `--commit` для tool loop (общий с `run_agent`).
- Показ коммита в итоге + подсказки `git show` / `git revert`.
- `git_repo` фикстура перенесена в `conftest.py`.
- 2 теста (успех, dry-run skip).

### Добавлено (10.2 — --resume)
- `_save_tool_loop_history`: `history.json` (машиночитаемый).
- `_load_tool_loop_history`: загрузка при resume.
- `run_tool_loop(resume_from=journal_dir)`: продолжает с N+1 итерации.
- `start_iteration`/`end_iteration` — корректный лимит.
- CLI: `--resume <journal-dir>`.
- `ToolResult.dry_run` — поле (для `history.json`).
- 3 теста: save history, resume, resume-no-history.

### Добавлено (10.4 — кэш phase1)
- `_phase1_cache_key`: SHA256(goal + tree + model), 32 hex.
- `_phase1_cache_dir` / `_from_cache` / `_save_cache`.
- `run_planner_phase1(use_cache=True, refresh=False)`:
  при cache hit LLM не вызывается (cost=0).
- `PlannerPhase1Result.llm: LLMResponse | None` (None при cache hit).
- `PlannerPhase1Result.from_cache: bool`.
- `conftest`: промпт `agent_plan_json_phase1` в `prompts_cfg`.
- 3 теста: cache_hit, cache_refresh, no_cache.

### Исправлено (10.5 — промпт + format_tool_history)
- `format_tool_history`: `read_file` → **3000 символов** (было 200).
  Модель видит содержимое файла в истории, не перечитывает
  и не использует `run_shell grep`.
- Остальные инструменты: 500 символов, многострочный вывод.
- `agent_tool_json`: примеры `edit_file` для YAML/Markdown/Python
  (уникальность `old`, контекст 2-3 строки).
- Пункт 11 «ЭФФЕКТИВНОСТЬ»: read → edit → finish (3 итерации),
  не перечитывать, не использовать grep для прочитанного.

### Метрика E2E (задача «поднять --cov-fail-under 40 → 70»)
- **10.5:** 5 итераций → **2 итерации** (`read_file` → `edit_file` → `finish`).
  Стоимость: 0.0709 → 0.0643 RUB.
- **10.4 (кэш phase1):**
  - запуск 1: `agent:plan1` 0.0345 RUB + `agent:plan` 0.0269 + `agent:step1` 0.0250.
  - запуск 2: **`agent:plan1` НЕТ** в `usage.jsonl` (cache hit),
    только `agent:plan` 0.0111 RUB.
  - **Экономия: ~0.06 RUB на повторной задаче.**
- **10.1 (автокоммит):** tool loop 4 итерации, 0.0483 RUB,
  коммит `35ea575` в `git log`.
- **10.2 (resume):** 2 итерации (0.0351) + resume 1 итерация (0.0090) = 0.0441 RUB.

### Что это даёт
- **Tool loop — production-ready:**
  - автокоммит в `git log` (история задач + стоимость);
  - `--resume` — не терять работу;
  - кэш phase1 — экономия на повторных;
  - 2 итерации на атомарную задачу (5 → 2);
  - безопасность: dry-run, interactive, бэкап, rollback.
- **Готовность к Уровню D:** автокоммит уже есть, ветки/PR — отложены.

### Итого тестов
- 280 passed (было 272, +8).

---

## [2026-10-08] iteration 9.1–9.4 — feat: tool loop (Уровень C)

### Добавлено (9.1 — tools)
- `ai_coder/tools.py`: `ToolSpec`, `ToolResult`, `ToolSecurityError`.
- Инструменты: `read_file`, `list_files`, `write_file`, `edit_file`.
- `_safe_path` — защита от выхода за `project_root` (абсолютные пути, `..`).
- `TOOL_REGISTRY`, `execute_tool`, `get_tool_specs`, `format_tools_for_prompt`.
- 25 тестов.

### Добавлено (9.2 — run_shell)
- `run_shell` с whitelist: `pytest`, `ruff`, `mypy`, `git status/diff/log`,
  `ls`, `cat`, `grep`, `find`, `head`, `tail`, `wc`,
  `python -m pytest|ruff|mypy`.
- Запрет shell-метасимволов (`;`, `&`, `|`, `<`, `>`, `$`, backticks, `$()`).
- Запрет опасных git-подкоманд: `push`, `reset`, `clean`, `rebase`,
  `merge`, `cherry-pick`, `revert`, `filter-branch`.
- Timeout (30 default, max 120), лимит вывода 10K символов.
- Лог команд в `.ai-out/commands.log`.
- 22 теста.

### Добавлено (9.3 — tool loop)
- `ToolAction`, `parse_tool_action` — устойчивый парсер ответа модели
  (markdown-обёртка, два JSON подряд через `json.JSONDecoder().raw_decode`,
  мусор после JSON).
- `format_tool_history` — рендер истории для промпта.
- `ToolLoopResult`, `run_tool_loop` — цикл `LLM → инструмент → результат → LLM`.
- CLI: `--tool-loop`, `--max-iterations`.
- Журнал: `.ai-out/<project>/tool-loop-<ts>/` (`step-N.md`, `report.md`).
- 6 тестов с мок LLM.

### Добавлено (9.4 — безопасность tool loop)
- `--dry-run` — dangerous-инструменты не выполняются, возвращают
  `(dry-run) EDITED/WROTE/RAN (simulated OK, ...)`.
- `--interactive` — панель + `y/n/a/s/d` перед каждым dangerous-инструментом.
- Бэкап перед первым изменением файла → совместим с `ai-coder rollback`
  (формат манифеста 1-в-1 как в `apply.py`).
- Показ бэкапа в итоге + подсказка `ai-coder rollback <backup-dir> .`.
- 3 теста backup, 4 теста interactive, 2 теста dry-run.

### Исправлено по ходу
- `parse_tool_action`: модель иногда возвращает два JSON подряд —
  теперь используется `json.JSONDecoder().raw_decode()`, берётся первый объект.
- `_save_tool_loop_step`: сохраняет `raw_json` при `parse_error` — видно
  в журнале, что вернула модель.
- `--dry-run` сообщение: раньше `would have called`, модель думала что
  не сработало и перечитывала файл (упиралась в `max_iterations`).
  Теперь `EDITED/WROTE/RAN (simulated OK)` — модель завершает.
- `agent_tool_json` промпт: пункт «после успешного edit — не перечитывать,
  сразу finish»; пункт «dry-run это УСПЕХ».
- `--interactive` разрешён с `--tool-loop` без `--apply` (tool loop
  применяет сам).

### Метрика E2E («поднять --cov-fail-under 40 → 70»)
- `--dry-run`: 2 итерации, **0.0386 RUB**, файл НЕ изменён.
- `--interactive`: 5 итераций, **0.0883 RUB**, файл изменён, бэкап создан.
- `rollback`: восстановил исходное значение (40).

### Что это даёт
- **Настоящая автономность:** модель сама вызывает инструменты до завершения.
- **Безопасность:** whitelist, dry-run, interactive, бэкап, лимиты.
- **Экономия:** tool loop + phase1 + only_paths — задача за <0.1 RUB.
- **Готовность к Уровню D:** автокоммит после успеха, ветки, PR.

### Итого тестов
- 272 passed.

---

## [2026-10-08] iteration 8.8 — feat(git): git-интеграция агента

### Добавлено
- `ai_coder/git.py` — враппер над git CLI (subprocess):
  `is_git_repo`, `status_porcelain`, `current_branch`, `commit`,
  `slugify`, `format_commit_message`.
- `GitConfig` — `enabled`, `require_clean`, `auto_commit`,
  `commit_template`.
- Секция `git:` в `config.yaml`.
- CLI-флаги для `agent`:
  - `--commit/--no-commit` (по умолчанию выкл);
  - `--require-clean/--no-require-clean` (по умолчанию вкл);
  - `--max-cost-rub N` — остановка при превышении бюджета.
- `run_agent(max_cost_rub=...)` — проверка бюджета в цикле шагов.
- Проверка чистоты дерева перед `--apply` (`git status --porcelain`).
- Автокоммит после успеха (`ai-coder: <goal> (N ops, X.XX RUB)`).
- 24 теста на временном git-репозитории.

### Как работает
- Перед `--apply` — проверка `git status --porcelain`.
  Грязно → предупреждение + вопрос.
- После успеха + `--commit` → `git add` + `git commit` в **текущую**
  ветку (обычно `main`).
- Ветки **не создаются** — одна `main`.
- Никаких `push`, `merge`, `branch -D`, `reset --hard`.

### Что это даёт
- История задач агента в `git log`.
- Стоимость каждой задачи в сообщении коммита.
- Откат через `git revert HEAD` — надёжнее `.ai-out/backup-*`.
- Фундамент для tool loop (Уровень C): агент будет сам коммитить.

### Итого тестов
- 186 passed.

---

## [2026-10-08] iteration 8.7 — feat(agent): phase1 — metadata-планировщик

### Добавлено
- `scan_project_metadata()` в `scanner.py` — обход без содержимого:
  только дерево + метаданные (`README`, `pyproject`, `requirements`).
- `render_metadata_block()` — рендер метаданных для phase1-промпта.
- `PlannerPhase1Result`, `_parse_phase1_response()`, `run_planner_phase1()`
  в `agent.py` — первый проход планировщика.
- `AgentConfig.phase1_enabled`, `phase1_max_output_tokens` (2000).
- `run_planner(only_paths=...)` — per-call override.
- `run_agent`: phase1 → phase2 → шаги.
- CLI-флаг `--no-phase1`.
- Промпт `agent_plan_json_phase1`.
- 8 тестов: 4 на `scan_project_metadata`, 4 на `_parse_phase1_response`.

### Как работает
- **Phase1** — планировщик видит только дерево + метаданные,
  возвращает `target_files`. Дёшево (~2K токенов).
- **Phase2** — планировщик видит только `target_files` из phase1.
- **Шаги** — как в 8.5/8.6 (шаг 1 сужен для одношагового плана).
- **Fallback:** phase1 упал или пуст → phase2 идёт с полным контекстом.

### Метрика (E2E: «поднять --cov-fail-under 40 → 70»)

| | 8.5 | 8.6 | 8.7 |
|---|---:|---:|---:|
| Планировщик | 0.5505 RUB | 0.5312 RUB | **0.0250 RUB** (в 21 раз) |
| Шаг 1 | 0.5358 RUB | 0.0249 RUB | 0.0257 RUB |
| **Всего** | **1.0863 RUB** | **0.5561 RUB** | **0.0507 RUB** |

**Экономия 8.7 vs 8.5 — 21x.**

### Итого тестов
- 162 passed.

---

## [2026-10-08] iteration 8.6 — feat(agent): сузить шаг 1 для одношаговых планов

### Добавлено
- `_select_step_only_paths(idx, is_single_step, auto_targets, auto_enabled)`
  в `agent.py` — выбор `only_paths` для шага.
- Логика:
  - **одношаговый план** — шаг 1 сужен до `target_files`;
  - **многошаговый план** — шаг 1 видит весь проект (может
    «доисследовать»), шаги 2+ сужены.
- 5 тестов на `_select_step_only_paths`.

### Метрика (E2E: «поднять --cov-fail-under 40 → 70»)

| | 8.5 | 8.6 |
|---|---:|---:|
| Планировщик | 0.5505 RUB | 0.5312 RUB |
| Шаг 1 — prompt | 41 209 | **1 482** (в 28 раз) |
| Шаг 1 — стоимость | 0.5358 RUB | **0.0249 RUB** (в 21 раз) |
| **Всего** | **1.0863 RUB** | **0.5561 RUB** |

Остаток — планировщик (0.53 RUB): он всё ещё видит весь проект.
Дальнейшее снижение — инкрементальный контекст (Уровень A+, TODO).

### Итого тестов
- 154 passed.

---

## [2026-10-08] iteration 8.5 — feat(agent): автовыбор only_paths из плана

### Добавлено
- `AgentConfig.auto_only_paths: bool = True` — авто-сужение контекста
  шагов 2+ до `target_files` из плана агента.
- CLI-флаг `--no-auto-only-paths` для `agent` — отключить авто-выбор.
- `_extract_target_files(plan)` в `agent.py` — уникальные пути
  из `step.target_files`, отсортированные, без дублей.
- Параметр `only_paths` в `scan_project()` — явный аргумент
  приоритетнее `cfg.scanning.only_paths`. Нужен агенту для
  per-step override; CLI-флаг `--only-path` работает как раньше.
- 5 тестов: 3 на `_extract_target_files`, 2 на
  `scan_project(only_paths=...)`.

### Как работает
- **Планировщик** видит весь проект.
- **Шаг 1** тоже видит весь проект — осознанно: он может
  «доисследовать», если планировщик не указал `target_files`.
- **Шаги 2+** видят только файлы из `target_files` плана.
- Если планировщик не указал `target_files` — предупреждение
  в консоли, шаги идут с полным контекстом.

### Замечено на E2E
- Задача «поднять `--cov-fail-under` 40 → 70» дала план **из 1 шага**.
  Фича включилась (`Авто-контекст: шаги 2+ увидят только 1 файл(ов)`),
  но применить сужение было не к чему.
- Одношаговый E2E: **1.086 RUB**, шаг 1 — 41K prompt-токенов.
- **Вывод:** эффект фичи виден на задачах из **2+ шагов**.

### TODO (8.6)
- Сужать контекст и для шага 1, если план одношаговый
  и `target_files` заполнены (~15 минут).

### Итого тестов
- 149 passed.

---

## [2026-10-08] iteration 8.4 — feat(scanner): --only-path

### Добавлено
- `ScanningConfig.only_paths` — сузить сканирование до файлов/директорий.
- CLI-флаг `--only-path` в `run` и `agent` (можно несколько раз).
- `_is_dir_relevant` / `_is_file_selected` в `scanner.py` —
  раздельные проверки для директорий и файлов (раньше одна
  `_matches_only_paths` ломала обход).
- `_normalize_only_paths` — нормализация `./`, `\`, хвостовых слэшей.
- 5 тестов в `test_scanner.py` на `only_paths`.

### Исправлено
- `--only-path ai_coder/cache.py` давал **0 файлов** вместо 1:
  `_matches_only_paths` блокировала родительские директории
  (`ai_coder/` отсеивалась, потому что не начинается с
  `ai_coder/cache.py`).
- Убран параметр `only_paths` из `scan_project` — один источник
  правды (`cfg.scanning.only_paths`).

### Метрики
- `--only-path ai_coder/cache.py`: ~2200 prompt-токенов
  вместо ~41054 (в 18 раз меньше).
- `--only-path ai_coder/`: 13 файлов, ~41K токенов.
- Тестов: 139 → 144.

### Итого тестов
- 144 passed.

---

## [2026-10-08] iteration 8.3 — баги self-hosted E2E

### Исправлено
- `agent._run_agent_step`: при невалидном плане `parse_error`
  и `problems` теперь попадают в `result.errors` — видно в консоли.
- `agent._run_agent_step`: `finish_reason == "length"` —
  явное сообщение в `errors` («Ответ модели обрезан...»).
- `AgentConfig.step_max_output_tokens` (8000) —
  конфигурируемо, передаётся в `client.chat`
  в `run_planner` и `_run_agent_step`.
- `config/config.yaml`: `agent.step_max_output_tokens: 8000`.

### Замечено (TODO)
- Модель слабо правит **YAML** (шаг 2 в self-hosted E2E не применился,
  хотя `old` уникален). Для YAML — править вручную или усилить
  промпт.
- Стоимость self-hosted E2E: 3.52 RUB за 2 шага.
- `flash` max output = 8192, `8000` — у потолка.

### Итого тестов
- 139 passed.

---

## [2026-10-08] iteration 8.2 — self-hosted E2E + cov-fail-under=70

### Изменено
- CI: `--cov-fail-under` с 40 на 70 (реальное покрытие 73%).
  **Правка сделана нашим агентом** через `--apply --interactive`.

### Замечено
- Self-hosted E2E: агент правит свой же `.github/workflows/test.yml`.
  Интерактив работает: diff показан, `y` применил, `completed`.
- **Стоимость на большом проекте:** 1.21 RUB за одну строку.
  Причина — контекст 43K токенов (весь проект).
  **Урок:** для маленьких задач на больших проектах нужен
  `--exclude` или селективный контекст (в TODO).

### Итого тестов
- 136 passed.

---

## [2026-10-08] iteration 8.1 — --interactive (Уровень B)

### Добавлено
- Флаг `--interactive` (`-i`) для команды `agent`.
- Перед применением **каждого шага** — панель с diff,
  список операций, explanation.
- Ответы:
  - `y` (yes) — применить шаг;
  - `n` (no) — отменить, прервать агента;
  - `a` (all) — применить все оставшиеся шаги без вопросов;
  - `s` (skip) — пропустить шаг, перейти к следующему;
  - `d` (diff) — показать diff ещё раз.
- Валидация: `--interactive` требует `--apply` и TTY.
- `accept_all_ref` — shared-флаг для «принять все».

### Проверено E2E
- Проект `/tmp/verify-test`: сброс `add` к багу,
  `agent --apply --interactive` -> план 1 шаг ->
  панель с diff -> ответ `y` -> применено -> `pytest` passed.
- Стоимость 0.066 RUB, 17.5 сек.

### Итого тестов
- 136 passed.

---

## [2026-10-07] iteration 8.0 — verify_commands (Уровень A)

### Добавлено
- `apply.run_verify_commands(commands, project_root, timeout_sec, max_output_chars)`
  — запуск shell-команд через subprocess, возвращает список ошибок.
- `AgentConfig.verify_timeout_sec` (60), `verify_max_output_chars` (10000).
- `agent._run_agent_step` — после `py_compile` запускает
  `cfg.agent.verify_commands`, вывод идёт в `verify_errors`.
- `cli.run` — verify_commands тоже запускаются (для `--apply`).
- CLI-флаги `--verify-commands "pytest -q;ruff check ."` для
  `agent` и `run`.
- Тесты: `test_run_verify_commands_*` (4), `test_agent_verify_commands_flag`.

### Проверено E2E
- Проект `/tmp/verify-test`: `add(a, b) -> a - b` (баг), тест падает.
- Агент: план 1 шаг -> `edit_file` -> `py_compile` passed ->
  `pytest -q` passed -> `completed`.
- Стоимость ~0.04-0.05 RUB, ~5-6 сек.
- Проверено и через config.yaml, и через CLI-флаг.

### Итого тестов
- 134 passed.

---

## [2026-10-07] iteration 7.8 — авто-исключение вёрстки

### Добавлено
- `ActionConfig.exclude_web_assets` (bool, по умолчанию false).
- Константа `WEB_ASSET_EXTENSIONS` в `config.py` —
  .html, .htm, .css, .scss, .less, .js, .jsx, .ts, .tsx, .mjs,
  .cjs, .vue, .svelte, .svg.
- `config.yaml`: `exclude_web_assets: true` для действий
  `greet`, `inventory`, `suggest_improvements`, `write_readme`.
- CLI-флаги `--exclude-web` / `--include-web` в `run` и `agent`:
  - `--exclude-web` — принудительно исключить вёрстку;
  - `--include-web` — принудительно включить (переопределить авто);
  - взаимоисключающие (одновременно нельзя).
- Логика `web_assets_override` в `run_action`, `run_agent`,
  `_run_agent_step`, `_run_dry`.

### Поведение
- **`greet`/`inventory`/`write_readme`** — вёрстка исключается
  автоматически.
- **`agent`** — вёрстка **включается** (по умолчанию);
  `--exclude-web` — исключает.
- **`refactor`** и другие действия — **без авто-исключения**.
- При малом бюджете (60K, 80K) эффект скрыт: вёрстка обрезается
  и так. При большом бюджете (200K) — видно: 65 -> 45 файлов,
  вёрстка 20 -> 0.

### Тесты
- 128 passed (+3 теста: --exclude-web, взаимоисключение,
  agent-exclude-web).

---

## [2026-10-07] iteration 7.7 — первый E2E-тест агента

### Проверено на `lichess_db_project`
- **Задача:** «убери неиспользуемые импорты `Optional` и `Union`
  из `config/config_loader.py`».
- **Планировщик:** 1 шаг — точный.
- **Применение:** 1 операция `edit_file`.
- **`py_compile`:** passed.
- **`ruff check --select F401`:** All checks passed.
- **Diff:** `-from typing import Dict, Any, Optional, Union`
  / `+from typing import Dict, Any`.
- **Бэкап:** создан с `manifest.json`.
- **Журнал:** `plan.json`, `step-1.md`, `report.md`.
- **Стоимость:** 0.54 ₽ (планировщик из кэша — 0.035 ₽).
- **Длительность:** 5.8 сек.
- **Откат:** проверен через `ai-coder rollback` — файл восстановлен.

### Что это доказывает
- Агент работает на **чужом** проекте.
- Декларативный пайплайн (план -> шаги -> apply) — надёжен.
- Бэкап + `py_compile` + откат — работают.
- Кэш даёт ощутимую экономию (0.035 vs 0.52).

### Добавлено
- `cli` флаг `--max-tokens` для `run` и `agent` —
  переопределение `max_total_tokens` из CLI.

---

## [2026-10-07] iteration 7.6 — scanner: приоритизация + пустые файлы

### Добавлено
- `scanner._file_weight(rel_path)` — вес файла для приоритизации.
  Точки входа (100), метаданные (90), код в пакетах (80),
  конфиги (70), `__init__.py` (40), скрипты (30), тесты (20),
  вёрстка (10).
- `scanner.scan_project` — двухфазный обход: `walk` собирает пути
  без чтения → сортировка `candidates` по весу → чтение
  в приоритетном порядке.
- Пропуск **пустых файлов** (`size == 0`) с причиной `empty`.
- Тест `test_scan_skips_empty_files`.

### Проверено на `lichess_db_project`
- **9 важных файлов** — в контексте: `README.md`, `Makefile`,
  `requirements.txt`, `run_web.py`, `wsgi.py`, `web_app/app.py`,
  `web_app/routes.py`, `services/lichess_client.py`,
  `services/pgn_parser.py`.
- **Обрезаны** — только скрипты (`scripts/*`) и вёрстка
  (`web_app/static/*`, `web_app/templates/*`).
- Раньше обрезались `README.md`, `web_app/app.py`, `services/*` —
  теперь попадают первыми.

### Итого тестов
- 123 passed.

---

## [2026-10-07] iteration 7.5 — первый реальный проект

### Проверено
- `greet` на чужом проекте `lichess_db_project` (74 файла, ~100K токенов).
- **Защита секретов работает:** `config/secrets*.yaml`, `.env` отсеяны.
  `pathspec` матчит `config/*secret*.yaml` на `secrets (Copy).yaml`,
  `config/secrets.yaml.example` отсеян через `*secret*`.
- **Кэш отчётов:** повторный запуск — 0 RUB, мгновенно.
- **Кэш инвалидация:** изменение файла → miss, DeepSeek-кэш даёт
  частичную экономию (0.55 RUB vs 0.75 RUB).
- **`--dry-run`** на большом проекте: точная оценка.

### Замечено
- **Обрезка контекста:** обрезаны `services/`, `web_app/`, `README.md`
  (лимит 60K токенов `flash`). Модель **честно отметила** их отсутствие,
  не выдумывала.
- Стоимость `greet` на среднем проекте: **~0.75 RUB**.
- Реальная стоимость **ниже** оценки `--dry-run` на **~20%**
  (оценка `len//3` завышает; DeepSeek-токенизатор эффективнее для кода).

### Записано в TODO
- Сканер: пустые файлы, приоритизация обхода, `--include`.

---

## [2026-10-07] iteration 7.4 — chore: pre-commit

### Добавлено
- `.pre-commit-config.yaml`:
  - `ruff --fix`
  - `ruff-format`
  - `trailing-whitespace`
  - `end-of-file-fixer`
  - `check-yaml`
  - `check-added-large-files`
- `pre-commit>=3.7` в `requirements-dev.txt`.
- `check.sh` — локальный скрипт (ruff + mypy + pytest).

### Изменено
- `ruff.toml` — убран `RUF059` (несовместим с ruff 0.6.x).
- Автоформат ruff-format (22 файла).
- Автофиксы trailing-whitespace и end-of-file-fixer.

### Заметка
- mypy **не в pre-commit** (медленный, и конфликтует с pass_filenames).
  Mypy работает в CI.

---

## [2026-10-07] iteration 7.3 — покрытие тестами (73%)

### Добавлено
- `tests/test_output.py` — 17 тестов, `output.py` 0% -> 87%.
- `tests/test_llm.py` — 9 тестов, `llm.py` 39% -> 96%.
- `tests/test_actions.py` — ~10 тестов, `actions.py` 0% -> 81%.
- `tests/test_cli.py` — 13 тестов, базовые команды CLI.
- `tests/test_cli_run.py` — 7 тестов, команда `run` с моками.
- `tests/test_cli_agent.py` — 4 теста, команда `agent` с моками.
- Новые фикстуры в `tests/conftest.py` (`fake_llm_response`, `fake_scan_result`, `fake_action_result`).

### Изменено
- `pyproject.toml` — секции `[tool.coverage.run]` и `[tool.coverage.report]`.
- `requirements-dev.txt` — добавлен `pytest-cov>=5`.
- `.github/workflows/test.yml` — `--cov=ai_coder --cov-fail-under=40` на Python 3.12.
- `.gitignore` — добавлен `.coverage`, `coverage.xml`, `htmlcov/`.

### Метрики
- Тестов: 56 -> 119.
- Общее покрытие: 40% -> 73%.
- `output.py`: 0% -> 87%.
- `llm.py`: 39% -> 96%.
- `actions.py`: 0% -> 81%.
- `cli.py`: 0% -> 75%.

---

## [2026-10-07] iteration 7.2 — feat(scanner): content-фильтр секретов

### Добавлено
- **review 1.4:** content-проверка файлов на типичные секреты.
  Файлы с найденными ключами не попадают в контекст (skipped
  с причиной `secret_content: <название>`).
- Паттерны (узкие, минимум ложных срабатываний):
  - `sk-...` — OpenAI/DeepSeek API key;
  - `AKIA...` — AWS access key;
  - `ghp_...` / `github_pat_...` — GitHub tokens;
  - `xox[baprs]-...` — Slack tokens;
  - `-----BEGIN ... PRIVATE KEY-----` — PEM-ключи;
  - `AIza...` — Google API key.

### Исправлено
- Восстановлена проверка `max_file_size_kb`: файлы больше лимита снова
  попадают в `skipped` с причиной `too_large` (регрессия была занесена
  при рефакторинге `walk`).

### Тесты
- 60 passed (+4 новых: content secret, PEM, короткий токен, too_large).

---

## [2026-10-07] iteration 7.1 — feat(agent): skipped в preview

### Добавлено
- В `_run_agent_step` при `apply=False` (preview): если план шага пуст
  (`operations: []`) — помечаем `skipped=True` с причиной
  «план не содержит операций».
- В CLI шага агента отображается как `пропущено`, а не
  «только предложение».

### Замечание
- Сложно протестировать E2E: нужна модель, которая создаст шаг,
  но не найдёт, что в нём править. Логика покрыта существующими
  тестами; полный E2E — в будущем.

### Тесты
- 56 passed.

---

## [2026-10-07] iteration 7.0 — fix(usage): конфиг + O(N^2)

### Исправлено
- **review 1.3:** `usage.append_usage` использовал хардкод путей
  (`output_root / "usage.jsonl"`) вместо `usage_cfg.jsonl` из конфига.
  Теперь путь берётся из конфига, относительно `project_root`.
- **review 1.3:** `_rebuild_summary` вызывался на каждый `append_usage`
  и читал весь JSONL — O(N^2) по I/O. Сводка теперь строится командой
  `usage` на лету из JSONL. Функция `_rebuild_summary` удалена
  (мёртвый код).

### Эффект
- 200 записей подряд: было 0.281 сек, стало 0.024 сек (~12x).
- `usage_summary.json` больше не создаётся; `ai-coder usage` читает
  JSONL напрямую (как и раньше).

### Тесты
- 56 passed.

---

## [2026-10-07] iteration 6.9 — perf(scanner): rglob с pruning

### Исправлено
- **review 5.2:** `scanner._load_specs_recursive` использовал `rglob`,
  который обходил все подкаталоги, включая `.venv`, `.git`,
  `.mypy_cache`, `.ruff_cache`, `.pytest_cache`. Теперь обход
  с pruning: служебные каталоги пропускаются до захода.

### Эффект
- Синтетический проект (.venv 5000 файлов): 0.0035 -> 0.0001 сек (~30x).
- Реальный `ai-coder`: находилось 5 .gitignore (корень + артефакты
  кэшей/venv), теперь 1 — только проектный. Правила из чужих файлов
  больше не примешиваются.

### Тесты
- 56 passed.

---

## [2026-10-07] iteration 6.8 — perf(scanner): PathSpec один раз

### Исправлено
- **review 5.3:** `scanner._match_any` компилировал `PathSpec` **на каждый
  файл и директорию**. Теперь `PathSpec` компилируется **один раз**
  в `scan_project` (функция `_compile_spec`), а в обход передаётся
  готовый spec.

### Метрика
- На синтетическом проекте 5000 файлов: **0.82 → 0.37 сек (~2.2x)**.
- На реальных проектах (монорепо, много паттернов) эффект масштабируется
  с количеством файлов.

### Тесты
- 56 passed (регрессий нет).

---

## [2026-10-07] iteration 6.7 — CI (GitHub Actions)

### Добавлено
- `.github/workflows/test.yml`:
  - pytest на Python 3.10, 3.11, 3.12 (матрица);
  - ruff — стиль и импорты;
  - mypy — типизация.
- Кэш pip через actions/setup-python (`cache: pip`).
- `workflow_dispatch` — запуск вручную.
- Бейдж CI в README.

### Изменено
- ruff.toml — конфиг с `select`/`ignore` (B008, BLE001, DTZ005 и др.).
- pyproject.toml — `[tool.pytest.ini_options]`.
- Автофиксы ruff (49 правок): порядок импортов, W291.
- mypy: реальные баги в `cli.py` (e вне except → err), `apply.py`
  (Path vs str), `agent.py` (TYPE_CHECKING + WritePlan), `llm.py`
  (create_kwargs + type: ignore), `cli.py` (peak_window).
- actions/checkout v4→v5, actions/setup-python v5→v6.

### Итог
- pytest — 56 passed (x3 Python)
- ruff check . — All checks passed
- mypy ai_coder — Success: no issues found in 13 source files

### TODO
- pytest-cov для измерения покрытия (в перспективе).

---

## [2026-10-07] iteration 6.6 — agent --preview-only

### Добавлено
- `agent --preview-only` — только план от планировщика, без выполнения
  шагов. Экономит токены: preview стал стоить как один запрос
  планировщика (~0.05 RUB), а не как N шагов (~11 RUB).
- Валидация: `--preview-only` нельзя совмещать с `--apply`.
- В панели `agent` — строка `Только план: да (--preview-only)`.
- После таблицы шагов — подсказка:
  `Режим --preview-only: шаги не выполнены...`.

### Изменено
- `AgentRunResult.stopped_reason = "preview_only"` при этом режиме.

### Замечено
- Preview агента **без** флага по-прежнему дорогой (6 шагов ~ 11 RUB).
  Это ожидаемо; `--preview-only` — правильный способ посмотреть план.

### Тесты
- 56 passed (без изменений).

---

## [2026-10-07] iteration 6.5 — правки агента (review 1.1/1.2 + TODO 🔥)

### Исправлено
- **review 1.2:** `pricing._save_cache` — не падать при невозможности
  записать `rates_cache.json` (read-only FS, нет прав). Молча пропускает.
- **review 1.1:** `actions.run_fix_action` — перепроверка кэшированного
  плана после cache hit: если blacklist изменился и план стал невалиден,
  идём в API заново.
  (В `run_action` перепроверка уже была.)

### Добавлено
- В CLI шага агента показывается количество применённых операций:
  `применено (N операций)`.
- `StepResult.skipped` и `skip_reason` — пустой план помечается как
  `пропущено` (а не «применено 0 операций»).
- `AgentPlan.empty` — отделяет «план пуст» (норма) от «ошибка парсинга».
  `run_agent` возвращает `stopped_reason = "empty_plan"`.
- `parse_agent_plan` — фильтрует «диагностические» шаги
  (по ключевым словам: диагностика, проанализируй, составь список,
  проверь, изучи, прочитай, опиши, исследуй).

### Тесты
- `test_parse_agent_plan_empty_steps` — теперь проверяет `empty=True`.
- `test_parse_agent_plan_valid_json_with_steps` — новый.
- `test_parse_agent_plan_skips_diagnostic_steps` — новый.
- `test_parse_agent_plan_all_steps_diagnostic_becomes_empty` — новый.

### Итого тестов
- 56 passed

### Замечено (в TODO)
- Preview агента дорогой: 6 шагов x 50K prompt-токенов = ~11 RUB.
- В preview пустые шаги не помечаются как `skipped` (только в apply).
- См. TODO: 3.5, 3.6, 3.7.

---

## [2026-10-07] iteration 6.4 — docs и обзор

### Добавлено
- README.md (пересобран через `write_readme` / `deepseek-v4-pro`)
- TODO.md — 54 пункта, 11 разделов, приоритеты
- docs/reviews/v4-pro-2026-10-07.md — обзор от `deepseek-v4-pro`
- docs/state.md — текущее состояние
- CHANGELOG.md — этот файл

### Изменено
- config/config.yaml — `suggest_improvements`:
  `max_output_tokens: 16000`, `temperature: 0.4`
- Убраны trailing whitespace в config.yaml

### Известные проблемы
- См. `docs/state.md` и `TODO.md`

---

## [2026-10-06] iteration 6.3 — эксперименты с агентом

### Замечено (не изменено в коде)
- Агент на markdown-задаче: 5 шагов, все «применено»,
  но README не изменился. Причина: нет verify для markdown.
- `flash --depth deep` на `suggest_improvements`: обрезка
  по `max_output_tokens: 8000`, пустой ответ.
- `v4-pro --depth deep`: 15921 токенов, полный отчёт (~5.4 RUB).
- Кэш отчётов возвращает план без перепроверки при cache hit.

### Исправлено
- В `_render_write_section` (output.py) — текст про применение
  (устаревшее «в следующих версиях»)

---

## [2026-10-06] iteration 6.2 — тесты для агента

### Добавлено
- tests/test_agent.py — 8 тестов:
  `parse_agent_plan`, `_render_plan_summary`, `run_planner`
- Покрыто: обёртки JSON, мусор, пустые steps, unknown type

### Итого тестов
- 53 passed

---

## [2026-10-06] iteration 6.1 — откат шага агента при verify fail

### Исправлено
- `agent._run_agent_step` — откат шага при `verify_errors`
  независимо от `max_fix_attempts`
- Раньше: если `max_fix_attempts == 0`, шаг с ошибкой
  оставался применённым. Теперь — откат.

---

## [2026-10-06] iteration 6 — агент

### Добавлено
- ai_coder/agent.py — планировщик, шаги, цикл, журнал
- config/prompts.yaml — `agent_plan_json`, `agent_step_json`
- config/config.yaml — секция `agent:`
- cli.py — команда `agent` с флагами
  `--apply`, `--verify`, `--max-steps`, `--max-minutes`,
  `--max-fix-attempts`, `--journal`
- Журнал: `plan.json`, `step-N.md`, `report.md`

### Артефакт
- Пробный запуск на /tmp/agent-test: 2 шага, оба успешно,
  докстринги добавлены, ~0.06 RUB

---

## [2026-10-06] iteration 5 — тесты

### Добавлено
- tests/conftest.py — фикстуры (minimal_cfg, sample_project, prompts_cfg)
- tests/test_scanner.py — 6 тестов
- tests/test_apply.py — 21 тест (парсинг, валидация, apply, rollback)
- tests/test_pricing.py — 10 тестов
- tests/test_cache.py — 8 тестов

### Итого тестов
- 45 passed

### Регрессии закрыты
- Бэкап оригинала, а не промежуточного состояния
- Пересекающиеся правки в одном файле

---

## [2026-10-06] iteration 4.8 — max_output_tokens per-action

### Добавлено
- `ActionConfig.max_output_tokens` и `temperature`
- `refactor`: 12000 / 0.2 (было 8000 / 0.3)
- Warning в консоли и отчёте при `finish_reason == "length"`

### Изменено
- `llm.LLMClient.chat` — параметры `max_tokens`, `temperature`

---

## [2026-10-06] iteration 4.7 — UX-полировка

### Добавлено
- `ai-coder actions --verbose` — оценка стоимости на текущем проекте

### Изменено
- Удалены мёртвые промпты `write_readme` / `add_docstrings` /
  `refactor` (без `_json`) из prompts.yaml
- Актуализирован текст в `_render_write_section`

---

## [2026-10-06] iteration 4.6 — авто-исправление ошибок

### Добавлено
- `actions.run_fix_action` — fix-итерация
- config/prompts.yaml — `fix_errors_json`
- config/config.yaml — секция `fix:`
- cli.py — цикл fix после apply, флаги `--max-fix-attempts`,
  `--no-auto-fix`
- Откат к `attempt0` при провале всех попыток
- Бэкапы `backup-<ts>-attemptN/`

### Проверено E2E
- Искусственная поломка: модель починила за 1 итерацию
- `usage.jsonl`: `agent:plan`, `agent:step1`, `agent:step2`

---

## [2026-10-06] iteration 4.5 — кэш отчётов

### Добавлено
- ai_coder/cache.py — `compute_hash`, `save`, `from_cache`
- `OutputConfig.use_cache`, `cache_dir_name`
- Флаги CLI `--no-cache`, `--refresh`
- Пометка «из кэша» в консоли и отчёте

### Проверено
- 98% cache hit при повторном запуске на том же проекте
- Стоимость снижается ~в 4 раза

---

## [2026-10-06] iteration 4.4 — usage с фильтрами

### Добавлено
- `ai-coder usage` — фильтры `--since`, `--until`, `--action`,
  `--project`, `--model`
- Экспорт `--export csv|json --out file`
- Группировки: by_action, by_model, by_project, by_day, by_iteration
- Поля `iteration`, `parent_action` в usage.jsonl

---

## [2026-10-06] iteration 4.3 — dry-run

### Добавлено
- `ai-coder run ... --dry-run` — оценка без API-запроса
- `_run_dry` в cli.py

### Исправлено
- Косметика в rollback — `done: set[str]`, без дублей в отчёте

---

## [2026-10-06] iteration 4 — применение правок

### Добавлено
- `apply.apply_plan` — применение с бэкапом и откатом
- `apply.rollback` — восстановление из бэкапа
- `apply.check_python_files` — py_compile
- Манифест `manifest.json` в бэкапе
- CLI: `--apply`, `--yes`, `--no-verify`, `rollback`, `backups`

### Исправлено
- Бэкап оригинала, а не промежуточного (баг с несколькими
  правками в одном файле)
- Откат create_file — удаление файла по манифесту

---

## [2026-10-06] iteration 3 — write-действия

### Добавлено
- JSON-формат ответа для write-действий
- `apply.WritePlan`, `Operation`, `parse_response`,
  `validate_operations`, `render_diff`
- `output._render_write_section` — секция с diff в отчёте
- config/prompts.yaml — `write_readme_json`, `add_docstrings_json`,
  `refactor_json`

---

## [2026-10-06] iteration 2 — LLM-клиент, peak/off-peak, usage

### Добавлено
- `llm.LLMClient` — клиент DeepSeek, извлечение cache hit/miss
- `pricing.is_peak_now`, `get_rate`, `calculate_cost`
- `usage.append_usage`, `_rebuild_summary`
- Цены DeepSeek в CNY, peak/off-peak, курсы ЦБ
- `ai-coder usage` — базовая сводка

---

## [2026-10-06] iteration 1 — сканер и первые действия

### Добавлено
- `scanner.scan_project` — обход, .gitignore, фильтры
- `prompts.render_prompt` — подстановка переменных
- `actions.run_action` — основной пайплайн
- `output.render_report`, `save_report`
- `cli.py` — Typer CLI: `actions`, `run`
- config/config.yaml, config/prompts.yaml
- Первые действия: `greet`, `inventory`, `suggest_improvements`
