## usage

Показать сводку расходов с фильтрами.

### Флаги

| Флаг | Описание |
|------|----------|
| `--config` | Путь к config.yaml (по умолчанию `config/config.yaml`). |
| `--since` | С какого дня (YYYY-MM-DD), в UTC. |
| `--until` | По какой день (YYYY-MM-DD), в UTC. |
| `--action` | Фильтр по действию. |
| `--project` | Фильтр по имени проекта. |
| `--model` | Фильтр по модели. |
| `--export` | csv\|json — выгрузить отфильтрованные записи. |
| `--out` | Файл для экспорта (по умолчанию stdout). |
| `--help` | Показать справку и выйти. |

### Примеры

**Фильтрация по действию (`--by-action`):**
```bash
python -m ai_coder.cli usage --action run
```

**Фильтрация по дням (`--by-day`):**
```bash
python -m ai_coder.cli usage --since 2026-10-01 --until 2026-10-31
```

## backups

Список бэкапов проекта.

### Флаги

| Флаг | Описание |
|------|----------|
| `--help` | Показать справку и выйти. |

### Пример

```bash
python -m ai_coder.cli backups
```

## rollback

Откатить изменения проекта из указанного бэкапа.

### Флаги

| Флаг | Описание |
|------|----------|
| `--yes` | Не спрашивать подтверждения. |
| `--help` | Показать справку и выйти. |

### Пример

```bash
python -m ai_coder.cli rollback .ai-out/project/backup-2026-10-10T00-00-00 --yes
```

## Алфавитный указатель флагов

| Флаг | Команды | Описание |
|------|---------|----------|
| `--action` | usage | Фильтр по действию. |
| `--allow-blacklist` | agent, fix | Разрешить запись в blacklist (self-improvement / fix-агенту). |
| `--apply` | run, agent | Применить план изменений / применять шаги. |
| `--auto-fix-issues` | agent | После tool loop: если verify упал — запустить цикл fix. Требует `--tool-loop`. |
| `--chain` | agent | Каталог с issues/*.md — выполнить все по очереди (по имени). |
| `--commit` | agent | Автокоммит после успешного `--apply`. |
| `--config` | actions, run, agent, fix, usage | Путь к config.yaml. |
| `--continue-on-fail` | agent | Chain: продолжать при провале задачи. |
| `--decompose` | agent | Декомпозиция: разбить задачу на подзадачи и выполнить через tool loop. |
| `--decompose-max-cost-rub` | agent | Остановка decompose при превышении стоимости (RUB). |
| `--decompose-replan` | agent | При провале подзадачи — перепланировать (skip/modify/stop). |
| `--decompose-rollback-on-fail` | agent | При провале — откатить все успешные подзадачи. |
| `--depth` | run, agent, fix | Уровень сканирования: shallow\|normal\|deep. |
| `--dry-read` | agent | Tool loop: read-only команды реально, write_file/edit_file блокируются. |
| `--dry-run` | run, agent | Только оценка без запроса к API / dangerous-инструменты не выполняются. |
| `--exclude` | run, agent, fix | Доп. паттерны исключения. |
| `--exclude-web` | run, agent | Исключить вёрстку (.html, .css, .js). |
| `--export` | usage | csv\|json — выгрузить отфильтрованные записи. |
| `--help` | ai-coder, actions, run, agent, fix, usage, backups, rollback | Показать справку и выйти. |
| `--hint` | run | Доп. указание к промпту (добавляется в конец user). |
| `--include-web` | run, agent | Включить вёрстку (переопределить авто-настройки / видеть всё). |
| `--interactive` | agent, fix | Подтверждать каждый шаг/инструмент вручную. |
| `--issue` | agent | Markdown-файл с задачей (вместо goal). |
| `--journal` | agent, fix | Сохранять журнал (по умолчанию включено). |
| `--max-attempts` | fix | Максимум попыток fix. |
| `--max-cost-rub` | agent, fix | Остановка при превышении стоимости (RUB). |
| `--max-fix-attempts` | run, agent | Сколько раз пробовать авто-исправление (0 = выключено). |
| `--max-iterations` | agent | Лимит итераций tool loop. |
| `--max-minutes` | agent | Максимум минут (по умолчанию из конфига). |
| `--max-steps` | agent | Максимум шагов (по умолчанию из конфига). |
| `--max-tokens` | run, agent | Переопределить max_total_tokens сканера. |
| `--model` | actions, run, agent, fix, usage | Модель для оценки/переопределения/фильтра. |
| `--no-auto-fix` | run | Отключить авто-исправление ошибок. |
| `--no-auto-only-paths` | agent | Отключить авто-сужение контекста шагов 2+ из плана. |
| `--no-cache` | run | Не использовать кэш отчётов. |
| `--no-commit` | agent | Не делать автокоммит после `--apply` (по умолчанию). |
| `--no-decompose-replan` | agent | Не перепланировать при провале подзадачи (по умолчанию). |
| `--no-decompose-rollback-on-fail` | agent | Не откатывать успешные подзадачи при провале (по умолчанию). |
| `--no-journal` | agent, fix | Не сохранять журнал. |
| `--no-phase1` | agent | Отключить phase1 (metadata-планировщик) — видеть весь проект. |
| `--no-require-clean` | agent | Не требовать чистое git-дерево перед `--apply`. |
| `--no-verify` | run, agent | Не запускать py_compile после применения/шага. |
| `--only-path` | run, agent | Сканировать только указанный путь (можно несколько раз). |
| `--out` | usage | Файл для экспорта (по умолчанию stdout). |
| `--path` | actions | Проект для оценки (только с `--verbose`). |
| `--plan` | agent | Показать план декомпозиции, спросить y/n/e, при y — выполнить. |
| `--preview-only` | agent | Только план и оценка, без выполнения шагов (экономит токены). |
| `--project` | usage | Фильтр по имени проекта. |
| `--prompts` | actions, run, agent, fix | Путь к config/prompts.yaml. |
| `--refresh` | run | Игнорировать кэш и заново спросить API. |
| `--require-clean` | agent | Требовать чистое git-дерево перед `--apply` (по умолчанию). |
| `--resume` | agent | Продолжить tool loop с журнала (tool-loop-<ts>/). |
| `--reverse-check` | agent | После finish(success) проверить diff на соответствие goal (вторая LLM-проверка). |
| `--since` | usage | С какого дня (YYYY-MM-DD), в UTC. |
| `--split-goals` | agent | Разбить фразу на N независимых issues/*.md (не выполняет). |
| `--stop-on-fail` | agent | Chain: останавливаться при провале задачи (по умолчанию). |
| `--tool-loop` | agent | Использовать tool loop (модель сама вызывает инструменты). |
| `--until` | usage | По какой день (YYYY-MM-DD), в UTC. |
| `--verbose` | actions | Показать оценку стоимости для текущего проекта. |
| `--verify` | agent, fix | В agent: проверять py_compile после шага. В fix: команды через ';' (например, `pytest -q;ruff check .`). |
| `--verify-commands` | run, agent | Verify-команды через ';'. |
| `--with-tests` | agent | После успешного tool loop попросить агента написать pytest-тесты. |
| `--yes` | run, rollback | Не спрашивать подтверждения. |

## Ссылки

- [README.md](../README.md)
- [docs/scenarios.md](../scenarios.md)
- [docs/examples.md](../examples.md)
- [docs/tools.md](../tools.md)
- [docs/state.md](../state.md)
