import re
from datetime import date
from pathlib import Path

from ai_coder.agent import _slug_for_issue


def next_history_number(directory: Path, day: str) -> int:
    """Return the next NN for date: max(existing)+1 else 0."""
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


def save_history_entry(
    project_root: Path,
    goal: str,
    command: str,
    *,
    today: date | None = None,
    write_issue: bool = True,
) -> tuple[Path, Path | None]:
    """Write two files: command and issue, return their paths."""
    if today is None:
        today = date.today()
    day_str = today.isoformat()
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
        issue_path: Path | None = project_root / "issues" / day_str / f"{nn_str}_{slug}.md"
        issue_content = f"# task: {slug}\n{goal}\n"
        issue_path.write_text(issue_content, encoding="utf-8")
    else:
        issue_path = None

    return cmd_path, issue_path
