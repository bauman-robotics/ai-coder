Прочитал оба файла плюс точки вызова (`tool_loop.py`, `config.py`, `cli.py`, тесты). Ничего не менял.

---

## 1. Что сейчас делает `run_reverse_check`

[ai_coder/agent/reverse.py:92-177](ai_coder/agent/reverse.py#L92-L177)

**Сигнатура** (keyword-only): `goal: str`, `diff: str`, `project_root: Path`, `cfg: AppConfig`, `prompts_cfg: PromptsConfig`, `model: str | None = None`. Возвращает `ReverseCheckResult`.

**Diff НЕ собирает** — принимает готовой строкой. Сборщик отдельный: `_collect_diff(project_root)` ([reverse.py:22-89](ai_coder/agent/reverse.py#L22-L89)) — `git diff HEAD` + вручную добавленные untracked-файлы из `git status --porcelain`; жёсткий лимит `_MAX_DIFF_CHARS = 15000` с урезанием бюджета untracked-части. Внутри RC ещё одна обрезка до `cfg.agent.reverse_check_max_diff_chars` (дефолт 15000, [config.py:210](ai_coder/config.py#L210)) с пометкой «[... обрезано]».

**Промпт**: `prompts_cfg.get("agent_reverse_check")`, подстановка `{{goal}}`/`{{diff}}` вручную через `str.replace` в `system` и `user` ([reverse.py:111-115](ai_coder/agent/reverse.py#L111-L115)); шаблон — [config/prompts.yaml:720-754](config/prompts.yaml#L720-L754), контракт `{"ok", "problems", "suggestion"}`.

**Модель**: `model` → `cfg.agent.reverse_check_model` → `cfg.agent.decompose_model` → `cfg.api.model` ([reverse.py:117-122](ai_coder/agent/reverse.py#L117-L122)). Вызов `client.chat(..., temperature=0.0)`, **без** `json_mode`.

**Парсинг**: снимает ```json-обёртку, `json.loads`; `ok=bool(data.get("ok", True))`, `problems` приводится к списку, `suggestion`. Считает стоимость через `calculate_cost` + курсы ([reverse.py:135-147](ai_coder/agent/reverse.py#L135-L147)).

**Fail-open**: исключение LLM или ошибка парсинга → `ReverseCheckResult(ok=True, parse_error=...)` ([reverse.py:132-133](ai_coder/agent/reverse.py#L132-L133), [169-177](ai_coder/agent/reverse.py#L169-L177)). То есть RC сам по себе никогда не блокирует пайплайн.

**Текущая точка вызова (верхний уровень)**: `_tool_loop_finalize`, [tool_loop.py:693-739](ai_coder/agent/tool_loop.py#L693-L739) — после verify, **до** автокоммита (diff собирается на 696, пока дерево ещё грязное), под условием `ctx.reverse_check and ctx.success and not ctx.dry_run and ctx.stopped_reason == "completed"`. Стоимость плюсуется в `ctx.total_*` (725-727). `ok=False` → только `ctx.warnings` + печать, **без fail и без rollback** (728-737). Пустой diff → пропуск. Результат уходит в `ToolLoopResult.reverse_check_result` ([759](ai_coder/agent/tool_loop.py#L759)) и в отчёт loop'а (790-804).

---

## 2. Где в `run_agent_decompose` точка вызова

Хронология внутри `while` ([decomposer.py:234-441](ai_coder/agent/decomposer.py#L234-L441)):

1. `run_tool_loop(...)` — [253-271](ai_coder/agent/decomposer.py#L253-L271). Важно: **`auto_commit` не передаётся** (дефолт `False`, [tool_loop.py:830](ai_coder/agent/tool_loop.py#L830)) и **`reverse_check` не передаётся** → в decompose ни коммитов, ни RC сейчас нет.
2. Плюс стоимости в `dec_result` — 273-275.
3. Запись `subtask_results` — [278-289](ai_coder/agent/decomposer.py#L278-L289).
4. Retry через v4-pro при fail — [292-346](ai_coder/agent/decomposer.py#L292-L346); здесь `subtask_results[-1]` **перезаписывается целиком** (333-346).
5. Проверка `max_cost` — 348-352.
6. Обработка fail (replan / откат упавшей / `rollback_on_fail` / выход) — 354-439.

**Рекомендуемая точка вставки: сразу после блока retry, перед проверкой `max_cost`** — т.е. между [346](ai_coder/agent/decomposer.py#L346) и [348](ai_coder/agent/decomposer.py#L348), под условием `loop_result.success and not dry_run`.

Почему именно там:
- если поставить до retry — новая запись потеряется при wholesale-replace на 333-346;
- RC должен валидировать **финальную** попытку, а не flash-черновик;
- до проверки `max_cost` — чтобы RC-стоимость успела войти в бюджет;
- не внутри `run_tool_loop` — иначе получим вторую проверку и глобальный diff (см. п.5).

**Что доступно в этой точке**: `st` (`n`, `goal`, `files`, `type`), `loop_result` (`success`, `stopped_reason`, `total_cost_rub/cny/usd`, `backup_dir`, `journal_dir`, `verify_errors`, `warnings`, `history`, `applied_ops`, `commit_hash=None`), `subtask_subdir`, `dec_result`, `cfg`, `prompts_cfg`, `project_root`, `depth`, `dry_run`.

**Что передать**: `goal=st.goal` (ровно тот текст, что ушёл в loop, [decomposer.py:254](ai_coder/agent/decomposer.py#L254)), `diff=<изолированный diff подзадачи>` (п.3), `project_root`, `cfg`, `prompts_cfg`, `model` (осознанный выбор, п.5). Ничего в `reverse.py` менять не нужно — сигнатура уже подходит; вся обвязка — в `decomposer.py`.

---

## 3. Какие данные нужны для валидации подзадачи

**goal** — `st.goal`. Годится как есть; опционально можно добавить в промпт контекст «подзадача n/N» и её `files`, но текущий шаблон принимает только `goal`/`diff`, так что либо оставляем как есть, либо это отдельная правка промпта (не обязательна для MVP).

**diff — главная проблема.** `_collect_diff` собирает `git diff HEAD` по **всему рабочему дереву**. В decompose нет автокоммита, поэтому для подзадачи 3 туда попадут изменения подзадач 1 и 2 → валидатор будет судить не тот diff. Варианты изоляции:

- **A. Baseline-снапшот (рекомендую).** Перед `run_tool_loop` зафиксировать состояние дерева дерево-объектом (`git stash create` даёт commit-объект, не трогая worktree; при пустом дереве вернёт пусто — тогда baseline = `HEAD`). После loop'а: `git diff <baseline>` для tracked + untracked, появившиеся после baseline (сравнить множества из `git status --porcelain` до/после). Даёт честную дельту именно подзадачи.
- **B. Скоуп по backup-манифесту.** `loop_result.backup_dir/manifest.json` содержит `operations: [{type: "edit_file"|"create_file", path}]` ([tool_loop.py:154-170](ai_coder/agent/tool_loop.py#L154-L170), запись на [649-654](ai_coder/agent/tool_loop.py#L649-L654)). Дельта = `git diff HEAD -- <path>...` + синтезированный new-file diff по `create_file`. Дёшево и точно, но **не видит** изменения, сделанные `run_shell`/удаления/переименования, и файлы, не прошедшие через `_backup_file_for_tool_loop`.
- **C. MVP-заглушка.** Просто `_collect_diff(project_root)` (весь worktree) — быстро, но валидатор увидит чужие правки. Приемлемо только как временный шаг или если одновременно включить `auto_commit=True` в вызовах loop'а (тогда HEAD двигается и `_collect_diff` становится «диффом последнего коммита») — но это уже смена поведения decompose (появятся коммиты), отдельное решение.

**Прочие параметры**: `project_root` (нужен для `is_git_repo`, курсов и лога), `cfg` (лимит символов, модель, прайсинг), `prompts_cfg` (шаблон), `model`. Для diff'а нужен хелпер, которого сейчас нет — новый приватный сборщик в `decomposer.py` (или расширение `reverse.py`), т.к. `_collect_diff` умеет только «весь HEAD-дифф».

---

## 4. Как результат валидатора повлияет на логику

**`ok=True`**: ничего не делаем, кроме учёта стоимости; в словарь подзадачи пишем `reverse_ok=True`. Идём дальше (`i += 1`).

**`ok=False`**: нужна явная политика, иначе поведение разъедется с верхним RC (там это только warning). Предлагаю флаг/политику, дефолт — **warn**:

- **warn (дефолт)** — как в `run_tool_loop`: пишем проблемы в `subtask_results[-1]`, печатаем в консоль, продолжаем. Пайплайн не ломается, fail-open-семантика RC сохраняется.
- **fail (opt-in)** — выставляем `dec_result.parse_error = f"subtask {st.n} reverse-check failed"`, сохраняем отчёт ([`_save_decompose_report`](ai_coder/agent/decomposer.py#L468)) и `return`. Важно: существующая fail-ветка (354-439) сейчас **не сработает**, т.к. `loop_result.success=True`; выход нужно делать отдельным блоком, а не «переиспользовать» её.
- **rollback (opt-in)** — откат по `loop_result.backup_dir` тем же хелпером, что на [407-418](ai_coder/agent/decomposer.py#L407-L418), и либо стоп, либо **один retry с фидбеком**: повторить `run_tool_loop` с `goal = st.goal + "\n\nЗамечания ревьюера: ..."`. Это самая полезная опция, но и самая дорогая + рискованная (п.5).

**Стоимость**: `dec_result.cost_rub/cny/usd += reverse_result.cost_*` (по образцу 273-275). Это критично, потому что `remaining` для следующей подзадачи считается от `dec_result.cost_rub` ([248-250](ai_coder/agent/decomposer.py#L248-L250)), а `max_cost` проверяется по нему же (348).

**`subtask_results`**: добавить ключи `reverse_ok`, `reverse_problems`, `reverse_suggestion`, `reverse_cost_rub` — **в оба** литерала словаря (278-289 и 333-346), иначе при retry они потеряются. `success` предлагаю оставить «истиной tool loop'а» (её читают тесты: [test_agent.py:2155-2156](tests/test_agent.py#L2155-L2156), 2245-2247, 2871, 2908), а вердикт ревьюера держать отдельным ключом (например `verified`). Иначе `--rollback-on-fail`, который ходит по `prev.get("success") and prev.get("backup_dir")` ([425-431](ai_coder/agent/decomposer.py#L425-L431)), начнёт откатывать подзадачи, прошедшие loop, и сломает существующие тесты.

**report.md** ([`_save_decompose_report`, 468-506](ai_coder/agent/decomposer.py#L468-L506)):
- в таблицу (487-494) — колонка `RC` со значениями `✅ / ❌ / —`;
- новая секция `## Reverse-check` со списком проблем и `suggestion` по подзадачам с `ok=False`;
- строка с суммарной стоимостью RC (её сейчас негде показать, т.к. входит в общую `**Стоимость**`).

---

## 5. Риски и конфликты

**Задвоение с верхним RC — сейчас нет, появится при неаккуратной разводке.** В decompose `reverse_check` в loop не передаётся, так что верхнего RC там не существует. Но если кто-то одновременно (а) добавит `reverse_check=True` в вызовы [253-271](ai_coder/agent/decomposer.py#L253-L271)/[305-323](ai_coder/agent/decomposer.py#L305-L323) и (б) включит новый per-subtask RC — каждая подзадача проверится дважды, причём внутренний RC будет судить **глобальный** worktree-diff (с чужими правками). Решение: per-subtask RC живёт **только** в `decomposer.py`, внутренний loop всегда `reverse_check=False`; один флаг включает ровно одну проверку.

**Diff-изоляция — главный технический риск.** Последовательные подзадачи зависят друг от друга: подзадача 2 может опираться на незакоммиченные правки подзадачи 1. Валидатор, которому скормили только дельту подзадачи 2, может решить «половина задачи не сделана», хотя в дереве всё корректно. Baseline-снапшот (вариант A) эту проблему не создаёт — он честно показывает только собственные правки подзадачи, но и не даёт ревьюеру контекст предыдущих. Стоит заложить в промпт формулировку «diff — только изменения данной подзадачи» либо оставлять это как известное ограничение.

**Стоимость**: +1 LLM-вызов на каждую **успешную** подзадачу, т.е. до +N вызовов и +N×diff-токенов; при дефолтном fallback-моде `cfg.agent.decompose_model` это v4-pro на каждую подзадачу ([reverse.py:119-120](ai_coder/agent/reverse.py#L119-L120)) — заметно дороже самого loop'а на flash. Митигации: явный `model` (subtask-модель flash или `cfg.agent.reverse_check_model`), обязательный учёт в `remaining`/`max_cost`, и пропуск RC при `loop_result.applied_ops == 0` / пустом diff (аналог [tool_loop.py:738-739](ai_coder/agent/tool_loop.py#L738-L739)). Плюс линейный рост латентности — подзадачи последовательны, распараллелить нельзя.

**Rollback при `ok=False`**: откат подзадачи N может сломать подзадачи N+1… (они уже писались поверх состояния N), а backup-директория хранит копии по файлам, не «точку во времени» — возможен откат файла, который позже трогал другой subtask. Поэтому дефолт — warn без отката, rollback только явным флагом, и лучше в паре с retry-фидбеком, а не с немедленным стопом.

**Fail-open vs «настоящий fail»**: сейчас любая ошибка парсинга/сети даёт `ok=True`. Если сделать per-subtask RC блокирующим, флаки LLM будут валить хорошие подзадачи. Семантику `parse_error → ok=True` нужно сохранить, а «fail» включать только при валидном `ok=False`.

**dry_run**: обязательно пропускать (нет правок и не должно быть трат) — по образцу `not ctx.dry_run` в [tool_loop.py:695](ai_coder/agent/tool_loop.py#L695).

**Тесты.** При дефолте нового флага **False** существующий набор не ломается: тесты decompose ([test_agent.py:2060-2915](tests/test_agent.py#L2060-L2915)) патчат `ai_coder.agent.decomposer.run_tool_loop` и подают фейковые `ToolLoopResult`, RC при выключенном флаге не вызовется. Что реально придётся смотреть/править:
- если флаг включить по умолчанию — все эти тесты уйдут в реальный `LLMClient` (сеть/исключения), плюс `remaining`/`cost_rub` изменятся → упадут `test_run_agent_decompose_retry_cost_summation` (2297-2298, точное `0.44`) и любые проверки бюджетов (2353, max_cost);
- тесты на форму `subtask_results` (2154-2156, 2193-2194, 2244-2247, 2838-2839, 2871, 2907-2908) — ломаются только если менять смысл ключа `success`; при добавлении новых ключей и сохранении `success` — проходят;
- `report.md`-тесты проверяют лишь существование файла (2390-2391), так что новая колонка/секция безопасна; но если в `test_cli_agent.py` есть проверки содержимого именно decompose-отчёта — их надо дополнить;
- фикстура `prompts_cfg` уже содержит `agent_reverse_check` ([conftest.py:195](tests/conftest.py#L195)) — правок не требует;
- `--reverse-check` в CLI валидируется как «требует `--tool-loop`» ([cli.py:1443](ai_coder/cli.py#L1443)); новый `--decompose-reverse-check` должен проходить **мимо** этой проверки и прокидываться в `run_agent_decompose` ([cli.py:1707-1726](ai_coder/cli.py#L1707-L1726)), а также в GUI-вызовы ([gui/app.py:79,144](ai_coder/gui/app.py#L79)).

**Минимальный MVP-порядок** (если нужно уложиться в один заход): флаг `decompose_reverse_check: bool = False` в `AgentConfig` + параметр в `run_agent_decompose` (дефолт False) → baseline-снапшот и приватный сборщик diff подзадачи → вызов `run_reverse_check` после retry-блока → warn-политика + учёт стоимости + ключи в `subtask_results` → колонка/секция в `report.md`. Политики fail/rollback и retry-с-фидбеком — вторым шагом.
