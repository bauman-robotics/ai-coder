# Текущее состояние проекта

**Дата обновления:** 2026-10-13 (итерации 10.29–10.34: `--no-verify`, chain report, read-шаги, GUI A.0+A.1)
**Ветка:** main
**Последний коммит:** `e07c857` (GUI A.1) + docs 10.34
**Тесты:** 409 passed | CI: pytest x3 + ruff + mypy — зелёный
**Статус:** рабочий инструмент, безопасность закрыта, автономность проверена (E9), цепочка `--split-goals` → `--chain --plan` работает, есть веб-панель (A.0+A.1)

---

## Что это

`ai-coder` — CLI-инструмент для AI-ассистированного анализа и правки
Python-проектов через DeepSeek API. Работает с git-проектами: сканирует
исходники, отправляет их в LLM, возвращает отчёты или предлагает правки.

---

## Что работает

### CLI

- `ai-coder actions [--verbose]` — список действий, с оценкой стоимости
- `ai-coder run <action> [path]` — выполнить действие
- `ai-coder agent "<goal>" [path]` — агент: план + шаги
- `ai-coder usage` — сводка расходов с фильтрами и экспортом
- `ai-coder backups [path]` — список бэкапов
- `ai-coder rollback <backup> [path]` — откат

### Действия (read)

- `greet` — обзор проекта
- `inventory` — инвентарь классов и функций
- `suggest_improvements` — предложения по улучшению

### Действия (write)

- `write_readme` — генерация README
- `add_docstrings` — добавление докстрингов
- `refactor` — предложения рефакторинга

### Применение

- JSON-план с операциями `edit_file` / `create_file`
- Валидация (пути, blacklist, уникальность old, пересечения)
- Бэкап перед применением
- `py_compile` после применения
- Авто-fix ошибок (`--max-fix-attempts`)
- Откат при провале verify

### Учёт

- `usage.jsonl` — все запросы с токенами, стоимостью, курсами
- `usage_summary.json` — агрегаты
- Peak/off-peak тарифы, cache hit/miss, CNY/RUB/USD
- Группировки: by_action, by_model, by_project, by_day, by_iteration

### Кэш

- Хэш по (файлы + промпт + модель + depth)
- `.ai-out/<project>/cache/<hash>.json`
- Флаги `--no-cache` / `--refresh`

### GUI (A.0 + A.1)

Веб-панель на FastAPI + Jinja2 + HTMX (тёмная тема).

- `GET /` — форма сборки команд:
  - **goal** (textarea), **path** (input + datalist последних из localStorage);
  - **mode** (select: `plain` / `tool-loop` / `decompose` / `plan` / `chain` / `split-goals`);
  - **model** (select: `default` / `flash` / `v4-pro`);
  - **флаги** — `--apply`, `--commit`, `--dry-run`;
  - **`--max-cost-rub`** (number);
  - **advanced-flags** — `details+textarea` для произвольных флагов.
- `POST /build` — собирает строку `ai-coder agent "..." . --tool-loop --apply ...`
  и возвращает `<pre>`. Кнопка «Скопировать» → `navigator.clipboard`.
- `GET /health` → `{"status":"ok"}`.
- `/static` — CSS.

**Запуск:**

    pip install -e ".[gui]"
    uvicorn ai_coder.gui.app:app --reload --port 8000
    # http://127.0.0.1:8000/

**A.2:** запуск команды со стримингом (SSE).
- `POST /run` — `subprocess.Popen([sys.executable, "-m", "ai_coder.cli", ...])`,
  `StreamingResponse(text/event-stream)`, формат `data: <строка>\n\n`.
- `POST /stop/{run_id}` — SIGTERM процессу. `RUNNING: dict[str, Popen]`.
- Кнопки «Запустить»/«Остановить» в браузере (fetch + ReadableStream).
- `DEEPSEEK_API_KEY` — `uvicorn` должен запускаться с `export`.

**Не умеет (A.3+):** встроенный терминал (PTY+WebSocket, этап B),
история/статистика из `usage.jsonl`, ссылки на отчёты. См. `docs/ui-ideas.md`.

### Agent

