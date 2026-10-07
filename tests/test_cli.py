from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ai_coder.cli import app
from ai_coder.config import ActionConfig

runner = CliRunner(env={"COLUMNS": "200"})


# ---------- фикстуры ----------


@pytest.fixture
def cli_files(tmp_path: Path, minimal_cfg):
    """Создаёт на диске config.yaml и prompts.yaml для CLI."""
    import yaml

    config_path = tmp_path / "config.yaml"
    prompts_path = tmp_path / "prompts.yaml"

    # минимальный config.yaml с действиями
    minimal_cfg.actions = {
        "greet": ActionConfig(description="greet desc", prompt="greet", mode="read", enabled=True),
        "write_readme": ActionConfig(
            description="write", prompt="write_readme_json", mode="write", enabled=True
        ),
    }
    config_path.write_text(
        yaml.safe_dump(minimal_cfg.model_dump(), allow_unicode=True), encoding="utf-8"
    )

    # минимальные промпты
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

    return config_path, prompts_path


# ---------- _load: ошибки конфигов ----------


def test_load_missing_config(tmp_path: Path):
    missing = tmp_path / "nope.yaml"
    result = runner.invoke(app, ["actions", "--config", str(missing)])

    assert result.exit_code == 1
    assert "Конфиг не найден" in result.stdout


def test_load_missing_prompts(tmp_path: Path, cli_files):
    config_path, _ = cli_files
    missing_prompts = tmp_path / "missing.yaml"
    result = runner.invoke(
        app,
        [
            "actions",
            "--config",
            str(config_path),
            "--prompts",
            str(missing_prompts),
        ],
    )

    assert result.exit_code == 1
    assert "Промпты не найдены" in result.stdout


# ---------- actions ----------


def test_actions_basic(cli_files):
    config_path, prompts_path = cli_files
    result = runner.invoke(
        app,
        [
            "actions",
            "--config",
            str(config_path),
            "--prompts",
            str(prompts_path),
        ],
    )

    assert result.exit_code == 0
    assert "greet" in result.stdout
    assert "write_readme" in result.stdout
    assert "read" in result.stdout
    assert "write" in result.stdout
    assert "Подсказка" in result.stdout  # напоминание про --verbose


