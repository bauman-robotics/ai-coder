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

import json
import re
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
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


# ---------- run_shell: whitelist и защита ----------

# Разрешённые команды (первое слово в command).
# Всё, что не здесь, — отклоняется.
_SHELL_WHITELIST: frozenset[str] = frozenset(
    {
        "pytest",
        "ruff",
        "mypy",
        "git",
        "ls",
        "cat",
        "grep",
        "find",
        "head",
        "tail",
        "wc",
        "python",
        "python3",
    }
)

# Запрещённые подкоманды git (опасные) — на случай, если модель попробует.
_GIT_FORBIDDEN: frozenset[str] = frozenset(
    {
        "push",
        "reset",
        "clean",
        "rebase",
        "merge",
        "cherry-pick",
        "revert",
        "filter-branch",
    }
)

# Метасимволы shell, запрещённые в command.
# Разрешаем только «простые» команды без пайпов и перенаправлений.
_SHELL_METACHARS = re.compile(r"[;&|<>`$]|\$\(|\|\|")

# Лимит вывода (символов).
_SHELL_MAX_OUTPUT_CHARS = 10_000

# Таймаут (секунд).
_SHELL_DEFAULT_TIMEOUT = 30
_SHELL_MAX_TIMEOUT = 120

# Путь к логу команд (относительно project_root).
_SHELL_LOG_REL = ".ai-out/commands.log"


def _log_command(project_root: Path, command: str, result: ToolResult) -> None:
    """Дописывает команду и результат в .ai-out/commands.log."""
    log_path = project_root / _SHELL_LOG_REL
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        ts = datetime.now().isoformat(timespec="seconds")
        status = "OK" if result.ok else "FAIL"
        line = f"{ts}\t{status}\t{command}\n"
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass  # лог не критичен


def _validate_command(command: str) -> str | None:
    """
    Проверяет команду против whitelist и метасимволов.

    Returns:
        None, если команда разрешена.
        Сообщение об ошибке, если запрещена.
    """
    cmd = command.strip()
    if not cmd:
        return "empty command"

    # метасимволы
    if _SHELL_METACHARS.search(cmd):
        return "shell metacharacters (;, &, |, <, >, `, $) are not allowed; use a single command"

    # парсим на токены
    try:
        tokens = shlex.split(cmd)
    except ValueError as e:
        return f"cannot parse command: {e}"

    if not tokens:
        return "empty command after parsing"

    first = tokens[0]
    if first not in _SHELL_WHITELIST:
        return f"command not in whitelist: {first}"

    # проверки для конкретных команд
    if first in ("python", "python3"):
        # разрешаем только python -m pytest / -m ruff / -m mypy
        if len(tokens) < 3 or tokens[1] != "-m" or tokens[2] not in ("pytest", "ruff", "mypy"):
            return "python allowed only as 'python -m pytest|ruff|mypy'"

    if first == "git":
        if len(tokens) < 2:
            return "git requires a subcommand"
        sub = tokens[1]
        if sub in _GIT_FORBIDDEN:
            return f"git subcommand forbidden: {sub}"
        # разрешённые git-подкоманды
        allowed_git = {"status", "diff", "log", "show", "branch", "rev-parse", "ls-files"}
        if sub not in allowed_git:
            return f"git subcommand not in whitelist: {sub}"

    return None


def tool_run_shell(args: dict[str, Any], project_root: Path) -> ToolResult:
    """
    run_shell(command: str, timeout_sec: int = 30) → вывод команды.

    Команда должна быть в whitelist, без shell-метасимволов.
    Запускается в project_root, с timeout и лимитом вывода.
    """
    command = str(args.get("command", "")).strip()
    timeout_sec = int(args.get("timeout_sec", _SHELL_DEFAULT_TIMEOUT))
    if timeout_sec < 1:
        timeout_sec = 1
    if timeout_sec > _SHELL_MAX_TIMEOUT:
        timeout_sec = _SHELL_MAX_TIMEOUT

    err = _validate_command(command)
    if err:
        result = ToolResult(ok=False, error=f"run_shell rejected: {err}")
        _log_command(project_root, command, result)
        return result

    try:
        tokens = shlex.split(command)
    except ValueError as e:
        result = ToolResult(ok=False, error=f"cannot parse command: {e}")
        _log_command(project_root, command, result)
        return result

    try:
        completed = subprocess.run(
            tokens,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result = ToolResult(
            ok=False,
            error=f"timeout after {timeout_sec}s",
        )
        _log_command(project_root, command, result)
        return result
    except OSError as e:
        result = ToolResult(ok=False, error=f"exec error: {e}")
        _log_command(project_root, command, result)
        return result

    # объединяем stdout + stderr
    parts: list[str] = []
    if completed.stdout:
        parts.append(completed.stdout)
    if completed.stderr:
        parts.append("--- stderr ---\n" + completed.stderr)
    output = "\n".join(parts).strip()

    if len(output) > _SHELL_MAX_OUTPUT_CHARS:
        output = (
            output[:_SHELL_MAX_OUTPUT_CHARS] + f"\n... [обрезано, всего {len(output)} символов]"
        )

    ok = completed.returncode == 0
    result = ToolResult(
        ok=ok,
        output=output or "(no output)",
        error="" if ok else f"exit code: {completed.returncode}",
    )
    _log_command(project_root, command, result)
    return result


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
    "run_shell": (
        ToolSpec(
            name="run_shell",
            description=(
                "Run a whitelisted shell command (pytest, ruff, mypy, git status/diff/log, "
                "ls, cat, grep, find). No shell metacharacters (;, &, |, <, >, $)."
            ),
            args={
                "command": "single command, e.g. 'pytest -q' or 'git status'",
                "timeout_sec": "optional timeout, default 30, max 120",
            },
            returns="stdout+stderr (up to 10K chars); ok=False if exit code != 0",
            dangerous=True,
        ),
        tool_run_shell,
    ),
}