- Планировщик: LLM → JSON-план шагов
- Цикл: план → шаг → apply → verify → fix
- Журнал: `plan.json`, `step-N.md`, `report.md`
- Откат неудачного шага
- Автовыбор `only_paths` из плана: шаги 2+ видят только
  `target_files` (8.5). Одношаговый план — сужен и шаг 1 (8.6)
- Phase1: планировщик видит только дерево + метаданные,
  возвращает `target_files` для phase2 (8.7)
- Git-интеграция: проверка чистоты + автокоммит после `--apply`
  (`--commit`), `--max-cost-rub` (8.8)
- **Tool loop** (`--tool-loop`): модель сама вызывает инструменты
  до завершения (9.1–9.4):
  - инструменты: `read_file`, `list_files`, `write_file`,
    `edit_file`, `run_shell` (whitelist, timeout, лог);
  - `--dry-run` — dangerous не выполняются, только логи;
- `--dry-read` — read-only команды (`ls/cat/grep/find/head/tail/wc`,
  `git status/diff/log/show/branch/rev-parse/ls-files`) выполняются
  реально; `write_file`/`edit_file` и остальные `run_shell` — блокируются.
  Несовместим с `--dry-run`. Решает проблему `--dry-run` для read-задач
  (E16: 1 итерация, 0.075 RUB vs 8 итераций, 0.41 RUB);
  - `--interactive` — подтверждение каждого dangerous (y/n/a/s/d);
  - `--max-iterations` — лимит итераций;
  - бэкап перед первым изменением + `ai-coder rollback` совместим;
  - журнал `tool-loop-<ts>/step-N.md` + `report.md`.
  - **Безопасность (10.15):**
    - blacklist в tool loop: `write_file`/`edit_file` не пишут
      в `.git/**`, `config/**`, `pyproject.toml`, `.env`
      (флаг `--allow-blacklist` — осознанный обход);
    - `mask_secrets` в `read_file`/`run_shell` — API-ключи,
      токены, PEM не уходят в LLM;
    - `run_verify_commands` без `shell=True` — RCE-вектор закрыт,
      blacklist первого токена (`rm`, `dd`, `sudo`, ...);
    - `run_shell` whitelist аргументов (10.18): `find` без
      `-delete`/`-exec`, `tail` без `-f`, `git branch` без `-D`,
      `git log` без `--exec`.
  - **Навигация (10.16):**
    - `read_symbol(name, path?, kind?)` — 6-й инструмент:
      тело функции/класса Python по имени, без `grep`+`read_file`.
      E2E: **2 итерации вместо 3**, 0.11 RUB вместо 0.13.
      Python-only; для C/C++ — направление 9 roadmap.
  - **Автономность (10.17):**
    - `--auto-fix-issues` — после tool loop, если verify упал,
      запускается `run_auto_fix` (до 3 попыток).
      E2E: сломанный `calc.py` → verify fail → auto-fix → success
      (0.1460 RUB, 2 попытки). Требует `--tool-loop`.
  - **Автономность (10.19):**
    - `--with-tests` — после успешного tool loop агент пишет
      pytest-тесты для изменённых файлов (второй tool loop).
      E2E: 3 итерации, 0.1945 RUB, обновляет существующий
      `test_calc.py`. Требует `--tool-loop`.
  - **Issue-driven (10.20):**
    - `--issue <file>` — задача из Markdown-файла вместо CLI.
      Работает с GitHub issues, `issues/*.md`, roadmap-кусками.
      Парсит `# task:`-заголовок, обрезает до 60 строк.
  - **Планировщик из human-goal (10.24):**
    - `--plan` — задача человеческим языком → v4-pro разбивает
      на подзадачи → таблица + `plan.yaml` → вопрос `y/n/e`
      (`e` — править план в `$EDITOR`) → при `y` выполнение
      **без повторного планирования** (`run_agent_decompose(plan=...)`).
    - E2E: `--plan` + `n` → 0.08 RUB, правок нет;
      `--plan` + `y` → 0.26 RUB, одна строка «Декомпозиция: 2 подзадач»,
      `sub` добавлен, `3 passed`.
  - **Пакетное выполнение issues (10.25):**
    - `--chain <dir>` — цикл по `sorted(dir.glob("*.md"))`.
    - Три режима: `--tool-loop`, `--tool-loop --decompose`,
      `--tool-loop --plan` (все планы → один `y/n/e` → decompose
      без перепланирования).
    - `--stop-on-fail` (default) / `--continue-on-fail`.
    - Итоговая таблица: задача / статус / RUB.
    - E2E: 3 режима, все ✅, 0.12–0.36 RUB.
  - **Разбиение фразы на issues (10.26):**
    - `--split-goals "<goal>"` — v4-pro разбивает одну фразу
      на N **независимых** issues, сохраняет `issues/N-<slug>.md`.
    - **Не выполняет** — только создаёт файлы.
    - `_slug_for_issue` — транслит кириллицы.
    - E2E: 3 issues (0.19 RUB) → `--chain --plan` → 3 задачи ✅
      (0.77 RUB). Полная цепочка ~0.95 RUB.
  - **chain report.md (10.30):**
    - `_save_chain_report` пишет `report.md` в `chain-<ts>/`
      **всегда** — включая полный провал.
    - `stopped_reason="no_ops"` при `success=True, applied_ops=0`.
    - `report_path` в dict + вывод «Отчёт: ...» в консоль.
  - **step_type + read_ops (10.31):**
    - `run_tool_loop(step_type)` — критерий успеха по типу шага:
      `edit` → `applied_ops > 0`, `read` → `read_ops > 0`,
      `None` → доверие LLM (обратная совместимость).
    - `ToolLoopResult.read_ops` — счётчик чтений.
    - Правило успеха **переехало** внутрь `run_tool_loop`
      (было в `run_agent_decompose` и `_run_chain`).
  - **read-шаги в плане (10.32):**
    - `parse_agent_plan` принимает `type: "read"`.
    - `_is_diagnostic_step` **переклассифицирует** `edit` → `read`
      (было — отбрасывал).
    - Промпт `agent_plan_json` разрешает `type: "read"`.
  - **read-шаги в `run_agent` (10.33):**
    - `_run_read_step` — для read-шага вызывает
      `run_tool_loop(step_type="read")`.
    - `StepResult.read_answer` — текстовый ответ.
    - verify не запускается (read не меняет файлы).
    - ответ печатается в консоль (Panel).
  - **Автономность (10.22, в работе):**
    - `docs/autonomy.md` — принципы (4 уровня), план.
    - **Этап 1 (E8):** граница flash — серия задач нарастающей
      сложности. Точное правило для `--issue`.
    - **Этап 2:** улучшение replan — история подзадачи, измельчение.
    - **Этап 3 (E9):** повторить задачу 1.5 с улучшенным replan.

