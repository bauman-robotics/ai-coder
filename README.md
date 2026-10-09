[![tests](https://github.com/bauman-robotics/ai-coder/actions/workflows/test.yml/badge.svg)](https://github.com/bauman-robotics/ai-coder/actions/workflows/test.yml)

# ai-coder

AI-ассистированный анализ git-проектов через DeepSeek API. Инструмент сканирует файлы проекта, отправляет их в LLM и возвращает отчёты или предложения изменений (с возможностью применения). Поддерживает кэширование, расчёт стоимости, авто-исправление синтаксических ошибок и агентный режим для многошаговых задач.

## Установка

1. Убедитесь, что установлен Python >= 3.10.
2. Клонируйте репозиторий:
   ```bash
   git clone <url>
   cd ai-coder
   ```
3. Установите зависимости:
   ```bash
   pip install -e .
   ```
   или:
   ```bash
   pip install -r requirements.txt
   ```
4. Задайте переменную окружения с API-ключом DeepSeek:
   ```bash
   export DEEPSEEK_API_KEY=ваш_ключ
   ```
5. Конфигурационные файлы `config/config.yaml` и `config/prompts.yaml` уже подготовлены. При необходимости измените модель, тарифы, сканирование и другие параметры.

## Инструменты tool loop

Полное описание 5 инструментов (`read_file`, `list_files`,
`write_file`, `edit_file`, `run_shell`) — в
[`docs/tools.md`](docs/tools.md).

**Как формулировать задачу агенту** (короткие промпты, без обратных
кавычек, 1-2 файла на задачу) — тоже в `docs/tools.md`,
раздел «Как формулировать задачу агенту».

**Декомпозиция задач** (`--decompose`) — для задач с 5+ файлов,
в `docs/tools.md`, раздел «Декомпозиция задач».

## Быстрый старт

```bash
# Показать список доступных действий
ai-coder actions

# Выполнить действие greet над текущим проектом
ai-coder run greet .

# Выполнить write-действие с просмотром плана (без применения)
ai-coder run write_readme .

# Применить предложенные изменения (с подтверждением)
ai-coder run write_readme . --apply

# Dry-run – оценка токенов и стоимости без обращения к API
ai-coder run suggest_improvements . --dry-run
```

## Использование (примеры)

### Действия (actions)

- `ai-coder actions` – показать список действий из конфига.
- `ai-coder actions --verbose` – показать оценку стоимости для текущего проекта.

### Выполнение действия (run)

Основной синтаксис:
```
ai-coder run <действие> [путь_к_проекту] [опции]
```

Примеры:
```bash
# Анализ проекта (read-режим)
ai-coder run greet . --depth normal

# Предложение улучшений с указанием глубины
ai-coder run suggest_improvements . --depth deep

# Генерация README с последующим применением
ai-coder run write_readme . --apply --yes

# Рефакторинг с другими параметрами модели
ai-coder run refactor . -m deepseek-v4-pro --temperature 0.2

# Исключение дополнительных файлов
ai-coder run inventory . --exclude "*.test.py" --exclude "docs/**"

# Отключить кэш отчётов
ai-coder run greet . --no-cache

# Принудительно обновить кэш (игнорировать старый)
ai-coder run write_readme . --refresh

# Авто-исправление ошибок после применения (до 5 попыток)
ai-coder run write_readme . --apply --max-fix-attempts 5

# Отключить авто-исправление
ai-coder run write_readme . --apply --no-auto-fix

# Пропустить проверку py_compile после применения
ai-coder run write_readme . --apply --no-verify
```

### Глобальные опции

- `--config`, `-c` – путь к конфигу (по умолчанию `config/config.yaml`).
- `--prompts`, `-p` – путь к промптам (по умолчанию `config/prompts.yaml`).
- `--model`, `-m` – переопределить модель.
- `--depth`, `-d` – глубина анализа: `shallow`, `normal`, `deep`.
- `--exclude`, `-x` – дополнительные gitignore-подобные паттерны.
- `--apply` – применить план изменений (для write-действий).
- `--yes`, `-y` – не спрашивать подтверждение при `--apply`.
- `--dry-run` – только оценка без запроса к API.
- `--no-cache` – не использовать кэш.
- `--refresh` – игнорировать кэш и выполнить запрос заново.
- `--no-auto-fix` – отключить авто-исправление ошибок.
- `--max-fix-attempts N` – количество попыток авто-исправления.

## Структура проекта

```
ai_coder/
├── __init__.py           # версия пакета
├── actions.py            # выполнение одиночного действия (run_action)
├── agent.py              # агентный режим (планировщик + исполнитель)
├── apply.py              # парсинг, валидация и применение планов правок
├── cache.py              # кэширование ответов LLM
├── cli.py                # CLI на основе Typer
├── config.py             # модели конфигурации (pydantic) и загрузка YAML
├── llm.py                # клиент для DeepSeek API (OpenAI SDK)
├── output.py             # генерация отчётов в Markdown
├── pricing.py            # расчёт стоимости, пиковые окна, курсы валют
├── prompts.py            # рендеринг промптов с подстановкой переменных
├── scanner.py            # сканирование проекта, фильтрация файлов, дерево
└── usage.py              # журнал использования (JSONL, summary)

config/
├── config.yaml           # основной конфиг: API, цены, сканирование, действия
└── prompts.yaml          # шаблоны промптов для действий и агента

tests/                    # тесты (pytest)
pyproject.toml            # метаданные проекта, зависимости, точка входа
requirements.txt          # runtime-зависимости
requirements-dev.txt      # dev-зависимости
.gitignore
```

## Лицензия

В проекте отсутствует явное указание лицензии (файл LICENSE не найден, поле license в pyproject.toml отсутствует).
