# Эксперименты

Журнал **экспериментов** с tool loop и агентом. **Не TODO** (что делать),
**не CHANGELOG** (что сделано). Это **знание** — что пробовали, что вышло,
какие выводы.

---

## 2026-10-14 — E21: GUI — чекбокс reverse-check (агент) — ✅ но дорого

**Гипотеза:** простая GUI-задача (2 файла, ~5 строк) — агент
справится за ~0.2 RUB.

**Задача:** добавить чекбокс `reverse-check` в форму + `--reverse-check`
в `_build_command`/`build`/`run`/`_build_argv`.

**Команда:**

    ai-coder agent . --issue issues/2-gui-reverse-check.md \
        --tool-loop --apply --max-iterations 15 --max-cost-rub 1 \
        --reverse-check

**Результат:**
- ✅ **Всё сделано правильно**: 9 строк (6 в app.py, 3 в index.html).
- ❌ **НЕ успех:** `stopped_reason="max_cost"`, 1.06 RUB > 1.0.
- ⚠️ 12 итераций, **reverse-check не запустился** (success=False).

**Разбор итераций:**
1-2. `read_file` ×2 — разведка (index.html + app.py).
3. `edit_file` index.html — чекбокс. ✅
4-8. `edit_file` ×5 в app.py — по одному месту.
9. `parse_error` — retry.
10. `run_shell grep` — самопроверка.
11. `run_shell rejected` — метасимволы `;`/`|`.
12. `read_symbol` — читал `_build_argv`.
**Стоп по бюджету.**

**Выводы:**

1. **Задача решена** правильно — 9 строк, все места.
2. **Дорого:** 1.06 RUB вместо ~0.2 (×5).
3. **Причина:** 5 `edit_file` подряд вместо 1 большого.
   Каждая правка = LLM-вызов.
4. **Reverse-check не запустился** — success=False (max_cost).
5. **Self-check** (grep, read_symbol) — правильная привычка,
   но **удорожает**.

**Сравнение:**
- **E19** (4 файла, связанные, --decompose) — 16.87 RUB, 1/4.
- **E21** (2 файла, простые, --tool-loop) — **1.06 RUB**, ✅ 100%.
- **Прогресс:** простая задача — **сделана**, но **дорого**.

**Правило:** даже простая GUI-задача — **вручную** дешевле.
Агент — **только** когда лень или много однотипных.

**Побочно:** `run_shell rejected` — агент попробовал grep с `;`/`|`.
Может, стоит **подсказать** в промпте: «без метасимволов».

---

## 2026-10-14 — E20: reverse-check — ✅ работает

**Гипотеза:** после `finish(success)` LLM перечитывает diff
и находит семантические ошибки, которые verify не ловит.

**Команда:**

    ai-coder agent "Функция add должна возвращать сумму a+b. Почини." \
        /tmp/rc-test --tool-loop --apply --reverse-check --max-cost-rub 1

**Результат:**
- ✅ tool loop: 2 итерации (read_file → edit_file).
- ✅ verify (pytest): пройдено.
- ✅ **reverse-check:** запустился, `ok=True`.
- ✅ Стоимость: **0.1252 RUB** (tool loop ~0.087 + reverse-check 0.0378).

**Report (`report.md`):**

    ## Reverse-check
    - ✅ Проблем не найдено.
    - **Стоимость:** 0.037808 RUB

**Тесты:** +8 (7 unit + 1 dataclass) → **427 passed**.

**Что работает:**
- Флаг `--reverse-check` (требует `--tool-loop`).
- Запуск после `success=True` + `stopped_reason="completed"`.
- Сбор diff через `git diff HEAD`.
- LLM-запрос (v4-pro) → JSON `{ok, problems, suggestion}`.
- Fail-safe: при ошибке парсинга / LLM — `ok=True`.
- Стоимость суммируется в общий bill.
- Секция `## Reverse-check` в `report.md`.
- Warnings при `ok=False`.

**Что не покрыто в E2E:**
- «Плохой» сценарий (reverse-check находит проблему) —
  покрыт **unit-тестом** `test_reverse_check_parses_problems`.

**Побочное наблюдение (TODO):**
- Verify на проекте **без тестов** падает с `exit code: 5`
  («no tests ran»). Это **не ошибка**, но прогон считается
  провалом → reverse-check не запускается.
  **TODO:** в `run_verify_commands` — `exit 5` для pytest
  считать успехом (с предупреждением).

**Цифры:**
- Стоимость reverse-check для маленького diff: **0.0378 RUB**.
- Дешевле прогноза (0.1–0.3 RUB).

**Открыто:**
- reverse-check **не работает при `--decompose`** (MVP).
- Промпт — итеративный, может давать ложные срабатывания.

**Связь:** reverse-check закрывает 6 паттернов
«куски ок, связка — нет» (A.0/A.2/A.3/A.4/E16).
Не закрывает **связанные правки** (JS↔Python↔HTML) —
см. `docs/tools.md` → «Когда НЕ использовать tool loop».

---

## 2026-10-14 — E19: A.11 через --decompose + баг `--max-cost-rub`

**Гипотеза:** 4-файловая GUI-задача (app.py, index.html, help.html,
style.css) через `--issue` + `--decompose`.

**Команда:**

    ai-coder agent . --issue issues/1-gui-run-commands.md \
        --tool-loop --decompose --apply \
        --max-iterations 15 --max-cost-rub 2.0

**Результат:**
- ✅ 1/4 подзадач (app.py, 33 строки, без ошибок).
- ❌ index.html — провал (flash 15 ит. → v4-pro retry 15 ит.).
- ⏸️ help.html, style.css — не запускались (стоп после fail).

**Стоимость: 16.87 RUB** при заявленном лимите 2.0.
**Превышение ×8.4.**

### Найденный баг (🔴 высокий)

**`--max-cost-rub` молча игнорировался при `--decompose`.**

`cli.py`, стр. 992 и 1674: `max_cost_rub=decompose_max_cost_rub`.

`decompose_max_cost_rub` — отдельный флаг (`--decompose-max-cost-rub`),
по умолчанию `None`. Если не задан — `run_agent_decompose` получал
`max_cost_rub=None` → все проверки бюджета пропускались
(стр. 774 `if max_cost_rub is not None`, стр. 872 — то же).
`--max-cost-rub` действовал только на простой tool-loop.

### Разбор usage (хронология)

    09:55:57  v4-pro   agent:decompose   0.85 RUB  (планировщик)
    09:55:59  flash    agent:tool1..11  ~2.10 RUB  (подзадача 1, ✅)
    09:57:02  flash    agent:tool1..15  ~2.20 RUB  (подзадача 2, fail)
    09:57:49  v4-pro   agent:tool1..15 ~11.50 RUB  (retry, fail)
    ---
    итого:                              16.87 RUB

### Фикс (10.44, этот же день)

**`cli.py`, стр. 992 и 1674:**

    max_cost_rub=decompose_max_cost_rub or max_cost_rub,

**+ help:** «Если не задан — наследует --max-cost-rub.»

### Выводы

1. **Финансовый баг:** `--max-cost-rub` молча игнорировался при
   `--decompose`. Хуже отсутствия флага — пользователь думал,
   что защищён.
2. **decompose не спасает против JS↔Python** (подтверждение E17):
   подзадача index.html (форма + JS + parseCommand) проваливается
   даже отдельным файлом.
3. **app.py (чистый Python) — агент делает правильно** (33 строки
   без ошибок с первого раза).
4. **Правило:** GUI-задачи вручную; связанные правки вручную;
   decompose — не универсальная защита.

### Связь

- E18 (3 файла, простые, tool-loop) = 0.67 RUB ✅.
- E18.3 (3 файла, сложные, tool-loop) = 1.05 RUB, 2/3.
- **E19** (4 файла, связанные, decompose) = 16.87 RUB, 1/4 + баг.

---

### Почему index.html — сложно для агента (анализ подзадачи 2)

Подзадача 2 (index.html) — **провал**. Не случайность, а **системная сложность**.

#### Что требовалось в index.html

1. Добавить `<select name="task_type">` **перед** полем `goal`.
2. Добавить `<select name="run_action">` (7 опций), скрытый.
3. Обернуть **3 разных места** (`goal`, `mode`, `flags`) в `<div class="agent-only">` — с сохранением вёрстки.
4. Написать JS `applyTaskType()` — toggle видимости через `classList.toggle("field-hidden", bool)`, listener на `change`, вызов при загрузке.
5. Обновить `parseCommand` (~80 строк) — **вставить ветку** `else if (result.action === "run")` **внутрь** существующей функции. Не сломать ветку `agent`.
6. Обновить обработку `pending_command` — установить `task_type`/`run_action`, вызвать `applyTaskType()`.

**Каждый пункт зависит от остальных.** Если в `parseCommand` добавили `run_action`, а в `pending` забыли использовать — команда из справки **не заполнит форму правильно**.

#### 4 причины сложности

**1. Связанность 6 правок в 1 файле.**

В `app.py` агент делал **одну изолированную функцию**: входные — параметры, выходные — return. Просто.

В `index.html` — **паутина**:
- HTML-элемент `name="task_type"` → форма → `app.py` должен принять.
- JS `parseCommand` → зависит от **формата команды**.
- JS-переключатель → зависит от **классов** в HTML.
- `pending` → зависит от **структуры** `result` в `parseCommand`.

Агент не держит в голове всю паутину. Правит **одно место**, потом **следующее** — и они **расходятся**.

**2. JS/HTML — «шумный» язык для LLM.**

Python: отступы вместо скобок, читаемые блоки, легко балансировать структуру. JS: `{`, `}`, `()`, `[]`, `;` — легко ошибиться, потерять закрывающую скобку. Отсюда `parse_error: tool JSON no '{' found` в логе E19.

**3. Нет обратной связи.**

В Python-задаче агент запускает `pytest` → видит `ok`/`fail`. Реальный сигнал.

В HTML/JS **запустить нечего**. Он не видит, что форма сломалась: поля пропали, `run_action` не появляется. Просто пишет код и **надеется**.

**4. Промпт > 15 строк.**

В issue-файле было ~60 строк. Агент **прочитал**, но удержал в голове только **часть**: запомнил `select task_type`, забыл про `parseCommand`, сделал `parseCommand` плохо, не помнил про `pending_command`, зациклился.

История раздувалась (`p=3000` → `p=15000`), полезное **терялось** в шуме.

#### Закономерность по экспериментам

| Эксперимент | Что делали | Связанность | Результат |
|---|---|---|---|
| **E18** | GUI A.9 — 3 файла (app.py + help.html + index.html) | низкая (каждый файл отдельно) | ✅ 0.67 RUB, без правок |
| **E18.3** | GUI A.10 — 5 однотипных правок в help.html + JS + CSS | средняя (5 правок в 1 файле) | 2/3 файла, 1.05 RUB |
| **E17** | GUI A.4 — checkbox → select (2 связанных файла) | высокая (JS↔Python) | 40%, 0.81 RUB |
| **E19** | GUI A.11 — 4 файла через decompose | очень высокая (JS↔Python↔HTML) | 1/4 подзадач, 16.87 RUB |

**Вывод:** чем больше «связанности» — тем хуже. Decompose (разбиение на подзадачи) **не спасает** — связь между файлами никуда не девается.

#### Что делать (в будущем)

Это **не приговор**, а известное ограничение. Идеи:

1. **Специализированные агенты** (Python-агент, HTML-агент, JS-агент, CSS-агент) — каждый со своим промптом. ~2 недели.
2. **Реактивный подход** — виртуальный браузер (playwright): агент вносит правку → симулирует клик → проверяет, что поле появилось. ~3-4 недели.
3. **Шаблоны правок** — готовые рецепты («checkbox → select», «обернуть в контейнер»). Агент выбирает и заполняет. ~1-2 недели.
4. **Обучение по образцу** — показать правильную правку в этом же файле, агент повторит для других. ~3-5 дней.

**Правило сейчас:** связанные правки (JS↔Python↔HTML) — **вручную**. Чистый Python — **агенту**.

---

## 2026-10-14 — E18.3: /help кнопка «в форму» — ❌ 2/3 файла

**Гипотеза:** агент справится с 3-файловой задачей:
- help.html — 5 однотипных правок + новый script.
- index.html — большой JS-парсер (parseCommand ~80 строк).
- style.css — 4 CSS-класса.

**Промпт:** структурированный, 3 файла, ~50 строк.

**Результат:**
- **7 итераций, 1.0542 RUB, --max-cost-rub 1.0 остановил.**
- **2 из 3 файлов** — help.html + index.html сделаны правильно.
- **style.css — не тронут** (бюджет кончился).

**Что сделал правильно:**
- help.html: 5 блоков в div.example + .use-example с data-cmd,
  первый блок (3 команды) НЕ тронут, script в конце.
- index.html: parseCommand полный — токенизация с "...", action,
  goal, path, --tool-loop/--dry-read/--max-cost-rub/--apply/--commit,
  advanced_flags. При загрузке — заполнение 8 полей + notice.

**Флейки:** 2 (run_shell rejected на метасимволе, missing_args).

**Выводы:**

1. **E18.3 != E18.** E18 — «3 файла, каждый простой» -> 0.67 RUB.
   E18.3 — «5 однотипных правок + большой JS + CSS» -> выход за 1 RUB.
2. **Правило:** если однотипных правок >= 3 в одном файле —
   flash тратит много итераций (5 блоков = 5 edit_file).
3. **Урок:** для таких задач — --decompose (v4-pro разобьёт на
   3 подзадачи: help.html / index.html / style.css).
4. **CSS** — «мелочь», но именно её не успел. В следующий раз
   ставить CSS-правку первой (или отдельной задачей).
5. **max-cost-rub работает** — остановил на 1.0542 RUB.

**Стоимость E18.3:** 1.0542 RUB + ~15 мин ручной доделки style.css.

**Связь:**
- E18: 3 файла (простые) -> 0.67 RUB.
- E18.1: 1 файл (секция) -> 0.18 RUB.
- E18.2: 1 файл (блок) -> ~0.2 RUB.
- E18.3: 3 файла (сложные) -> 1.05 RUB, 2/3.

---

## 2026-10-13 — E18: агент на GUI-задаче (3 файла) — ✅ без правок

**Гипотеза:** агент справится со страницей /help (справка) —
3 файла (2 существующих + 1 новый), если промпт структурирован
(файлы + содержимое + стиль).

**Задача:** добавить `/help` со справкой по режимам/опциям.
- `app.py` — роут `GET /help`.
- `help.html` — новый шаблон.
- `index.html` — ссылка в nav.

**Промпт:** 16 строк (⚠ система предупредила: > 15, риск флейка).

