from __future__ import annotations

import json
from pathlib import Path

from ai_coder.apply import (
    Operation,
    WritePlan,
    apply_plan,
    build_plan,
    check_python_files,
    parse_response,
    rollback,
    validate_operations,
)

# ---------- parse_response ----------


def test_parse_valid_json():
    content = json.dumps(
        {
            "explanation": "add file",
            "operations": [
                {"type": "create_file", "path": "a.py", "content": "x = 1\n"},
            ],
        }
    )
    plan = parse_response(content)
    assert plan.parse_error is None
    assert plan.explanation == "add file"
    assert len(plan.operations) == 1
    assert plan.operations[0].type == "create_file"
    assert plan.operations[0].path == "a.py"


def test_parse_json_in_markdown_fence():
    content = '```json\n{"explanation": "x", "operations": []}\n```'
    plan = parse_response(content)
    assert plan.parse_error is None
    assert plan.explanation == "x"
    assert plan.operations == []


def test_parse_json_with_surrounding_text():
    content = 'Here is the plan:\n{"explanation": "y", "operations": []}\nEnd.'
    plan = parse_response(content)
    assert plan.parse_error is None
    assert plan.explanation == "y"


def test_parse_invalid_json():
    plan = parse_response("not a json at all")
    assert plan.parse_error is not None


def test_parse_unknown_operation_type():
    content = json.dumps(
        {
            "explanation": "",
            "operations": [{"type": "delete_file", "path": "x.py"}],
        }
    )
    plan = parse_response(content)
    assert any("неизвестный type" in p for p in plan.problems)


# ---------- validate_operations ----------


def _plan_with(ops: list[Operation], explanation: str = "") -> WritePlan:
    return WritePlan(explanation=explanation, operations=ops)


