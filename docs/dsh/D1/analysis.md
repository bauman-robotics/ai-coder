# D1 — анализ ответа dsh (сравнение с нашим планом)

**Контекст:** dsh дал план встраивания Validator (`run_reverse_check`
per-подзадача в `run_agent_decompose`). Здесь — **наш анализ**:
что совпало с нашим планом, что dsh **добавил**, что **пропустил**.

**Сырые материалы:** `session.v4.jsonl`, `answer.md`,
`reasoning-seq109.md`, `reasoning-seq121.md`.

## Trajectory (что dsh делал)

**15 шагов, 24 tool calls, 1 turn.**

| Шаг | Что делал |
|---|---|
| 1 | `find` + `glob` — разведка структуры. |
| 2 | `read reverse.py` + `read decomposer.py` — наши файлы. |
| 3 | `grep run_reverse_check\|_collect_diff` + `grep class` — вызовы/классы. |
| 4 | `read tool_loop.py:640-780` + `read models.py:25-155` — точками. |
| 5 | `read models.py:210-253` + `grep reverse_check` — уточнение. |
| 6 | `read tool_loop.py:800-930` + `grep cli.py` — сигнатуры. |
| 7 | `read cli.py:1690-1750` + `read cli.py:1325-1355` — CLI-вызовы. |
| 8 | `bash grep` + `bash sed` — тесты + apply.py. |
| 9 | `bash grep` x2 — тесты + CLI (reverse_check/decompose). |
| 10 | `read tool_loop.py:120-200` + `bash grep backup_dir` — backup-манифест. |
| 11 | `bash grep agent_reverse_check` — промпт. |
| 12 | `read prompts.yaml:715-755` — сам промпт. |
| 13 | `bash grep subtask_results\|report.md` — отчёт. |
| 14 | `bash sed tests/test_agent.py:2810-2915` — тесты verify/rollback. |
| 15 | `assistant/message` — финальный ответ. |

**Tool set dsh:** `bash`, `glob`, `grep`, `read` (с `offset`+`limit`).

**Ключевое:**
- **Параллельные tool calls** — 2 read за шаг (шаги 2, 4, 5, 7, 8, 9, 10, 12).
- **Точное чтение** — `read offset=640, limit=140` (не весь файл).
- **Reasoning** — в `content[0]` (thinking chunks).
- **Stop condition** — `step/end reason: {'kind': 'completed'}`.

## Статистика dsh (виджет после turn)

- **1 turn, 15 steps** — совпадает с trajectory.
- **208 tok/s** — скорость генерации (Flash — быстрый).
- **416K токенов** — **кумулятивно** (сумма `totalTokens` по 15 шагам).
  - Каждый шаг **включает** весь контекст.
  - `totalTokens` **последнего** шага = 55K (не путать).
- **Cache hit 89%** — input-токены **из кэша**.
  - Cache hit — дешёвый (0.02 CNY/1M).
  - Cache miss — дорогой (1 CNY/1M).
  - **Экономия:** ~×50 по input.
- **5% of context used** (подсказка) — контекст **последнего** запроса
  (55K токенов) относительно **окна** модели (~1.1M).
  Не путать с кумулятивными 416K.

### Сравнение с ai-coder

| Метрика | dsh | ai-coder |
|---|---|---|
| Итерации | 15 steps | до 20 (`--max-iterations`) |
| Скорость | 208 tok/s | не логируется |
| Total tokens | 416K (кумулятивно) | логируется в `usage.jsonl` |
| Cache hit | 89% | логируется (`cache_hit_tokens`) |
| Context used | 5% (55K / ~1.1M) | не логируется |
| Turn / step | явные сущности | нет (`run_tool_loop` — плоско) |

### Что взять

1. **Скорость (tok/s)** — в `usage.jsonl` есть `duration_ms`,
   можно посчитать.
2. **Кумулятивный `total_tokens` за сессию** — суммировать по итерациям,
   писать в `report.md`.
3. **Cache hit rate** — в `report.md` строка «Cache hit: X%».
4. **Context used** — размер последнего запроса / окно модели.
   Полезно для контроля «не приближаемся ли к лимиту».
5. **Turn / step — явные сущности** — иерархия в логе.

## Сравнение dsh vs наш план