**Результат:**
- **7 итераций, 0.6728 RUB, 0 флейков.**
- ✅ **Все 3 файла сделаны правильно**, без правок вручную.

**История:**
| # | Инструмент | Что |
|---|---|---|
| 1 | read_file | `app.py` (структура) |
| 2 | read_file | `stats.html` (образец шаблона) |
| 3 | read_file | `index.html` (nav) |
| 4 | read_file | `style.css` (классы) |
| 5 | edit_file | `app.py` (роут) |
| 6 | write_file | `help.html` (7823 chars) |
| 7 | edit_file | `index.html` (ссылка) |

**Что сделал правильно:**
- `TemplateResponse(request, "help.html", {})` — **правильный
  порядок аргументов** (в A.0 агент путал — урок усвоен).
- `request: Request` в сигнатуре роута.
- Прочитал `style.css` → использовал `.panel` + `.markdown-body`.
- В `help.html` — 4 секции с `<table>` (стилизуется
  `.markdown-body table` из A.6).
- `verify` (pytest) — прошёл с первого раза.

**Выводы:**

1. **GUI-задача на 3 файла — посильна агенту**, если:
   - промпт структурирован (файлы + что делать + стиль);
   - задача **не связная** (нет JS↔Python согласования, как в A.2/A.4);
   - агент **читает CSS** перед правками.
2. **4 read_file подряд** — не флейк, а **разведка**. Агент
   собрал контекст, потом **сразу** сделал 3 правки.
3. **0.6728 RUB** — дороже, чем A.3 (0.28), но там было 2 файла.
   **×2.4 к стоимости** за +1 файл — приемлемо.
4. **Правило «промпт < 15 строк»** — система предупредила
   (16 строк), но **флейка не было**. Видимо, структура
   (явные «Файлы: 1. 2. 3.») помогает модели удержать фокус.
5. **A.0-баг (TemplateResponse) не повторился** — важный сигнал:
   модель **запоминает** API, если правило 10 в промпте
   `agent_tool_json` (10.39) **явно** говорит «сверься с версией».

**Связь с этой сессией:**
- A.2 (SSE) — 8 итераций, 1.26 RUB, 1 фикс вручную.
- A.4 (связки) — 10 итераций, 0.81 RUB, 40%.
- **E18 (новый)** — 7 итераций, 0.67 RUB, **0 фиксов**.

**Стоимость E18:** 0.6728 RUB + 0 ручных правок.

---

## 2026-10-13 — E17: GUI A.4 — checkbox → select (2 связанных файла)

**Гипотеза:** агент справится с заменой `checkbox dry_run` → `select
check_mode` в GUI (2 файла: `index.html` + `app.py`).

**Промпт:** 12 строк, без backticks.

**Результат:**
- **10 итераций, 0.81 RUB**, `--max-cost-rub 0.7` **остановил**.
- Агент сделал **~40%**: `index.html` (checkbox → select) + `build()`
  Form (`dry_run: bool` → `check_mode: str`).
- **Не успел:** `_build_command`, `_build_argv`, `/run`, JS
  `buildParams()` — эти 4 места **доделаны вручную** (~20 мин).

**Что сделал правильно:**
- `index.html`: `checkbox` → `select` с 3 опциями (`normal`, `dry-run`,
  `dry-read`), все подписи корректны.
- `build()`: `Form(dry_run=False)` → `Form(check_mode="normal")` +
  проброс в `_build_command(check_mode=check_mode)`.

**Флейки:**
- `run_shell ❌` × 3 (метасимвол, no output).
- Итерации 1-2 — `read_file` + `run_shell` (rejected).
- Итерации 4-5 — `run_shell` с `(no output)`.
- Итерации 6-9 — grep + read_file (уже **работа**).
- Итерация 10 — последний `edit_file`.
- **10 из 10 итераций** — **все** осмысленные, но **бюджет кончился**.

**Причина:** **связанные** правки (JS ↔ Python ↔ Form). Агенту нужно
**согласовать** 5+ мест. Он **успел** 2, **остальные** — не хватило.

**Выводы:**

1. **Для связанных правок (JS ↔ Python) — вручную** или `--decompose`.
2. **Промпт 12 строк, файлов 2** — **всё равно** флейки на старте
   (2-5 итераций впустую).
3. **`--max-cost-rub` работает** ✅ — остановил на 0.7 RUB.
4. **`index.html` правки** — **лёгкие** (1 `edit_file`). **`app.py`
   согласование** — **сложное** (4 места).

**Побочно — `--dry-read` работает в живом прогоне.**

Задача «Найди все TODO в `ai_coder/tools.py`» (через GUI):

| Флаг | run_shell | Результат |
|---|---|---|
| `--dry-read` | `✅` (grep **выполнен**) | «TODO не найдено» (честно) |
| `--dry-run` | `✅ (simulated)` | зациклился (E15) |

**`(no output)`** — не баг: `grep` вернул exit 1 (**не найдено**).
Агент **правильно** интерпретировал.

**Идея для TODO:** в `tool_run_shell`, если `returncode == 1` и
`stdout == ""` — вернуть `ok=True, output="(no matches)"`. Сейчас
`ok=False, output="(no output)"` — **агент** понимает, **пользователь** —
может подумать «ошибка».

**Стоимость E17:**
- Агент: **0.81 RUB** (40%).
- Живой `--dry-read`: 0.167 RUB.
- **Итого:** ~1.0 RUB + ~20 мин ручных правок.

### Связь с A.3 (предыдущая)

A.3: агент **4 итерации, 0.28 RUB**, ✅ — **всё** сделал (select
`max-cost-rub` + `copy-output-btn`).

**A.4 — сложнее** (2 файла, **связанные** правки). Разница — **×3
по стоимости**.

---

## 2026-10-13 — E16: --dry-read — read выполняется, write блокируется

**Гипотеза:** агент справится с флагом `--dry-read` (3 файла + тесты).
Побочно: `--dry-read` **решает** проблему `--dry-run` для read-задач.

### Часть 1 — разработка флага (агент, --tool-loop)

**Задача:** добавить `--dry-read`: read-команды выполняются реально,
write_file/edit_file — блокируются.

**Промпт:** 18 строк (больше 15 — риск).

**Результат агента:**
- **21 итерация, 2.08 RUB**, `--max-cost-rub 2` **остановил**.
- `tools.py` + `agent.py` — **готовы** (42 строки, **5/5 качества**).
- `cli.py` + тесты — **не успел** (задача 3-файловая).

**Причина:** флейки на старте (**10 из 21 итераций**):
- `parse_error` × 1 (tool JSON no `{`).
- `missing_args` × 3.
- `run_shell rejected` × 1 (метасимвол `|` в `grep ... | head`).

**Фиксы вручную (~30 мин):**
- `cli.py`: флаг `--dry-read` + валидация + проброс (6 вызовов).
- Проброс в `_run_chain` и `run_agent_decompose` (не были готовы).
- 8 тестов.

**Что сделал агент правильно (без правок):**
- `READ_ONLY_COMMANDS` (7 команд), `READ_ONLY_GIT_SUBCOMMANDS` (7).
- `_is_read_only_command` с `try/except`, git с проверкой `len >= 2`.
- `execute_tool`: проверка **ПЕРЕД** dry-run, try/except вокруг `fn`.
- `agent.py`: ровно 2 строки (сигнатура + проброс).

**Итог части 1:** 2/3 файлов за 2.08 RUB + 30 мин ручной доделки.

### Часть 2 — доказательство, что флаг решает проблему (E15)

**Задача:** «Найди все вхождения `READ_ONLY_COMMANDS` в `ai_coder/tools.py`».

**Прямое сравнение:**

| Флаг | Итерации | RUB | Результат |
|---|---|---|---|
| **`--dry-read`** | **1** | **0.075** | ✅ **нашёл** (3 вхождения) |
| **`--dry-run`** | **8** | **0.409** | ❌ max_iterations |
| **Разница** | **×8** | **×5.5** | **✅ vs ❌** |

**Что было с `--dry-run`:**
- Итерации 1-5: агент **5 раз** дёргает `grep` → получает
  `(dry-run) RAN ... (simulated OK)`. **Зацикливается.**
- Итерации 6-8: пробует через `read_file` (работает в dry-run),
  но `max_iterations=8` — **не успел**.
- **Стоимость 0.41 RUB** — впустую.

**Что было с `--dry-read`:**
- **1 итерация:** `run_shell grep` → **реальный вывод** → finish.
- **0.075 RUB.**

**Выводы:**

1. **`--dry-read` — не просто фикс, а фундаментальное улучшение.**
   Read-задачи **работают** без риска write.
2. **`--dry-run` для read-задач — антипаттерн.** Агент зацикливается
   на симуляции.
3. **`--dry-read` дешевле** в 5.5 раз и **быстрее** в 8 раз.
4. **Баг-паттерн `--dry-run`** (из `docs/tools.md`): «модель перечитывает»
   — **распространяется и на `run_shell`**.

### Часть 3 — процесс

**Баг-паттерн (как в E15):** «мой regex задел 6 мест вместо 2».
Скрипт `cli.py` пробросил `dry_read` в **6 вызовов** — включая
`_run_chain` и `run_agent_decompose`, которые `dry_read` **не принимали**.
**Пришлось** добавить параметр и туда. **Итог:** лучше, чем откатывать
(теперь `--chain --dry-read` и `--decompose --dry-read` **работают**).

**Стоимость E16:**
- Агент: **2.08 RUB** (разработка, 60%).
- Тесты (2 запуска): **0.075 + 0.41 = 0.485 RUB**.
- **Итого:** ~2.6 RUB + ~30 мин ручной работы.

### Связь с автономностью

- **`--max-cost-rub` работает** ✅ — остановил агента на 2 RUB.
- **Для 3+ файлов — `--decompose`** (в E12 decompose справлялся с 5+
  файлами за 1.22 RUB).
- **Промпт < 15 строк** — критично (у нас 18 → флейки).
- **Reverse-check** (Уровень 2.5 из `autonomy.md`) — снова актуален:
  «мой regex задел 6 мест вместо 2» — LLM бы **увидел** в diff.

---

## 2026-10-13 — E15: агент на SSE + subprocess + stream (GUI A.2)

**Гипотеза:** агент справится с SSE (`StreamingResponse`) + `subprocess.Popen`
+ process management, **если промпт явно указывает API**.

**Задача:** добавить в веб-панель (GUI A.2) запуск команды `ai-coder agent`
со стримингом вывода в браузер.

**Промпт:** 14 строк, **явно указано**:
- `sys.executable -m ai_coder.cli`, не `ai-coder`;
- `subprocess.Popen(..., stdout=PIPE, stderr=STDOUT, text=True, bufsize=1)`;
- `StreamingResponse(media_type="text/event-stream")`, формат `data: <строка>\n\n`;
- `RUNNING: dict[str, Popen]` + `POST /stop/{run_id}` (SIGTERM).

### Результаты

| Задача | Итераций | RUB | Фиксов после |
|---|---|---|---|
| A.0 (скелет) | 13 | 0.93 | 2 |
| A.1 (форма) | 6 | 0.95 | 2 |
| **A.2 (SSE + subprocess)** | **8** | **1.26** | **1** |

**Что сделал правильно (без фиксов):**
- Импорты полные: `subprocess, sys, uuid, signal, shlex, Iterator, StreamingResponse`.
- `_build_argv`: `shlex.split(_build_command(...))` + замена `ai-coder` на
  `[sys.executable, "-m", "ai_coder.cli"]`. **Переиспользует** `_build_command`.
- `_stream_process`: `for line in proc.stdout` → `yield f"data: {line.rstrip(chr(10))}\n\n"`.
  `finally: proc.wait(); RUNNING.pop(...); yield f"data: [exit N]\n\n"`.
- `StreamingResponse(..., headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})`
  — **профессионально**, `X-Accel-Buffering` для nginx reverse proxy.
- `POST /stop/{run_id}`: `SIGTERM`, `proc.poll() is None`, `{"ok": True}`.
- **Не тронул** `cli.py`, `agent.py`, `config.py`.

**Баг агента (1 фикс):**
- `@app.post("/run")` + JS `new EventSource("/run?" + params)` — EventSource
  шлёт **только GET**. `GET /run → 405`. Все **куски** правильные, **связка** — нет.
- Фикс: JS → `fetch("/run", {method: "POST", body: FormData})` + `ReadableStream`.
  `currentAbort.abort()` для прерывания.

### Выводы

1. **Явное указание API в промпте** — решающий фактор. A.0 (13 итер, 2 фикса)
   → A.2 (8 итер, 1 фикс). Гипотеза «агент не справится с SSE» — **опровергнута**.
2. **Агент учится на примерах** проекта (A.0 → A.1 → A.2, тренд: 13 → 6 → 8).
3. **Новый баг-паттерн:** «все куски правильные, связка — нет». Нужен **cross-check**
   (reverse-check из `autonomy.md` → Уровень 2.5).
4. **`X-Accel-Buffering: no`** — агент добавил **сам**. Знание о streaming в FastAPI — есть.

### Побочное наблюдение — `--dry-run` и read-задачи

Второй прогон (goal: «Найди все TODO в проекте», mode: tool-loop, dry-run ON):
- 6 итераций, 0.53 RUB, ✅.
- `run_shell grep -rn TODO` — **симулирован** (`(dry-run) RAN ... (simulated OK,
  command NOT executed)`).
- Агент **честно признал** в summary: «точную локализацию inline-комментариев
  `# TODO` подтвердить не удалось — dry-run не выполняет grep».
- **Вывод:** `--dry-run` **вредит read-задачам** (grep/read не дают результата).
  Нужен `--dry-read` (read-only shell разрешён, write запрещён). См. TODO.

### Стоимость

- A.2: **1.26 RUB**.
- Всего GUI: A.0 (0.93) + A.1 (0.95) + A.2 (1.26) = **3.14 RUB**.

---

## 2026-10-13 — E14: синтетическая верификация `--no-verify`

**Гипотеза:** фикс 10.29 (`--no-verify` отключает `verify_commands`)
работает **на живом проекте**, а не только в мок-тестах.

**Что делали:** песочница `/tmp/verify-test` — `calc.py` с багом
(`add` возвращает `a - b`), `test_calc.py` с двумя тестами:
`test_add` (целевой, падает до правки) и `test_always_fails`
(имитация чужого `legacy/test_url.py` — падает **всегда**).
Конфиг: `verify_commands: ["python -m pytest -q"]`.

**Результаты:**

| Прогон | Флаг | verify запущен? | Итог | Стоимость |
|---|---|---|---|---|
| A | `--no-verify` | **нет** | ✅ `success=True` | 0.0883 RUB |
| B | (без флага) | **да** | ❌ `verify_failed` | 0.0222 RUB |