---

## Что не доделано

Смотри `TODO.md` (54 пункта). Главное:

- `agent.verify_commands` — не подключены (задел на будущее)
- Read-шаги агента (сейчас все шаги — `edit`)
- Пустой план (`operations: []`) не помечается как `skipped`
- CI / GitHub Actions
- `mypy` / `ruff` — не настроены
- Git-интеграция: ветки `ai-coder/<slug>-<ts>`, push, PR
  (автокоммит уже есть с 8.8)
- **Направление 10, остаток:** `--interactive-plan` (C — диалог
  уточнений), `--context-search` (D — агент сам ищет контекст).
  Уровни **A, B, E, F** закрыты (10.24–10.26).
- **`--split-goals`: pre-check «уже решено»** — не реализован.

---

## Известные проблемы

Из review `deepseek-v4-pro` (см. `docs/reviews/v4-pro-2026-10-07.md`):

- **1.1** Кэш не перепроверяет план после cache hit (может применять
  правки в файлы, добавленные в blacklist после кэширования)
- **1.2** `pricing.get_rate` падает, если `.ai-out` не writable
- **1.3** `usage.jsonl`/`usage_summary.json` игнорируют конфиг — ✅ исправлено (7.0)
- **1.4** Нет content-level фильтрации секретов
- **5.2** `rglob(".gitignore")` заходит в `.venv`, `node_modules`
- **5.3** `PathSpec` компилируется на каждый файл — ✅ исправлено (6.8)

Локальные:

