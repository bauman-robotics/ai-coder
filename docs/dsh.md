# DeepSeek Harness (dsh) — эксперименты

Дневник экспериментов с **DeepSeek Harness** (`dsh`) — открытым агентом
от DeepSeek AI. https://github.com/deepseek-ai/deepseek-harness

**Зачем:** понять, чем `dsh` **дополняет** `ai-coder` (не конкурирует,
а другой слой), что **взять** из его идей, где `ai-coder` **сильнее**.

**Формат:** `D1, D2, ...` (D = DeepSeek harness).

**Связь:** `docs/experiments.md` — эксперименты **с ai-coder**
(E1-E38). Здесь — только `dsh`.

---

## 2026-10-16 — D9: E2E Router без `--model` (Router ✅ работает)

**Задача:** проверить, что Router (10.70) **реально** выбирает модель
подзадачи по `type`, а не только «числится» починенным после D8.
**Где:** worktree `.worktrees/d9` (ветка `d9`). **Не запушено.**

### E2E без `--model` — Router работает ✅

Песочница (README с опечаткой, `calc.py`, `utils.py`, `test_calc.py`),
цель: «Изучи структуру проекта, исправь опечатку в README.md, добавь
функцию `mul` в `calc.py` и используй её в `utils.py`, добавь тест
`test_mul` в `test_calc.py` и прогони тесты.»
Команда: `--tool-loop --decompose --apply` **без `--model`**,
`--max-cost-rub 15`.

Результат: **6 подзадач, все ✅, EXIT=0, 4.6092 RUB.**

| # | Подзадача | Роль | Модель | Итер |
|---|---|---|---|---|
| 1 | Изучить текущее содержимое `calc.py` | `explore` | `deepseek-flash` | 2 |
| 2 | Изучить `test_calc.py` и `README.md` | `explore` | `deepseek-flash` | 2 |
| 3 | Добавить функцию `mul(a, b)` в `calc.py` | `edit-complex` | **`deepseek-v4-pro`** | 7 |
| 4 | Исправить опечатку в `README.md` | `edit-simple` | `deepseek-flash` | 4 |
| 5 | Добавить тест `test_mul` | `edit-simple` | `deepseek-flash` | 3 |
| 6 | Запустить `pytest` | `verify` | `deepseek-flash` | 4 |

Покрыты **все четыре типа** Router. Модель каждой подзадачи взята из
её журнала (`step-0.md` → «Модель»).

### Уточнение: `--model` и не перекрывал Router

Исходная посылка задачи («в D8 E2E модель задавалась `--model`, который
перекрывает Router») **неверна**. В коде модель подзадачи берётся из
`_resolve_subagent(st)`, а параметр `model` из CLI идёт только в
планировщик (`decompose_model`) и в retry-fallback:

```python
subtask_model, subtask_iters = _resolve_subagent(st)  # decomposer.py:371
...
model = (subtask_model,)  # :379
```

Журнал **D8** это подтверждает: подзадачи 1/4 — flash, 2/3 — v4-pro.
То есть Router был в силе уже в D8, а запись в `TODO.md` (и в
`state.md`) про «не проверено» опиралась на неверную предпосылку —
исправлено.

### 🐞 Баг A: у Router нет fallback, если модели нет в `pricing`

`_resolve_subagent` возвращает **захардкоженные** имена
(`deepseek-flash` / `deepseek-v4-pro`) и **не проверяет** их наличие
в конфиге. Если у пользователя нет цен для выбранной модели:

```
del cfg.api.pricing["deepseek-v4-pro"]
_estimate_next_cost_rub(cfg, "deepseek-v4-pro", ...)
→ KeyError: "Нет цен для модели 'deepseek-v4-pro' в конфиге"
```

Падение происходит **в середине прогона** (`pricing_for` вызывается в
precheck и в `calculate_cost`), то есть уже после потраченных денег.

При этом `SubagentConfig.model` (D6) **валидируется на старте**. Router
и subagents ведут себя непоследовательно.

→ issue в `TODO.md`.

### 🐞 Баг B: `--max-iterations` (default 20) перекрывает лимиты Router

`agent_cmd` объявляет `--max-iterations` со **значением по умолчанию
20** (не `None`) и всегда передаёт его в `run_agent_decompose`, а там:

```python
final_iters = max_iterations if max_iterations is not None else subtask_iters
```

`20 is not None` → всегда 20 → **лимиты Router (5/10/15/3) не
применяются** при запуске через CLI.

**Доказательство из этого же E2E:** подзадача 6 (`verify`) отработала
**5 шагов** (`step-0..step-4`) при лимите Router **3**. Значит
действовал не Router-лимит, а 20.

Модели при этом выбираются правильно (за это отвечает `subtask_model`,
а не `final_iters`) — поэтому баг не был заметен.

→ issue в `TODO.md`.

### Что НЕ подтвердилось

- «Router не работает без `--model`» — работает.
- «`--model` перекрывает Router» — не перекрывает (для подзадач).

### Стоимость

- E2E: **4.6092 RUB**. Диагностика (чистые функции, без LLM): 0 RUB.
- Артефакты: `.ai-out/dsh-d9/` (лог, журнал).

---

## 2026-10-16 — D8: verify-подзадача в decompose (🔴) — ROOT CAUSE найден

**Задача:** закрыть 🔴 «планировщик создаёт verify-подзадачи» из `TODO.md`
(он же — причина, по которой `--decompose` падал на реальных прогонах).
**Где:** worktree `.worktrees/d8` (ветка `d8`), коммит `9eae807`.
**Не запушено.**

### Симптом