**Выводы:**

1. **`--no-verify` реально отключает `verify_commands`** — в A нет
   строки «Проверка: ...», verify не запускался.
2. **Без флага verify запускается** — в B виден `✗ python -m pytest -q`
   и `stopped_reason=verify_failed`.
3. **Правки в A и B одинаковые** (агент корректно исправил `add`) —
   значит, фикс 10.29 точечный, tool loop не задет.
4. **E12-баг воспроизведён и закрыт:** чужой тест (`legacy/test_url.py`
   → `test_always_fails`) валит прогон, хотя работа сделана верно.
   `--no-verify` — правильное лекарство.

**E12-перезапуск считается закрытым:** его цель (проверить фикс на
реальном проекте с чужими падающими тестами) достигнута
синтетическим тестом. Внешний `youtube-playlist-downloader` не нужен.

**Стоимость верификации:** 0.11 RUB.

---

## 2026-10-12 — E13: ревью v4-pro чужого проекта + фиксы 1.2-1.4

**Гипотеза:** `ai-coder` справится с ролью **аудитора** и **фиксера** на
**реальном** **чужом** **проекте** — от отчёта v4-pro до правок в коде.

**Что делали:** `youtube-playlist-downloader` (знакомый по E9, E12).
Задача: полное ревью + фикс P0 багов.

### 1. `run explain src/gui.py` — 0.46 RUB (flash)

- 1 файл, 41.9s, 13000 токенов (5324 prompt + 7676 completion).
- flash **разобрал** архитектуру GUI **правильно**: класс `YtdlApp`,
  цепочка `ytdl → transcribe → punctuate → summarize`, авто-логика
  чекбоксов, режимы работы.
- **НО:** модель **заметила**, **что** **файл** **обрезан** (`gui.py` —
  26 KB, лимит ~8K токенов). Для больших файлов — `--max-tokens`
  больше или **чанками**.

### 2. `run suggest_improvements --depth deep -m v4-pro` — 3.79 RUB

- **9 файлов**, 37712 токенов (23209 prompt + 14503 completion), 151s.
- **Отчёт 24 KB**, **35 пунктов** (P0-P3).
- **Нашёл баг 1.1** (обработка всех файлов вместо новых), плюс:
  - **1.2** — имя выходного файла в `summarize.py`.
  - **1.3** — `TypeError` при сортировке канала (`view_count=None`).
  - **1.4** — падение на невалидных `entries`.
  - **1.5** — нет валидации `transcribe_python`.
  - **1.6** — `requirements.txt` без `vosk`/`punctuators`.
  - **1.7** — `.gitignore` (`secret_conf.yaml`, `data/`).

### 3. Фиксы через `--issue` + `--tool-loop` (flash)

- **1.2** (summarize.py): `basename = path.stem.removesuffix("_punctuated")` —
  2 итерации, 0.03 RUB.
- **1.3 + 1.4** (ytdl.py): `(x.get("view_count") or 0)`, фильтр
  `entries = [e for e in entries if isinstance(e, dict) and e.get("id")]` —
  3 итерации, 0.18 RUB.
- **1.7** (`.gitignore`): `data/`.
- **Прогон** на канале `@AndreyMikitin` top=20 **воспроизвёл** баг 1.3
  (`TypeError`), после фикса — работает.

**Потрачено:** ~**4.5 RUB** (ревью + фиксы).

### 4. Побочный баг `ai-coder`: `UnboundLocalError: Table`

При запуске fix 1.2 в `ai-coder` упал:

    UnboundLocalError: cannot access local variable 'Table'

Причина: 4 локальных `from rich.table import Table` внутри функций
перекрывали глобальный импорт (Python scoping — все `Table` в функции
становятся локальными).

Фикс: удалены 4 локальных импорта, оставлен глобальный. Коммит `2a6dba8`.

### 5. Параллельная работа

В `youtube-...` — коммиты `928c545` (`download_single_video` возвращает
тройку), `75671dd` (пропуск существующих). В `ai-coder` — `--split-goals`
(10.26), E11, E12. **Урок:** `git fetch` + `git rebase` после
параллельной работы.

### Итог

`ai-coder` справился с ролью **аудитора и фиксера**:
- Нашёл **4 реальных бага** из 6 известных (1.2, 1.3, 1.4, 1.7).
- Исправил их через `--issue`.
- В процессе починил **свой баг** (`Table`).
- **Стоимость всего цикла:** ~**4.5 RUB** (ревью + фиксы).

**Осталось:**
- **1.5** — валидация `transcribe_python`.
- **1.6** — `requirements.txt`.
- **1.1** — главный баг (обработка всех файлов).

**Ссылки:** коммиты `77272d6` (youtube), `2a6dba8` (ai-coder),
`docs/reviews/v4-pro-2026-10-11-full.md`.

---

## 2026-10-11 — E12: decompose в чужом проекте (ytdl.py) — ✅ но с ложным ✅

**Гипотеза:** `--decompose` справится с рефакторингом функции
`download_single_video` в `youtube-playlist-downloader` (реальный
чужой проект, ~15 файлов). Первый прогон дал verify_failed из-за
чужого теста (`legacy/test_url.py`).

**Что делали:** тот же проект, что в E9. Задача: `download_single_video`
возвращает тройку `(success, stats_str, final_path)`, обновить вызовы.

### Прогон 1 — c verify по умолчанию

    python3 -m ai_coder.cli agent "<goal>" <project> \
        --tool-loop --decompose --no-verify \
        --exclude "legacy/**" --max-cost-rub 4

**Результат:** decompose 2 подзадачи, subtask 1 (ytdl.py) — `parse_error`
+ verify_failed на `legacy/test_url.py`. Стоимость 4.57 RUB.
Правки в `ytdl.py` **были** (18 строк), но verify их отверг.

**Находка 1:** `--no-verify` **не работает** для decompose/tool loop.
`run_agent_decompose` не принимает `verify`, `run_tool_loop` берёт
`cfg.agent.verify_commands` напрямую. Workaround — свой config без verify.

### Прогон 2 — со своим config (/tmp/no-verify.yaml)

    python3 -m ai_coder.cli agent "<goal>" <project> \
        --config /tmp/no-verify.yaml --prompts .../prompts.yaml \
        --tool-loop --decompose --exclude "legacy/**" --max-cost-rub 5

**Результат:** ✅ по отчёту, 2 подзадачи, 8.3701 RUB.

- **subtask 1** (`ytdl.py`) — ✅, изменения корректные:
  - `final_path = None` + `nonlocal final_path`;
  - `if d['status'] == 'finished': final_path = str(Path(...).absolute())`;
  - `return True, stats_str, final_path` и `return False, None, None`;
  - обновлён `download_playlist`, `download_channel_videos` внутри файла.
- **subtask 2** (`gui.py`) — **ложный ✅**, файл **не изменён**.

**Находка 2 (баг):** в `run_agent_decompose` **retry-путь** (v4-pro
fallback) не учитывал `applied_ops > 0`. Строка 852:
`"success": loop_result.success` — без фикса 10.27. Flash флейкнул
(subtask 2, max_iterations), v4-pro retry вернул `finish(success)` без
правок → subtask 2 записан как ✅. Итог — «✅ успех» ложно.

**Находка 3 (твоя, из параллельной сессии):**
`max_iterations` из CLI **не доходил** до decompose (использовался
`cfg.agent.max_steps`). Заменено на `eff_iters`.

### Фикс (10.28)

- **`run_agent_decompose`:** новый параметр `max_iterations: int | None`.
  `eff_iters = max_iterations or cfg.agent.max_steps`. Применён в
  основном и retry-пути.
- **retry-путь:** `"success": loop_result.success and
  loop_result.applied_ops > 0` (как основной путь в 10.27).
- **CLI:** проброс `max_iterations` из `agent_cmd` в
  `run_agent_decompose`.

### Уроки

1. **`--no-verify` и `--verify-commands` не работают** для
   decompose/tool loop (только для простого `agent`). **TODO.**
2. **Retry-путь v4-pro** — отдельная кодовая ветка. Фиксы основного
   пути **не покрывают** её. **Проверять оба.**
3. **Chужой verify (`legacy/test_url.py`) ломает прогон.** Нужно
   уметь запускать на **проект-специфичных** командах.
4. **v4-pro retry** формально «успешен» без правок. Фикс `applied_ops`
   закрывает **основной** и **retry** пути.
5. **Стоимость выросла ×2** из-за retry (8.37 RUB на 2 подзадачи).

### Открытые вопросы

- **`--no-verify` / `--verify-commands`** — не работают в
  decompose/tool loop. Workaround: свой config.
- **E12 перезапустить** после фиксов — проверить, что `gui.py`
  **реально** обновится (или получит ❌, а не ложный ✅).

### Ссылки

- CHANGELOG 10.28.
- TODO.md → «--no-verify / --verify-commands».
- Коммиты: `653d87f` (10.27), `2a6dba8` (Table), `f572288` (10.28).

---

### Финал E12 (после запуска GUI)

Пользователь запустил GUI ютуб-проекта после правки агента.

**Результат полного pipeline (mtime подтверждает — свежие):**

1. **`ytdl.py`** (`20:25`) — скачал `Экономическое чудо Китая за 13 минут`
   (46 MB, `[download] 100%`, `✅ Готово`). Правка тройки **не сломала**.
2. **`transcribe.py`** (`20:26`) — Vosk, `✅ Успешно: 1`.
3. **`punctuate.py`** (`20:26:47`) — 6 файлов `_punctuated.txt`, `Успешно: 6`.
4. **`summarize.py`** (`20:27:33`) — 6/6 `_punctuated_summary.md`, `код: 0`.

**Никаких `ValueError: too many values to unpack`** — все вызовы
тройки **корректны**.

**Финал:**
- ✅ `ytdl.py` — правка **работает**.
- ✅ **GUI проходит все этапы** end-to-end.
- ❌ `gui.py` — **ложная подзадача** от v4-pro. Он вызывает `ytdl.py`
  через `subprocess.Popen`, **не импортирует** функцию. Менять его
  **не надо**.
- 💰 Стоимость: **~13 RUB** (4.57 + 8.37). С правильными флагами
  было бы **~1 RUB**.

**Уроки (расширение E12):**
1. **`--only-path <file>`** — если знаешь, какой файл править.
2. **`--model deepseek-v4-pro` сразу** — для сложных файлов, без retry.
3. **`--plan`** — проверить декомпозицию перед `y`. v4-pro может
   создать **ложные** подзадачи (`gui.py` — не нужна была).
4. **Config без verify** для чужих проектов (verify на
   `legacy/test_url.py` ломал прогон).

---

## 2026-10-11 — E11: self-hosted на своём проекте — ❌ провал

**Гипотеза:** `--split-goals` + `--chain --plan` справятся с задачами
на **нашем же проекте** (реальный self-hosted сценарий).

**Что делали:** ветка `ai-coder-self-test`, `--split-goals` создал
3 issues по трём реальным TODO-пунктам:

1. `applied_count == 0` → `skipped` в `_run_agent_step` (`agent.py`);
2. сохранение `.raw.json` рядом с отчётом (`output.py`);
3. раздел «Конфигурация» в `README.md`.

Затем: `--chain <dir> --tool-loop --plan` + `y`.

### Результат

- **Задача 1:** ❌ **провал** (2 подзадачи).
  - subtask 1 (flash): 10 итераций, **0 правок**, `max_iterations`.
  - subtask 1 retry (v4-pro): 1 итерация, **«Уже сделано»** (ложно).
  - subtask 2 (flash): 10 итераций, **0 правок**.
  - subtask 2 retry (v4-pro): 1 итерация, **«Уже сделано»** (ложно).
- **Задача 1 — стоп.** `--stop-on-fail` остановил chain.
- **Задачи 2, 3 не запускались.**
- **Стоимость: 6.8783 RUB** за 0 правок.
- **chain-журнал пуст:** `.ai-out/ai-coder/chain-<ts>/` создан, но без файлов.

### Что произошло (из журналов tool loop)

**Flash (10 итераций) — был на верном пути:**

1. `read_symbol('_run_agent_step')` → ok;
2. `read_file(issue)` → ok;
3. `run_shell(grep)` → **FAIL**;
4. `run_shell({})` → **FAIL** (пустые args);
5. `read_symbol('apply_plan')` → ok;
6. `run_shell(grep skipped tests)` → ok;
7. `run_shell(grep applied tests)` → **FAIL**;
8. `({})` → **FAIL** (совсем пустой);
9. `run_shell(grep "not applied")` → ok;
10. `read_file(agent.py, 1755-1800)` → ok.

**Итог:** к 10-й итерации **дошёл до места**, но **лимит исчерпался**.
Ему нужно было **ещё 2-3** (`read_file` → `edit_file`).

**v4-pro retry — преждевременный «успех»:**

1. `read_symbol('_run_agent_step')` → ok;
2. **`success: True`, «Уже сделано: при applied_count == 0 шаг
   помечается как skipped»**.

**Проблема:** v4-pro прочитал **только начало** функции, увидел
блок `if not apply: ... skipped = True`, и **решил**, что фича есть.
**Не заметил `if not apply`** — а нужный кейс (apply=True,
applied_count == 0) **не покрыт**.

### Баг — ошибочная диагностика

**Изначально думали**, что `applied_count == 0` при `apply=True`
не помечается skipped. Проверка **опубликовала обратное**: в
`_run_agent_step` **оба** блока корректны:

1. `if not apply: ... return result` — правильный;
2. `if not applied: ... skipped = True; return result` — правильный.

**Второй блок** (после `apply_plan`) ставит `skipped` и **возвращается
до** `result.applied = True`. Инвариант **соблюдён**:
`applied_count == 0` **возможно только** при `applied == []`, а тогда
`skipped = True` и возврат.

**Ирония:** задача E11 была **некорректной** — просила «починить» то,
что уже работает. **v4-pro был прав**, когда сказал «уже сделано».
Flash честно ничего не делал 10 итераций — тоже корректно.

### Реальный баг (обнаружен после разбора)

Не `applied_count == 0`, а **`subtask.success` в `run_agent_decompose`**:

        "success": loop_result.success,  # ← success tool loop ≠ применены правки

Если модель сделала `finish(success)`, но **0 правок** — подзадача
считается ✅. Это позволило в E11 subtask 1 (v4-pro) формально
«успешно завершиться», хотя правок не было.

**Аналогично в `_run_chain`:** `ok = lr.success` для tool loop-ветки
и `all(subtask.success)` для decompose-ветки (пустой список = True).

### Фикс (10.27)

- **`ToolLoopResult.applied_ops: int`** — счётчик успешных
  `write_file`/`edit_file`. Учитывает resume.
