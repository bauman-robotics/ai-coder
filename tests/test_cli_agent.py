from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ai_coder.cli import app

runner = CliRunner(env={"COLUMNS": "200"})


@pytest.fixture
def cli_env(tmp_path: Path, minimal_cfg):
    import yaml

    from ai_coder.config import ActionConfig

    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    project = tmp_path / "proj"
    project.mkdir()

    minimal_cfg.actions = {
        "greet": ActionConfig(description="greet", prompt="greet", mode="read", enabled=True),
    }
    config_path.write_text(
        yaml.safe_dump(minimal_cfg.model_dump(mode="json"), allow_unicode=True), encoding="utf-8"
    )
    prompts_path.write_text(
        yaml.safe_dump(
            {
                "greet": {"system": "S", "user": "U"},
                "agent_plan_json": {"system": "S {{max_steps}}", "user": "U {{goal}}"},
                "agent_step_json": {"system": "S", "user": "U {{goal}}"},
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    return {
        "config": config_path,
        "prompts": prompts_path,
        "project": project,
    }


def _fake_agent_result(project: Path, *, preview_only: bool = False):
    """Собирает AgentRunResult с пустым планом."""
    from ai_coder.agent import AgentPlan, AgentRunResult
    from ai_coder.llm import LLMResponse

    now = datetime.now(timezone.utc)
    llm = LLMResponse(
        content="plan json",
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=500,
        finish_reason="stop",
    )

    # пустой план (empty_plan) — самый простой сценарий для рендера
    plan = AgentPlan(
        goal="test goal",
        explanation="nothing to do",
        steps=[],
        empty=True,
    )

    return AgentRunResult(
        goal="test goal",
        plan=plan,
        planner_llm=llm,
        planner_cost_rub=0.05,
        planner_cost_cny=0.004,
        planner_cost_usd=0.0006,
        steps=[],
        started_at=now,
        finished_at=now,
        stopped_reason="empty_plan",
        journal_dir=None,
    )


# ---------- тесты ----------


def test_agent_preview_only_apply_conflict(cli_env):
    """--preview-only и --apply вместе — ошибка."""
    result = runner.invoke(
        app,
        [
            "agent",
            "test goal",
            str(cli_env["project"]),
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
            "--preview-only",
            "--apply",
        ],
    )

    assert result.exit_code == 1
    assert "Нельзя одновременно" in result.stdout


def test_agent_bad_path(cli_env, tmp_path):
    missing = tmp_path / "no-such-dir"
    result = runner.invoke(
        app,
        [
            "agent",
            "test goal",
            str(missing),
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
        ],
    )

    assert result.exit_code == 1
    assert "Не директория" in result.stdout


def test_agent_empty_plan(cli_env):
    """Мок run_agent — пустой план, вывод «цель достигнута»."""
    with patch("ai_coder.cli.run_agent") as mock_agent:
        mock_agent.return_value = _fake_agent_result(cli_env["project"])

        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                "--preview-only",
            ],
        )

    assert result.exit_code == 0
    assert mock_agent.call_count == 1
    assert "План агента" in result.stdout


def test_agent_error_handling(cli_env):
    with patch("ai_coder.cli.run_agent") as mock_agent:
        mock_agent.side_effect = RuntimeError("planner failed")

        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
            ],
        )

    assert result.exit_code == 1
    assert "Ошибка агента" in result.stdout


def test_agent_max_tokens_override(cli_env):
    """--max-tokens принимается командой agent."""
    from unittest.mock import patch

    with patch("ai_coder.cli.run_agent") as mock_agent:
        mock_agent.return_value = _fake_agent_result(cli_env["project"])

        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                "--max-tokens",
                "50000",
                "--preview-only",
            ],
        )

    assert result.exit_code == 0


def test_agent_conflicting_web_flags(cli_env):
    """--exclude-web и --include-web в агенте — ошибка."""
    result = runner.invoke(
        app,
        [
            "agent",
            "test goal",
            str(cli_env["project"]),
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
            "--exclude-web",
            "--include-web",
        ],
    )
    assert result.exit_code == 1
    assert "Нельзя одновременно" in result.stdout


def test_agent_verify_commands_flag(cli_env):
    from unittest.mock import patch

    with patch("ai_coder.cli.run_agent") as mock_agent:
        mock_agent.return_value = _fake_agent_result(cli_env["project"])

        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                "--verify-commands",
                "pytest -q;ruff check .",
                "--preview-only",
            ],
        )

    assert result.exit_code == 0
    call_kwargs = mock_agent.call_args.kwargs
    cfg = call_kwargs["cfg"]
    assert cfg.agent.verify_commands == ["pytest -q", "ruff check ."]


def test_agent_interactive_requires_apply(cli_env):
    """--interactive без --apply — ошибка."""
    result = runner.invoke(
        app,
        [
            "agent",
            "test goal",
            str(cli_env["project"]),
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
            "--interactive",
        ],
    )
    assert result.exit_code == 1
    assert "требует --apply" in result.stdout


# ---------- agent --issue ----------


def test_agent_issue_reads_goal(tmp_path: Path, monkeypatch):
    """--issue читает goal из файла, первая строка # task: отбрасывается."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    issue = tmp_path / "1.md"
    issue.write_text(
        "# task: test\n\n## Цель\nСделай что-то.\n",
        encoding="utf-8",
    )

    captured: dict = {}

    def fake_run_tool_loop(**kwargs):
        captured.update(kwargs)
        from ai_coder.agent import ToolLoopResult

        return ToolLoopResult(success=True, summary="ok", iterations=0)

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_run_tool_loop)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "agent",
            "--issue",
            str(issue),
            str(project),
            "--tool-loop",
            "--no-verify",
        ],
    )
    # goal должен быть из issue (без "# task:")
    assert "Сделай что-то" in captured.get("goal", "")
    assert not captured.get("goal", "").startswith("# task:")


def test_agent_issue_and_goal_conflict(tmp_path: Path):
    """--issue + непустой goal-не-директория → ошибка."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    issue = tmp_path / "1.md"
    issue.write_text("# task\n\nЦель.\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "agent",
            "это-не-директория",
            "--issue",
            str(issue),
            "--tool-loop",
        ],
    )
    # exit != 0 и сообщение про несовместимость
    assert result.exit_code != 0
    assert "несовместим" in result.stdout.lower() or "несовместим" in result.output.lower()


def test_agent_issue_missing_file(tmp_path: Path):
    """Несуществующий --issue → ошибка."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "--issue", str(tmp_path / "nope.md"), "--tool-loop"],
    )
    assert result.exit_code != 0


def test_agent_issue_empty_file(tmp_path: Path):
    """Пустой --issue (после отбрасывания заголовка) → ошибка."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    issue = tmp_path / "empty.md"
    issue.write_text("# task: empty\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "--issue", str(issue), "--tool-loop"],
    )
    assert result.exit_code != 0
