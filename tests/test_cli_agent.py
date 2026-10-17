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
            # path обязателен: без него project_root = cwd = реальный main,
            # и history пишет мусор в issues/ и commands/.
            str(tmp_path),
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


# ---------- agent --plan ----------


def test_agent_plan_requires_tool_loop(tmp_path: Path):
    """--plan без --tool-loop → ошибка (как у --decompose)."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "goal", str(project), "--plan"],
    )
    assert result.exit_code != 0
    assert "tool-loop" in result.stdout.lower() or "tool loop" in result.stdout.lower()


def test_agent_plan_no_cancels(tmp_path: Path, monkeypatch):
    """--plan: показ плана, ответ 'n' → выход без выполнения."""
    from typer.testing import CliRunner

    from ai_coder.agent import DecomposeResult, Subtask
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    dec = DecomposeResult(
        explanation="plan",
        subtasks=[Subtask(n=1, goal="do it", files=["x.py"])],
        cost_rub=0.05,
    )

    called = {"exec": False}

    def fake_exec(**kwargs):
        called["exec"] = True
        from ai_coder.agent import DecomposeResult as DR

        return DR(explanation="", subtasks=[])

    monkeypatch.setattr("ai_coder.agent.run_planner_decompose", lambda **kw: dec)
    monkeypatch.setattr("ai_coder.agent.run_agent_decompose", fake_exec)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "goal", str(project), "--plan", "--tool-loop"],
        input="n\n",
    )
    assert result.exit_code == 0, result.stdout
    assert called["exec"] is False, "run_agent_decompose НЕ должен вызываться при 'n'"
    assert "Отменено" in result.stdout


def test_agent_plan_yes_executes(tmp_path: Path, monkeypatch):
    """--plan + 'y' → run_agent_decompose вызван с plan=."""
    from typer.testing import CliRunner

    from ai_coder.agent import DecomposeResult, Subtask
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    dec = DecomposeResult(
        explanation="plan",
        subtasks=[Subtask(n=1, goal="do it", files=["x.py"])],
        cost_rub=0.05,
    )

    captured: dict = {}

    def fake_exec(**kwargs):
        captured.update(kwargs)
        return DecomposeResult(explanation="", subtasks=[])

    monkeypatch.setattr("ai_coder.agent.run_planner_decompose", lambda **kw: dec)
    monkeypatch.setattr("ai_coder.agent.run_agent_decompose", fake_exec)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "goal", str(project), "--plan", "--tool-loop"],
        input="y\n",
    )
    assert result.exit_code == 0, result.stdout
    assert captured.get("plan") is dec, "должен передать готовый план в run_agent_decompose"


# ---------- agent --chain ----------


def test_chain_requires_tool_loop(tmp_path: Path):
    """--chain без --tool-loop → ошибка."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1.md").write_text("# task\n\nGoal.\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", str(project), "--chain", str(issues)],
    )
    assert result.exit_code != 0
    assert "tool-loop" in result.stdout.lower() or "tool loop" in result.stdout.lower()


def test_chain_and_issue_conflict(tmp_path: Path):
    """--chain + --issue → ошибка."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1.md").write_text("# task\n\nGoal.\n", encoding="utf-8")
    single = tmp_path / "single.md"
    single.write_text("# task\n\nSingle.\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "agent",
            str(project),
            "--chain",
            str(issues),
            "--issue",
            str(single),
            "--tool-loop",
        ],
    )
    assert result.exit_code != 0
    assert "несовместим" in result.stdout.lower() or "conflict" in result.stdout.lower()


def test_chain_and_goal_conflict(tmp_path: Path):
    """--chain + непустой goal (не директория) → ошибка."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1.md").write_text("# task\n\nGoal.\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "agent",
            "это-не-директория",
            # path обязателен: иначе project_root = cwd = реальный main.
            str(project),
            "--chain",
            str(issues),
            "--tool-loop",
        ],
    )
    assert result.exit_code != 0


