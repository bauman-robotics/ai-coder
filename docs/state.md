# Текущее состояние проекта

**Дата обновления:** 2026-10-07 (утро + вечер)
**Ветка:** main
**Последний коммит:** (см. `git log -1 --oneline`)
**Тесты:** 56 passed | CI: pytest x3 + ruff + mypy — зелёный
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

Сделано в итерациях 6.5–7.2:
- review 1.2 — `get_rate` не падает на read-only FS
- review 1.1 — перепроверка плана при cache hit (частично)
- review 1.3 — usage пути из конфига + нет O(N^2) в summary
- review 1.4 — content-фильтр секретов (sk-, AKIA, ghp_, PEM и др.)
- review 5.2 — `_load_specs_recursive` без обхода служебных каталогов (~30x)
- review 5.3 — `PathSpec` компилируется один раз (~2.2x)
- TODO про агент: applied_count, skipped, empty_plan, фильтр диагностики
- `agent --preview-only` — только план, без шагов (~0.05 RUB вместо ~11)
- CI: GitHub Actions (pytest x3 + ruff + mypy) — зелёный

Осталось:

1. **TODO 3.6, 3.8** — экономия в обычном preview, замена эвристики
   диагностики на явный `type: read` в JSON-плане
2. **TODO 3.7** — `--preview-only` уже сделано, TODO обновить
3. **pytest-cov** — измерение покрытия тестами
4. **Review 5.4** — пересканирование проекта на fix-итерациях

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
