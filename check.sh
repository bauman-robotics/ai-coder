#!/bin/bash
set -e
echo "→ ruff"
ruff check .
echo "→ mypy"
mypy ai_coder
echo "→ pytest"
python -m pytest tests/ -q
echo "✓ all checks passed"