def test_chain_without_goal_ok(tmp_path: Path, monkeypatch):
    """--chain без goal (пустой первый позиционный) — не ошибка (10.59).

    Раньше: валидация «Нужен goal» срабатывала ДО проверки --chain.
    Теперь: --chain не требует goal, проект берётся вторым позиционным.
    """
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1-a.md").write_text("# task\n\nFirst.\n", encoding="utf-8")

    def fake_loop(**kwargs):
        return ToolLoopResult(
            success=True,
            summary="ok",
            iterations=1,
            total_cost_rub=0.05,
            applied_ops=1,
        )

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "", str(project), "--chain", str(issues), "--tool-loop"],
    )
    # Не должно быть ошибки «Нужен goal» — фикс 10.59.
    assert "Нужен goal" not in result.stdout
    assert result.exit_code == 0, result.stdout


def test_chain_empty_dir(tmp_path: Path):
    """--chain на пустую директорию → ошибка."""
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    issues = tmp_path / "issues"
    issues.mkdir()  # пусто

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", str(project), "--chain", str(issues), "--tool-loop"],
    )
    assert result.exit_code != 0
    assert "*.md" in result.stdout or "нет" in result.stdout.lower()


def test_chain_two_issues_ok(tmp_path: Path, monkeypatch):
    """--chain: 2 issue, обе ✅."""
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1-a.md").write_text("# task\n\nFirst.\n", encoding="utf-8")
    (issues / "2-b.md").write_text("# task\n\nSecond.\n", encoding="utf-8")

    calls: list[str] = []

    def fake_loop(**kwargs):
        calls.append(kwargs["goal"])
        return ToolLoopResult(
            success=True,
            summary="ok",
            iterations=1,
            total_cost_rub=0.05,
            applied_ops=1,
        )

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", str(project), "--chain", str(issues), "--tool-loop"],
    )
    assert result.exit_code == 0, result.stdout
    assert len(calls) == 2, f"должно быть 2 вызова, было {len(calls)}"
    assert "First" in calls[0]
    assert "Second" in calls[1]


def test_chain_zero_ops_not_success(tmp_path: Path, monkeypatch):
    """--chain: tool loop success=True, но applied_ops=0 → НЕ успех."""
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1-a.md").write_text("# task\n\nOnly.\n", encoding="utf-8")

    def fake_loop(**kwargs):
        # 10.31: реальный run_tool_loop(step_type="edit") сам ставит
        # success=False, stopped_reason="no_ops" при 0 правок.
        return ToolLoopResult(
            success=False,
            summary="nothing to do",
            iterations=1,
            total_cost_rub=0.05,
            applied_ops=0,
            stopped_reason="no_ops",
        )

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", str(project), "--chain", str(issues), "--tool-loop"],
    )
    # 0 правок → fail → exit 1
    assert result.exit_code == 1, result.stdout
    assert "провалено: 1" in result.stdout

    # 10.30: в отчёте stopped_reason должен быть "no_ops", не "completed"
    chain_dirs = _chain_task_dirs(project)
    assert len(chain_dirs) == 1
    report = chain_dirs[0] / "report.md"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "no_ops" in content, (
        f"при 0 правок в отчёте должен быть no_ops, а не completed.\n"
        f"Содержимое report.md:\n{content}"
    )
    assert "completed" not in content, "completed не должен встречаться, когда 0 правок"


def test_chain_stop_on_fail(tmp_path: Path, monkeypatch):
    """--chain --stop-on-fail: первая упала → вторая НЕ запущена."""
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1-a.md").write_text("# task\n\nFirst.\n", encoding="utf-8")
    (issues / "2-b.md").write_text("# task\n\nSecond.\n", encoding="utf-8")

    calls: list[str] = []

    def fake_loop(**kwargs):
        calls.append(kwargs["goal"])
        if len(calls) == 1:
            return ToolLoopResult(
                success=False,
                summary="fail",
                iterations=5,
                stopped_reason="max_iterations",
                total_cost_rub=0.1,
            )
        return ToolLoopResult(success=True, summary="ok", iterations=1, total_cost_rub=0.05)

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", str(project), "--chain", str(issues), "--tool-loop"],
    )
    assert result.exit_code != 0  # есть fail → exit 1
    assert len(calls) == 1, "вторая задача НЕ должна запуститься"
    assert "Остановка" in result.stdout


