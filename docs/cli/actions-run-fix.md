## actions

Показать доступные действия из конфига.

| Флаг | Тип | Default | Описание |
|---|---|---|---|
| `--config, -c` | `<path>` | `config/config.yaml` | Путь к файлу конфигурации. |
| `--prompts, -p` | `<path>` | `config/prompts.yaml` | Путь к файлу промптов. |
| `--path` | `<path>` | `.` | Проект для оценки (только с `--verbose`). |
| `--model, -m` | `<str>` | — | Модель для оценки (с `--verbose`). |
| `--verbose, -v` | `flag` | — | Показать оценку стоимости для текущего проекта. |
| `--help` | `flag` | — | Показать справку. |

Пример:

```bash
ai-coder actions --verbose
```

## run

Выполнить действие над проектом.

**Аргументы**:
- `action` (`<str>`) — имя действия из config.yaml (обязательный).
- `path` (`<path>`) — путь к проекту (по умолчанию `.`).

| Флаг | Тип | Default | Описание |
|---|---|---|---|
| `--config, -c` | `<path>` | `config/config.yaml` | Путь к файлу конфигурации. |
| `--prompts, -p` | `<path>` | `config/prompts.yaml` | Путь к файлу промптов. |
| `--model, -m` | `<str>` | — | Модель (переопределить). |
| `--depth, -d` | `<str>` | `normal` | Глубина сканирования: shallow, normal, deep. |
| `--exclude, -x` | `<str>` | — | Дополнительные паттерны исключения. |
| `--apply` | `flag` | — | Применить план изменений (для write-действий). |
| `--yes, -y` | `flag` | — | Не спрашивать подтверждения при `--apply`. |
| `--no-verify` | `flag` | — | Не запускать py_compile после применения. |
| `--dry-run` | `flag` | — | Только оценка: файлы, токены, стоимость — без запроса к API. |
| `--no-cache` | `flag` | — | Не использовать кэш отчётов. |
| `--refresh` | `flag` | — | Игнорировать кэш и заново спросить API. |
| `--max-fix-attempts` | `<int>` | — | Сколько раз пробовать авто-исправление (0 = выключено). |
| `--no-auto-fix` | `flag` | — | Отключить авто-исправление ошибок. |
| `--max-tokens` | `<int>` | — | Переопределить max_total_tokens сканера (по умолчанию из config.yaml). |
| `--exclude-web` | `flag` | — | Исключить вёрстку (.html, .css, .js). |
| `--include-web` | `flag` | — | Включить вёрстку (переопределить авто-настройки). |
| `--verify-commands` | `<str>` | — | Verify-команды через ';' (например, 'pytest -q;ruff check .'). |
| `--only-path` | `<str>` | — | Сканировать только указанный путь (можно несколько раз). Например: --only-path ai_coder/ --only-path config/ |
| `--hint` | `<str>` | — | Доп. указание к промпту (добавляется в конец user). |
| `--help` | `flag` | — | Показать справку. |

Примеры:

```bash
# Чтение/анализ (read-действие)
ai-coder run analyze .

# Запись изменений с применением (write-действие)
ai-coder run modify . --apply
```

## fix

Автоматическое исправление: verify → fix → verify → ...

**Аргументы**:
- `path` (`<path>`) — путь к проекту (по умолчанию `.`).

| Флаг | Тип | Default | Описание |
|---|---|---|---|
| `--config, -c` | `<path>` | `config/config.yaml` | Путь к файлу конфигурации. |
| `--prompts, -p` | `<path>` | `config/prompts.yaml` | Путь к файлу промптов. |
| `--model, -m` | `<str>` | — | Модель для fix. |
| `--depth, -d` | `<str>` | `normal` | Глубина сканирования: shallow, normal, deep. |
| `--verify` | `<str>` | `из config.yaml` | Команды через ';' (например, 'pytest -q;ruff check .'). По умолчанию — из config.yaml. |
| `--max-attempts` | `<int>` | `3` | Максимум попыток fix. |
| `--allow-blacklist` | `flag` | `False` | Разрешить fix-агенту запись в blacklist. По умолчанию запрещено. |
| `--interactive, -i` | `flag` | — | Подтверждать каждый dangerous-инструмент. |
| `--journal, --no-journal` | `flag` | `journal` | — |
| `--exclude, -x` | `<str>` | — | — |
| `--max-cost-rub` | `<float>` | — | Остановка цикла fix при превышении стоимости (RUB). |
| `--help` | `flag` | — | Показать справку. |

Примеры:

```bash
# Запуск с пользовательской verify-командой
ai-coder fix . --verify "pytest -q"

# Ограничение числа попыток исправления
ai-coder fix . --max-attempts 5
```
