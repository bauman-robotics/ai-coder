# TODO

Список идей и задач на будущее. Не всё срочно; помечено приоритетом.



## Findings D5/D6/D7 (сессия 2026-10-16, 10.75–10.77)

Детали — `docs/findings-d5.md`; отчёты — `docs/dsh.md` → D5, D6.

### ✅ Закрыто в 10.76

- [x] **#1 verify не ловит mypy** — `agent.self_verify_commands`
      применяются только для проекта-цели «сам ai-coder»
      (`apply.is_self_hosted`). Коммит `1b2ee2f`.
      Проверено: типовая ошибка → verify fail; чужой проект не затронут.
- [x] **#3 модель не делегирует без подсказки** — правило «когда»
      в `build_subagents_section`. Коммит `043aa96`.
      Уточнение: на **малой** задаче не делегировать — **правильно**
      (0/3 в обоих вариантах); проблема была на большой (0/3 → 3/3).

### ✅ #2 Validator в tool loop — закрыто (D7, `1822df5`)

- [x] `--reverse-check` **включён по умолчанию** в tool loop (10.77).
      Реализация — **tri-state** (`bool | None`): `None` → вкл в tool loop
      и выкл вне него; `--no-reverse-check` → явный отказ; явный
      `--reverse-check` без `--tool-loop` — по-прежнему ошибка.
      Библиотечный `run_tool_loop(reverse_check=False)` не менялся.
      Стоимость: **+1 запрос**, только при непустом diff.
      **Файлы:** `ai_coder/cli.py`, `ai_coder/agent/tool_loop.py`.
- ⚠️ **Остаточное ограничение:** RC ловит несоответствие diff и goal,
      но **не** ловит фикс, формально удовлетворяющий **размытому**
      goal (эксперимент D7, 0.85 RUB: размытый goal → `ok=True`,
      точный → `ok=False`). Корень — формулировка задачи, а не тайминг.

### 🟡 #4 `iterations` ≠ числа LLM-вызовов

- [ ] `iterations=len(ctx.history)`, а `_handle_finish` в `history`
      не пишет → расхождение на 1 с `usage.jsonl` (в D6: 15 шагов
      против 16 записей). **Файлы:** `ai_coder/agent/tool_loop.py`.
      ~1 ч. **Приоритет:** 🟡.

### 🟡 #5 пустой `summary` при `max_iterations`

- [ ] Digest subagent'а приходит с `summary:` пустым — родитель
      не знает, что упало (D5: test-runner; D6: все large-прогоны).
      **Файлы:** `ai_coder/agent/tool_loop.py` (ветка `for/else`),
      `ai_coder/agent/spawn.py` (`summarize_subagent_result`). ~1 ч.
      **Приоритет:** 🟡.

### 🟡 #6 перерасход `cap`

- [ ] «≤ 1 итерации» уже задокументировано в `CHANGELOG.md`, но
      **не** в `docs/tools.md` §6 → дописать. Опционально: precheck
      по типу инструмента (E37). **Файлы:** `docs/tools.md`,
      `ai_coder/agent/planner.py`. ~15 мин / ~2 ч. **Приоритет:** 🟡→🟢.

### 🟢 #7 `.venv/bin/ai-coder` из worktree не существует

- [ ] Не баг ai-coder: venv в main + editable install. Нужен рецепт
      (абсолютный путь к venv, `PATH=.venv/bin`,
      `PYTHONPATH=<worktree>`, `set -a; . .env; set +a`).
      **Файлы:** `docs/tools.md` (раздел «Self-hosted E2E в worktree»).
      ~30 мин. **Приоритет:** 🟢.

### ✅ E2E Router без `--model` — закрыто (D9)

- [x] **Проверено (D9): Router работает.** E2E
      `--tool-loop --decompose --apply` **без `--model`**: 6 подзадач,
      все ✅, EXIT=0, 4.6092 RUB.
      `explore` → flash, `edit-complex` → **v4-pro**, `edit-simple` →
      flash, `verify` → flash (модель из журнала каждой подзадачи).
- ⚠️ **Исходная посылка была неверна:** `--model` **не** перекрывает
      выбор Router. Модель подзадачи берётся из `_resolve_subagent(st)`
      (`decomposer.py:371/379`), а параметр `model` идёт только в
      планировщик и retry-fallback. Журнал D8 это подтверждает
      (подзадачи 1/4 — flash, 2/3 — v4-pro).

### ✅ Баг A: у Router нет fallback, если модели нет в `pricing` — закрыто (D10)

- [x] **Исправлено (`5966d52`):** `_resolve_subagent(st, cfg)` теперь
      проверяет `cfg.api.pricing` и при отсутствии модели
      **откатывается на `cfg.api.model`** с предупреждением, а не падает
      `KeyError` в середине прогона.
      Выбран fallback, а не валидация на старте: модели Router —
      встроенная деталь реализации, и требовать цены на
      `deepseek-v4-pro` от конфига с другим провайдером нельзя
      (это сломало бы на старте то, что раньше работало). Модели
      subagent'ов — пользовательские, они и дальше валидируются в D6.
      **Тесты:** fallback, отсутствие `KeyError` в предпроверке бюджета,
      предупреждение.

### ✅ Баг B: `--max-iterations` перекрывал лимиты Router — закрыто (D10)

- [x] **Исправлено (`5966d52`):** default `--max-iterations` → `None`
      (+ хелпер `_iters_or_default()` = 20 для не-decompose путей).
      `run_agent_decompose` получает **сырое** значение: `None` →
      лимиты Router; обычный tool loop, `--with-tests` и chain —
      прежние 20. Явный `--max-iterations N` работает как раньше.
      **Тесты:** `[5, 10, 15, 3]` при `None`; явный `N` перекрывает;
      CLI-проброс в обоих режимах.

### ⚠️ Баг C: `verify: 3` мало — лимит поднят до 5 (D10 → D10.1), но это НЕ корень

- [ ] **Симптом (E2E D10, повтор сценария D9):** после включения
      Router-лимитов verify-подзадача («Запустить pytest и
      убедиться») **упала**: `max_iterations` при 3 итерациях, и
      retry (v4-pro) тоже получил 3 → `subtask 7 failed`, EXIT=1.
      В D9 (лимит фактически 20) та же задача проходила, EXIT=0.
      **Разбор:** модель потратила **все 3 итерации на `run_shell`**
      (`step-0..step-2`) и не успела вернуть `finish`:
      `for iteration in range(max_iterations)` исчерпался.
      То есть на подзадачу нужно `K` вызовов инструментов **плюс ещё
      одна итерация на `finish`** — лимит по типу задан без этого.
      **Решение (варианты):**
      - поднять значения в `_SUBAGENT_ITERS` (например, verify 3 → 5);
      - трактовать `max_iterations` как лимит **вызовов инструментов**
        и разрешать одну дополнительную итерацию на `finish`
        (правка в `run_tool_loop`).
      **Файлы:** `ai_coder/agent/decomposer.py` (`_SUBAGENT_ITERS`),
      `ai_coder/agent/tool_loop.py` (цикл).
      **Сделано в D10.1 (`f045772`):** вариант A — `verify` 3 → 5
      (вариант B, «+1 итерация на finish», отклонён как рискованный).
      **Результат: не помогло.** E2E D10.1 при лимите 5: те же
      `max_iterations`, EXIT=1. **Настоящая причина — баг D ниже**
      (модель повторяет `pytest -q` и не делает `finish`), поэтому
      значение лимита её не лечит. Лимит 5 оставлен: 3 заведомо мало.

### 🐞 Баг D: verify зацикливается на `pytest -q` и не делает `finish`

- [ ] **Симптом (D10/D10.1):** verify-подзадача («Запустить pytest и
      убедиться») вызывает **одну и ту же** команду `pytest -q` каждую
      итерацию, каждый раз получает `✅ ok` (`2 passed`) и **ни разу не
      возвращает `finish`** → `max_iterations`. Воспроизводится и на
      `deepseek-flash`, и на retry через `deepseek-v4-pro`.
      В D9 та же задача завершилась: 4 вызова `pytest` **+ finish**.
      Сравнение: D9 — 4 вызова + finish (✅), D10 — 3 вызова без finish,
      D10.1 — 5 вызовов без finish (❌ оба).
      **Причина:** в промптах tool loop есть антиповтор для чтения
      («НЕ перечитывай файл, просто `finish`», `config/prompts.yaml`
      ~стр. 347), но **нет такого же правила для `run_shell`**.
      Модель трактует «убедиться» как «запустить ещё раз».
      **Решение:** добавить в промпт правило вида «если команда уже
      вернула `ok` — не повторяй её, верни `finish(success=true)`»;
      возможно, отдельная ветка промпта для `verify`-подзадач.
      **Файлы:** `config/prompts.yaml` (промпт tool loop),
      возможно `ai_coder/agent/prompts.py`.
      **Оценка:** ~2 ч. **Приоритет:** 🔴 (end-to-end `--decompose`
      на задаче с verify падает: EXIT=1).

## Из Validator/GUI (сессия 2026-10-16, 10.71 + 10.72)

### CLI: валидация `--decompose-reverse-check`