def test_chain_continue_on_fail(tmp_path: Path, monkeypatch):
    """--chain --continue-on-fail: первая упала → вторая запущена."""
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")

    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1-a.md").write_text("# task\n\nFirst.\n", encoding="utf-8")
    (issues / "2-b.md").write_text("# task\n\nSecond.\n", encoding="utf-8")

    calls: list[str] = []

    def fake_loop(**kwargs):
        calls.append(kwargs["goal"])
        if len(calls) == 1:
            return ToolLoopResult(
                success=False,
                summary="fail",
                iterations=5,
                stopped_reason="max_iterations",
                total_cost_rub=0.1,
            )
        return ToolLoopResult(success=True, summary="ok", iterations=1, total_cost_rub=0.05)

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "agent",
            str(project),
            "--chain",
            str(issues),
            "--tool-loop",
            "--continue-on-fail",
        ],
    )
    assert result.exit_code != 0  # fail был → exit 1
    assert len(calls) == 2, "обе задачи должны запуститься"


# ---------- agent --split-goals ----------


def test_split_goals_conflicts_with_chain(tmp_path: Path):
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1.md").write_text("# task\n\nGoal.\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "big", str(project), "--split-goals", "--chain", str(issues)],
    )
    assert result.exit_code != 0
    assert "несовместим" in result.stdout.lower()


def test_split_goals_conflicts_with_tool_loop(tmp_path: Path):
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "big", str(project), "--split-goals", "--tool-loop"],
    )
    assert result.exit_code != 0
    assert "несовместим" in result.stdout.lower()


def test_split_goals_requires_goal(tmp_path: Path):
    from typer.testing import CliRunner

    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "", str(project), "--split-goals"],
    )
    assert result.exit_code != 0
    assert "goal" in result.stdout.lower()


def test_split_goals_ok(tmp_path: Path, monkeypatch):
    from typer.testing import CliRunner

    from ai_coder.agent import SplitGoalsResult, SplitIssue
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()

    sg = SplitGoalsResult(
        issues=[
            SplitIssue(n=1, title="add sub", goal="add sub to calc"),
            SplitIssue(n=2, title="add mul", goal="add mul to calc"),
        ],
        cost_rub=0.04,
    )
    out = project / "issues"
    sg.output_dir = out

    monkeypatch.setattr("ai_coder.agent.run_split_goals", lambda **kw: sg)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["agent", "add sub and mul", str(project), "--split-goals"],
    )
    assert result.exit_code == 0, result.stdout
    assert "Split-goals" in result.stdout
    assert "2" in result.stdout  # число issues
    assert "add sub" in result.stdout


def test_agent_cmd_no_verify_disables_verify_commands(cli_env):
    """--no-verify должен обнулять cfg.agent.verify_commands."""
    captured: dict = {}

    def fake_loop(**kwargs):
        captured["cfg"] = kwargs["cfg"]
        from ai_coder.agent import ToolLoopResult

        return ToolLoopResult(
            success=True,
            summary="stub",
            iterations=1,
            total_cost_rub=0.01,
            applied_ops=1,
        )

    # Подкладываем verify_commands в конфиг — проверим, что --no-verify обнулит
    import yaml

    cfg_data = yaml.safe_load(cli_env["config"].read_text(encoding="utf-8"))
    cfg_data["agent"]["verify_commands"] = ["false"]
    cli_env["config"].write_text(yaml.safe_dump(cfg_data, allow_unicode=True), encoding="utf-8")

    with (
        patch("ai_coder.agent.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.append_usage"),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--tool-loop",
                "--no-verify",
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
            ],
        )

    # CLI мог вернуть код 0 или 1 — важно, что cfg дошёл
    if "cfg" not in captured:
        # Если CLI не дошёл до run_tool_loop (валидация), покажем вывод
        raise AssertionError(
            f"run_tool_loop не вызван.\nexit_code={result.exit_code}\noutput={result.output[:2000]}"
        )

    assert captured["cfg"].agent.verify_commands == [], (
        "--no-verify должен был обнулить verify_commands, "
        f"а там {captured['cfg'].agent.verify_commands}"
    )


