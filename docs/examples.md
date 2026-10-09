# Примеры использования ai-coder

Практические сценарии — команда, стоимость, что происходит. От
базовых до сложных. Теория — в [`scenarios.md`](scenarios.md),
здесь — конкретные примеры с командами.

**Соглашения:**
- `.` — путь к проекту (текущий).
- Стоимость — из реальных прогонов (DeepSeek flash, off-peak).
- `--max-cost-rub N` — страховка от превышения.

---

## 1. Базовые действия

### Обзор проекта

    ai-coder run greet . --depth normal

**Стоимость:** ~0.05 RUB. **Что:** LLM читает проект, описывает
стек, структуру, точки входа.

### Инвентарь

    ai-coder run inventory . --depth normal

**Стоимость:** ~0.05 RUB. **Что:** список классов, функций,
переменных с сигнатурами.

### Предложения по улучшению

    ai-coder run suggest_improvements . --depth deep

**Стоимость:** ~0.15 RUB. **Что:** приоритизированные
предложения (архитектура, читаемость, тесты).

### Объяснить файл

    ai-coder run explain . --only-path ai_coder/agent.py

**Стоимость:** ~0.05 RUB. **Что:** LLM объясняет назначение,
ключевые функции, связи.

### Сгенерировать README

    ai-coder run write_readme . --apply --yes

**Стоимость:** ~0.3 RUB. **Что:** LLM пишет README.md,
применяет с бэкапом, `py_compile` после.

---

### Уточнение промпта через `--hint`

    ai-coder run suggest_improvements . --depth deep \
        --hint "Фокус на безопасности и автономности агента."

**Что:** флаг `--hint "текст"` дописывает текст в конец `user`-промпта
(с пометкой `[УТОЧНЕНИЕ]`). Работает для всех `run`-действий.

**Когда:** нужен акцент — безопасность, автономность, стиль,
краткость, фокус на конкретном аспекте.

**Пример из практики:**

    ai-coder run suggest_improvements . --depth deep \
        --model deepseek-v4-pro \
        --only-path ai_coder/ --only-path config/ \
        --max-tokens 100000 \
        --hint "Проект движется к полной автономности агента..."

**Результат:** v4-pro получил уточнение — в ревью появился раздел
«Приоритизация для полной автономности». См.
[`docs/reviews/v4-pro-2026-10-09-full.md`](reviews/v4-pro-2026-10-09-full.md).

---

## 2. Tool loop — исправить баг

**Задача:** в песочнице `/tmp/agent-test` баг в `calc.py`:
`add(a, b)` возвращает `a - b` вместо `a + b`. Тест падает.

**Подготовка:**

    mkdir -p /tmp/agent-test && cd /tmp/agent-test
    cat > calc.py <<'PY'
    def add(a, b):
        return a - b
    def mul(a, b):
        return a * b
    PY
    cat > test_calc.py <<'PY'
    from calc import add, mul
    def test_add():
        assert add(2, 3) == 5
    def test_mul():
        assert mul(2, 3) == 6
    PY
    python -m pytest -q   # test_add падает

**Запуск:**

    cd ~/projects/15_ai_coder/ai-coder
    ai-coder agent "В файле calc.py функция add возвращает неверный \
    результат. Исправь баг так, чтобы тесты проходили." \
    /tmp/agent-test --tool-loop --apply --max-iterations 10 \
    --max-cost-rub 2

**Результат (живой прогон):**
- **3 итерации**, **0.10 RUB**.
- `read_file` → `edit_file` → `run_shell(pytest)` → `finish`.
- Агент сам запускает pytest до `finish`.
- Внешний `verify_commands` → `✅ Проверка пройдена`.

---

## 3. YAML — добавить действие

**Задача:** добавить действие `explain` в `config.yaml` и
`prompts.yaml` своего проекта.

**Запуск:**

    ai-coder agent "Добавь в config/config.yaml действие explain \
    (description, prompt, mode=read, exclude_web_assets=true). \
    Добавь в config/prompts.yaml промпт explain с system и user \
    (с плейсхолдерами depth, depth_hint, files). Только эти два \
    файла." . --tool-loop --apply --max-iterations 15 \
    --max-cost-rub 3

**Результат:**
- **4 итерации**, **0.31 RUB**.
- `read_file × 2` → `edit_file × 2` → `finish`.
- YAML-слабость (CHANGELOG 8.3) **закрыта** после 10.8.

---

## 4. Decompose — задача на несколько файлов

**Задача:** добавить тест, README-строку и раздел в docs — три
разных файла.

**Запуск:**

    ai-coder agent "Добавь в tests/test_config.py тест на explain \
    в enabled_actions. Добавь в README.md строку про explain. \
    Добавь в docs/scenarios.md раздел 12 про explain." . \
    --tool-loop --decompose --apply --max-iterations 10 \
    --max-cost-rub 5

