"""
Минимальный враппер над git CLI через subprocess.

Используется для:
  - проверки, что project_root — git-репозиторий;
  - проверки чистоты рабочего дерева перед --apply;
  - автокоммита после успешного --apply.

Намеренно НЕ использует pygit2/dulwich — только subprocess, как в терминале.
Не делает push, merge, rebase, branch -D, reset --hard.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Таймаут на одну git-команду. git обычно быстрый, 30 секунд с запасом.
_GIT_TIMEOUT_SEC = 30


def _run_git(
    args: list[str],
    cwd: Path,
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str] | None:
    """
    Запускает git с аргументами. Возвращает CompletedProcess или None
    при OSError (git не установлен) или TimeoutExpired.
    """
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SEC,
            check=check,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def is_git_repo(path: Path) -> bool:
    """
    True, если path находится внутри git-репозитория.

    Работает и для подкаталогов: git сам поднимается до корня.
    """
    r = _run_git(["rev-parse", "--git-dir"], path)
    return r is not None and r.returncode == 0


def status_porcelain(path: Path) -> str:
    """
    Возвращает вывод `git status --porcelain`.

    Пустая строка — рабочее дерево чистое.
    Непустая — есть изменения (staged, unstaged, untracked).

    При ошибке (не git-репо, git недоступен) — возвращает "".
    Различить «чисто» от «ошибка» можно через is_git_repo().
    """
    r = _run_git(["status", "--porcelain"], path)
    if r is None or r.returncode != 0:
        return ""
    return r.stdout


def current_branch(path: Path) -> str | None:
    """
    Имя текущей ветки или None, если:
      - не git-репозиторий;
      - git недоступен;
      - detached HEAD (не на ветке).
    """
    r = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], path)
    if r is None or r.returncode != 0:
        return None
    name = r.stdout.strip()
    if not name or name == "HEAD":
        # detached HEAD — git возвращает "HEAD"
        return None
    return name


def commit(
    path: Path,
    message: str,
    files: list[str] | None = None,
) -> str | None:
    """
    Делает git add + git commit.

    Args:
        path: корень репозитория.
        message: сообщение коммита.
        files: список путей (относительно path) для `git add`.
               None → `git add -A` (все изменения, включая новые/удалённые).

    Returns:
        Короткий hash коммита (8 символов) или None, если коммит не создан
        (нечего коммитить, ошибка git, git недоступен).

    Не делает push. Не меняет ветку.
    """
    # --- git add ---
    if files:
        # добавить только указанные пути
        add_args = ["add", "--", *files]
    else:
        # добавить всё (новые, изменённые, удалённые)
        add_args = ["add", "-A"]

    r_add = _run_git(add_args, path)
    if r_add is None or r_add.returncode != 0:
        return None

    # --- git commit ---
    r_commit = _run_git(["commit", "-m", message], path)
    if r_commit is None or r_commit.returncode != 0:
        # Частая причина — нечего коммитить. Возвращаем None.
        return None

    # --- hash ---
    r_hash = _run_git(["rev-parse", "--short=8", "HEAD"], path)
    if r_hash is None or r_hash.returncode != 0:
        return None
    return r_hash.stdout.strip()


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 40) -> str:
    """
    Превращает произвольный текст в slug для имени ветки/метки.

    "Подними --cov-fail-under с 40 до 70" → "podnimi-cov-fail-under-s-40-do-70"
    (кириллица → транслит не делаем, режем не-ASCII).

    Для ASCII-текста: lowercase, не-буквы/цифры → дефис, схлопывание.
    Для кириллицы: буквы становятся дефисами, остаётся мало — ок,
    используем fallback "task".

    Возвращает непустую строку (минимум "task").
    """
    # Приводим к ASCII: не-ASCII символы (в т.ч. кириллица) выкидываем.
    ascii_text = text.encode("ascii", errors="ignore").decode("ascii").lower()
    slug = _SLUG_RE.sub("-", ascii_text).strip("-")
    if not slug:
        return "task"
    return slug[:max_len].rstrip("-")


def format_commit_message(goal: str, ops: int, cost_rub: float) -> str:
    """
    Формирует сообщение коммита агента.

    Пример:
      "ai-coder: подними cov-fail-under (1 ops, 0.05 RUB)"

    goal обрезается до 60 символов, переводы строк заменяются пробелами.
    """
    short_goal = " ".join(goal.split())[:60].strip()
    if not short_goal:
        short_goal = "agent task"
    return f"ai-coder: {short_goal} ({ops} ops, {cost_rub:.2f} RUB)"
