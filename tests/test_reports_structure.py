"""Структура отчётов: .ai-out/<project>/<date>/<NN>_<mode>_<slug>/.

Issue 2026-10-17/01_reports-structure.md.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ai_coder.cli import app
from ai_coder.config import ActionConfig
from ai_coder.history import build_command, save_history_entry
from ai_coder.llm import LLMResponse
from ai_coder.pricing import Rate

runner = CliRunner(env={"COLUMNS": "200"})


# ---------- общие фикстуры/хелперы ----------


@pytest.fixture
def project(tmp_path: Path, minimal_cfg):
    """tmp-проект + config.yaml + prompts.yaml для CLI-вызовов."""
    import yaml

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "x.py").write_text("a = 1\n", encoding="utf-8")

    minimal_cfg.actions = {
        "greet": ActionConfig(description="greet", prompt="greet", mode="read", enabled=True)
    }
    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    config_path.write_text(
        yaml.safe_dump(minimal_cfg.model_dump(mode="json"), allow_unicode=True),
        encoding="utf-8",
    )
    prompts_path.write_text(
        yaml.safe_dump(
            {
                "greet": {"system": "S {{depth}}", "user": "U {{files}}"},
                "agent_tool_json": {
                    "system": "S {{tools}}",
                    "user": "G {{goal}} T {{tree}} H {{history}}",
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return {"project": proj, "config": config_path, "prompts": prompts_path}


def _fake_action_result(project: Path):
    from ai_coder.actions import ActionResult
    from ai_coder.scanner import ScanResult

    now = datetime.now(timezone.utc)
    scan = ScanResult(root=project, files={"x.py": "a = 1\n"}, tree="x.py")
    llm = LLMResponse(
        content="answer",
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=500,
        finish_reason="stop",
    )
    return ActionResult(
        action="greet",
        model="test-model",
        depth="shallow",
        scan=scan,
        llm=llm,
        cost_rub=0.25,
        cost_cny=0.02,
        cost_usd=0.003,
        is_peak=False,
        peak_window=None,
        started_at=now,
        finished_at=now,
        write_plan=None,
        from_cache=False,
    )


def _invoke(env: dict, args: list[str]):
    return runner.invoke(
        app,
        [
            *args,
            "--config",
            str(env["config"]),
            "--prompts",
            str(env["prompts"]),
        ],
    )


def _task_dirs(project: Path, mode_slug: str) -> list[Path]:
    base = project / ".ai-out" / project.name
    return sorted(base.glob(f"*/*_{mode_slug}"))


def _commands(project: Path) -> list[Path]:
    day = date.today().isoformat()
    directory = project / "commands" / day
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.txt"))


# ---------- 1. run: report.md в <date>/<NN>_run_<action>/ ----------


def test_run_report_in_date_task_dir(project):
    with patch("ai_coder.cli.run_action", return_value=_fake_action_result(project["project"])):
        result = _invoke(project, ["run", "greet", str(project["project"])])
    assert result.exit_code == 0, result.stdout

    day = date.today().isoformat()
    task_dirs = _task_dirs(project["project"], "run_greet")
    assert len(task_dirs) == 1, f"ожидалась одна папка задачи, есть {task_dirs}"
    task = task_dirs[0]
    assert task.parent.name == day
    assert (task / "report.md").is_file()
    assert not (
        project["project"] / ".ai-out" / project["project"].name / f"{day}/greet.md"
    ).exists()


# ---------- 2. tool-loop: journal внутри <date>/<NN>_tool-loop_<slug>/ ----------


def _finish_response() -> LLMResponse:
    return LLMResponse(
        content='{"finish": true, "summary": "done", "success": true}',
        model="test-model",
        prompt_tokens=10,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        duration_ms=10,
        finish_reason="stop",
    )


def test_tool_loop_journal_in_date_task_dir(sample_project, minimal_cfg, prompts_cfg):
    from ai_coder.agent import run_tool_loop

    subdir = f"{date.today().isoformat()}/00_tool-loop_test-goal"
    with (
        patch("ai_coder.agent.tool_loop.LLMClient") as MockClient,
        patch("ai_coder.agent.tool_loop.get_rate") as mock_rate,
        patch("ai_coder.agent.tool_loop.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _finish_response()
        result = run_tool_loop(
            goal="test goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=True,
            report_subdir=subdir,
        )

    expected = sample_project / ".ai-out" / sample_project.name / subdir
    assert result.journal_dir == expected
    assert (expected / "report.md").is_file()
    assert (expected / "history.json").is_file()
    assert list(expected.glob("step-*.md"))


def test_tool_loop_report_subdir_with_relative_project_root(
    sample_project, minimal_cfg, prompts_cfg, monkeypatch
):
    """Регрессия: project_root=Path(".") не должен терять имя проекта.

    Path(".").name == "", поэтому старый код писал в .ai-out/<date>/...,
    а не в .ai-out/<project>/<date>/....
    """
    from ai_coder.agent import run_tool_loop

    monkeypatch.chdir(sample_project)
    subdir = f"{date.today().isoformat()}/99_tool-loop_test"
    with (
        patch("ai_coder.agent.tool_loop.LLMClient") as MockClient,
        patch("ai_coder.agent.tool_loop.get_rate") as mock_rate,
        patch("ai_coder.agent.tool_loop.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _finish_response()
        result = run_tool_loop(
            goal="test",
            project_root=Path("."),
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_iterations=1,
            report_subdir=subdir,
        )

    expected = sample_project / ".ai-out" / sample_project.name / subdir
    assert result.journal_dir is not None
    assert result.journal_dir.resolve() == expected.resolve()
    assert (expected / "report.md").is_file()
    assert not (sample_project / ".ai-out" / subdir).exists()


def test_agent_tool_loop_report_in_new_layout_no_legacy(project, monkeypatch):
    """Реальный run_tool_loop (fake LLM): report.md в новом layout, не tool-loop-*."""
    monkeypatch.chdir(project["project"])
    with (
        patch("ai_coder.agent.tool_loop.LLMClient") as MockClient,
        patch("ai_coder.agent.tool_loop.get_rate") as mock_rate,
        patch("ai_coder.agent.tool_loop.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _finish_response()
        result = _invoke(project, ["agent", "test goal", ".", "--tool-loop"])

    assert result.exit_code == 0, result.stdout
    task = _task_dirs(project["project"], "tool-loop_test-goal")[0]
    assert (task / "goal.txt").is_file()
    assert (task / "report.md").is_file()
    assert list(task.glob("step-*.md"))
    assert not list((project["project"] / ".ai-out" / project["project"].name).glob("tool-loop-*"))


def test_run_report_with_relative_path(project, monkeypatch):
    """`run greet .` (cwd=проект) пишет report.md в новую папку, не greet-<ts>.md."""
    monkeypatch.chdir(project["project"])
    with patch("ai_coder.cli.run_action", return_value=_fake_action_result(project["project"])):
        result = _invoke(project, ["run", "greet", "."])
    assert result.exit_code == 0, result.stdout

    task = _task_dirs(project["project"], "run_greet")[0]
    assert (task / "goal.txt").is_file()
    assert (task / "report.md").is_file()
    base = project["project"] / ".ai-out" / project["project"].name
    assert not list(base.glob("greet-*.md"))

    # Команда в commands/<date>/<NN>_greet.txt создана и совпадает с goal.txt.
    cmds = _commands(project["project"])
    assert len(cmds) == 1
    assert cmds[0].name.endswith("_greet.txt")
    assert cmds[0].read_text(encoding="utf-8") == (task / "goal.txt").read_text(encoding="utf-8")
    assert cmds[0].name.split("_", 1)[0] == task.name.split("_", 1)[0]


def test_run_cli_subprocess_creates_commands_and_goal(project):
    """Реальный `python -m ai_coder.cli run greet .`: commands/ + goal.txt.

    API-ключа в subprocess нет, поэтому report.md не появится (ошибка
    после записи истории), но проверяем именно фактический wiring run.
    """
    env = dict(os.environ)
    env.pop("DEEPSEEK_API_KEY", None)
    # Явно фиксируем worktree-пакет: без PYTHONPATH консольный ai-coder
    # может исполнить установленный main-код (у него нет этой истории).
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_coder.cli",
            "run",
            "greet",
            ".",
            "--no-cache",
            "--config",
            str(project["config"]),
            "--prompts",
            str(project["prompts"]),
        ],
        cwd=project["project"],
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "API-ключ" in proc.stdout + proc.stderr

    cmds = _commands(project["project"])
    assert len(cmds) == 1 and cmds[0].name.endswith("_greet.txt")
    task = _task_dirs(project["project"], "run_greet")[0]
    assert (task / "goal.txt").is_file()
    assert cmds[0].name.split("_", 1)[0] == task.name.split("_", 1)[0]


# ---------- 3-4. goal.txt = полная CLI-команда ----------


def test_goal_txt_for_run(project, monkeypatch):
    args = ["run", "greet", str(project["project"])]
    monkeypatch.setattr(sys, "argv", ["ai-coder", *args])

    with patch("ai_coder.cli.run_action", return_value=_fake_action_result(project["project"])):
        result = _invoke(project, args)
    assert result.exit_code == 0, result.stdout

    task = _task_dirs(project["project"], "run_greet")[0]
    expected = "ai-coder run greet " + shlex.quote(str(project["project"]))
    assert (task / "goal.txt").read_text(encoding="utf-8") == expected + "\n"
    # commands/<date>/<NN>_greet.txt — ровно тот же текст
    cmd = _commands(project["project"])[0]
    assert cmd.read_text(encoding="utf-8") == expected + "\n"


def test_goal_txt_for_tool_loop(project, monkeypatch):
    from ai_coder.agent import ToolLoopResult

    args = ["agent", "add feature", str(project["project"]), "--tool-loop"]
    monkeypatch.setattr(sys, "argv", ["ai-coder", *args])

    def fake_loop(**kwargs):
        return ToolLoopResult(
            success=True, summary="ok", iterations=1, total_cost_rub=0.1, applied_ops=1
        )

    with patch("ai_coder.agent.run_tool_loop", fake_loop):
        result = _invoke(project, args)
    assert result.exit_code == 0, result.stdout

    task = _task_dirs(project["project"], "tool-loop_add-feature")[0]
    expected = build_command(args)
    assert (task / "goal.txt").read_text(encoding="utf-8") == expected + "\n"
    assert expected == f"ai-coder agent 'add feature' {project['project']} --tool-loop"


def test_goal_txt_cli_vs_gui(project, monkeypatch):
    """GUI собирает argv, CLI реконструирует из него goal.txt — один формат."""
    from ai_coder.gui import app as gui_app

    gui_cmd = gui_app._build_command(
        goal="add feature",
        path=str(project["project"]),
        mode="tool-loop",
        model="default",
        apply=True,
        commit=False,
        check_mode="normal",
        max_cost_rub="",
        advanced_flags="",
    )
    gui_argv = shlex.split(gui_cmd)[1:]
    cli_argv = gui_app._build_argv(
        goal="add feature",
        path=str(project["project"]),
        mode="tool-loop",
        model="default",
        apply=True,
        commit=False,
        check_mode="normal",
        max_cost_rub="",
        advanced_flags="",
    )[3:]
    assert gui_argv == cli_argv

    from ai_coder.agent import ToolLoopResult

    monkeypatch.setattr(sys, "argv", ["ai-coder", *cli_argv])

    def fake_loop(**kwargs):
        return ToolLoopResult(
            success=True, summary="ok", iterations=1, total_cost_rub=0.1, applied_ops=1
        )

    with patch("ai_coder.agent.run_tool_loop", fake_loop):
        result = _invoke(project, cli_argv)
    assert result.exit_code == 0, result.stdout

    task = _task_dirs(project["project"], "tool-loop_add-feature")[0]
    goal = (task / "goal.txt").read_text(encoding="utf-8")
    # CLI-реконструкция (build_command из sys.argv) == GUI-команда,
    # нормализованная тем же build_command.
    assert goal == build_command(cli_argv) + "\n"


# ---------- 5-6. общий <NN> для commands/ и .ai-out ----------


def test_nn_shared_commands_and_aiout(project):
    """Два прогона в день: один и тот же NN в commands/ и .ai-out."""
    with patch("ai_coder.cli.run_action", return_value=_fake_action_result(project["project"])):
        first = _invoke(project, ["run", "greet", str(project["project"])])
        second = _invoke(project, ["run", "greet", str(project["project"])])
    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout

    cmds = _commands(project["project"])
    task_dirs = _task_dirs(project["project"], "run_greet")
    assert len(cmds) == 2
    assert len(task_dirs) == 2
    nn_cmd = [p.name.split("_", 1)[0] for p in cmds]
    nn_task = [p.name.split("_", 1)[0] for p in task_dirs]
    assert nn_cmd == nn_task, f"NN не совпадает: commands={nn_cmd}, .ai-out={nn_task}"
    # next_history_number исторически начинает с 00 (см. tests/test_history.py).
    assert nn_cmd == ["00", "01"]


def test_nn_increments_within_day(tmp_path: Path):
    first, _ = save_history_entry(tmp_path, "g1", "cmd1", today=date(2026, 1, 2))
    second, _ = save_history_entry(tmp_path, "g2", "cmd2", today=date(2026, 1, 2))
    assert first.name.startswith("00_")
    assert second.name.startswith("01_")


# ---------- 7. autofix/attempt-N внутри папки задачи ----------


def test_autofix_subdir_inside_task(project):
    from ai_coder.agent import ToolLoopResult
    from ai_coder.agent.autofix import run_auto_fix

    task_subdir = f"{date.today().isoformat()}/00_tool-loop_x"
    report_subdir = f"{task_subdir}/autofix"

    def fake_loop(**kwargs):
        sub = kwargs.get("journal_subdir")
        if sub is not None:
            (sub / "tool-loop-ts").mkdir(parents=True, exist_ok=True)
        return ToolLoopResult(success=True, summary="fixed", iterations=1)

    with (
        patch("ai_coder.agent.autofix.run_verify_commands", side_effect=[["error"], []]),
        patch("ai_coder.agent.autofix.run_tool_loop", fake_loop),
    ):
        result = run_auto_fix(
            project_root=project["project"],
            cfg=_cfg_from(project),
            prompts_cfg=_prompts_from(project),
            verify_commands=["true"],
            journal=True,
            report_subdir=report_subdir,
        )

    task = project["project"] / ".ai-out" / project["project"].name / task_subdir
    assert result.success is True
    assert (task / "autofix" / "report.md").is_file()
    assert (task / "autofix" / "attempt-1").is_dir()
    assert not list((project["project"] / ".ai-out" / project["project"].name).glob("autofix-*"))


def _cfg_from(env: dict):
    from ai_coder.config import load_config

    return load_config(env["config"])


def _prompts_from(env: dict):
    from ai_coder.config import load_prompts

    return load_prompts(env["prompts"])


# ---------- 7b. decompose ----------


def test_decompose_report_in_date_task_dir(sample_project, minimal_cfg, prompts_cfg, monkeypatch):
    from ai_coder.agent import DecomposeResult, Subtask, ToolLoopResult, run_agent_decompose

    dec = DecomposeResult(
        explanation="one subtask",
        subtasks=[Subtask(n=1, goal="do one", files=[])],
    )
    subdir = f"{date.today().isoformat()}/00_decompose_test-goal"

    def fake_loop(**kwargs):
        sub = kwargs.get("journal_subdir")
        if sub is not None:
            (sub / "tool-loop-ts").mkdir(parents=True, exist_ok=True)
        return ToolLoopResult(success=True, summary="ok", iterations=1)

    monkeypatch.chdir(sample_project)
    with (
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_tool_loop", fake_loop),
        patch("ai_coder.agent.decomposer.append_usage"),
    ):
        result = run_agent_decompose(
            goal="test goal",
            project_root=Path("."),
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=True,
            report_subdir=subdir,
        )

    expected = sample_project / ".ai-out" / sample_project.name / subdir
    assert result.journal_dir is not None
    assert result.journal_dir.resolve() == expected.resolve()
    assert (expected / "report.md").is_file()
    assert (expected / "subtask-1").is_dir()
    assert not (sample_project / ".ai-out" / subdir).exists()


# ---------- 8. chain ----------


def test_chain_report_in_date_task_dir(project):
    from ai_coder.agent import ToolLoopResult

    issues = project["project"] / "issues"
    issues.mkdir()
    (issues / "1-a.md").write_text("# task\n\nFirst.\n", encoding="utf-8")
    (issues / "2-b.md").write_text("# task\n\nSecond.\n", encoding="utf-8")

    def fake_loop(**kwargs):
        return ToolLoopResult(
            success=True, summary="ok", iterations=1, total_cost_rub=0.05, applied_ops=1
        )

    with patch("ai_coder.agent.run_tool_loop", fake_loop):
        result = _invoke(
            project,
            ["agent", str(project["project"]), "--chain", str(issues), "--tool-loop"],
        )
    assert result.exit_code == 0, result.stdout

    task_dirs = _task_dirs(project["project"], "chain_issues")
    assert len(task_dirs) == 1, task_dirs
    task = task_dirs[0]
    assert (task / "goal.txt").is_file()
    assert (task / "report.md").is_file()
    assert (task / "issues" / "1-a.md").is_file()
    assert (task / "issues" / "2-b.md").is_file()
    assert not list((project["project"] / ".ai-out" / project["project"].name).glob("chain-*"))


# ---------- 9. fix ----------


def test_fix_report_in_date_task_dir(project):
    with patch("ai_coder.agent.autofix.run_verify_commands", return_value=[]):
        result = _invoke(
            project,
            ["fix", str(project["project"]), "--verify", "true"],
        )
    assert result.exit_code == 0, result.stdout

    base = project["project"] / ".ai-out" / project["project"].name
    task_dirs = list(base.glob("*/*_fix_*"))
    assert len(task_dirs) == 1, task_dirs
    task = task_dirs[0]
    assert (task / "goal.txt").is_file()
    assert (task / "report.md").is_file()


# ---------- 10. split-goals: без .ai-out ----------


def test_split_goals_no_aiout_dir(project):
    from ai_coder.agent import SplitGoalsResult, SplitIssue

    sg = SplitGoalsResult(
        issues=[SplitIssue(n=1, title="one", goal="do one")],
        cost_rub=0.01,
        output_dir=project["project"] / "issues",
    )
    with patch("ai_coder.agent.run_split_goals", lambda **kw: sg):
        result = _invoke(project, ["agent", "big task", str(project["project"]), "--split-goals"])
    assert result.exit_code == 0, result.stdout
    assert not (project["project"] / ".ai-out").exists()
    assert len(_commands(project["project"])) == 1


# ---------- 11. legacy + новый layout в /reports ----------


def test_legacy_reports_still_listed(tmp_path: Path, monkeypatch):
    from ai_coder.gui import app as gui_app

    out = tmp_path / ".ai-out"
    legacy = out / "proj" / "agent-2026-01-01T00-00-00"
    legacy.mkdir(parents=True)
    (legacy / "report.md").write_text("# Agent — legacy\n- **Итераций:** 3\n", encoding="utf-8")

    new = out / "proj" / "2026-10-17" / "00_run_greet"
    new.mkdir(parents=True)
    (new / "report.md").write_text("# Greet — new\n- **Итераций:** 1\n", encoding="utf-8")

    monkeypatch.setattr(gui_app, "AI_OUT_DIR", out)
    items = gui_app._collect_journals()
    names = {item["journal"] for item in items}
    assert "agent-2026-01-01T00-00-00" in names
    assert "2026-10-17/00_run_greet" in names
    # Абсолютный путь к папке задачи есть у обеих записей.
    assert all(Path(item["path"]).is_absolute() for item in items)  # type: ignore[arg-type]


# ---------- 12. GUI: кнопка «Скопировать путь» ----------


def test_gui_copy_path_button(tmp_path: Path, monkeypatch):
    from fastapi.testclient import TestClient

    from ai_coder.gui import app as gui_app

    out = tmp_path / ".ai-out"
    task = out / "proj" / "2026-10-17" / "00_run_greet"
    task.mkdir(parents=True)
    (task / "report.md").write_text("# Greet\n\nтекст\n", encoding="utf-8")

    monkeypatch.setattr(gui_app, "AI_OUT_DIR", out)
    client = TestClient(gui_app.app)
    response = client.get("/reports/proj/2026-10-17/00_run_greet")

    assert response.status_code == 200
    assert "Скопировать путь" in response.text
    assert f'data-path="{task.resolve()}"' in response.text

    # Кнопка рядом с #report-link в форме тоже есть (создаётся из JS).
    index = client.get("/")
    assert index.status_code == 200
    assert "Скопировать путь" in index.text
    assert "data-path" in index.text


# ---------- доп.: _newest_report понимает новый layout ----------


def test_newest_report_finds_nested_task(tmp_path: Path, monkeypatch):
    from ai_coder.gui import app as gui_app

    out = tmp_path / ".ai-out"
    task = out / "proj" / "2026-10-17" / "00_run_greet"
    task.mkdir(parents=True)
    (task / "report.md").write_text("# Greet\n", encoding="utf-8")

    monkeypatch.setattr(gui_app, "AI_OUT_DIR", out)
    since = time.time() - 1
    assert gui_app._newest_report(since) == ("proj", "2026-10-17/00_run_greet")