- [ ] **`--decompose-reverse-check` без `--decompose` молча игнорируется.**
      Пользователь думает, что проверка включена, реально — нет.
      **Фикс:** в `agent_cmd` (`cli.py`) проверка по образцу
      `--reverse-check требует --tool-loop` (стр. ~1443):

          if decompose_reverse_check and not decompose:
              console.print("[red]--decompose-reverse-check требует --decompose[/red]")
              raise typer.Exit(1)

      **Приоритет:** 🟢 низкий (в GUI — не проблема, чекбокс скрыт).

### Аналогично — для `--decompose-replan`

- [ ] **`--decompose-replan` без `--decompose`** — тоже **молча
      игнорируется**. Добавить такую же проверку.
      **Приоритет:** 🟢 низкий.

### usage: RC-записи

- [ ] **`run_reverse_check` не пишет в `usage.jsonl`.**
      Стоимость RC **не видна** в `usage`. В E2E мы это **искали**
      и **не нашли** — полчаса на разгадку.
      **Фикс:** добавить `append_usage` в `run_reverse_check`
      (с `parent_action="reverse_check"`).
      **Файл:** `ai_coder/agent/reverse.py`.
      **Приоритет:** 🟡 средний (наблюдаемость).

### Расширить `--reverse-check` на chain

- [ ] **`--reverse-check` не работает с `--chain`.** Каждая задача
      chain — отдельный tool-loop, RC **доступен**.
      **Фикс:** прокид `reverse_check` в `_run_chain`.
      **Приоритет:** 🟡 средний.

### Унификация `--reverse-check` везде

- [ ] **Идея:** один флаг `--reverse-check` для **всех** режимов
      (`tool-loop`, `decompose`, `chain`, `plan`). Обсудить
      семантику (RC per подзадача vs per задача).
      **Приоритет:** 🟢 низкий (архитектурный вопрос).

---

### usage: `--by-action` не существует

- [ ] **Наш ТЗ упоминал `usage --by-action`, но такого флага нет.**
      У команды `usage` есть только `--action` (для фильтра).
      **Найдено** dsh при задаче D2.
      **Решение:** или добавить `--by-action` (алиас/таблица),
      или исправить доку (в `docs/cli/usage.md`).
      **Приоритет:** 🟢 низкий.

### usage: пути (CWD vs project_root)

- [ ] **Pre-existing баг:** `usage` читает `Path(cfg.usage.jsonl)`
      **относительно CWD**, а `append_usage` пишет **относительно
      `project_root`**. При `--config` и CWD ≠ корень проекта —
      статистика расходится.
      **Найдено** dsh при задаче D2.
      **Решение:** читать `usage.jsonl` относительно `--path` (target),
      не CWD.
      **Файл:** `ai_coder/cli.py` (функция `usage_show`).
      **Приоритет:** 🟡 средний (баг наблюдаемости).

### decompose: планировщик создаёт verify-подзадачи

- [ ] **E2E feedback loop:** v4-pro планировщик создал 3-ю
      подзадачу «Запустить тесты и убедиться, что test_sub проходит»
      (verify по сути). `run_tool_loop(step_type="edit")` требует
      `applied_ops > 0` — verify **ничего не правит** →
      `success=False` → retry v4-pro → тоже fail.
      **Фикс (варианты):**
      - в промпте `agent_decompose_json` — **запретить** verify-шаги;
      - `run_tool_loop` — поддержать `step_type="verify"` (только
        `run_shell`, `applied_ops` не требуется);
      - `_resolve_subagent` — для `type="verify"` использовать
        flash + step_type="verify".
      **Файлы:** `config/prompts.yaml` (промпт),
      `ai_coder/agent/decomposer.py`, `ai_coder/agent/tool_loop.py`.
      **Приоритет:** 🔴 высокий (ломает decompose при verify-шагах).

## Из GUI A.0/A.1 (сессия 2026-10-13)

- [x] **Агент пишет под устаревший API библиотек.** ЗАКРЫТО 10.39:
      правило 10 в `agent_tool_json`. Smoke-тест — TODO.
      FastAPI 0.143 в проекте, агент написал
      `TemplateResponse("index.html", {"request": request})` (API <0.108).
      Падало с HTTP 500 на `GET /`. `py_compile` и `pytest` не ловят.
      **Фиксы:**
      - В промпт `agent_tool_json`: «перед использованием API библиотеки —
        посмотри версию в pyproject.toml/requirements.txt».
      - Smoke-тест в verify для веб-задач:
        `python -c "from ai_coder.gui.app import app; ..."`.
      - Флаг `--verify-url http://localhost:8000/` — после finish дёрнуть URL.
      **Приоритет:** 🟡 средний.

- [x] **`success=False` при частичном применении плана.** ЗАКРЫТО 10.39:
      `ToolLoopResult.warnings` + CLI + report.md.
      A.0: агент создал 5 файлов из 6 (pyproject.toml в blacklist),
      но `success=False, stopped_reason="completed"`. Вводит в заблуждение.
      **Фикс:** статус `partial` (когда `applied_ops > 0` и есть отклонённые
      операции), или `success=True, warnings=[...]`.
      **Приоритет:** 🟡 средний.

- [x] **`python-multipart` — не в зависимостях.** ЗАКРЫТО 10.39:
      правило 9 в `agent_tool_json`.
      FastAPI >=0.113 требует `python-multipart` явно для `Form(...)`.
      Агент использовал `Form`, но не добавил зависимость.
      При импорте `app.py` — `RuntimeError` на `@app.post("/build")`,
      uvicorn завис.
      **Фиксы:**
      - Промпт `agent_tool_json`: «если используешь Form/File в FastAPI —
        добавь python-multipart».
      - Smoke-тест в verify: `python -c "from ai_coder.gui.app import app"`.
      **Приоритет:** 🟡 средний.

---

## Из GUI — UX-проблемы (сессия 2026-10-15)

### Нет прогресс-бара при запуске

- [ ] При запуске долгих операций (`run suggest_improvements` —
      178 сек) **нет прогресс-бара** в GUI. Пользователь **не видит**:
      работает ли процесс, **завис** ли, **идёт** ли стрим.
      **Фикс:** индикатор прогресса (spinner / progress bar) на кнопке
      «Запустить» **до первого** SSE-сообщения. Показывать **время**
      выполнения (mm:ss).
      **Файлы:** `ai_coder/gui/templates/index.html`, `static/style.css`.
      **Приоритет:** 🟡 средний.

### Нет кнопки «Открыть отчёт» для `run`-действий

- [ ] После `run suggest_improvements` (или **любого** `run`-действия)
      в форме **нет** ссылки **«Открыть отчёт»** (в отличие от
      `agent`/`tool-loop`, где это есть после A.5).
      **Фикс:** после `/run` — **парсить** строку `Отчёт: <path>` из
      вывода и **показывать** ссылку на `/reports/<project>/<journal>`
      + кнопку **«Все отчёты»** (`/reports`).
      **Файлы:** `ai_coder/gui/templates/index.html`, JS-обработчик.
      **Приоритет:** 🟡 средний.

### Поле `--max-tokens` в форме

- [ ] `--max-tokens` **нет** в форме — только через `advanced_flags`.
      **Фикс:** добавить `<input type="number">` в форму (`model`-секция
      или отдельное поле). Select с типовыми значениями:
      **не задано / 40000 / 60000 / 80000 / 120000**.
      **Файлы:** `ai_coder/gui/templates/index.html`, `app.py`.
      **Приоритет:** 🟢 низкий.

### `--only-path` не сработал в GUI (для ревью ядра)

- [ ] При запуске `suggest_improvements` с `--only-path ai_coder/` (в
      `advanced_flags`) — v4-pro **не увидел** ядро (`agent/*.py`).
      Отчёт показал `budget: 64` — **много** файлов **отсеялись**.
      **Проверить:**
      - как **парсится** `--only-path` в `_build_command`;
      - **сколько** файлов **влезает** в `max_tokens` (по умолчанию
        из `config.yaml`);
      - **работает** ли `--only-path` **вообще** через GUI.
      **Обходной путь:** увеличить `--max-tokens` и/или явно указать
      `--only-path ai_coder/agent/ --only-path ai_coder/tools.py` и т.д.
      **Файлы:** `ai_coder/gui/app.py`, `ai_coder/scanner.py`.
      **Приоритет:** 🟡 средний (без него ревью **неполное**).

### `--max-cost-rub` не вставляется для `run`

- [x] **Отдельный** пункт — **10.67** (в разделе 🟡 Среднее).
      **Связано** с UX-проблемами GUI. **Обходной путь:**
      `agent --tool-loop --max-cost-rub N`.
      **См.** `docs/cli/actions-run-fix.md` → примечание про
      `--max-cost-rub`.


---

## Из v4-pro-ревью ядра (2026-10-15, 3.99 RUB)

Ревью после split-file 10.65. Отчёт: `docs/reviews/v4-pro-2026-10-15-core.md`.
Из 10 находок — 8 подтверждены, 2 отклонены (проверено кодом).

### 🟡 `run_verify_commands` — `python -c` разрешён