**Результат:**
- **3 подзадачи** × 1 файл (v4-pro разбил точно).
- Все ✅, `verify_commands` после каждой.
- **1.22 RUB** — в **3.9×** дороже прямого tool loop на 2 файлах.

**Правило:** decompose — для **5+ файлов**, где tool loop
**зацикливается**. Для 2-3 файлов **прямой tool loop дешевле**.

---

## 5. Decompose + Replan — skip подзадачи

**Задача:** специально содержит fail — прочитать несуществующий
файл + создать `utils.py`.

**Запуск:**

    ai-coder agent "Открой файл nonexistent.py и покажи содержимое. \
    Создай utils.py с функцией double(x: int) -> int." \
    /tmp/agent-replan --tool-loop --decompose --decompose-replan \
    --apply --max-iterations 8 --max-cost-rub 5

**Результат:**
- Подзадача 1 → fail (файл не найден).
- Retry v4-pro → fail.
- **Replan (v4-pro)** → **skip**: «подзадача не влияет на остальные».
- Подзадача 2 → ✅.
- **0.79 RUB**, пропущено 1.

**Что проверяет:** механизм replan при провале.

---

## 6. Fix — авто-починка ошибок

**Задача:** после правок тесты/линтер падают — починить
автоматически.

**Запуск:**

    ai-coder fix . --verify "python -m pytest -q;ruff check ." \
    --max-attempts 3 --max-cost-rub 1

**Что делает:** цикл `verify → fix (tool loop) → verify`.
Останавливается при success или `--max-attempts`.

**Флаги:**
- `--verify "cmd1;cmd2"` — свои команды.
- `--max-attempts N` — сколько попыток (по умолчанию 3).
- `--max-cost-rub N` — бюджет цикла.
- `--interactive` — подтверждение dangerous.

---

## 7. Большой файл — правка конкретного участка

**Задача:** файл `agent.py` (2723 строки, ~90 KB). Нужно
добавить строку в docstring функции `run_agent_decompose`.

**Запуск:**

    ai-coder agent "В ai_coder/agent.py в docstring функции \
    run_agent_decompose добавь строку «При dry_run=true правки не \
    выполняются». Сохрани остальной текст без изменений." . \
    --tool-loop --apply --max-iterations 15 --max-cost-rub 1

**Результат:**
- **3 итерации**, **0.13 RUB**.
- Модель **сама** пошла через `grep -n` → `read_file(line_start,
  line_end)` → `edit_file` (фикс 10.14.14).
- Никаких sed, никаких перечитываний.

**До фикса** (правило 11 — ловушка):
- **12 итераций**, **0.65 RUB**, **0 правок** — модель
  зациклилась, не могла прочитать середину файла.

**Ускорение:** ×4, **дешевле:** ×5.

---

## 8. Сравнение подходов

| Задача | Прямой tool loop | Decompose | Комментарий |
|---|---:|---:|---|
| 1 файл, 1 правка | **0.10 RUB** (3 ит.) | 0.6 RUB | decompose **не нужен** |
| 2 файла, 2 правки | **0.31 RUB** (4 ит.) | 0.64 RUB | tool loop **дешевле** в 2× |
| 3 файла, 3 правки | ~0.4 RUB | **1.22 RUB** | tool loop **дешевле** в 3× |
| 5+ файлов | ❌ зацикливается (7.74 RUB) | **✅ 1.22 RUB** | decompose **оправдан** |

**Правило:** decompose — для **5+ файлов**, где tool loop **провал**.

---

## 9. Частые ошибки

### Backticks в промпте

**Плохо** (bash съест):

    ai-coder agent "Замени \`old\` на \`new\`" .

**Хорошо** (через файл):

    cat > /tmp/task.txt <<'TASK'
    Замени old на new в файле X
    TASK
    ai-coder agent "$(cat /tmp/task.txt)" .

### `--dry-run` для многошаговых задач

**Не работает:** edit_file не меняет виртуальный файл → модель
перечитывает → зацикливается.

**Правило:** `--dry-run` — **только** для 1-2 итераций или
`--preview-only`.

### Промпт > 15 строк

**Проблема:** модель теряет фокус.

**Правило:** промпт < 15 строк. Если больше — разбить на
несколько задач или использовать `--decompose`.

### Задача на 5+ файлов без decompose

**Проблема:** 10.8 E2E: 6 файлов, 5 правок — **зациклилась**
на 15 итераций, **0 правок**, 7.74 RUB.

**Решение:** `--decompose` → 1.22 RUB, ✅.

---

## Что дальше

- **Теория** — [`scenarios.md`](scenarios.md) (12 сценариев).
- **Инструменты** — [`tools.md`](tools.md) (5 инструментов + правила).
- **Эксперименты** — [`experiments.md`](experiments.md) (что пробовали).
- **Текущее состояние** — [`state.md`](state.md).
