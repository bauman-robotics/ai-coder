#!/usr/bin/env bash
# Подготовка песочницы /tmp/chain-test для демо 1.
set -e

SANDBOX=/tmp/chain-test
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX"
cd "$SANDBOX"

cat > calc.py <<'PY'
def add(a, b):
    """Сложить два числа."""
    return a + b
PY

cat > utils.py <<'PY'
def parse(s):
    return s.strip().lower()
PY

cat > README.md <<'PY'
# My Project

This tool helps you recieve data.
PY

git init -q
git add .
git -c user.email=demo@demo -c user.name=demo commit -q -m "init"

echo "✅ Песочница готова: $SANDBOX"
echo "   Файлы: calc.py, utils.py, README.md"