В `--decompose` v4-pro создаёт подзадачу «Запустить тесты (pytest)».
`decomposer.py` передавал **всем** подзадачам `step_type="edit"`, а
`_handle_finish` при `"edit"` требует `applied_ops > 0`. Verify ничего
не правит → `success=False` → retry → снова fail.

### ROOT CAUSE — глубже, чем `step_type`

Первый прогон E2E с уже исправленным `step_type` **всё равно упал**.
Разбор журнала: у подзадачи 3 `finish(success=True)`, но
`success=False` и verify даже не запускался → значит `step_type`
не был `None`.

Прямая проверка планировщика показала:

```
=== raw JSON (фрагмент с type) ===
  type = explore
  type = edit-complex
  type = edit-complex
  type = verify
=== распарсенные подзадачи ===
  n=1 type='edit'   n=2 type='edit'   n=3 type='edit'   n=4 type='edit'
```

`planner.py::parse_decompose_response` держал whitelist
`("edit", "read")` и **приводил к `"edit"` всё остальное**. Промпт
планировщика корректно просит `explore` / `edit-simple` /
`edit-complex` / `verify` — но парсер их уничтожал.

**Следствия (до фикса):**
- **Router (10.70) фактически не работал:** `st.type` всегда `"edit"`,
  а `_resolve_subagent` для `"edit"` не находит тип в `_SUBAGENT_MODEL`
  и берёт фолбэк `edit-simple`. То есть `edit-complex` **никогда**
  не получал v4-pro, а `explore`/`verify` не существовали.
- ломались **два типа из четырёх**: `explore` (только читает →
  `applied_ops=0`) и `verify` (ничего не правит) не могли завершиться
  успешно **в принципе**.

### Фикс (2 части)

**1. `ai_coder/agent/planner.py`** — принимать типы Router:

```python
_VALID_SUBTASK_TYPES = (
    "explore",
    "edit-simple",
    "edit-complex",
    "verify",
    "edit",
    "read",
)  # legacy edit/read
...
if stype not in _VALID_SUBTASK_TYPES:
    stype = "edit"
```

**2. `ai_coder/agent/decomposer.py`** — `_step_type_for(st)`:

| `st.type` | `step_type` | критерий `_handle_finish` |
|---|---|---|
| `explore`, `read` | `"read"` | `read_ops > 0` |
| `verify` | `None` | из `finish` модели |
| `edit`, `edit-simple`, `edit-complex`, прочее | `"edit"` | `applied_ops > 0` |

Значение передаётся в **оба** вызова `run_tool_loop` (обычный и retry).

### Почему `verify → None`, а не новый `"verify"`

- При `None` `_handle_finish` берёт success из `finish` модели, а роль
  «проверить» дальше закрывает **сам tool loop**: `verify_commands`
  (pytest) выполняется после success и при падении тестов ставит
  `success=False`. Отдельный критерий просто не нужен.
- Новый `"verify"` потребовал бы своего критерия (например, «был
  `run_shell`») — это новый счётчик и риск ложных падений у verify,
  который проверяет чтением.
- `_handle_finish` **не менялся** — минимальный радиус.

### E2E (до / после)

Песочница `calc.py` + `test_calc.py`, цель «Добавь sub в calc.py и
test_sub в test_calc.py. Прогони тесты.»,
`--decompose --tool-loop --apply --model deepseek-v4-pro`:

| | Подзадач | Результат | Стоимость |
|---|---|---|---|
| **До** фикса | 3 | verify ❌ → **EXIT=1** | 0.7175 RUB |
| **После** | 4 (explore + 2 edit + verify) | **все ✅ → EXIT=0** | 3.0292 RUB |

В «после» впервые прошла и **explore**-подзадача («Изучить текущую
реализацию calc.py…») — до фикса она была обречена так же, как verify.
Разница в числе подзадач (3 vs 4) — недетерминизм планировщика.

### Побочный (ожидаемый) эффект

После фикса парсера **Router (10.70) начал работать по-настоящему**:
`edit-complex` получает v4-pro, `explore` — flash и 5 итераций,
`verify` — flash и 3. Это не «новый функционал», а включение уже
написанного кода.

### Тесты (+10, `tests/test_decompose_step_type.py`)

- `_step_type_for`: explore→read, read→read (legacy), verify→None,
  edit/edit-simple/edit-complex→edit, неизвестный→edit;
- парсер **сохраняет** типы Router; регистр нормализуется; legacy
  `read` сохраняется; мусор → `edit`; отсутствующий `type` → `edit`;
- retry использует **тот же** `step_type` (не возвращается к `"edit"`);
- сквозной путь: JSON планировщика → `type` → `step_type` в
  `run_tool_loop`.

**576 passed** (было 566), ruff/mypy/pre-commit — зелёные.

### Acceptance

| Критерий | Результат |
|---|---|
| decompose с verify-подзадачей — verify проходит | ✅ E2E: EXIT=1 → **EXIT=0**, все 4 подзадачи ✅ |
| Не ломает 566 | ✅ **576 passed** (+10 новых) |
| E2E `/tmp/decompose-verify-e2e` | ✅ выполнен до и после |

### Осталось

- `Router` теперь работает — но **не проверен** отдельно: нужен E2E,
  где планировщик даёт `edit-complex`, и видно, что взят v4-pro
  (в этом прогоне `edit-complex` был, но модель tool loop задана
  флагом `--model`, что перекрывает Router).
- D2: `usage --by-action`, пути `usage.jsonl`.
- D5 findings #4-#7 (`iterations`, пустой `summary`, cap, worktree-рецепт).

### Стоимость

