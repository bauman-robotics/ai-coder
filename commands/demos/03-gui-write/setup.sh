#!/usr/bin/env bash
# Подготовка песочницы /tmp/gui-test для демо 3.
set -e

SANDBOX=/tmp/gui-test

if [ -z "$SANDBOX" ]; then
    echo "ERROR: SANDBOX пуст — прерываю" >&2
    exit 1
fi
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX"
cd "$SANDBOX" || { echo "ERROR: cd $SANDBOX не удался" >&2; exit 1; }

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
