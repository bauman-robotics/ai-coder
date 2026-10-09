# Сценарии использования ai-coder

Обзор **сценариев** — как использовать `ai-coder` для разных задач.
По возрастанию автономности: от «один запрос» до «дай задачу — получи PR».

## Обзор

| # | Сценарий | Команда | Автономность | Стоимость |
|---|---|---|---|---|
| 1 | Обзор проекта | `run greet` | ⚪ | ~0.05 RUB |
| 2 | Инвентарь | `run inventory` | ⚪ | ~0.05 RUB |
| 3 | Улучшения | `run suggest_improvements` | ⚪ | ~0.15 RUB |
| 4 | README | `run write_readme --apply` | 🟡 | ~0.3 RUB |
| 5 | Докстринги | `run add_docstrings --apply` | 🟡 | ~0.3 RUB |
| 6 | Рефакторинг | `run refactor --apply` | 🟡 | ~0.4 RUB |
| 7 | Агент (план → шаги) | `agent "<goal>" --apply` | 🟢 | ~0.05–0.2 RUB |
| 8 | Tool loop | `agent "<goal>" --tool-loop --apply` | 🟢 | ~0.05–0.5 RUB |
| 9 | Decompose (5+ файлов) | `... --decompose` | 🟢 | ~0.6–2 RUB |
| 10 | Replan при fail | `... --decompose-replan` | 🟢 | +0.5 RUB/replan |
| 11 | Авто-починка | `fix --max-attempts N` | 🟢 | ~0.3–1.5 RUB |
| 12 | Объяснение кода | `run explain` | ⚪ | ~0.05 RUB |

**Легенда автономности:**
- ⚪ — один запрос, отчёт.
- 🟡 — план + apply (с бэкапом).
- 🟢 — итеративно, с verify и fix.

---

## 1. Обзор проекта

**Что:** LLM читает проект и описывает: структура, стек, точки входа.

**Команда:**

    ai-coder run greet . --depth normal

**Когда:** первый раз в проекте, понять структуру.

**Стоимость:** ~0.05 RUB (`deepseek-flash`).

**Флаги:**
- `--depth shallow|normal|deep`
- `--only-path <dir>` — сузить контекст.
- `--no-cache` / `--refresh`.
- `--exclude-web` — исключить вёрстку.

---

## 2. Инвентарь

**Что:** список классов, функций, переменных.

**Команда:**

    ai-coder run inventory . --depth normal

**Когда:** понять API проекта.

**Стоимость:** ~0.05 RUB.

---

## 3. Предложения по улучшению

**Что:** LLM предлагает улучшения (архитектура, читаемость, тесты).

**Команда:**

    ai-coder run suggest_improvements . --depth deep

**Когда:** аудит проекта перед рефакторингом.

**Стоимость:** ~0.15 RUB (`v4-pro` deep).

---

## 4. README

**Что:** сгенерировать README.md по проекту.

**Команда:**

    ai-coder run write_readme . --apply

**Когда:** нет README или устарел.

**Стоимость:** ~0.3 RUB.

**Что делает:**
1. LLM возвращает план операций (`create_file` / `edit_file`).
2. Apply с бэкапом.
3. `py_compile` проверка.

**Флаги:** `--apply --yes`, `--max-fix-attempts N`.

---

## 5. Докстринги

**Что:** добавить докстринги к функциям и классам.

**Команда:**

    ai-coder run add_docstrings . --apply

**Когда:** нет докстрингов.

**Стоимость:** ~0.3 RUB.

---

## 6. Рефакторинг

**Что:** предложить (и применить) рефакторинг.

**Команда:**

    ai-coder run refactor . --apply --model deepseek-v4-pro

**Когда:** код сложный, есть дубли.

**Стоимость:** ~0.4 RUB.

---

## 7. Агент (декларативный: план → шаги)

**Что:**
1. **Phase1** — metadata-планировщик (дерево + метаданные), кэшируется.
2. **Phase2** — планировщик строит план шагов.
3. **Шаги** — LLM → `WritePlan` → apply → verify.
4. **Fix-цикл** при ошибках.

**Команда:**

    ai-coder agent "добавь поле test_field в AgentConfig" . --apply

**Когда:** задача из 1–3 файлов, простой план.

**Стоимость:** ~0.05–0.2 RUB.

**Флаги:**
- `--interactive` — подтверждение каждого шага.
- `--commit` — автокоммит после успеха.
- `--max-cost-rub N` — лимит.
- `--preview-only` — только план.
- `--only-path <dir>` — селективный контекст.

**Ограничения:** шаги только `edit`. Нет `read_file`, `grep`.

---

## 8. Tool loop (итеративный)

**Что:** LLM сама вызывает инструменты до `finish`.

**5 инструментов:** `read_file`, `list_files`, `write_file`, `edit_file`, `run_shell`.