- E2E до фикса: **0.7175 RUB**; после: **3.0292 RUB**; диагностический
  вызов планировщика: **0.6074 RUB**. Итого ~**4.35 RUB**.
- Артефакты: `.ai-out/dsh-d8/` (логи, журналы до/после).

---

## 2026-10-16 — D7: #2 Validator (`--reverse-check`) в tool loop

**Задача:** закрыть finding #2 — «Validator не применяется в tool loop».
**Где:** worktree `.worktrees/d7` (ветка `d7`), коммит `1822df5`.
**Не запушено.**

### Что уже было (уточнение к формулировке находки)

`--reverse-check` **уже работал** в tool loop: флаг — `cli.py:1336`,
передача — `cli.py:1830`, RC-блок — `tool_loop.py:747` и `:766`.
Проблема была не в отсутствии, а в **`default=False`** и в том, что RC
срабатывает **один раз в конце** (после `finish`), а не по итерациям.
Плюс: в E2E-2 RC вообще не выполнился бы — прогон упал по
`max_iterations`, а RC требует `success and stopped_reason == "completed"`.

### Эксперимент: ловит ли RC неправильный фикс?

Стенд — `scripts/d7_rc_experiment.py`. Прогнал `run_reverse_check` на
**реальном** диффе из E2E-2 (неправильный фикс `step_type=st.type`)
с тремя формулировками goal, плюс контроль на правильном диффе.
Стоимость — **0.85 RUB**.

| Дифф | Goal | Вердикт RC |
|---|---|---|
| неправильный | **goal из E2E-2** («пробрасывай type в step_type») | `ok=True` — **НЕ поймал** |
| неправильный | точный (описан контракт `_handle_finish`) | `ok=False` — **поймал** ✅ |
| неправильный | issue-стиль (`explore→read, verify→None, edit-*→edit`) | `ok=False` — **поймал** ✅ |
| **правильный** | goal из E2E-2 | `ok=False` — поймал отсутствие правки `docs/state.md` |

Что именно сказал RC в удачных случаях:
- «В обоих вызовах `verify_commands` вместо `None` передаётся `st.type`.
  Для verify-подзадачи `st.type` будет …»;
- «Не реализована сама функция/mapping преобразования type подзадачи
  в step_type, хотя именно это требовалось».

**Вывод: потолок RC — качество goal, а не момент срабатывания.**
Если goal описывает только *форму* («пробрасывай type»), фикс, формально
ей удовлетворяющий, пройдёт. Если goal описывает *требуемое поведение*
(контракт `step_type`), RC ловит подмену.

### Выбор варианта: **A** (default on), не B

- **Вариант B (RC per-iteration, 4-6 ч) размытый goal не лечит** —
  RC снова получит тот же goal и снова скажет `ok`. При этом он стоит
  N лишних LLM-вызовов на прогон.
- **Вариант A (1-2 ч)** повышает **покрытие**: проверка выполняется,
  даже если пользователь о ней не вспомнил. Цена — ровно **+1 запрос**
  и только когда diff непустой (пустой diff RC пропускает сам).
- Корень проблемы (размытый goal) лежит **выше** RC — в формулировке
  задачи/issue. Это зафиксировано как ограничение, а не «вылечено»
  переключением тайминга.

Итог: **A как MVP**, ограничение задокументировано.

### Реализация

Сделал **tri-state**, иначе `default=True` сломал бы существующую
валидацию `if reverse_check and not tool_loop` (`cli.py:1465`) —
она срабатывала бы на каждом прогоне без tool loop:

```python
reverse_check: bool | None = typer.Option(None, "--reverse-check/--no-reverse-check", ...)
...
rc_enabled = tool_loop if reverse_check is None else reverse_check
```

- `None` (не указывали) → **включено в tool loop**, выключено вне него;
- `--reverse-check` без `--tool-loop` → по-прежнему ошибка (проверено);
- `--no-reverse-check` → явный отказ.

Библиотечный `run_tool_loop(reverse_check=False)` **не менял**: CLI
передаёт значение явно, поэтому `decompose` и `spawn` не затронуты.

### Acceptance

| Критерий | Результат |
|---|---|
| RC ловит неправильный фикс | **Да, если goal точный** (2 из 3 формулировок). При размытом goal — нет, и это свойство RC, а не тайминга |
| Не ломает существующее | **566 passed** (было 562; +4 новых теста), ruff/mypy/pre-commit зелёные |
| Стоимость предсказуема | **+1 LLM-запрос** на прогон, и только при непустом diff |

### Тесты (+4, `tests/test_cli_agent.py`)

- дефолт без флага в tool loop → `reverse_check=True`;
- `--no-reverse-check` → `False`;
- явный `--reverse-check` без `--tool-loop` → exit 1 и понятная ошибка;
- дефолт (`None`) без `--tool-loop` → ошибки про RC **нет**.

### Что осталось

- **#4** `iterations` ≠ числа LLM-вызовов;
- **#5** пустой `summary` при `max_iterations`;
- **#6** перерасход `cap` (дописать в `docs/tools.md` §6);
- **#7** рецепт self-hosted E2E в worktree (доки);
- D2/D3-находки: `usage --by-action`, пути `usage.jsonl`,
  **verify-подзадача в decompose** (🔴, D7 её не касался).

### Стоимость

- Эксперимент RC: **0.85 RUB**.
- Артефакт: `scripts/d7_rc_experiment.py`, сырые данные —
  `.ai-out/dsh-d7/rc-experiment.json` (gitignored).

---

## 2026-10-16 — D6: починка findings D5 (#1 verify+mypy, #3 делегирование)