- [ ] Blacklist `_VERIFY_FORBIDDEN_COMMANDS` проверяет **только первый
      токен**. `python`/`python3`/`pip`/`bash` — **разрешены**. Через
      `python -c "..."` — произвольный код.
      **Контекст:** `verify_commands` — из `config.yaml` или
      `--verify-commands` CLI (задаёт **пользователь**, не LLM). **Не
      RCE-вектор** напрямую, но **защита в глубину**.
      **Фикс:** запретить `python`/`python3`/`pip`/`bash`/`sh` с
      `-c`/`-e`, или проверять все токены на опасные флаги.
      **Файл:** `ai_coder/apply.py`, `run_verify_commands`.
      **Приоритет:** 🟡 средний.

### 🟡 `_handle_finish` — бессмысленное условие

- [ ] `if ctx.success and action.tool not in ("read_file", ...)` — при
      `finish` `action.tool == "finish"` — условие **всегда true**.
      **Фикс:** упростить или убрать.
      **Файл:** `ai_coder/agent/tool_loop.py`, `_handle_finish`.
      **Приоритет:** 🟢 низкий.

### 🟡 `parse_response` — хрупкий парсер markdown

- [ ] `parse_response` режет ` ``` ` по **первой/последней** строке.
      **Ломается**, если внутри JSON есть ` ``` `.
      **Фикс:** regex по первой `{` / последней `}`.
      **Файл:** `ai_coder/apply.py`, `parse_response`.
      **Приоритет:** 🟡 средний.

### 🟡 Дублирование LLM-запроса (10 мест)

- [ ] Копипаста: `is_peak_now` → `LLMClient` → `chat` →
      `calculate_cost` → `append_usage`. **Фикс:** вынести
      `_call_llm_and_charge(...)` в `ai_coder/llm.py`.
      **Файлы:** `ai_coder/agent/planner.py`, `classic.py`,
      `decomposer.py`, `autofix.py`, `tool_loop.py`.
      **Приоритет:** 🟡 средний.

### 🟡 Локальные импорты для обхода циклов

- [ ] `classic.py` — `from ..actions import run_fix_action` **внутри**
      функции. **Симптом** циклической зависимости.
      **Фикс:** выделить `run_fix_action` в `ai_coder/fixers.py`.
      **Файл:** `ai_coder/agent/classic.py`.
      **Приоритет:** 🟡 средний.

### 🟢 `planner.py` — размытая ответственность

- [ ] `planner.py` (1021) содержит парсеры + LLM-запросы + slug + кэш
      + оценку. **Фикс:** `planner.py` + `parsers.py`.
      **Приоритет:** 🟢 низкий.

### 🟢 Ручное `__all__` в `agent/__init__.py`

- [ ] Хрупко — легко забыть. **Фикс:** автогенерация через обход
      `__all__` модулей.
      **Файл:** `ai_coder/agent/__init__.py`.
      **Приоритет:** 🟢 низкий.

### 🟢 `tool_loop.py` — дальнейшее разбиение

- [ ] 31k символов. Кандидат на `ToolLoopSession`, `Journal`,
      `BackupManager`.
      **Приоритет:** 🟢 низкий.

### 🟡 Тесты / CI

- [ ] **4.2** — интеграционные тесты циклов агента с моком LLM.
- [ ] **4.3** — тесты безопасности для `_safe_path`, `_validate_command`.
- [ ] **4.4** — тесты отката `apply_plan` и `rollback`.
- [ ] **6.5** — `bandit` (SAST) в CI.
      **Приоритет:** 🟡 средний.

### ❌ Отклонено (проверено кодом)

- **1.2 (пустые директории при откате)** — **ошибка v4-pro**:
      `created_dirs` **используется** в `rollback` (`apply.py:487-489`).
      Пустые каталоги **удаляются**.
- **1.3 (`llm=None` при phase1 cache hit)** — **ошибка v4-pro**:
      `phase1_result.llm` **не читается** с обращением к атрибутам.


---

## Из E11 (self-hosted провал) — 2026-10-11

- [x] **`applied_count == 0` + `apply=True` → `skipped`.** ЗАКРЫТО
      10.27. Оказалось — **ошибочный диагноз** (код уже корректен);
      реальный баг был в `subtask.success = loop.success`.
- [x] **`--chain`: `applied_count == 0` ≠ «✅ успех».** ЗАКРЫТО
      10.27: `ToolLoopResult.applied_ops` + фикс `run_agent_decompose`
      + `_run_chain` (основной и retry-пути — 10.28).
- [ ] **`--chain` журнал при провале.** Сейчас
      `.ai-out/<project>/chain-<ts>/` создаётся, но **пустой**, если
      все подзадачи упали. Писать `report.md` всегда.
- [x] **`ai-coder` console script.** ЗАКРЫТО 10.29: работает,
      `.venv/bin/ai-coder`, `pip install -e .` сделан.
- [ ] **Self-hosted рекомендации в docs/examples.md.**
      Для больших файлов (после split-file 10.65 — модули ≤1021 строк):
      - `--only-path ai_coder/agent/tool_loop.py`;  # был agent.py
      - `--max-iterations 15+`;
      - v4-pro вместо flash;
      - точная формулировка (файл + функция + строка).

---

## Из E12 (decompose в чужом проекте) — 2026-10-11

- [x] **`--no-verify` / `--verify-commands` для decompose/tool loop.**
      ЗАКРЫТО 10.29: `--no-verify` теперь отключает и `py_compile`,
      и `verify_commands`. `run_tool_loop`/`run_agent_decompose`
      принимают явный `verify_commands`.
      **Фикс:** прокинуть `verify` / `verify_commands` параметром в
      `run_agent_decompose` и `run_tool_loop`.
      Файлы: `ai_coder/agent/decomposer.py`, `ai_coder/cli.py`.

- [ ] **Verify на чужом проекте ломает прогон** (E12: `legacy/test_url.py`
      — фикстура `url` не найдена). Нужна возможность **указывать
      конкретный тест** или **исключать каталоги** из verify.

- [x] **Перезапуск E12.** ЗАКРЫТО 10.29: синтетическая верификация
      (E14) подтвердила фикс `--no-verify` на живом проекте.
      См. `docs/experiments.md` → E14.

- [x] **`max_iterations` из CLI не доходил** до decompose. ЗАКРЫТО 10.28.
- [x] **Retry-путь v4-pro не учитывал `applied_ops > 0`.** ЗАКРЫТО 10.28.

---

## 📝 Обзоры проекта (reviews)

- [v4-pro, 2026-10-07](docs/reviews/v4-pro-2026-10-07.md) — глубокий обзор `deepseek-v4-pro`.
  Найдены проблемы, которых не было в этом TODO: перепроверка плана при cache hit,
  content-level фильтрация секретов, O(N²) в usage, `rglob` без pruning, компиляция `PathSpec` на каждый файл.
  Приоритетные фиксы см. в самом review.
- **Закрыто из ревью:** 1.1, 1.2, 1.3, 1.4, 3.2 (хэш по отрендеренному промпту, 10.14.6), 5.2, 5.3.
  - 1.1–1.3 из review-2026-10-09-full закрыты 2026-10-10 (10.15, Сессия 1: security).

## 🔥 Автономность: shell-команды и tool loop
### Баги, обнаруженные при self-hosted E2E (2026-10-08)

- [~] **`max_output_tokens` для `agent_step_json` мало 8000.**
      ✅ Обход 10.66: `step_max_output_tokens: 8000 → 24000` в
      `config.yaml`. Подтверждено E30 (create_file 4752 символа).
      ❌ **Настоящий фикс не сделан:** JSON-обёртка `write_file`
      раздувает output в ~2× (4752 символа текста → ~14K токенов
      JSON). Даже 24000 — не панацея для файлов >6 KB.
      **Фикс:** (а) писать файлы без JSON-эскейпинга (инструмент
      `write_file_raw` с raw-блоками), или (б) разбиение
      `create_file` на append-чанки.
      и передавать в `_run_agent_step`.
- [ ] **`parse_error` и `problems` не различаются в сообщении.**
      Сейчас «План невалиден, применение отменено» — не ясно,
      JSON сломан или валидация. Нужно разделить.
- [ ] **Пустой план (`operations: []`) — не спрашивать интерактив.**
      **Фикс:** в `_run_agent_step` — если `not write_plan.operations`,
      не вызывать `_prompt_review`, сразу `skipped=True`.
- [ ] **Стоимость self-hosted E2E: 5.66 RUB.**
      Причина: контекст 45K токенов × 3 шага. Нужен
      селективный контекст (см. Уровень A+).

**Приоритет:** 🟡 средний.


### Уровень A+: селективный контекст для маленьких задач

**Проблема (обнаружено):** агент на **своём проекте** потратил
**1.21 RUB** за одну строку (правка `--cov-fail-under=40 -> 70`).
Причина — контекст **43K токенов** (весь проект).

**Решения:**

- [x] `--only-path <path>` — ограничить сканирование
      одним файлом/директорией (iteration 8.4).
- [x] Автоматический `--exclude` для задач, где цель упоминает
      конкретный файл (парсить `target_files` из плана) — iteration 8.5.
- [x] **8.6:** сужать контекст и для шага 1, если план одношаговый
      и `target_files` заполнены (iteration 8.6).
- [x] **Уровень A+ (продолжение):** инкрементальный контекст
      для планировщика — phase1 (iteration 8.7).
- [ ] Инкрементальный контекст: сначала план (по дереву),
      потом — только релевантные файлы.
