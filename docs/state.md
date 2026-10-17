# Текущее состояние проекта

**Дата обновления:** 2026-10-17 (10.79 — структура отчётов; инцидент: потеря старых логов)
**Ветка:** main
**Последний коммит:** `15fc6aa` (test: изоляция тестов от реальных issues/commands; выше — merge `397a534`)
**Тесты:** 624 passed (605 + 19 reports-structure: 14 в 173c44e, +4 в af8246c, +1 в ac010e0) | CI: pytest x3 + ruff + mypy — зелёный
**Статус:** рабочий инструмент; безопасность закрыта; автономность проверена (E9);
цепочка `--split-goals` → `--chain --plan` работает; веб-панель A.0–A.18.

**Split-file (10.65):** `ai_coder/agent.py` (3614 строк) разбит на пакет
`ai_coder/agent/` из 9 модулей — все ≤1021 строк:
- `models.py` (251) — 14 dataclass-ов
- `planner.py` (1021) — парсеры + run_planner*
- `reverse.py` (184) — reverse-check
- `tool_loop.py` (922) — tool loop
- `autofix.py` (181) — auto-fix
- `decomposer.py` (493) — декомпозиция
- `classic.py` (~450) — классический агент
- `_legacy.py` (~40) — compatibility-shim для патчей в тестах
- `__init__.py` (~100) — реэкспорт публичного API

**Зачем:** Flash теряет фокус на файлах >1000 строк (E7, E11). После split-file
агент может читать и править любой свой модуль целиком.

**Read_symbol (10.66):** `read_symbol` теперь работает не только с `.py`,
но и с C/C++/JS/TS/Go через новый модуль `ai_coder/symbols.py` (154 строки,
regex-парсер без зависимостей). Python-путь не изменён (регрессия E3).

**Структура отчётов (10.79, 2026-10-17):** новые прогоны пишут отчёты
в `.ai-out/<project>/<YYYY-MM-DD>/<NN>_<mode>_<slug>/`:
- `goal.txt` — полная CLI-команда (копия `commands/<date>/<NN>_<slug>.txt`);
- `report.md` — итоговый отчёт;
- `step-N.md` / `subtask-N/` / `issues/*.md` / `attempt-N/` / `autofix/` —
  по режиму.
`<NN>` — общий для `commands/` и `.ai-out/` (связь по `<NN>_<slug>`).
`run` теперь тоже пишет `commands/` + папку задачи. `split-goals` — без
папки в `.ai-out`. Старые (legacy) отчёты читаются как раньше.
GUI: кнопка «Скопировать путь».
**Важно:** `ai-coder` (console script) из worktree импортирует
**main**-код (editable `.pth`); для worktree — `PYTHONPATH` или
`python -m ai_coder.cli`. См. `docs/incidents.md` (2026-10-17 — потеря
старых логов `.ai-out`).

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

### GUI (A.0–A.8)

Веб-панель на FastAPI + Jinja2 + HTMX (тёмная тема).

- `GET /` — форма сборки команд:
  - **goal** (textarea), **path** (input + datalist последних из localStorage);
  - **mode** (select: `plain` / `tool-loop` / `decompose` / `plan` / `chain` / `split-goals`);
  - **model** (select: `default` / `flash` / `v4-pro`; value = API-имя
    `deepseek-flash` / `deepseek-v4-pro`);
  - **флаги** — `--apply`, `--commit`;
  - **check_mode** (select: `normal` / `dry-run` / `dry-read`);
  - **`--max-cost-rub`** (select: без ограничения, 0.1, 0.2, 0.5, 1, 2, 5, 10);
  - **advanced-flags** — `details+textarea` для произвольных флагов.
- `POST /build` — собирает строку `ai-coder agent "..." . --tool-loop --apply ...`
  и возвращает `<pre>`. Кнопки «Скопировать» (команда) и «Скопировать вывод» (`#run-output`).
- `GET /health` → `{"status":"ok"}`.
- `/static` — CSS.

**Fix (после A.3):**
- `model` value = `deepseek-flash`/`deepseek-v4-pro` (API требует полное имя).
- `path` — всегда (`.`, если пусто — второй позиционный аргумент `agent_cmd`).

**Запуск:**

    cp .env.example .env && nano .env   # вставь DEEPSEEK_API_KEY
    chmod 600 .env                       # один раз
    bash scripts/run_gui.sh 8000         # Ctrl+C — стоп
    # или: bash scripts/run_gui.sh 8000 --reload
    # http://127.0.0.1:8000/