**Задача:** закрыть 2 критичные находки `docs/findings-d5.md`.
**Где:** worktree `.worktrees/d6` (ветка `test-d6`), коммиты — **в ветке**,
не в `main`. Изменения не запушены.

---

### #1 — verify не ловит mypy → ✅ FIXED (`1b2ee2f`)

**Проблема:** `agent.verify_commands` = только `python -m pytest -q`,
поэтому фикс E2E-1 прошёл verify с падающим mypy
(`decomposer.py:353: Incompatible types in assignment`).

**Почему нельзя «просто дописать mypy в verify_commands»:** verify
выполняется в **проекте-цели**, а `python -m mypy ai_coder` в чужом
проекте упадёт — пакета `ai_coder` там нет.

**Решение — два списка:**
- `agent.verify_commands` — generic (pytest), как было;
- `agent.self_verify_commands` — применяются **только** когда
  проект-цель — сам ai-coder (`is_self_hosted`: в корне есть
  `ai_coder/__init__.py`).

Новое в `apply.py`: `is_self_hosted()` и чистая
`resolve_verify_commands(...)` с приоритетом
`--no-verify` → `--verify-commands` → `config + self`.
Явный `[]` (read-only subagent в spawn) остаётся `[]` — self-проверки
не подмешиваются.

Врезка **одна** — в `cli.py::agent_cmd` (там известны и target, и флаги);
оба пути (tool loop и decompose) берут уже готовый
`cfg.agent.verify_commands`.

`config/config.yaml`: `self_verify_commands = [ruff check ai_coder/,
mypy ai_coder]`.

**E2E (детерминированный, без LLM):** песочница с `ai_coder/__init__.py`
и файлом с несовместимым присваиванием → `resolve_verify_commands`
добавляет mypy → `run_verify_commands` возвращает ошибку.
В чужом проекте команда не добавляется и verify не падает.

**Тесты:** 18 новых — `tests/test_verify_resolve.py` (15: приоритеты,
self/foreign, дедуп, механизменный E2E с mypy) + 3 CLI-теста проводки
(self-hosted добавляет mypy; чужой — нет; `--verify-commands`
переопределяет). **562 passed**, ruff/mypy clean.

---

### #3 — делегирование без подсказки → ✅ FIXED (`043aa96`)

**Гипотеза, проверенная первой (до правок):** в E2E-2 задача была
**маленькой** (правка в 1-2 файлах) — модель, возможно,
**рационально** не делегировала. Значит, «0 spawn» мог быть не багом
промпта, а верным решением.

**Стенд:** `scripts/d6_delegation_ab.py` — песочница на 30 файлов
(4 подсистемы × 5-7 файлов), у каждой свой способ обращения с ошибками.
Две задачи: **small** («добавь mul в calc.py и упомяни в README») и
**large** («найди ВСЕ места, где ошибки логируются/глотаются/
пробрасываются, и опиши различия»). verify в эксперименте выключен.

**Результаты (делегировали / прогонов):**

| Задача | Секция ролей | Модель | Делегировали |
|---|---|---|---|
| small | старая | flash | 0/3 |
| small | новая | flash | 0/3 |
| large | старая | flash | 1/3 (12 ит.) |
| large | **новая** | flash | **3/3** ✅ |
| large | старая | flash | 0/3 (15 ит.) |
| large | **новая** | flash | **3/3** ✅ |
| large | старая | **v4-pro** | 0/1 |
| large | **новая** | **v4-pro** | **1/1** ✅ |

**Вывод — гипотеза подтвердилась:**
- на **маленькой** задаче не делегирует **никто** (0/3 оба варианта) —
  и это правильно: она решается за 4 шага, делегировать нечего;
- сломан был отклик на **большую** задачу: со старым текстом модель
  делала разведку сама (10-15 своих `run_shell`/`read_file`),
  с новым — делегирует.

**Фикс:** в `build_subagents_section` добавлен блок «Делегируй, когда
работа требует прочитать много файлов (>3-4) или сделать несколько
независимых шагов… НЕ делегируй мелочи». Per-role «**Когда:**»
не добавлял: описания ролей задаёт пользователь в конфиге, генератор
их не знает. **Правило 19 в `prompts.yaml` не менял** — секция
оказалась достаточным рычагом (меньше churn).

**Acceptance:** ✅ 3/3 на большой задаче (требовалось ≥3 из 5);
подтверждено и на v4-pro (1/1).

**Ограничения эксперимента (честно):**
- **Выгода делегирования не доказана.** ВСЕ large-прогоны упёрлись в
  `max_iterations` (12 или 15) — и со spawn, и без. То есть делегирование
  **включается**, но что оно **улучшает результат**, этот опыт не показал.
  Нужен отдельный эксперимент с большим лимитом итераций.
- **n мало:** 3 повтора на flash + 1 на v4-pro.
- Разброс стоимости: со spawn дороже (flash 5.16 vs 3.82 RUB на 3 прогона;
  v4-pro 6.07 vs 4.93 RUB на 1) — subagent сам стоит денег.
- Задачи синтетические; на реальном репозитории (больше шума) картина
  может отличаться.

---

### Ответы на вопросы задачи

- **verify ловит mypy?** Да, для self-hosted прогонов: ошибка типов →
  verify fail. В чужих проектах self-проверки не включаются (проверено).
- **Делегирование работает?** Да, но **условно**: на большой задаче —
  3/3 с новым текстом секции; на маленькой не делегирует и не должен.
  Ценность («стало лучше») не измерена — см. ограничения.

---

### Оставшиеся findings (коротко)