- [ ] Файлы `.github/**`, `.gitlab/**` — низкий вес (20)?

**Приоритет:** 🟡 средний. Обнаружено на self-hosted E2E.



**Цель:** ускорить разработку — агент **сам запускает команды**
(pytest, ruff, mypy, git) и **чинит по выводу**. Человек — только
подтверждает и ревьюит.

### Уровень A: verify_commands (сделано, iteration 8.0)

- [x] `agent.verify_commands` из `config.yaml` через subprocess.
- [x] `run_fix_action` видит вывод команд (pytest/ruff/mypy).
- [x] Флаг CLI `--verify-commands "pytest -q;ruff check ."`.
- [x] Whitelist, timeout (60 сек), лимит вывода (10K).
- [x] Тесты `test_run_verify_commands_*` (4).
- [x] Проверено E2E: агент сам чинит по pytest.

**Что это даст:** агент правит код, запускает `pytest`, если упал —
**сам чинит** до N попыток. Если не смог — откат.

### Уровень B: --interactive (сделано, iteration 8.1)

- [x] Флаг `--interactive` в `agent`: diff + `y/n/a/s/d`.
- [x] «Принять все» (`a`), «skip» (`s`), «diff» (`d`).
- [x] Решения логируются в журнал.

### Уровень C: tool loop (сделано, iterations 9.1–9.4)

- [x] Промпт `agent_tool_json`, парсер `parse_tool_action`.
- [x] 5 инструментов: `read_file`, `list_files`, `write_file`,
      `edit_file`, `run_shell`.
- [x] Whitelist shell: pytest, ruff, mypy, git status/diff/log,
      ls, cat, grep, find, head, tail, wc, `python -m pytest|ruff|mypy`.
- [x] Запрет метасимволов (`;`, `&`, `|`, `<`, `>`, `$`).
- [x] Цикл `run_tool_loop`: LLM → инструмент → результат → LLM.
- [x] CLI: `--tool-loop`, `--max-iterations`, `--dry-run`, `--interactive`.
- [x] Безопасность: `--dry-run`, `--interactive`, бэкап перед первым изменением.
- [x] Совместимость с `ai-coder rollback` (манифест 1-в-1).
- [x] 25 + 22 + 24 + 9 = ~80 тестов.
- [x] E2E: `--dry-run` 2 итерации 0.039 RUB, `--interactive` 5 итераций 0.088 RUB, rollback работает.

### Уровень D: полная автономность (неделя+)

- [x] **D.1 (частично):** автокоммит после `finish(success=true)`
      (iteration 10.1). Флаг `--commit` для tool loop.
- [x] **D.1.5:** `--resume` для tool loop (10.2) — продолжение прерванного.
- [x] **D.1.6:** кэш phase1 (10.4) — экономия ~0.03 RUB на задаче.
- [ ] **D.2:** ветка `ai-coder/<slug>-<ts>` перед tool loop (отложено).
- [ ] **D.3:** push ветки + PR через `gh` CLI (отложено).
- [x] **D.4:** `--max-cost-rub` для tool loop — ✅ проверено 2026-10-15: precheck (10.54) работает, 6 тестов зелёные. См. TODO 8.5.
- [ ] **D.5:** MCP-интеграции (опционально).
- [ ] **D.6:** multi-turn задачи (агент уточняет у пользователя).

**Приоритет:** 🔴 высокий (стратегическое направление).

**Начать с:** Уровень A — `verify_commands`. **2 часа**, максимум пользы.

---

## 🔥 Срочное / дешёвое (сделать в первую очередь)

### Агент: честность про пустые шаги

- [ ] Помечать `applied_count == 0` как `skipped`, а не «применено».
      Если `apply_plan` вернул пустой список без ошибок — это не успех, а
      отсутствие работы. Не запускать verify, не считать шаг выполненным.
      Файл: `ai_coder/agent/classic.py`, `_run_agent_step`.

### README

- [x] README пересобран через `write_readme` / `deepseek-v4-pro`.
- [ ] Добавить разделы: «Конфигурация», «Agent-режим», «Безопасность», «Тестирование».
      Можно взять из `README.md.broken` (если ещё сохранился) или восстановить из git-истории.

---

## 🔥 Агент: правки итерации 6.5

- [x] Показывать количество операций в CLI-выводе шага агента.
- [x] Помечать пустой план внутри шага как `skipped`.
- [x] Отличать «план пуст» (`empty_plan`) от «ошибка парсинга».
- [x] Фильтровать диагностические шаги в `parse_agent_plan`.
- [x] **3.5** — в preview помечать пустой план как `skipped` (сделано в 7.1)
      `applied=False` для всех, непонятно почему).
- [ ] **3.6** — preview не должен делать LLM-запрос на каждый шаг
      (сейчас 6 шагов x 50K токенов = ~11 RUB).
      Варианты: только первый шаг; `--preview-only` (только план);
      оценка через логику `--dry-run`.
- [x] **3.7** — флаг `--preview-only`: только план и оценка, без шагов.

---

## 🔴 Сканер: пустые файлы, приоритизация, вёрстка

**Обнаружено на `lichess_db_project`** (74 файла, ~100K токенов).

**Проблема:** алфавитный обход даёт **неправильный приоритет**.
В контекст попадают **пустые `__init__.py`** и **вспомогательные
скрипты** (`scripts/01_*.py`), а `services/`, `web_app/`,
`README.md` — обрезаются первыми.

**Что модель сделала правильно:** обнаружила отсутствие
`services/lichess_client.py` по импортам и **явно указала**
на пробел. Не выдумывала. Промпт `greet` работает даже
на частичном контексте.

**Решения (приоритет):**

- [ ] **1.** Пропускать **пустые файлы** (`size == 0`)
      и мелкие `__init__.py` (< 50 байт).
      **Эффект:** -5–7 файлов. **~15 минут.**
- [ ] **2.** **Приоритизация обхода:**
      - точки входа (`main.py`, `app.py`, `wsgi.py`, `run_*.py`);
      - пакеты (`core/`, `src/`, `services/`, `web_app/`, `api/`);
      - конфиги (`config/`);
      - метаданные (`README.md`, `pyproject.toml`, `requirements.txt`);
      - **в конце** `tests/`, `scripts/`, вёрстка (`.html`, `.css`, `.js`).
      **~1 час.**
- [ ] **3.** **Авто-исключение вёрстки** для `greet`/`inventory`
      (`.html`, `.css`, `.js`, `.svg`). **~30 минут.**
- [ ] **4.** **Флаг `--include <glob>`** — противоположность `--exclude`.
      **~30 минут.**
- [ ] **5.** **Предупреждение в консоли** при `truncated=True`
      («обрезано N файлов — часть проекта не попадёт в контекст»).
      **~15 минут.**
- [ ] **6.** **Двухпроходная схема** для больших проектов
      (разбить по директориям, N запросов). **~2 часа.**

---

## 🟡 Среднее (полезно, но не срочно)

### Агент: поддержка read-шагов

- [ ] Явно поддержать `type: "read"` в плане.
      Read-шаг: LLM получает контекст + вопрос, возвращает свободный текст
      (не JSON-операции). Результат пишется в журнал как `step-N.md`,
      но не применяется.
      Файлы: `ai_coder/agent/classic.py` (`AgentStep.type` — в models.py, `_run_agent_step`),
      `config/prompts.yaml` (`agent_read_json` или `agent_read_text`).

### Агент: verify-команды

- [ ] Подключить `agent.verify_commands` к циклу шага.
      Поле уже есть в `config.yaml`, но не используется.
      Логика: после `apply_plan` запустить команды в `project_root`,
      stderr / non-zero exit → `verify_errors`.
      Примеры для config.yaml:
      - "python -m pytest tests/ -q"
      - "ruff check ."
      Файлы: `ai_coder/agent/classic.py`, `ai_coder/config.py`.

- [ ] Отказ агента от задач без верификации.
      Если `verify_commands` пуст, а действие — не .py-правка,
      честно сказать: «не могу проверить результат» и остановиться.
      Опционально, под флагом `--strict-verify`.

### `run` не поддерживает `--max-cost-rub` (10.67)

- [ ] У `agent`/`fix` — есть, у `run` — **нет** (by design: `run` —
      один запрос, стоимость предсказуема ~0.05–0.4 RUB). **НО:** для
      дорогих `run`-запросов (`--depth deep`, `--model v4-pro`,
      весь проект) — лимит **полезен**.
      **GUI** — **правильно** не вставляет `--max-cost-rub` в ветку
      `run` (`ai_coder/gui/app.py:86-88` — комментарий «у команды run
      нет флагов --max-cost-rub и --commit»).
      **Что делать (если нужно):**
      1. `cli.py` — параметр `--max-cost-rub` для `run`.
      2. `actions.py` — precheck через `_estimate_next_cost_rub` **до**
         запроса + post-check после.
      3. `gui/app.py` — включить `--max-cost-rub` в ветку `run`.
      **Файлы:** `ai_coder/cli.py`, `ai_coder/actions.py`,
      `ai_coder/gui/app.py`.
      **Обходной путь:** `agent "<goal>" . --tool-loop --max-cost-rub N`.
      **Приоритет:** 🟢 низкий.


---

## Кэш и парсинг

