## agent

Агент строит план и выполняет его по цели.

**Аргументы**

- `goal` — цель агента (что нужно сделать). Можно заменить на `--issue`.
- `path` — путь к проекту. По умолчанию `.`.

### Общие флаги

| Флаг | Тип | Default | Описание |
|------|-----|---------|----------|
| `--config`, `-c` | `<path>` | `config/config.yaml` | Путь к конфигурационному файлу. |
| `--prompts`, `-p` | `<path>` | `config/prompts.yaml` | Путь к файлу промптов. |
| `--model`, `-m` | `<str>` | — | Модель (переопределить). |
| `--depth`, `-d` | `<str>` | `normal` | Глубина сканирования: `shallow`, `normal`, `deep`. |
| `--exclude`, `-x` | `<str>` | — | Дополнительные паттерны исключения. |
| `--max-tokens` | `<int>` | из `config.yaml` | Переопределить `max_total_tokens` сканера. |
| `--only-path` | `<str>` | — | Сканировать только указанный путь (можно несколько раз). |
| `--exclude-web` | flag | — | Исключить вёрстку (`.html`, `.css`, `.js`). |
| `--include-web` | flag | — | Включить вёрстку (по умолчанию агент видит всё). |

### Планирование

| Флаг | Тип | Default | Описание |
|------|-----|---------|----------|
| `--apply` | flag | — | Применять шаги (по умолчанию — только план и предложения). |
| `--verify` / `--no-verify` | flag | `verify` | Проверять `py_compile` после каждого шага. |
| `--verify-commands` | `<str>` | — | Verify-команды через `;`. Переопределяет `config.yaml`. |
| `--max-steps` | `<int>` | из конфига | Максимум шагов. |
| `--max-minutes` | `<int>` | из конфига | Максимум минут. |
| `--max-fix-attempts` | `<int>` | `0` | Попыток fix на шаг (0 = без fix). |
| `--journal` / `--no-journal` | flag | `journal` | Сохранять журнал агента в `.ai-out/<project>/agent-<ts>/`. |
| `--preview-only` | flag | — | Только план и оценка, без выполнения шагов. |
| `--no-auto-only-paths` | flag | — | Отключить авто-сужение контекста шагов 2+ из плана. |
| `--no-phase1` | flag | — | Отключить phase1 (metadata-планировщик) — видеть весь проект. |

### Tool loop

| Флаг | Тип | Default | Описание |
|------|-----|---------|----------|
| `--tool-loop` | flag | — | Использовать tool loop (модель сама вызывает инструменты). |
| `--max-iterations` | `<int>` | `20` | Лимит итераций tool loop. |
| `--dry-run` | flag | — | Tool loop: dangerous-инструменты не выполняются (только логи). |
| `--dry-read` | flag | — | Tool loop: read-only команды выполняются реально, `write_file`/`edit_file` блокируются. Несовместим с `--dry-run`. |
| `--interactive`, `-i` | flag | — | Подтверждать каждый шаг/инструмент вручную (`y/n/a/s/d`). |
| `--resume` | `<path>` | — | Продолжить tool loop с журнала (`tool-loop-<ts>/`). |
| `--allow-blacklist` | flag | — | Разрешить tool loop запись в blacklist (self-improvement). |
| `--reverse-check` | flag | — | После `finish(success)` проверить diff на соответствие goal (вторая LLM-проверка). Требует `--tool-loop`. |
| `--with-tests` | flag | — | После успешного tool loop: попросить агента написать pytest-тесты для изменённых файлов. Требует `--tool-loop`. |

### Бюджет и git

| Флаг | Тип | Default | Описание |
|------|-----|---------|----------|
| `--max-cost-rub` | `<float>` | — | Остановка при превышении стоимости (RUB). |
| `--commit` / `--no-commit` | flag | `no-commit` | Автокоммит после успешного `--apply` (`git add` + `git commit`). |
| `--require-clean` / `--no-require-clean` | flag | `require-clean` | Требовать чистое git-дерево перед `--apply`. |

### Декомпозиция

| Флаг | Тип | Default | Описание |
|------|-----|---------|----------|
| `--decompose` | flag | — | Декомпозиция: разбить задачу на подзадачи и выполнить через tool loop. |
| `--decompose-replan` / `--no-decompose-replan` | flag | `no-decompose-replan` | При провале подзадачи — перепланировать (skip/modify/stop). |
| `--decompose-rollback-on-fail` / `--no-decompose-rollback-on-fail` | flag | `no-decompose-rollback-on-fail` | При провале — откатить все успешные подзадачи. |
| `--decompose-max-cost-rub` | `<float>` | — | Остановка decompose при превышении стоимости (RUB). Если не задан — наследует `--max-cost-rub`. |
| `--plan` | flag | — | Показать план декомпозиции, спросить y/n/e, при y — выполнить. |

### Issues и chain

| Флаг | Тип | Default | Описание |
|------|-----|---------|----------|
| `--issue` | `<path>` | — | Markdown-файл с задачей (вместо goal). Первая строка `# task: ...` отбрасывается. Удобно для GitHub issues и roadmap-задач. |
| `--chain` | `<path>` | — | Каталог с `issues/*.md` — выполнить все по очереди (по имени). |
| `--continue-on-fail` / `--stop-on-fail` | flag | `stop-on-fail` | Chain: продолжать при провале задачи (по умолчанию — остановиться). |
| `--split-goals` | flag | — | Разбить фразу на N независимых `issues/*.md` (не выполняет). |
| `--auto-fix-issues` | flag | — | После tool loop: если verify упал — запустить цикл fix (verify → fix → verify). Требует `--tool-loop`. |

### Примеры

    ai-coder agent "добавь функцию sub(a, b) в calc.py" . --tool-loop --apply
    ai-coder agent --issue issues/1-add-sub.md . --tool-loop --apply
    ai-coder agent "исправь баг в calc.py" . --tool-loop --apply --reverse-check
    ai-coder agent . --chain issues/ --tool-loop --plan