| Пункт | Наш план | dsh | Итог |
|---|---|---|---|
| Diff-изоляция | «подзадачи» | **baseline-снапшот** (`git stash create`) | dsh нашёл |
| Точка вставки | «после finish» | **после retry** (346-348), до max_cost | dsh уточнил |
| `ok=False` | «semantic_failed» | **3 политики** (warn/fail/rollback) | dsh расширил |
| `success` | менять | **не менять**, +`verified` | dsh защитил |
| Rollback | простой | **опасен**, opt-in + retry | dsh предупредил |
| Стоимость | «второй вызов» | **+v4-pro per подзадача**, пропуск при `applied_ops==0` | dsh детализировал |
| Fail-open | не проговорили | **сохранить** `parse_error -> ok=True` | dsh защитил |
| Тесты | «тест» | **конкретный список** | dsh дал |
| Промпт | `agent_subtask_reverse_check` | **не обязателен** (MVP) | dsh прагматичнее |
| CLI-флаг | `--decompose-reverse-check` | мимо `--tool-loop`, cli.py:1443 | совпало |
| GUI | прокинуть | `gui/app.py:79,144` | dsh конкретнее |

## Что dsh **добавил** (мы пропустили)

### 1. Diff-изоляция — **главный** риск

`_collect_diff` собирает `git diff HEAD` по **всему worktree**.
В decompose **нет** автокоммита -> подзадача 3 увидит правки 1 и 2.
Валидатор будет судить **не тот diff**.

**Решения:**
- **A** (рекомендация dsh): baseline-снапшот через `git stash create`.
- **B:** backup-манифест (не видит `run_shell`).
- **C:** MVP-заглушка (весь worktree).

### 2. Точка вставки — **после retry**, не до

Строки 333-346: `subtask_results[-1] = {...}` (wholesale-replace).
Вставка **до** retry -> новая запись **потеряется**.
Правильно: между 346 и 348, под условием `loop_result.success and not dry_run`.

### 3. Политика `ok=False` — **3 уровня**, не одно поведение

- **warn** (default) — проблемы в `subtask_results`, продолжаем.
- **fail** (opt-in) — `parse_error`, return. **Отдельный блок** (существующий
  fail-путь 354-439 **не сработает** при `loop_result.success=True`).
- **rollback** (opt-in) — откат + **retry с фидбеком**.

### 4. Не менять `success` — добавить `verified`

`success` читают тесты + `--rollback-on-fail` (стр. 425-431).
Изменение семантики -> поломка отката и тестов.

### 5. Rollback при `ok=False` — **опасен**

Откат подзадачи N **сломает** N+1 (писались поверх N).
Backup — по файлам, **не** «точка во времени».
Дефолт — warn без отката, rollback только opt-in + retry.

### 6. Стоимость — **заметная**

RC fallback на `decompose_model` = **v4-pro** per подзадача.
**Дороже** loop'а на flash. Митигации:
- явный `model`,
- учёт в `remaining`/`max_cost`,
- **пропуск при `applied_ops == 0`**.

### 7. Fail-open — **сохранить**

`parse_error -> ok=True`. Иначе флаки LLM **завалят** хорошие подзадачи.

### 8. Тесты — **конкретный список**

- default `False` -> существующие не ломаются.
- default `True` -> `test_run_agent_decompose_retry_cost_summation` (0.44) упадёт.
- форма `subtask_results` — проходит если не менять `success`.
- `report.md` — только существование файла.
- `conftest.py:195` — `agent_reverse_check` уже есть.
- `cli.py:1443` — `--reverse-check требует --tool-loop`; новый — мимо.
- `gui/app.py:79,144` — прокинуть.

## Что dsh **пропустил**

- Новый промпт `agent_subtask_reverse_check` — dsh считает **не обязательным** (MVP).
- Детали GUI — упомянул, но не раскрыл.
- (Спорно) diff-контекст предыдущих подзадач — dsh считает **известным
  ограничением**, не предлагает решения.

## Уроки

1. **dsh — архитектурный ревьюер.** Сильнее `ai-coder` в планировании.
2. **Flash справился** с разведкой 5+ файлов — **дёшево** (~1 RUB).
3. **Reasoning логируется** — мы видим **как** модель думает.
4. **Reasoning растёт** перед сложным (шаг 13: 9821 chars).
5. **Параллельные tool calls** — 24 calls за 15 шагов.
6. **Cache hit** работает отлично (0 -> 48896).
7. **dsh находит архитектурные риски**, которые `ai-coder` не делает
   (у нас нет фазы «ревью плана»).
8. **Разделение труда:** dsh — план, ai-coder — исполнение.

## Что взять в `ai-coder`

См. `docs/dsh.md` -> «Что взять в ai-coder» (D2-кандидаты):
- **Reasoning logging** — 💎 (если API отдаёт).
- **Параллельные tool calls** — 💎.
- **`grep`/`glob` как инструменты** — 💎.
- **Event-sourced JSONL** (append-only) — 💎 (стратегическое).
