#!/usr/bin/env bash
# Минимальный bundle для нового чата.
# Включает: git, проверки, state.md, TODO.md (открытые),
# последние 8 секций CHANGELOG, последние 4 experiments,
# обзор scenarios, шапку tools. Без ядра кода.

set -eu

WITH_INVENTORY=false
for arg in "$@"; do
    case "$arg" in
        --with-inventory) WITH_INVENTORY=true ;;
        *) echo "⚠ неизвестный аргумент: $arg" ;;
    esac
done

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$PROJECT_ROOT/next-chat"
BUNDLE="$OUT/bundle.md"

rm -rf "$OUT"
mkdir -p "$OUT"
cd "$PROJECT_ROOT"

# --- inventory (опционально) ---
INVENTORY_FILE=""
if [ "$WITH_INVENTORY" = true ]; then
    echo "Запускаю inventory (это вызов API, ~0.05 RUB)..."
    python -m ai_coder.cli run inventory . --depth normal --no-cache 2>&1 | tail -5
    INVENTORY_FILE=$(ls -t .ai-out/ai-coder/inventory-*.md 2>/dev/null | head -1)
    if [ -z "$INVENTORY_FILE" ]; then
        echo "⚠ inventory-отчёт не найден — продолжаю без него"
    else
        echo "✓ inventory: $INVENTORY_FILE"
    fi
fi

{
    echo "# ai-coder — контекст для нового чата"
    echo ""
    echo "**Дата:** $(date '+%Y-%m-%d %H:%M')"
    echo "**HEAD:** $(git rev-parse HEAD)"
    echo "**Ветка:** $(git rev-parse --abbrev-ref HEAD)"
    echo ""
    echo "## git log (последние 20)"
    echo ""
    echo '```'
    git log --oneline -20
    echo '```'
    echo ""
    echo "## git status"
    echo ""
    echo '```'
    git status --short
    echo '```'
    echo ""
    echo "## Проверки"
    echo ""
    echo '```'
    python -m pytest tests/ 2>&1 | tail -2
    ruff check . 2>&1 | tail -1
    ruff format --check . 2>&1 | tail -1
    mypy ai_coder 2>&1 | tail -1
    echo '```'
    echo ""

    echo "---"
    echo ""
    echo "# state.md"
    echo ""
    echo '```'
    cat docs/state.md
    echo '```'
    echo ""

    echo "# TODO.md — открытые пункты"
    echo ""
    echo "(только незакрытые `[ ]`)"
    echo ""
    echo '```'
    # Открытые пункты TODO: строки - [ ] с 3 строками контекста
    grep -n -A 3 '^- \[ \]' TODO.md | head -400
    echo '```'
    echo ""

    echo "# CHANGELOG — последние 8 секций"
    echo ""
    echo '```'
    awk '/^## \[/{c++} c<=8' CHANGELOG.md | head -250
    echo '```'
    echo ""

    echo "# experiments.md — последние 4 записи"
    echo ""
    echo '```'
    awk '/^## [0-9]{4}-/{c++} c>=1 && c<=4' docs/experiments.md | head -200
    echo '```'
    echo ""

    echo "# docs/scenarios.md — обзор + таблица"
    echo ""
    echo '```'
    head -30 docs/scenarios.md
    echo '```'
    echo ""

    echo "# docs/tools.md — шапка (первые 60 строк)"
    echo ""
    echo '```'
    head -60 docs/tools.md
    echo '```'
    echo ""

    if [ -n "$INVENTORY_FILE" ] && [ -f "$INVENTORY_FILE" ]; then
        echo "# inventory.md — инвентарь проекта (классы, функции, точки входа)"
        echo ""
        echo '```markdown'
        cat "$INVENTORY_FILE"
        echo '```'
        echo ""
        echo "---"
        echo ""
    fi

    echo "# Структурная карта проекта (grep: class + def)"
    echo ""
    echo "Все классы и функции в ai_coder/*.py с номерами строк."
    echo "Для чтения конкретного участка используйте read_file(path, line_start, line_end)."
    echo ""
    echo '```'
    for f in ai_coder/*.py; do
        matches=$( (grep -n "^class \|^def " "$f" 2>/dev/null || true) | head -60)
        if [ -n "$matches" ]; then
            echo "## $f"
            echo "$matches"
            echo ""
        fi
    done
    echo '```'
    echo ""

    echo "# pyproject.toml"
    echo ""
    echo '```toml'
    cat pyproject.toml
    echo '```'
    echo ""

    echo "# tests/conftest.py (фикстуры)"
    echo ""
    echo '```python'
    cat tests/conftest.py
    echo '```'
    echo ""

    if [ -f .github/workflows/test.yml ]; then
        echo "# .github/workflows/test.yml"
        echo ""
        echo '```yaml'
        cat .github/workflows/test.yml
        echo '```'
        echo ""
    fi

    echo "# Оглавление experiments.md (заголовки записей)"
    echo ""
    echo '```'
    grep '^## ' docs/experiments.md 2>/dev/null || true
    echo '```'
    echo ""

    echo "---"
    echo ""
    echo "# Изменённые файлы (за последние 5 коммитов)"
    echo ""
    echo '```'
    git diff --stat HEAD~5..HEAD
    echo '```'
    echo ""
} > "$BUNDLE"

# --- финальный вывод ---
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Bundle готов: $BUNDLE"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Файлы в $OUT:"
ls -la "$OUT"
echo ""
echo "Размер bundle:"
wc -c "$BUNDLE"
echo ""
echo "───────────────────────────────────────────────────────────"
echo "  Для нового чата"
echo "───────────────────────────────────────────────────────────"
echo ""
echo "1. Обновить prompt (HEAD, задачи):"
echo "     nano $OUT/prompt.md"
echo ""
echo "2. Скопировать prompt в буфер:"
echo "     cat $OUT/prompt.md | xclip -selection clipboard"
echo ""
echo "3. Скопировать bundle в буфер:"
echo "     cat $BUNDLE | xclip -selection clipboard"
echo ""
echo "4. Вставить в новый чат: prompt → bundle."
