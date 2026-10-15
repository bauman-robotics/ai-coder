"""
Модуль для regex-поиска символов в исходниках C, C++, JS, TS, Go.

Предоставляет функции для определения языка по расширению файла и поиска
объявлений функций, классов и структур с определением границ их тел.
"""

from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".cc": "cpp",
    ".hh": "cpp",
    ".js": "js",
    ".jsx": "js",
    ".mjs": "js",
    ".ts": "ts",
    ".tsx": "ts",
    ".go": "go",
}


def detect_language(path: str) -> str | None:
    """Определяет язык по расширению файла."""
    suffix = Path(path).suffix.lower()
    return SUPPORTED_EXTENSIONS.get(suffix)


# Вспомогательные regex для разных языков
_RE_C_FUNC = re.compile(r"^\s*(?:[\w:<>*&\s]+?\s+)?(\w+)\s*\(")
_RE_C_STRUCT = re.compile(r"^\s*(struct|class)\s+(\w+)")

_RE_JS_FUNC = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(")
_RE_JS_CLASS = re.compile(r"^\s*(?:export\s+)?class\s+(\w+)")
_RE_JS_ARROW = re.compile(r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(")

_RE_GO_FUNC = re.compile(r"^\s*func\s+(\w+)\s*\(")
_RE_GO_METHOD = re.compile(r"^\s*func\s+\([^)]*\)\s+(\w+)\s*\(")
_RE_GO_TYPE = re.compile(r"^\s*type\s+(\w+)\s+struct")


def _parse_line(lang: str, line: str) -> tuple[str | None, str | None]:
    """Извлекает kind и name из строки; возвращает (kind, name) или (None, None)."""
    # C / C++
    if lang in ("c", "cpp"):
        # Только строки с нулевым отступом
        if line[:1] in (" ", "\t"):
            return None, None
        # Пропускаем typedef struct {
        if line.startswith("typedef struct {"):
            return None, None
        # struct/class
        m = _RE_C_STRUCT.match(line)
        if m:
            kind = "struct" if m.group(1) == "struct" else "class"
            return kind, m.group(2)
        # function (возможно с телом или прототип)
        m = _RE_C_FUNC.match(line)
        if m:
            name = m.group(1)
            # Дополнительно отфильтруем явные ключевые слова
            if name in {
                "if",
                "for",
                "while",
                "switch",
                "return",
                "do",
                "else",
                "case",
                "default",
                "typedef",
                "sizeof",
            }:
                return None, None
            return "func", name
        return None, None

    # JS / TS
    if lang in ("js", "ts"):
        # function
        m = _RE_JS_FUNC.match(line)
        if m:
            return "func", m.group(1)
        # class
        m = _RE_JS_CLASS.match(line)
        if m:
            return "class", m.group(1)
        # arrow
        m = _RE_JS_ARROW.match(line)
        if m:
            return "func", m.group(1)
        return None, None

    # Go
    if lang == "go":
        # method с receiver
        m = _RE_GO_METHOD.match(line)
        if m:
            return "func", m.group(1)
        # обычная функция
        m = _RE_GO_FUNC.match(line)
        if m:
            return "func", m.group(1)
        # type struct
        m = _RE_GO_TYPE.match(line)
        if m:
            return "struct", m.group(1)
        return None, None

    return None, None


def find_symbol(
    text: str,
    name: str,
    lang: str,
    kind: str | None = None,
) -> tuple[int, int, str] | None:
    """Ищет символ name в тексте; возвращает (start_line, end_line_exclusive, kind)."""
    if lang not in ("c", "cpp", "js", "ts", "go"):
        return None

    lines = text.splitlines()
    for i, line in enumerate(lines):
        # Для C/C++ пропускаем строки с отступом (уже проверяется в _parse_line)
        candidate_kind, candidate_name = _parse_line(lang, line)
        if candidate_name is None:
            continue
        if candidate_name != name:
            continue
        if kind is not None and candidate_kind != kind:
            continue

        # Нашли подходящую строку объявления.
        # Определяем границы тела.
        has_brace = "{" in line
        if has_brace:
            balance = line.count("{") - line.count("}")
            if balance == 0:
                # Однострочное тело (или скобки закрыты в этой же строке)
                end_line = i + 1
            else:
                # Ищем закрывающую скобку
                end_line = None
                for j in range(i + 1, len(lines)):
                    balance += lines[j].count("{") - lines[j].count("}")
                    if balance == 0:
                        end_line = j + 1
                        break
                if end_line is None:
                    # Не нашли закрытие, считаем до конца файла
                    end_line = len(lines)
        else:
            # Нет тела — только строка объявления
            end_line = i + 1

        return (i + 1, end_line, candidate_kind)

    return None
