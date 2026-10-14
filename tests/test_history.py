from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ai_coder.history import make_slug, next_history_number, save_history_entry

# ---------- next_history_number ----------


def test_next_history_number_empty_dir(tmp_path: Path) -> None:
    """Пустая директория -> 0."""
    assert next_history_number(tmp_path, "2026-01-01") == 0


def test_next_history_number_missing_dir(tmp_path: Path) -> None:
    """Несуществующая директория -> 0."""
    missing = tmp_path / "nope"
    assert next_history_number(missing, "2026-01-01") == 0


def test_next_history_number_files_but_no_matches(tmp_path: Path) -> None:
    """Файлы есть, но не подходят под шаблон -> 0."""
    (tmp_path / "readme.md").write_text("x", encoding="utf-8")
    (tmp_path / "abc_foo.txt").write_text("x", encoding="utf-8")
    assert next_history_number(tmp_path, "2026-01-01") == 0


def test_next_history_number_single_file(tmp_path: Path) -> None:
    (tmp_path / "00_hello.txt").write_text("x", encoding="utf-8")
    assert next_history_number(tmp_path, "2026-01-01") == 1


def test_next_history_number_max_plus_one(tmp_path: Path) -> None:
    (tmp_path / "00_a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "02_b.md").write_text("x", encoding="utf-8")
    (tmp_path / "05_c.txt").write_text("x", encoding="utf-8")
    assert next_history_number(tmp_path, "2026-01-01") == 6


def test_next_history_number_ignores_non_matching_names(tmp_path: Path) -> None:
    (tmp_path / "03_ok.txt").write_text("x", encoding="utf-8")
    (tmp_path / "notthere.txt").write_text("x", encoding="utf-8")
    (tmp_path / "7_short.txt.md.bak").write_text("x", encoding="utf-8")
    assert next_history_number(tmp_path, "2026-01-01") == 4


def test_next_history_number_ignores_subdirs(tmp_path: Path) -> None:
    """Директории с подходящим именем не учитываются (только файлы)."""
    (tmp_path / "09_dir.txt").mkdir()
    assert next_history_number(tmp_path, "2026-01-01") == 0


def test_next_history_number_markdown_ext(tmp_path: Path) -> None:
    (tmp_path / "10_task.md").write_text("x", encoding="utf-8")
    assert next_history_number(tmp_path, "2026-01-01") == 11


# ---------- make_slug ----------


def test_make_slug_ascii() -> None:
    assert make_slug("Add new feature") == "add-new-feature"


def test_make_slug_lowercases() -> None:
    assert make_slug("UPPER Case") == "upper-case"


def test_make_slug_cyrillic() -> None:
    """Кириллица транслитерируется, пробелы -> дефисы."""
    slug = make_slug("Проверка связи")
    assert slug
    assert " " not in slug
    assert slug.isascii()


def test_make_slug_empty_text_returns_task() -> None:
    assert make_slug("!!!") == "task"


def test_make_slug_respects_max_len() -> None:
    slug = make_slug("a" * 100)
    assert len(slug) <= 40


def test_make_slug_no_leading_trailing_dashes() -> None:
    slug = make_slug("  hello  ")
    assert not slug.startswith("-")
    assert not slug.endswith("-")


# ---------- save_history_entry ----------


def test_save_history_entry_creates_files(tmp_path: Path) -> None:
    cmd_path, issue_path = save_history_entry(
        tmp_path,
        "Test goal",
        "do the thing",
        today=date(2026, 1, 2),
    )
    assert cmd_path.exists()
    assert issue_path.exists()
    assert cmd_path.parent == tmp_path / "commands" / "2026-01-02"
    assert issue_path.parent == tmp_path / "issues" / "2026-01-02"


def test_save_history_entry_content(tmp_path: Path) -> None:
    cmd_path, issue_path = save_history_entry(
        tmp_path,
        "Test goal",
        "do the thing",
        today=date(2026, 1, 2),
    )
    slug = make_slug("Test goal")
    assert cmd_path.name == f"00_{slug}.txt"
    assert issue_path.name == f"00_{slug}.md"
    assert cmd_path.read_text(encoding="utf-8") == "do the thing\n"
    assert issue_path.read_text(encoding="utf-8") == f"# task: {slug}\nTest goal\n"


def test_save_history_entry_numbering_increments(tmp_path: Path) -> None:
    save_history_entry(tmp_path, "first", "cmd1", today=date(2026, 1, 2))
    cmd_path, _ = save_history_entry(tmp_path, "second", "cmd2", today=date(2026, 1, 2))
    assert cmd_path.name.startswith("01_")


def test_save_history_entry_returns_paths(tmp_path: Path) -> None:
    result = save_history_entry(tmp_path, "g", "c", today=date(2026, 1, 2))
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert all(isinstance(p, Path) for p in result)


def test_save_history_entry_default_today(tmp_path: Path) -> None:
    """Без today используется date.today()."""
    cmd_path, issue_path = save_history_entry(tmp_path, "g", "c")
    day = date.today().isoformat()
    assert day in str(cmd_path)
    assert day in str(issue_path)


def test_save_history_entry_idempotent_creates_dirs(tmp_path: Path) -> None:
    """Повторный вызов в тот же день не падает (exist_ok=True)."""
    save_history_entry(tmp_path, "a", "b", today=date(2026, 1, 2))
    # повторный вызов не должен бросить FileExistsError
    save_history_entry(tmp_path, "a", "b", today=date(2026, 1, 2))


def test_save_history_entry_no_issue(tmp_path: Path) -> None:
    """write_issue=False: только команда, без issue-файла."""
    cmd_path, issue_path = save_history_entry(
        tmp_path,
        "Test goal",
        "do the thing",
        today=date(2026, 1, 2),
        write_issue=False,
    )
    assert cmd_path.exists()
    assert issue_path is None
    assert not (tmp_path / "issues").exists()
