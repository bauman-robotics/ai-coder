# Changelog

Все значимые изменения проекта. Формат: `дата — итерация — краткое описание`.

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
