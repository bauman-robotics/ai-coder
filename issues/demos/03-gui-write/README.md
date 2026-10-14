# Демо 3 — write в песочнице для GUI

5 write-задач в песочнице `/tmp/gui-test`.

## Запуск (вручную из GUI)

1. Подготовь песочницу:

       bash commands/demos/03-gui-write/setup.sh

2. Запусти GUI:

       bash scripts/run_gui.sh 8000

3. Открой `http://127.0.0.1:8000/`.

4. Для каждой задачи:
   - **path:** `/tmp/gui-test`
   - **mode:** `tool-loop`
   - **check_mode:** `normal`
   - **флаг:** `--apply`

## Задачи

### 1. sub

    В файле calc.py добавь функцию sub(a, b), возвращающую a - b.

### 2. mul

    В файле calc.py добавь функцию mul(a, b), возвращающую a * b.

### 3. docstring

    В файле utils.py добавь docstring к функции parse: 'Привести строку к нижнему регистру и убрать пробелы.'

### 4. typo

    В файле README.md исправь опечатку: замени 'recieve' на 'receive'.

### 5. type hints

    В файле calc.py добавь type hints к функциям add, sub, mul (int, int) -> int.

## Повторный запуск

`setup.sh` пересоздаёт `/tmp/gui-test` — можно запускать снова.