# ---------- 10.30: chain-report при полном провале ----------


def _chain_issues(tmp_path: Path) -> Path:
    issues = tmp_path / "issues"
    issues.mkdir()
    (issues / "1-a.md").write_text("# task\n\nFirst.\n", encoding="utf-8")
    (issues / "2-b.md").write_text("# task\n\nSecond.\n", encoding="utf-8")
    return issues


def _chain_task_dirs(project: Path) -> list[Path]:
    """Новый layout: .ai-out/<project>/<date>/<NN>_chain_<dirname>/."""
    return list((project / ".ai-out" / project.name).glob("*/*_chain_*"))


def test_chain_saves_report_on_success(tmp_path: Path, monkeypatch):
    """--chain: обе ✅ → report.md есть, содержит ✅."""
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")
    issues = _chain_issues(tmp_path)

    def fake_loop(**kwargs):
        return ToolLoopResult(
            success=True, summary="ok", iterations=1, total_cost_rub=0.05, applied_ops=1
        )

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    result = CliRunner().invoke(app, ["agent", str(project), "--chain", str(issues), "--tool-loop"])
    assert result.exit_code == 0, result.stdout

    chain_dirs = _chain_task_dirs(project)
    assert len(chain_dirs) == 1, f"ожидалась 1 chain-папка, найдено {len(chain_dirs)}"
    report = chain_dirs[0] / "report.md"
    assert report.exists(), "report.md должен быть создан"
    content = report.read_text(encoding="utf-8")
    assert "✅" in content, "отчёт должен содержать ✅"
    assert "1-a.md" in content
    assert "2-b.md" in content


def test_chain_saves_report_on_all_fail(tmp_path: Path, monkeypatch):
    """--chain: все ❌ → report.md есть, содержит ❌ и stopped_reason."""
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")
    issues = _chain_issues(tmp_path)

    def fake_loop(**kwargs):
        return ToolLoopResult(
            success=False,
            summary="fail",
            iterations=5,
            total_cost_rub=0.03,
            applied_ops=0,
            stopped_reason="max_iterations",
        )

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    # --continue-on-fail, иначе остановится после первой
    result = CliRunner().invoke(
        app,
        [
            "agent",
            str(project),
            "--chain",
            str(issues),
            "--tool-loop",
            "--continue-on-fail",
        ],
    )
    # exit_code=1 — ожидаемо (failed>0)
    assert result.exit_code == 1, result.stdout

    chain_dirs = _chain_task_dirs(project)
    assert len(chain_dirs) == 1, f"ожидалась 1 chain-папка, найдено {len(chain_dirs)}"
    report = chain_dirs[0] / "report.md"
    assert report.exists(), "report.md должен быть создан ДАЖЕ при полном провале"
    content = report.read_text(encoding="utf-8")
    assert "❌" in content, "отчёт должен содержать ❌"
    assert "max_iterations" in content, "отчёт должен содержать stopped_reason"
    assert "провалено: 2" in content, "в шапке — сколько провалено"


def test_chain_saves_report_on_partial_fail(tmp_path: Path, monkeypatch):
    """--chain: 1 ✅, 1 ❌ → report.md есть, содержит обоих."""
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")
    issues = _chain_issues(tmp_path)

    calls: list[str] = []

    def fake_loop(**kwargs):
        calls.append(kwargs["goal"])
        if "First" in kwargs["goal"]:
            return ToolLoopResult(
                success=True, summary="ok", iterations=1, total_cost_rub=0.05, applied_ops=1
            )
        return ToolLoopResult(
            success=False,
            summary="fail",
            iterations=3,
            total_cost_rub=0.02,
            applied_ops=0,
            stopped_reason="verify_failed",
        )

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    result = CliRunner().invoke(
        app,
        [
            "agent",
            str(project),
            "--chain",
            str(issues),
            "--tool-loop",
            "--continue-on-fail",
        ],
    )
    assert result.exit_code == 1, result.stdout

    chain_dirs = _chain_task_dirs(project)
    assert len(chain_dirs) == 1
    report = chain_dirs[0] / "report.md"
    assert report.exists()
    content = report.read_text(encoding="utf-8")
    assert "✅" in content and "❌" in content
    assert "провалено: 1" in content