- **#2 (Validator в tool loop)** — не трогал. Напоминание: `--reverse-check`
  **уже** работает в tool loop, вопрос в `default=False` и в том, что RC
  один раз в конце. Отдельно: RC мог не поймать фикс E2E-2, т.к. тот
  формально соответствовал goal.
- **#4 (`iterations` ≠ LLM-вызовов)** — не трогал. Подтверждено в D6:
  v2-large сделал 15 шагов, а `usage.jsonl` писал 16 записей.
- **#5 (пустой summary при `max_iterations`)** — не трогал. В D6 видно
  снова: все large-прогоны `max_iterations` с пустым `summary`.
- **#6 (перерасход cap)** — не трогал; уже задокументирован в CHANGELOG.
- **#7 (`.venv` из worktree)** — не трогал. В D6 применён тот же рецепт:
  абсолютный путь к venv, `PATH=.venv/bin`, `PYTHONPATH=<worktree>`,
  ключ из `.env`.

---

### Стоимость

**Эксперименты D6 (реальные LLM-вызовы):**

| Что | Модель | RUB |
|---|---|---|
| smoke-тест стенда | flash | 0.75 |
| матрица 1 (v0/v1 × small/large × 3) | flash | 6.80 |
| матрица 2 (v0/v2 × large × 3) | flash | 8.99 |
| матрица 3 (v0/v2 × large × 1) | **v4-pro** | 11.00 |
| **Итого экспериментов** | | **27.54** |

**DSH-сессия целиком** (модель `deepseek-flash`, off-peak):
output **320 132** токена, cache read 98.1M, uncached input 202 086 →
**3.4454 CNY ≈ 43.05 RUB** (по прайсу `config/config.yaml`; счёт
DeepSeek может отличаться). Больше, чем в D5 (34.83 RUB), из-за
12 туров / 408 шагов.

**Артефакты:** `scripts/d6_delegation_ab.py` (стенд, в коммите),
сырые логи — `.ai-out/dsh-d6-*.log` (gitignored).

---

## 2026-10-16 — D5: verify-подзадача + 3 subagents (E2E) (⚠️ смешанный)

**Задача:** проверить `spawn_subagent` (10.75) на **реальной** задаче —
починить verify-подзадачу в `decompose`
(`issues/2026-10-16/12-verify-subtask.md`), с **3 ролями** в конфиге.

**Где:** отдельный worktree `.worktrees/verify` (ветка
`test-verify-spawn`), `--tool-loop --apply --model deepseek-v4-pro
--max-cost-rub 15`. `PYTHONPATH` = worktree (self-hosted),
`PATH` = `.venv/bin` (иначе `run_shell` не находит `python`/`pytest`).

### Config (10.75.1)

3 subagents раскомментированы в `config/config.yaml`:
`code-explorer` (read-only, flash, 5 ит, cap 1.0),
`test-runner` (`run_shell`, flash, 3 ит, cap 0.5),
`markdown-writer` (`read_file`+`write_file`, v4-pro, 8 ит, cap 2.0).
Коммит `1775bc1`, **542 passed**.

### E2E-1 (с подсказкой — все 3 роли): ✅ 11.1805 RUB

Goal **явно называл** роли. **Все 3 роли вызваны** (3 × `spawn_subagent`):

| # | Роль | Итог | Стоимость | Итер |
|---|---|---|---|---|
| 1 | code-explorer | ✅ completed | 0.1999 RUB | 3 |
| 2 | test-runner | ❌ max_iterations | 0.1599 RUB | 3 |
| 3 | markdown-writer | ❌ max_cost | 2.4496 RUB | 3 |

- Итог: **15 шагов, 11.1805 RUB** (из них **2.8094 — subagents**),
  причина `completed`, `success`.
- Digest'ы (журнал `history.json`):
  - **code-explorer**: «step_type в `decomposer.py` присваивается в
    двух местах: `:367` и `:420`» — **точная** разведка.
  - **test-runner**: `summary:` **пустой** (max_iterations).
  - **markdown-writer**: `budget exceeded: 2.4496 RUB >= 2.0000 RUB`.
- Родитель сделал правки **сам**: 3 × `edit_file` в `decomposer.py`
  + `edit_file` в `docs/state.md`.
- **Фикс семантически верный:** `explore→read`, `verify→None`, иначе
  `edit`; оба вызова — `step_type=step_type`.
- **НО ломает mypy:** `decomposer.py:353: Incompatible types in
  assignment (expression has type "None", variable has type "str")` —
  нужно `step_type: str | None = "edit"`. Тесты/ruff — зелёные.
- **Журналы детей вложены** в родительский (проверено):
  `tool-loop-<ts>/spawn-<name>/tool-loop-<ts>/`.

### E2E-2 (без подсказки): ❌ 10.5242 RUB

Тот же goal, но **без имён ролей**.

- **`spawn_subagent` не вызван ни разу** (0 из 20 шагов), хотя
  инструмент был в промпте, а 3 роли — в конфиге.
- Модель сделала всё сама: 8 `run_shell`, 8 `read_file`,
  3 `edit_file`, 1 `read_symbol`.
- Итог: **20 шагов, 10.5242 RUB**, `max_iterations`, `summary` пустой.
- **Фикс неверный:** `step_type=st.type` — сырые значения (`explore`,
  `edit-simple`, `verify`), а `_handle_finish` понимает только
  `None` / `"read"` / «всё остальное = edit».
- **При этом pytest 542 ✅, ruff ✅, mypy ✅** — все проверки зелёные
  при **неработающем** фиксе.

### Почему фикс E2E-2 не лечит (демонстрация)

`_handle_finish` при `applied_ops=0, read_ops=0`:

    step_type      success
    None           True     OK
    read           False    (нужен read_ops > 0)
    edit           False
    explore        False    <-- баг НЕ исправлен
    edit-simple    False
    verify         False    <-- баг НЕ исправлен

