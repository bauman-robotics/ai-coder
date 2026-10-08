"""
Инструменты для tool loop агента.

Каждый инструмент — функция, которая принимает аргументы (dict) и
возвращает ToolResult. Инструменты безопасны: не выходят за пределы
project_root, не запускают shell, не делают сетевых вызовов.

Регистрация:
    from .tools import TOOL_REGISTRY
    spec = TOOL_REGISTRY["read_file"]

Использование:
    result = execute_tool("read_file", {"path": "src/main.py"}, project_root)
    if result.ok:
        print(result.output)
    else:
        print(result.error)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ToolSpec:
    """Описание инструмента для промпта модели."""

    name: str
    description: str
    args: dict[str, str]  # arg_name -> human-readable description
    returns: str  # описание результата
    dangerous: bool = False  # требует ли подтверждения


@dataclass
class ToolResult:
    """Результат выполнения инструмента."""

    ok: bool
    output: str = ""
    error: str = ""


# ---------- безопасность ----------


class ToolSecurityError(Exception):
    """Инструмент отказался работать из-за нарушения безопасности."""


def _safe_path(project_root: Path, rel_path: str) -> Path:
    """
    Приводит rel_path к абсолютному внутри project_root.

    Raises:
        ToolSecurityError: если путь выходит за пределы project_root
            или если это абсолютный путь.
    """
    if not rel_path:
        raise ToolSecurityError("empty path")
    p = Path(rel_path)
    if p.is_absolute():
        raise ToolSecurityError(f"absolute path not allowed: {rel_path}")
    # нормализуем: убираем '..', схлопываем './'
    abs_path = (project_root / p).resolve()
    project_resolved = project_root.resolve()
    try:
        abs_path.relative_to(project_resolved)
    except ValueError as e:
        raise ToolSecurityError(f"path escapes project root: {rel_path}") from e
    return abs_path


# ---------- инструменты ----------


def tool_read_file(args: dict[str, Any], project_root: Path) -> ToolResult:
    """read_file(path: str) → содержимое файла (до 50K символов)."""
    path = str(args.get("path", "")).strip()
    if not path:
        return ToolResult(ok=False, error="read_file: missing 'path'")

    try:
        abs_path = _safe_path(project_root, path)
    except ToolSecurityError as e:
        return ToolResult(ok=False, error=str(e))

    if not abs_path.exists():
        return ToolResult(ok=False, error=f"file not found: {path}")
    if not abs_path.is_file():
        return ToolResult(ok=False, error=f"not a file: {path}")

    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ToolResult(ok=False, error=f"read error: {e}")

    # ограничение — 50K символов
    if len(text) > 50_000:
        text = text[:50_000] + f"\n... [обрезано, всего {len(text)} символов]"

    return ToolResult(ok=True, output=text)


def tool_list_files(args: dict[str, Any], project_root: Path) -> ToolResult:
    """
    list_files(dir: str = ".", pattern: str = "") → список файлов.

    pattern — простой суффикс или fnmatch-паттерн (*.py, test_*.py).
    """
    dir_rel = str(args.get("dir", ".")).strip() or "."
    pattern = str(args.get("pattern", "")).strip()

    try:
        abs_dir = _safe_path(project_root, dir_rel)
    except ToolSecurityError as e:
        return ToolResult(ok=False, error=str(e))

    if not abs_dir.exists():
        return ToolResult(ok=False, error=f"dir not found: {dir_rel}")
    if not abs_dir.is_dir():
        return ToolResult(ok=False, error=f"not a dir: {dir_rel}")

    try:
        entries = sorted(abs_dir.iterdir(), key=lambda p: (p.is_file(), p.name))
    except OSError as e:
        return ToolResult(ok=False, error=f"list error: {e}")

    lines: list[str] = []
    for entry in entries:
        name = entry.name
        if entry.is_dir():
            lines.append(f"{name}/")
            continue
        if pattern and not _match_pattern(name, pattern):
            continue
        lines.append(name)

    if not lines:
        return ToolResult(ok=True, output="(empty)")

    return ToolResult(ok=True, output="\n".join(lines))


def _match_pattern(name: str, pattern: str) -> bool:
    """Простой fnmatch: '*.py', 'test_*.py'. Если pattern без '*', сравниваем как суффикс."""
    from fnmatch import fnmatch

    if "*" in pattern or "?" in pattern:
        return fnmatch(name, pattern)
    return pattern in name


def tool_write_file(args: dict[str, Any], project_root: Path) -> ToolResult:
    """write_file(path: str, content: str) → создать/перезаписать файл."""
    path = str(args.get("path", "")).strip()
    content = str(args.get("content", ""))

    if not path:
        return ToolResult(ok=False, error="write_file: missing 'path'")

    try:
        abs_path = _safe_path(project_root, path)
    except ToolSecurityError as e:
        return ToolResult(ok=False, error=str(e))

    # создаём родительские директории
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
    except OSError as e:
        return ToolResult(ok=False, error=f"write error: {e}")

    return ToolResult(ok=True, output=f"wrote {len(content)} chars to {path}")


def tool_edit_file(args: dict[str, Any], project_root: Path) -> ToolResult:
    """
    edit_file(path: str, old: str, new: str) → заменить old на new.

    Если old встречается 0 раз — ошибка.
    Если >1 раз — ошибка (нужен уникальный контекст).
    """
    path = str(args.get("path", "")).strip()
    old = str(args.get("old", ""))
    new = str(args.get("new", ""))

    if not path:
        return ToolResult(ok=False, error="edit_file: missing 'path'")
    if not old:
        return ToolResult(ok=False, error="edit_file: empty 'old'")

    try:
        abs_path = _safe_path(project_root, path)
    except ToolSecurityError as e:
        return ToolResult(ok=False, error=str(e))

    if not abs_path.exists():
        return ToolResult(ok=False, error=f"file not found: {path}")
    if not abs_path.is_file():
        return ToolResult(ok=False, error=f"not a file: {path}")

    try:
        text = abs_path.read_text(encoding="utf-8")
    except OSError as e:
        return ToolResult(ok=False, error=f"read error: {e}")

    count = text.count(old)
    if count == 0:
        return ToolResult(
            ok=False,
            error=f"edit_file: 'old' not found in {path}",
        )
    if count > 1:
        return ToolResult(
            ok=False,
            error=f"edit_file: 'old' found {count} times in {path} (must be unique)",
        )

    new_text = text.replace(old, new, 1)
    try:
        abs_path.write_text(new_text, encoding="utf-8")
    except OSError as e:
        return ToolResult(ok=False, error=f"write error: {e}")

    return ToolResult(ok=True, output=f"edited {path} (1 replacement)")


# ---------- реестр ----------


TOOL_REGISTRY: dict[str, tuple[ToolSpec, Callable[[dict[str, Any], Path], ToolResult]]] = {
    "read_file": (
        ToolSpec(
            name="read_file",
            description="Read the contents of a file. Use for inspection.",
            args={"path": "relative path to file (POSIX)"},
            returns="file contents as text (up to 50K chars)",
        ),
        tool_read_file,
    ),
    "list_files": (
        ToolSpec(
            name="list_files",
            description="List files in a directory. Use to discover structure.",
            args={
                "dir": "relative directory (default '.')",
                "pattern": "optional fnmatch pattern, e.g. '*.py'",
            },
            returns="one file per line; directories end with '/'",
        ),
        tool_list_files,
    ),
    "write_file": (
        ToolSpec(
            name="write_file",
            description="Create or overwrite a file with new content.",
            args={"path": "relative path", "content": "full new content"},
            returns="confirmation message",
            dangerous=True,
        ),
        tool_write_file,
    ),
    "edit_file": (
        ToolSpec(
            name="edit_file",
            description=(
                "Replace a unique substring 'old' with 'new' in a file. "
                "'old' must appear exactly once."
            ),
            args={"path": "relative path", "old": "substring to find", "new": "replacement"},
            returns="confirmation or error",
            dangerous=True,
        ),
        tool_edit_file,
    ),
}


def get_tool_specs() -> list[ToolSpec]:
    """Возвращает список ToolSpec для промпта."""
    return [spec for spec, _ in TOOL_REGISTRY.values()]


def execute_tool(
    name: str,
    args: dict[str, Any],
    project_root: Path,
) -> ToolResult:
    """
    Выполняет инструмент по имени.

    Returns:
        ToolResult. Если инструмент не найден или упал — ok=False.
    """
    if name not in TOOL_REGISTRY:
        return ToolResult(ok=False, error=f"unknown tool: {name}")
    _, fn = TOOL_REGISTRY[name]
    try:
        return fn(args, project_root)
    except Exception as e:
        return ToolResult(ok=False, error=f"tool crashed: {type(e).__name__}: {e}")


def format_tools_for_prompt() -> str:
    """
    Формирует текстовое описание инструментов для промпта.

    Пример вывода:
        read_file(path)
          Read the contents of a file.
          args: path — relative path to file (POSIX)
          returns: file contents as text
    """
    lines: list[str] = []
    for spec in get_tool_specs():
        args_str = ", ".join(f"{k}: {v}" for k, v in spec.args.items())
        lines.append(f"{spec.name}({args_str})")
        lines.append(f"  {spec.description}")
        lines.append(f"  returns: {spec.returns}")
        lines.append("")
    return "\n".join(lines)