**Команда:**

    ai-coder agent "найди и исправь баг в cache.py" . --tool-loop --apply

**Когда:** задача требует чтения, анализа, проверки, итераций.

**Стоимость:** ~0.05–0.5 RUB.

**Флаги:**
- `--dry-run` — dangerous-инструменты не выполняются.
- `--interactive` — подтверждение каждого dangerous.
- `--resume <dir>` — продолжить с журнала.
- `--max-iterations N`.
- `--commit`.

---

## 9. Decompose (большая задача → подзадачи)

**Что:**
1. V4-pro разбивает задачу на N подзадач (по 1–2 файла).
2. Для каждой — `run_tool_loop` (flash).
3. Retry v4-pro при fail.
4. Откат всех успешных при fail (opt-in).
5. Журнал `decompose-<ts>/` + `report.md`.

**Команда:**

    ai-coder agent "6 файлов, 5 правок, 3 теста" . --tool-loop --decompose --apply

**Когда:** 5+ файлов, 5+ правок.

**Стоимость:** ~0.6–2 RUB.

**Флаги:**
- `--decompose-replan` — перепланировать при fail.
- `--decompose-rollback-on-fail` — откат.

**Ограничение:** дорого для 2 файлов (~0.6 vs 0.05).

---

## 10. Replan при fail

**Что:** при fail подзадачи (после retry v4-pro) — v4-pro анализирует ошибку и решает:
- **skip** — пропустить подзадачу.
- **modify** — обновить оставшиеся.
- **stop** — остановить.

**Команда:**

    ai-coder agent "<goal>" . --tool-loop --decompose --decompose-replan --apply

**Когда:** сложные задачи с риском fail.

**Стоимость:** +0.5 RUB за replan.

---

## 11. Авто-починка ошибок

**Что:** цикл `verify → fix (tool loop) → verify → ...` до `success`
или `--max-attempts`. Не строит план заранее — реагирует на конкретные
ошибки от pytest/ruff/mypy.

**Команда:**

    ai-coder fix . --verify "python -m pytest -q;ruff check ."

**Когда:** после правок (своих или агента) тесты/линтер падают,
и надо, чтобы агент сам починил до N раз. Или — как «страховка»
после ручного рефакторинга.

**Стоимость:** ~0.3–1.5 RUB. Сильно зависит от числа попыток;
ограничивается `--max-cost-rub N`.

**Флаги:**
- `--verify "cmd1;cmd2"` — переопределить `config.agent.verify_commands`.
- `--max-attempts N` — сколько попыток (по умолчанию 3).
- `--max-cost-rub N` — бюджет всего цикла (10.14.4).
- `--interactive` — подтверждение каждого dangerous-инструмента.
- `--journal/--no-journal` — писать журнал `autofix-<ts>/`.
- `--model`, `--depth`, `--exclude` — как у остальных команд.

**Итог:** `attempts`, `stopped_reason` (`completed` | `max_attempts`
| `max_cost` | `loop_failed`), `total_cost_rub`, `final_errors`,
путь к журналу.

**Журнал:** `autofix-<ts>/report.md` + `attempt-N/tool-loop-<ts>/`.

**Отличия от `agent --tool-loop`:** `fix` не планирует — сразу
запускает цикл по ошибкам verify. Полезно, когда уже понятно,
что именно надо править (ошибки от pytest/ruff/mypy).

---

## 12. Объяснение кода (explain)

**Что:** LLM читает проект (или выбранные пути) и объясняет —
что делает код, как он устроен, где точки входа и ключевые
структуры.

**Команда:**

    ai-coder run explain . --depth normal

**Когда:** нужно быстро разобраться в незнакомом коде, понять
архитектуру или объяснить изменения коллеге.

**Стоимость:** ~0.05 RUB (`deepseek-flash`).

**Флаги:**
- `--only-path <dir>` — сузить контекст до каталога.
- `--depth shallow|normal|deep`.
- `--exclude-web` — исключить вёрстку.
- `--no-cache` / `--refresh`.

---

## Сценарии **будущего** (TODO)

Не реализованы, но запланированы. См. `TODO.md`.

- **`--auto-fix-issues`** — прогон `pytest` → fix → повтор до success.
- **`--with-tests`** — код + тесты для изменённых файлов.
- **`--issue <file>`** — читать issue (markdown) → план → выполнить.
- **`--multi-step`** — цепочка задач из CLI.
- **`--verify-only`** — только проверка без правок.
- **Git + PR** — ветки, commit, push, PR (Уровень D).
- **Multi-turn** — уточнения от агента.

---

## Что **дальше**

- **Инструменты tool loop** — в [`docs/tools.md`](tools.md).
- **Проблемы и эксперименты** — в [`docs/experiments.md`](experiments.md).
- **Текущее состояние** — в [`docs/state.md`](state.md).