### Находки

1. **`iterations` ≠ число LLM-вызовов.** Explorer: digest «3 итер»,
   а в `usage.jsonl` — **4** записи (`:tool0..:tool3`). Причина:
   `iterations=len(ctx.history)`, а `_handle_finish` в history не
   пишет. Подтверждено дважды (E2E-1: 15 шагов / 16 записей).
2. **Атрибуция расходов работает и точна:** сумма
   `agent:spawn:code-explorer:*` = 0.2000 RUB = digest 0.1999 RUB.
   Без 10.75 эти **2.81 RUB** были бы неотличимы от родительских.
3. **Verify не ловит mypy.** `verify_commands` = `python -m pytest -q`
   → фикс E2E-1 прошёл verify, хотя mypy падает. Нужен mypy в verify
   (или RC).
4. **Зелёные проверки ≠ правильный фикс** (E2E-2: pytest+ruff+mypy ✅,
   баг остался) — ровно тот случай, для которого делали Validator
   (`--decompose-reverse-check`), а в tool loop он не применяется.
5. **Модель не делегирует без прямого указания** — даже с 3 ролями в
   промпте и правилом 19.
6. **test-runner вернул пустой summary** при `max_iterations` — родитель
   не понимает, что именно упало.
7. **markdown-writer превысил cap** (2.4496 > 2.0) — подтверждает
   задокументированный перерасход «≤ 1 итерации» (последняя итерация
   v4-pro — 1.6470 RUB).
8. **Вложенные журналы и allowlist** — работают.

### Итог

- `spawn_subagent` **технически работает**: роли вызваны, digest'ы
  приходят, стоимость атрибутируется, журналы вложены, depth=1 и
  allowlist соблюдены.
- **Практическая ценность под вопросом:** 2 из 3 ролей упали, родитель
  всё равно сделал работу сам; без подсказки модель **не делегирует**.
- **Worktree `test-verify-spawn`** оставлен пользователю (чистый, на
  `1775bc1`). Артефакты в `.ai-out/dsh-d5/` (gitignored):
  `e2e1-changes.patch`, `e2e2-changes.patch`, журналы, `.e2e1.log`,
  `.e2e2.log`.

**Ссылки:** `docs/autonomy.md` §9, `issues/2026-10-16/12-verify-subtask.md`,
коммиты 10.75 (`d679409..9d5d840`) + `1775bc1`.
**Backlog по находкам:** `docs/findings-d5.md`.

---

## 2026-10-16 — D3: dsh реализовал Feedback loop (✅ успех)

**Задача:** Feedback loop — подзадача N **видит** результат
подзадач 1..N-1 (наша Направление 12).

**Что dsh сделал:**

- **4 файла, +52 строки, 0 удалений** — чисто.
- `_build_feedback` в `decomposer.py` — нормализация goal, обрезка
  до 200 символов, fallback на `cost_rub`.
- `feedback_section` — параметр в `run_tool_loop`, поле в `_ToolLoopCtx`.
- Промпт — через `render_prompt(extra=...)`.
- Конфиг: `feedback_enabled=True`, `feedback_max_subtasks=7`.
- `{{feedback_section}}` после `ЦЕЛЬ:` в `agent_tool_json`.

**Осознанные отступления от ТЗ:**

1. **Feedback один раз на итерацию** (не «перед каждым
   `run_tool_loop`»). Иначе retry **видел бы** свою **неудачную**
   попытку в «Предыдущих подзадачах».
2. **Строка `Результат:`** в формате — пример в ТЗ был **сокращён**,
   но `summary` **указан** в списке полей.

**Проверка:**

- **9 кейсов** временным тестом — формат, пустой вход, `max_items=0/1`,
  обрезка, fallback.
- **Интеграционный** тест на **реальном** `prompts.yaml` — важно,
  потому что `render_prompt` **бросает** `KeyError` на **неизвестные**
  переменные.

**Итог:**

- **1 turn, 27 steps, ~0.25 RUB**.
- **491 passed**, ruff/mypy clean.
- **E2E:** 3 подзадачи, prompt-tokens **3067 → 3114 → 3159**
  (+45-50 на feedback).
- **1 коммит** `254f41e`.

**Вывод:** dsh **снова** показал **уровень middle+**:
- **поймал** критичный `KeyError`-риск;
- **осознанно** отступил от ТЗ — **объяснил**;
- **спросил** разрешение на **коммит**;
- **не** сломал **491** существующий тест.

---

**Гипотезы на будущее:**
- **D2:** дать `dsh` ту же задачу в **режиме реализации** (не план) —
  сравнить с `ai-coder --tool-loop --apply`.
- **D3:** дать **ai-coder** тот же промпт (`--dry-read`) — сравнить
  планы `dsh` vs `ai-coder` напрямую.
- **D4:** дать `dsh` задачу **Router** (уже решённую, E38) — сравнить
  с результатом `ai-coder` (32 RUB, 3 прогона).

**Ссылки:**
- `next-chat/in-progress.md` → Feedback (следующее, после Validator 10.71).
- `docs/autonomy.md` → раздел 9 (Validator).
## 2026-10-16 — D2: dsh в режиме реализации (✅ успех)

**Задача:** usage-запись для `run_reverse_check` — RC не логировался
в `usage.jsonl` (наша E39-находка).

**Контекст:** dsh **уже видел** наш Validator (не смогли откатить).
**НО** задача — **новая** (usage-записи), в **нашем** коде **не было**.

**Что dsh сделал:**

