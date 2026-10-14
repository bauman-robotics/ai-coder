# Changelog

Все значимые изменения проекта. Формат: `дата — итерация — краткое описание`.

---

## [2026-10-14] iteration 10.58 — GUI: datalist для `chain_path`

### Что сделано

**UX-улучшение:** поле `#chain-path` (mode=chain) теперь хранит
**историю** введённых каталогов в `localStorage` (ключ
`ai-coder:chain-paths`, лимит 10) и показывает их как **подсказки**
через `<datalist id="chain-path-history">` — по аналогии с `#path`.

**`index.html`:**
- `<input id="chain-path" list="chain-path-history">` +
  `<datalist id="chain-path-history">`;
- JS: `loadChainPaths`, `renderChainPaths`, `rememberChainPath` —
  копия паттерна `path-history` (уникально, лимит 10, в начало);
- `htmx:afterRequest` на `#build-form` — сохраняет `chain_path`;
- `applyParsed` — сохраняет **распарсенный** `chain_path` (из вставки
  команды).

**Зачем:** пользователь **не печатает** каждый раз
`issues/demos/01-chain-sandbox` — браузер **подскажет** из истории.

### Проверки

- `curl /` — 7 упоминаний `chain-path-history`/`rememberChainPath` — ✅
- Браузер: подсказка появляется из localStorage — ✅
- pytest 459 passed — ✅
- ruff — ✅

### Коммиты

- <добавится> feat(gui): datalist для chain_path (10.58)

---

## [2026-10-14] iteration 10.57 — GUI: `--chain` без дефолта + подсказки

### Что сделано

**Баг (10.56):** при `mode=chain` с **пустым** `chain_path` подставлялся
дефолт `issues`. В **этом** проекте `issues/` содержит `README.md`
(индекс), который chain принимает за задачу → **одна** «задача» = README.
**Плохо.**

**Фикс `_build_command`** (`ai_coder/gui/app.py`):
- **убран** дефолт `issues`;
- при пустом `chain_path` команда собирается **без** `--chain`:
  `ai-coder agent <path>` — пользователь видит, что chain **не собрался**.

**`index.html`:**
- `#chain-path`: placeholder `issues/demos/01-chain-sandbox` (пример),
  title с явным «ОБЯЗАТЕЛЬНО для mode=chain», подсказка `<small>`:
  «Каталог с *.md-задачами. Пусто → chain не соберётся.»;
- `style.css`: `.field-hint` (мелкий, полупрозрачный).

**`help.html`:** примеры chain исправлены — `issues/` → `issues/demos/01-chain-sandbox`
(в `<pre>` **и** `data-cmd`), чтобы кнопка «→ в форму» не подставляла
плохой путь.

### Проверки

- `curl /build`: пусто → без chain, с `chain_path` → с chain — ✅
- `/` содержит `field-hint` — ✅
- `/docs/cli/help` содержит 4 вхождения нового примера — ✅
- `ruff` — ✅
- pytest 459 passed — ✅

### Коммиты

- <добавится> fix(gui): --chain без дефолта + подсказки (10.57)

---

## [2026-10-14] iteration 10.56 — GUI: поддержка `--chain`

### Что сделано

**Баг:** `mode=chain` в select на `/` **молча игнорировался**.
`_build_command` знал только `task_type=agent` и `task_type=run`, а
`--chain` требует **значение** (`<dir>`) — это не «просто флаг режима».

**Фикс `_build_command`** (`ai_coder/gui/app.py`):
- новый параметр `chain_path: str = ""` (прокинут в `build`,
  `_build_argv`, `run`);
- **особая ветка** `mode_val == "chain"`: команда собирается
  **как в `run.sh`** — `ai-coder agent <path> --chain <dir> --tool-loop`.
  `path` идёт **на место goal** (hack в `cli.py` — если goal
  директория, а есть `--chain`, CLI сам считает это path);
- дефолт `chain_path` — `issues`, если пусто;
- `--tool-loop` **добавляется автоматически** (chain без tool loop
  бессмыслен, см. `docs/cli/agent.md`).

**Форма `index.html`:**
- новое поле `#chain-path` (`.field agent-only field-hidden`) —
  видно **только** при `mode=chain`;
- `applyModeConstraints()` — toggle видимости;
- `parseCommand()` — распознаёт `--chain <dir>` (забирает
  следующий токен как `chain_path`);
- `applyParsed()` — устанавливает `#chain-path` из парсинга.

**`help.html`:** 2 chain-примера с кнопками «→ в форму».

**Демо-наборы:** `README.md` перенесены из `issues/demos/*` в
`commands/demos/*` — иначе `--chain` **глотал** README как задачу
(6-я «задача» вместо 5).

### Проверки

- `curl /build` (4 кейса): chain + path, chain + дефолт,
  tool-loop (регресс), run (регресс) — ✅
- CLI-смоук: **наша команда запускается**, chain видит 5 задач,
  precheck бюджета сработал (0 RUB), отчёт **пишется** — ✅
- GUI в браузере: поле `#chain-path` появляется при `mode=chain` — ✅
- `ruff check` / `ruff format --check` — ✅
- pytest 459 passed (GUI тестами не покрыт) — ✅

### Ограничение

`--plan` (интерактив `y/n/e`) в GUI **не заработает** —
`subprocess` без PTY, `input()` → `EOFError`. Документировать.

### Коммиты

- <добавится> feat(gui): поддержка `--chain` (10.56)

---

## [2026-10-14] iteration 10.55 — GUI: /docs/cli + объединение с /help

### Что сделано

**Справочник `docs/cli/`** (коммит `9be5a44`):
- `docs/cli/README.md` — индекс + обзор 7 команд.
- `docs/cli/actions-run-fix.md` — команды `actions`, `run`, `fix`.
- `docs/cli/agent.md` — команда `agent` (49 флагов, 6 групп, 4 примера).
- `docs/cli/usage-backups-rollback-index.md` — `usage`, `backups`,
  `rollback` + алфавитный указатель (~60 флагов).

Собрано агентами (v4-pro) **по частям** (5 успешных запусков,
~11.6 RUB + 2 провала 11.6 RUB = **~23 RUB**). Затем — склейка
и чистка вручную:
- `agent.md = _03a + _03b` (убраны дублирующие заголовки);
- убран битый список с якорями из `README.md`.

**Страница `/docs/cli` в GUI** (коммит `eb1d5ef`):
- `app.py`: `DOCS_CLI_DIR`, `_collect_docs_cli`, `_safe_docs_cli_path`
  (защита от traversal), `_render_docs_cli_md` (правка локальных
  ссылок `.md` → `/docs/cli/<page>`), `GET /docs/cli` и
  `GET /docs/cli/{page}`.
- `templates/docs_cli.html` — двухколоночный layout (nav + markdown).
- `static/style.css` — `.docs-cli-layout`, `.docs-cli-nav`, адаптив.
- `index.html` — ссылка «Справочник» в nav.

Проверено: `/docs/cli` → 200 (2838 байт), `/docs/cli/agent` → 200,
`/docs/cli/nonexistent` → 404, ссылки `.md` в контенте → `/docs/cli/<page>`.

**Объединение `/help` с `/docs/cli`** (коммит `0ddef7c`):
- `GET /docs/cli/help` → `help.html` (как есть).
- `GET /help` → 301 редирект на `/docs/cli/help`.
- `help.html`: nav — ссылка «Справочник команд» → `/docs/cli`.
- `docs_cli.html`: nav — «Справка: режимы, примеры» → `/docs/cli/help`.
- `index.html`: ссылка «Справка» убрана (остаётся «Справочник»).
- `docs/cli/README.md`: в «Содержимое» добавлена ссылка на `/docs/cli/help`.

Кнопки «→ в форму» (12 шт., `sessionStorage.pending_command`)
работают как раньше — `help.html` не тронут по логике.

### Тесты

459 passed (без изменений — GUI не покрыт тестами).

### Коммиты

- `9be5a44` docs: справочник docs/cli/ (команды и флаги) + ссылка в README
- `eb1d5ef` feat(gui): страница /docs/cli — справочник команд в вебе
- `0ddef7c` feat(gui): /help → /docs/cli/help (единый вход в справочник)

---

## [2026-10-14] iteration 10.54 — fix: precheck бюджета в tool loop и planner

### Что сделано

**Баг (E25):** `--max-cost-rub N` не срабатывал в `--tool-loop` и
`--chain --plan`.
- Task 1 (E25): 8 итераций, **2.28 RUB** при `--max-cost-rub 1`.
- E25 chain-plan: планирование **1.12 RUB** при лимите `1.0`.
- Третий случай (`--decompose`, 10.44) — **исправлен ранее**.

**Причина:**
- **tool loop:** проверка бюджета была **после** `client.chat` →
  одна итерация могла стоить **больше** остатка.
- **planner:** `run_planner_decompose` **не принимал** `max_cost_rub`
  вообще — планирование тратило сколько угодно.

**Фикс A — `run_tool_loop`:** precheck **перед** `client.chat`.
Новый хелпер `_estimate_next_cost_rub` (грубая оценка по длине
промпта, ХУДШАЯ ставка: peak, cache miss). Если `est >= remaining` —
`stopped_reason = "max_cost"`, `break` **без запроса**.

**Фикс B — `run_planner_decompose`:** параметр `max_cost_rub`. Тот же
precheck → `parse_error="budget: ..."` до запроса.

**Фикс C — `_run_chain`:** накопительный `remaining` для planner
(`--chain --plan`): после каждого плана вычитаем `dec.cost_rub`.

**Фикс D — `cli.py` `--plan` без chain:** `max_cost_rub=decompose_max_cost_rub
or max_cost_rub` передан в planner.

**Унификация:** precheck использует `stopped_reason = "max_cost"`
(как post-check) — семантика та же, различие в `summary` («precheck»).

### Тесты

- `test_run_tool_loop_budget_precheck_no_call` — бюджет крошечный,
  `client.chat.call_count == 0`, `cost_rub == 0.0`, `stopped_reason == "max_cost"`.
- `test_run_planner_decompose_budget_precheck` — то же для planner,
  `parse_error` содержит «budget».

### Тесты

457 → **459** passed (+2).

### Коммиты

- <добавится> fix(budget): precheck в tool loop и planner (10.54)

---

## [2026-10-14] iteration 10.53 — fix: откат при verify_failed в tool loop

### Что сделано

**Баг (из E27):** подзадача 1 задачи 2 упала на `verify_failed`
(`test_agent_bad_path`). `--apply` правку в `cli.py` применил (+12 строк).
Бэкап **был** (`.ai-out/ai-coder/tool-loop-backup-20261014-180635/`),
но `cli.py` **не откатился**. Пришлось `git checkout` вручную.

**Причина:** `run_tool_loop` при `verify_failed` ставил
`success=False`, `stopped_reason="verify_failed"` — и **возвращал
результат**, не откатывая свой `backup_dir`. Откат делала **вызывающая
сторона** (в `run_agent` через `do_rollback(backup0)`), но в путях
`--tool-loop` / `--chain` / `--decompose` этого вызова не было.

