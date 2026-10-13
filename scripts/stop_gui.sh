#!/usr/bin/env bash
# Остановка GUI ai-coder (uvicorn).
#
# Использование:
#   bash scripts/stop_gui.sh          # порт по умолчанию 8000
#   bash scripts/stop_gui.sh 8001     # конкретный порт
#   bash scripts/stop_gui.sh all      # убить все uvicorn ai_coder.gui

set -eu

TARGET="${1:-8000}"

if [ "$TARGET" = "all" ]; then
    echo "Останавливаю все процессы ai_coder.gui..."
    pkill -f "uvicorn ai_coder.gui" 2>/dev/null || true
    sleep 1
    if ps aux | grep -v grep | grep -q "uvicorn ai_coder.gui"; then
        echo "  остались процессы — SIGKILL"
        pkill -9 -f "uvicorn ai_coder.gui" 2>/dev/null || true
        sleep 1
    fi
    if ps aux | grep -v grep | grep -q "uvicorn ai_coder.gui"; then
        echo "❌ не удалось убить все процессы"
        ps aux | grep -v grep | grep "uvicorn ai_coder.gui"
        exit 1
    fi
    echo "✅ все процессы ai_coder.gui остановлены"
    exit 0
fi

PORT="$TARGET"

if ! ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    echo "✅ порт $PORT свободен — нечего останавливать"
    exit 0
fi

echo "Останавливаю процесс на порту $PORT..."
if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
else
    PIDS=$(lsof -ti:"$PORT" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        # shellcheck disable=SC2086
        kill $PIDS 2>/dev/null || true
    fi
fi

sleep 1

if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    echo "  всё ещё занят — SIGKILL"
    if command -v fuser >/dev/null 2>&1; then
        fuser -k -9 "${PORT}/tcp" >/dev/null 2>&1 || true
    else
        lsof -ti:"$PORT" 2>/dev/null | xargs -r kill -9
    fi
    sleep 1
fi

if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
    echo "❌ порт $PORT всё ещё занят"
    exit 1
fi

echo "✅ порт $PORT свободен"