**Остановка:**

    bash scripts/stop_gui.sh 8000        # по порту
    bash scripts/stop_gui.sh all         # все uvicorn ai_coder.gui

**API-ключ:** `.env` (локальный) или `~/.ai-coder.env` (глобальный).
`run_gui.sh` подхватывает автоматически. `.env` — в `.gitignore`.

**A.2:** запуск команды со стримингом (SSE).
- `POST /run` — `subprocess.Popen([sys.executable, "-m", "ai_coder.cli", ...])`,
  `StreamingResponse(text/event-stream)`, формат `data: <строка>\n\n`.
- `POST /stop/{run_id}` — SIGTERM процессу. `RUNNING: dict[str, Popen]`.

**A.3:** улучшения формы.
- `max-cost-rub`: input → select (8 значений).
- `copy-output-btn`: копирует `pre#run-output` в clipboard
  (navigator.clipboard + fallback execCommand).

**A.4:** `dry-run` checkbox → `check_mode` select (`normal`/`dry-run`/`dry-read`).
- Кнопки «Запустить»/«Остановить» в браузере (fetch + ReadableStream).
- `DEEPSEEK_API_KEY` — `uvicorn` должен запускаться с `export`.

**A.5:** ссылка на отчёт после `/run`.
- `app.py`: `mount("/ai-out", StaticFiles(...))` — статический доступ
  к `.ai-out` (для `report.md`, `plan.json`, `step-N.md`).
- JS в `index.html`: ловит `Журнал: <path>` в SSE (`data:`) →
  ссылка «Открыть отчёт».

**A.6:** рендер `report.md` в HTML.
- `app.py`: `GET /reports/{project}/{journal}` — `markdown.markdown(...)`
  → `report.html` (шаблон с `markdown-body`, тёмная тема).
- `_safe_report_path` — защита от path traversal (`relative_to AI_OUT_DIR`).
- `templates/report.html` — шаблон (header, nav, `{{ content|safe }}`).
- `style.css` — стили markdown (h1-h3, code, pre, table, blockquote).
- Ссылка в `index.html` → `/reports/<project>/<journal>` (вместо raw
  `.md` — **отрендеренный** HTML).

**A.7:** список журналов.
- `app.py`: `GET /reports` — обход `.ai-out/*/*/report.md`,
  сортировка по mtime desc, рендер `reports.html`.
- `_collect_journals()` — защита от symlink-выхода за `AI_OUT_DIR`.
- `_parse_report_meta()` — парсер `- **Ключ:** значение` из шапки
  `report.md` (Успех / Стоимость / Итераций / Причина остановки).
- `_is_journal_dir()` + `JOURNAL_PREFIXES` — whitelist префиксов;
  backup/cache отсекаются отсутствием `report.md`.
- `templates/reports.html` — таблица (Дата / Проект / Журнал / Успех
  / Итераций / Стоимость / Причина / ссылка), 8 колонок.
- `index.html`: `<nav class="report-nav">` в `<header>` → «Все отчёты».
- `style.css`: `.reports-table` (тёмная тема, `ok`/`fail`/`num`).
- Живой прогон: **83 журнала** (67 tool-loop + 11 agent + 3 decompose
  + 2 autofix), `/reports/ai-coder/tool-loop-<ts>` → 200.
- **A.7+ (10.79):** `_collect_journals()` читает **оба** layout:
  legacy `<project>/<journal>/report.md` и новый
  `<project>/<date>/<task>/report.md`; nested-роут
  `GET /reports/{project}/{date}/{task}`; кнопка «Скопировать путь»
  (`data-path` = абсолютный путь к папке задачи) на странице отчёта
  и рядом с `#report-link` в форме.

**A.8:** статистика расходов.
- `app.py`: `GET /stats/data` — агрегаты из `usage.jsonl`
  (по дням/моделям/действиям), `GET /stats` — страница.
- `templates/stats.html` — 4 summary-карточки + 3 графика
  (Chart.js 4.4: line + doughnut + bar).
- `style.css`: `.stats-summary`, `.stat-card`, `.chart-wrap`,
  `.panel-row`.
- `index.html`: ссылка «Статистика» в nav.
- Живой прогон: **525 записей, 106.24 RUB, 4.8M токенов, 7 дней**.

