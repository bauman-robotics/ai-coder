"""Тесты выбора verify-команд (D6, finding #1).

Проблема: `verify_commands` гоняется в проекте-цели, поэтому
`python -m mypy ai_coder` нельзя включать безусловно — в чужом проекте
пакета `ai_coder` нет. Решение: `self_verify_commands` применяются
только когда проект-цель — сам ai-coder (`is_self_hosted`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from ai_coder.apply import is_self_hosted, resolve_verify_commands, run_verify_commands
from ai_coder.config import load_config

REPO = Path(__file__).resolve().parent.parent


# ---------- is_self_hosted ----------


def test_is_self_hosted_true_for_ai_coder():
    assert is_self_hosted(REPO) is True


def test_is_self_hosted_false_for_foreign_project(tmp_path: Path):
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    assert is_self_hosted(tmp_path) is False


def test_is_self_hosted_false_for_empty_dir(tmp_path: Path):
    assert is_self_hosted(tmp_path) is False


def test_is_self_hosted_false_without_init(tmp_path: Path):
    """Каталог ai_coder/ без __init__.py — не считаем self-hosted."""
    (tmp_path / "ai_coder").mkdir()
    assert is_self_hosted(tmp_path) is False


# ---------- resolve_verify_commands: приоритеты ----------


def test_disabled_wins_over_everything(tmp_path: Path):
    (tmp_path / "ai_coder").mkdir()
    (tmp_path / "ai_coder" / "__init__.py").write_text("", encoding="utf-8")
    assert (
        resolve_verify_commands(
            project_root=tmp_path,
            base_commands=["pytest -q"],
            self_commands=["mypy ai_coder"],
            explicit=["ruff check ."],
            disabled=True,
        )
        == []
    )


def test_explicit_wins_over_self(tmp_path: Path):
    (tmp_path / "ai_coder").mkdir()
    (tmp_path / "ai_coder" / "__init__.py").write_text("", encoding="utf-8")
    got = resolve_verify_commands(
        project_root=tmp_path,
        base_commands=["pytest -q"],
        self_commands=["mypy ai_coder"],
        explicit=["ruff check ."],
    )
    assert got == ["ruff check ."]


def test_explicit_empty_stays_empty(tmp_path: Path):
    """Явный [] (read-only subagent в spawn) НЕ получает self-проверок."""
    (tmp_path / "ai_coder").mkdir()
    (tmp_path / "ai_coder" / "__init__.py").write_text("", encoding="utf-8")
    assert (
        resolve_verify_commands(
            project_root=tmp_path,
            base_commands=["pytest -q"],
            self_commands=["mypy ai_coder"],
            explicit=[],
        )
        == []
    )


# ---------- resolve_verify_commands: base / self ----------


def test_foreign_project_gets_only_base(tmp_path: Path):
    got = resolve_verify_commands(
        project_root=tmp_path,
        base_commands=["python -m pytest -q"],
        self_commands=["python -m mypy ai_coder"],
    )
    assert got == ["python -m pytest -q"]


def test_self_hosted_gets_base_plus_self(tmp_path: Path):
    (tmp_path / "ai_coder").mkdir()
    (tmp_path / "ai_coder" / "__init__.py").write_text("", encoding="utf-8")
    got = resolve_verify_commands(
        project_root=tmp_path,
        base_commands=["python -m pytest -q"],
        self_commands=["python -m ruff check ai_coder/", "python -m mypy ai_coder"],
    )
    assert got == [
        "python -m pytest -q",
        "python -m ruff check ai_coder/",
        "python -m mypy ai_coder",
    ]


def test_self_commands_deduplicated(tmp_path: Path):
    (tmp_path / "ai_coder").mkdir()
    (tmp_path / "ai_coder" / "__init__.py").write_text("", encoding="utf-8")
    got = resolve_verify_commands(
        project_root=tmp_path,
        base_commands=["python -m mypy ai_coder"],
        self_commands=["python -m mypy ai_coder"],
    )
    assert got == ["python -m mypy ai_coder"]


def test_none_self_commands_ok(tmp_path: Path):
    got = resolve_verify_commands(
        project_root=tmp_path, base_commands=["pytest -q"], self_commands=None
    )
    assert got == ["pytest -q"]


# ---------- реальный конфиг проекта ----------


def test_real_config_has_self_verify_mypy():
    cfg = load_config(REPO / "config" / "config.yaml")
    joined = " ".join(cfg.agent.self_verify_commands)
    assert "mypy" in joined
    assert "ruff" in joined
    # generic-команды не должны содержать self-специфику
    assert not any("ai_coder" in c for c in cfg.agent.verify_commands)


def test_real_config_resolution_for_self_and_foreign(tmp_path: Path):
    cfg = load_config(REPO / "config" / "config.yaml")
    own = resolve_verify_commands(
        project_root=REPO,
        base_commands=cfg.agent.verify_commands,
        self_commands=cfg.agent.self_verify_commands,
    )
    assert any("mypy" in c for c in own)

    foreign = resolve_verify_commands(
        project_root=tmp_path,
        base_commands=cfg.agent.verify_commands,
        self_commands=cfg.agent.self_verify_commands,
    )
    assert foreign == cfg.agent.verify_commands
    assert not any("mypy" in c for c in foreign)


# ---------- механизменный E2E: mypy-ошибка → verify fail ----------


def test_e2e_mypy_error_fails_verify(tmp_path: Path):
    """Self-hosted песочница с mypy-ошибкой → verify возвращает ошибку.

    Используем sys.executable, чтобы тест не зависел от PATH.
    """
    pkg = tmp_path / "ai_coder"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # Несовместимое присваивание — ровно класс ошибки из D5 (E2E-1).
    (pkg / "broken.py").write_text(
        "def f() -> None:\n    x = 'edit'\n    x = None\n", encoding="utf-8"
    )

    cmds = resolve_verify_commands(
        project_root=tmp_path,
        base_commands=[],
        self_commands=[f"{sys.executable} -m mypy ai_coder"],
    )
    assert cmds, "self-проверка должна была добавиться"

    errors = run_verify_commands(cmds, tmp_path, timeout_sec=120)
    assert errors, "mypy-ошибка должна была завалить verify"
    assert "mypy" in errors[0].lower() or "broken.py" in errors[0]


def test_e2e_foreign_project_not_broken_by_mypy(tmp_path: Path):
    """В чужом проекте self-команда не добавляется → verify не падает."""
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    cmds = resolve_verify_commands(
        project_root=tmp_path,
        base_commands=[],
        self_commands=[f"{sys.executable} -m mypy ai_coder"],
    )
    assert cmds == []
    assert run_verify_commands(cmds, tmp_path) == []