def get_tool_specs() -> list[ToolSpec]:
    """Возвращает список ToolSpec для промпта."""
    return [spec for spec, _ in TOOL_REGISTRY.values()]


def execute_tool(
    name: str,
    args: dict[str, Any],
    project_root: Path,
    *,
    dry_run: bool = False,
) -> ToolResult:
    """
    Выполняет инструмент по имени.

    Args:
        name: имя инструмента.
        args: аргументы.
        project_root: корень проекта.
        dry_run: если True — dangerous-инструменты НЕ выполняются,
                 возвращают "(dry-run) would have ...".

    Returns:
        ToolResult. Если инструмент не найден или упал — ok=False.
    """
    if name not in TOOL_REGISTRY:
        return ToolResult(ok=False, error=f"unknown tool: {name}")

    spec, fn = TOOL_REGISTRY[name]

    # dry-run: пропускаем dangerous, но сообщаем, что бы сделали
    if dry_run and spec.dangerous:
        args_repr = ", ".join(f"{k}={v!r}" for k, v in args.items())
        preview = f"(dry-run) would have called {name}({args_repr})"
        return ToolResult(ok=True, output=preview)

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


# ---------- парсинг ответа модели (tool loop) ----------


@dataclass
class ToolAction:
    """
    Разобранное действие модели в tool loop.

    Ровно одно из двух:
      - вызов инструмента: tool != "", finish == False
      - завершение:        finish == True, tool == ""

    Если parse_error не None — действие невалидно, ничего выполнять нельзя.
    """

    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    finish: bool = False
    summary: str = ""
    success: bool = True
    parse_error: str | None = None
    raw_json: str = ""


def _strip_json_wrapper(text: str) -> str:
    """Снимает markdown-обёртку ```json ... ```."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _parse_first_json_object(text: str) -> tuple[dict | None, str | None]:
    """
    Парсит ПЕРВЫЙ JSON-объект из текста, игнорируя хвост.

    Полезно, когда модель возвращает два JSON подряд:
      {"tool": "..."}
      {"finish": true}
    — берём первый.

    Returns:
        (data, error). data=None при ошибке.
    """
    text = text.strip()
    if not text.startswith("{"):
        start = text.find("{")
        if start == -1:
            return None, "no '{' found"
        text = text[start:]

    decoder = json.JSONDecoder()
    try:
        data, _ = decoder.raw_decode(text)
    except json.JSONDecodeError as e:
        return None, f"JSON parse error: {e}"

    if not isinstance(data, dict):
        return None, f"expected dict, got {type(data).__name__}"
    return data, None


def parse_tool_action(content: str) -> ToolAction:
    """
    Парсит ответ модели на tool loop.

    Ожидает JSON одного из видов:
      {"tool": "<name>", "args": {...}, "reason": "..."}
      {"finish": true, "summary": "...", "success": true|false}

    Возвращает ToolAction. При ошибке — parse_error != None, tool="" и finish=False.
    """
    action = ToolAction(raw_json=content)
    text = _strip_json_wrapper(content)

    data, err = _parse_first_json_object(text)
    if err is not None:
        action.parse_error = f"tool JSON {err}"
        return action
    if data is None:
        action.parse_error = "tool JSON empty data"
        return action

    # --- finish ---
    if data.get("finish") is True:
        action.finish = True
        action.summary = str(data.get("summary", "")).strip()
        action.success = bool(data.get("success", True))
        return action

    # --- tool ---
    tool = data.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        action.parse_error = "missing or invalid 'tool' field (and no 'finish' flag)"
        return action
    tool = tool.strip()

    if tool not in TOOL_REGISTRY:
        action.parse_error = f"unknown tool: {tool}"
        return action

    args = data.get("args", {})
    if not isinstance(args, dict):
        action.parse_error = f"'args' must be a dict, got {type(args).__name__}"
        return action

    action.tool = tool
    action.args = args
    action.reason = str(data.get("reason", "")).strip()
    return action


def format_tool_history(history: list[tuple[ToolAction, ToolResult]], max_items: int = 10) -> str:
    """
    Формирует текстовый лог предыдущих действий для промпта.

    Берёт последние max_items. Каждый пункт:
        #1. read_file(path='a.py') → ok, 12 chars
        #2. edit_file(path='a.py') → ok, 'edited a.py'
        #3. run_shell('pytest -q') → FAIL (exit code: 1)
          first 200 chars of output/error

    Если истории нет — возвращает "(нет)".
    """
    if not history:
        return "(нет)"

    items = history[-max_items:]
    lines: list[str] = []
    for i, (action, result) in enumerate(items, 1):
        if action.finish:
            desc = f"finish(success={action.success})"
        else:
            args_short = ", ".join(f"{k}={v!r}" for k, v in action.args.items())
            desc = f"{action.tool}({args_short})"

        status = "ok" if result.ok else "FAIL"
        snippet = (result.output or result.error or "")[:200].replace("\n", " ")
        lines.append(f"#{i}. {desc} → {status}")
        if snippet:
            lines.append(f"     {snippet}")
    return "\n".join(lines)