**A.9:** страница справки `/help`.
- `app.py`: `GET /help` → `templates/help.html`.
- `templates/help.html` — 5 секций: Режимы, Опции, **Действия (run)**,
  Рекомендации, Примеры (`.panel` + `.markdown-body`). Секция
  «Действия» добавлена агентом 2026-10-13 (2 итерации, 0.18 RUB).
- `index.html`: ссылка «Справка» в nav.
- **Сделано агентом** (`--tool-loop`, 7 итераций, 0.6728 RUB,
  0 флейков) — **первый раз без правок вручную** на 3-файловой
  GUI-задаче. См. `docs/experiments.md` → E18.

**A.10:** кнопка «→ в форму» в `/help`.
- `help.html`: 5 примеров обёрнуты в `div.example` + кнопка
  `.use-example` с `data-cmd`. Первый блок (3 команды) не тронут.
  `<script>` в конце: клик → `sessionStorage.pending_command` → `/`.
- `index.html`: `parseCommand(cmd)` — токенизация, `action`, `goal`
  (в кавычках), `path`, `--tool-loop`/`--dry-read`/`--max-cost-rub`/
  `--apply`/`--commit`, `advanced_flags`. При загрузке:
  `pending_command` → заполнить форму → `#pending-notice`.
- `style.css`: `.example` / `.use-example` (`:hover`/`:active`) /
  `#pending-notice`.
- Сделано агентом (E18.3): 2 из 3 файлов (help.html + index.html),
  style.css доделан вручную. 1.05 RUB, max_cost.

**A.12:** расширения формы (2026-10-14).
- «Вставить команду» — `<details>` + textarea + кнопка
  «Заполнить форму» → `parseCommand` → `applyParsed` (новая функция).
- «Загрузить команду из файла» — `<input type="file" id="command-file">`
  + FileReader → `#paste-command.value` → `applyParsed`. ✅ 10.49.
- «Загрузить goal из файла» — `<input type="file">` + FileReader.
- ~~Поле `--issue <path>`~~ — **откачено** (commit `ebd1a6e`):
  дублировало «Из файла». См. CHANGELOG 10.48.
- Fix: `_build_argv` не передавал `reverse_check` в `_build_command`.
- **Как сделано:** Task 1+2 — агентом (2.28 + 0.81 RUB, RC ✅),
  Task 3 — вручную (откачен). См. E25.

**A.11:** run-команды в GUI (2026-10-14).
- `app.py`: `_build_command` — `task_type="agent"`, `run_action=""`,
  ветка `if task_type == "run"`. Для run: `ai-coder run <action> <path>`
  + `--model`/`--apply`/`--dry-run`/`advanced_flags`.
  **Без** `--max-cost-rub`/`--commit` (их нет у CLI `run`).
- `index.html`: select «Тип задачи» (`task_type`), select «Действие»
  (`run_action`, 7 действий), обёртки `.agent-only` (goal/mode/flags),
  JS `applyTaskType()`, ветка `run` в `parseCommand`, установка
  `task_type`/`run_action` из `pending_command`.
- `help.html`: секция `#run-examples` — 5 примеров run-команд
  с кнопками «→ в форму».
- `style.css`: `.field-hidden { display: none !important; }`.
- **Как сделано:** `app.py` — **агентом** (подзадача 1, ✅ 33 строки
  без ошибок). `index.html`/`help.html`/`style.css` — вручную
  (~1.5 ч, 0 RUB). **См.** E19.

**Fix (10.44):** `--max-cost-rub` игнорировался при `--decompose`.
Найдено в E19 (перерасход ×8.4). Исправлено в `cli.py` (2 места):
`decompose_max_cost_rub or max_cost_rub`.

**A.17:** GUI — поддержка `--chain` (2026-10-14, 10.56).
- `app.py`: `chain_path` в `_build_command`/`_build_argv`/`build`/`run`.
  Особая ветка `mode=chain`: `agent <path> --chain <dir> --tool-loop`
  (path — на месте goal, hack CLI). Дефолт `chain_path` — `issues`.
- `index.html`: `#chain-path` (видно при `mode=chain`),
  `applyModeConstraints` — toggle, `parseCommand` — распознаёт
  `--chain <dir>`, `applyParsed` — устанавливает.
