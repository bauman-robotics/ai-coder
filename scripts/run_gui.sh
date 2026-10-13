#!/usr/bin/env bash
# Запуск GUI ai-coder (FastAPI + uvicorn).
#
# Использование:
#   bash scripts/run_gui.sh                 # порт 8000
#   bash scripts/run_gui.sh 8001            # порт 8001
#   bash scripts/run_gui.sh 8001 --reload   # с авто-перезагрузкой

set -eu

PORT="${1:-8000}"
RELOAD=""
if [ "${2:-}" = "--reload" ]; then
    RELOAD="--reload"
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
    echo "❌ .venv не найден."
    echo "   python3 -m venv .venv"
    echo "   source .venv/bin/activate"
    echo "   pip install -e '.[gui]'"
    exit 1
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -c "import fastapi, uvicorn, jinja2" 2>/dev/null || {
    echo "❌ GUI-зависимости не установлены."
    echo "   pip install -e '.[gui]'"
    exit 1
}

# Подхват API-ключа: сначала локальный .env, потом ~/.ai-coder.env
if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$PROJECT_ROOT/.env"
    set +a
    echo "✓ API-ключ из .env"
fi

if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ -f "$HOME/.ai-coder.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$HOME/.ai-coder.env"
    set +a
    echo "✓ API-ключ из ~/.ai-coder.env"
fi

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo "⚠  DEEPSEEK_API_KEY не задан — форма соберётся, но /run упадёт."
    echo "   Создайте .env в корне проекта:"
    echo "     echo 'DEEPSEEK_API_KEY=sk-...' > .env && chmod 600 .env"
    echo "   Или глобальный:"
    echo "     echo 'DEEPSEEK_API_KEY=sk-...' > ~/.ai-coder.env && chmod 600 ~/.ai-coder.env"
    echo ""
fi

echo "═══════════════════════════════════════════════════════════"
echo "  ai-coder GUI"
echo "  http://127.0.0.1:$PORT/"
echo "  Ctrl+C — остановить"
echo "═══════════════════════════════════════════════════════════"
echo ""

exec uvicorn ai_coder.gui.app:app --host 127.0.0.1 --port "$PORT" $RELOAD