- [x] **3.2** — `run_fix_action`: хэш по отрендеренному промпту,
      а не по синтетической склейке шаблона (10.14.6).
- [ ] Сохранять сырой JSON рядом с отчётом отдельным файлом.
      Сейчас сырой ответ — внутри MD в `<details>`. Для программного
      доступа к нему приходится парсить markdown. Писать `.raw.json`
      рядом с `.md` при `save_raw_response: true`.
      Файл: `ai_coder/output.py`.

---

## Действия

- [ ] Новое действие `fix-readme` (markdown-linter + fix).
      Аналог нашей разовой задачи: принять файл, вернуть исправленную
      разметку, но не через JSON-план, а как свободный текст.
      Режим: `read` (предложение), `--apply` — записать файл.
      Файлы: `config/prompts.yaml` (`fix_readme_text`),
      `config/config.yaml` (действие),
      `ai_coder/actions.py` (поддержка режима «замена файла целиком»).

- [x] Новое действие `explain <file>` (10.14.10).
      Объяснить файл / функцию / класс. Режим `read`.
      **Написано агентом** через tool loop: 4 итерации, 0.31 RUB.
      YAML-стресс пройден (см. `docs/experiments.md`).

- [ ] Новое действие `suggest-tests`.
      Предложить юнит-тесты для модуля. Режим `write`.

---

## 🟢 Инфраструктура

### CI

- [x] GitHub Actions: pytest + ruff + mypy на push и PR (5 jobs: pytest x3, ruff, mypy).
      Файл: `.github/workflows/test.yml`.
      Быстрая матрица: `python-version: ["3.10", "3.11", "3.12"]`.
      Кэш зависимостей через `actions/setup-python@v5` с `cache: pip`.

- [x] Бейдж CI в README. (сделан ранее, найден в E11)

### Типизация

- [ ] Прогнать `mypy --strict` на `ai_coder/` и устранить ошибки.
      Проверить `pyproject.toml`, добавить секцию `[tool.mypy]`.

- [ ] Прогнать `ruff check --fix` и `ruff format`.

---

## 🔵 Будущее (крупные фичи)

### Git-интеграция

- [x] Проверка `git status --porcelain` перед `--apply` (8.8).
- [x] Автокоммит после успешного `--apply` (флаг `--commit`, 8.8).
      Шаблон: `ai-coder: <goal> (N ops, X.XX RUB)`.
- [x] `--max-cost-rub N` — остановка при превышении бюджета (8.8).
- [ ] Ветки `ai-coder/<action>-<ts>` перед `--apply` (отложено — одна `main`).
- [ ] Команда `ai-coder diff` — сравнить текущее состояние с HEAD.

### Agent v2

- [ ] Разбиение задач по файлам. Если цель касается одного файла —
      сузить контекст до него и его соседей.
- [ ] Продолжение прерванного агента с шага N.
      Сохранять состояние в журнале, флаг `--resume <journal-dir>`.
- [ ] Интерактивный режим `--interactive`.
      Подтверждение каждого шага вручную.
- [x] `--max-cost-rub N` — ✅ проверено 2026-10-15: precheck (10.54) в tool loop + planner, post-check в auto-fix/decompose. См. TODO 8.5.
- [ ] Планировщик умеет `read` + `edit` + `verify` как отдельные типы.
- [ ] Оценка плана до запуска: «шагов: 5, ожидаемая стоимость: ~2 ₽».

### Улучшения промптов

- [ ] Параметризовать стиль докстрингов (`--style google|sphinx|numpy`)
      в `add_docstrings`.
- [ ] Стиль README (`--style short|full`) в `write_readme`.
- [ ] Разные промпты для разных языков (locale) — сейчас всё на русском.

### Мультипроектность

- [ ] Команда `ai-coder scan <dir>` — обзор нескольких проектов сразу.
- [ ] Общий `usage.jsonl` по всем проектам (уже есть),
      но CLI-вывод по всем проектам сразу.

### Модели

- [ ] **Reasoning logging.** Читать `reasoning_content` из ответа LLM.
      Добавить в `LLMResponse.reasoning_content: str = ""`.
      Логировать в `step-N.md` (в `<details>`).
      См. `docs/thinking-mode.md` -> «Что взять».
- [ ] **`reasoning_tokens` — наблюдение.** Читать
      `usage.completion_tokens_details.reasoning_tokens`, логировать
      в `usage.jsonl`. В `ai-coder usage` — колонка «reasoning %».
- [ ] **`reasoning_effort` — флаг.** Параметр в `LLMClient.chat` +
      config (`agent.reasoning_effort`) + CLI (`--reasoning-effort
      low|high|max`). Для простых задач (`greet`, `inventory`) — `low`.
- [ ] **`--no-thinking` — toggle.** Флаг в CLI ->
      `extra_body={"thinking": {"type": "disabled"}}`. Для простых
      задач — не тратить output на reasoning.

- [ ] Автоматический выбор модели по размеру задачи.
      Если prompt-токенов < 20K → `flash`, иначе → `v4-pro`.
      Или по типу действия: `write_readme` → `v4-pro`, `greet` → `flash`.
- [ ] Проверка `finish_reason` в `run_planner` и `_run_agent_step`.
      Если `length` — не парсить, останавливаться с предупреждением.

---

## ⚫ Известные проблемы / баги

### Форматы

- [ ] `Path.is_relative_to` требует Python 3.9+. В `cli.py` есть места,
      где это используется без fallback. Проверить совместимость с 3.10.
- [ ] `json.tool` не читает JSONL. Не наш баг, но документация
      должна предупреждать: `usage.jsonl` — не `json.tool`, читать через
      `jq` или свой скрипт.

### Мелочи

- [ ] `_render_write_section` в `output.py` упоминает «в следующих версиях» —
      устарело, уже работает `--apply`.
      Проверить, поправлено ли. Если нет — поправить.
- [ ] Дубликат коммита `5bac4f3` / `5fb5b8c` — «iteration 5» дважды.
      Не критично, но при случае — squash.
- [x] **Verify: pytest `exit 5` (no tests) — не ошибка.**
      ✅ ЗАКРЫТО 10.46: в `run_verify_commands` — если команда
      `pytest` (или `python -m pytest`) и `returncode == 5` —
      **пропускаем** (не ошибка). Покрыто тестами.
      См. `docs/experiments.md` → E20/E22.
- [ ] ✅ ЗАКРЫТО 2026-10-15 (8.5): **`--commit` ломает reverse-ch...
      В `tool_loop.py` при `--commit`: сначала `git commit` (строка ~662
      в `_tool_loop_finalize`), потом `_collect_diff` (`git diff HEAD`) —
      пусто → reverse-check пропускается.
      **НЕ путать с E26-a** (untracked): это исправлено (коммит `00319df`).
      **Фикс:** брать diff из последнего коммита агента (`git show HEAD`
      или `git diff HEAD~1`) или делать `_collect_diff` **до** `--commit`.
      **Файл:** `ai_coder/agent/tool_loop.py`, `_tool_loop_finalize`.
      **Приоритет:** 🟡 низкий.
      **Фикс:** брать diff из истории tool loop
      (`write_file`/`edit_file` в `history`), а не из git.
      Файл: `ai_coder/agent/reverse.py`, `_collect_diff`.
      **Приоритет:** 🟡 средний.

---


### 24. Tool loop: флейки `missing 'path'` в edit_file — ✅ решено (10.14.26)

- [x] **E26-a: reverse-check не видит untracked.** ЗАКРЫТО 2026-10-14:
      `_collect_diff` включает untracked через `git status --porcelain`.
      Коммит `00319df` (+ тесты `1480bce`, E26-b).
- [x] **Проблема:** flash-модель 5× вернула `edit_file` с пустым args.
- [x] **Фикс (промпт):** правило 12 — добавлен случай `missing 'path'`.
- [x] **Фикс (код):** retry — при пустом args не считать итерацию
      (max_arg_retries=3, код 10.14.26).
- [x] **E2E:** flash v2 — 9 итераций, 0 флейков, ✅ (было 20 / 7 / ❌).
- **Приоритет:** 🟢 закрыто.

### 25. Tool loop: правило 12 не покрывает пустой args — ✅ решено (10.14.26)

- [x] **Проблема:** правило 12 не покрывало `missing 'path'`/`'old'`/`'new'`.
- [x] **Фикс:** правило 12 расширено — явные случаи.
- **Приоритет:** 🟢 закрыто.
## 📚 Документация

- [ ] Docstrings на все публичные функции в `ai_coder/`.
- [ ] `docs/architecture.md` — подробное описание потоков и решений.
- [ ] `docs/prompts.md` — как писать свои промпты и действия.
- [ ] `docs/troubleshooting.md` — частые проблемы:
      `finish_reason: length`, cache miss, invalid JSON, blacklist и т.п.
- [ ] Примеры в `examples/` — sample-проекты и команды.
## 🧪 Тесты (что ещё стоит покрыть)

- [ ] `test_output.py` — рендер отчёта, шапка, warning про `length`.
- [ ] `test_prompts.py` — `render_prompt`, `validate_prompt_vars`.
- [ ] `test_usage.py` — `append_usage`, `_rebuild_summary`.
- [ ] `test_cli.py` — через `typer.testing.CliRunner`:
      `actions`, `actions --verbose`, `run --dry-run`, `usage`.