- `Path.is_relative_to` требует Python 3.9+ (проверить 3.10-совместимость)
- Кэш сохраняет и обрезанные ответы (`finish_reason: length`)
- **Tool loop — известные проблемы (2026-10-08):**
  - ✅ `format_tool_history` обрезал `read_file` — **исправлено (10.8)**.
  - ✅ Нет правила для `'old' not found` — **исправлено (10.8)**.
  - ✅ Backticks в CLI-промпте съедаются bash — **исправлено (10.10)**.
  - `--dry-run` не меняет виртуальный файл → модель перечитывает.
  - Промпт > 15 строк — модель теряет фокус.
  - Агент не справляется с задачами на 5+ файлов.
  - См. подробно `TODO.md`, раздел «Известные проблемы tool loop».

---

## Актуальные приоритеты

Сделано в итерациях 6.5–10.14:
- review 1.1–1.4, 5.2, 5.3 — закрыты

**Сессия 1: security (10.15, 2026-10-10):**
- review 1.1 — blacklist для tool loop (`--allow-blacklist`);
- review 1.2 — `mask_secrets` в `read_file`/`run_shell`;
- review 1.3 — `run_verify_commands` без `shell=True`.
- CI + coverage + pre-commit — настроены
- Покрытие тестами: 40% -> 73% (144 теста)
- Сканер: пустые + приоритизация + content-секреты + вёрстка
- Сканер: `--only-path` — селективный контекст до файла/директории (8.4)
- CLI: `--max-tokens`, `--exclude-web`/`--include-web`,
  `--verify-commands`, `--only-path`
- **Уровень A: verify_commands** — агент сам запускает pytest
- **Уровень B: --interactive** — подтверждение каждого шага (y/n/a/s/d)
- **Self-hosted E2E** — агент правит свой же код
- Баги self-hosted E2E закрыты: parse_error/finish_reason в errors,
  `step_max_output_tokens`, `max_tokens` в `client.chat`
- Баг `--only-path` закрыт: 0 файлов → 1 файл (8.4)
- Автовыбор `only_paths` из плана агента (8.5): шаги 2+ видят
  только `target_files`.
- Одношаговый план: шаг 1 тоже сужен (8.6). E2E: шаг 1 — 1482
  токена вместо 41209 (в 28 раз), стоимость 0.0249 RUB вместо
  0.5358 RUB. Total E2E: 0.556 RUB вместо 1.086 RUB.
- Phase1: metadata-планировщик (8.7). E2E: планировщик —
  0.025 RUB вместо 0.53 RUB (в 21 раз). Total E2E: 0.051 RUB
  вместо 0.556 RUB (в 11 раз).
- Git-интеграция (8.8): `git.py`, `GitConfig`, флаги
  `--commit` / `--require-clean` / `--max-cost-rub`, автокоммит
  с шаблоном `ai-coder: <goal> (N ops, X.XX RUB)`, 24 теста.
- **Уровень C — tool loop (9.1–9.4):**
  - 5 инструментов, безопасность (`_safe_path`, whitelist shell);
  - `run_tool_loop`: LLM → инструмент → результат → LLM;
  - CLI: `--tool-loop`, `--max-iterations`, `--dry-run`,
    `--interactive`;
  - бэкап + `ai-coder rollback` совместим;
  - журнал `tool-loop-<ts>/`.
- **Tool loop — автономность (10.1–10.4):**
  - автокоммит после `finish(success)` (10.1);
  - `--resume <journal-dir>` (10.2);
  - кэш phase1 (10.4);
  - промпт + `format_tool_history` (10.5): 5 → 2 итерации.
- **Fix `format_tool_history` (10.8):**
  - `read_file` в истории: 3000 → **10000 символов**;
  - пометка «Используй `run_shell grep`» при обрезке;
  - правило 12 в промпте: при `'old' not found` — `grep`;
  - E2E: 15 итераций → **1**, 1.82 → **0.10 RUB**, ❌ → **✅**.
- **Предупреждение про backticks (10.10):**
  - в `agent_cmd`: если в `goal` есть обратные кавычки —
    предупреждение + подсказка про файл;
  - закрывает п.10 из TODO.
- **Декомпозиция задач (10.11.2):**
  - `Subtask`, `DecomposeResult` — dataclass'ы;
  - `parse_decompose_response` — парсер;
  - `run_planner_decompose` — v4-pro разбивает на подзадачи;
  - `run_agent_decompose` — последовательный `run_tool_loop`;
  - CLI: `--decompose` (вместе с `--tool-loop`);
  - `decompose_model` в config;
  - промпт `agent_decompose_json`;
  - E2E: **2 подзадачи × 1 файл**, ✅ успех, 0.64 RUB.