**Фикс №1 — `run_tool_loop`** (`ai_coder/agent.py`):
при `verify_failed` — сразу откатывать свой `backup_dir` (через
`apply.rollback`). Печатает «Откат после verify_failed: N файлов».
Закрывает **все** пути: tool loop, `--chain`, `--decompose`, `--with-tests`.

**Фикс №2 — `run_agent_decompose`** (`ai_coder/agent.py`):
перед `rollback_on_fail` — **страховка**: откат **упавшей** подзадачи,
если у неё есть `backup_dir`. Раньше откатывались только успешные
(`prev.get("success")`), а «напакостившая» оставалась.

**Тест:** `test_run_tool_loop_rollback_on_verify_failed` — edit_file,
verify `["false"]`, проверка что файл **восстановлен** (содержимое —
исходное `x = 1`).

### Тесты

456 → **457** passed (+1).

### Коммиты

- <добавится> fix(agent): откат при verify_failed в tool loop (10.53)

---

## [2026-10-14] iteration 10.52 — GUI: кнопка «Скопировать git diff»

### Что сделано

**`POST /diff`** в `ai_coder/gui/app.py`:
- принимает `path` (Form), резолвит в `Path(path).resolve()`;
- `subprocess.run(["git", "diff", "HEAD"], cwd=root, timeout=30)`;
- возвращает `{"diff": "..."}` или `{"diff": "", "error": "..."}`;
- ошибки: не-каталог, `OSError`/`SubprocessError`, `returncode != 0`.

**Кнопка `#copy-diff-btn`** в `templates/index.html`:
- между «Скопировать вывод» и «Запустить» (в блоке `.actions`);
- всегда видна, всегда активна;
- JS: `fetch("/diff", {method: "POST", body: fd})` c `path` из `#path`
  → `navigator.clipboard.writeText` (fallback — `textarea + execCommand`);
- при пустом diff — текст-заглушка
  «[пусто — нет изменений или --commit уже закоммитил]»;
- feedback: кнопка «Скопировано» на 1.2 с.

**Проверено:** `curl -X POST -d "path=." /diff` → непустой diff
(содержит текущие правки `app.py`/`index.html`), `error: None`.

**Сделано вручную** (~20 мин, 0 RUB). Скрипт правки — `/tmp/add_diff_btn.py`.

### Ограничение

`--commit` → diff пустой (агент закоммитил, `git diff HEAD` — пусто).
Это ожидаемо; в JS предусмотрена заглушка.

### Тесты

456 passed (без изменений — GUI не покрыт тестами).

### Коммиты

- <добавится> feat(gui): кнопка «Скопировать git diff» (10.52)

---

## [2026-10-14] iteration 10.51 — демо-наборы (`issues/demos/`, `commands/demos/`)

### Что сделано

**Демо-наборы** — самодостаточные примеры для демонстрации и повторного запуска:

- `issues/demos/01-chain-sandbox/` — 5 задач для `--chain` (цели).
- `issues/demos/02-gui-readonly/` — 5 read-only задач для GUI (на `ai-coder`).
- `issues/demos/03-gui-write/` — 5 write-задач для GUI (песочница `/tmp/gui-test`).
- `commands/demos/01-chain-sandbox/` — `setup.sh`, `run.sh`, 5 команд (`.txt`).
- `commands/demos/03-gui-write/` — `setup.sh`.

**Структура:**
- **цели** — в `issues/demos/`, **команды** — в `commands/demos/` (симметрия).
- **`.gitignore`** — исключения: `issues/*` + `!issues/demos/**`,
  `commands/*` + `!commands/demos/**` (демо — в git, автоистория — локально).

**Демо 1** — `--chain --tool-loop --apply` в песочнице `/tmp/chain-test`:

    bash commands/demos/01-chain-sandbox/run.sh

Проверено в E28: **5/5 ✅**, 0.5665 RUB.

**Демо 2** — read-only задачи на `ai-coder` для GUI (`mode=tool-loop`,
`check_mode=dry-read`). Ничего не меняется.

**Демо 3** — write-задачи в песочнице `/tmp/gui-test` для GUI (`--apply`).
Перед запуском — `bash commands/demos/03-gui-write/setup.sh`.

### Коммиты

- <добавится> feat(demos): демо-наборы (10.51)

---

## [2026-10-14] iteration 10.50 — история команд и целей + E27

### Что сделано

**`ai_coder/history.py`** — новый модуль:

- `next_history_number(directory, day) -> int` — следующий `NN` (`max+1` или `0`).
  Паттерн: `NN_slug.txt` / `NN_slug.md`.
- `make_slug(goal) -> str` — обёртка над `agent._slug_for_issue` (транслит).
- `save_history_entry(project_root, goal, command, *, today=None, write_issue=True)`
  — пишет `commands/YYYY-MM-DD/NN_slug.txt` и (опц.) `issues/YYYY-MM-DD/NN_slug.md`.

**`ai_coder/cli.py`** — вставка в `agent_cmd`:

- после валидации `project_root` (`if not project_root.is_dir()`), **до** `--split-goals`;
- условия: `if goal and "pytest" not in sys.modules` — не пишем в тестах
  (иначе мусор в `commands/`/`issues/` от `CliRunner`);
- `write_issue=not split_goals` — при `--split-goals` пишем только команду
  (issues создаёт сам split-goals, другая схема имён);
- `_cmd_str` — из `sys.argv`, **без дубля** `agent` (в отличие от версии агента);
- try/except — история не ломает агента.

**`tests/test_history.py`** — 21 тест: `next_history_number` (7),
`make_slug` (6), `save_history_entry` (8, включая `write_issue=False`).

**Исправлено в процессе:**

- NN-сдвиг: агент сделал `01_, 03_` (двойной `+1`), спецификация — `00_, 01_`.
  Убрали `+1` в `save_history_entry`. Тесты поправили.
- `write_issue: bool = True` — добавлен после E27 (мусор от `--split-goals`).
- Защита `"pytest" not in sys.modules` — после E27 (мусор от тестов).

### Как сделано — E27 (`--chain --plan`)

Фича разбита на 2 issue (`issues/2026-10-14/history/`):

1. `01-history-module.md` — `history.py` + тесты. **✅** через v4-pro (flash
   провалился на `create_file`, `max_iterations`). **3.6074 RUB.**
2. `02-cli-insert.md` — вставка в `cli.py`. **❌** — `verify_failed`
   (`test_agent_bad_path`), v4-pro retry не помог. **1.4378 RUB.**
   Причина: наш issue не учёл валидацию `path` — `save_history_entry`
   создавал каталог **до** неё.

**Итого:** 5.0453 RUB, 1/2 задачи. Вставку сделали **вручную** — с исправлениями.

### Находки E27

- 🔴 **Баг: откат не работает в `--chain --decompose`.** Правка `cli.py`
  осталась после `verify_failed` — пришлось `git checkout`. Бэкап был.
  См. `TODO.md`.
- **`create_file` — граница flash** (новый датапоинт, после E26).
- **Тесты агента зелёные ≠ спецификация** — агент подстраивает тесты
  под свой код (`NN`-сдвиг).
- **Мусор от pytest** — сломанная вставка писала в корень проекта.

### Тесты

435 → **456** passed (+21).

### Коммиты

- <добавится> feat(agent): история команд и целей (10.50)
- <добавится> docs: E27 + TODO (баг отката)

---

## [2026-10-14] iteration 10.49 — GUI: загрузка команды из файла + commands/

### Что сделано

**`#command-file` — загрузка команды из файла:**

Рядом с textarea `#paste-command` (блок «Вставить команду») добавлен
`<input type="file" id="command-file" accept=".txt,.sh,.md">`.
При выборе файла — `FileReader.readAsText` → `#paste-command.value`
→ `applyParsed(parseCommand(...))`.

**Симметрия:**
- `#goal-file` — загрузка goal из файла;
- `#command-file` — загрузка команды из файла.

**Сделано вручную** (~15 мин, 0 RUB). См. `docs/ui-ideas.md` → A.12.

### Каталог `commands/` — сохранённые команды

Симметрично `issues/`:

    commands/
    ├── README.md
    └── YYYY-MM-DD/
        └── N-<slug>.txt

Файлы — чистые команды (одна строка). Загрузка через `#command-file`.

В `.gitignore` (как `issues/`) — локальные, не в публичном репо.

### Коммиты