- [ ] `test_agent.py` — расширить: `run_agent` с моком LLM,
      `_run_agent_step` с реальным `apply_plan` + мок LLM.
- [ ] E2E-тест через subprocess: запуск CLI на временном проекте.

---

## 💡 Идеи «на подумать»

- [ ] Интеграция с IDE — LSP-плагин или простой HTTP-сервер для Cursor/VS Code.
- [ ] Локальные модели — поддержка Ollama / llama.cpp как альтернативы DeepSeek.
- [ ] Пакет в PyPI — публикация wheel, чтобы `pip install ai-coder`.
- [ ] Web-интерфейс — минимальная панель для просмотра отчётов и usage.
- [ ] Плагины действий — загрузка из `~/.ai-coder/actions/`.
- [ ] Diff-режим для write-действий: показывать только изменения,
      не всё содержимое файла.
- [ ] Инкрементальный анализ — только изменённые с последнего запуска файлы.
- [ ] «Запомнить» состояние проекта — кэш `greet` как контекст
      для следующих действий (прототип «памяти» Cursor).

---

## Легенда приоритетов

- 🔥 — сделать в ближайшее время (день-два).
- 🟡 — полезно, но не срочно (неделя-две).
- 🟢 — инфраструктура (когда есть время).
- 🔵 — крупные фичи (месяц+).
- ⚫ — известные проблемы (чинить по мере обнаружения).
- 📚 — документация.
- 🧪 — тесты.
- 💡 — идеи для будущего.

---

## 🔥 Итерации 10.1–10.4 (сделано)

### Tool loop — автономность

- [x] **10.1** — автокоммит после `finish(success)` для tool loop.
- [x] **10.2** — `--resume <journal-dir>` — продолжение прерванного loop.
- [x] **10.4** — кэш phase1 (`use_cache=True`, `refresh=False`).
- [x] **10.5** — промпт + `format_tool_history` (5 → 2 итерации).

### Сделано (10.13–10.14)

- [x] **10.13** — verify_commands после `finish` в tool loop.
- [x] **10.14.1** — `run_auto_fix` — цикл verify → fix.
- [x] **10.14.2** — CLI-команда `fix`.
- [x] **10.14.3** — 3 теста `run_auto_fix`.

### Что осталось (10.x продолжение)

- [ ] **10.3** — оценка стоимости tool loop после каждой итерации.
- [ ] **10.6** — read-шаги в `run_agent` (`type: "read"`).
- [ ] **10.7** — UX resume: общая стоимость (сессия 1 + 2).
- [ ] **10.8** — обрезка в `format_tool_history` для больших файлов
      (> 3000 символов) — пометка «[см. step-N.md]».

---

## 🔥 Известные проблемы tool loop (обнаружены 2026-10-08)

**Контекст:** пытались попросить агента сделать 3 точечные правки
в `docs/tools.md` (заменить `transcript.jsonl` на `history.json`
в 2 местах, `ai_coder/config.py` на `ai_coder/tools.py`).
**Агент не справился за 3 запуска.** Разбор:

### 1. Backticks в bash-промпте съедаются — ✅ решено (10.10)

- [x] **Проблема:** если в промпте к `agent` есть backticks,
      bash выполняет содержимое как **command substitution**.
- [x] **Фикс (документация):** раздел «Как формулировать задачу
      агенту» в `docs/tools.md`.
- [x] **Фикс (код):** предупреждение в CLI, если в `goal` есть
      обратные кавычки.
- **Приоритет:** 🟢 закрыто.

### 2. `--dry-run` ломает логику при нескольких правках

- [ ] **Проблема:** в `--dry-run` `edit_file` **не меняет** файл.
      Модель видит **тот же контент** → думает «не сработало» →
      **перечитывает** → снова `edit_file` → `max_iterations`.
- [ ] **Фикс (документация):** в `docs/tools.md` — явное
      предупреждение: «`--dry-run` — **только предпросмотр**.
      Для реального выполнения — **без флага**».
- [ ] **Фикс (код):** при `--dry-run` — **изменять** виртуальный
      файл в памяти (модель видит результат симуляции). Сложно.
- **Приоритет:** 🟡 средний.

### 3. `format_tool_history` обрезает `read_file` до 3000 символов — ✅ решено (10.8)

- [x] **Проблема:** файл `docs/tools.md` — **~8000 символов**.
      `read_file` возвращает всё (50K лимит), но `format_tool_history`
      показывает в **истории** только **3000 символов**.
- [x] **Фикс:** `AgentConfig.tool_loop_history_max_chars = 10000`
      (конфигурируемо).
- [x] **Фикс:** при обрезке — пометка «Используй `run_shell grep`
      для точного поиска».
- [x] **E2E:** было 15 итераций / 1.82 RUB / ❌ неуспех,
      стало **1 итерация** / 0.10 RUB / **✅ успех**.
- **Приоритет:** 🟢 закрыто.

### 4. Промпт: нет правила для `'old' not found` — ✅ решено (10.8)

- [x] **Проблема:** в `agent_tool_json` не было правила для
      `'old' not found`.
- [x] **Фикс:** правило 12 в `agent_tool_json` —
      при `'old' not found` использовать `grep`, не повторять edit.
- **Приоритет:** 🟢 закрыто.

### 5. Flash-модель игнорирует правила при сложных задачах

- [ ] **Наблюдение:** `deepseek-flash` соблюдает правила 1–11,
      но **игнорирует** их, когда задача **кажется сложной**
      (3 правки + big file). Использует `read_file` × 5.
- [ ] **Фикс (документация):** в `docs/tools.md` — рекомендация:
      «для задач **>2 правок** используй `deepseek-v4-pro` или
      разбивай на несколько запусков».
- [ ] **Фикс (код):** автоматический выбор модели по сложности
      задачи (TODO `### Модели`).
- **Приоритет:** 🟡 средний.

### 6. Вывод: tool loop — не для всего

- [ ] **Наблюдение:** для **3 точечных замен** Python/sed **лучше**:
      - **30 секунд** вместо 5 минут;
      - **0 RUB**;
      - **точно**.
- [ ] **Фикс (документация):** в `docs/tools.md` — раздел
      «Когда использовать tool loop»:
      - **Используй:** для создания файлов, рефакторинга,
        задач с анализом (read → edit → verify).
      - **Не используй:** для 1–3 точечных замен (`sed` быстрее).

### 7. `--dry-run` + многошаговые задачи = зацикливание

- [ ] **Проблема:** в `--dry-run` `edit_file` **не меняет** файл.
      Модель видит **тот же контент** → **перечитывает** →
      зацикливается (14 `read_file` подряд на задаче про 10.8).
- [ ] **Наблюдение:** `--dry-run` подходит **только** для **1-2 итераций**.
- [ ] **Фикс (документация):** в `docs/tools.md` и `README.md` —
      предупреждение: «`--dry-run` — предпросмотр **первых шагов**.
      Для многошаговых задач — **без dry-run** или Python-скрипт».
- **Приоритет:** 🟡 средний.

### 8. Агент не справляется с задачами на 5+ файлов

- [ ] **Проблема:** задача 10.8 (6 файлов, 5 правок, 3 теста) —
      модель **зациклилась** на 15 итераций, **0 правок**.
- [ ] **Наблюдение:** flash-модель **теряет фокус** при **>2 файлах**.
- [ ] **Фикс (документация):** правило — «для задач >2 файлов —
      разбивать на несколько запусков или использовать Python-скрипт».
- [ ] **Фикс (код):** автовыбор модели по сложности (TODO `### Модели`).
- **Приоритет:** 🔴 высокий.

### 8.7. Precheck бюджета — ✅ ЗАКРЫТО 2026-10-15 (10.69)

**8.7B — ✅ ЗАКРЫТО 2026-10-15 (4965dcb):**
оценка `_estimate_next_cost_rub` по типу инструмента
(`last_tool`). Формула: read=500, edit=2000, write=8000,
run_shell=300, default=500. E37.

**✅ Закрыто 10.69:** последняя итерация завершается (verify + finish),
если остаток > 0. Helper `_stop_on_last_iteration`.

**Историческое (2026-10-15, E30/E31/E32):** precheck останавливал
**после** применения правок, но **до** `finish` и **verify**.
Симптом: пользователь видит «❌ неуспех», а на диске — полуготовый
файл с неотverifyенными правками. Три случая за день.

**Фикс:** дать **последней итерации** завершиться полностью
(`finish` + verify), даже если бюджет чуть превышен (например,
+20%). Остановка — **перед** следующей итерацией, не **после**
текущей. Или явно помечать: «частичный результат, verify не выполнен».


- [ ] **Проблема:** precheck (`_estimate_next_cost_rub`) оценивает
      «следующую итерацию» через `max_output_tokens // 2`, не
      учитывая **тип предстоящей операции**. `read_file` дёшев
      (~0.05 RUB), `edit_file`/`write_file` дороги (1.5–6 RUB).