- **Проверил** факт (grep по `reverse.py` — нет `append_usage`).
- **Нашёл** образец: `_accumulate_cost_and_usage` в `tool_loop.py`.
- **Заметил** расхождения в **моём ТЗ**: список полей ≠ сигнатура
  `append_usage` (большинство — в `CostBreakdown`). Адаптировал.
- **Реализовал**: 23 строки, `cost=cost`, `action="agent:reverse_check"`.
- **E2E** в **temp-каталоге**: мок LLM + реальный `usage.jsonl`
  + реальный CLI.
- **Нашёл** pre-existing баг путей: `usage` читает **относительно**
  CWD, `append_usage` — **относительно** `project_root`.
- **Нашёл**, что `usage --by-action` **не** существует (наш ТЗ **неверен**).

**Задача 3 (тесты):**

- dsh **сам** добавил 2 теста (78 строк).
- **Mutation-check**: временно **вырезал** `append_usage` → тест
  **упал**, восстановил → прошёл. **Доказал** регрессию.
- **Проверка** `--collect-only` — **2 новых**, 489 **не** изменены.

**Итог:**

- **1 turn, 38 steps, ~0.25 RUB** (cache hit 98%).
- **491 passed**, ruff/mypy clean.
- **2 коммита** (`6b71dbd`, `8afc4e6`), merge `9cdff16`.

**Вывод:** dsh **справился лучше** ai-coder:
- **глубже** проверяет (E2E в изоляции);
- **адаптирует** ТЗ к **реальному** коду;
- **находит** баги **нашей** документации.

---

## 2026-10-16 — D1.5: Validator реализован (✅)

**Итог D1 + E39:** план Validator от dsh (D1) **реализован** в ai-coder
через 3 маленьких issue + E2E-проверку.

**Что сделано (issue 10.71):**
- `decompose_reverse_check: bool = False` в конфиге.
- `_collect_subtask_diff(project_root, baseline_sha, untracked_before)`
  в `reverse.py` — изолированный diff подзадачи.
- Baseline через `git stash create` — **работает** как снапшот «до».
- RC **после** retry-блока, до `max_cost`-проверки.
- Ключи `reverse_ok/problems/suggestion/cost_rub` в `subtask_results[-1]`.
- Колонка RC + секция `## Reverse-check` в `report.md`.
- Флаг `--decompose-reverse-check` в CLI.

**Что отложено (второй шаг):**
- Политики `fail` / `rollback` для `ok=False` — opt-in, не сделано.
- Retry-с-фидбеком — не сделано.
- `success` **не** меняется на `verified` — добавили **отдельные** ключи
  (`reverse_*`), `success` по-прежнему **verify-based**.

**Находки D1 подтвердились:**
- Diff-изоляция — **главный риск.** Решена через baseline.
- Точка вставки — после retry. **Проверено.**
- Fail-open — сохранён (`parse_error → ok=True`).
- `success` **не трогаем.**

**Проверки:** 489 passed, ruff/mypy clean, merge `23d785c`,
E2E в `/tmp/validator-e2e4`.

**Связь:** `docs/experiments.md` → E39, `CHANGELOG.md` → 10.71,
`docs/autonomy.md` → раздел 9.

**Остаток Направления 12:** Feedback loop (summary в N+1),
`spawn_subagent`.

---

## 2026-10-16 — D1: dsh как архитектурный ревьюер (✅)

**Задача:** понять, может ли `dsh` помочь в планировании Validator
(Направление 12) — LLM-проверка каждой подзадачи в `--decompose`.

**Метод:**
- Web UI `dsh`, Standard mode, Workspace Write.
- Модель: `DeepSeek-V41-FlashHigh`.
- Промпт (read-only, с guardrails):
  > Прочитай `ai_coder/agent/reverse.py` + `ai_coder/agent/decomposer.py`.
  > Не правь код. Предложи план адаптации `run_reverse_check` для
  > проверки КАЖДОЙ подзадачи в `run_agent_decompose`. Структура ответа:
  > 1) что делает `run_reverse_check`; 2) где точка вызова;
  > 3) какие данные нужны; 4) как результат влияет; 5) риски.

**Что `dsh` сделал:**
- Прочитал **5+ файлов** (не только 2 указанных): `reverse.py`,
  `decomposer.py`, `tool_loop.py`, `config.py`, `cli.py`, `tests/`.
- Дал **структурированный ответ** (5 пунктов, ~400 строк).
- **Не правил код** (guardrails сработали).

**Что `dsh` нашёл — то, что мы пропустили:**

1. **Diff-изоляция — главный риск.** `_collect_diff` собирает
   `git diff HEAD` по **всему worktree**. В decompose нет автокоммита —
   подзадача 3 увидит правки подзадач 1 и 2. Валидатор будет судить
   **не тот diff**.
   - Решение A (рекомендация): baseline-снапшот через `git stash create` —
     даёт commit-объект, **не трогая** worktree.
   - Решение B: скоуп по backup-манифесту.
   - Решение C: MVP-заглушка (неверно для подзадач 2+).

2. **Точка вставки — после retry-блока, не до.** Строки 333-346
   в `decomposer.py` — `subtask_results[-1] = {...}` (wholesale-replace).
   Вставка **до** retry → новая запись **потеряется**. Правильно —
   между 346 и 348, под условием `loop_result.success and not dry_run`.

3. **`ok=False` — политика (3 уровня), не одно поведение.**
   - `warn` (default) — проблемы в `subtask_results`, продолжаем.
   - `fail` (opt-in) — `dec_result.parse_error`, return. **Но** fail-ветка
     354-439 **не сработает** (`loop_result.success=True`) — нужен
     **отдельный** блок.
   - `rollback` (opt-in) — откат + один retry с фидбеком («Замечания
     ревьюера: ...»). Самое полезное, но дорого.

