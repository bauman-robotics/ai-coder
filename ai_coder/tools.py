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

from .scanner import mask_secrets


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
    dry_run: bool = False  # NEW: результат симуляции (dry-run)


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

# Чёрный список флагов для простых команд.
# Токен сравнивается целиком ИЛИ по префиксу до '=' (для --flag=value).
# Whitelist по имени команды — уже есть; это дополнительный слой
# (защита от опасных флагов внутри разрешённых команд).
_SHELL_FORBIDDEN_FLAGS: dict[str, frozenset[str]] = {
    "find": frozenset(
        {
            "-delete",
            "-exec",
            "-execdir",
            "-ok",
            "-okdir",
            "-fdelete",  # BSD
            "-fls",  # BSD: запись списка в файл
        }
    ),
    "tail": frozenset({"-f", "--follow", "-F"}),  # бесконечный хвост
    # ls, cat, grep, head, wc, pytest, ruff, mypy — нечего запрещать.
    # python / python3 — проверяются отдельно (только -m pytest|ruff|mypy).
}

# Чёрный список флагов для git-подкоманд.
# Ключ — подкоманда (status/diff/log/show/branch/rev-parse/ls-files).
_GIT_FORBIDDEN_FLAGS: dict[str, frozenset[str]] = {
    "branch": frozenset(
        {
            "-D",
            "-d",
            "-m",
            "-M",
            "--delete",
            "--move",
            "--set-upstream-to",
            "-u",
        }
    ),
    "log": frozenset({"--exec", "--ext-diff", "--textconv"}),
    "diff": frozenset({"--ext-diff", "--textconv", "--exec"}),
    "show": frozenset({"--ext-diff", "--textconv", "--exec"}),
    # status, rev-parse, ls-files — без запретов.
}


def _flag_is_forbidden(tokens: list[str], forbidden: frozenset[str]) -> str | None:
    """
    Проверяет токены на запрещённые флаги.
    Сравнивает как целый токен, так и префикс до '=' (--flag=value).
    Возвращает найденный флаг или None.
    """
    for tok in tokens:
        base = tok.split("=", 1)[0]
        if base in forbidden:
            return base
    return None


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

    # --- дополнительно: чёрный список флагов для простых команд ---
    forbidden = _SHELL_FORBIDDEN_FLAGS.get(first)
    if forbidden:
        bad = _flag_is_forbidden(tokens[1:], forbidden)
        if bad is not None:
            return f"flag forbidden for {first}: {bad}"

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

        # --- дополнительно: чёрный список флагов для git-подкоманды ---
        git_forbidden = _GIT_FORBIDDEN_FLAGS.get(sub)
        if git_forbidden:
            bad = _flag_is_forbidden(tokens[2:], git_forbidden)
            if bad is not None:
                return f"flag forbidden for git {sub}: {bad}"

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

    # content-фильтр секретов: маскируем ДО обрезки,
    # чтобы warning был виден даже если вывод огромный
    output, secret_names = mask_secrets(output)
    if secret_names:
        warning = f"⚠️ [masked {len(secret_names)} secret(s): {', '.join(secret_names)}]"
        output = warning + "\n" + output

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
    """read_file(path, line_start?, line_end?) → содержимое файла или участок.

    Без line_start/line_end — весь файл (до 50K символов).
    С line_start/line_end — только строки [line_start, line_end] включительно
    (нумерация с 1). Нужно для больших файлов: не обрезается, читаем точно
    нужный участок.
    """
    path = str(args.get("path", "")).strip()
    if not path:
        return ToolResult(ok=False, error="read_file: missing 'path'")

    line_start = args.get("line_start")
    line_end = args.get("line_end")

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

    # --- режим участка: line_start / line_end ---
    if line_start is not None or line_end is not None:
        try:
            start = int(line_start) if line_start is not None else 1
            end = int(line_end) if line_end is not None else 10**9
        except (TypeError, ValueError):
            return ToolResult(
                ok=False,
                error="read_file: line_start/line_end must be integers",
            )
        if start < 1:
            start = 1
        lines = text.splitlines()
        total = len(lines)
        if end > total:
            end = total
        if start > total:
            return ToolResult(
                ok=False,
                error=f"read_file: line_start={start} > total lines ({total})",
            )
        if start > end:
            return ToolResult(
                ok=False,
                error=f"read_file: line_start={start} > line_end={end}",
            )
        selected = "\n".join(lines[start - 1 : end])
        header = f"# {path} (lines {start}-{end} of {total})\n"
        selected, secret_names = mask_secrets(selected)
        if secret_names:
            warning = f"⚠️ [masked {len(secret_names)} secret(s): {', '.join(secret_names)}]\n"
            header = warning + header
        return ToolResult(ok=True, output=header + selected)

    # --- режим файла целиком (как было) ---
    if len(text) > 50_000:
        text = text[:50_000] + f"\n... [обрезано, всего {len(text)} символов]"

    text, secret_names = mask_secrets(text)
    if secret_names:
        warning = f"⚠️ [masked {len(secret_names)} secret(s): {', '.join(secret_names)}]\n"
        text = warning + text

    return ToolResult(ok=True, output=text)