- **`run_agent_decompose`:** `"success": loop_result.success and
  loop_result.applied_ops > 0`.
- **`_run_chain`:**
  - decompose: `ok = parse_error is None and bool(subtask_results)
    and all(r["success"])`;
  - tool loop: `ok = lr.success and lr.applied_ops > 0`.

### Что чинить дальше (TODO)

- **`--split-goals` не проверяет, решена ли задача.** E11-задача #1
  была **уже реализована**, но `--split-goals` создал issue.
  Возможный фикс: перед созданием issue — `read_symbol` + семантика
  (проверка кода на наличие решения).
- **Читающие задачи** (`read_file`, `read_symbol`, `list_files`
  без правок) — новый критерий `applied_ops > 0` их ломает.
  Нужен отдельный признак (`read_ops > 0` или явный тип read).

### Сопутствующие проблемы

1. **Flash флейкует на `run_shell`** — пустые args, неверные
   команды. Уже известно (10.14.26 — retry).
2. **10 итераций мало** для большого файла. Нужно **15+**.
3. **v4-pro — «преждевременный успех»** — читает только начало
   функции и делает вывод.
4. **chain-журнал не пишется при провале** — пустая директория.
5. **verify при 0 правок = зелёный = ложный успех.**
6. **`applied_count == 0` при `apply=True`** — не помечается skipped.

### Уроки

**Для self-hosted задач на своём проекте:**

1. **Большой файл + большая функция = провал.** `agent.py` ~3100
   строк, `_run_agent_step` ~200 строк. Flash теряется.
2. **Точная формулировка:** указать **файл + функцию + строку**.
3. **`--only-path ai_coder/agent.py`** — сузить контекст.
4. **`--max-iterations 15+`** — дать место для разведки.
5. **v4-pro вместо flash** для сложных файлов.
6. **Мелкие подзадачи:** 20-30 строк кода, не «функция целиком».

**Для `--chain`:**

- **Провал одного шага останавливает всё** (`--stop-on-fail`).
  Для независимых задач — `--continue-on-fail`.
- **«Ложный успех» из-за verify без правок** — нужен фикс.

### Находки (TODO)

- [ ] **`applied_count == 0` + `apply=True` → `skipped`**, не запускать
      verify. (Сама задача E11 — подтверждена как баг.)
- [ ] **`--chain`: `applied_count == 0` ≠ «✅ успех»** — считать
      «skipped», не успех.
- [ ] **`--chain` журнал при провале** — писать `report.md` даже
      если все подзадачи упали.
- [ ] **flash флейкует на `run_shell` с пустыми args** — часто.
- [ ] **`ai-coder` console script сломан** (`ModuleNotFoundError`) —
      `pip install -e .` не сделан в venv.

### Ссылки

- Ветка `ai-coder-self-test` — **удалена**.
- `issues-2026-10-11T16-47-19/` — **удалён**.
- Артефакты в `.ai-out/ai-coder/decompose-2026-10-11T16-48-39/`.
- `.gitignore` — добавлено `issues-*/`.

---

## 2026-10-11 — E10: --split-goals + --chain (полная цепочка)

**Гипотеза:** одна фраза → N issue-файлов → `--chain --plan` →
готовые фичи. Устраняет ручную работу из E9 (там ты писал
~15 issue-файлов вручную).

**Что делали:** песочница `/tmp/split-test`, `calc.py` с `add`.

### Прогон 1 — `--split-goals`

    ai-coder agent "Добавь в calc.py sub, mul, div. Плюс README. \
    И тесты в test_calc.py." /tmp/split-test --split-goals

**Результат:** 3 issues, **0.1856 RUB**.

- `1-add-arithmetic-functions.md` (sub+mul+div);
- `2-create-readme.md` (README);
- `3-add-calc-tests.md` (тесты).

v4-pro разбил **разумно**: 3 issues, не 10. Порядок правильный
(код → README → тесты). **Язык** — английский, хотя фраза русская.
Слаги — транслит: `1-add-arithmetic-functions`, `2-create-readme`,
`3-add-calc-tests`.

### Прогон 2 — `--chain --plan`

    ai-coder agent /tmp/split-test \
        --chain /tmp/split-test/issues \
        --tool-loop --plan \
        --verify-commands "python -m py_compile calc.py"

**Ответ:** `y`.

**Результат:** 3 задачи ✅, **0.7659 RUB**.

- Планирование: 3 вызова v4-pro (~0.13 RUB).
- Выполнение: 3 decompose (~0.64 RUB).
- **Планирование не повторяется** — 3 вызова, не 6.

### Итог E2E

- `calc.py`: `add`, `sub`, `mul`, `div` + `ZeroDivisionError`.
- `README.md`: описание, usage, таблица функций.
- `test_calc.py`: 5 тестов.
- `pytest` → **5 passed**.
- **Полная цепочка: ~0.95 RUB.**

### Уроки

1. **Разбиение адекватное** — 3 issues по фичам, порядок
   код → README → тесты.
2. **Планирование не повторяется** — `run_agent_decompose(plan=...)`
   получает готовый план, `run_planner_decompose` не вызывается
   второй раз. Экономия ~0.13 RUB на 3 задачах.
3. **Язык issues** — английский, хотя goal русский. **TODO.**
   Фикс: в промпт `agent_split_goals_json` — «отвечай на языке goal».
4. **Модель дорогая** — `decompose_model` (v4-pro) на простой
   задаче разбиения. flash хватило бы. **TODO:**
   `agent.split_goals_model`.
5. **Порядок валидаций** — `--split-goals` должен проверяться
   **раньше** `--chain`, иначе конфликт (`--split-goals --chain`)
   ловится не той веткой. Исправлено (10.26).
6. **Hack goal-директория** — работает для `--split-goals`
   (`agent /tmp/split-test --split-goals` → path). Достаточно
   `goal and Path(goal).is_dir()` перед `project_root = path.resolve()`.

### Артефакты

- `/tmp/split-test/issues/` — 3 issue-файла (в gitignore, не мешают).
- `/tmp/split-test/.ai-out/split-test/chain-plan-<ts>/plan.yaml` —
  все планы chain.
- `/tmp/split-test/.ai-out/split-test/chain-<ts>/` — общий журнал.
- `/tmp/split-test/.ai-out/split-test/decompose-<ts>/` — по одной
  на задачу.

### Ссылки

- CHANGELOG 10.26.
- `docs/roadmap.md` → направление 10, F.
- `docs/examples.md` → раздел 13.
- `docs/autonomy.md` → Этап 5, 10F закрыт.
- TODO.md → 3 мелочи после E10.

---

## 2026-10-10 — E9: ai-coder в чужом проекте (youtube-playlist-downloader)

**Гипотеза:** `--issue` + `--tool-loop` справятся с большим чужим
проектом (рефакторинг + GUI + интеграция с LLM).

**Что делали:** агент работал в проекте
`~/projects/03_Youtube_downloader/youtube-playlist-downloader/`
(скрипт скачивания с YouTube, ~600 строк) — не нашем.

### Задачи

Всего ~15 задач, каждая — через `--issue` (короткий markdown
файл с задачей) + `--tool-loop --apply --model deepseek-flash`.

**Рефакторинг:**
- Структура: `src/`, `scripts/`, `data/`, `models/`, `legacy/`.
- Переименование файлов (gui.py, ytdl.py, transcribe.py,
  punctuate.py, summarize.py) через `git mv`.