4. **Не менять `success`** — добавить `verified`. `success` читают
   существующие тесты + `--rollback-on-fail` ходит по `prev.get("success")`.
   Изменение семантики → сломаем откат и тесты.

5. **Rollback при `ok=False` — опасен.** Откат подзадачи N **сломает**
   N+1 (писались поверх N). Backup — по файлам, **не** «точка во
   времени». Дефолт — warn без отката.

6. **Стоимость — заметная.** По дефолту `reverse_check_model` →
   `decompose_model` = **v4-pro** → +v4-pro **per подзадача** — дороже
   самого loop'а на flash. Митигации: явный `model`, учёт в
   `remaining`/`max_cost`, **пропуск при `applied_ops == 0`** / пустом diff.

7. **Fail-open сохранить.** `parse_error → ok=True`. Иначе флаки LLM
   **завалят** хорошие подзадачи. «Fail» — только при **валидном**
   `ok=False`.

8. **Тесты — конкретный список.** Дефолт `False` → существующие
   не ломаются. Если по дефолту `True` → `test_run_agent_decompose_retry_cost_summation`
   упадёт (`0.44`). Тесты на форму `subtask_results` — проходят, если
   **не** менять `success`. `report.md`-тесты — только существование
   файла, новая колонка/секция безопасна.

**Что `dsh` пропустил (мы додумали):**
- Новый промпт `agent_subtask_reverse_check` (контекст подзадачи
  отличается от верхнего RC).
- CLI-флаг `--decompose-reverse-check` — нужен ли **отдельный**?
- GUI — что менять (чекбокс? связь с `--reverse-check`?).

**Сравнение с нашим планом:**

| Пункт | Наш план | dsh | Итог |
|---|---|---|---|
| Diff | «подзадачи» | **изоляция через baseline** | dsh нашёл |
| Точка вставки | «после finish» | **после retry, до max_cost** | dsh уточнил |
| `ok=False` | «semantic_failed» | **3 политики** | dsh расширил |
| `success` | менять | **не менять**, +`verified` | dsh защитил |
| Rollback | простой | **опасен**, opt-in + retry | dsh предупредил |
| Стоимость | «второй вызов» | **+v4-pro per подзадача** | dsh детализировал |
| Тесты | «тест» | **конкретный список** | dsh дал |

**Уроки:**
- **dsh — архитектурный ревьюер**, сильнее `ai-coder` в **планировании**.
- **Flash справился** с разведкой 5+ файлов — **дёшево** (~0.1-0.2 RUB).
- **Промпт с guardrails + структурой (1-5)** — работает: модель
  не «действует», отвечает по делу.
- **dsh находит архитектурные риски**, которые `ai-coder` не делает
  (у нас нет фазы «ревью плана»).
- **Разделение труда:** dsh — план, ai-coder — исполнение.

**Статистика:** 1 turn, 15 steps, 208 tok/s. 416K токенов
(кумулятивно), cache hit 89%, context used 5%.
См. `docs/dsh/D1/analysis.md` -> «Статистика dsh».

**Стоимость:** ~1 RUB (Flash, off-peak).

## Что взять в `ai-coder` (кандидаты)

По итогам D1 — идеи, которые можно реализовать в `ai-coder`:

1. **Reasoning logging** — 💎 (подтверждено API docs)
   - **DeepSeek API** отдаёт `reasoning_content` (отдельное поле).
   - **Thinking mode — default on** (effort `high`) — мы **не отключаем**.
   - **Сейчас:** `LLMResponse.content` — только финальный ответ.
     Reasoning **теряется** (но **оплачивается**).
   - **Что:** `LLMResponse.reasoning_content` + `reasoning_tokens`
     + логировать в `step-N.md`.
   - **Дополнительно:** `reasoning_effort` (low/high/max) — управлять.
   - См. `docs/thinking-mode.md`.
   - **Польза:** отладка, оценка качества, эксперименты.

2. **Параллельные tool calls** — 💎
   - dsh: 2 read за шаг (24 calls / 15 steps).
   - У нас: 1 tool за итерацию.
   - **Что:** `parse_response` — массив tool calls; `tool_loop` — параллельно.
   - **Польза:** ×1.5-2 по итерациям (быстрее, дешевле).

3. **`grep` / `glob` как инструменты** — 💎
   - dsh: первоклассные tools (`grep`, `glob`).
   - У нас: через `run_shell` (whitelist).
   - **Что:** добавить `grep` (и `glob`) в tool set.
   - **Польза:** проще для модели, меньше ошибок.

4. **Event-sourced JSONL (append-only)** — 💎
   - dsh: `session.v4.jsonl` (seq, time, type, data).
   - У нас: `.ai-out/step-N.md` (человекочитаемо, но не replay).
   - **Что:** добавить JSONL-лог **параллельно** с MD.
   - **Польза:** replay, fork, programmatic analysis.

5. **`turn` / `step` / `session` — явные сущности** — 💎
   - dsh: явная иерархия.
   - У нас: `run_tool_loop` + `run_agent_decompose`.
   - **Что:** явная иерархия в логе.
   - **Польза:** легче анализировать.

**Приоритет (мой):**
1. **Reasoning logging** — простая, высокая ценность.
2. **`grep` / `glob`** — средняя, полезно.
3. **Параллельные calls** — средняя.
4. **JSONL-лог** — большая, стратегическая.

**Связь:** см. `docs/dsh/D1/analysis.md` → «Что взять» (детали).

---
