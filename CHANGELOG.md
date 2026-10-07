# Changelog

Все значимые изменения проекта. Формат: `дата — итерация — краткое описание`.

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
