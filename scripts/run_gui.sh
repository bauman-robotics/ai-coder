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

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
    echo "⚠  DEEPSEEK_API_KEY не задан — форма соберётся, но /run упадёт."
    echo "   export DEEPSEEK_API_KEY=sk-..."
    echo ""
fi

echo "═══════════════════════════════════════════════════════════"
echo "  ai-coder GUI"
echo "  http://127.0.0.1:$PORT/"
echo "  Ctrl+C — остановить"
echo "═══════════════════════════════════════════════════════════"
echo ""

exec uvicorn ai_coder.gui.app:app --host 127.0.0.1 --port "$PORT" $RELOAD