def test_chain_report_path_in_stdout(tmp_path: Path, monkeypatch):
    """--chain: в консольном выводе есть строка «Отчёт:»."""
    from typer.testing import CliRunner

    from ai_coder.agent import ToolLoopResult
    from ai_coder.cli import app

    project = tmp_path / "proj"
    project.mkdir()
    (project / "x.py").write_text("a = 1\n", encoding="utf-8")
    issues = _chain_issues(tmp_path)

    def fake_loop(**kwargs):
        return ToolLoopResult(
            success=True, summary="ok", iterations=1, total_cost_rub=0.05, applied_ops=1
        )

    monkeypatch.setattr("ai_coder.agent.run_tool_loop", fake_loop)

    result = CliRunner().invoke(app, ["agent", str(project), "--chain", str(issues), "--tool-loop"])
    assert result.exit_code == 0, result.stdout
    assert "Отчёт:" in result.stdout, (
        f"в выводе должна быть строка «Отчёт:», а есть:\n{result.stdout[-1000:]}"
    )


# ---------- D6 #1: self_verify_commands для проекта-цели ----------


def _cli_env_with_verify(cli_env, verify, self_verify, *, self_hosted: bool):
    import yaml

    data = yaml.safe_load(cli_env["config"].read_text(encoding="utf-8"))
    data["agent"]["verify_commands"] = verify
    data["agent"]["self_verify_commands"] = self_verify
    cli_env["config"].write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    if self_hosted:
        pkg = cli_env["project"] / "ai_coder"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("", encoding="utf-8")


def _invoke_tool_loop(cli_env, extra: list[str] | None = None):
    captured: dict = {}

    def fake_loop(**kwargs):
        captured["cfg"] = kwargs["cfg"]
        from ai_coder.agent import ToolLoopResult

        return ToolLoopResult(
            success=True, summary="stub", iterations=1, total_cost_rub=0.01, applied_ops=1
        )

    with (
        patch("ai_coder.agent.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.append_usage"),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--tool-loop",
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                *(extra or []),
            ],
        )
    return captured, result


def test_self_verify_added_for_self_hosted_project(cli_env):
    """D6 #1: проект-цель = ai-coder → добавляется mypy."""
    _cli_env_with_verify(
        cli_env, ["python -m pytest -q"], ["python -m mypy ai_coder"], self_hosted=True
    )
    captured, result = _invoke_tool_loop(cli_env)

    assert "cfg" in captured, result.output[:2000]
    assert captured["cfg"].agent.verify_commands == [
        "python -m pytest -q",
        "python -m mypy ai_coder",
    ]


def test_self_verify_skipped_for_foreign_project(cli_env):
    """D6 #1: чужой проект → self-проверки НЕ добавляются."""
    _cli_env_with_verify(
        cli_env, ["python -m pytest -q"], ["python -m mypy ai_coder"], self_hosted=False
    )
    captured, result = _invoke_tool_loop(cli_env)

    assert "cfg" in captured, result.output[:2000]
    assert captured["cfg"].agent.verify_commands == ["python -m pytest -q"]


def test_explicit_verify_commands_win_over_self(cli_env):
    """D6 #1: --verify-commands переопределяет и self-проверки."""
    _cli_env_with_verify(
        cli_env, ["python -m pytest -q"], ["python -m mypy ai_coder"], self_hosted=True
    )
    captured, result = _invoke_tool_loop(cli_env, extra=["--verify-commands", "ruff check ."])

    assert "cfg" in captured, result.output[:2000]
    assert captured["cfg"].agent.verify_commands == ["ruff check ."]


# ---------- D7 #2: reverse-check по умолчанию в tool loop ----------


