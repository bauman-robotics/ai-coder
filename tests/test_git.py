from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_coder.git import (
    commit,
    current_branch,
    format_commit_message,
    is_git_repo,
    slugify,
    status_porcelain,
)

# ---------- фикстура: временный git-репозиторий ----------


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Хелпер для setup-команд в тестах."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """
    Создаёт временный git-репозиторий с одним коммитом.

    Важно: настраиваем user.email/user.name локально, чтобы
    git commit работал без глобального конфига.
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    _run_git(["init", "-b", "main"], repo)
    _run_git(["config", "user.email", "test@example.com"], repo)
    _run_git(["config", "user.name", "Test User"], repo)
    _run_git(["config", "commit.gpgsign", "false"], repo)

    # первый коммит — чтобы был HEAD
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    _run_git(["add", "README.md"], repo)
    _run_git(["commit", "-m", "initial"], repo)

    return repo


# ---------- is_git_repo ----------


def test_is_git_repo_true(git_repo: Path):
    assert is_git_repo(git_repo) is True


def test_is_git_repo_false(tmp_path: Path):
    # tmp_path — не git-репозиторий
    plain = tmp_path / "not_a_repo"
    plain.mkdir()
    assert is_git_repo(plain) is False


def test_is_git_repo_subdir(git_repo: Path):
    """Подкаталог git-репозитория — тоже git-репо."""
    sub = git_repo / "src"
    sub.mkdir()
    assert is_git_repo(sub) is True


# ---------- status_porcelain ----------


def test_status_porcelain_clean(git_repo: Path):
    """Свежий репо — чисто."""
    assert status_porcelain(git_repo) == ""


def test_status_porcelain_modified(git_repo: Path):
    """Изменённый файл — непустой вывод."""
    (git_repo / "README.md").write_text("# changed\n", encoding="utf-8")
    out = status_porcelain(git_repo)
    assert out != ""
    assert "README.md" in out


def test_status_porcelain_untracked(git_repo: Path):
    """Новый файл — тоже видно."""
    (git_repo / "new.py").write_text("x = 1\n", encoding="utf-8")
    out = status_porcelain(git_repo)
    assert "new.py" in out


def test_status_porcelain_not_a_repo(tmp_path: Path):
    """Не git-репо — пустая строка (не падаем)."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert status_porcelain(plain) == ""


# ---------- current_branch ----------


def test_current_branch_main(git_repo: Path):
    assert current_branch(git_repo) == "main"


def test_current_branch_after_checkout(git_repo: Path):
    _run_git(["checkout", "-b", "feature-x"], git_repo)
    assert current_branch(git_repo) == "feature-x"


def test_current_branch_not_a_repo(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert current_branch(plain) is None


# ---------- commit ----------


def test_commit_modified_file(git_repo: Path):
    (git_repo / "README.md").write_text("# updated\n", encoding="utf-8")
    h = commit(git_repo, "ai-coder: test commit")
    assert h is not None
    assert len(h) == 8
    # дерево стало чистым
    assert status_porcelain(git_repo) == ""


def test_commit_nothing_to_commit(git_repo: Path):
    """Нет изменений — commit возвращает None, не падает."""
    h = commit(git_repo, "ai-coder: empty")
    assert h is None


def test_commit_specific_files_only(git_repo: Path):
    """files=[...] — коммитит только указанные, остальные остаются modified."""
    (git_repo / "a.py").write_text("a = 1\n", encoding="utf-8")
    (git_repo / "b.py").write_text("b = 2\n", encoding="utf-8")

    h = commit(git_repo, "ai-coder: add a.py", files=["a.py"])
    assert h is not None

    # a.py — в коммите, b.py — всё ещё untracked
    out = status_porcelain(git_repo)
    assert "b.py" in out
    assert "a.py" not in out


def test_commit_all_files(git_repo: Path):
    """files=None → git add -A (все изменения)."""
    (git_repo / "a.py").write_text("a = 1\n", encoding="utf-8")
    (git_repo / "b.py").write_text("b = 2\n", encoding="utf-8")

    h = commit(git_repo, "ai-coder: add all")
    assert h is not None
    assert status_porcelain(git_repo) == ""


def test_commit_not_a_repo(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "x.py").write_text("x = 1\n", encoding="utf-8")
    h = commit(plain, "ai-coder: nope")
    assert h is None


# ---------- slugify ----------


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"


def test_slugify_punctuation():
    assert slugify("подними --cov-fail-under 40 до 70") == "cov-fail-under-40-70"


def test_slugify_only_punctuation():
    """Только не-ASCII — fallback 'task'."""
    assert slugify("русский текст") == "task"


def test_slugify_max_len():
    s = slugify("a" * 100, max_len=10)
    assert len(s) <= 10


def test_slugify_no_trailing_dash():
    assert not slugify("hello---").endswith("-")


# ---------- format_commit_message ----------


def test_format_commit_message_basic():
    msg = format_commit_message("подними cov-fail-under", ops=1, cost_rub=0.05)
    assert msg.startswith("ai-coder:")
    assert "1 ops" in msg
    assert "0.05 RUB" in msg


def test_format_commit_message_multiline_goal():
    msg = format_commit_message("line1\nline2", ops=2, cost_rub=0.123)
    assert "\n" not in msg


def test_format_commit_message_long_goal():
    msg = format_commit_message("a" * 200, ops=1, cost_rub=0.0)
    # 60 символов на goal + служебный текст
    assert len(msg) < 120


def test_format_commit_message_empty_goal():
    msg = format_commit_message("", ops=0, cost_rub=0.0)
    assert "agent task" in msg