- [ ] **Симптомы (2026-10-15):**
      - **E30:** create_file символов, `--max-cost-rub 5.0`,
        фактически **5.92 RUB** (write_file 14K output-токенов).
      - **E31:** edit_file tools.py, `--max-cost-rub 4.0`,
        остановлен **на полпути** (3.49 + оценка 1.15 > 4.00),
        2 из 6 правок сделаны.
      - **E26-a:** три задачи по 0.47/0.85/0.68 при лимите 2.0 —
        не сработал, потому что **суммарно меньше** (не баг).
- [ ] **Фикс:** оценка через **тип предстоящего инструмента**
      (model prediction) + **размер контекста**. Для write_file —
      оценка по длине content (если передаётся), или по среднему
      размеру подобных файлов в проекте.
- [ ] **Альтернатива:** дать «последнюю итерацию» дойти до конца,
      если остаток > 0 (не рубить на полпути).
- **Файл:** `ai_coder/agent/tool_loop.py`, `_estimate_next_cost_rub`
  (в `planner.py`? — уточнить).
- **Приоритет:** 🟡 средний (не блокирует, но мешает).

---

### 8.6. `_MAX_DIFF_CHARS` — хардкод в reverse.py

- [ ] **Проблема:** `_collect_diff` использует `_MAX_DIFF_CHARS = 15000`
      (константа модуля), а `run_reverse_check` — `cfg.agent.reverse_check_max_diff_chars`
      (конфиг). Если конфиг изменить — `_collect_diff` всё равно обрежет по 15000.
- [ ] **Фикс:** передавать `max_chars` параметром в `_collect_diff`
      (из `cfg.agent.reverse_check_max_diff_chars`). Сигнатуру менять,
      значит вызовы в `run_tool_loop` тоже.
- **Приоритет:** 🟡 низкий.
- **См.** `docs/experiments.md` → E26 (задача a).

### 8.5. `--max-cost-rub` — ✅ ЗАКРЫТО 2026-10-15 (проверено)

- [x] **Фикс 10.54** (precheck в tool loop + planner): 6 тестов зелёные,
      `client.chat.call_count == 0` при крошечном лимите.
- [x] **E25** (2.28 RUB при лимите 1.0) — **старый** баг, закрыт в 10.54.
- [x] **E26** (0.47/0.85/0.68 при лимите 2.0) — **НЕ БАГ**: стоимость
      не превысила лимит, остановки не было — правильно.
- [x] **Третий случай** (10.44, `--decompose`) — закрыт ранее.
- **Проверено:** 2026-10-15, `pytest tests/ -k "budget or max_cost or precheck"` → **6 passed**.
- **См.** `docs/experiments.md` → E25/E26.

### 9. Промпт 55 строк — слишком большой

- [ ] **Проблема:** в задаче 10.8 промпт был **55 строк**.
      Модель **не удерживает** все требования — читает файл →
      забывает, что делать → читает другой.
- [ ] **Фикс (документация):** правило — «промпт к агенту должен
      быть **< 15 строк**. Если больше — разбить на несколько задач».
- **Приоритет:** 🟡 средний.

### 10. Backticks в CLI-промпте съедаются bash — ✅ решено (10.10)

- [x] **Проблема:** если в промпте к `agent` есть backticks,
      bash выполняет содержимое как **command substitution**.
- [x] **Фикс (документация):** раздел «Как формулировать задачу
      агенту» в `docs/tools.md` — не использовать backticks.
- [x] **Фикс (код):** предупреждение в CLI, если в `goal` есть
      обратные кавычки.
- **Приоритет:** 🟢 закрыто.

### 11. `parse_error` при пустом JSON от flash — ✅ решено (10.11.5)

- [x] **Проблема:** в decompose E2E подзадача 2 упала на
      `tool JSON no '{' found`.
- [x] **Фикс:** `parse_retries` (max 2) в `run_tool_loop`.
      При `parse_error` — retry с сообщением «верни СТРОГО JSON».
      После 2 retry — `stopped_reason=parse_error`.
- [x] **2 теста:** retry-ok, exhausted.
- **Приоритет:** 🟢 закрыто.

### 12. Подзадачи не знают, что задача уже решена — ✅ решено (10.11.7)

- [x] **Проблема:** подзадачи не знали про 'уже сделано'.
- [x] **Фикс (промпт):** правило 14 в `agent_tool_json`.
- [x] **Фикс (retry):** при fail — повтор через `decompose_model`.
- **Приоритет:** 🟢 закрыто.

### 13. Decompose: нет отката при частичном провале — ✅ решено (10.12)

- [x] **Проблема:** в E2E 10.8 подзадача 1 ✅ (применена), подзадача 2
      ❌ → стоп. **Подзадача 1 осталась применённой**, хотя decompose
      не завершился.
- [x] **Фикс:** опция `--decompose-rollback-on-fail` — откат всех
      успешных подзадач при провале любой (10.12).
- [x] **Фикс (проще):** `DecomposeResult.rolled_back`, откат по
      `backup_dir` каждой успешной подзадачи.
- **Приоритет:** 🟢 закрыто.

### 14. Decompose дорого для 2-3 файлов — подтверждено (10.14.11)

- [x] **Наблюдение (2 файла):** E2E decompose: 0.64 RUB.
      Без decompose: ~0.05-0.10 RUB. **Дельта — 6-10×**.
- [x] **Подтверждено (3 файла, 10.14.11):** decompose 1.2193 RUB vs
      прямой tool loop ~0.3-0.5 RUB. **Дельта — ×3.9**.
- [x] **Причина:** v4-pro decompose (отдельный LLM-вызов с полным
      деревом) + N × tool loop (каждый сканирует проект).
- [x] **Правило:** decompose — для **5+ файлов**, где прямой tool loop
      **зацикливается** (10.8: ❌ 15 итераций, 7.74 RUB → decompose ✅
      1.22 RUB). Для 2-3 файлов **прямой tool loop дешевле**.
- **Приоритет:** 🟢 закрыто (правило уточнено).

### 18. Tool loop: правило 11 — ловушка для больших файлов — ✅ решено (10.14.14)

- [x] **Проблема:** правило 11 запрещало `grep` после `read_file`.
      Для больших файлов (>50K) — ловушка: `read_file` обрезает,
      `grep` запрещён → модель не может найти место для `edit_file`.
- [x] **Живой пример:** попытка починить `agent.py` (2600 строк) —
      12 итераций, 0.6541 RUB, 0 правок.
- [x] **Фикс (инструмент):** `read_file(line_start, line_end)` —
      читать конкретный участок. Не обрезается.
- [x] **Фикс (промпт):** правило 11 разделено:
      - A (маленький файл) — read_file → edit_file → finish;
      - B (большой файл) — grep -n → read_file(offset) → edit_file.
- [x] **Тесты:** 6 в `test_tools.py`.
- **Проверка в бою:** E2 — живой прогон на `agent.py` (10.14.15).
- **Приоритет:** 🟢 закрыто.

### 15b. Decompose: узкий промпт подзадачи (обнаружено 2026-10-09)

- [ ] **Проблема:** в decompose-3 (10.14.11) промпт подзадачи 3 был
      «добавь раздел 12 в scenarios.md». Модель добавила **раздел**,
      но **забыла строку в таблице обзора** сверху.
- [ ] **Причина:** подзадача сформулирована узко, модель не выходит
      за рамки явного указания.
- [ ] **Фикс (документация):** в промпте decompose — перечислять
      **все** места, где нужно отразить изменение (раздел **и**
      таблица, строка **и** подраздел).
- [ ] **Фикс (идея):** v4-pro decompose должен **сам** проверять
      согласованность файлов (таблица ↔ разделы).
- **Приоритет:** 🟡 средний.

### 16. Auto-fix: нет ограничения бюджета — ✅ решено (10.14.4)

- [x] **Проблема:** `run_auto_fix` не прокидывал `max_cost_rub`
      в `run_tool_loop`. Каждая попытка — полный tool loop,
      суммарная стоимость не ограничена.
- [x] **Фикс:** параметр `max_cost_rub` в `run_auto_fix`,
      проброс остатка в каждый `run_tool_loop`;
      CLI-флаг `--max-cost-rub`.
- [x] **Фикс (плюс):** остановка цикла, если суммарная
      стоимость превысила лимит (`stopped_reason="max_cost"`).
- **Приоритет:** 🟢 закрыто.

### 15. Replan — проверен unit-тестами ✅ (10.14.7)

- [x] **Наблюдение:** E2E 10.11.8 показал, что replan **не сработал** —
      правило 14 + grep **предотвратили** fail.
- [x] **Проверка:** 3 unit-теста в `tests/test_agent.py`:
      `test_run_agent_decompose_replan_skip`, `..._stop`, `..._modify`.
      Мок `run_tool_loop` даёт fail, мок `run_planner_replan` —
      action. Проверяется поведение оркестратора.
- [x] **Вывод:** replan **не мёртвый код**. В E2E не срабатывает
      по объективным причинам (fail не наступает).
      **Оставляем в кодовой базе.**
- **Приоритет:** 🟢 закрыто.

---

## 10.32: read-шаги — сделано

- [x] **read-шаги в плане агента** — ЗАКРЫТО 10.32:
  `parse_agent_plan` принимает `type: "read"`, промпт разрешает,
  `run_tool_loop` использует `read_ops` для критерия успеха.
- [x] **read в простом агенте** (`run_agent`) — ЗАКРЫТО 10.33:
  `_run_read_step` через `run_tool_loop(step_type="read")`.
  `StepResult.read_answer`, verify не запускается.