# ---------- read_symbol (Python-only) ----------

_SYMBOL_DEF_RE = re.compile(r"^([ \t]*)(async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_SYMBOL_CLASS_RE = re.compile(r"^([ \t]*)class\s+([A-Za-z_][A-Za-z0-9_]*)\s*[\(:]")
_SYMBOL_DECORATOR_RE = re.compile(r"^[ \t]*@")


def _indent_width(line: str) -> int:
    """Ширина отступа (пробелы + tabs*4) для строки."""
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += 4
        else:
            break
    return n


def _find_symbol_in_text(text: str, name: str, kind: str | None) -> tuple[int, int, str] | None:
    """
    Ищет символ name в тексте.
    Возвращает (start_line_1based, end_line_1based, kind) или None.
    kind: 'def' | 'class' | None (любой).
    """
    lines = text.splitlines()
    total = len(lines)

    for i, line in enumerate(lines):
        m_def = _SYMBOL_DEF_RE.match(line)
        m_class = _SYMBOL_CLASS_RE.match(line)

        found_kind: str | None = None
        found_indent = 0
        if m_def and m_def.group(3) == name and kind in (None, "def"):
            found_kind = "def"
            found_indent = _indent_width(line)
        elif m_class and m_class.group(2) == name and kind in (None, "class"):
            found_kind = "class"
            found_indent = _indent_width(line)

        if found_kind is None:
            continue

        # границы: идём вниз до следующего def/class с отступом <= found_indent
        end = total
        for j in range(i + 1, total):
            lj = lines[j]
            if not lj.strip():
                continue
            if _indent_width(lj) <= found_indent:
                # проверяем, что это def/class (а не просто строка кода)
                if _SYMBOL_DEF_RE.match(lj) or _SYMBOL_CLASS_RE.match(lj):
                    end = j  # exclusive
                    break
                # если это не def/class, но с меньшим отступом —
                # символ уже закончился (конец файла / блока)
                if _indent_width(lj) < found_indent:
                    end = j
                    break

        return (i + 1, end, found_kind)

    return None


def _iter_python_files(project_root: Path):
    """Все .py в проекте, кроме служебных папок."""
    skip_dirs = {".git", ".venv", "venv", "__pycache__", ".ai-out", "node_modules"}
    for p in project_root.rglob("*.py"):
        rel = p.relative_to(project_root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        yield p, rel.as_posix()


def tool_read_symbol(args: dict[str, Any], project_root: Path) -> ToolResult:
    """
    read_symbol(name, path=None, kind=None) → тело функции/класса Python.

    name: имя символа (обязательно).
    path: опциональный путь к .py файлу (если None — искать везде).
    kind: 'def' | 'class' (опционально; иначе — любой).

    Возвращает заголовок '# <path>:<line> (<kind> <name>)' и тело.
    Если символов несколько — возвращает первый и помечает в шапке.
    Только .py файлы.
    """
    name = str(args.get("name", "")).strip()
    if not name:
        return ToolResult(ok=False, error="read_symbol: missing 'name'")

    path_arg = args.get("path")
    kind = args.get("kind")
    if kind not in (None, "def", "class"):
        return ToolResult(
            ok=False,
            error="read_symbol: kind must be 'def' or 'class'",
        )

    # --- выбор файлов ---
    candidates: list[tuple[Path, str]] = []
    if path_arg:
        p_str = str(path_arg).strip()
        if not p_str.endswith(".py"):
            return ToolResult(
                ok=False,
                error=f"read_symbol supports only .py files, got: {p_str}",
            )
        try:
            abs_p = _safe_path(project_root, p_str)
        except ToolSecurityError as e:
            return ToolResult(ok=False, error=str(e))
        if not abs_p.exists():
            return ToolResult(ok=False, error=f"file not found: {p_str}")
        candidates.append((abs_p, p_str))
    else:
        candidates = list(_iter_python_files(project_root))

    # --- ищем во всех кандидатах, собираем совпадения ---
    matches: list[tuple[Path, str, int, int, str]] = []
    for abs_p, rel in candidates:
        try:
            text = abs_p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = _find_symbol_in_text(text, name, kind)
        if found is not None:
            start, end, k = found
            matches.append((abs_p, rel, start, end, k))
            if path_arg:
                # если путь задан явно — первого достаточно
                break

    if not matches:
        where = f"in {path_arg}" if path_arg else "in any .py file"
        return ToolResult(
            ok=False,
            error=f"read_symbol: symbol '{name}' not found {where}",
        )

    # --- берём первый, читаем его тело ---
    abs_p, rel, start, end, k = matches[0]
    try:
        all_lines = abs_p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return ToolResult(ok=False, error=f"read error: {e}")

    # включаем декораторы сверху (если есть)
    deco_start = start - 1
    while deco_start > 0 and _SYMBOL_DECORATOR_RE.match(all_lines[deco_start - 1]):
        deco_start -= 1

    body_lines = all_lines[deco_start:end]
    body = "\n".join(body_lines)

    # --- маскировка секретов ---
    body, secret_names = mask_secrets(body)

    # --- обрезка ---
    if len(body) > 50_000:
        body = body[:50_000] + f"\n... [обрезано, всего {len(body)} символов]"

    # --- шапка ---
    header_parts = [f"# {rel}:{start} ({k} {name})"]
    if len(matches) > 1:
        others = ", ".join(f"{r}:{s}" for _, r, s, _, _ in matches[1:4])
        header_parts.append(f"# (first match of {len(matches)}; others: {others})")
    header = "\n".join(header_parts) + "\n"

    if secret_names:
        warning = f"⚠️ [masked {len(secret_names)} secret(s): {', '.join(secret_names)}]\n"
        header = warning + header

    return ToolResult(ok=True, output=header + body)


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
            description=(
                "Read a file (or a specific line range of a large file). "
                "For files with '[обрезано]' in output, use grep -n + "
                "read_file(line_start, line_end) to read the exact range."
            ),
            args={
                "path": "relative path to file (POSIX)",
                "line_start": "optional 1-based start line (for large files)",
                "line_end": "optional 1-based end line (inclusive)",
            },
            returns=(
                "file contents, or a line-range slice with header "
                "'# path (lines X-Y of N)' when line_start/line_end given"
            ),
        ),
        tool_read_file,
    ),
    "read_symbol": (
        ToolSpec(
            name="read_symbol",
            description=(
                "Read the full body of a Python function or class by name. "
                "Python (.py) only. Use instead of grep+read_file when you "
                "know the symbol name. Returns header '# path:line (kind name)' "
                "plus the body."
            ),
            args={
                "name": "function or class name (required)",
                "path": "optional .py file to search in (default: whole project)",
                "kind": "optional 'def' or 'class' (default: any)",
            },
            returns="header + body of the symbol; first match if several",
        ),
        tool_read_symbol,
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
    write_cfg: Any = None,
    allow_blacklist: bool = False,
) -> ToolResult:
    """
    Выполняет инструмент по имени.

    Args:
        name: имя инструмента.
        args: аргументы.
        project_root: корень проекта.
        dry_run: если True — dangerous-инструменты НЕ выполняются,
                 возвращают "(dry-run) would have ...".
        write_cfg: секция cfg.write (blacklist_paths/blacklist_files).
                   Если None — проверка blacklist выключена
                   (для обратной совместимости с тестами).
        allow_blacklist: если True — осознанно разрешить запись
                   в blacklist (для self-improvement).

    Returns:
        ToolResult. Если инструмент не найден или упал — ok=False.
    """
    if name not in TOOL_REGISTRY:
        return ToolResult(ok=False, error=f"unknown tool: {name}")

    spec, fn = TOOL_REGISTRY[name]

    # --- blacklist для write_file / edit_file ---
    if write_cfg is not None and not allow_blacklist and name in ("write_file", "edit_file"):
        rel = str(args.get("path", "")).strip()
        if rel:
            from .pathfilter import is_blacklisted

            if is_blacklisted(rel, write_cfg.blacklist_paths, write_cfg.blacklist_files):
                return ToolResult(
                    ok=False,
                    error=(
                        f"{name}: path '{rel}' is blacklisted (use --allow-blacklist to override)"
                    ),
                )

    # dry-run: пропускаем dangerous, но сообщаем, что БЫЛО БЫ сделано.
    # Формулировка "EDITED/WROTE/RAN" (а не "would have called") — чтобы
    # модель понимала: в симуляции действие УСПЕШНО, можно завершать.
    if dry_run and spec.dangerous:
        if name == "edit_file":
            path = args.get("path", "?")
            preview = f"(dry-run) EDITED {path} (simulated OK, file NOT changed on disk)"
        elif name == "write_file":
            path = args.get("path", "?")
            content = args.get("content", "")
            preview = (
                f"(dry-run) WROTE {path} ({len(content)} chars) "
                f"(simulated OK, file NOT created on disk)"
            )
        elif name == "run_shell":
            cmd = args.get("command", "?")
            preview = f"(dry-run) RAN `{cmd}` (simulated OK, command NOT executed)"
        else:
            args_repr = ", ".join(f"{k}={v!r}" for k, v in args.items())
            preview = f"(dry-run) would have called {name}({args_repr})"
        return ToolResult(ok=True, output=preview, dry_run=True)

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


def format_tool_history(
    history: list[tuple[ToolAction, ToolResult]],
    max_items: int = 10,
    read_file_max_chars: int = 10_000,
    other_max_chars: int = 500,
) -> str:
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
        full_output = result.output or result.error or ""

        # read_file / read_symbol — привилегированные: показываем
        # содержимое целиком (до read_file_max_chars), чтобы модель
        # НЕ перечитывала файл/символ. Для остальных — 500 символов.
        if action.tool in ("read_file", "read_symbol"):
            max_chars = read_file_max_chars
        else:
            max_chars = other_max_chars

        if len(full_output) > max_chars:
            # для read_symbol подсказка про grep не нужна —
            # символ уже прочитан, второй раз не надо
            if action.tool == "read_symbol":
                hint = "Не перечитывай — правь через edit_file или finish.]"
            else:
                hint = "Используй run_shell grep для точного поиска.]"
            snippet = (
                full_output[:max_chars]
                + f"\n     ... [обрезано, всего {len(full_output)} символов. "
                + hint
            )
        else:
            snippet = full_output

        lines.append(f"#{i}. {desc} → {status}")
        if snippet:
            lines.append(f"     {snippet}")
    return "\n".join(lines)