def test_actions_verbose(cli_files, tmp_path: Path):
    config_path, prompts_path = cli_files
    project = tmp_path / "test-project"
    project.mkdir()
    (project / "x.py").write_text("x = 1\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "actions",
            "--config",
            str(config_path),
            "--prompts",
            str(prompts_path),
            "--path",
            str(project),
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert "Оценка действий" in result.stdout
    assert "Файлов в контексте" in result.stdout


def test_actions_verbose_bad_path(cli_files, tmp_path: Path):
    config_path, prompts_path = cli_files
    missing = tmp_path / "no-such-dir"

    result = runner.invoke(
        app,
        [
            "actions",
            "--config",
            str(config_path),
            "--prompts",
            str(prompts_path),
            "--path",
            str(missing),
            "--verbose",
        ],
    )

    assert result.exit_code == 1
    assert "Не директория" in result.stdout


# ---------- usage ----------


def test_usage_empty_journal(cli_files, tmp_path: Path, minimal_cfg):
    config_path, prompts_path = cli_files

    # делаем путь к usage.jsonl "несуществующим" (в tmp)
    minimal_cfg.usage.jsonl = str(tmp_path / "nonexistent" / "usage.jsonl")
    import yaml

    config_path.write_text(
        yaml.safe_dump(minimal_cfg.model_dump(), allow_unicode=True), encoding="utf-8"
    )

    result = runner.invoke(app, ["usage", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Журнал пуст" in result.stdout


def test_usage_with_records(cli_files, tmp_path: Path, minimal_cfg):
    config_path, prompts_path = cli_files

    # создаём usage.jsonl с 2 записями
    jsonl_path = tmp_path / "usage.jsonl"
    records = [
        {
            "ts_utc": "2026-10-07T10:00:00+00:00",
            "action": "greet",
            "project_name": "test",
            "model": "test-model",
            "prompt_tokens": 100,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost_cny": 0.01,
            "cost_rub": 0.12,
            "cost_usd": 0.001,
            "iteration": 0,
        },
        {
            "ts_utc": "2026-10-07T11:00:00+00:00",
            "action": "write_readme",
            "project_name": "test",
            "model": "test-model",
            "prompt_tokens": 200,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 200,
            "completion_tokens": 100,
            "total_tokens": 300,
            "cost_cny": 0.02,
            "cost_rub": 0.25,
            "cost_usd": 0.002,
            "iteration": 0,
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    minimal_cfg.usage.jsonl = str(jsonl_path)
    import yaml

    config_path.write_text(
        yaml.safe_dump(minimal_cfg.model_dump(), allow_unicode=True), encoding="utf-8"
    )

    result = runner.invoke(app, ["usage", "--config", str(config_path)])

    assert result.exit_code == 0
    assert "Запросов" in result.stdout
    assert "2" in result.stdout  # 2 запроса
    assert "greet" in result.stdout
    assert "write_readme" in result.stdout


def test_usage_filter_by_action(cli_files, tmp_path: Path, minimal_cfg):
    config_path, prompts_path = cli_files

    jsonl_path = tmp_path / "usage.jsonl"
    records = [
        {
            "ts_utc": "2026-10-07T10:00:00+00:00",
            "action": "greet",
            "project_name": "p",
            "model": "m",
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
            "cost_rub": 0.12,
            "cost_cny": 0.01,
            "cost_usd": 0.001,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 100,
            "iteration": 0,
        },
        {
            "ts_utc": "2026-10-07T11:00:00+00:00",
            "action": "refactor",
            "project_name": "p",
            "model": "m",
            "prompt_tokens": 200,
            "completion_tokens": 100,
            "total_tokens": 300,
            "cost_rub": 0.25,
            "cost_cny": 0.02,
            "cost_usd": 0.002,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 200,
            "iteration": 0,
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    minimal_cfg.usage.jsonl = str(jsonl_path)
    import yaml

    config_path.write_text(
        yaml.safe_dump(minimal_cfg.model_dump(), allow_unicode=True), encoding="utf-8"
    )

    result = runner.invoke(
        app,
        [
            "usage",
            "--config",
            str(config_path),
            "--action",
            "greet",
        ],
    )

    assert result.exit_code == 0
    assert "greet" in result.stdout
    # refactor отфильтрован
    assert "refactor" not in result.stdout
    assert "1 из 2" in result.stdout


def test_usage_export_json(cli_files, tmp_path: Path, minimal_cfg):
    config_path, prompts_path = cli_files

    jsonl_path = tmp_path / "usage.jsonl"
    record = {
        "ts_utc": "2026-10-07T10:00:00+00:00",
        "action": "greet",
        "project_name": "p",
        "model": "m",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "cost_rub": 0.12,
        "cost_cny": 0.01,
        "cost_usd": 0.001,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 100,
        "iteration": 0,
    }
    jsonl_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    minimal_cfg.usage.jsonl = str(jsonl_path)
    import yaml

    config_path.write_text(
        yaml.safe_dump(minimal_cfg.model_dump(), allow_unicode=True), encoding="utf-8"
    )

    out_file = tmp_path / "export.json"
    result = runner.invoke(
        app,
        [
            "usage",
            "--config",
            str(config_path),
            "--export",
            "json",
            "--out",
            str(out_file),
        ],
    )

    assert result.exit_code == 0
    assert out_file.exists()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["action"] == "greet"


# ---------- backups ----------


def test_backups_empty(tmp_path: Path):
    project = tmp_path / "empty-project"
    project.mkdir()

    result = runner.invoke(app, ["backups", str(project)])

    assert result.exit_code == 0
    assert "Бэкапов нет" in result.stdout


def test_backups_with_data(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    backup = project / ".ai-out" / "proj" / "backup-20261007-120000-attempt0"
    backup.mkdir(parents=True)
    (backup / "file.py").write_text("x = 1\n", encoding="utf-8")
    (backup / "manifest.json").write_text('{"operations": []}', encoding="utf-8")

    result = runner.invoke(app, ["backups", str(project)])

    assert result.exit_code == 0
    assert "backup-20261007-120000-attempt0" in result.stdout


# ---------- rollback ----------


def test_rollback_missing_backup(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    missing_backup = tmp_path / "no-such-backup"

    result = runner.invoke(app, ["rollback", str(missing_backup), str(project), "--yes"])

    assert result.exit_code == 1
    assert "Бэкап не найден" in result.stdout


def test_rollback_success(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    (project / "file.py").write_text("changed\n", encoding="utf-8")

    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "file.py").write_text("original\n", encoding="utf-8")
    (backup / "manifest.json").write_text(
        json.dumps({"operations": [{"type": "edit_file", "path": "file.py"}]}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["rollback", str(backup), str(project), "--yes"])

    assert result.exit_code == 0
    assert "Изменено путей" in result.stdout
    # файл восстановлен
    assert (project / "file.py").read_text(encoding="utf-8") == "original\n"