---

## 10.31: step_type + read_ops — сделано

- [x] **Критерий успеха по типу шага** — ЗАКРЫТО 10.31:
  `run_tool_loop(step_type)` — `edit` требует `applied_ops > 0`,
  `read` требует `read_ops > 0`, `None` доверяет LLM.
- [x] **`ToolLoopResult.read_ops`** — счётчик успешных чтений.

---

## 10.30: chain report.md — сделано

- [x] **`--chain`: журнал при полном провале** — ЗАКРЫТО 10.30:
  `_save_chain_report` пишет `report.md` всегда, даже если все
  задачи упали. `stopped_reason="no_ops"` при 0 правок.

---

## 10.34+: автономность — доработки

- [ ] **«Признание сложности».** Если N попыток подряд провалились —
  остановиться и сообщить: «задача сложна для <model>». Опционально:
  флаг `--strict-autonomy`. См. `docs/autonomy.md` → Проблема 4.
- [ ] **Память между запусками.** `.ai-out/<project>/tasks/<hash>/state.json`,
  `--resume-last`. См. `docs/autonomy.md` → Этап 6.
- [ ] **Конвенции проекта.** `.ai-out/<project>/conventions.md` —
  тесты, docstrings, формат коммитов. См. `docs/autonomy.md` → Этап 7.
- [ ] **Reverse-check.** LLM перечитывает свой diff после
  `finish(success)`. См. `docs/autonomy.md` → Уровень 2.5.
- [ ] **Улучшение replan: история подзадачи.** Передавать последние
  5-10 шагов. См. `docs/autonomy.md` → Этап 2.
- [ ] **Рекурсивный replan.** `modify` → fail → `modify` с
  ограничением глубины. См. `docs/autonomy.md` → Этап 4.

---

## Направление 11 — связанные правки

**Проблема:** агент **проваливает** задачи, где изменение
в одном файле требует согласованного изменения в другом.

**Примеры (провалы):**
- **E17** (A.4): `checkbox` → `select`. JS + Python. **40%**, 0.81 RUB.
- **E19** (A.11): форма + `parseCommand` + `pending`.
  JS + Python + HTML. **1/4**, 16.87 RUB.

**Причина:** агент правит **локально**, не **глобально**.
Decompose **не решает** — связь между файлами сохраняется.

**Идеи (на будущее):**

- [ ] **11.1 Специализированные агенты / промпты для HTML/JS/CSS.**
      Не один `agent_tool_json`, а `agent_tool_html`,
      `agent_tool_js`, `agent_tool_css`. Разные правила,
      разные примеры, разные whitelist'ы инструментов.
      **Оценка:** ~2 недели.
      **Приоритет:** 🟡 средний.

- [ ] **11.2 Playwright в tool loop.**
      Инструмент `check_in_browser(url, selector)` — агент
      симулирует клик и проверяет, что элемент видим.
      **Оценка:** ~3-4 недели (тяжёлая зависимость, браузер).
      **Приоритет:** 🟢 низкий (универсальное, но дорого).

- [ ] **11.3 Библиотека шаблонов правок.**
      Готовые рецепты: `checkbox_to_select`,
      `wrap_in_container`, `add_form_field`,
      `add_route_to_fastapi`. Агент выбирает и заполняет
      параметры.
      **Оценка:** ~1-2 недели.
      **Приоритет:** 🟡 средний.

- [ ] **11.4 Обучение по образцу.**
      Показать агенту **правильную** правку в этом же файле
      (например, `mode` уже обёрнут в `.agent-only`), агент
      **повторяет** для других элементов.
      **Оценка:** ~3-5 дней.
      **Приоритет:** 🟡 средний (быстро, полезно).

**Что работает сейчас:** связанные правки — **вручную**
или **разбить на атомы** (6 задач по 3-5 строк).
См. `docs/tools.md` → «Когда НЕ использовать tool loop».

**Приоритет раздела:** 🟢 низкий (не блокирует автономность
на Python — агентом делает чистый Python хорошо).

---



## Направление 12 — Subagents и оркестрация (10.70–10.76) — ✅ ЗАКРЫТО

**Основание:** E36 (2026-10-15) — `--decompose` уже реализует
базовую оркестрацию: разбиение, изоляция, retry, verify.

**Не строить с нуля — доработать.**

### Сделано

- [x] **Router** — модель по сложности (explore/edit-simple/edit-complex/verify). ✅ 10.70 (2026-10-15).
      Router по-прежнему хардкодит типы в `decomposer.py`; секция
      `agent.subagents` (10.75) — отдельный механизм для `spawn_subagent`.
- [x] **Validator** — семантическая проверка результата подзадачи
  (адаптация `--reverse-check`). ✅ 10.71 (2026-10-16).
- [x] **Feedback loop** — summary подзадачи N в подзадачу N+1
  и в планировщик. ✅ 10.74 (2026-10-16).
- [x] **Инструмент `spawn_subagent`** — ✅ 10.75 (2026-10-16).
      Коммиты `d679409`, `00c6700`, `1546ad0`, `9d5d840`. E2E:
      `/tmp/spawn-e2e`, 0.1139 RUB. Реализовано dsh (D4),
      дизайн — `docs/dsh/D4/answer.md`.

### Осталось (follow-up 10.75, найдено в E2E)

> **Перенесено** в раздел «Findings D5/D6» выше (10.76):
> depth 2, backup merge, `max_minutes`, `_handle_finish` для
> explorer-родителя, `toolN` с 1, `iterations` с finish.
> Там же — статус #1-#7.

- [ ] **depth 2** — рекурсия subagent'ов (сейчас depth = 1, 3 барьера).
      ~1-2 дня.
- [ ] **backup merge** — манифест backup'ов subagent'а в родителя,
      чтобы родительский `rollback` откатывал и правки ребёнка
      (сейчас у ребёнка свой `backup_dir`). ~4 ч.
- [ ] **`max_minutes` в tool loop** — сейчас не проверяется вообще,
      subagent'а ограничивает только бюджет (`cap`). ~2 ч.
- [ ] **`_handle_finish` для explorer-родителя** — `step_type="edit"`
      требует `applied_ops > 0`, поэтому родитель, который только
      делегировал read-only разведку, завершиться не может
      (`read_ops` не подходит). ~2 ч.
- [ ] **`toolN` с 1** — pre-existing: `start_iteration = 0`, первый
      запрос `agent:tool0`. ~30 мин.
- [ ] **`iterations` включая finish** — `iterations=len(ctx.history)`,
      а `_handle_finish` в history не пишет (расхождение с
      `usage.jsonl` на 1). ~30 мин.
- [ ] **Retry-политика** — расширить (parse_error, verify_failed).
      ~1-2 дня.

### Связанные находки (см. «Из Validator/GUI», выше)

- `usage --by-action` не существует (🟢 низкий).
- `usage.jsonl`: пути CWD vs `project_root` (🟡 средний).
- E2E feedback: планировщик создаёт verify-подзадачи (🔴 высокий) —
  тот же класс проблемы, что «`_handle_finish` для explorer-родителя».

### Концепция

`docs/autonomy.md` → раздел «9. Subagents и оркестрация».

### Приоритет

✅ направление закрыто (10.75). Follow-up — по списку выше;
сначала 🔴 verify-подзадачи, затем 🟡 пути `usage.jsonl`.

## GUI — сделано

- [x] **A.0** — скелет FastAPI + Jinja2 + HTMX.
- [x] **A.1** — форма сборки команд.
- [x] **A.2** — запуск со стримингом (SSE + fetch).
- [x] **A.3** — `max-cost-rub` select + copy-output-btn.
- [x] **A.4** — `check_mode` select (normal/dry-run/dry-read).
- [x] **A.5** — ссылка на отчёт после `/run` + mount `/ai-out`.
- [x] **A.6** — рендер `report.md` в HTML.
- [x] **A.7** — `/reports` — список всех журналов (2026-10-13, 10.40).

**Осталось:**
- [x] **A.8** — история usage в GUI (графики Chart.js: по дням/моделям/действиям). ЗАКРЫТО 10.42.
- [ ] **A.9** — пагинация/фильтр в `/reports` (если журналов станет 500+).
- [ ] **A.10** — встроенный терминал (PTY + WebSocket, этап B).

- [x] **GUI: `--chain` не поддержан.** ЗАКРЫТО 10.56/10.57: `chain_path`
      в `_build_command`/`_build_argv`, поле `#chain-path` в форме,
      `--chain <dir> --tool-loop` собирается автоматически. В 10.57
      убран плохой дефолт `issues` (в нашем проекте — `README.md`),
      добавлены placeholder и подсказки.

- [x] **CLI: `--chain` требует непустой `goal`.** ЗАКРЫТО 10.59:
      `if not goal and chain is None` — при `--chain` проверка
      пропускается. Тест `test_chain_without_goal_ok`.
      + поле `#chain-path` в форме (видно при `mode=chain`).
      **Ограничение:** `--plan` (интерактив `y/n/e`) в GUI **не
      заработает** — `subprocess` без PTY, `input()` → EOFError.
      Для `--chain --plan` — только CLI.
- **Приоритет:** 🟡 средний.
