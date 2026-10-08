# Текущее состояние проекта

**Дата обновления:** 2026-10-08 (вечер, iteration 10.4)
**Ветка:** main
**Последний коммит:** (см. `git log -1 --oneline`)
**Тесты:** 280 passed | CI: pytest x3 + ruff + mypy — зелёный
**Статус:** рабочий инструмент, активная разработка

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
  - `--interactive` — подтверждение каждого dangerous (y/n/a/s/d);
  - `--max-iterations` — лимит итераций;
  - бэкап перед первым изменением + `ai-coder rollback` совместим;
  - журнал `tool-loop-<ts>/step-N.md` + `report.md`.

---

## Что не доделано

Смотри `TODO.md` (54 пункта). Главное:

- `agent.verify_commands` — не подключены (задел на будущее)
- Read-шаги агента (сейчас все шаги — `edit`)
- Пустой план (`operations: []`) не помечается как `skipped`
- CI / GitHub Actions
- `mypy` / `ruff` — не настроены
- Git-интеграция (ветки, автокоммит)

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

---

## Актуальные приоритеты

Сделано в итерациях 6.5–10.4:
- review 1.1–1.4, 5.2, 5.3 — закрыты
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
  - автокоммит после `finish(success)` (10.1) — история задач
    в `git log` с шаблоном `ai-coder: <goal> (N ops, X.XX RUB)`;
  - `--resume <journal-dir>` (10.2) — продолжение прерванного loop;
  - кэш phase1 (10.4) — при повторной задаче LLM не вызывается
    (экономия ~0.03 RUB на задаче);
  - промпт + `format_tool_history` (10.5): 5 → 2 итерации на
    атомарную задачу.
- Тестов: 186 → 280 (+94).

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

---

## Где что искать

| Файл | Что внутри |
|---|---|
| `README.md` | краткое описание, установка, использование |
| `TODO.md` | что осталось (54 пункта, приоритеты) |
| `CHANGELOG.md` | что сделано, по датам и итерациям |
| `docs/state.md` | этот файл, текущее состояние |
| `docs/reviews/` | внешние обзоры проекта |
| `config/config.yaml` | настройки (API, scanning, write, fix, agent) |
| `config/prompts.yaml` | тексты промптов по действиям |
| `.ai-out/` | результаты работы (отчёты, usage, кэш, бэкапы) |

---

## Как обновлять

После каждой значимой итерации:

1. Обновить `docs/state.md` — дата, последний коммит, что работает,
   известные проблемы, приоритеты.
2. Обновить `CHANGELOG.md` — добавить секцию с датой и номером итерации.
3. Обновить `TODO.md` — убрать выполненное, добавить новое.

Это 2-3 минуты, но экономит часы контекста при возвращении.