- **10.57:** убран плохой дефолт `issues` (в проекте — `README.md`),
  добавлены placeholder и `.field-hint` «Пусто → chain не соберётся».
- **10.58:** `datalist` для `#chain-path` (история в `localStorage`,
  ключ `ai-coder:chain-paths`, лимит 10) — по аналогии с `#path`.
- **10.59:** CLI-баг `--chain требует goal` закрыт (`if not goal and
  chain is None`). Тест `test_chain_without_goal_ok`.
- **10.60:** mypy — 9 ошибок в `gui/app.py` + `history.py` закрыты.
  `[tool.mypy] ignore_missing_imports = true`, `cast(float, ...)`
  в sort, `parts` без redefinition.
- **10.61:** coverage — **omit gui/ убран** (10.63): TOTAL 74%, gui/app.py 80% (CI падал
  с 69% < 70% после добавления ~80 строк в `gui/app.py`).
- `help.html`: 2 chain-примера.
- Демо-README: `issues/demos/*` → `commands/demos/*` (chain
  глотал README как задачу).
- **Ограничение:** `--plan` в chain через GUI не заработает
  (subprocess без PTY).

**A.18:** GUI — чекбокс `--decompose-reverse-check` (2026-10-16, 10.72).
- `app.py`: параметр `decompose_reverse_check: bool = False` в
  `_build_command`/`_build_argv`/`build`/`run`.
- `index.html`: чекбокс `<input name="decompose_reverse_check">` рядом
  с `reverse_check`.
- `applyModeConstraints`: видно только при `mode=decompose`.
- **Связано:** CLI-флаг `--decompose-reverse-check` (10.71, Validator).
- Сделано агентом (v4-pro, 6.63 RUB) + ручная доводка.

**Не умеет (A.14+):** встроенный терминал (PTY + WebSocket),
пагинация `/reports`, экспорт статистики. См.
`next-chat/in-progress.md`.

### Agent

**Subagents (spawn_subagent) — 10.75/10.76, D4/D6, Направление 12:**
инструмент `spawn_subagent`, секция `agent.subagents` в конфиге,
перехват в tool loop + модуль `spawn.py`. Ограничения — в конце раздела.

- `SubagentConfig` (Pydantic, frozen) + `AgentConfig.subagents=[]` и
  3 cap-поля (`subagent_max_per_task=3`,
  `subagent_max_total_cost_rub=3.0`,
  `subagent_default_max_cost_rub=1.5`) в `config.py`.
- Валидация **на старте**: regex имени, уникальность, `tools ⊆
  TOOL_REGISTRY`, `spawn_subagent ∉ tools` (depth=1), `model ∈ pricing`.
- `spawn_subagent` в `TOOL_REGISTRY` — **только** `ToolSpec` + заглушка;
  реальное исполнение — перехват в `_tool_loop_one_iteration` перед
  `execute_tool` (у tool-функции нет `cfg`/бюджета, и был бы цикл
  импортов).
- `ai_coder/agent/spawn.py` (новый): `build_subagents_section`,
  `_remaining_budget`, `_spawn_cap`, `summarize_subagent_result`,
  `run_spawn_subagent`.
- `run_tool_loop`: `allowed_tools`, `spawn_depth`, `max_spawns`,
  `subagents_section`, `usage_action_prefix`.
- **Allowlist enforce на исполнении**; нет subagents или `spawn_depth>0`
  → `spawn_subagent` не рекламируется.
- Бюджет **fail-closed**, провал ребёнка **fail-open**; digest вместо
  истории ребёнка; журнал ребёнка внутри родительского.
- `usage.jsonl`: `action="agent:spawn:<name>:toolN"`,
  `parent_action="agent:spawn:<name>"`.
- `{{subagents_section}}` + правило 19 в `agent_tool_json`; заодно
  исправлена нумерация правил (1..19 без дублей).
- Тесты: `tests/test_spawn.py` (51). **576 passed** (всего).
- Реализовано **dsh** (D4). E2E: `/tmp/spawn-e2e`, **0.1139 RUB**.
- **Коммиты:** `d679409` (A: конфиг), `00c6700` (B: ToolSpec +
  allowlist), `1546ad0` (C: исполнение), `9d5d840` (D: usage + docs).