- Обновление путей в config.yaml, gui.py, ytdl.py, scripts/*.sh.

**GUI (Tkinter):**
- Класс YtdlApp: поле ссылок (Text), кнопки Запустить/Стоп,
  лог, тёмная тема, контекстное меню.
- Чекбокс «Транскрибация», Combobox «Обработка LLM».
- Цепочка: ytdl → transcribe → punctuate → summarize
  через `self.stage`.
- Кнопка «Выбрать файл» + режим файла (без скачивания).
- Авто-логика чекбоксов (trace_add):
  - Транскрибация → аудио.
  - LLM-промпт → аудио + транскрибация.
  - Снятие аудио → сброс всего.

**Transcribe / Punctuate / Summarize:**
- transcribe.py: флаг `--file` (обработать один файл).
- punctuate.py: `skip_suffix` (пропуск уже пунктуированных).
- summarize.py: LLM через DeepSeek (`urllib`, без openai-пакета),
  API-ключ из `secret_conf.yaml`.
- summarize.py: `rglob` (рекурсивный поиск).
- prompts.yaml: 4 промпта (summary, summary_short, structured,
  translate_en).
- secret_conf.example.yaml: шаблон (secret_conf.yaml gitignored).

**Скрипты:**
- `run.sh` в корне — читает `venv_path` из config.yaml,
  запускает GUI или CLI.

**README:**
- Полностью переписан через скрипт (не агент) — точнее и надёжнее.

### Результаты

**Все задачи — ✅.** E2E: ссылка YouTube → mp3 → txt →
_punctuated.txt → _summary.md (через GUI, один клик).

**Модели:**
- flash — везде для tool loop.
- deepseek-chat — для summarize (быстрее v4-pro в 12 раз).

### Проблемы и уроки

**1. `max_iterations` × 3** (17-22 строки goal).

Задачи > 15 строк → модель уходит в изучение кода, не успевает
править за 12-14 итераций. **Урок:** для UI/больших задач —
**< 10 строк goal**, иначе флейк (Warning срабатывает, но игнорировали).

**2. `parse_error` × 2.**

Модель отвечает текстом вместо JSON. Retry иногда спасает,
иногда нет (при большом объёме правок).

**3. Verify-артефакты** (`;` в `python -c`).

`--verify-commands "python -c 'import yaml; ...'"` — `;` разбивает
команду на две. **Урок:** не использовать `;` внутри `python -c`,
использовать `,` (или отдельный файл для проверки).

**4. `read_symbol` работает** — используется для навигации по gui.py,
transcribe.py. **Экономит итерации** на больших файлах.

**5. Auto-chmod работает** — `write_file` для файлов с `#!`
автоматически ставит `+x`. `run.sh` стал executable без `chmod`.

**6. Мелкие баги после фич:**
- `punctuate.py` создавал `_punctuated_punctuated.txt` —
  фикс через `skip_suffix`.
- `summarize.py` использовал `glob` вместо `rglob` —
  не находил файлы в подпапках.

**7. `deepseek-v4-pro` — медленный.**

`structured` с `v4-pro` — 40+ секунд (или висит) на файл.
**Урок:** для автоматизации через GUI — `deepseek-chat`
(3-10s на файл).

### Итог

**Агент создал полноценное AI-приложение в чужом проекте**
за ~15 задач (~15-20 RUB на всё).

**Ключевые факторы успеха:**
- **Короткие задачи** (< 10 строк) с явными требованиями.
- **Отдельные файлы** для prompts, secrets, config.
- **Ручная проверка** после каждой задачи (агент не видит
  интеграционных багов).
- **Разбиение больших задач** на 2-3 маленьких.

**Ссылки:**
- Проект: `github.com/bauman-robotics/youtube-playlist-downloader`
- Ветка: `ai-coder/llm-summary`
- Коммиты: `c15b510..fdc4e85` (~10 коммитов).

---

## 2026-10-10 — E8.1: повтор 1.5 с коротким goal (flash vs v4-pro)

**Что пробовали:** E7 показал провал на задаче 1.5 (19-строчный goal,
`apply.py`, `apply_plan` + `rollback`). Здесь — **та же задача**, но
**короткий goal (4 строки)**. Проверяем гипотезу **H12: длина goal**.

**Issue (4 строки):**

    # task: manifest version в apply.py

    ## Цель
    В ai_coder/apply.py добавь в manifest поле version: 1.
    В rollback проверь: если manifest.get("version") != 1 —
    raise ValueError с сообщением "unsupported manifest version".

**Прогон 1 — flash:**

    python -m ai_coder.cli agent --issue /tmp/issue-b15/short.md . \
        --tool-loop --apply --max-iterations 15 --max-cost-rub 2 \
        --verify-commands "python -m pytest tests/test_apply.py -q;ruff check ." \
        --model deepseek-flash

**Результат flash:**

- **6 итераций**, **0.3435 RUB**, ✅ успех.
- Итерации: `read_file` → `run_shell (rejected)` → `run_shell (grep)` →
  `read_file (lines 400-545)` → `edit_file` × 2.
- **0 флейков** (rejection `run_shell` — whitelist, не флейк модели).

**Прогон 2 — v4-pro:**

    python -m ai_coder.cli agent --issue /tmp/issue-b15/short.md . \
        --tool-loop --apply --max-iterations 15 --max-cost-rub 3 \
        --verify-commands "python -m pytest tests/test_apply.py -q;ruff check ." \
        --model deepseek-v4-pro

**Результат v4-pro:**

- **8 итераций**, **2.5880 RUB**, ✅ успех.
- Итерации: `read_file` → `run_shell (rejected)` → `run_shell (grep)` →
  `read_file (400-470)` → `read_file (410-430)` → `read_symbol` →
  `edit_file` × 2.
- **0 флейков.**

**Сравнение:**

| Модель | Goal | Итераций | Стоимость | Результат |
|---|---|---|---|---|
| **flash (E7)** | 19 | ≥15 | ~0.5+ | ❌ `parse_error` |
| **flash (E8.1)** | 4 | **6** | **0.3435** | ✅ |
| **v4-pro (E8.1)** | 4 | **8** | **2.5880** | ✅ |

**Выводы:**

1. **H12 подтверждена: длина goal — критична.** **19 строк → флейк,
   4 строки → ✅.** Это **главный фактор** провала 1.5, а не
   алгоритмическая природа задачи, не размер файла.

2. **v4-pro не быстрее flash на этой задаче.** **8 итераций** vs 6.
   **×7.5 дороже** (2.59 vs 0.34 RUB).

3. **Flash достаточен** для **большинства** задач. **v4-pro** —
   только если flash **действительно** не справляется.

4. **`read_symbol` используется** — v4-pro применил (итерация 6),
   flash — нет (пошёл через `read_file` диапазона).

5. **Правило для `--issue`:** **< 10 строк** — безопасно,
   **10-15** — риск флейка, **> 15** — высокий риск (`parse_error`).

**Действия (сделано):**

- **Warning в `--issue`** (>10 — жёлтый, >15 — красный).
  См. `ai_coder/cli.py`.

**Открытый вопрос:**

- **Почему v4-pro «думает» дольше?** 4 итерации на чтение
  (`read_file` × 2, `read_symbol`), тогда как flash — 3
  (`read_file`, `run_shell`, `read_file`). Возможно, v4-pro
  **осторожнее** — читает больше контекста перед правкой.

**Замечание о честности сравнения:**

B.1 (flash) запущен на **чистом** `apply.py` (HEAD `6ffbce5`).
B.2 (v4-pro) — на `apply.py`, **уже модифицированном** B.1
(`version: 1` в manifest). **Сравнение нечестное:** v4-pro видел
уже-правленый файл. Для **честного** сравнения — откат между
прогонами (`git checkout ai_coder/apply.py`). **Оба ✅**, но
**итерации** могут быть **не сопоставимы**.

**Ссылки:** E7 (провал 1.5, 19 строк), E8 (граница flash, 10 задач),
CHANGELOG 10.22 (warning + E8.1).

---

## 2026-10-10 — E8: граница flash — 10 задач нарастающей сложности

**Что пробовали:** понять, где flash перестаёт справляться.
Серия из **10 задач** — от простых (`calc.py`, ~10 строк) до
реальных (**`ytdl.py`, 600+ строк**).

**Подготовка:** песочницы `/tmp/agent-e8/` (calc.py, git init) и
`/tmp/agent-e8-real/` (копия реального `07_youtube_downloader.py`).
Все задачи — через `--issue --tool-loop --apply`, модель
`deepseek-flash`, verify — `pytest -q` (smoke-тест).

**10 задач:**

| # | Задача | Файл | Строк goal | Итераций | Стоимость | Флейки | `parse_error` | Результат |
|---|---|---|---|---|---|---|---|---|
| 1 | mul | calc.py | 2 | 2 | 0.0914 | 0 | 0 | ✅ |
| 2 | mul + div | calc.py | 4 | 2 | 0.0977 | 0 | 0 | ✅ |
| 3 | проверка типов | calc.py | 4 | 2 | 0.1064 | 0 | 0 | ✅ |
| 4 | history | calc.py | 5 | 2 | 0.1085 | 0 | 0 | ✅ |
| 5 | класс Calculator | calc.py | 5 | 2 | 0.1024 | 0 | 0 | ✅ |
| 6 | 3 функции (pow_, mod, avg) | calc.py | 5 | 2 | 0.1023 | 0 | 0 | ✅ |
| A | `--no-log` | ytdl.py 600+ | 5 | 8 | 0.4540 | 1 | 0 | ✅ |
| D | `audio_marker` | ytdl.py 600+ | 13 | 6 | 0.5142 | 0 | 0 | ✅ |
| C | `validate_url` | ytdl.py 600+ | 9 | 2 | 0.2226 | 0 | 0 | ✅ |
| B | кэш video_ids | ytdl.py 600+ | 12 | 7 | 0.5078 | 2 | 0 | ✅ |

**10 из 10 — успех.** `parse_error` — **ни разу**.

**Флейки:**
- **A** — 1×: `read_symbol: missing 'name'` (итерация 3).
- **B** — 2×: `run_shell rejected: shell metacharacters` (итерация 2),
  `edit_file: missing args` (итерация 5).
- **Все** — retry **спас** (10.14.26).

**Наблюдения:**

1. **Flash справляется с реальным 600-строчным кодом.** A, D, C, B —
   все ✅, включая **алгоритмическую** задачу B (кэш: сбор в одном
   месте, использование в другом).
2. **`parse_error` — не системная проблема.** В E8 — **0 раз**.
   Значит, провал 1.5 (E7) — **исключение**.
3. **`read_symbol` используется** — если goal **явно называет**
   функцию (D: 3×, A: 2×). Если функция неизвестна (C) — модель
   читает `read_file` всего файла.
4. **Стоимость растёт с размером файла** — calc.py: 0.10 RUB,
   ytdl.py: 0.22-0.51 RUB (×2-5).
5. **Флейки — обычное дело**, retry спасает. **1.5 — исключение**
   (2× `parse_error` подряд, retry **не помог**).
6. **Стратегии модели:**
   - точечные `edit_file` × N (A, D, B);
   - **один большой** `edit_file` (C — 2 итерации, дешевле);
   - `read_symbol` — при **явном** goal;
   - `read_file` всего файла — если **навигация неясна** (C, A).

**Новые гипотезы:**

- **H5 (размер файла):** подтверждена — большой файл → больше
  итераций (6-8 vs 2).
- **H7 (`read_symbol`):** подтверждена — используется, если goal
  **явный**.
- **H8 (2 согласованные функции):** **опровергнута** — D, B
  (3-4 правки) — flash справился.
- **H9 (алгоритмические задачи сложнее):** **опровергнута** — B
  (кэш) — flash справился.
- **H10 (большой `edit_file` может быть дешевле):** **подтверждена** —
  C (один edit, 2 итерации, 0.22) дешевле, чем A (8 итераций, 0.45).
- **H12 (длина goal):** **не подтверждена** — B (12 строк) справился,
  A (5) — 8 итераций.
- **H14 (флейк):** **частично** — 1.5 — **случай** тяжёлого флейка,
  retry не помог.

**Главный вывод:**

**Flash достаточно для большинства задач**, включая реальный код
600+ строк и алгоритмические задачи. **1.5 (E7) — исключение.**
Возможные причины: комбинация (19 строк goal + специфика `apply.py` +
флейк).

**Открытые вопросы:**

- **Повторить 1.5** с коротким goal (10 строк) — проверить H12.
- **Повторить 1.5** с v4-pro — проверить, справится ли сильная модель.
- **Улучшить replan** (Этап 2 autonomy.md) — чтобы **флейк** не
  приводил к провалу.

**Ссылки:** `docs/autonomy.md` (план), E7 (провал 1.5), коммиты
`2d8e31b`-`e3d5384` (сессия).

---

## 2026-10-10 — E7: --issue на сложной задаче: ❌ flash не справился

**Что пробовали:** задачу 1.5 (apply.py — удалять пустые каталоги при
откате) через `--issue`. Issue-файл: **19 строк**, **2 функции**
(apply_plan + rollback), файл `ai_coder/apply.py` — **500+ строк**.

**Прогон 1 — обычный tool loop (flash):**

    ai-coder agent --issue issues/apply-nonatomic.md . \
        --tool-loop --apply --max-iterations 15 --max-cost-rub 2 \
        --verify-commands "python -m pytest tests/test_apply.py -q;ruff check ." \
        --model deepseek-flash

- **`parse_error (попытка 1/2): tool JSON no '{' found`** —
  модель ответила **текстом**, а не JSON.
- **Retry** — та же ошибка.
- **Остановлено вручную.**

**Прогон 2 — с decompose:**

    ai-coder agent --issue issues/apply-nonatomic.md . \
        --tool-loop --decompose --decompose-replan ... \
        --model deepseek-flash

- v4-pro разбил на **2 подзадачи**.
- **Подзадача 1 — снова ПОЛНАЯ задача** (apply_plan + rollback),
  v4-pro **не разбил** по функциям.
- **`parse_error` + `max_iterations`** — flash не справился.
- **Retry через v4-pro** — тоже не помог.
- **Остановлено вручную.**

**Что успел сделать агент (50%):**

- **`_collect_new_dirs(abs_parent, root)`** — **корректная** функция:
  идёт вверх, собирает несуществующие каталоги, создаёт от корня
  к глубокому, возвращает от глубокого к корню.
- **`created_dirs: list[str] = []`** — добавлено в `apply_plan`.
- **Собирает `missing_dirs`** в `apply_plan`.
- **Синтаксис OK**, **28 старых тестов зелёные**.

**Что НЕ сделал:**

- **`manifest["created_dirs"]`** — не записано (переменная мёртвая).
- **`rollback`** — не тронут (пустые каталоги остаются).
- **Тесты** — не написаны.
- **Дублирование:** функция `_collect_new_dirs` определена, но
  **не вызывается** — inline-цикл в `apply_plan` делает то же самое.

**Финал — доделано вручную (~30 минут):**

- Вызов `_collect_new_dirs` вместо inline-цикла.
- `manifest["created_dirs"] = created_dirs`.
- `rollback` удаляет `created_dirs` через `rmdir` (не пуст → ignore).
- **+2 теста** (`removes_empty_dirs`, `keeps_non_empty_dirs`).
- Коммит `6ffbce5`.

**Выводы:**

1. **`--issue` требует `< 15 строк`, 1 функцию, 1 файл.** 19 строк +
   2 функции + 500-строчный файл — за пределами flash.
2. **flash флейкает текстом на 2 функциях.** `parse_error: tool JSON
   no '{' found` — не стилистическая проблема, а **структурная**.
   Retry **не помогает**, когда ошибка **систематическая**.
3. **`--decompose` не помогает, если v4-pro не понимает, КАК разбить.**
   Здесь он разбил **формально** — 2 подзадачи, но первая = вся
   задача целиком.
4. **Агент сделал полезные 50%** — не откатывали, **доделали**.
   Даже провальный прогон оставляет **полезный** след.
5. **Правильный подход для таких задач:** **2 отдельных issue** —
   «apply_plan: created_dirs» и «rollback: удалить created_dirs».
   Каждый **~5-6 строк, 1 функция, 1 файл**.

**Стоимость:** ~1 RUB потрачено (2 прогона). ~30 минут сэкономлено
ручной работой.

**Открытый вопрос:** стоит ли добавить **warning** в `--issue`,
если goal **> 15 строк**? Сейчас обрезка только после 60.

**Ссылки:** CHANGELOG 10.21, коммит `6ffbce5`, ревью 1.5 (закрыто).

---

## 2026-10-10 — E6: --with-tests — короткий goal ×2.3 дешевле: ✅

**Что пробовали:** новый флаг `--with-tests` (10.19) — агент
пишет pytest-тесты для изменённых файлов. Сравнили **два goal**:
длинный (13 строк) и короткий (5 строк).

**Песочница `/tmp/withtests-test2`:**

    calc.py:      def add(a, b): return a + b
    test_calc.py: from calc import add
                  def test_add(): assert add(2, 3) == 5

**Задача:** «Добавь в calc.py функцию sub(a, b), возвращающую a - b.»

**Команда:**

    python -m ai_coder.cli agent "Добавь в calc.py функцию sub..." \
        /tmp/withtests-test2 --tool-loop --apply --with-tests \
        --max-iterations 10 --max-cost-rub 3 \
        --verify-commands "python -m pytest -q" --model deepseek-flash

**Сравнение goal v1 vs v2:**

**v1 — длинный (13 строк):**

    Напиши pytest-тесты для недавно изменённых файлов:
    - calc.py

    Требования:
    1. Для каждого модуля создай или обнови tests/test_<module>.py
       (имя модуля без пути и без .py).
    2. Покрой новые/изменённые функции: happy path и 1-2 edge cases.
    3. После написания запусти `python -m pytest -q` (через run_shell).
    4. Если тесты падают из-за багов в коде — верни finish(success=false).
    5. Если всё зелёное — finish(success=true).
    Не трогай файлы, не являющиеся тестами.

**v2 — короткий (5 строк):**

    Напиши pytest-тесты для изменённых файлов:
    - calc.py

    Сначала найди существующие тесты (list_files + grep test_).
    Если тест для модуля уже есть — добавь в существующий файл.
    Иначе — создай test_<module>.py рядом с модулем.
    Покрой новую/изменённую функцию. Не трогай не-тестовые файлы.

**Результаты:**

| Метрика | v1 (13 строк) | **v2 (5 строк)** |
|---|---|---|
| Итераций with-tests | 9 | **3** |
| Флейки `missing args` | 3 | **0** |
| Файл тестов | **создал `tests/`** (дубль) | **обновил `test_calc.py`** |
| Стоимость всего | 0.4493 RUB | **0.1945 RUB** |
| Результат | ✅ но с дублем | ✅ **чисто** |

**Что было в v1:**

1. **Жёсткий путь `tests/test_<module>.py`** — модель **создала**
   папку `tests/`, хотя `test_calc.py` **уже был в корне**.
   → дублирование тестов.
2. **13 строк** — модель **теряла фокус** → `missing args (write_file)` ×3.
3. **Retry спас** (10.14.26), но 3 из 9 итераций ушли на флейки.
4. **`run_shell pytest` в goal** — лишние итерации (внешний verify
   всё равно запускается).

**Что изменилось в v2:**

1. **Убран жёсткий путь** — «создай `test_<module>.py` рядом».
2. **Добавлено «сначала найди существующие тесты»** — модель
   использует `list_files` + `grep test_` → находит `test_calc.py`.
3. **Убран `run_shell pytest`** — не дублирует verify.
4. **5 строк** — модель держит фокус.

**Выводы:**

1. **Короткий промпт — не стилистика, а функциональность.**
   ×2.3 по стоимости, ×3 по итерациям, 0 флейков.
2. **Не указывать конкретный путь к тестам** — в разных проектах
   тесты лежат в разных местах (`test_*.py` в корне, `tests/`,
   `tests/unit/`, `spec/`). Инструкция «сначала найди» работает
   для всех.
3. **Не дублировать verify в goal** — внешний `verify_commands` уже
   запускает pytest после finish. `run_shell pytest` в промпте
   тратит итерации.
4. **«Сначала посмотри, потом делай»** — универсальный паттерн для
   tool loop goal'ов.

**Открытые вопросы:**

- **Auto-fix для новых тестов?** Если тесты падают — сейчас
  `success=False`. Можно добавить `--with-tests --auto-fix-issues`
  → третий цикл fix. Отложено.
- **5+ файлов с --with-tests?** Пока не проверяли. Модель может
  писать тесты для 5 файлов — это много итераций. Может нужен
  `--decompose --with-tests`?
- **Качество тестов?** В v1 модель писала параметризованные + edge
  cases (`-1+1=0`, `10**18`, `0-5=-5`). В v2 — проще (`test_sub` без
  параметризации). Стоит ли жертвовать глубиной ради краткости?
  Пока — да, стабильность важнее.

**Ссылки:** CHANGELOG 10.19, коммит `0659638`, roadmap → направление 3
(закрыто).

---

## 2026-10-10 — E5: --auto-fix-issues в бою: ✅ успех за 2 попытки

**Что пробовали:** новый флаг `--auto-fix-issues` (10.17) — цикл
`verify → fix → verify` после tool loop.

**Песочница `/tmp/autofix-test`:**

    calc.py:      def add(a, b): return a - b       # баг
    test_calc.py: def test_add(): assert add(2, 3) == 5   # падает

**Задача агенту:** «Прочитай файл calc.py и верни finish(success=true).
НЕ правь файл» — специально, чтобы verify упал и сработал auto-fix.

**Команда:**

    python -m ai_coder.cli agent "Прочитай файл calc.py и верни finish..." \
        /tmp/autofix-test --tool-loop --apply --auto-fix-issues \
        --max-iterations 5 --max-cost-rub 2 \
        --verify-commands "python -m pytest -q" --model deepseek-flash

**Что произошло:**

1. **Tool loop:** `read_file(calc.py)` → `finish(success=true)` (1 итерация).
2. **Verify:** `pytest -q` → ❌ `assert -1 == 5` → `success=False`,
   `stopped_reason="verify_failed"`.
3. **Auto-fix стартует** (новый блок):
   - Попытка 1/3: `pytest` → ошибка → `fix через tool loop` →
     правит `calc.py` (`a - b` → `a + b`) → `pytest` ✅.
   - Попытка 2/3: `✅ Auto-fix: успех`.
4. **Итог:** `✅ успех`, `Стоимость: 0.1460 RUB`,
   `Summary: verify failed, auto-fix: 2 попыток → ok`.

**Проверка результата:**

    $ cat /tmp/autofix-test/calc.py
    def add(a, b): return a + b

    $ git diff
    -def add(a, b): return a - b
    +def add(a, b): return a + b

**Стоимость:**

- Tool loop: ~0.06 RUB (1 итерация — read + finish).
- Auto-fix: ~0.09 RUB (2 попытки: fail + fix + verify success).
- **Итого:** 0.1460 RUB.

**Выводы:**

1. **Цикл замкнут:** «правка → verify → fix → verify» — в одной
   команде, без ручного перезапуска.
2. **Стоимость предсказуема:** 2 попытки auto-fix = ~0.09 RUB.
3. **Бюджет делится:** остаток `--max-cost-rub` уходит в auto-fix
   (в тесте не пригодилось — остаток 1.85 RUB, потратили 0.09).
4. **Отчёт консистентен:** `loop_result.success=True` после
   auto-fix, `summary` объясняет что было.

**Открытые вопросы:**

- **Что если auto-fix зациклится?** Ограничение `max_attempts=3`
  жёсткое. Проверить на реально сложном баге.
- **Интеграция в `--decompose`:** там уже replan/rollback,
  auto-fix поверх — потенциально сложно (что чинить, если подзадача
  упала?). **Отложено.**
- **Auto-fix внутри `run_agent` (классический):** там свой
  `--max-fix-attempts`. Дублировать или унифицировать? **Отложено.**

**Ссылки:** CHANGELOG 10.17, коммит `b421c38`, roadmap → направление 1
(закрыто).

---

## 2026-10-10 — E4: scan-cache содержимого — ❌ отрицательный результат

**Что пробовали:** кэш сканирования проекта. Идея (roadmap 2B):
`.ai-out/<project>/scan-cache.json` хранит `{path: {mtime, size, content}}`.
При следующем скане — если `mtime` + `size` совпали, берём `content`
из кэша, не читаем файл.

**Реализовали:** полностью (scanner.py + проброс `cache_path` из 6
вызовов в cli/agent/actions + 5 тестов). Тесты зелёные.

**Замер на живом проекте** (`ai-coder`, 52 файла, `greet`):

| Метрика | Значение |
|---|---|
| `_contains_secret` на 32 файла | **0.055 s** (1.73 ms/файл) |
| `read_text` на 32 файла | **0.052 s** |
| `scan_project` полностью | **0.014 s** |
| **scan-cache.json** | **868 KB** |
| **Полный `greet`** | **12 s** |

**Первый запуск `greet` (без кэша):** 12.005 s.
**Второй запуск `greet` (с кэшем):** 13.950 s.

**Вывод:** кэш **не ускорил** скан — **замедлил** (парсинг JSON 868K
дороже, чем чтение 52 файлов напрямую). Полный `greet` — 12 s,
из которых скан — **0.014 s = 0.1%**. HTTP-запрос к DeepSeek — ~99%.
**Даже если ускорить скан в 100× — общее время не изменится.**

**Почему не работает:**

1. **Скан — не бутылочное горлышко.** 0.014 s на 52 файла —
   тысячная доля от 12 s.
2. **Хранить содержимое бессмысленно.** Read из файла vs read из
   JSON — та же I/O. JSON **медленнее** (парсинг + распаковка).
3. **`_contains_secret` дешёвый.** 1.73 ms/файл — копейки.
4. **Кэш 868 KB — дорого.** Он **больше**, чем сами 52 файла
   в сумме? Нет, те же данные, но **один JSON** — хуже для инкремента
   (перезапись всего файла при изменении одного исходника).

**Что было бы правильно** (следующая итерация, если возьмёмся):

- **Вариант А: кэш `_contains_secret`** (только CPU-экономия).
  `{path: {mtime, size, secret: bool}}`. Размер ~50 KB. Скан
  пропускает regex для неизменённых. Экономия 0.055 s — всё ещё **0.4%
  от 12 s**. **Не стоит.**
- **Вариант Б: кэш карты символов** (для `read_symbol`).
  `{path: {symbols: [{name, kind, start, end}]}}`. Не для ускорения
  скана, а для **быстрой навигации** — `read_symbol` без `grep`.
  **Другая цель.**
- **Вариант В (правильный): инкрементальный контекст.**
  Если изменились 3 файла из 50 — в промпт **только 3**.
  Это **архитектура**, не кэш. Экономит **токены** (главная статья
  расходов), а не секунды. См. `TODO.md` → «Инкрементальный контекст».

**Урок:** «ускорить X» без замера X — опасно. Скан был **0.1%** времени,
а мы чуть не построили инфраструктуру на 868 KB ради этого.

**Ссылки:** roadmap 2B (уточнено), `TODO.md` → «Инкрементальный контекст».

---

## 2026-10-10 — E3: read_symbol на большом файле: ✅ 2 итерации вместо 3

**Что пробовали:** новый инструмент `read_symbol` (10.16) на живой задаче —
сравнить с путём через `grep` + `read_file(line_start, line_end)` (10.14.14).

**Задача:** добавить строку в docstring функции `run_tool_loop`
в `ai_coder/agent.py` (2806 строк).

**Команда:**

    python -m ai_coder.cli agent "$(cat /tmp/task.txt)" . \
        --tool-loop --apply --max-iterations 10 --max-cost-rub 1 \
        --model deepseek-flash

**Три прогона:**

| Метрика | 10.14.14 (grep+read_file) | read_symbol v1 | **read_symbol v2** |
|---|---|---|---|
| Итераций | 3 | 3 | **2** |
| Стоимость | 0.13 RUB | 0.1586 RUB | **0.1125 RUB** |
| Путь | read_file→grep→read_file→edit | read_symbol→**read_file**→edit | **read_symbol→edit** |
| Результат | ✅ | ✅ | ✅ |

**v1 — что было не так:**

- `read_symbol` **сработал** (итерация 1), модель получила тело функции
  (14101 символов — полный docstring).
- Но на итерации 2 модель сделала `read_file(2092-2200)` — **перечитала то,
  что уже видела**.
- **Причина:** `format_tool_history` обрезал `read_symbol` до
  `other_max_chars=500` → в истории модели был обрезанный вывод →
  модель «не увидела» docstring → решила перечитать.

**Фикс `format_tool_history`:**

- `read_symbol` добавлен в привилегированный путь (лимит 10000, как `read_file`);
- пометка при обрезке **разная**:
  - `read_file` → «Используй run_shell grep для точного поиска»;
  - `read_symbol` → «Не перечитывай — правь через edit_file или finish».

**v2 — идеальная последовательность (2 итерации):**
1. `read_symbol(name="run_tool_loop")` → тело функции;
2. `edit_file` → 1 replacement;
3. `finish(success=true)`.

**Выводы:**

1. **`read_symbol` работает end-to-end:** модель сама выбирает его
   (без подсказки в промпте на первом прогоне), читает тело символа,
   правит, завершает.
2. **2 итерации вместо 3** — экономия ~13% по стоимости от пути через grep,
   ~29% от v1.
3. **Привилегированный путь в истории критичен.** Без него модель
   перечитывает то, что уже видела — теряется весь выигрыш инструмента.
4. **Общая закономерность:** любой инструмент, возвращающий «контент»
   (read_file, read_symbol), должен попадать в `format_tool_history`
   с увеличенным лимитом, иначе модель не видит результата.

**Открытые вопросы:**

- Эффект **на 5+ файлах**: `read_symbol` × 5 → возможно, справится без
  decompose?
- **Коллизии** (одно имя в разных файлах): модель поймёт по шапке
  «first match of 2»?
- **Не-функции** (константы, глобальные переменные): не поддержаны.
  Модель пойдёт через `read_file`.

**Ссылки:** CHANGELOG 10.16, коммиты `c66ec38`, `70e15d1`,
roadmap → направление 2A (закрыто).

---

## 2026-10-09 — --hint проверен живьём: ✅ работает

**Что пробовали:** E2E-проверку флага `--hint` (10.14.23).

**Три уровня доказательства:**

**Уровень 1 — unit (без LLM):**
- `render_prompt(entry, hint="...")` — дописывает `\n\n[УТОЧНЕНИЕ]\n{hint}\n`
  в **конец** user;
- `user_with` длиннее `user_without` **ровно на 76 символов**
  (длина текста `"Отвечай максимально кратко: ровно 2 предложения,
  без списков."` + `\n\n[УТОЧНЕНИЕ]\n` + `\n`);
- `user_without` **не** заканчивается на `[УТОЧНЕНИЕ]`.

**Уровень 2 — живой прогон (greet):**
    python -m ai_coder.cli run greet . --depth shallow \
        --only-path ai_coder/prompts.py \
        --hint "Отвечай максимально кратко: ровно 2 предложения, без списков." \
        --no-cache
- **Ответ модели:** 2 предложения, **без списков**;
- **Стоимость:** 0.015156 RUB;
- **Cache hit:** 768 токенов (статическая часть промпта).

**Уровень 3 — отчёт:**
- `.ai-out/ai-coder/greet-2026-10-09T20-52-50.md`;
- метаданные + ответ + приложение (файлы в контексте).

**Выводы:**
1. `--hint` **работает** end-to-end: CLI → render_prompt → LLM;
2. **Модель** **учитывает** уточнение (**кратко** — **без** **списков**);
3. **Unit-проверка** через `render_prompt` **доказывает** сборку промпта
   **без** **LLM** (0 RUB).

**Наблюдение для тестов:**
- Проверка «`[УТОЧНЕНИЕ]` not in user_without» **ложно** **падает**,
  если в сканируемом файле (`.ai_coder/prompts.py`) **есть** **строка**
  `user = user + "\n\n[УТОЧНЕНИЕ]\n"` — она попадает в `{{files}}`.
- **Правильный** **assert:** `user_with.endswith("\n\n[УТОЧНЕНИЕ]\n" + hint + "\n")`.

**Ссылки:** CHANGELOG 10.14.23, TODO — закрыто (реализация + проверка).

---

## 2026-10-09 — --hint flash v2: ✅ фикс сработал

**Что пробовали:** ту же задачу (4 правки в 3 файлах) **после**
фикса 10.14.26 (правило 12 + retry на missing args).

**Команда:**
    python -m ai_coder.cli agent "$(cat /tmp/task_hint.txt)" . \
        --tool-loop --apply --max-iterations 20 --max-cost-rub 3

**Результат:** ✅ **успех**, **9 итераций**, **0.5390 RUB**,
`verify_commands` passed.

**Сравнение до / после фикса:**

| Метрика | 1-й flash (до) | 2-й flash (после) |
|---|---|---|
| Итераций | 20 (max) | **9** |
| Флейков `missing 'path'` | **7** | **0** |
| Файлов изменено | 2 из 3 | **3 из 3** |
| Результат | ❌ max_iterations | **✅ success** |
| Стоимость | 1.01 RUB | **0.54 RUB** |

**В 2.2× меньше итераций, в 1.9× дешевле, 0 флейков.**

**История (9 итераций) — идеальная последовательность:**
1-3. `read_file` × 3 (`prompts.py`, `actions.py`, `cli.py`);
4-5. `edit_file(prompts.py)` × 2;
6-7. `edit_file(actions.py)` × 2;
8-9. `edit_file(cli.py)` × 2.
Ни одного флейка, ни одного лишнего действия.

**Почему фикс сработал:**
1. **Правило 12** в `agent_tool_json` теперь покрывает `missing 'path'` —
   модель **знает**, какие поля обязательны, и **превентивно** не флейкает.
2. **Retry-логика** в `run_tool_loop` — страховка: при пустом args
   повторяет запрос **без** траты итерации.

**Вывод:** задача на 3 файла выполнима при правиле + retry.
До фикса — провал, после — уверенный успех за 9 итераций.

**Уточнения (что НЕ проверяли):**

- Задача запускалась **прямым** `--tool-loop` с **flash** — **без** `--decompose`.
- **Не** было **подзадач**, **не** было **retry** **через** **v4-pro**
  (это функция `--decompose`), **не** было `--decompose-replan`.
- **Гипотезы** для следующего эксперимента:
  1. **`--decompose` до фикса** — v4-pro разбил бы задачу на 3 подзадачи,
     flash мог флейкать в каждой, **retry через v4-pro** — добил бы.
     **Возможно**, ✅ **до** фикса — но **дороже** (~2-3 RUB).
  2. **`--model deepseek-v4-pro` без decompose** — v4-pro строже держит
     JSON-формат, **возможно** 0-1 флейк. **~1.5-2 RUB**.
  3. **Сравнение** «правило 12 + retry» (0.5 RUB) vs decompose (~2 RUB)
     vs v4-pro (~2 RUB) — **что дешевле** для задач на 3+ файлов.
- **Вывод**: фикс **правила** — **дешевле** и **универсальнее**,
  но **эмпирически** **не** сравнили с decompose/v4-pro на этой задаче.

**Ссылки:** CHANGELOG 10.14.26, TODO п.24-25 (закрыты).

---

## 2026-10-09 — --hint агентом: ❌ частичный провал (флейки)

**Что пробовали:** попросить агента реализовать флаг `--hint`
(4 правки в 3 файлах: `prompts.py`, `actions.py`, `cli.py`).

**Команда:**
    python -m ai_coder.cli agent "$(cat /tmp/task_hint.txt)" . \
        --tool-loop --apply --max-iterations 20 --max-cost-rub 3

**Результат:** ❌ **max_iterations** (20), **1.01 RUB**.
**Частичный** успех: `prompts.py` ✅, `actions.py` ✅, `cli.py` ❌.

**Хронология (20 итераций):**
- **10** полезных (read_file, edit_file ×4, run_shell grep ×2, ...);
- **7** флейков `missing 'path'` (итерации 2, 11, 12, 13, 14, 15, 17);
- **2** `run_shell` с метасимволами;
- `cli.py` — **только** начал (итерация 19).

**Что сломалось:**

**1. Флейки `edit_file: missing 'path'` — 45% итераций.**
- Модель возвращала `{"tool": "edit_file", "args": {}}`.
- **5** флейков **подряд** (11-15) — модель **застряла**.
- **Правило 12** в промпте — **нет** случая `missing 'path'`.

**2. Задача на грани возможностей.**
- **4** правки в **3** файлах → минимум **10-15** итераций;
- **+9** флейков = **19-24** — **превышение** `max_iterations=20`.

**3. `cli.py` — большой файл.**
- 1612 строк → даже **дойти** до `def run` **сложно**.

**Выводы:**
1. **Flash-модель флейкает** при **длинных** промптах;
2. **Правило 12** не покрывает `missing 'path'` — модель **не** знает, что делать;
3. **Задачи на 3+ файла** — **рискованны** для flash;
4. **Разбивать** на **1 файл** / `--decompose` / `--model v4-pro`.

**Ссылки:** docs/tools.md → «Как формулировать», TODO п.24-25.

---

## 2026-10-09 — tool loop на песочнице: ✅ успех за 3 итерации

**Что пробовали:** `agent --tool-loop --apply --commit` на проекте
`/tmp/agent-test` (баг в `add`: `return a - b` вместо `a + b`,
падающий тест `test_add`).

**Команда:**
    python -m ai_coder.cli agent "В файле calc.py функция add \
        возвращает неверный результат. Исправь баг так, чтобы \
        тесты проходили." /tmp/agent-test --tool-loop --apply \
        --commit --max-iterations 10 --max-cost-rub 2

**Результат:** ✅ **успех**, 3 итерации, **0.1048 RUB**.

**Что произошло:**
- Итерация 1: `read_file(calc.py)` — прочитал содержимое.
- Итерация 2: `edit_file(calc.py)` — `return a - b` → `return a + b`,
  `edited calc.py (1 replacement)`.
- Итерация 3: `run_shell(python -m pytest -q)` — `..` (2 passed).
- `finish(success=true, summary="Баг в calc.py исправлен...")`.
- Внешний `verify_commands` после finish → `✅ Проверка пройдена`.

**Выводы:**
1. **Агент сам верифицирует правку** — запускает pytest до finish,
   не ждёт внешней проверки.
2. **Двухуровневая защита:** модель проверяет себя +
   `verify_commands` после finish.
3. **3 итерации** — целевая последовательность
   `read → edit → verify → finish`. Никакого зацикливания.
4. **0.10 RUB** для атомарной задачи — норма после фикса 10.8.
5. **Автокоммит не сработал** — песочница не git-репозиторий.
   Не баг, среда. Проверить отдельно с `git init`.

**Ссылки:** CHANGELOG 10.5–10.8, docs/tools.md → «Как формулировать».

---

## 2026-10-09 — D: --decompose-max-cost-rub агентом, ✅ успех

**Что пробовали:** попросить агента реализовать **реальную фичу** —
флаг `--decompose-max-cost-rub` (аналог `fix --max-cost-rub`, 10.14.4),
но для decompose. **4 правки в двух файлах**:
- `agent.py`: параметр `max_cost_rub`, проброс в **оба**
  `run_tool_loop` (основной + retry), проверка бюджета;
- `cli.py`: флаг `--decompose-max-cost-rub`, проброс.

**Команда:**
    python -m ai_coder.cli agent "$(cat /tmp/task_d.txt)" . \
        --tool-loop --apply --max-iterations 20 --max-cost-rub 2

**Результат:** ✅ **успех**, **16 итераций**, **1.8532 RUB**,
verify passed (314).

**История (16 итераций, 6 edit_file):**
1. `read_file(agent.py, 455-600)` — **сразу** участок (новый
   инструмент работает!).
2. `read_file(agent.py, 515-620)` — расширил диапазон.
3-6. `edit_file` × 4 (два провала — `missing 'path'`, потом успех).
7-10. `read_file(agent.py, 515-640)` + `edit_file` × 2.
11. `read_file` — ❌ `missing 'path'`.
12-14. `read_file(cli.py, 740-850)` + `read_file(cli.py, 836-875)` +
   `edit_file(cli.py)`.
15-16. `read_file(agent.py, 455-500)` + `edit_file(cli.py)`.

**Что особенно удалось:**
1. **`read_file(offset)` использован с 1-й итерации** — фикс
   10.14.14 работает на больших файлах (`agent.py` 2723 строки,
   `cli.py` 1612 строк).
2. **`remaining` пересчитывается ДВАЖДЫ** — перед основным и
   перед retry. Модель **сама** догадалась: после первой попытки
   `dec_result.cost_rub` вырос, остаток уменьшился.
3. **Проверка бюджета — один раз**, в правильном месте (после
   retry, перед `if not loop_result.success`).
4. **Только нужные правки** — ничего лишнего. `run_auto_fix`
   (третий `run_tool_loop` в файле) **не тронут**.
5. **314 passed** — тесты не сломались.
6. **3 промежуточных фейла** (`missing 'path'`) — модель
   **повторила** вызовы и справилась.

**Стоимость 1.85 RUB** — выше ожидаемой:
- 16 итераций × ~0.1 RUB;
- 6 `edit_file`, каждый со своим LLM-вызовом.
- Прямая правка `edit_file` (10.14.4) — **5 минут**, ~0.3 RUB.

**Выводы:**
1. **Агент справляется с реальными фичами** (не только docstring).
2. **`read_file(offset)` — критичный инструмент.** Без него —
   провал (10.14.13).
3. **Модель понимает логику** — пересчёт `remaining` перед retry
   не был явно указан, но модель догадалась.
4. **Стоимость реальной фичи через агента — ×5-6 к ручной**.
   Но **без участия человека**. Для сложных случаев — оправдано.

**Ссылки:** TODO п.18 (закрыт), CHANGELOG 10.14.14 (read_file
offset), 10.14.16.

---

## 2026-10-09 — E2: read_file(offset) на большом файле, ✅ успех

**Что пробовали:** после фикса 10.14.14 (`read_file(line_start, line_end)`
+ новое правило 11) — та же задача на **большом** файле:
добавить строку в docstring `run_agent_decompose` (`ai_coder/agent.py`,
2723 строки, ~90 KB).

**Команда:**
    python -m ai_coder.cli agent "В ai_coder/agent.py в docstring \
        функции run_agent_decompose добавь одну строку в конце: \
        \"При dry_run=True реальные правки не выполняются.\" \
        Сохрани остальной текст docstring без изменений." . \
        --tool-loop --apply --max-iterations 15 --max-cost-rub 1

**Результат:** ✅ **успех**, **3 итерации**, **0.1288 RUB**, verify passed.

**История (3 итерации):**
1. `run_shell(grep -n "def run_agent_decompose")` → **строка 462**.
2. `read_file(agent.py, line_start=462, line_end=500)` →
   **38 строк** вокруг функции. Заголовок:
   `# ai_coder/agent.py (lines 462-500 of 2723)`.
3. `edit_file(agent.py, ...)` → `edited ai_coder/agent.py
   (1 replacement)`.
4. `finish(success=true, summary="...")`.
5. Внешний `verify_commands` → `✅ Проверка пройдена`.

**Diff — ровно одна строка:**
    +    При dry_run=True реальные правки не выполняются.
Ничего лишнего, отступы корректные.

**Сравнение с провалом до фикса:**

| Метрика | До E1 (10.14.13) | После E1 (E2) |
|---|---|---|
| Итераций | 12 | **3** |
| Правок | 0 | **1** |
| Стоимость | 0.6541 RUB | **0.1288 RUB** |
| Результат | ❌ max_iterations | **✅ success** |

**В 4 раза меньше итераций. В 5 раз дешевле. Работает.**

**Выводы:**
1. **`read_file(line_start, line_end)` работает** на большом файле
   (2723 строки). Читает точный участок (38 строк), не обрезается,
   попадает в историю целиком.
2. **`edit_file` работает** после чтения участка — точная правка
   (1 replacement), ничего лишнего.
3. **Правило 11 работает** — модель **сразу** пошла через
   `grep -n` → `read_file(offset)` → `edit_file`. Никаких sed,
   никаких повторных `read_file` всего файла.
4. **Фикс 10.14.14 решает проблему больших файлов.**
5. **Стоимость упала в 5 раз, итераций в 4 раза.**

**Артефакты:** журнал
`.ai-out/ai-coder/tool-loop-2026-10-09T17-00-15`.

**Ссылки:** CHANGELOG 10.14.14, TODO п.18 (закрыт),
`docs/tools.md` → «Как формулировать».

---

## 2026-10-09 — tool loop на большом файле: ❌ провал (правило 11)

**Что пробовали:** попросить агента починить баг в
`run_agent_decompose` (`ai_coder/agent.py`, ~2600 строк, ~90 KB):
при retry через v4-pro стоимость первой (flash) попытки теряется —
`subtask_results[-1]["cost_rub"]` перезаписывается, а не суммируется.
Задача — заменить присваивание на суммирование.

**Команда:**
    python -m ai_coder.cli agent "$(cat /tmp/fix_decompose.txt)" . \
        --tool-loop --apply --max-iterations 12 --max-cost-rub 1

**Результат:** ❌ **неуспех**, 12 итераций, **0.6541 RUB**, **0 правок**.

**История (12 итераций):**
1. `read_file(agent.py)` — прочитал **начало** файла (обрезано).
2. `run_shell(grep ...)` — **нашёл** строку 590.
3. `run_shell(grep ...)` — нашёл блок retry (строки 565+).
4-6. `run_shell(grep ...)` × 3 — те же строки.
7. `run_shell(sed ...)` — ❌ **whitelist violation** (`sed` не разрешён).
8. `run_shell(...)` — ❌ (no output).
9. `read_file(agent.py)` — перечитал (зачем? уже читал).
10-12. `run_shell(grep ...)` / `run_shell(...)` — ❌.
**Ни одного `edit_file`.**

**Что сломалось — три проблемы:**

### 1. Правило 11 не различает «весь файл» и «обрезан»

Правило 11 в `agent_tool_json` буквально:
> «Не используй `run_shell grep` для поиска строк в файле, который
> уже прочитал через `read_file`. Всё есть в контексте.»

Для **больших** файлов это **ловушка**:
- `read_file` возвращает до 50K символов;
- `agent.py` ~90 KB → **обрезано** («[обрезано, всего N символов]»);
- нужный блок — в **середине**, не попал в контекст;
- модель **следует правилу** — не grep (но всё же grepn'ула);
- **не может сформировать `edit_file`** — нет уникального `old`,
  потому что реального текста вокруг строки 590 она **не видела**.

Модель **застряла** между «читай» и «не grep».

### 2. `edit_file` требует уникальный `old`, но модель не видит контекст

`grep` показывает **одну** строку (590) — недостаточно для
уникального `old`. Модели нужен **блок** вокруг строки — а
`read_file` возвращает либо **начало**, либо **всё** (обрезано).
**Нет способа прочитать только участок.**

### 3. `sed` запрещён в whitelist

Модель **попробовала** `sed` как способ обойти `edit_file` — но
`sed` **не в whitelist**. Правильно с точки зрения безопасности,
но модель **рассчитывала** на него.

**Выводы:**
1. **Агент не может править большие файлы** (>50K символов)
   из-за сочетания «read_file обрезает» + «правило 11 запрещает grep»
   + «нет read_file с offset/limit».
2. **Правило 11 вредно** для больших файлов — оно толкает модель
   в тупик. Нужно различать:
   - весь файл в контексте → не grep, сразу edit;
   - файл обрезан → grep **разрешён**, потом read_file вокруг
     строки, потом edit.
3. **`sed` как обходной путь** — модель пытается, но whitelist
   блокирует. **Правильно** (безопасность), но **ожидаемо** модель
   будет пробовать снова.
4. **Нужен `read_file` с offset/limit** — читать конкретный
   участок файла. **Идея на будущее.**

**Это важнее фикса decompose.** Агент **не работает** с большими
файлами — а наш проект такой. Зафиксировано в TODO п.18.

**Артефакты:** журнал `.ai-out/ai-coder/tool-loop-2026-10-09T16-27-25`.

**Ссылки:** TODO п.18, CHANGELOG 10.8 (format_tool_history),
docs/tools.md → «Как формулировать».

---

## 2026-10-09 — decompose на 3 файлах: ✅ успех, но ×3.9 к стоимости

**Что пробовали:** `--decompose` на 3 файлах — расширить только что
сделанное действие `explain` (10.14.10):
- тест в `tests/test_config.py`;
- строка в `README.md`;
- раздел 12 в `docs/scenarios.md`.

**Команда:**
    python -m ai_coder.cli agent "Добавь в tests/test_config.py тест \
        который проверяет что действие explain присутствует в \
        enabled_actions. Добавь в README.md в раздел про действия \
        строку про explain. Добавь в docs/scenarios.md новый \
        раздел 12 про действие explain с примером команды." . \
        --tool-loop --decompose --apply --max-iterations 10 \
        --max-cost-rub 5

**Результат:** ✅ **успех**, **3 подзадачи** (по 1 файлу),
**1.2193 RUB**. Все 3 `verify_commands` — ✅.

**Декомпозиция (v4-pro):**
1. `tests/test_config.py` — тест на `explain` в `enabled_actions`.
2. `README.md` — строка про `explain`.
3. `docs/scenarios.md` — раздел 12.

Порядок **правильный** — тест первым, потом доки.

**Качество результата:**
- **`tests/test_config.py`** — **новый файл** (раньше тестов конфига
  не было!). 22 строки, 3 assert'а:
  - `"explain" in cfg.actions`,
  - `"explain" in cfg.enabled_actions()`,
  - `cfg.enabled_actions()["explain"].enabled is True`.
  Загружает **реальный** конфиг с диска (не мок). Стиль проекта
  (`from __future__ import annotations`, аннотация `-> None`,
  docstring).
- **`README.md`** — строка в правильном разделе (после
  `actions --verbose`), в правильном стиле.
- **`docs/scenarios.md`** — раздел 12 с правильной нумерацией,
  **перед** «Сценарии будущего», в стиле разделов 1–11.
- **Но:** модель **забыла** строку `| 12 | ...` в **таблице обзора**
  сверху файла. Дописано вручную.

**Сравнение с B (10.14.10, 2 файла, прямой tool loop):**

| | B (2 файла, tool loop) | D (3 файла, decompose) |
|---|---|---|
| Подзадач | — | 3 (v4-pro) |
| Стоимость | **0.3096 RUB** | **1.2193 RUB** |
| Дельта | — | **×3.9** |
| Результат | ✅ | ✅ |

**Почему decompose дорог:**
1. **v4-pro decompose** — отдельный LLM-вызов с полным деревом +
   метаданными.
2. **3 подзадачи = 3 × tool loop**. Каждый tool loop тянет
   **сканирование проекта** — это ~5-10K токенов prompt'а
   даже с phase1.
3. Стоимость растёт как `N × (scan + LLM)`.

**Выводы:**
1. **Decompose сработал** — 3 подзадачи × 1 файл, все ✅.
2. **Но для 3 файлов он ×3.9 дороже прямого tool loop.**
   Прямой tool loop стоил бы ~0.3-0.5 RUB (один scan, 3-5 LLM).
3. **Правило п.14 подтверждено на 3 файлах:** decompose оправдан
   для **5+ файлов**, где прямой tool loop зацикливается
   (10.8: ❌ 15 итераций, 7.74 RUB → decompose ✅ 1.22 RUB).
   Для 3 файлов **прямой tool loop дешевле**.
4. **Новая проблема 15b:** узкий промпт подзадачи (только раздел,
   без таблицы) → модель не выходит за рамки. Записано в TODO.
5. **Бонус:** появился `tests/test_config.py` — **первый** тест
   конфига в проекте.

**Ссылки:** TODO п.14, п.15b, CHANGELOG 10.11.2, 10.11.6–10.12.

---

## 2026-10-09 — YAML-стресс: действие explain в 2 файлах, ✅ успех

**Что пробовали:** `agent --tool-loop --apply` на **своём** проекте.
Задача — добавить новое действие `explain` (read-only):
- в `config/config.yaml` — блок `actions.explain`;
- в `config/prompts.yaml` — промпт `explain`;
- `ai_coder/actions.py` — **не трогать**.

**Зачем:** YAML — известная слабость (CHANGELOG 8.3:
«модель слабо правит YAML, шаг 2 в self-hosted E2E не применился»).
Проверяем, жив ли этот баг после фиксов 10.5–10.8.

**Команда:**
    python -m ai_coder.cli agent "Добавь в config/config.yaml новое \
        действие explain с полями: description 'Объяснить \
        файл/функцию/класс', prompt 'explain', mode 'read', \
        exclude_web_assets true. Добавь в config/prompts.yaml промпт \
        explain с system и user (user — с плейсхолдерами depth, \
        depth_hint, files, как у других read-действий). Только эти \
        два файла, actions.py не трогай." . --tool-loop --apply \
        --max-iterations 15 --max-cost-rub 3

**Результат:** ✅ **успех**, **4 итерации**, **0.3096 RUB**, pytest 306 passed.

**Что произошло:**
1. `read_file(config/config.yaml)` — увидел структуру `actions:`.
2. `read_file(config/prompts.yaml)` — увидел промпты.
3. `edit_file(config/config.yaml)` — добавил `explain`
   между `inventory` и `suggest_improvements`.
4. `edit_file(config/prompts.yaml)` — добавил `explain`
   между `inventory` и `suggest_improvements`.
5. `finish(success=true)`.
6. Внешний `verify_commands` → `✅ Проверка пройдена`.

**Качество результата:**
- `config.yaml`: блок `explain` с корректными отступами (2 пробела),
  `mode=read`, `prompt=explain`, `exclude_web_assets=true`.
- `config/prompts.yaml`: `system` (3 строки, включая правило
  «опирайся только на исходники») и `user` (7 пунктов +
  `{{depth}}` / `{{depth_hint}}` / `{{files}}`).
- **`actions.py` не тронут.**
- Стиль промпта — как у `greet`/`inventory` (скопировал паттерн).

**Выводы:**
1. **YAML-слабость закрыта.** Два YAML-edit подряд с идеальными
   отступами. Скорее всего — следствие фикса 10.8
   (`format_tool_history` → 10 000 символов): модель видит файл
   целиком, выбирает уникальный `old`.
2. **Правило 3 («после edit → finish») не сработало слишком
   рано** — модель сделала **обе** правки подряд. Это был главный
   риск, реализовался в правильную сторону.
3. **`read_file × 2 → edit_file × 2 → finish`** — минимальная
   последовательность, 4 итерации.
4. **Инструкция «не трогай actions.py» сработала.**
5. **`verify_commands` ✅** — 306 тестов не сломались.
6. **0.31 RUB** — выше песочницы (0.16): `config.yaml` +
   `prompts.yaml` большие, проект сканируется целиком.

**Артефакт:** новое действие `explain` — реально полезно
(из TODO «Действия»). Закоммичено в 10.14.10.

**Ссылки:** CHANGELOG 8.3 (YAML), 10.8 (format_tool_history),
docs/tools.md → «Как формулировать».

---

## 2026-10-09 — автономное написание кода: класс Stats, ✅ успех

**Что пробовали:** `agent --tool-loop --apply` на пустой песочнице
`/tmp/agent-write` (только `README.md`). Задача — **написать с нуля**
модуль `stats.py` с классом `Stats` (методы `add/mean/min/max/count`)
и `test_stats.py` с тестами на все методы, включая пустой список.

**Команда:**
    python -m ai_coder.cli agent "Создай в проекте модуль stats.py \
        с классом Stats. Класс Stats хранит список чисел и умеет: \
        add(x) — добавить; mean() — среднее (0.0 для пустого); \
        min() — минимум или None; max() — максимум или None; \
        count() — количество. Создай test_stats.py с тестами на все \
        методы, включая пустой список. После написания запусти pytest \
        и убедись, что всё проходит." /tmp/agent-write --tool-loop \
        --apply --max-iterations 15 --max-cost-rub 3

**Результат:** ✅ **успех**, **4 итерации**, **0.1635 RUB**, `8 passed`.

**Что произошло:**
1. `list_files(".")` — разведка (`.ai-out/`, `README.md`).
2. `write_file(stats.py)` — 858 символов, класс `Stats`.
3. `write_file(test_stats.py)` — 1018 символов, тесты.
4. `run_shell("python -m pytest -q")` — `........` (8 passed).
5. `finish(success=true)`.
6. Внешний `verify_commands` → `✅ Проверка пройдена`.

**Качество кода (что написал агент сам, без подсказок):**
- докстринги на классе и **на каждом методе**;
- приватное поле `self._numbers`;
- аннотации: `x: float -> None`, `mean() -> float`, `count() -> int`;
- `if not self._numbers: return 0.0` — корректный edge case;
- в тестах — **`pytest.approx`** для float-сравнений
  (`assert s.mean() == pytest.approx(1.5)`);
- **8 тестов** — покрывают `empty`, `single`, `negative`,
  `mean_float` (последние три модель придумала сама).

**Шероховатости (микро):**
- `def min(self):` / `def max(self):` — **без** `-> float | None`
  (в отличие от остальных методов — модель не уверена в union-типах);
- методы называются `min`/`max` — затеняют built-in (работает,
  но стилистически спорно).

**Выводы:**
1. **`write_file` в цикле работает.** Раньше был покрыт только
   юнит-тестами — теперь подтверждён живьём.
2. **Агент пишет код на уровне «senior».** Докстринги, приватные
   поля, `pytest.approx`, edge cases — всё **без просьбы**.
3. **Агент пишет тесты, которые проверяют.** Не «для галочки»,
   а покрытие всех методов + граничные случаи.
4. **Минимальная последовательность** —
   `list_files → write_file × 2 → run_shell → finish`.
   Ни одного лишнего `read_file`. **4 итерации — оптимум.**
5. **Агент сам верифицирует** — запускает pytest **до** finish.
6. **Двухуровневая защита:** модель проверяет себя +
   `verify_commands` после finish.
7. **0.16 RUB** за ~1900 символов кода. Для сравнения:
   `suggest_improvements --depth deep` стоил 5.36 RUB —
   в **33 раза дороже**.

**Ссылки:** CHANGELOG 10.5–10.8, docs/tools.md → «Как формулировать».

---

## 2026-10-08 — задача 10.8: 6 файлов, 5 правок, 3 теста

**Что пробовали:** попросить агента сделать итерацию 10.8
(`format_tool_history` — read_file 3000→10000 символов, 6 файлов,
5 правок, 3 теста) одной задачей.

**Команда:**
    python -m ai_coder.cli agent "$(cat /tmp/task_10_8.txt)" . --tool-loop --dry-run

**Результат:** ❌ **неуспех**, 15 итераций, 0 правок, 1.82 RUB.

**Что произошло:**
- Модель `flash` 14 раз вызвала `read_file`, 1 раз `grep`.
- **Ни одной** правки.
- `read_file` в истории обрезался **до 3000 символов**, файл
  `docs/tools.md` (~8000 символов) **не влезал** → модель шла в `grep`
  → зацикливалась.

**Выводы:**
1. **`format_tool_history` — критичный лимит.** `read_file` должен
   видеть файл целиком (до 10000 символов).
2. **`--dry-run`** — не подходит для многошаговых задач.
3. **6 файлов** — слишком много для одной задачи.
4. **Промпт 55 строк** — модель теряет фокус.

**Что сделали:**
- **10.8** — fix `format_tool_history` (10000 символов). ✅
- **B** — документация: промпт < 15 строк, 1-2 файла, без `--dry-run`
  для многошаговых.
- **TODO**: п. 3, 4, 7, 8, 9.

**Ссылки:** CHANGELOG 10.8, TODO п.3, docs/tools.md → «Как формулировать».

---

## 2026-10-09 — задача 10.11.2: run_agent_decompose (55 строк)

**Что пробовали:** попросить агента реализовать итерацию 10.11.2
(`run_agent_decompose` — 2 dataclass, 3 функции, промпт, config,
3 теста, 7 подпунктов) одной задачей.

**Команда:**
    python -m ai_coder.cli agent "$(cat /tmp/task_10_11_2.txt)" . --tool-loop --dry-run --model deepseek-v4-pro

**Результат:** ❌ **неуспех**, 15 итераций, 0 правок, **7.7453 RUB**.

**Что произошло:**
- Модель `v4-pro` **10 раз вызвала `run_shell grep`**, 5 раз `read_file`.
- **Ни одной** правки.
- Модель искала `run_tool_loop`, `run_agent`, `@dataclass` — **не находила**
  нужного контекста, искала снова.

**Выводы:**
1. **`--dry-run` + 15 итераций = зацикливание.** Подтверждено на `v4-pro`.
2. **`v4-pro` тоже зацикливается** — не только `flash`.
3. **Задача 55 строк / 7 подпунктов** — модель теряет фокус.
4. **Предупреждение про backticks — ЛОЖНОЕ** для `$(cat file)`.
   Backticks **внутри файла** bash **не трогает**. Предупреждение 10.10
   сработало на **результат подстановки**, а не на CLI-аргумент.

**Что нужно сделать:**
- **TODO п.11 (новый):** предупреждение 10.10 — **не срабатывать**,
  если backticks пришли из `$(cat file)`. Проверять **исходный**
  CLI-аргумент, а не `goal`.
- **TODO п.12 (новый):** для задач > 3 подпунктов — **только Python/sed**
  или **разбить на несколько запусков** (уже есть в B, но подтверждено).

**Ссылки:** TODO п.10 (backticks), п.12 (новый).

---

## 2026-10-09 — задача 10.8 (после fix): 1 файл, 1 правка

**Что пробовали:** ту же задачу 10.8, но **после** fix
`format_tool_history` (10000 символов).

**Команда:**
    python -m ai_coder.cli agent "Замени в docs/tools.md 'transcript.jsonl' на 'history.json', если есть" . --tool-loop --dry-run

**Результат:** ✅ **успех**, 1 итерация, 0.10 RUB.

**Что произошло:**
- `read_file(docs/tools.md)` — **весь файл** в контексте (8000 < 10000).
- Модель **видит**, что строки нет → `finish(success=true)`.
- **1 итерация.**

**Выводы:**
1. **Fix 10.8 работает** — 15× быстрее, 18× дешевле.
2. **1 файл + 1 правка** — модель справляется **за 1 итерацию**.
3. **Формулировка «найди + замени, если есть»** — работает.

**Ссылки:** CHANGELOG 10.8.

---

## 2026-10-09 — decompose (2 файла): ✅ успех

**Что пробовали:** E2E `--decompose` на задаче «добавь
`test_field_decompose: int = 100` в `AgentConfig` и в `config.yaml`».

**Команда:**
    python -m ai_coder.cli agent "$(cat /tmp/task_test.txt)" . --tool-loop --decompose --interactive --max-iterations 10

**Результат:** ✅ **успех**, 2 подзадачи × 1 файл, **0.6399 RUB**.

**Что произошло:**
- v4-pro (decompose) — **2 подзадачи** (по 1 файлу).
- tool loop (flash) — `edit_file(config.py)` ✅, `edit_file(config.yaml)` ✅.
- Все правки применены.
- Итог: **✅ успех**, стоимость **0.64 RUB**.

**Выводы:**
1. **Decompose работает** — v4-pro точно разбивает.
2. **2 файла → 2 подзадачи** — идеально.
3. **Интерактив** — панели, `y`.
4. **Стоимость** — 0.64 RUB. Без decompose — ~0.05-0.10 RUB.
   **Дельта — 6-10×**.

**Ссылки:** CHANGELOG 10.11.2, TODO п.14.

---


## 2026-10-09 — decompose (задача 10.8, 5 подзадач): ❌ неуспех

**Что пробовали:** E2E `--decompose` на задаче 10.8 (6 файлов,
5 правок, 3 теста) — но **задача уже решена** в git.

**Команда:**
    python -m ai_coder.cli agent "$(cat /tmp/task_10_8_short.txt)" . --tool-loop --decompose --interactive --max-iterations 10

**Результат:** ❌ **неуспех**, 5 подзадач, стоп на 2-й, **1.2245 RUB**.

**Что произошло:**
- v4-pro — **5 подзадач** (по 1 файлу): config.py, config.yaml,
  prompts.yaml, tools.py, test_tools.py.
- **Подзадача 1** — ✅: `read_file(config.py)`, увидела «уже есть»,
  `finish(success=true)`. 1 итерация, 0.097 RUB.
- **Подзадача 2** — ❌: `parse_error` на 3-й итерации.
  `tool JSON no '{' found` — flash вернула `{}`.
- **Стоп** по правилу `if not success: break`.

**Выводы:**
1. **Decompose работает** — v4-pro **точно** разбил на 5.
2. **Проблема 11** (new): `parse_error` при `{}` от flash.
3. **Проблема 12** (new): подзадачи **не знают**, что задача
   уже решена. Подзадача 1 «поняла», подзадача 2 — нет.
4. **Проблема 13** (new): **нет отката** при частичном провале.
5. **Проблема 14** (new): decompose **дорого** для 2 файлов.
   Для 5+ — **оправдан** (1.22 RUB с decompose vs 7.74 RUB
   в 10.8 без decompose — в **6× дешевле**).

**Ссылки:** CHANGELOG 10.11.2, TODO п.11-14.

---
