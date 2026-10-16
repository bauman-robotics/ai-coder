# DeepSeek Harness (dsh) — эксперименты

Дневник экспериментов с **DeepSeek Harness** (`dsh`) — открытым агентом
от DeepSeek AI. https://github.com/deepseek-ai/deepseek-harness

**Зачем:** понять, чем `dsh` **дополняет** `ai-coder` (не конкурирует,
а другой слой), что **взять** из его идей, где `ai-coder` **сильнее**.

**Формат:** `D1, D2, ...` (D = DeepSeek harness).

**Связь:** `docs/experiments.md` — эксперименты **с ai-coder**
(E1-E38). Здесь — только `dsh`.

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
