from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ai_coder.cli import app

runner = CliRunner(env={"COLUMNS": "200"})


# ---------- фикстуры ----------


@pytest.fixture
def cli_env(tmp_path: Path, minimal_cfg):
    """Готовит config.yaml + prompts.yaml + пустой проект."""
    import yaml

    from ai_coder.config import ActionConfig

    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"
    project = tmp_path / "proj"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")

    minimal_cfg.actions = {
        "greet": ActionConfig(description="greet", prompt="greet", mode="read", enabled=True),
        "write_readme": ActionConfig(
            description="write", prompt="write_readme_json", mode="write", enabled=True
        ),
    }
    config_path.write_text(
        yaml.safe_dump(minimal_cfg.model_dump(mode="json"), allow_unicode=True), encoding="utf-8"
    )
    prompts_path.write_text(
        yaml.safe_dump(
            {
                "greet": {"system": "S {{depth}}", "user": "U {{files}}"},
                "write_readme_json": {"system": "S", "user": "U {{files}}"},
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


def _fake_action_result(
    project: Path, *, write_plan=None, from_cache: bool = False, finish_reason: str = "stop"
):
    """Собирает ActionResult для мока run_action."""
    from ai_coder.actions import ActionResult
    from ai_coder.llm import LLMResponse
    from ai_coder.scanner import ScanResult

    now = datetime.now(timezone.utc)
    scan = ScanResult(root=project, files={"src/main.py": "x = 1\n"}, tree="src/\n  main.py")
    llm = LLMResponse(
        content="answer",
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=500,
        finish_reason=finish_reason,
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
        write_plan=write_plan,
        from_cache=from_cache,
    )


def _fake_write_plan(valid: bool = True):
    from ai_coder.apply import Operation, WritePlan

    plan = WritePlan(
        explanation="test plan",
        operations=[Operation(type="create_file", path="README.md", content="# test\n")],
        problems=[],
        diff="--- /dev/null\n+++ b/README.md\n+# test\n",
        raw_json="{}",
    )
    if not valid:
        plan.problems = ["test problem"]
    return plan


# ---------- dry-run ----------


def test_run_dry_run(cli_env):
    result = runner.invoke(
        app,
        [
            "run",
            "greet",
            str(cli_env["project"]),
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
            "--dry-run",
            "--depth",
            "shallow",
        ],
    )

    assert result.exit_code == 0
    assert "Оценка (dry-run)" in result.stdout
    assert "Файлов в контексте" in result.stdout
    assert "Оценка стоимости" in result.stdout


def test_run_dry_run_unknown_action(cli_env):
    result = runner.invoke(
        app,
        [
            "run",
            "unknown-action",
            str(cli_env["project"]),
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
            "--dry-run",
        ],
    )

    assert result.exit_code == 1
    assert "не найдено в конфиге" in result.stdout


def test_run_bad_path(cli_env, tmp_path):
    missing = tmp_path / "no-such-dir"
    result = runner.invoke(
        app,
        [
            "run",
            "greet",
            str(missing),
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
        ],
    )

    assert result.exit_code == 1
    assert "Не директория" in result.stdout


# ---------- run с моком run_action ----------


def test_run_success(cli_env):
    with (
        patch("ai_coder.cli.run_action") as mock_run,
        patch("ai_coder.cli.save_report") as mock_save,
    ):
        mock_run.return_value = _fake_action_result(cli_env["project"])
        mock_save.return_value = cli_env["project"] / "report.md"

        result = runner.invoke(
            app,
            [
                "run",
                "greet",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                "--depth",
                "shallow",
            ],
        )

    assert result.exit_code == 0
    assert mock_run.call_count == 1
    assert mock_save.call_count == 1


def test_run_from_cache(cli_env):
    with (
        patch("ai_coder.cli.run_action") as mock_run,
        patch("ai_coder.cli.save_report") as mock_save,
    ):
        mock_run.return_value = _fake_action_result(cli_env["project"], from_cache=True)
        mock_save.return_value = cli_env["project"] / "report.md"

        result = runner.invoke(
            app,
            [
                "run",
                "greet",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
            ],
        )

    assert result.exit_code == 0
    assert "из кэша" in result.stdout.lower()


def test_run_error_handling(cli_env):
    with patch("ai_coder.cli.run_action") as mock_run:
        mock_run.side_effect = RuntimeError("API failed")

        result = runner.invoke(
            app,
            [
                "run",
                "greet",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
            ],
        )

    assert result.exit_code == 1
    assert "Ошибка" in result.stdout


def test_run_length_warning(cli_env):
    with (
        patch("ai_coder.cli.run_action") as mock_run,
        patch("ai_coder.cli.save_report") as mock_save,
    ):
        mock_run.return_value = _fake_action_result(cli_env["project"], finish_reason="length")
        mock_save.return_value = cli_env["project"] / "report.md"

        result = runner.invoke(
            app,
            [
                "run",
                "greet",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
            ],
        )

    assert result.exit_code == 0
    assert "обрезан" in result.stdout


# ---------- run --apply ----------


def test_run_apply_invalid_plan(cli_env):
    invalid_plan = _fake_write_plan(valid=False)

    with (
        patch("ai_coder.cli.run_action") as mock_run,
        patch("ai_coder.cli.save_report") as mock_save,
    ):
        mock_run.return_value = _fake_action_result(cli_env["project"], write_plan=invalid_plan)
        mock_save.return_value = cli_env["project"] / "report.md"

        result = runner.invoke(
            app,
            [
                "run",
                "write_readme",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                "--apply",
                "--yes",
            ],
        )

    assert result.exit_code == 0
    assert "невалиден" in result.stdout.lower()


def test_run_apply_yes_success(cli_env):
    valid_plan = _fake_write_plan(valid=True)

    with (
        patch("ai_coder.cli.run_action") as mock_run,
        patch("ai_coder.cli.save_report") as mock_save,
        patch("ai_coder.cli.apply_plan") as mock_apply,
        patch("ai_coder.cli.check_python_files") as mock_verify,
    ):
        mock_run.return_value = _fake_action_result(cli_env["project"], write_plan=valid_plan)
        mock_save.return_value = cli_env["project"] / "report.md"
        mock_apply.return_value = (["README.md"], [])  # applied, errors
        mock_verify.return_value = []  # no verify errors

        result = runner.invoke(
            app,
            [
                "run",
                "write_readme",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                "--apply",
                "--yes",
            ],
        )

    assert result.exit_code == 0
    assert mock_apply.call_count == 1
    assert "применено операций" in result.stdout.lower() or "Применено" in result.stdout


def test_run_apply_rollback_on_verify_fail(cli_env):
    valid_plan = _fake_write_plan(valid=True)

    with (
        patch("ai_coder.cli.run_action") as mock_run,
        patch("ai_coder.cli.save_report") as mock_save,
        patch("ai_coder.cli.apply_plan") as mock_apply,
        patch("ai_coder.cli.check_python_files") as mock_verify,
        patch("ai_coder.cli.do_rollback") as mock_rollback,
    ):
        mock_run.return_value = _fake_action_result(cli_env["project"], write_plan=valid_plan)
        mock_save.return_value = cli_env["project"] / "report.md"
        mock_apply.return_value = (["README.md"], [])
        mock_verify.return_value = ["syntax error in README.md"]  # verify fail
        mock_rollback.return_value = ["README.md"]

        result = runner.invoke(
            app,
            [
                "run",
                "write_readme",
                str(cli_env["project"]),
                "--config",
                str(cli_env["config"]),
                "--prompts",
                str(cli_env["prompts"]),
                "--apply",
                "--yes",
                "--max-fix-attempts",
                "0",  # отключаем fix, сразу откат
            ],
        )

    assert result.exit_code == 0
    assert mock_rollback.call_count == 1
    assert "откат" in result.stdout.lower() or "Откат" in result.stdout


def test_run_dry_run_with_max_tokens(cli_env):
    """--max-tokens переопределяет max_total_tokens сканера."""
    result = runner.invoke(
        app,
        [
            "run",
            "greet",
            str(cli_env["project"]),
            "--config",
            str(cli_env["config"]),
            "--prompts",
            str(cli_env["prompts"]),
            "--dry-run",
            "--max-tokens",
            "100000",
        ],
    )

    assert result.exit_code == 0
    assert "Оценка (dry-run)" in result.stdout
