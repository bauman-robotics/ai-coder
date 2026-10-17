import re
import shlex
import sys
from datetime import date
from pathlib import Path

from ai_coder.agent import _slug_for_issue


def next_history_number(directory: Path, day: str) -> int:
    """Return the next NN for date: max(existing)+1 else 0.

    v1: гонка <NN> при ПАРАЛЛЕЛЬНЫХ прогонах не обрабатывается — чтение
    commands/<date>/ и запись файла не атомарны, два одновременных запуска
    могут получить один NN. Осознанно отложено, см. issue
    2026-10-17/01_reports-structure.md («Гонку <NN> ... игнорируем (v1)»).
    """
    pattern = re.compile(r"^(\d+)_.*\.(?:txt|md)$")
    max_nn = -1
    if directory.is_dir():
        for f in directory.iterdir():
            if f.is_file():
                m = pattern.match(f.name)
                if m:
                    nn = int(m.group(1))
                    if nn > max_nn:
                        max_nn = nn
    if max_nn == -1:
        return 0
    return max_nn + 1


def make_slug(goal: str) -> str:
    """Wrapper around ai_coder.agent._slug_for_issue."""
    return _slug_for_issue(goal)


def build_command(argv: list[str] | None = None) -> str:
    """Полная CLI-команда: `ai-coder ...` из argv (по умолчанию sys.argv[1:]).

    Один источник для commands/<date>/<NN>_<slug>.txt и goal.txt: и CLI,
    и GUI (через subprocess) в итоге проходят через реконструкцию argv
    по shlex.quote, поэтому формат совпадает.
    """
    args = sys.argv[1:] if argv is None else argv
    return "ai-coder " + " ".join(shlex.quote(a) for a in args)


def parse_nn_slug(cmd_path: Path) -> tuple[int, str]:
    """Разобрать `<NN>_<slug>.txt` (или .md) -> (int NN, slug).

    Формат имён commands/ не меняем — только читаем его.
    """
    m = re.match(r"^(\d+)_(.+)\.(?:txt|md)$", cmd_path.name)
    if m is None:
        raise ValueError(f"Не удалось разобрать <NN>_<slug> из {cmd_path.name!r}")
    return int(m.group(1)), m.group(2)


def report_subdir_for(day: str, nn: int, mode: str, slug: str) -> str:
    """Относительный путь папки задачи: `<date>/<NN>_<mode>_<slug>`."""
    return f"{day}/{nn:02d}_{mode}_{slug}"


def write_goal_txt(task_dir: Path, command: str) -> Path:
    """Записать goal.txt рядом с report.md — ровно тот же текст, что в commands/."""
    task_dir.mkdir(parents=True, exist_ok=True)
    path = task_dir / "goal.txt"
    path.write_text(command.rstrip("\n") + "\n", encoding="utf-8")
    return path


def save_history_entry(
    project_root: Path,
    goal: str,
    command: str,
    *,
    today: date | None = None,
    write_issue: bool = True,
    slug: str | None = None,
) -> tuple[Path, Path | None]:
    """Write two files: command and issue, return their paths.

    slug по умолчанию = make_slug(goal). Явный slug нужен chain: там
    <slug> — dirname каталога issues, а не транслит общего goal.
    """
    if today is None:
        today = date.today()
    day_str = today.isoformat()
    if slug is None:
        slug = make_slug(goal)

    commands_dir = project_root / "commands" / day_str
    commands_dir.mkdir(parents=True, exist_ok=True)

    nn_cmd = next_history_number(commands_dir, day_str)
    nn_issue = 0
    if write_issue:
        issues_dir = project_root / "issues" / day_str
        issues_dir.mkdir(parents=True, exist_ok=True)
        nn_issue = next_history_number(issues_dir, day_str)

    nn = max(nn_cmd, nn_issue)
    nn_str = f"{nn:02d}"

    cmd_path = commands_dir / f"{nn_str}_{slug}.txt"
    cmd_path.write_text(command + "\n", encoding="utf-8")

    if write_issue:
        issue_path_obj = project_root / "issues" / day_str / f"{nn_str}_{slug}.md"
        issue_content = f"# task: {slug}\n{goal}\n"
        issue_path_obj.write_text(issue_content, encoding="utf-8")
        issue_path: Path | None = issue_path_obj
    else:
        issue_path = None

    return cmd_path, issue_path
