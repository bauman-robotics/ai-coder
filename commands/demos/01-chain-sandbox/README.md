# Демо 1 — `--chain` в песочнице

5 простых задач по очереди через `--chain`. Песочница — `/tmp/chain-test`.

## Запуск

    bash commands/demos/01-chain-sandbox/run.sh

`run.sh` вызовет `setup.sh` и запустит:

    ai-coder agent /tmp/chain-test \
        --chain issues/demos/01-chain-sandbox/ \
        --tool-loop --apply \
        --stop-on-fail \
        --max-cost-rub 3

## Задачи

| # | Issue | Что |
|---|---|---|
| 1 | `01-add-sub.md` | добавить `sub(a, b)` в `calc.py` |
| 2 | `02-add-mul.md` | добавить `mul(a, b)` в `calc.py` |
| 3 | `03-docstring-parse.md` | docstring к `parse` в `utils.py` |
| 4 | `04-fix-typo.md` | `recieve` → `receive` в `README.md` |
| 5 | `05-add-type-hints.md` | type hints в `calc.py` |

## Ожидаемый результат

- **5/5 ✅**, ~0.55 RUB.
- Изменения — в `/tmp/chain-test`.