- `5de2b69` chore: .gitignore — commands/
- <добавится> feat(gui): загрузка команды из файла (#command-file)

### Тесты

435 passed.

---

## [2026-10-14] iteration 10.48 — revert: убрать поле --issue из GUI

### Что сделано

**Причина:** поле `#issue` **дублировало** кнопку «Из файла»
(`#goal-file`). Оба:
- выбирают файл с задачей;
- дают **одинаковый результат**.

**Разница** — только в форме команды:
- `#goal-file` → текст в goal → **длинная команда** (`"<25 строк>"`);
- `#issue` → путь в `--issue` → **короткая команда**.

**Решение:** оставить **один** способ — `#goal-file`.

### Изменения

**`ai_coder/gui/templates/index.html`:**
- удалён `<div class="field agent-only">` с `<input id="issue">`;
- из `parseCommand` убраны `result.issue` и обработка `--issue`;
- из `applyParsed` убран `issueEl`.

**`ai_coder/gui/app.py`:**
- `issue` удалён из `_build_command` / `_build_argv` / `build` / `run`;
- **`reverse_check` в `_build_argv` оставлен** (баг-фикс из 10.47).

### Что осталось

- `#goal-file` — «Из файла» (загрузка goal).
- `#paste-command` — «Вставить команду» (вставка в textarea).
- `reverse_check` — флаг.

### Тесты

435 passed. Smoke-тесты GUI: `/build` без `--issue`, с `--reverse-check`.

### Коммит

`ebd1a6e` revert(gui): убрать поле --issue из формы (дубль с 'Из файла')

---

## [2026-10-14] iteration 10.47 — GUI A.12 (paste / goal-file / --issue) + E25

### Что сделано

**A.12 — расширения формы GUI:**

- **«Вставить команду»** — `<details>` с textarea + кнопка
  «Заполнить форму» → `parseCommand` → новая функция
  `applyParsed(parsed)` (вынесена из `pending_command`).
- **Загрузка goal из файла** — `<input type="file" id="goal-file">`
  + FileReader → `#goal.value`.
- **Поле `--issue <path>`** — `#issue` в форме + распознавание
  `--issue` в `parseCommand` + `applyParsed` устанавливает `#issue`.
- **`app.py`:** `issue` в `_build_command`/`_build_argv`/`build`/`run`.
- **Fix:** `_build_argv` не передавал `reverse_check` в
  `_build_command` (reverse-check молча терялся при запуске из GUI).

**Как сделано:**

- Task 1 (`paste-command` + `applyParsed`) — **агентом**:
  8 итераций, 2.2767 RUB, reverse-check ✅.
- Task 2 (`goal-file`) — **агентом**: 2 итерации, 0.8067 RUB,
  reverse-check ✅.
- Task 3 (`issue` в `app.py` + HTML) — **вручную** (~15 мин, 0 RUB).
- **См.** `docs/experiments.md` → E25.

### Наблюдения (E25)

- Warning E8 (goal > 10 строк) — **консервативный**: 11-15 строк
  дали отличный результат при точной формулировке.
- **Тип задачи важнее размера:** «вставка» = 2 ит/0.81 RUB,
  «рефакторинг + вставка» = 8 ит/2.28 RUB (×2.8).
- **Баг бюджета:** `--max-cost-rub 1` **не остановил** на 2.28 RUB.
  Второй случай (первый: `--chain --plan` — 1.12 RUB при лимите 1.0;
  третий: 10.44 — `--decompose`, исправлено). См. TODO.

### Тесты

431 passed. Smoke-тесты GUI: 5/5.

### Коммит

`91ecf82` feat(gui): A.12 — расширения формы (paste / goal-file / --issue)

---

## [2026-10-14] iteration 10.46 — fix: pytest exit 5 (no tests) — не ошибка

### Что сделано

**`ai_coder/apply.py` — `run_verify_commands`:**
- Если команда = `pytest` (или `python -m pytest`,
  или `/venv/bin/pytest`) и `returncode == 5` — **пропускаем**
  (не ошибка).
- Покрывает: `pytest`, `python -m pytest`, `python3 -m pytest`,
  `/usr/bin/pytest`, `/venv/bin/pytest`.

**Почему:** `pytest` в проекте без тестов возвращает `exit 5`
(«no tests collected»). **Это не ошибка** — просто нечего
проверять. Но verify считал провалом → agent tool loop
зря получал `verify_failed` → `success=False`.

**Найдено в E20/E22:** в E22-Тест-2 (5 docstrings) verify упал
с `exit code: 5`, хотя правки были корректны.

**`tests/test_apply.py`:** +4 теста:
- `test_run_verify_commands_pytest_exit5_ok`;
- `test_run_verify_commands_python_m_pytest_exit5_ok`;
- `test_run_verify_commands_pytest_exit1_fail`;
- `test_run_verify_commands_other_exit5_fail`.

**Тесты:** 427 → **431**.

### Как сделано

**Вручную** (5-10 минут).

---

## [2026-10-14] iteration 10.45 — reverse-check (Уровень 2.5)

### Что сделано

**Флаг `--reverse-check`** (требует `--tool-loop`): после
`finish(success=True)` + `stopped_reason="completed"` —
вторая LLM-проверка diff на соответствие goal.

**`ai_coder/agent.py`:**
- `ReverseCheckResult` — dataclass (`ok`, `problems`,
  `suggestion`, `cost_*`, `raw_response`, `parse_error`).
- `_collect_diff(project_root)` — git diff HEAD.
- `run_reverse_check(goal, diff, project_root, cfg, prompts_cfg)` —
  LLM-запрос, парсинг JSON, fail-safe (ok=True при ошибке).
- `run_tool_loop(..., reverse_check=False)` — параметр, вызов после
  success, суммирование стоимости, warnings при `ok=False`.
- `ToolLoopResult.reverse_check_result` — новое поле.
- `_save_tool_loop_report` — секция `## Reverse-check`.

**`ai_coder/config.py` (`AgentConfig`):**
- `reverse_check_model: str | None = None`.
- `reverse_check_max_diff_chars: int = 15000`.

**`ai_coder/cli.py`:**
- Флаг `--reverse-check`.
- Валидация (`--tool-loop` обязателен).
- Передача в `run_tool_loop`.

**`config/prompts.yaml`:**
- Промпт `agent_reverse_check`.

**`tests/test_agent.py` + `tests/conftest.py`:**
- +8 тестов (parse ok / parse problems / bad json / markdown
  wrapper / truncate / llm error / collect_diff non-git /
  dataclass).
- Фикстура `prompts_cfg` дополнена `agent_reverse_check`.

**Тесты:** 419 → **427**.

### E2E

См. `docs/experiments.md` → E20.

- Простая задача (fix add): 2 итерации, 0.1252 RUB (RC 0.0378).
- Reverse-check: `ok=True`.

### Ограничения MVP

- Не работает при `--decompose`.
- Промпт — итеративный, калибровка на будущее.

### Как сделано

**Вручную** (связанные правки: agent.py + config.py + cli.py +
prompts.yaml + tests + conftest). ~3 ч.

---

## [2026-10-14] iteration 10.44 — fix бюджета --decompose + GUI A.11 (run-команды)

### Fix: `--max-cost-rub` игнорировался при `--decompose`

**Найдено в E19** (прогон A.11 через --decompose, перерасход ×8.4:
16.87 RUB при лимите 2.0).

**`ai_coder/cli.py`:**
- Стр. ~992 (`_run_chain`): `max_cost_rub=decompose_max_cost_rub or max_cost_rub`.
- Стр. ~1674 (`agent_cmd`): то же.
- Help для `--decompose-max-cost-rub`: «Если не задан — наследует --max-cost-rub.»

**Причина:** `--decompose` использовал только `--decompose-max-cost-rub`
(отдельный флаг, по умолчанию None). Если не задан —
`run_agent_decompose` получал `max_cost_rub=None` и не проверял бюджет
(стр. 774, 872: `if max_cost_rub is not None`). `--max-cost-rub`
действовал только на простой tool-loop.

### A.11: run-команды в GUI

**`ai_coder/gui/app.py`:**
- `_build_command`: параметры `task_type="agent"`, `run_action=""`,
  ветка `if task_type == "run"`. Для run: `ai-coder run <action> <path>`
  + `--model`/`--apply`/`--dry-run`/`advanced_flags`.
  **Без** `--max-cost-rub`/`--commit` (их нет у CLI `run`).
- `build`, `run`, `_build_argv`: параметры `task_type`, `run_action`.

**`ai_coder/gui/templates/index.html`:**
- Select «Тип задачи» (`task_type`: agent/run).
- Select «Действие» (`run_action`: 7 действий), скрыт по умолчанию.
- Обёртки `.agent-only` (goal, mode, flags) скрываются при run.
- JS `applyTaskType()` — toggle + listener.
- `parseCommand`: ветка `else if (result.action === "run")`.
- Pending: установка `task_type`/`run_action` из `pending_command`.

**`ai_coder/gui/templates/help.html`:**
- Секция `#run-examples` — 5 примеров run-команд + кнопки «→ в форму».

**`ai_coder/gui/static/style.css`:**
- `.field-hidden { display: none !important; }`.

### E19

См. `docs/experiments.md` → E19 (4 файла, связанные, --decompose,
1/4 подзадач, 16.87 RUB + баг бюджета).

### Как сделано

- **app.py (подзадача 1):** агент `--tool-loop --decompose` — ✅
  (33 строки, правильно с первого раза).
- **index.html, help.html, style.css:** вручную (~1.5 ч, 0 RUB).
- **Fix бюджета:** вручную (3 строки + help).

---

## [2026-10-13] iteration 10.42 — GUI A.8 (статистика расходов, Chart.js)

### Что сделано

**`ai_coder/gui/app.py`:**
- `USAGE_JSONL` — путь к `.ai-out/usage.jsonl`.
- `_collect_stats()` — агрегаты из `usage.jsonl`:
  - `summary`: total_rub, total_requests, total_tokens, days;
  - `by_day`: `[{date, cost_rub, requests}]` (хронологически);
  - `by_model`: `[{model, cost_rub, requests}]` (по убыванию);
  - `by_action`: `[{action, cost_rub, requests}]` — `action.split(":")[0]`.
- `GET /stats/data` — JSON для Chart.js.
- `GET /stats` — HTML со графиками.
- Устойчивость: битые JSON-строки — пропускаются; нет файла — пустые данные.

**`templates/stats.html`** (новый):
- 4 summary-карточки: RUB / запросов / токенов / дней.
- 3 графика (Chart.js 4.4): line (по дням) + doughnut (модели)
  + bar (действия).
- Тёмная тема, `Intl.NumberFormat('ru-RU')`.

**`static/style.css`:**
- `.stats-summary` (grid 4 карточки, auto-fit min 150px).
- `.stat-card`, `.stat-label`, `.stat-value`.
- `.chart-wrap` (height 320px, relative).
- `.panel-row` (grid 1fr 1fr, media query 900px).

**`templates/index.html`:**
- Ссылка «Статистика» в `<nav class="report-nav">`.

### Живой прогон

- `/stats/data` → `{summary: {total_rub: 106.24, total_requests: 525,
  total_tokens: 4826409, days: 7}, ...}`.
- `/stats` → HTTP 200.
- 7 дней: 06.10–13.10. Пики: 07.10 (28.02 RUB / 21 запрос) и
  09.10 (27.32 RUB / 162 запроса).

### Как сделано

**Вручную** (связанные правки Python+Jinja+JS+CSS, `--tool-loop`
не использовался). ~1.5 ч.

### Ссылки

- `docs/state.md` → раздел GUI (A.0–A.8).
- `docs/ui-ideas.md` → секция 1.5 (A.0–A.8).

---

## [2026-10-13] iteration 10.40 — GUI A.7 (/reports — список журналов)

### Что сделано

**`ai_coder/gui/app.py`:**
- `GET /reports` — список всех журналов из `.ai-out/*/*/report.md`,
  отсортированных по mtime desc.
- `_collect_journals()` — обход с защитой от symlink-выхода за `AI_OUT_DIR`.
- `_parse_report_meta()` — грубый парсер `- **Ключ:** значение`
  (Успех / Стоимость / Итераций / Причина остановки).
- `_is_journal_dir()` + `JOURNAL_PREFIXES` — whitelist префиксов
  (`tool-loop-`, `agent-`, `decompose-`, `chain-plan-`, `chain-`,
  `autofix-`, `plan-`). Backup/cache отсекаются автоматически
  отсутствием `report.md`.
- Импорты: `re`, `datetime`.

**`templates/reports.html`** (новый):
- Таблица: Дата / Проект / Журнал / Успех / Итераций / Стоимость /
  Причина / ссылка. 8 колонок.
- CSS-классы `ok` / `fail` / `num` / `nowrap`.

**`templates/index.html`:**
- В `<header>` добавлен `<nav class="report-nav">` со ссылкой
  «Все отчёты» → `/reports`.

**`static/style.css`:**
- Стили `.reports-table` (тёмная тема): `th`/`td`, hover,
  `.num` (tabular-nums), `.ok` (#4caf50), `.fail` (#e57373).

### Проверка (живой прогон)

- `/reports` → **83 журнала** (67 tool-loop + 11 agent + 3 decompose
  + 2 autofix), совпадает с `find .ai-out -maxdepth 2 -name report.md | wc -l`.
- `/reports/ai-coder/tool-loop-2026-10-13T18-32-29` → HTTP 200.
- `/` → header с «Все отчёты».
- Логи uvicorn — 200 OK на всех запросах.

### Как сделано

**Вручную** (связанные правки Python+Jinja+CSS, `--tool-loop` не использовался).
~40 мин.

### Ссылки

- `docs/state.md` → раздел GUI (A.0–A.7).
- `docs/ui-ideas.md` → секция 1.5 (A.0–A.7).

---

## [2026-10-13] iteration 10.39 — 3 TODO из GUI-сессии (промпт, partial, warnings)

Закрытие трёх пунктов из TODO, обнаруженных при создании GUI.

### TODO 1 + 3 — правила в промпте

**`config/prompts.yaml` → `agent_tool_json`:**
- **Правило 9** (ЗАВИСИМОСТИ): если используешь `Form(...)`/`File(...)`
  в FastAPI — добавь `python-multipart`; `jinja2`/`aiofiles`/`websockets`
  — тоже должны быть в зависимостях.
- **Правило 10** (ВЕРСИИ API): перед использованием API библиотеки —
  посмотри версию в `pyproject.toml`. API мог измениться (пример:
  FastAPI `<0.108` vs `>=0.108` — у `TemplateResponse` другой порядок
  аргументов).
- Правило **9. ПРИМЕРЫ** → **11. ПРИМЕРЫ** (нумерация сдвинута).

### TODO 2 — partial (warnings)

**`ai_coder/agent.py`:**
- `ToolLoopResult.warnings: list[str]` — новое поле.
- `run_tool_loop`: при `finish(success=True)` и `applied_ops <
  write_attempts` → `warnings.append("applied N/M (часть операций
  отклонена)")`.
- `_save_tool_loop_report`: секция `## Предупреждения` в `report.md`.

**`ai_coder/cli.py`:**
- После панели «Tool Loop — итог» — печать `⚠️ <warning>` для каждого.

**`tests/test_agent.py`:**
- `test_run_tool_loop_partial_warns` — 1 ok + 1 blacklist → success=True,
  applied_ops=1, warnings=["applied 1/2 ..."].
- `test_run_tool_loop_no_partial_when_all_applied` — 2 ok → warnings=[].

**Тесты:** 417 → **419**.

### Как сделано

**Вручную** (правка промпта — chicken-and-egg, partial — сложная логика).

---

## [2026-10-13] iteration 10.38 — GUI A.5 + A.6 (ссылка на отчёт + рендер)

Две фичи для отчётов в веб-панели.

### A.5 — ссылка на отчёт после `/run`

**`app.py`:**
- `mount("/ai-out", StaticFiles(...))` — статический доступ к `.ai-out`
  (для `report.md`, `plan.json`, `step-N.md`).

**`index.html`:**
- `div#report-link` — контейнер под `run-output`.
- JS в обработчике `data:`: ловит `Журнал: <path>` → формирует
  URL → «Открыть отчёт» (открывается в новой вкладке).
- Очистка `#report-link` при новом запуске.

### A.6 — рендер `report.md` в HTML

**`app.py`:**
- `GET /reports/{project}/{journal}` — читает `.ai-out/<project>/<journal>/report.md`,
  `markdown.markdown(extensions=["fenced_code", "tables", "sane_lists"])`,
  рендерит через `report.html`.
- `_safe_report_path` — защита от path traversal: `(AI_OUT_DIR / project /
  journal).resolve()` + `relative_to(AI_OUT_DIR.resolve())`.

**`templates/report.html`:**
- Шаблон с `header` (project / journal, nav) и `<main class="markdown-body">`.
- Nav: «← к панели», «raw .md».

**`style.css`:**
- Стили markdown: `.markdown-body h1/h2/h3`, `code`, `pre`, `table`,
  `th`, `td`, `blockquote`, `a`.

**`index.html`:**
- Ссылка «Открыть отчёт» → `/reports/<project>/<journal>`
  (вместо `/ai-out/.../report.md`).

**`pyproject.toml`:**
- `markdown>=3.5` в `[gui]`.

### Как сделано

**Оба — вручную** (связанные правки JS/Python, `--tool-loop` не использовался).
**A.5:** ~15 мин. **A.6:** ~30 мин.

### Ссылки

- `docs/state.md` → раздел GUI (A.0–A.6).
- `docs/ui-ideas.md` → секция 1.5 (A.0–A.6).

---

## [2026-10-13] iteration 10.37 — GUI A.3 + A.4 (форма: select-ы, fix)

Доработка формы GUI. Три улучшения + два фикса.

### A.3 — select-ы и кнопка

**`index.html`:**
- `max-cost-rub`: `input type=number` → `select` (8 значений:
  без ограничения, 0.1, 0.2, 0.5, 1, 2, 5, 10 RUB).
- `copy-output-btn`: копирует `pre#run-output` в clipboard
  (`navigator.clipboard.writeText` + fallback `execCommand`).
  Кнопка в `.actions` после `copy-btn`.

### A.4 — check_mode select

**`index.html`:**
- `checkbox dry_run` → `select name=check_mode`:
  `normal` / `dry-run` / `dry-read`.

**`app.py`:**
- `_build_command`/`_build_argv`/`build`/`run`:
  `dry_run: bool` → `check_mode: str`.
- Логика: `"dry-run"` → `--dry-run`; `"dry-read"` → `--dry-read`;
  `"normal"` → ничего.
- JS `buildParams()`: `dry_run=false` → `check_mode=normal`.

### Фиксы (после агента)

- **`model` select:** value `flash` → `deepseek-flash` (API требует полное
  имя; было `BadRequestError 400`).
- **`path` в `_build_command`:** всегда добавлять `.` (было: пропуск,
  и `--tool-loop` оказывался на месте позиционного `path`).

### Как сделано

**A.3:** агент (`--tool-loop`, 4 итерации, 0.28 RUB) — ✅.
**A.4:** агент (`--tool-loop`, 10 итераций, **0.81 RUB**, `max_cost`) —
сделал **~40%** (`index.html` + `build()` Form). `_build_command`,
`_build_argv`, `/run`, JS — **доделано вручную** (~20 мин).

### E17

См. `docs/experiments.md` → E17.

### Побочно — `--dry-read` работает

Живой тест «Найди все TODO в `ai_coder/tools.py`»:
- `--dry-read`: `run_shell ✅` (grep **реально выполнен**, не найдено) → finish.
- `--dry-run`: `run_shell ✅` (simulated) → **зацикливается**.

---

## [2026-10-13] iteration 10.36 — --dry-read (read-выполняется, write-блокируется)

Новый флаг `--dry-read` для `ai-coder agent --tool-loop`.

### Что сделано

**`ai_coder/tools.py`:**
- `READ_ONLY_COMMANDS` (`ls, cat, grep, find, head, tail, wc`).
- `READ_ONLY_GIT_SUBCOMMANDS` (`status, diff, log, show, branch,
  rev-parse, ls-files`).
- `_is_read_only_command(cmd)` — `shlex.split`, `try/except`,
  для git — проверка `len >= 2`.
- `execute_tool(..., dry_read: bool = False)`:
  проверка **ПЕРЕД** `if dry_run and spec.dangerous` — read-only
  `run_shell` → реальный запуск; `write_file`/`edit_file` —
  как `dry_run`.

**`ai_coder/agent.py`:**
- `run_tool_loop(dry_read: bool = False)`.
- `run_agent_decompose(dry_read: bool = False)`.
- Проброс в оба `run_tool_loop` (основной + retry).

**`ai_coder/cli.py`:**
- `--dry-read` (несовместим с `--dry-run`, валидация).
- Проброс в `_run_chain`, `run_agent_decompose`, оба `run_tool_loop`.

**`tests/test_tools.py`:** +8 тестов.

### E16 — доказательство

Прямое сравнение (задача «Найди READ_ONLY_COMMANDS»):

| Флаг | Итерации | RUB | Результат |
|---|---|---|---|
| `--dry-read` | **1** | **0.075** | ✅ |
| `--dry-run` | 8 | 0.41 | ❌ max_iterations |

`--dry-run` зацикливается на `(dry-run) RAN ... (simulated OK)`.
`--dry-read` — **×8 быстрее, ×5.5 дешевле**.

### Как сделано

- Агент (`--tool-loop`, **21 итерация, 2.08 RUB**, `--max-cost-rub`):
  `tools.py` + `agent.py` — **готовы** (42 строки).
- **Не успел** `cli.py` + тесты — флейки на старте (10 из 21:
  `parse_error`, `missing_args` × 3, `run_shell rejected`).
- **Вручную:** `cli.py` (флаг + валидация + проброс), 8 тестов.

См. `docs/experiments.md` → E16.

---

## [2026-10-13] iteration 10.35 — GUI A.2 (запуск + стриминг)

Запуск команды из веб-панели со стримингом вывода в браузер.

### Что сделано

**`app.py`:**
- `POST /run` — `subprocess.Popen([sys.executable, "-m", "ai_coder.cli", ...],
  stdout=PIPE, stderr=STDOUT, text=True, bufsize=1)`,
  `StreamingResponse(media_type="text/event-stream")`, формат `data: <строка>\n\n`.
- `POST /stop/{run_id}` — SIGTERM.
- `RUNNING: dict[str, Popen]` — реестр.
- `_build_argv` — `shlex.split(_build_command(...))` + замена префикса.
- `_stream_process` — построчно + cleanup в `finally`.

**`index.html`:**
- Кнопки «Запустить»/«Остановить».
- `fetch("/run", {method: "POST", body: FormData})` + `ReadableStream`.
- Парсинг `data: ` вручную, `run_id` из первого события.
- `AbortController` для прерывания стрима.

**`style.css`:**
- Стили `#run-output`.

### Фикс после агента

Агент написал `@app.post("/run")` **и** JS `EventSource("/run?")`.
`EventSource` шлёт **только GET** → `GET /run → 405`. Все куски
правильные, связка — нет.

**Фикс:** JS → `fetch + ReadableStream` (POST).

### E15

См. `docs/experiments.md` → E15.

- A.2: **8 итераций, 1.26 RUB, 1 фикс**.
- Гипотеза «агент не справится с SSE» — **опровергнута**.
- Явное указание API в промпте — решающий фактор.
- Новый баг-паттерн: «куски правильные, связка — нет» → reverse-check.

### Побочно — `--dry-run` вредит read-задачам

Прогон «Найди все TODO в проекте» с `--dry-run`: `grep` **симулирован**,
результата нет. Агент **честно** пишет в summary. Нужен `--dry-read`
(read-only shell разрешён). См. TODO.

---

## [2026-10-13] iteration 10.34 — GUI A.0 + A.1 (веб-панель)

Начало направления UI. Веб-панель на FastAPI + Jinja2 + HTMX
(тёмная тема). Первая версия — **сборка команды** (без запуска).

### A.0 — скелет

Агент (`--tool-loop`, 13 итераций, 0.93 RUB) создал:
- `ai_coder/gui/app.py` — FastAPI app, `/`, `/health`, `/static`.
- `ai_coder/gui/templates/index.html` — тёмная тема, HTMX 1.9.12 (CDN).
- `ai_coder/gui/static/style.css` — CSS-переменные dark mode.
- `pyproject.toml` — **правка вручную** (blacklist): добавлена секция
  `[project.optional-dependencies] gui = [...]`.
- `README.md` — секция «GUI».

**Баг агента:** написал `TemplateResponse("index.html", {"request": request})`
(API <0.108). Под FastAPI 0.143 — **HTTP 500** на `GET /`. Исправлено
вручную: `TemplateResponse(request, "index.html", {})`.

### A.1 — форма сборки команд

Агент (`--tool-loop`, 6 итераций, 0.95 RUB) создал:
- `POST /build` — собирает строку `ai-coder agent "..." . --tool-loop ...`,
  возвращает `<pre>`.
- **Форма**: goal (textarea), path (input+datalist localStorage),
  mode (select), model (select), apply/commit/dry-run (чекбоксы),
  max-cost-rub (number), advanced-flags (details+textarea).
- Кнопки «Собрать команду» (HTMX POST /build) и «Скопировать»
  (navigator.clipboard).
- `style.css` — стили формы.

**Фиксы после агента:**
- **`mode` без `--`:** команда была `... . tool-loop --apply`,
  стало `... . --tool-loop --apply`.
- **`python-multipart`:** не был в `pyproject.toml`. `Form(...)` в FastAPI
  требует его явно — `app.py` падал с `RuntimeError` при импорте,
  `uvicorn` зависал. Добавлено в `gui` extras.

### Запуск

    pip install -e ".[gui]"
    uvicorn ai_coder.gui.app:app --reload --port 8000
    # http://127.0.0.1:8000/

### TODO (из этой сессии)

- Агент пишет под устаревший API библиотек — нужен smoke-тест в verify.
- `success=False` при частичном применении (5 из 6 файлов) — статус `partial`.
- `python-multipart` не в зависимостях — правило в промпте.

### Связь с `docs/ui-ideas.md`

`docs/ui-ideas.md` предлагал wizard на `typer.prompt` (4 ч). Выбран
**другой путь** — веб-панель (FastAPI + HTMX). Причины:
- Встроенный терминал (этап B) требует WebSocket — в FastAPI из коробки.
- Pydantic v2 уже в проекте — валидация формы без новых зависимостей.
- Открывается в браузере — не мешает терминалу.

План: **A** (сборка команды, ✅) → **B** (запуск + терминал, PTY+WebSocket)
→ **C** (история + статистика из `usage.jsonl`).

---

## [2026-10-13] iteration 10.33 — read-шаги в простом агенте (run_agent)

Завершение read-направления. В 10.31 введён `step_type="read"`, в 10.32
`parse_agent_plan` принял `type: "read"`, но **простой агент** (`run_agent`)
read-шаги **пропускал** — `apply_plan` не умеет read. Теперь работает.

### Что сделано

- **`StepResult.read_answer: str`** — текстовый ответ read-шага.
- **`_run_read_step`** — новая функция: для read-шага вызывает
  `run_tool_loop(step_type="read")`, собирает `StepResult`:
  - `write_plan=None`, `applied=False`, `applied_count=0`;
  - `read_answer = loop.summary`;
  - **verify не запускается** (read не меняет файлы);
  - `skipped=True`, `skip_reason=stopped_reason`, если loop не успешен.
- **`_run_agent_step`** — ветка `if step.type == "read": return _run_read_step(...)`.
  Новый параметр `journal_subdir` — чтобы read-журнал шёл в `agent-<ts>/`.
- **`run_agent`**:
  - **убран** пропуск read-шагов (10.32);
  - передаётся `journal_subdir=journal_dir`;
  - ответ read-шага **печатается** в консоль (`Panel.fit`).

### Тесты

+4 (409 passed):

- `test_run_read_step_calls_tool_loop` — `step_type="read"` уходит в tool loop.
- `test_run_read_step_success` — успех, `read_answer` заполнен.
- `test_run_read_step_failure` — fail, `skipped=True`, `skip_reason` из loop.
- `test_run_agent_calls_read_step_for_read_type` — `run_agent` для read
  вызывает `_run_read_step` (через `_run_agent_step`).

### Связь с 10.31–10.32

- 10.31: механизм (`step_type`, `read_ops`).
- 10.32: доступ (`parse_agent_plan`, промпт).
- 10.33: **простого агента научили read** — через tool loop.

---

## [2026-10-13] iteration 10.32 — read-шаги в плане агента

Завершение направления «read-задачи». В 10.31 введён `step_type`
(edit/read) для `run_tool_loop`, но **`parse_agent_plan` продолжал
отбрасывать read-шаги** — и промпт запрещал `type: "read"`.

### Что сделано

- **`parse_agent_plan`:** принимает `type: "read"` (было: только `"edit"`).
- **`_is_diagnostic_step`:** переклассифицирует `edit` → `read`, если
  текст шага содержит read-маркеры («прочитай», «проанализируй»,
  «опиши»). **Больше не отбрасывает** шаг.
- **Промпт `agent_plan_json`:** разрешён `type: "read"` для read-only
  задач (объяснить, найти, показать, проанализировать).
- **`run_agent` (простой агент):** read-шаги **пропускаются** с
  предупреждением — `apply_plan` их не умеет. Read работает через
  `--tool-loop` (chain, decompose).

### Что НЕ сделано (TODO)

- **`run_agent` не умеет read** — только отбрасывает. Полная
  поддержка (read через tool loop в простом агенте) — отдельная задача.

### Тесты

+2 (405 passed):

- `test_parse_agent_plan_accepts_read_type` — `type: "read"` принят.
- `test_parse_agent_plan_reclassifies_diagnostic_edit_to_read` — `edit`
  с read-маркерами → `read`.

Переделаны:

- `test_parse_agent_plan_skips_diagnostic_steps` →
  `test_parse_agent_plan_reclassifies_diagnostic_to_read`.
- `test_parse_agent_plan_all_steps_diagnostic_becomes_empty` →
  `test_parse_agent_plan_all_diagnostic_become_read`.

### Связь с 10.31

- 10.31: механизм (`step_type`, `read_ops`, критерий успеха).
- 10.32: доступ (`parse_agent_plan`, промпт, `run_agent`).

---


## [2026-10-13] iteration 10.31 — step_type + read_ops: критерий по типу шага

Механизм для read-задач. Правило 10.27 (`success = applied_ops > 0`)
**философски неверно** для read-задач: агент читает, отвечает, но
«провал» — потому что 0 правок. Введён `step_type`.

### Добавлено

- **`ToolLoopResult.read_ops: int = 0`** — счётчик успешных
  `read_file` / `read_symbol` / `list_files`.
- **`run_tool_loop(step_type: str | None = None)`** — критерий успеха
  по типу шага:
  - `None` — `success = action.success` (обратная совместимость);
  - `"edit"` — `action.success AND applied_ops > 0` (правило 10.27);
  - `"read"` — `action.success AND read_ops > 0` (новое).
- **Resume** — пересчёт `read_ops` из history.
- **`run_agent_decompose`** — `step_type="edit"` в оба `run_tool_loop`.
- **`_run_chain`** — `step_type="edit"` + доверяет `lr.success`
  (больше не проверяет `applied_ops` снаружи).

### Убрано

- **`run_agent_decompose`:** внешняя проверка `loop_result.applied_ops > 0`
  — переехала в `run_tool_loop`.
- **`_run_chain`:** внешняя проверка `lr.applied_ops > 0` — то же.

### Тесты

Переделаны (моки стали честными):

- `_ok_loop_no_ops` → `success=False, stopped_reason="no_ops"`.
- `test_run_agent_decompose_success_requires_applied_ops` —
  decompose доверяет `loop.success`.
- `test_run_agent_decompose_retry_zero_ops_not_success` — то же.
- `test_chain_zero_ops_not_success` — мок `success=False`.

405 passed (вместе с 10.32).

---


## [2026-10-13] iteration 10.30 — chain report.md при полном провале

Разбор E12/chain: `chain-<ts>/` создавался, но **пустой**, если все
задачи упали. Пользователь открывает журнал — тишина, отладка
невозможна.

### Добавлено

- **`_save_chain_report(chain_dir, chain_result, loaded)`** — пишет
  `report.md`:
  - шапка (дата, задач, успешно/провалено, суммарная стоимость);
  - markdown-таблица `# | Issue | Статус | RUB | Детали`;
  - секция «Goal каждой задачи».
- **`_run_chain`** вызывает `_save_chain_report` **перед return**,
  если `chain_dir` создан. Пишется **всегда** — включая полный провал.
- **`report_path`** в возвращаемом dict + вывод «Отчёт: ...» в
  `_print_chain_report`.
- **`stopped_reason="no_ops"`** при `success=True, applied_ops=0`
  (вместо вводящего в заблуждение `completed`).

### Тесты

+4 (403 passed):

- `test_chain_saves_report_on_success` — обе ✅ → `report.md`.
- `test_chain_saves_report_on_all_fail` — все ❌ → `report.md` есть.
- `test_chain_saves_report_on_partial_fail` — 1 ✅, 1 ❌ → `report.md`.
- `test_chain_report_path_in_stdout` — «Отчёт:» в выводе.

Расширен:

- `test_chain_zero_ops_not_success` — проверяет `no_ops` в отчёте.

### E2E

Chain из 2 задач (1 ✅, 1 ❌) — отчёт создан, читаемый,
markdown-таблица корректна.

---


## [2026-10-13] iteration 10.29 — --no-verify отключает verify_commands

Разбор E12. Нашли, что `--no-verify` в `agent_cmd` управлял **только**
`py_compile`, а `cfg.agent.verify_commands` (запуск `pytest` и т.п.)
**не трогал**. На чужом проекте это ломало прогон: verify чужого
`legacy/test_url.py` падал → агент считал работу провалённой.

### Фикс

- **`run_tool_loop`:** новый параметр `verify_commands: list[str] | None`.
  Fallback на `cfg.agent.verify_commands` при `None`. Позволяет
  вызывать tool loop с явным списком или с `[]` (не проверять).
- **`run_agent_decompose`:** новый параметр `verify_commands`.
  Пробрасывается в оба `run_tool_loop` (основной + retry).
- **`agent_cmd --no-verify`:** теперь отключает **и** `py_compile`,
  **и** `verify_commands` (обнуляет `cfg.agent.verify_commands = []`).
  Семантика: «не проверять вообще».
- **`_run_chain`:** удалён мёртвый параметр `verify_commands: str | None`
  (был в сигнатуре, не использовался).

### Тесты

+5 (399 passed):

- `test_run_tool_loop_verify_commands_explicit` — `verify_commands=["true"]`
  при пустом cfg → verify зовётся.
- `test_run_tool_loop_verify_commands_empty_disables` — `verify_commands=[]`
  при непустом cfg → verify не зовётся.
- `test_run_tool_loop_verify_commands_none_falls_back_to_cfg` — `None` →
  fallback на cfg.
- `test_run_agent_decompose_verify_commands_passthrough` — `[]` уходит
  в `run_tool_loop` из decompose.
- `test_agent_cmd_no_verify_disables_verify_commands` — CLI `--no-verify`
  обнуляет `cfg.agent.verify_commands`.

### TODO

- **E12 перезапустить** после фиксов — теперь можно без своего config.
- Workaround «свой config с `verify_commands: []`» — больше не нужен.

---


## [2026-10-11] iteration 10.28 — max_iterations + fix applied_ops в retry

Разбор E12 (decompose в чужом проекте). Нашли **неполноту фикса 10.27**:
retry-путь v4-pro **не учитывал** `applied_ops > 0`. Плюс — отдельная
правка `max_iterations` (из параллельной сессии).

### Что нашли

- **E12 subtask 2 (`gui.py`)** — формально ✅, но **0 правок**.
  Причина: в `run_agent_decompose` **retry-путь** (v4-pro fallback)
  записывал `"success": loop_result.success` **без** `applied_ops > 0`
  (основной путь уже был пофикшен в 10.27).
- **`max_iterations` из CLI** не доходил до `run_tool_loop` в
  decompose — использовался `cfg.agent.max_steps` безусловно.

### Фикс

- **`run_agent_decompose`:** новый параметр `max_iterations: int | None`.
  `eff_iters = max_iterations if not None else cfg.agent.max_steps`.
  Применён в основном и retry-путях.
- **retry-путь:** `"success": loop_result.success and
  loop_result.applied_ops > 0` (как основной путь в 10.27).
- **`cli.py`:** проброс `max_iterations` из `agent_cmd`.

### Тесты

+3 (394 passed):

- `test_run_agent_decompose_passes_max_iterations` — аргумент
  перебивает `cfg.agent.max_steps`.
- `test_run_agent_decompose_max_iterations_fallback` — без аргумента
  используется `cfg.agent.max_steps`.
- `test_run_agent_decompose_retry_zero_ops_not_success` — retry
  (v4-pro) с `applied_ops=0` → subtask success=False.

### E12 (в experiments.md)

- Прогон 1 (verify по умолчанию): `parse_error` + verify_failed
  на `legacy/test_url.py` (чужой тест). 4.57 RUB.
- Прогон 2 (свой config без verify): отчёт ✅, 8.37 RUB.
  - subtask 1 (`ytdl.py`) — ✅, изменения корректные.
  - subtask 2 (`gui.py`) — **ложный ✅** (0 правок).
- **Урок:** retry-путь — отдельная ветка, фиксы основного пути её
  не покрывают.

### Открыто (TODO)

- **`--no-verify` / `--verify-commands` не работают** для
  decompose/tool loop (только для простого `agent`). Workaround —
  свой config с `verify_commands: []`.
- **E12 перезапустить** после фиксов.

---


## [2026-10-11] iteration 10.27 — applied_ops: успех = применённые правки

Разбор E11 (self-hosted провал). Изначальный диагноз («applied_count == 0
не помечается skipped») оказался **ошибочным** — код в `_run_agent_step`
корректен. Реальный баг: **subtask.success = loop.success** независимо
от того, применены ли правки.

### Проблема

- **`run_agent_decompose`:** `"success": loop_result.success`. Если
  модель сделала `finish(success)`, но 0 правок — подзадача ✅.
- **`_run_chain`:** `ok = lr.success` (tool loop) и
  `all(subtask.success)` (decompose). Пустой список = True.
- **E11 subtask 1 (v4-pro retry):** `success: True`, правок 0 —
  формально «успех», фактически ничего.

### Фикс

- **`ToolLoopResult.applied_ops: int = 0`** — счётчик успешных
  `write_file`/`edit_file`. Учитывает `--resume` (пересчёт из
  загруженной history).
- **`run_agent_decompose`:**
  `"success": loop_result.success and loop_result.applied_ops > 0`.
- **`_run_chain`:**
  - decompose: `ok = parse_error is None and bool(subtask_results)
    and all(r["success"])`;
  - tool loop: `ok = lr.success and lr.applied_ops > 0`,
    в entry добавляется `applied_ops`.

### Тесты

- `_ok_loop` → `applied_ops=1` (фикс мока).
- `_ok_loop_no_ops` — новый мок (success=True, правок 0).
- `test_run_agent_decompose_success_requires_applied_ops` — 0 правок
  → subtask success=False.
- `test_run_agent_decompose_success_with_applied_ops` — 1 правка
  → success=True.
- `test_chain_zero_ops_not_success` — chain: applied_ops=0 → ❌.

+4 (391 passed).

### E11 — обновление

- **Баг «applied_count == 0»** — ошибочный диагноз, **закрыт**.
- **v4-pro был прав**, когда сказал «уже сделано».
- **Новый TODO:** `--split-goals` не проверяет, решена ли задача.
- **Открытый вопрос:** read-задачи (без правок) новый критерий
  `applied_ops > 0` сломает. Нужен `read_ops` или явный тип read.

### Docs

- `docs/experiments.md` → E11 (поправка).
- `TODO.md` → уточнение находок.

---


## [2026-10-11] iteration 10.26 — --split-goals: одна фраза → N issues

Направление 10, уровень F. Замыкает цепочку: `--split-goals` создаёт
issues → `--chain` их выполняет. Устраняет ручную работу из E9
(~15 issue-файлов, написанных руками).

### Добавлено

- **`agent --split-goals "<goal>" <project>`** — разбивает фразу на N
  **независимых** issues (v4-pro):
  - сохраняет `issues/1-<slug>.md`, `2-<slug>.md`, ...;
  - `# task: <title>` + тело (goal);
  - **не выполняет** — только создаёт файлы;
  - если `issues/` не пуст — пишет в `issues-<ts>/`;
  - если фраза — одна задача, создаётся **один** файл.
- **`_slug_for_issue(text)`** — транслит кириллицы:
  «Добавь sub в calc.py» → `dobav-sub-v-calc-py`.
- **`parse_split_goals_response(content)`** — парсер JSON
  `{"issues": [{"title", "goal"}, ...]}`.
- **`run_split_goals(...)`** — LLM-вызов + сохранение файлов.
- **Промпт `agent_split_goals_json`** в `config/prompts.yaml`.
- **Запрещено совмещать:** `--split-goals` + `--plan` /
  `--decompose` / `--tool-loop` / `--chain` / `--issue`.

### E2E

Песочница `/tmp/split-test`, фраза «добавь sub, mul, div + README +
тесты»:

- `--split-goals` → **3 issues**, 0.1856 RUB.
  - `1-add-arithmetic-functions.md`, `2-create-readme.md`,
    `3-add-calc-tests.md`.
- `--chain issues/ --plan --tool-loop` + `y` → 3 задачи ✅,
  0.7659 RUB.
- **Итог:** `calc.py` + `sub/mul/div`, `README.md`, `test_calc.py`
  (5 тестов), `5 passed`.
- **Полная цепочка:** 0.95 RUB.

### Тесты

+10 (387 passed):

- `test_parse_split_goals_valid`, `test_parse_split_goals_markdown_wrapper`,
  `test_parse_split_goals_empty`, `test_parse_split_goals_invalid_json`,
  `test_slug_for_issue_cyrillic`, `test_run_split_goals_saves_files`,
  `test_run_split_goals_nonempty_dir_uses_timestamp`,
  `test_split_goals_conflicts_with_chain`,
  `test_split_goals_conflicts_with_tool_loop`,
  `test_split_goals_requires_goal`, `test_split_goals_ok`.

### Roadmap

Направление 10: уровни **A, B, E, F** закрыты. Остаются C
(`--interactive-plan`), D (`--context-search`).

### TODO (мелочи после E2E)

- язык issue (LLM пишет на английском, если goal русский);
- отдельная модель `split_goals_model` (flash вместо v4-pro);
- подсказка в ошибке `--split-goals` + `--plan`.

---


## [2026-10-11] iteration 10.25 — --chain: пакетное выполнение issues

Направление 10, уровень E. Пользователь пишет N независимых issue
(`issues/*.md`), одна команда выполняет все по очереди с итоговым
отчётом.

### Добавлено

- **`agent --chain <dir>`** — цикл по `sorted(dir.glob("*.md"))`:
  - три режима: `--tool-loop` (без decompose), `--tool-loop --decompose`,
    `--tool-loop --plan` (показ всех планов + один `y/n/e` → decompose);
  - `--stop-on-fail` (по умолчанию) / `--continue-on-fail`;
  - итоговая таблица: `# | задача | статус | RUB | детали` + сумма.
- **`_read_issue_file()`** — вынесена из `agent_cmd` для переиспользования.
- **`--chain --plan`:** все планы через один `y/n/e`; один общий
  `plan.yaml`; при `y` — `run_agent_decompose(plan=pre_plan)` **без
  повторного планирования**.
- **hack для `--chain`:** если `goal` — директория, считать это `path`
  (как у `--issue`). Перенесён **выше** `project_root = path.resolve()`,
  иначе chain правил не тот проект (баг найден на E2E).
- **Хелперы:** `_run_chain`, `_print_chain_report`, `_print_chain_plans`,
  `_save_chain_plan_yaml`, `_load_chain_plan_yaml`,
  `_edit_chain_plans_and_reload`.

### E2E

Песочница `/tmp/chain-*`, `calc.py` + issues:

- `--chain --tool-loop` (2 задачи) → 0.12 RUB, обе ✅.
- `--chain --tool-loop --decompose` (1 задача) → 0.17 RUB, ✅.
- `--chain --tool-loop --plan` + `n` (2 задачи) → 0.13 RUB, правок нет.
- `--chain --tool-loop --plan` + `y` (2 задачи) → 0.36 RUB, обе ✅,
  планирование **не повторяется** (2 вызова v4-pro, не 4).

### Тесты

+7 (377 passed):

- `test_chain_requires_tool_loop`, `test_chain_and_issue_conflict`,
  `test_chain_and_goal_conflict`, `test_chain_empty_dir`,
  `test_chain_two_issues_ok`, `test_chain_stop_on_fail`,
  `test_chain_continue_on_fail`.

### Roadmap

Направление 10: уровни **A (`--plan`), B (`--plan-review`), E (`--chain`)**
закрыты. Остаются C (`--interactive-plan`), D (`--context-search`).

---


## [2026-10-11] iteration 10.24 — --plan: план → подтверждение → выполнение

Направление 10 (планировщик из human-goal), MVP. Пользователь даёт
задачу человеческим языком — v4-pro разбивает на подзадачи, агент
показывает план, спрашивает `y/n/e`, и только после `y` выполняет.

### Добавлено

- **`agent --plan`** — разбиение + показ + подтверждение + выполнение:
  - `run_planner_decompose` → таблица подзадач (номер, задача, файлы);
  - `plan.yaml` сохраняется в `.ai-out/<project>/plan-<ts>/`;
  - вопрос `y/n/e` (`e` — открыть `plan.yaml` в `$EDITOR` и перечитать);
  - при `y` — `run_agent_decompose(plan=pre_plan)` **без повторного
    планирования** (экономия ~0.06–0.08 RUB на каждой задаче).
- **`run_agent_decompose(plan=...)`** — принимает готовый `DecomposeResult`.
  Обратная совместимость: `plan=None` → планирует сам, как раньше.
- **Хелперы в `cli.py`:** `_print_decompose_plan`, `_save_plan_yaml`,
  `_edit_plan_and_reload`, `_prompt_plan_review`, `_plan_yaml_path`.
- **Edge-cases:**
  - `except typer.Exit: raise` — `Exit(0)` при `n` больше не превращается
    в `Ошибка decompose: 0`;
  - `EOFError`/`KeyboardInterrupt` в prompt → отмена, не трейсбек;
  - проверка `shutil.which(editor)` — понятное сообщение, если
    `$EDITOR`/`vi` не найден.

### E2E

Песочница `/tmp/plan-test`, задача «добавь `sub` + тест»:

- **`--plan` + `n`:** план на 2 подзадачи, 0.0837 RUB, правок нет. ✅
- **`--plan` + `y`:** одна строка «Декомпозиция: 2 подзадач»
  (не перепланирует), 0.2625 RUB, `sub` добавлен, `3 passed`. ✅

### Тесты

+4 (370 passed):

- `test_run_agent_decompose_accepts_plan` — не зовёт планировщик;
- `test_agent_plan_requires_tool_loop` — ошибка без `--tool-loop`;
- `test_agent_plan_no_cancels` — `n` → без выполнения;
- `test_agent_plan_yes_executes` — `y` → с планом в `run_agent_decompose`.

### Roadmap

Направление 10, уровни **A (`--plan`) и B (`--plan-review`)** закрыты.
Остаются C (`--interactive-plan`), D (`--context-search`),
E (`--chain <dir>`).

---


## [2026-10-10] iteration 10.23 — E9: ai-coder в чужом проекте

Агент работал в `youtube-playlist-downloader` (~600 строк) через
`--issue` + `--tool-loop`. ~15 задач: рефакторинг, GUI,
транскрибация, пунктуация, LLM-обработка, README.

### Ключевые фичи (за сессию)

- **write_file auto-chmod** — `.sh`/shebang → +x.
- **--issue <file>** — задача из Markdown-файла.
- **--with-tests** — pytest-тесты для изменённых файлов.
- **--auto-fix-issues** — цикл verify → fix → verify.
- **read_symbol** — чтение функции/класса Python по имени.
- **blacklist, mask_secrets, shell=False, whitelist аргументов** —
  безопасность (ревью 09-full закрыто).
- **apply.py неатомарность** — rollback удаляет пустые каталоги.

### Эксперименты E3–E9

- **E3**: read_symbol — 2 итерации вместо 3.
- **E4**: scan-cache — отклонён (0.1% времени).
- **E5**: --auto-fix-issues.
- **E6**: --with-tests (×2.3 дешевле).
- **E7**: --issue на сложном — провал (19 строк goal).
- **E8**: граница flash — 10 задач, все ✅.
- **E8.1**: длина goal критична.
- **E9**: ai-coder в чужом проекте — ~15 задач, ✅.

См. `docs/experiments.md`, `docs/roadmap.md` (направление 10),
`docs/autonomy.md` (этап 5).

Тесты: 366 passed.

---

## [2026-10-10] iteration 10.22 — warning о длине goal + E8.1 (граница flash)

### Warning о длине goal в `--issue`

- **Что:** в `ai_coder/cli.py` в `agent_cmd` — предупреждение
  о длине goal (для `--issue` и CLI-аргумента).
- **Пороги (по E7, E8):**
  - **> 10 строк** — жёлтый: «Правило: < 10 (E8). Риск флейка».
  - **> 15 строк** — красный: «Высокий риск флейка (E7: 19 строк
    → parse_error). Разбей на 2-3 коротких задачи».
- **Зачем:** E7 (провал 1.5, 19 строк), E8.1 (4 строки → ✅),
  E8 (10 задач — все ✅). Длина goal — **главный фактор** флейков.

### E8.1 — повтор 1.5 с коротким goal (в `experiments.md`)

- **Та же задача** (`apply.py`, manifest version + rollback),
  но **goal 4 строки** вместо 19.
- **flash:** 6 итераций, **0.3435 RUB**, ✅.
- **v4-pro:** 8 итераций, **2.5880 RUB**, ✅ (×7.5 дороже).
- **Вывод:** H12 (длина goal) подтверждена. v4-pro **не быстрее**
  flash на этой задаче. Flash достаточен для большинства задач.

### E8 — граница flash (в `experiments.md`)

10 задач, все ✅. См. `docs/experiments.md` → E8.

---

## [2026-10-10] iteration 10.21 — rollback удаляет пустые каталоги (ревью 1.5)

Последний пункт ревью v4-pro (09-full). Закрывает «неатомарность»
`apply_plan`: при откате пустые каталоги, созданные `mkdir(parents=True)`,
оставались на диске.

### Что было

`apply_plan` создавал каталоги через `mkdir(parents=True)` и **не
запоминал**, какие были созданы. `rollback` удалял **файлы**, но
**каталоги** — нет. После отката оставались пустые `a/b/c/`.

### Фикс

- **`_collect_new_dirs(abs_parent, root)`** — собирает несуществующие
  каталоги вверх от `abs_parent`, создаёт от корня к глубокому,
  возвращает **от глубокого к корню** (порядок для отката).
- **`apply_plan`:** `created_dirs: list[str]` → `manifest.json`
  (поле `"created_dirs"`).
- **`rollback`:** после удаления файлов проходит по `created_dirs`,
  удаляет через `rmdir` (не пуст → ignore).

### Тесты

+2 в `test_apply.py`:
- `test_rollback_removes_empty_dirs`: create_file a/b/c.py →
  rollback → файл и каталоги a/b/c, a/b, a удалены.
- `test_rollback_keeps_non_empty_dirs`: если в a/b есть другой
  файл — a/b сохранён.

### Как это сделано (важно)

- **Прогон 1** (`--issue --tool-loop`, flash): **провал** —
  `parse_error: tool JSON no '{' found`. Issue 19 строк, 2 функции
  (apply_plan + rollback), файл 500+ строк.
- **Прогон 2** (`--issue --decompose --decompose-replan`, v4-pro
  разбивает): **провал** — v4-pro не разбил по функциям, первая
  подзадача = вся задача.
- **Агент успел 50%:** `_collect_new_dirs` (корректная), `created_dirs`
  собирается, но **не записано в manifest**, `rollback` не тронут.
- **Доделано вручную (~30 минут):** вызов `_collect_new_dirs`,
  `manifest["created_dirs"]`, `rollback` + 2 теста.

См. `docs/experiments.md` → E7 (отрицательный результат `--issue`).

### Итого

- Тесты: **360 → 362** (+2).
- Ревью 09-full: **1.1, 1.2, 1.3, 1.4, 1.5** — **все закрыты**.

---

## [2026-10-10] iteration 10.20 — --issue <file> (направление 4, issue-driven)

Задача агента — из Markdown-файла, а не из командной строки.
Снимает боль с backticks/кавычками в bash, даёт структуру и
переиспользование. Фундамент issue-driven development.

### Добавлено

- **`--issue <file>`** для `agent`: читает Markdown-файл с задачей.
- **`goal` стал опциональным** — `typer.Argument("")` вместо `...`.
- **Парсинг:**
  - первая строка `# task: ...` отбрасывается (заголовок);
  - обрезка до 60 строк (с пометкой в конце).
- **Hack с path:** если `--issue` + позиционный `goal` — это
  **директория**, считаем её `path`. Убирает путаницу typer с двумя
  позиционными аргументами (`goal`, `path`).
- **Валидации:**
  - `--issue` + goal (не директория) → ошибка;
  - файл не найден → ошибка;
  - файл пустой (после заголовка) → ошибка.
- **Backticks-warning** пропускается для `--issue` (в файле они
  нормальны, не bash).

### Сценарии

- **GitHub issues:** `gh issue view 123 > issues/123.md` →
  `ai-coder agent --issue issues/123.md . --tool-loop --apply`.
- **Свои задачи:** `issues/*.md` в репозитории.
- **Roadmap-driven:** roadmap разбит на куски, каждый — `issues/N.md`.
- **Воспроизводимость:** задача в файле — вернуться через неделю легко.

### Пример

    ai-coder agent --issue issues/1-add-sub.md /tmp/proj \
        --tool-loop --apply --max-cost-rub 1

Вывод: `Задача из issue: 1-add-sub.md (87 символов, 5 строк)`.
Дальше — обычный tool loop.

### Тесты

+4 в `test_cli_agent.py` (чтение goal, конфликт с goal, файл не
найден, пустой файл).

---

## [2026-10-10] iteration 10.19 — --with-tests (автономность, направление 3)

Агент сам пишет pytest-тесты для изменённых файлов. Замыкает цикл:
`правка → verify → fix → verify → тесты`.

### Добавлено

- **`extract_changed_files(history)`** — публичный хелпер в `agent.py`:
  .py-файлы из `edit_file`/`write_file` (ok=True), без `test_*` и `tests/`.
- **CLI:** `--with-tests` для `agent` (требует `--tool-loop`).
- **Логика:** после успешного tool loop (и опц. auto-fix) —
  извлекаются изменённые файлы, запускается **второй** `run_tool_loop`
  с goal «напиши тесты для этих файлов».
- **Короткий goal (5 строк):** «Сначала найди существующие тесты
  (list_files + grep test_). Если тест для модуля уже есть — добавь
  в существующий. Иначе — создай `test_<module>.py` рядом».
- **Стоимость суммируется**, `success`/`verify_errors`/`summary`
  обновляются.

### E2E (E6)

Песочница `/tmp/withtests-test2`: `calc.py` (`add`), `test_calc.py`
(`test_add`). Задача: добавить `sub`. Флаг `--with-tests`.

| Метрика | v1 (13 строк goal) | **v2 (5 строк)** |
|---|---|---|
| Итераций with-tests | 9 | **3** |
| Флейки `missing args` | 3 | **0** |
| Файл тестов | **создал `tests/`** (дубль) | **обновил `test_calc.py`** |
| Стоимость всего | 0.4493 RUB | **0.1945 RUB** |
| Результат | ✅ но с дублем | ✅ **чисто** |

**Вывод:** короткий goal (5 строк) с «сначала найди» — **в 2.3×
дешевле** и **в 3× меньше итераций**, чем длинная инструкция (13 строк).

### Тесты

+6 в `test_agent.py` (`extract_changed_files`: empty, edits, skip
tests, skip failed, skip finish, skip non-py).

---

## [2026-10-10] iteration 10.18 — whitelist аргументов run_shell (ревью 1.4)

Второй слой защиты `run_shell`: после whitelist по имени команды —
чёрный список опасных флагов. Закрывает дыры, которые оставались
внутри разрешённых команд.

### Проблема

`find` и `git branch` были в whitelist **целиком** — вместе с
опасными флагами:
- `find . -delete` — **удалял файлы** в проекте;
- `find . -exec <cmd>` — **выполнял произвольные команды**;
- `tail -f` — **бесконечный** вывод (только timeout спасал);
- `git branch -D <branch>` — **удалял ветку**;
- `git log --exec=<cmd>` — **выполнял команду** на каждом коммите.

### Фикс

- `_SHELL_FORBIDDEN_FLAGS` — простые команды:
  - `find`: `-delete`, `-exec`, `-execdir`, `-ok`, `-okdir`, `-fdelete`, `-fls`;
  - `tail`: `-f`, `--follow`, `-F`.
- `_GIT_FORBIDDEN_FLAGS` — по подкоманде:
  - `branch`: `-D`, `-d`, `-m`, `-M`, `--delete`, `--move`, `--set-upstream-to`, `-u`;
  - `log`, `diff`, `show`: `--exec`, `--ext-diff`, `--textconv`.
- `_flag_is_forbidden` — сравнение как целого токена, так и префикса
  до `=` (`--exec=rm` → `--exec`).

### Smoke

| Команда | Результат |
|---|---|
| `find . -delete` | REJECT (`flag forbidden for find: -delete`) |
| `find . -name *.py` | OK |
| `find . -name x -exec rm` | REJECT (`-exec`) |
| `tail -f log.txt` | REJECT (`-f`) |
| `tail -n 10 log.txt` | OK |
| `git branch -D main` | REJECT (`-D`) |
| `git branch` | OK |
| `git log --exec=rm` | REJECT (`--exec`) |
| `git log --oneline` | OK |

### Тесты

+9 в `test_tools.py` (find, tail, git branch, git log).

---

## [2026-10-10] iteration 10.17 — --auto-fix-issues (автономность, направление 1)

Замкнули цикл `правка → verify → fix → verify` в одну команду.
Если после `run_tool_loop` verify падает — автоматически запускается
`run_auto_fix` (до 3 попыток).

### Добавлено

- **CLI:** `--auto-fix-issues` для `agent` (требует `--tool-loop`).
- **Логика в `agent_cmd`:** после `run_tool_loop`, если
  `not success and verify_errors` — вызывается `run_auto_fix`.
- **Суммирование стоимости:** tool loop + auto-fix в одном отчёте.
- **Бюджет:** `--max-cost-rub` делится — остаток идёт в auto-fix.
- **Обновление итога:** `success`, `verify_errors`, `summary`
  пересчитываются после auto-fix.

### Smoke-тест (E5)

Песочница `/tmp/autofix-test`: `calc.py` с багом (`return a - b`),
падающий тест `test_add`. Агент по задаче **не правил** файл
(просто `read_file` + `finish`), verify упал → auto-fix:

- **Попытка 1:** ошибка → fix через tool loop → правит `calc.py` → pytest ✅
- **Попытка 2:** ✅ Auto-fix: успех
- **Стоимость:** 0.1460 RUB (tool loop ~0.06 + auto-fix ~0.09)
- **Результат:** `✅ успех`, `Summary: verify failed, auto-fix: 2 попыток → ok`

### Отложено

- Интеграция в `--decompose` (там уже replan/rollback для подзадач).
- Интеграция в `run_agent` (классический) — там свой `--max-fix-attempts`.

---

## [2026-10-10] iteration 10.16 — read_symbol (навигация, направление 2A)

Инструмент `read_symbol` — чтение функции/класса Python по имени,
без `grep -n` + `read_file(line_start, line_end)`. Два коммита.

### feat — read_symbol (`c66ec38`)

- **tools.py:** `tool_read_symbol(name, path=None, kind=None)`
  - Python-only (regex `^def` / `^class` / `^async def`);
  - `path` опционально (иначе — поиск по всем `.py` проекта);
  - `kind`: `'def'` | `'class'` (опционально);
  - учитывает декораторы, вложенные методы, отступы;
  - при коллизии возвращает первый + помечает в шапке;
  - `mask_secrets` применяется;
  - обрезка на 50K, как в `read_file`.
- **TOOL_REGISTRY:** 6-й инструмент (`read_symbol`).
- **prompts.yaml:** правило 11 — путь **C** (read_symbol вместо grep).
- **tests:** +9, обновлены `test_registry_has_six_tools`.

### fix — format_tool_history (`70e15d1`)

- **Проблема (из эксперимента):** `read_symbol` попадал в `other_max_chars`
  (500 символов) → в истории для модели был обрезанный результат →
  модель **перечитывала** через `read_file`. 3 итерации вместо 2.
- **Фикс:** `read_symbol` в привилегированном пути (10000, как `read_file`);
  пометка при обрезке: «Не перечитывай — правь через edit_file».
- **tests:** +2.

### Эксперимент (E3, 2026-10-10)

Задача: добавить строку в docstring `run_tool_loop` (`agent.py`, 2806 строк).

| Метрика | 10.14.14 (grep) | read_symbol v1 | **read_symbol v2** |
|---|---|---|---|
| Итераций | 3 | 3 (+read_file) | **2** |
| Стоимость | 0.13 RUB | 0.1586 RUB | **0.1125 RUB** |
| Путь | read_file→grep→read_file→edit | read_symbol→**read_file**→edit | **read_symbol→edit** |

**Итог:** 2 итерации вместо 3, дешевле на 13% (от 10.14.14) и на 29%
(от read_symbol v1).

### Итого тестов

- 330 → **341** (+11: +9 read_symbol, +2 format_tool_history).

---

## [2026-10-10] iteration 10.15 — Сессия 1: критичные фиксы безопасности

Три пункта из ревью v4-pro (2026-10-09-full), раздел «Критично». Все
блокировали безопасную автономность агента.

### 1.1 — blacklist для tool loop (`2d8e31b`)

- **Проблема:** tool loop обходил `apply_plan`-blacklist. Агент мог
  писать в `.git/**`, `config/config.yaml`, `pyproject.toml`, `.env`.
- **Фикс:**
  - новый модуль `ai_coder/pathfilter.py` — общий `is_blacklisted()`;
  - `apply._path_is_blacklisted` делегирует в `pathfilter`;
  - `tools.execute_tool`: `write_cfg` + `allow_blacklist` (keyword-only);
  - проброс через `run_tool_loop`, `run_agent_decompose`, `run_auto_fix`;
  - CLI: `--allow-blacklist` для `agent` и `fix` (opt-in self-improvement);
  - дефолт `write_cfg=None` → проверка выключена (обратная совместимость).
- **Тесты:** +4 в `test_tools.py`.

### 1.2 — маскировка секретов в tool loop (`1f31880`)

- **Проблема:** `_contains_secret` работал только при скане. `tool_read_file`
  и `run_shell` отдавали секреты в LLM (утечка API-ключей).
- **Фикс:**
  - `scanner.mask_secrets(text)` → `(masked, names)`;
  - `tool_read_file` (оба режима) и `tool_run_shell` маскируют вывод;
  - warning-строка в начале вывода: `⚠️ [masked N secret(s): ...]`.
- **Тесты:** +3 в `test_scanner.py`, +3 в `test_tools.py`.

### 1.3 — `run_verify_commands` без `shell=True` (`2ef8073`)

- **Проблема:** `subprocess.run(cmd, shell=True)` — RCE-вектор.
  `pytest -q; rm -rf /` выполнял `rm`.
- **Фикс:**
  - `shlex.split` + `shell=False`;
  - blacklist первого токена: `rm`, `dd`, `mkfs`, `shutdown`, `kill`,
    `sudo`, `chmod`, `chown` и др.;
  - `pytest -q; rm -rf /` больше не выполняет `rm` — `;` становится
    частью аргумента `-q;`.
- **Тесты:** +3 в `test_apply.py`.

### Итого

- Тесты: **317 → 330** (+13).
- CI: pytest × 3 (3.10/3.11/3.12) + ruff + mypy — зелёный.
- Коммиты: `2d8e31b`, `1f31880`, `2ef8073`.

---

































## [2026-10-09] iteration 10.14.9–10.14.29 — серия улучшений (docs + infra + фичи)

Сводная секция: **17 итераций** (не попали в CHANGELOG отдельно).
Основное — в `docs/experiments.md` и коммитах.

### Фичи

- **10.14.10** — действие `explain` (read): объяснить файл/функцию/класс.
- **10.14.23** — `--hint` для `run`: доп. указание к промпту (дописывается
  в конец `user` с пометкой `[УТОЧНЕНИЕ]`). Работает для всех `run`-действий.
- **10.14.26** — retry в tool loop при `missing args` (`_has_missing_args`,
  `max_arg_retries=3`); правило 12 расширено — закрыты TODO п.24-25.

### Документация

- **10.14.9, 10.14.12, 10.14.15, 10.14.17, 10.14.25, 10.14.27, 10.14.29** —
  `docs/experiments.md`: класс Stats, decompose-replan в бою, E2
  (read_file offset), наблюдения, разбор провала `--hint`, flash v2
  после фикса, уточнения.
- **10.14.11** — `test_config.py` + README + `scenarios.md` (раздел 12
  про `explain`).
- **10.14.20** — README: разделы «Действия», «Агент — флаги», «Команды CLI».
- **10.14.21** — `docs/examples.md` — 9 практических сценариев.
- **10.14.22** — README: раздел «Документация» + кликабельные ссылки.
- **10.14.24** — `docs/reviews/v4-pro-2026-10-09-full.md`: полное ревью
  v4-pro (17 файлов, 4.37 RUB, 6 разделов + приоритизация для автономности).
- **10.14.28** — TODO п.24-25 закрыты.
- **10.14.30** — `--hint` в README/scenarios/examples.

### Инфраструктура

- **10.14.19** — `scripts/collect_for_next_chat.sh` — сборка bundle
  для нового чата; `next-chat/` в `.gitignore`.

### Тесты

- 316 → **317** passed (+1, retry missing args).

---

## [2026-10-09] iteration 10.14.18 — fix(decompose): report.md при ранних return

### Исправлено (TODO п.19)
- `run_agent_decompose`: при **раннем `return`** —
  `_save_decompose_report` **не вызывался**, если выход произошёл
  **до** финального сохранения. Пользователь **не видел**
  итоговый отчёт.
- Три места:
  - `max_cost exceeded` (новый блок из 10.14.16);
  - `replan_result.parse_error`;
  - `replan_result.action == "stop"`.
- Во всех трёх — теперь `if decompose_dir is not None:
  _save_decompose_report(...)` **перед** `return`.

### Найдено
- При живой проверке `--decompose-max-cost-rub 0.01` (10.14.17) —
  `decompose-<ts>/` создан, а `report.md` внутри **нет**.

### Тест
- `test_run_agent_decompose_max_cost_saves_report` — проверяет,
  что при `max_cost` `report.md` **создан**.

### Итого тестов
- 315 → 316 passed (+1).

---

## [2026-10-09] iteration 10.14.16 — feat(decompose): --decompose-max-cost-rub

### Добавлено
- `run_agent_decompose(max_cost_rub: float | None = None)` —
  бюджет всего decompose.
- `remaining` пересчитывается **перед каждым** `run_tool_loop`
  (основной + retry) как `max(0.0, max_cost_rub - dec_result.cost_rub)`.
- После каждой подзадачи (после retry) — проверка:
  `if max_cost_rub is not None and dec_result.cost_rub >= max_cost_rub:
  dec_result.parse_error = "max_cost exceeded"; return`.
- CLI `agent`: флаг `--decompose-max-cost-rub N`.
- Тест `test_run_agent_decompose_max_cost`.

### Написано агентом через tool loop
- **16 итераций, 1.8532 RUB, 6 edit_file** — 4 в `agent.py`,
  2 в `cli.py`.
- `read_file(line_start, line_end)` использован **с самого начала** —
  фикс 10.14.14 работает.
- Модель **сама** догадалась:
  - `remaining` пересчитывать **перед** retry;
  - проверку бюджета делать **один раз** после retry.
- 3 промежуточных фейла (`missing 'path'`) — модель повторила
  вызовы и справилась.

### Итого тестов
- 314 → 315 passed (+1).

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