def test_validate_create_file_ok(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(type="create_file", path="new.py", content="x = 1\n"),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert plan.problems == []


def test_validate_create_file_exists(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(type="create_file", path="README.md", content="x"),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert any("уже существует" in p for p in plan.problems)


def test_validate_path_escapes_project(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(type="create_file", path="../evil.py", content="x"),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert any("относительным" in p or "вне проекта" in p for p in plan.problems)


def test_validate_blacklist(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(type="create_file", path=".git/hooks/pre-commit", content="x"),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert any("blacklist" in p for p in plan.problems)


def test_validate_edit_file_ok(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(
                type="edit_file",
                path="src/main.py",
                old='    return "world"',
                new='    """docstring"""\n    return "world"',
            ),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert plan.problems == []


def test_validate_edit_file_old_not_found(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(
                type="edit_file",
                path="src/main.py",
                old="never_was_in_file",
                new="x",
            ),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert any("не найден" in p for p in plan.problems)


def test_validate_edit_file_old_ambiguous(sample_project: Path, minimal_cfg):
    (sample_project / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    plan = _plan_with(
        [
            Operation(type="edit_file", path="dup.py", old="x = 1", new="y = 1"),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert any("неоднозначна" in p for p in plan.problems)


def test_validate_multiple_edits_same_file_ok(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(
                type="edit_file", path="src/main.py", old="def hello():", new="def hello() -> str:"
            ),
            Operation(
                type="edit_file",
                path="src/main.py",
                old='    return "world"',
                new='    return "world!"',
            ),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert plan.problems == []


def test_validate_overlapping_edits_same_file(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(
                type="edit_file",
                path="src/main.py",
                old='def hello():\n    return "world"',
                new='def hello():\n    """doc"""\n    return "world"',
            ),
            Operation(
                type="edit_file",
                path="src/main.py",
                old='    return "world"',
                new='    return "WORLD"',
            ),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert any("пересекается" in p for p in plan.problems)


# ---------- apply_plan / rollback ----------


def test_apply_create_file_and_rollback(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(type="create_file", path="new.py", content="x = 1\n"),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    backup = sample_project / ".ai-out" / "b1"

    applied, errors = apply_plan(plan, sample_project, backup)
    assert errors == []
    assert "new.py" in applied
    assert (sample_project / "new.py").exists()

    rollback(backup, sample_project)
    assert not (sample_project / "new.py").exists()


def test_apply_edit_file_and_rollback(sample_project: Path, minimal_cfg):
    original = (sample_project / "src" / "main.py").read_text(encoding="utf-8")
    plan = _plan_with(
        [
            Operation(
                type="edit_file",
                path="src/main.py",
                old='    return "world"',
                new='    """docstring"""\n    return "world"',
            ),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    backup = sample_project / ".ai-out" / "b2"

    applied, errors = apply_plan(plan, sample_project, backup)
    assert errors == []
    assert "src/main.py" in applied
    after = (sample_project / "src" / "main.py").read_text(encoding="utf-8")
    assert after != original
    assert '"""docstring"""' in after

    rollback(backup, sample_project)
    restored = (sample_project / "src" / "main.py").read_text(encoding="utf-8")
    assert restored == original


def test_apply_multiple_edits_same_file_backup_is_original(sample_project: Path, minimal_cfg):
    """Регрессия: бэкап должен содержать ОРИГИНАЛ, а не промежуточное состояние."""
    original = (sample_project / "src" / "main.py").read_text(encoding="utf-8")
    plan = _plan_with(
        [
            Operation(
                type="edit_file", path="src/main.py", old="def hello():", new="def hello() -> str:"
            ),
            Operation(
                type="edit_file",
                path="src/main.py",
                old='    return "world"',
                new='    return "world!"',
            ),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    backup = sample_project / ".ai-out" / "b3"

    applied, errors = apply_plan(plan, sample_project, backup)
    assert errors == []

    backup_file = backup / "src" / "main.py"
    assert backup_file.exists()
    assert backup_file.read_text(encoding="utf-8") == original

    rollback(backup, sample_project)
    assert (sample_project / "src" / "main.py").read_text(encoding="utf-8") == original


def test_apply_fails_on_invalid_plan(sample_project: Path, minimal_cfg):
    plan = _plan_with(
        [
            Operation(type="create_file", path="README.md", content="x"),
        ]
    )
    validate_operations(plan, sample_project, minimal_cfg)
    assert plan.problems

    backup = sample_project / ".ai-out" / "b4"
    applied, errors = apply_plan(plan, sample_project, backup)
    assert applied == []
    assert errors


def test_check_python_files_ok(sample_project: Path):
    assert check_python_files(["src/main.py"], sample_project) == []


def test_check_python_files_broken(sample_project: Path):
    broken = sample_project / "broken.py"
    broken.write_text("def f(\n", encoding="utf-8")
    errors = check_python_files(["broken.py"], sample_project)
    assert len(errors) == 1
    assert "broken.py" in errors[0]


def test_build_plan_full_cycle(sample_project: Path, minimal_cfg):
    content = json.dumps(
        {
            "explanation": "test",
            "operations": [
                {"type": "create_file", "path": "new.py", "content": "x = 1\n"},
            ],
        }
    )
    plan = build_plan(content, sample_project, minimal_cfg)
    assert plan.parse_error is None
    assert plan.problems == []
    assert plan.valid
    assert "+++ b/new.py" in plan.diff
    assert "+x = 1" in plan.diff


def test_run_verify_commands_success(sample_project: Path):
    from ai_coder.apply import run_verify_commands

    errors = run_verify_commands(
        ["python -c 'print(1)'"],
        sample_project,
        timeout_sec=10,
    )
    assert errors == []


def test_run_verify_commands_failure(sample_project: Path):
    from ai_coder.apply import run_verify_commands

    errors = run_verify_commands(
        ["python -c 'import sys; sys.exit(2)'"],
        sample_project,
        timeout_sec=10,
    )
    assert len(errors) == 1
    assert "exit code: 2" in errors[0]


def test_run_verify_commands_timeout(sample_project: Path):
    from ai_coder.apply import run_verify_commands

    errors = run_verify_commands(
        ["python -c 'import time; time.sleep(5)'"],
        sample_project,
        timeout_sec=1,
    )
    assert len(errors) == 1
    assert "ТАЙМАУТ" in errors[0]


def test_run_verify_commands_empty_list(sample_project: Path):
    from ai_coder.apply import run_verify_commands

    errors = run_verify_commands([], sample_project)
    assert errors == []


def test_run_verify_commands_rejects_blacklist(sample_project: Path):
    """verify_commands с rm отклоняется (blacklist первого токена)."""
    from ai_coder.apply import run_verify_commands

    errors = run_verify_commands(["rm -rf /"], sample_project, timeout_sec=5)
    assert len(errors) == 1
    assert "команда запрещена" in errors[0]
    assert "rm" in errors[0]


def test_run_verify_commands_no_shell_metachars_leak(sample_project: Path):
    """`pytest -q; rm -rf /` НЕ выполняет rm: shlex.split → pytest с аргументом `-q;`."""
    from ai_coder.apply import run_verify_commands

    # pytest, скорее всего, вернёт non-zero (нет тестов / аргумент странный) —
    # главное, что rm НЕ выполняется и в errors нет "rm -rf".
    errors = run_verify_commands(
        ["pytest -q; rm -rf /nonexistent-xyz"],
        sample_project,
        timeout_sec=10,
    )
    # Ошибка есть (pytest не пройдёт), но она про pytest, не про rm.
    assert len(errors) == 1
    assert "rm" not in errors[0] or "pytest" in errors[0]


def test_run_verify_commands_unparseable(sample_project: Path):
    """Некорректные кавычки → ошибка парсинга, не запуск."""
    from ai_coder.apply import run_verify_commands

    errors = run_verify_commands(["python -c 'unclosed"], sample_project, timeout_sec=5)
    assert len(errors) == 1
    assert "распарсить" in errors[0]


# ---------- rollback: удаление пустых каталогов ----------


def test_rollback_removes_empty_dirs(tmp_path: Path, minimal_cfg):
    """apply_plan создаёт a/b/c.py; rollback удаляет файл И каталоги."""
    from ai_coder.apply import Operation, WritePlan, apply_plan, rollback

    # создаём план: create_file a/b/c.py
    plan = WritePlan(
        operations=[
            Operation(type="create_file", path="a/b/c.py", content="x = 1\n"),
        ]
    )

    backup = tmp_path / "backup"
    applied, errors = apply_plan(plan, tmp_path, backup)

    assert errors == [], errors
    assert (tmp_path / "a/b/c.py").exists()
    assert (tmp_path / "a/b").is_dir()

    # rollback
    restored = rollback(backup, tmp_path)
    assert not (tmp_path / "a/b/c.py").exists()
    # ключевое: пустые каталоги удалены
    assert not (tmp_path / "a/b").exists()
    assert not (tmp_path / "a").exists()
    # и в restored есть записи об удалении каталогов
    assert any(r.startswith("-") and r.endswith("/") for r in restored)


def test_rollback_keeps_non_empty_dirs(tmp_path: Path, minimal_cfg):
    """Если в a/b есть ДРУГОЙ файл — rollback НЕ удаляет a/b."""
    from ai_coder.apply import Operation, WritePlan, apply_plan, rollback

    # заранее создаём a/b/keep.py — он не в плане
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "keep.py").write_text("keep\n", encoding="utf-8")

    plan = WritePlan(
        operations=[
            Operation(type="create_file", path="a/b/c.py", content="x = 1\n"),
        ]
    )

    backup = tmp_path / "backup"
    applied, errors = apply_plan(plan, tmp_path, backup)
    assert errors == []

    # rollback
    rollback(backup, tmp_path)

    # c.py удалён, но a/b сохранён (непустой)
    assert not (tmp_path / "a/b/c.py").exists()
    assert (tmp_path / "a/b").is_dir()
    assert (tmp_path / "a/b/keep.py").exists()
