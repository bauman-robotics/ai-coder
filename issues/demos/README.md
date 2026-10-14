# Демо-наборы ai-coder

Самодостаточные примеры для демонстрации и повторного запуска.
Цели — здесь (`.md`). Команды и скрипты — в `commands/demos/`.

| # | Демо | Что | Безопасность |
|---|---|---|---|
| 1 | `01-chain-sandbox/` | 5 задач через `--chain` в песочнице `/tmp/chain-test` | только песочница |
| 2 | `02-gui-readonly/` | 5 read-only задач на самом `ai-coder` (для GUI) | ничего не меняется |
| 3 | `03-gui-write/` | 5 write-задач в песочнице `/tmp/gui-test` (для GUI) | только песочница |

## Быстрый старт

**Демо 1 — chain в песочнице:**

    bash commands/demos/01-chain-sandbox/run.sh

**Демо 2 — read-only, вручную из GUI:**

1. Запусти GUI: `bash scripts/run_gui.sh 8000`
2. Открой `http://127.0.0.1:8000/`
3. Скопируй задачу из `issues/demos/02-gui-readonly/README.md` в поле `goal`
4. Выбери `mode=tool-loop`, `check_mode=dry-read`
5. Нажми «Запустить»

**Демо 3 — write в песочнице, из GUI:**

1. Подготовь песочницу: `bash commands/demos/03-gui-write/setup.sh`
2. Скопируй задачу из `issues/demos/03-gui-write/README.md`
3. В GUI: `path=/tmp/gui-test`, `mode=tool-loop`, флаг `--apply`
4. Нажми «Запустить»

## Стоимость

| Демо | Стоимость |
|---|---|
| 01-chain-sandbox | ~0.55 RUB |
| 02-gui-readonly | ~0.05–0.15 RUB / задача |
| 03-gui-write | ~0.10–0.15 RUB / задача |