- **Правило 14 (10.11.7):** «изменение уже есть» → finish.
- **Retry через v4-pro (10.11.7):** при fail подзадачи — повтор.
- **Replan при fail v4-pro (10.11.8):**
  - `ReplanResult` + `parse_replan_response`;
  - `run_planner_replan` — v4-pro анализирует fail;
  - `--decompose-replan` — opt-in;
  - skip/modify/stop.
- **Документация (10.11.6):** раздел «Декомпозиция задач».
- Документация: `docs/tools.md` (написана агентом через tool loop),
  README, TODO (10 разделов известных проблем).
- Тестов: 186 → **283** (+97).

Осталось:

1. **Уровень D.1 (автокоммит для tool loop)** — сделано в 10.1.
   Отложено: ветки `ai-coder/<slug>-<ts>`, push, PR (без веток —
   только коммит в текущую ветку).
2. **Улучшения tool loop:**
   - read-шаги в `run_agent` (не только edit);
   - кэш phase1 (для похожих задач);
   - YAML-правки (модель слабо справляется).
3. **`agent.py`** — 43% покрытия (190 строк)
4. **`apply.py`, `pricing.py`, `prompts.py`** — покрытие до ~90%
5. **YAML-правки** — модель слабо справляется, усилить промпт

---

## Артефакты и пути

    .ai-out/
    ├── usage.jsonl                    все запросы, append-only
    ├── usage_summary.json             агрегаты
    ├── rates_cache.json               кэш курсов ЦБ
    └── <project>/
        ├── <action>-<ts>.md           отчёты
        ├── <action>-<ts>.md.raw.txt   сырые ответы
        ├── cache/<hash>.json          кэш по хэшу
        ├── backup-<ts>-attemptN/      бэкапы применения
        └── agent-<ts>/                журналы агента
            ├── plan.json
            ├── step-N.md
            └── report.md

---

## Стек

- Python >= 3.10
- Typer (CLI), Rich (вывод), Pydantic v2 (конфиги)
- openai SDK (клиент DeepSeek), httpx (курсы ЦБ)
- pathspec (gitignore), pyyaml
- fastapi, uvicorn, jinja2, python-multipart (gui extras)
- pytest (тесты), ruff, mypy (dev)

---

## Как запустить

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements-dev.txt
    pip install -e .

    export DEEPSEEK_API_KEY=sk-...

    python -m pytest tests/ -v
    python -m ai_coder.cli actions --verbose
    python -m ai_coder.cli run greet . --depth shallow

**GUI:**

    pip install -e ".[gui]"
    uvicorn ai_coder.gui.app:app --reload --port 8000
    # http://127.0.0.1:8000/

---

## Где что искать

| Файл | Что внутри |
|---|---|
| `README.md` | краткое описание, установка, использование |
| `TODO.md` | что осталось (54 пункта, приоритеты) |
| `CHANGELOG.md` | что сделано, по датам и итерациям |
| `docs/state.md` | этот файл, текущее состояние |
| `docs/autonomy.md` | автономность: принципы, план (E8-E9) |
| `docs/reviews/` | внешние обзоры проекта |
| `config/config.yaml` | настройки (API, scanning, write, fix, agent) |
| `config/prompts.yaml` | тексты промптов по действиям |
| `ai_coder/gui/` | веб-панель (FastAPI + Jinja2 + HTMX, A.0+A.1) |
| `.ai-out/` | результаты работы (отчёты, usage, кэш, бэкапы) |

---

## Как обновлять

После каждой значимой итерации:

1. Обновить `docs/state.md` — дата, последний коммит, что работает,
   известные проблемы, приоритеты.
2. Обновить `CHANGELOG.md` — добавить секцию с датой и номером итерации.
3. Обновить `TODO.md` — убрать выполненное, добавить новое.
4. Обновить `docs/what-is-ai-coder.md` — если изменилось:
   - **«Что умеет сейчас»** — новая команда, флаг, режим;
   - **«Что в плане»** — фича **закрыта** (перенести в «сейчас»);
   - **«Стоимость»** — изменились цены или типичные суммы;
   - **Дата** и **Версия** в конце файла.

Это 3-4 минуты, но экономит часы контекста при возвращении.