def _invoke_tool_loop_kwargs(cli_env, extra: list[str] | None = None):
    """Как _invoke_tool_loop, но перехватывает ВСЕ kwargs run_tool_loop."""
    captured: dict = {}

    def fake_loop(**kwargs):
        captured.update(kwargs)
        from ai_coder.agent import ToolLoopResult

        return ToolLoopResult(
            success=True, summary="stub", iterations=1, total_cost_rub=0.01, applied_ops=1
        )

    with (
        patch("ai_coder.agent.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.append_usage"),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--tool-loop",
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                *(extra or []),
            ],
        )
    return captured, result


def test_reverse_check_on_by_default_in_tool_loop(cli_env):
    """D7 #2: без флага RC включён (tri-state None → авто)."""
    captured, result = _invoke_tool_loop_kwargs(cli_env)

    assert "reverse_check" in captured, result.output[:1500]
    assert captured["reverse_check"] is True


def test_no_reverse_check_disables(cli_env):
    """D7 #2: --no-reverse-check явно выключает."""
    captured, result = _invoke_tool_loop_kwargs(cli_env, ["--no-reverse-check"])

    assert captured.get("reverse_check") is False, result.output[:1500]


def test_explicit_reverse_check_without_tool_loop_errors(tmp_path, cli_env):
    """D7 #2: явный --reverse-check без --tool-loop по-прежнему ошибка."""
    result = runner.invoke(
        app,
        [
            "agent",
            "test goal",
            str(cli_env["project"]),
            "--reverse-check",
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
        ],
    )
    assert result.exit_code == 1
    assert "требует --tool-loop" in result.output


def test_default_reverse_check_without_tool_loop_not_an_error(cli_env):
    """D7 #2: дефолт (None) без --tool-loop НЕ должен давать ошибку RC."""
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
    assert "reverse-check требует" not in result.output


# ---------- D10 (баг B): --max-iterations и лимиты Router ----------


def test_decompose_max_iterations_none_by_default(cli_env):
    """Без --max-iterations в run_agent_decompose уходит None → лимиты Router."""
    captured: dict = {}

    def fake_decompose(**kw):
        captured.update(kw)
        from ai_coder.agent import DecomposeResult, Subtask

        return DecomposeResult(subtasks=[Subtask(n=1, goal="g", type="verify")])

    with patch("ai_coder.agent.run_agent_decompose", side_effect=fake_decompose):
        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--decompose",
                "--tool-loop",
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
            ],
        )

    assert "max_iterations" in captured, result.output[:2000]
    assert captured["max_iterations"] is None


def test_decompose_explicit_max_iterations_passed(cli_env):
    """Явный --max-iterations N доходит до run_agent_decompose как N."""
    captured: dict = {}

    def fake_decompose(**kw):
        captured.update(kw)
        from ai_coder.agent import DecomposeResult, Subtask

        return DecomposeResult(subtasks=[Subtask(n=1, goal="g", type="verify")])

    with patch("ai_coder.agent.run_agent_decompose", side_effect=fake_decompose):
        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--decompose",
                "--tool-loop",
                "--max-iterations",
                "7",
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
            ],
        )

    assert captured.get("max_iterations") == 7, result.output[:2000]


def _tool_loop_iters(cli_env, extra: list[str] | None = None) -> dict:
    captured: dict = {}

    def fake_loop(**kw):
        captured.update(kw)
        from ai_coder.agent import ToolLoopResult

        return ToolLoopResult(
            success=True, summary="stub", iterations=1, total_cost_rub=0.01, applied_ops=1
        )

    with (
        patch("ai_coder.agent.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.append_usage"),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "test goal",
                str(cli_env["project"]),
                "--tool-loop",
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                *(extra or []),
            ],
        )
    captured["_output"] = result.output
    return captured


def test_tool_loop_default_iterations_still_20(cli_env):
    """Без --max-iterations обычный tool loop по-прежнему получает 20."""
    captured = _tool_loop_iters(cli_env)
    assert captured.get("max_iterations") == 20, captured["_output"][:2000]


def test_tool_loop_explicit_iterations_passed(cli_env):
    captured = _tool_loop_iters(cli_env, ["--max-iterations", "5"])
    assert captured.get("max_iterations") == 5, captured["_output"][:2000]
