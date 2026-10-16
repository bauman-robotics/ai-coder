I have everything I need. Here is the design document.

---

# D4 — Дизайн `spawn_subagent` для ai-coder

**Статус:** дизайн (read-only, код не менялся).
**Основание:** `docs/autonomy.md` §9, `docs/dsh.md` D1–D3, `docs/experiments.md` E37/E38/E39.
**Предпосылки (уже в `main`):** Router `_resolve_subagent` ([decomposer.py:122](ai_coder/agent/decomposer.py#L122)), Validator `--decompose-reverse-check`, Feedback `_build_feedback` ([decomposer.py:79](ai_coder/agent/decomposer.py#L79)).

Ключевой вывод из разбора кода: **`spawn_subagent` — не «ещё один tool», а второй оркестратор.** Существующий `execute_tool` физически не может его выполнить (см. §3), поэтому 80% работы — это плюмбинг контекста, а не сам tool.

---

## 1. `SubagentSpec`

### Где хранить

**Pydantic-модель в `config.py`**, а не dataclass в `models.py`.

Обоснование:
- `Subtask` в `models.py` — это dataclass, потому что он **парсится из JSON LLM** и не имеет схемы. `SubagentSpec` приходит **из конфига** → нужна валидация **на старте** (`load_config`), а не в момент вызова.
- Валидация «fail fast» принципиальна: `cfg.api.pricing_for(model)` **бросает `KeyError`** на неизвестной модели ([config.py:74-77](ai_coder/config.py#L74-L77)). Опечатка в `model:` внутри subagent'а иначе упадёт посреди прогона, уже потратив деньги.
- Agent-код уже импортирует `config` (`from ..config import AppConfig, PromptsConfig`), так что дублировать модель в `models.py` не нужно.

```python
# ai_coder/config.py  (добавить импорт: ConfigDict, model_validator)
_SUBAGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class SubagentConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str  # ^[a-z][a-z0-9-]{1,30}$
    description: str  # попадает в промпт родителя
    tools: list[str]  # подмножество TOOL_REGISTRY
    model: str | None = None  # None → cfg.api.model
    max_iterations: int = Field(5, ge=1, le=30)
    instructions: str | None = None  # НЕ system_prompt — см. ниже
    max_cost_rub: float | None = Field(None, gt=0)
```

### Про `system_prompt` — рекомендация не делать его

В ТЗ поле помечено `system_prompt?`. **Предлагаю заменить на `instructions`.**

Причина: system-промпт `agent_tool_json` — это **жёсткий контракт строгого JSON** ([prompts.yaml:307-320](config/prompts.yaml#L307-L320)): «Не пиши текст вокруг JSON. Никаких markdown-обёрток». Если разрешить subagent'у подменять system, первый же эксперимент с «дружелюбным» промптом сломает `parse_tool_action` и уйдёт в `parse_retries`.

Правильно: `instructions` подставляется в **user**-промпт отдельным блоком `{{role_section}}` (аналогично `{{feedback_section}}` из D3). Контракт JSON сохраняется, роль — настраивается.

### Валидация

| Что | Где | Правило |
|---|---|---|
| `name` формат | `field_validator` | `^[a-z][a-z0-9-]{1,30}$` — нижний регистр, чтобы LLM не путал регистр в `args` |
| `name` уникальность | `@model_validator(mode="after")` на `AgentConfig` | дубликат → `ValueError` со списком имён |
| `tools` непустой | `field_validator` | `[]` → ошибка (бессмысленный subagent) |
| `tools` ⊆ `TOOL_REGISTRY` | `field_validator` | импорт `TOOL_REGISTRY` в `config.py` **нельзя** (цикл: `tools.py` → `scanner` → ...). Валидировать **лениво** через `field_validator`, делая `from .tools import TOOL_REGISTRY` внутри функции |
| `spawn_subagent ∉ tools` | `field_validator` | depth = 1 (см. §4) |
| `model` имеет цены | `@model_validator` на `AgentConfig` | `model in self.api.pricing` — иначе `KeyError` в рантайме |

```python
@model_validator(mode="after")
def _check_subagents(self):
    names = [s.name for s in self.subagents]
    dupes = {n for n in names if names.count(n) > 1}
    if dupes:
        raise ValueError(f"duplicate subagent names: {sorted(dupes)}")
    for s in self.subagents:
        if s.model and s.model not in self.api.pricing:
            raise ValueError(f"subagent '{s.name}': нет цен для модели '{s.model}'")
    return self
```

**Критично для совместимости:** `subagents: list[SubagentConfig] = []` по умолчанию. Существующие 491 тест и `config/config.yaml` (где секции нет) не ломаются. Это тот же приём, что с `feedback_enabled=True`.

---

## 2. Секция в `config.yaml`

```yaml
agent:
  # ... существующее ...

  # --- Subagents (Направление 12, D4) ---
  # Пусто/отсутствует → spawn_subagent НЕ регистрируется и НЕ попадает
  # в промпт: нулевой оверхед на существующие сценарии.
  subagents:
    - name: code-explorer
      description: "Ищет определения символов и вызовы. Read-only."
      tools: [read_file, read_symbol, list_files, run_shell]
      model: deepseek-flash
      max_iterations: 5
      instructions: "Отвечай списком файл:строка. Не пересказывай код."
      max_cost_rub: 1.0

    - name: test-runner
      description: "Запускает pytest и возвращает только упавшие тесты."
      tools: [run_shell]
      model: deepseek-flash
      max_iterations: 3
      max_cost_rub: 0.5

    - name: markdown-writer
      description: "Пишет и правит markdown-документы."
      tools: [read_file, write_file]
      model: deepseek-v4-pro
      max_iterations: 8
      max_cost_rub: 2.0

  # --- caps (anti-abuse, §5) ---
  subagent_max_per_task: 3            # максимум spawn на один tool loop
  subagent_max_total_cost_rub: 3.0    # суммарный лимит на все spawn
  subagent_default_max_cost_rub: 1.5  # лимит одного spawn, если spec.max_cost_rub=None
```

Три уровня лимитов — не избыточность: `max_per_task` бьёт по «злоупотреблению», `max_total_cost_rub` — по «много дорогих», `default_max_cost_rub` — по «один жирный». Плюс `remaining` родителя (§4).

---

## 3. Инструмент `spawn_subagent`

### 3.1 Главная проблема: `execute_tool` не подходит

Реестр типизирован как `dict[str, tuple[ToolSpec, Callable[[dict, Path], ToolResult]]]` ([tools.py:779](ai_coder/tools.py#L779)), и `execute_tool` вызывает `fn(args, project_root)` ([tools.py:955](ai_coder/tools.py#L955)). Tool-функция **не видит** `cfg`, `prompts_cfg`, `ctx`, бюджет, `depth`. Плюс `tools.py` не может импортировать `tool_loop.py` — это **цикл** (`tool_loop.py:40` импортирует `execute_tool`).

**Решение: перехват в `tool_loop.py`, а не маршрутизация через `execute_tool`.**

`ToolSpec` всё равно регистрируем в `TOOL_REGISTRY` — он нужен для промпта и для проверки `tool not in TOOL_REGISTRY` в `parse_tool_action` ([tools.py:1081](ai_coder/tools.py#L1081)). Но callable — это **заглушка-предохранитель**:

```python
# tools.py
"spawn_subagent": (
    ToolSpec(
        name="spawn_subagent",
        description=(
            "Делегировать подцель настроенному subagent'у. "
            "Дорого: это отдельный агент со своим контекстом. "
            "Используй для широкой разведки/многошаговой работы, "
            "не для одного чтения файла."
        ),
        args={
            "name": "имя subagent'а из списка ДОСТУПНЫЕ SUBAGENTS",
            "goal": "что именно сделать (>= 10 символов)",
        },
        returns="краткая выжимка: статус, summary, файлы, стоимость",
    ),
    _tool_spawn_unavailable,   # (args, project_root) → ok=False
),
```

`_tool_spawn_unavailable` возвращает `ToolResult(ok=False, error="spawn_subagent доступен только внутри tool loop")` — на случай вызова из `apply`/`verify`.

В `_tool_loop_one_iteration` (перед `execute_tool`, [tool_loop.py:617](ai_coder/agent/tool_loop.py#L617)):

```python
if action.tool == "spawn_subagent":
    tool_result = _spawn_from_ctx(ctx, action.args)
else:
    tool_result = execute_tool(...)
```

`_spawn_from_ctx` живёт в **новом модуле `ai_coder/agent/spawn.py`**, который импортирует `run_tool_loop` из `.tool_loop`. Импорт в `tool_loop.py` — **ленивый, внутри функции** (разрывает цикл, как это уже сделано для `from ..apply import rollback` в [tool_loop.py:682](ai_coder/agent/tool_loop.py#L682)).

Плюс запись в `_REQUIRED_ARGS` ([tool_loop.py:53](ai_coder/agent/tool_loop.py#L53)): `"spawn_subagent": ["name", "goal"]` — иначе `_has_missing_args` пропустит вызов без `goal`.

### 3.2 Как subagents попадают в контекст родителя

Зеркально D3 (`feedback_section`) — это снижает риск, потому что паттерн уже отлажен:

| Слой | Что добавить |
|---|---|
| `render_prompt` extra | `"subagents_section": ctx.subagents_section` |
| `_ToolLoopCtx` | `subagents_section: str`, `allowed_tools: frozenset[str]` |
| `run_tool_loop(...)` | `allowed_tools: list[str] \| None = None`, `spawn_depth: int = 0` |
| `prompts.yaml` | `{{subagents_section}}` в `agent_tool_json` |

⚠️ **Ловушка, которую уже поймали в D3:** `render_prompt` **бросает `KeyError`** на переменную, которой нет в `values` ([prompts.py:49-53](ai_coder/prompts.py#L49-L53)). Значит `subagents_section` обязана передаваться **всегда** (пустой строкой, если subagents нет). Тестовый `prompts_cfg` в `conftest.py` шаблон без `{{subagents_section}}` имеет — и это нормально (лишний ключ в `extra` игнорируется), но **`config/prompts.yaml` без ключа в extra сломает весь tool loop**.

Секция строится из специй:

```
## ДОСТУПНЫЕ SUBAGENTS (spawn_subagent)

- code-explorer — Ищет определения символов и вызовы. Read-only.
  tools: read_file, read_symbol, list_files, run_shell
- test-runner — Запускает pytest и возвращает только упавшие тесты.
  tools: run_shell
```

### 3.3 Как реализуется внутри

`spawn.py::run_spawn_subagent(ctx, args)`:

```python
spec = ctx.subagents_by_name.get(args["name"])     # dict[str, SubagentConfig]
if spec is None:
    return ToolResult(ok=False, error=f"unknown subagent: {name}. Доступные: {names}")

remaining = _remaining_budget(ctx)                  # §4
cap = min(x for x in (spec.max_cost_rub, ctx.cfg.agent.subagent_default_max_cost_rub,
                      remaining, ctx.spawn_budget_left) if x is not None)
if cap <= 0:
    return ToolResult(ok=False, error="бюджет исчерпан — spawn запрещён")

sub = run_tool_loop(
    goal=args["goal"],
    project_root=ctx.project_root,
    cfg=ctx.cfg,
    prompts_cfg=ctx.prompts_cfg,
    model=spec.model or ctx.cfg.api.model,
    depth=ctx.depth,
    max_iterations=spec.max_iterations,
    max_cost_rub=cap,
    journal=ctx.journal is not None,
    journal_subdir=<parent journal>/f"spawn-{spec.name}",   # §7: вложенный журнал
    dry_run=ctx.dry_run,          # ← иначе dry-run РЕАЛЬНО пишет файлы
    dry_read=ctx.dry_read,
    interactive=ctx.interactive,
    allow_blacklist=ctx.allow_blacklist,
    allowed_tools=spec.tools,     # §3.4
    spawn_depth=ctx.spawn_depth + 1,
    verify_commands=[] if spec.tools is read-only else ctx.verify_commands,
    usage_action_prefix=f"agent:spawn:{spec.name}",
)
ctx.total_cost_rub += sub.total_cost_rub      # ДО postcheck родителя
ctx.total_cost_cny += sub.total_cost_cny
ctx.total_cost_usd += sub.total_cost_usd
ctx.spawn_count += 1
ctx.spawn_cost_rub += sub.total_cost_rub
if sub.success and sub.applied_ops > 0:
    ctx.applied_ops += 1                       # §7: иначе parent finish(success) не пройдёт
return ToolResult(ok=sub.success, output=digest, error="" if sub.success else digest)
```

Изоляция контекста достигается **бесплатно**: `run_tool_loop` создаёт собственный `_ToolLoopCtx` (своя `history`, свой `backup_dir`, свои счётчики). Родитель получает **только** `digest`.

### 3.4 Allowlist — обязательна на исполнении, а не только в промпте

`parse_tool_action` отвергает только **неизвестные** имена; любой tool из `TOOL_REGISTRY` пройдёт, даже если его нет в промпте subagent'а. Поэтому:

1. `get_tool_specs(allowlist=None)` и `format_tools_for_prompt(allowlist=None)` — фильтрация для промпта.
2. **В `_tool_loop_one_iteration`, сразу после парсинга:** `if action.tool not in ctx.allowed_tools: → ToolResult(ok=False, error="tool X не разрешён этому subagent'у")`.

Effective allowlist в `run_tool_loop`:

```python
all_tools = list(TOOL_REGISTRY)
if allowed_tools is not None:
    effective = [t for t in allowed_tools if t in all_tools]  # ужесточаем
else:
    effective = all_tools
    if not cfg.agent.subagents or spawn_depth > 0:
        effective.remove("spawn_subagent")  # не рекламируем то, что нельзя
```

Так «нет subagents» → `spawn_subagent` **исчезает из промпта** (нулевой оверхед, нулевой соблазн), а subagent не может спавнить (§4).

### 3.5 Как возвращается результат

Краткая выжимка, не `step-N.md` и не история:

```python
def summarize_subagent_result(spec, res, cap_chars=1500) -> str:
    mark = "✅" if res.success else "❌"
    head = (
        f"[subagent {spec.name}] {mark} "
        f"{res.stopped_reason}, {res.iterations} итер, {res.total_cost_rub:.4f} RUB"
    )
    parts = [head, f"summary: {res.summary[:300]}"]
    if res.applied_ops:
        parts.append(f"изменений: {res.applied_ops}")
    if res.verify_errors:
        parts.append("verify: " + "; ".join(res.verify_errors[:3]))
    if res.journal_dir:
        parts.append(f"журнал: {res.journal_dir.name}")
    return "\n".join(parts)[:cap_chars]
```

Никакого `res.history` в родителя. `ToolResult.ok = res.success` — чтобы `_handle_finish`/parent видел провал, но **не падал** (fail-open, §4).

### 3.6 Стоимость

Суммируется в родительский `ctx.total_cost_*` **немедленно, до postcheck бюджета** ([tool_loop.py:637-644](ai_coder/agent/tool_loop.py#L637-L644)). Тогда родительский `max_cost_rub` учитывает spawn и корректно останавливается.

**Отдельная дыра (обязательно в issue D):** `append_usage` в `_accumulate_cost_and_usage` **хардкодит** `action=f"agent:tool{iteration}"` и `parent_action="agent"` ([tool_loop.py:250-263](ai_coder/agent/tool_loop.py#L250-L263)). То есть запросы subagent'а в `usage.jsonl` **неотличимы** от запросов родителя. Это ровно та же болезнь, что E39/D2 с `run_reverse_check`. Нужно прокинуть `usage_action_prefix` в `run_tool_loop` → `_accumulate_cost_and_usage`.

---

## 4. Ограничения

### Глубина: **depth = 1** (subagent НЕ вызывает subagent)

Рекомендую жёстко запретить в v1, тремя независимыми барьерами:
1. Pydantic-валидатор: `spawn_subagent` не может быть в `tools` subagent'а.
2. `format_tools_for_prompt`/effective allowlist: при `spawn_depth > 0` tool не попадает в промпт **и** отвергается на исполнении.
3. Явный guard: `if ctx.spawn_depth > 0: return ToolResult(ok=False, error="вложенный spawn запрещён")` — на случай, если 1-2 обойдут (например, tool прописан в `tools` руками при `model_construct`).

Почему не разрешать: нет бюджетной модели для рекурсии (дерево растёт экспоненциально), нет ограничения по времени (`cfg.agent.max_minutes` **не проверяется** в tool loop — только в `classic.py:524`, я это проверил), и отладка `_ToolLoopCtx`-дерева резко усложняется. Будущее: `agent.subagents_max_depth` (2), отдельная задача.

### Бюджет

Формула (переиспользует паттерн decomposer'а `max(0.0, max_cost_rub - dec_result.cost_rub)`):

```
cap = min(spec.max_cost_rub, agent.subagent_default_max_cost_rub,
          parent_remaining, agent.subagent_max_total_cost_rub - ctx.spawn_cost_rub)
parent_remaining = (ctx.max_cost_rub - ctx.total_cost_rub) if ctx.max_cost_rub else +inf
```

- `cap <= 0` → **fail-closed**: spawn отклоняется с ясной ошибкой. Здесь, в отличие от RC, fail-open опасен — это трата денег.
- Проверка бюджета внутри `run_tool_loop` — **поитерационная** (precheck [tool_loop.py:486](ai_coder/agent/tool_loop.py#L486) + postcheck). Значит возможен перерасход **до одной итерации** сверх `cap`. Это надо задокументировать, а не делать вид, что лимит жёсткий.
- Родитель узнаёт фактическую стоимость **после** возврата — суммируем сразу.

### Fail-open

| Что упало | Поведение |
|---|---|
| subagent `success=False` (`max_iterations`, `verify_failed`) | `ToolResult(ok=False, error=digest)` — родитель **видит** и решает сам (retry/другой subagent/finish) |
| исключение внутри `run_tool_loop` | `try/except Exception` → `ToolResult(ok=False, error="spawn crashed: ...")`, по образцу `execute_tool` ([tools.py:956](ai_coder/tools.py#L956)) |
| неизвестное `name` / пустой `goal` | `ok=False` + подсказка со списком доступных |
| бюджет исчерпан | `ok=False` (fail-closed) |

**Важно:** digest при провале обязан быть **явно** провальным (`❌`, `stopped_reason`, `verify_errors`). Иначе родитель сделает `finish(success=true)`, считая, что делегирование удалось — это тихая потеря корректности.

### Изоляция контекста

- Свой `_ToolLoopCtx` — автоматически, т.к. вызывается `run_tool_loop`.
- **Общий `project_root`.** Следствие: subagent пишет файлы напрямую, и его `backup_dir` **отдельный** от родительского. Если потом родительский `verify_failed` вызовет `rollback(ctx.backup_dir)`, правки subagent'а **не откатятся** ([tool_loop.py:681-691](ai_coder/agent/tool_loop.py#L681-L691)). В v1 — задокументировать; в v2 — мёржить `backup_manifest` ребёнка в родителя.
- `dry_run`/`dry_read`/`interactive`/`allow_blacklist` **обязаны** пробрасываться. Забыть `dry_run` = «симуляция», которая реально пишет на диск. Это надо закрыть тестом.
- `verify_commands`: для read-only subagent'ов передавать `[]`. Иначе разведчик, успешно завершившись, запустит `pytest` ([tool_loop.py:664](ai_coder/agent/tool_loop.py#L664)) — чистые потерянные минуты и деньги.

---

## 5. Промпт

### Описание в `agent_tool_json`

Два места. Первое — `{{subagents_section}}` после блока инструментов (генерируется из специй, §3.2). Второе — правила против злоупотреблений в блок `ПРАВИЛА`:

```
12. SUBAGENTS. spawn_subagent — ДОРОГО: это отдельный агент со своим
    контекстом и своим бюджетом. Вызывай ТОЛЬКО когда нужна широкая
    разведка или многошаговая работа, которую ты не сделаешь за 2-3
    своих шага. Для «прочитать один файл» используй read_file.
    Результат subagent'а — КРАТКАЯ выжимка. Если нужен точный код,
    читай файлы сам, а не проси пересказать.
    Не более одного spawn на подцель. Не более {{max_spawns}} за задачу.
```

### Пример вызова

```json
{"tool": "spawn_subagent",
 "args": {"name": "code-explorer",
          "goal": "найди все вызовы _collect_diff в ai_coder/ и верни список файл:строка"},
 "reason": "нужен полный список вызовов по всему проекту — сам сделаю за 10+ шагов"}
```

### Как ограничить злоупотребления

Структурно (надёжно) + инструкциями (мягко):

1. **Нет subagents → нет tool'а.** Не рекламируем `spawn_subagent`, если `cfg.agent.subagents` пуст. Это главный барьер: нечего злоупотреблять.
2. **`subagent_max_per_task: 3`** — жёсткий счётчик в ctx; после лимита `ToolResult(ok=False, "spawn-лимит исчерпан")`.
3. **`subagent_max_total_cost_rub`** — суммарный лимит (§4).
4. **Валидация `goal`**: `< 10` символов → отказ; `goal`, совпадающий с `ctx.goal` родителя (нормализованно) → отказ с подсказкой «это твоя собственная задача, сделай сам».
5. **Depth = 1** — subagent не может спавнить.
6. **Правила в промпте** (мягкий слой) — `max_spawns` подставляется числом.
7. В описании `ToolSpec` явно: «Дорого… не для одного чтения файла» — модель читает `description` в промпте.

---

## 6. Файлы, которые нужно менять

| # | Файл | Зачем |
|---|---|---|
| 1 | `ai_coder/config.py` | `SubagentConfig`, `AgentConfig.subagents` + 3 cap-поля, валидаторы (уникальность, tools ⊆ registry, цены, запрет вложенного spawn). Импорты `ConfigDict`, `model_validator`. **Fail-fast на старте.** |
| 2 | `ai_coder/tools.py` | `ToolSpec` + заглушка `_tool_spawn_unavailable`; `get_tool_specs(allowlist)` / `format_tools_for_prompt(allowlist)` — фильтрация. **Без этого subagent получит все 6 инструментов.** |
| 3 | `ai_coder/agent/spawn.py` **(новый)** | `build_subagents_section()`, `run_spawn_subagent()`, `summarize_subagent_result()`, `_remaining_budget()`. **Изолирует оркестрацию**, разрывает цикл импортов с `tool_loop`. |
| 4 | `ai_coder/agent/tool_loop.py` | Перехват spawn в `_tool_loop_one_iteration`; `_REQUIRED_ARGS`; поля `_ToolLoopCtx` (`subagents_section`, `allowed_tools`, `spawn_depth`, `spawn_count`, `spawn_cost_rub`, `subagents_by_name`); параметры `run_tool_loop` (`allowed_tools`, `spawn_depth`, `usage_action_prefix`); enforcement allowlist; `applied_ops` от spawn; атрибуция usage. **Точка сборки всего.** |
| 5 | `config/prompts.yaml` | `{{subagents_section}}` + правило 12 в `agent_tool_json`. **Ловушка `KeyError` — см. §3.2.** |
| 6 | `config/config.yaml` | Закомментированный пример `subagents` (по умолчанию секции нет — это ОК, как с `feedback_enabled`). |
| 7 | `docs/tools.md` | Раздел `## 6. spawn_subagent` (шаблон: аргументы/пример/возврат/опасный). Документация инструментов — часть контракта. |
| 8 | `docs/autonomy.md` | §9: пометить `spawn_subagent` как реализованный; убрать «Позже». |
| 9 | `docs/state.md`, `docs/progress.md` | По конвенции проекта (10.7x-записи) — что сделано и что осталось. |
| 10 | `ai_coder/cli.py` | **Опционально:** `--no-subagents`, `--subagent-max-per-task`. Если не нужно — не трогать (config-only). |
| 11 | `tests/test_spawn.py` **(новый)** | Валидация конфига, allowlist, depth, бюджет, dry_run-проброс, fail-open, «нет subagents → нет tool'а». |

---

## 7. Риски и митигации

| # | Риск | Митигация |
|---|---|---|
| 1 | **Взрыв стоимости** (spawn внутри spawn, много spawn) | depth=1 (3 барьера), `max_per_task`, `max_total_cost`, `cap` от `remaining`; сумма сразу в parent |
| 2 | **Тихий перерасход бюджета** (≤1 итерация сверх cap) | `cap` от `remaining`, а не свежий бюджет; задокументировать; тест на «родитель остановился после дорогого spawn» |
| 3 | **`dry_run` не проброшен** → симуляция реально пишет файлы | явный проброс + тест «в dry_run subagent не создаёт файлов» |
| 4 | **Allowlist только в промпте** → модель вызовет запрещённый tool | enforcement в `_tool_loop_one_iteration` (parse пропускает любой `TOOL_REGISTRY`-tool!) |
| 5 | **`render_prompt` KeyError** на `{{subagents_section}}` | всегда передавать (пустая строка) + интеграционный тест на **реальном** `prompts.yaml` (урок D3) |
| 6 | **Rollback родителя не откатывает правки subagent'а** (разные `backup_dir`) | v1: задокументировать; v2: мёржить манифесты |
| 7 | **Родитель делает `finish(success=true)` после провала subagent'а** | digest явно `❌` + `verify_errors`; `ToolResult.ok=res.success` |
| 8 | **Explorer-only родитель не может завершиться**: `_handle_finish` при `step_type="edit"` требует `applied_ops > 0` ([tool_loop.py:283-287](ai_coder/agent/tool_loop.py#L283-L287)) | считать успешный spawn с `applied_ops>0` в `ctx.applied_ops` (иначе `success=False` при нулевых правках) |
| 9 | **Subagent'у запустится `pytest`** (наследует `verify_commands`) | `verify_commands=[]` для read-only spec'ов |
| 10 | **usage.jsonl без атрибуции** (D2/E39 повтор) | `usage_action_prefix` → `action="agent:spawn:<name>:toolN"`, `parent_action="agent:spawn:<name>"` |
| 11 | **Плоский журнал**: `tool-loop-<ts>` ребёнка рядом с родителем | `journal_subdir=<parent>/spawn-<name>` (паттерн `subtask_subdir` из decomposer) |
| 12 | **`pricing_for` KeyError** на модели без цен | валидация `model in api.pricing` в `model_validator` |
| 13 | **Нет ограничения по времени**: `max_minutes` в tool loop не проверяется | только бюджетный guard; зафиксировать в docs; отдельная задача |
| 14 | **`interactive` subagent** повиснет на prompt'е без TTY | пробрасывать `interactive`, но в spawn при `ctx.interactive=True` предупредить/запретить (v1: запретить spawn при `interactive`) |
| 15 | Изменение `format_tools_for_prompt()` сигнатуры | добавить `allowlist=None` **с дефолтом** → существующие вызовы и тесты не ломаются |

---

## 8. Разбиение на issue (по уроку E39: 25–50 строк, одна забота, явные файлы/строки)

Урок E39 из `docs/experiments.md`: issue на **180 строк** → v4-pro «читает и не делает» (13 итераций, 19.93 RUB, ~70% задачи). Три issue по **25–50 строк** → ✅. Плюс E37: **явный вариант** лучше свободы (E37.1 — 53 строки свободы → провал; E37.2 — 20 строк явного → успех). Поэтому каждый issue ниже — с точными именами функций и готовыми сниппетами.

### Issue A — «Конфиг: SubagentConfig + валидация» (~45 строк, 1 файл)
- `SubagentConfig`, `AgentConfig.subagents=[]`, 3 cap-поля, валидаторы.
- **Acceptance:** 3 subagents парсятся; дубликат `name` → `ValueError`; неизвестный tool → `ValueError`; `spawn_subagent` в `tools` → `ValueError`; модель без цен → `ValueError`; `subagents` пусто → **491 passed** без изменений.
- **Без изменений поведения** — чистая схема.

### Issue B — «ToolSpec + allowlist + секция в промпте» (~50 строк, 3 файла)
- `spawn_subagent` в `TOOL_REGISTRY` + заглушка; `get_tool_specs(allowlist)` / `format_tools_for_prompt(allowlist)`; `_REQUIRED_ARGS`; `_ToolLoopCtx.subagents_section` + `allowed_tools`; `{{subagents_section}}` в `prompts.yaml`.
- **Acceptance:** `subagents=[]` → `spawn_subagent` **отсутствует** в промпте; с subagents → присутствует; **реальный `config/prompts.yaml` рендерится без `KeyError`**; enforcement allowlist отклоняет запрещённый tool.
- Ещё **не спавнит** — только реклама и фильтрация.

### Issue C — «Исполнение spawn: бюджет, depth, fail-open» (~60 строк, 2 файла)
- `spawn.py` (`run_spawn_subagent`, `summarize_subagent_result`, `_remaining_budget`); перехват в `_tool_loop_one_iteration`; сумма стоимости; `applied_ops`; depth-guard; cap; проброс `dry_run`/`verify_commands`.
- **Acceptance:** mock `run_tool_loop` → digest в родителе; стоимость в `ctx.total_cost_rub`; `spawn` при `cap<=0` → `ok=False`; depth>0 → отказ; в `dry_run` файлы не создаются; падение subagent'а не роняет родителя.

### Issue D — «Наблюдаемость + документация» (~40 строк, 4 файла)
- `usage_action_prefix` в `run_tool_loop` → `_accumulate_cost_and_usage`; вложенный `journal_subdir`; `docs/tools.md` §6; `docs/autonomy.md` §9; `docs/state.md`.
- **Acceptance:** запись в `usage.jsonl` с `action="agent:spawn:code-explorer:tool1"`; журнал ребёнка внутри родительского; docs обновлены.

**Порядок обязателен:** A → B → C → D. B без A не скомпилируется (нет `SubagentConfig`), C без B не найдёт `ctx.allowed_tools`, D без C нечего логировать. Каждый issue — отдельный прогон `ai-coder agent --issue ... --tool-loop --apply --model deepseek-v4-pro --max-cost-rub ~8`, как в E39.

**Оценка:** A ~1 прогон, B ~1–2, C ~2, D ~1 → **5–6 прогонов, ~40–60 RUB**, против исходной оценки `docs/autonomy.md` в «5–7 дней». Это существенно дешевле, потому что 80% механики (изоляция ctx, бюджет, журнал, `_resolve_subagent`) уже есть — `spawn_subagent` в основном *переиспользует* `run_tool_loop`, а не строит новый оркестратор.

---

## Итог: три вещи, которые определяют успех

1. **`spawn_subagent` нельзя выполнить через `execute_tool`** — сигнатура `(args, project_root)` не даёт доступа к `cfg`/`ctx`/бюджету, а `tools.py` не может импортировать `tool_loop.py`. Правильное место — перехват в `tool_loop.py` + новый `spawn.py` с ленивым импортом.
2. **Allowlist надо enforce'ить на исполнении**, а не только фильтровать промпт: `parse_tool_action` пропускает любой tool из `TOOL_REGISTRY`.
3. **Два неочевидных бага уже заложены в существующем коде:** `_handle_finish` требует `applied_ops > 0` (explorer-only родитель не завершится), а `append_usage` хардкодит `agent:toolN` (стоимость subagent'а неотличима от родительской — повтор истории E39/D2).

Код не менялся. Если нужно — сохраню это как `docs/dsh/D4/answer.md` (по конвенции `docs/dsh/README.md`) или разложу issue-файлы в `issues/2026-10-16/`.