**3 роли в `config/config.yaml` (10.76):** `code-explorer` (read-only,
flash, 5 ит, cap 1.0), `test-runner` (`run_shell`, flash, 3 ит, cap 0.5),
`markdown-writer` (`read_file`+`write_file`, v4-pro, 8 ит, cap 2.0).
Коммит `1775bc1`. E2E D5: 2 из 3 ролей упали (max_iterations /
max_cost), родитель сделал работу сам.

**Verify: `self_verify_commands` (10.76, finding #1):** `verify_commands`
выполняются в **проекте-цели**, поэтому `python -m mypy ai_coder`
нельзя хардкодить — в чужом проекте упадёт. Новое:
`agent.self_verify_commands` применяются **только** когда проект-цель —
сам ai-coder (`apply.is_self_hosted`). Приоритет:
`--no-verify` → `--verify-commands` → `config + self`; явный `[]`
(read-only subagent) остаётся `[]`. Врезка одна — `cli.py::agent_cmd`.
Коммит `1b2ee2f`.

**Reverse-check по умолчанию (10.77, finding #2):** `--reverse-check`
включён по умолчанию в tool loop. Реализация — **tri-state**
(`bool | None`): `None` → вкл в tool loop и выкл вне него;
`--no-reverse-check` → явный отказ; явный `--reverse-check` без
`--tool-loop` — по-прежнему ошибка. Библиотечный
`run_tool_loop(reverse_check=False)` не менялся (CLI передаёт явно),
поэтому `decompose`/`spawn` не затронуты.
Стоимость: **+1 LLM-запрос**, только при непустом diff.
⚠️ RC ловит несоответствие diff и goal, но **не** ловит фикс, формально
удовлетворяющий размытому goal (эксперимент 0.85 RUB: размытый goal →
`ok=True`; точный goal → `ok=False`). Коммиты `1822df5`, `092760c`.

**Надёжность Router и tool loop (D10.1-D11):**
- **Fallback моделей Router (D10, баг A):** `_resolve_subagent(st, cfg)`
  проверяет `cfg.api.pricing`; если модели там нет — откат на
  `cfg.api.model` с предупреждением (раньше был `KeyError` **в середине
  прогона**, уже после потраченных денег).
- **Лимиты Router применяются (D10, баг B):** `--max-iterations` по
  умолчанию `None`; в `--decompose` действуют лимиты по типу подзадачи
  (`explore` 5 / `edit-simple` 10 / `edit-complex` 15 / `verify` 5),
  в остальных режимах — 20. Явный `--max-iterations N` перекрывает.
- **`verify`-лимит 3 → 5 (D10.1)** и **правило против повторов
  `run_shell` (D10.2):** в промпте появилось правило 19 — если команда
  уже вернула `ok`, повторять её не нужно, надо возвращать `finish`.
  E2E: verify 5× `pytest` без `finish` → 2× `pytest` + `finish`, EXIT=0.
- **`iterations` точный (D11, #4):** равен числу вызовов LLM.
- **Непустой digest subagent'а (D11, #5):** при обрыве до `finish`
  выжимка собирается из причины остановки и последнего шага.
- **`usage --path` (D12, #D2.2):** журнал читается относительно
  целевого проекта, а не CWD (совпадает с тем, куда пишет
  `append_usage`).
- **GUI (D12):** индикатор выполнения (спиннер + «Выполняется… N с») и
  ссылка «Открыть отчёт» после действий `run`.

**Делегирование: правило «когда» (10.76, finding #3):**
`build_subagents_section` получил блок «Делегируй, когда нужно прочитать
много файлов (>3-4)… НЕ делегируй мелочи». Эксперимент
(`scripts/d6_delegation_ab.py`, песочница 30 файлов): большая задача
0/3 → **3/3** (и 1/1 на v4-pro); маленькая — 0/3 в обоих вариантах,
и это **правильно** (решается за 4 шага). Коммит `043aa96`.
⚠️ Выгода делегирования **не** доказана: все прогоны упирались в
`max_iterations`.

**Ограничения (v1):**
- **Depth = 1** — subagent не может вызвать subagent'а (depth 2 не
  реализовано).
- Родительский `rollback` **не** откатывает правки subagent'а: у
  ребёнка свой `backup_dir` (мёрж манифестов не реализован).
- `max_minutes` в tool loop **не** проверяется — subagent'а ограничивает
  только бюджет.
- `step_type="edit"` + explorer-родитель: `read_ops` не удовлетворяет
  edit-критерию `_handle_finish` (см. «Известные проблемы»).
- `iterations` не считает finish-итерацию (`len(ctx.history)`), а
  `usage.jsonl` считает — расхождение на 1.

**Feedback loop (10.74, D3):**
- `_build_feedback(subtask_results, max_items=7)` в `decomposer.py`.
- `feedback_section: str = ""` — параметр в `run_tool_loop`.
- Поле `feedback_section` в `_ToolLoopCtx`, передаётся в `render_prompt`.
- Конфиг: `feedback_enabled=True`, `feedback_max_subtasks=7`.
- `{{feedback_section}}` в `agent_tool_json` (после `ЦЕЛЬ:`).
- Feedback считается один раз на итерацию (до первого `run_tool_loop`).
- Реализовано **dsh** (D3). E2E: prompt-tokens 3067 → 3114 → 3159.
- Обнаружено: планировщик создаёт verify-подзадачи (TODO — 🔴).

**RC в usage (10.73, D2):**
- `run_reverse_check` вызывает `append_usage` (action="agent:reverse_check").
- Реализовано **dsh** (D2). 2 теста (491 passed).

**Validator (10.71, Направление 12):**
- `decompose_reverse_check: bool = False` в `AgentConfig`.
- `_collect_subtask_diff` в `reverse.py` — изолированный diff подзадачи.
- Baseline через `git stash create` — снапшот «до».
- RC после retry, до `max_cost`. Ключи `reverse_ok/problems/suggestion/cost_rub`.
- Колонка RC + секция `## Reverse-check` в отчёте.
- Флаг `--decompose-reverse-check` в CLI.
- Fail-open сохранён. Политики fail/rollback — отложены.
- E2E: `/tmp/validator-e2e4`, 2 подзадачи, обе ✅, RC ✅.
- Основание: D1 (`docs/dsh.md`), E39.

**Router (10.70, Направление 12):**
- `Subtask.type`: `explore` | `edit-simple` | `edit-complex` | `verify`.
- v4-pro планировщик возвращает `type` в JSON (`agent_decompose_json`).
- `parse_decompose_response` — валидация, fallback `"edit"`.
- `_resolve_subagent(st) -> (model, iters)`:
  explore→flash/5, edit-simple→flash/10, edit-complex→v4-pro/15,
  verify→flash/3.
- В `run_agent_decompose`: `model=subtask_model`, `max_iterations=final_iters`.
- **Приоритет:** явный `max_iterations` → Router → `cfg.agent.max_steps`.
- Retry v4-pro при fail — оставлен (страховка).
- Основание: E36, E38.

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
  - журнал: `<project>/<date>/<NN>_tool-loop_<slug>/` + `step-N.md` +
    `report.md` + `goal.txt`; legacy `tool-loop-<ts>/` только читается.
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
      тело функции/класса по имени, без `grep`+`read_file`.
      E2E: **2 итерации вместо 3**, 0.11 RUB вместо 0.13.
      **10.66:** `.py` + C/C++/JS/TS/Go через `ai_coder/symbols.py`.
  - **Ядро (10.67):**
    - `_handle_finish` — упрощено условие warning (убрано
      бессмысленное `action.tool not in (...)` — там всегда
      `finish`). Добавлено `write_attempts > 0`.
  - **Парсер (10.68):**
    - `parse_response` — устойчив к любым обёрткам: убран хрупкий
      `startswith("```")`, всегда `find("{") / rfind("}")`.
      +4 теста (бэктики внутри content, мусор вокруг).
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
    - **`warnings` (10.39):** при `finish(success=True)` и
      `applied_ops < write_attempts` → `warnings.append("applied N/M
      (часть операций отклонена)")`. Печатается в CLI (`⚠️ ...`)
      и в `report.md` (секция `## Предупреждения`).
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

  - **Reverse-check (10.45):**
    - `--reverse-check` — после `finish(success=True)` +
      `stopped_reason="completed"` — вторая LLM-проверка
      diff на соответствие goal. Требует `--tool-loop`.
    - `ReverseCheckResult` (ok / problems / suggestion /
      cost_* / parse_error).
    - `_collect_diff` — `git diff HEAD`.
    - `run_reverse_check` — v4-pro, парсинг JSON.
      Fail-safe: при ошибке парсинга / LLM → `ok=True`.
    - Стоимость суммируется в общий bill.
    - Warnings при `ok=False` + секция `## Reverse-check`
      в `report.md`.
    - **E2E (E20):** простая задача — 2 итерации,
      0.1252 RUB (reverse-check 0.0378 RUB), `ok=True`.
    - **Ограничения MVP:** не работает при `--decompose`;
      промпт — итеративный.
    - **Закрывает:** 6 паттернов «куски ок, связка — нет»
      (A.0/A.2/A.3/A.4/E16).
    - **Не закрывает:** связанные правки (JS↔Python↔HTML) —
      см. `docs/tools.md` → «Когда НЕ использовать tool loop».

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
- **Бюджет — ✅ проверено 2026-10-15 (10.69):**
  - ✅ precheck (10.54) работает.
  - ✅ **10.69:** последняя итерация завершается (verify + finish),
    если остаток > 0. Postcheck и `_handle_finish` — через helper
    `_stop_on_last_iteration`.
  - Остаток: `_MAX_DIFF_CHARS = 15000` хардкод (TODO 8.6) — reverse-check.
  - `step_max_output_tokens: 24000` (10.66, было 8000) — обход TODO 249-252.
  - **8.5 — ✅ ЗАКРЫТО 2026-10-15 (cf5273f):**
    reverse-check работает при `--commit` — diff собирается **до**
    коммита (`diff_before_commit`).
- **Tool loop — известные проблемы (2026-10-08):**
  - ✅ `format_tool_history` обрезал `read_file` — **исправлено (10.8)**.
  - ✅ Нет правила для `'old' not found` — **исправлено (10.8)**.
  - ✅ Backticks в CLI-промпте съедаются bash — **исправлено (10.10)**.
  - `--dry-run` не меняет виртуальный файл → модель перечитывает.
  - Промпт > 15 строк — модель теряет фокус.
  - Агент не справляется с задачами на 5+ файлов.
  - См. подробно `TODO.md`, раздел «Известные проблемы tool loop».
- **Subagents (spawn_subagent, 10.75) — найденное E2E:**
  - **depth 2 не реализовано** — subagent не может вызвать subagent'а
    (осознанное ограничение v1, 3 барьера).
  - **backup merge не реализован** — у ребёнка свой `backup_dir`, поэтому
    родительский `rollback` **не** откатывает правки subagent'а.
  - **`max_minutes` не проверяется в tool loop** — subagent'а
    ограничивает только бюджет (`cap`), не время.
  - **`_handle_finish` + `step_type="edit"` для explorer-родителя:**
    критерий успеха — `applied_ops > 0`, поэтому родитель, который
    только делегировал read-only разведку, завершиться не может
    (`read_ops` не подходит). `_handle_finish` не менялся.
  - **`toolN` начинается с 0** (pre-existing: `start_iteration = 0`) —
    первый запрос `agent:tool0`, а не `tool1`.
  - **`iterations` не считает finish-итерацию:**
    `iterations=len(ctx.history)`, а `_handle_finish` в history **не**
    пишет. Итог: `iterations` = число LLM-вызовов − 1, тогда как
    `usage.jsonl` пишет все вызовы (расхождение на 1).
- **Findings D5 (`docs/findings-d5.md`) — 7 находок E2E:**
  - ✅ **#1 verify не ловит mypy** — закрыто 10.76 (`1b2ee2f`):
    `self_verify_commands` для self-hosted.
  - ✅ **#3 модель не делегирует без подсказки** — закрыто 10.76
    (`043aa96`), с уточнением: на малой задаче это **правильно**.
  - ✅ **#2 Validator в tool loop** — закрыто 10.77 (`1822df5`):
    `--reverse-check` включён по умолчанию (tri-state).
    **Остаточное ограничение:** RC ловит несоответствие diff и goal,
    но **не** ловит фикс, формально удовлетворяющий размытому goal
    (эксперимент D7: размытый goal → `ok=True`, точный → `ok=False`).
    Корень — формулировка задачи, а не тайминг RC.
  - ✅ **#4 `iterations` ≠ LLM-вызовов** — закрыто D11 (`1b2b1e4`):
    отдельный счётчик `ctx.llm_calls`; `iterations` = число вызовов LLM
    (включая `finish`), совпадает с записями в `usage.jsonl`.
  - ✅ **#5 пустой `summary` при `max_iterations`** — закрыто D11
    (`3240890`): `summarize_subagent_result` собирает выжимку из причины
    остановки, последнего шага ребёнка и числа ошибок проверки.
  - ✅ **#6 перерасход `cap`** — закрыто D11 (`8f3a972`): механизм
    («≤ 1 итерации») описан в `docs/tools.md` §6.
  - ✅ **#7 `.venv/bin/ai-coder` из worktree** — закрыто D11 (`cbddd2f`):
    рецепт self-hosted E2E в `docs/tools.md`.
  - ✅ **Все 7 находок D5 закрыты** (D6, D7, D10.1, D11).

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
  - журнал `tool-loop-<ts>/` (исторический legacy; с 10.79 новый —
    `<date>/<NN>_tool-loop_<slug>/`).
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

1. **Направление 12 — subagents — ✅ ЗАКРЫТО (10.70–10.76):**
   Router (10.70), Validator (10.71), Feedback (10.74),
   `spawn_subagent` (10.75), 3 роли + verify+mypy + делегирование
   (10.76). Follow-up 10.75 (depth 2, backup merge, `max_minutes`,
   `_handle_finish` для explorer-родителя, `toolN` с 1,
   `iterations` с finish) — перенесены в findings ниже.
2. **✅ #2 Validator в tool loop** — закрыто 10.77 (`1822df5`):
   RC по умолчанию. Остаток — качество goal (см. «Известные проблемы»).
3. **✅ verify-подзадача в decompose** — закрыто D8 (`9eae807`):
   Root cause был в парсере — `parse_decompose_response` приводил все
   типы Router к `"edit"`, поэтому Router (10.70) не работал, а
   `explore`/`verify` были обречены. Фикс: whitelist типов Router +
   `_step_type_for` (explore/read→read, verify→None, edit-*→edit).
   E2E: EXIT=1 → **EXIT=0**. Осталось — E2E Router без `--model`.
4. **✅ findings #4-#7** — закрыто D11 (`1b2b1e4`, `3240890`,
   `8f3a972`, `cbddd2f`).
5. **✅ E2E Router без `--model`** — закрыто D9: `explore` → flash,
   `edit-complex` → v4-pro, `edit-simple`/`verify` → flash (EXIT=0).
6. **✅ 2 находки dsh (D2)** — закрыто D12: `--by-action` оказался
   опечаткой в доке (разбивка «По действиям» печатается всегда);
   пути `usage.jsonl` → добавлен `--path` (`8e544c1`, `83b5a3c`).
7. **Уровень D.1 (автокоммит для tool loop)** — сделано в 10.1.
   Отложено: ветки `ai-coder/<slug>-<ts>`, push, PR (без веток —
   только коммит в текущую ветку).
8. **GUI UX** — ✅ частично закрыто D12: сделан индикатор выполнения и
   ссылка «Открыть отчёт» для `run`. **Осталось:** `--max-tokens` в
   форме; прогресс по шагам (heartbeat-SSE).
9. **MCP-интеграция**, **унификация `--reverse-check`** (все режимы),
   **`_legacy.py`** — 140 патчей.
10. **Улучшения tool loop:** read-шаги в `run_agent`; кэш phase1;
   YAML-правки (модель слабо справляется).
11. **Покрытие:** `agent.py` — 43%; `apply.py`/`pricing.py`/
    `prompts.py` — до ~90%.

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
| `docs/cli/` | **справочник команд и флагов** (7 команд + алфавитный указатель) |
| `TODO.md` | что осталось (54 пункта, приоритеты) |
| `CHANGELOG.md` | что сделано, по датам и итерациям |
| `docs/state.md` | этот файл, текущее состояние |
| `docs/autonomy.md` | автономность: принципы, план (E8-E9) |
| `docs/dsh.md` | DeepSeek Harness — эксперименты (D1+) |
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
5. Обновить `docs/progress.md` — **дневник сессий**:
   - добавить **секцию** с сегодняшней датой;
   - **главное** (2-5 пунктов, простым языком);
   - **цифры** (тесты, коммиты, experiments);
   - **уроки** и **на следующий раз**.

6. Если **эксперимент с `dsh`** (DeepSeek Harness) — обновить
   `docs/dsh.md` (формат D1, D2, ...). Отдельно от `experiments.md`
   (там — эксперименты **с ai-coder**).

Это 4-5 минут, но экономит часы контекста при возвращении.
