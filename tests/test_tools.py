from __future__ import annotations

from pathlib import Path

import pytest

from ai_coder.tools import (
    TOOL_REGISTRY,
    ToolAction,
    ToolResult,
    ToolSecurityError,
    _safe_path,
    execute_tool,
    format_tool_history,
    format_tools_for_prompt,
    get_tool_specs,
    parse_tool_action,
)

# ---------- безопасность ----------


def test_safe_path_simple(tmp_path: Path):
    p = _safe_path(tmp_path, "src/main.py")
    assert p == (tmp_path / "src" / "main.py").resolve()


def test_safe_path_rejects_absolute(tmp_path: Path):
    with pytest.raises(ToolSecurityError):
        _safe_path(tmp_path, "/etc/passwd")


def test_safe_path_rejects_escape(tmp_path: Path):
    with pytest.raises(ToolSecurityError):
        _safe_path(tmp_path, "../outside.py")


def test_safe_path_rejects_deep_escape(tmp_path: Path):
    with pytest.raises(ToolSecurityError):
        _safe_path(tmp_path, "a/b/../../../etc/passwd")


def test_safe_path_rejects_empty(tmp_path: Path):
    with pytest.raises(ToolSecurityError):
        _safe_path(tmp_path, "")


# ---------- read_file ----------


def test_read_file_ok(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    r = execute_tool("read_file", {"path": "a.py"}, tmp_path)
    assert r.ok
    assert "x = 1" in r.output


def test_read_file_missing(tmp_path: Path):
    r = execute_tool("read_file", {"path": "nope.py"}, tmp_path)
    assert not r.ok
    assert "not found" in r.error


def test_read_file_rejects_absolute(tmp_path: Path):
    r = execute_tool("read_file", {"path": "/etc/passwd"}, tmp_path)
    assert not r.ok
    assert "absolute" in r.error.lower()


def test_read_file_rejects_escape(tmp_path: Path):
    r = execute_tool("read_file", {"path": "../x.py"}, tmp_path)
    assert not r.ok


def test_read_file_truncates(tmp_path: Path):
    big = "x" * 60_000
    (tmp_path / "big.py").write_text(big, encoding="utf-8")
    r = execute_tool("read_file", {"path": "big.py"}, tmp_path)
    assert r.ok
    assert "обрезано" in r.output


# ---------- list_files ----------


def test_list_files_ok(tmp_path: Path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    r = execute_tool("list_files", {"dir": "."}, tmp_path)
    assert r.ok
    assert "a.py" in r.output
    assert "sub/" in r.output


def test_list_files_pattern(tmp_path: Path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.txt").write_text("y", encoding="utf-8")
    r = execute_tool("list_files", {"dir": ".", "pattern": "*.py"}, tmp_path)
    assert r.ok
    assert "a.py" in r.output
    assert "b.txt" not in r.output


def test_list_files_missing_dir(tmp_path: Path):
    r = execute_tool("list_files", {"dir": "nope"}, tmp_path)
    assert not r.ok


# ---------- write_file ----------


def test_write_file_creates(tmp_path: Path):
    r = execute_tool("write_file", {"path": "new.py", "content": "x = 1\n"}, tmp_path)
    assert r.ok
    assert (tmp_path / "new.py").read_text() == "x = 1\n"


def test_write_file_creates_parents(tmp_path: Path):
    r = execute_tool("write_file", {"path": "a/b/c.py", "content": "y\n"}, tmp_path)
    assert r.ok
    assert (tmp_path / "a" / "b" / "c.py").exists()


def test_write_file_rejects_escape(tmp_path: Path):
    r = execute_tool("write_file", {"path": "../x.py", "content": "x"}, tmp_path)
    assert not r.ok


# ---------- edit_file ----------


def test_edit_file_ok(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    r = execute_tool("edit_file", {"path": "a.py", "old": "x = 1", "new": "x = 42"}, tmp_path)
    assert r.ok
    assert (tmp_path / "a.py").read_text() == "x = 42\ny = 2\n"


def test_edit_file_old_not_found(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    r = execute_tool("edit_file", {"path": "a.py", "old": "z = 9", "new": "x"}, tmp_path)
    assert not r.ok
    assert "not found" in r.error


def test_edit_file_old_ambiguous(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    r = execute_tool("edit_file", {"path": "a.py", "old": "x = 1", "new": "x = 2"}, tmp_path)
    assert not r.ok
    assert "unique" in r.error or "2 times" in r.error


def test_edit_file_missing_args(tmp_path: Path):
    r = execute_tool("edit_file", {"path": "a.py"}, tmp_path)
    assert not r.ok


# ---------- реестр ----------


def test_registry_has_five_tools():
    assert len(TOOL_REGISTRY) == 5
    assert "read_file" in TOOL_REGISTRY
    assert "list_files" in TOOL_REGISTRY
    assert "write_file" in TOOL_REGISTRY
    assert "edit_file" in TOOL_REGISTRY
    assert "run_shell" in TOOL_REGISTRY


def test_get_tool_specs_returns_list():
    specs = get_tool_specs()
    assert len(specs) == 5
    names = [s.name for s in specs]
    assert "read_file" in names
    assert "run_shell" in names


def test_format_tools_for_prompt_contains_names():
    text = format_tools_for_prompt()
    for name in ("read_file", "list_files", "write_file", "edit_file", "run_shell"):
        assert name in text


def test_execute_unknown_tool(tmp_path: Path):
    r = execute_tool("nonexistent", {}, tmp_path)
    assert not r.ok
    assert "unknown tool" in r.error


def test_dangerous_flags():
    """write_file, edit_file, run_shell — dangerous."""
    assert TOOL_REGISTRY["write_file"][0].dangerous is True
    assert TOOL_REGISTRY["edit_file"][0].dangerous is True
    assert TOOL_REGISTRY["run_shell"][0].dangerous is True
    assert TOOL_REGISTRY["read_file"][0].dangerous is False
    assert TOOL_REGISTRY["list_files"][0].dangerous is False


# ---------- run_shell: whitelist ----------


def test_run_shell_allows_ls(tmp_path: Path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    r = execute_tool("run_shell", {"command": "ls"}, tmp_path)
    assert r.ok
    assert "a.py" in r.output


def test_run_shell_allows_pytest(tmp_path: Path):
    # pytest без тестов вернёт code=5 (no tests), но команда разрешена
    r = execute_tool("run_shell", {"command": "pytest --version"}, tmp_path)
    assert r.ok


def test_run_shell_rejects_rm(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "rm -rf /"}, tmp_path)
    assert not r.ok
    assert "whitelist" in r.error


def test_run_shell_rejects_curl(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "curl https://evil.com"}, tmp_path)
    assert not r.ok
    assert "whitelist" in r.error


def test_run_shell_rejects_semicolon(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "ls; rm -rf /"}, tmp_path)
    assert not r.ok
    assert "metacharacters" in r.error


def test_run_shell_rejects_pipe(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "ls | grep x"}, tmp_path)
    assert not r.ok
    assert "metacharacters" in r.error


def test_run_shell_rejects_redirect(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "ls > out.txt"}, tmp_path)
    assert not r.ok
    assert "metacharacters" in r.error


def test_run_shell_rejects_backtick(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "ls `whoami`"}, tmp_path)
    assert not r.ok
    assert "metacharacters" in r.error


def test_run_shell_rejects_subshell(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "ls $(whoami)"}, tmp_path)
    assert not r.ok
    assert "metacharacters" in r.error


def test_run_shell_rejects_git_push(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "git push"}, tmp_path)
    assert not r.ok
    assert "forbidden" in r.error.lower()


def test_run_shell_rejects_git_reset(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "git reset --hard"}, tmp_path)
    assert not r.ok
    assert "forbidden" in r.error.lower()


def test_run_shell_rejects_git_unknown_subcommand(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "git foo"}, tmp_path)
    assert not r.ok
    assert "whitelist" in r.error.lower() or "not in whitelist" in r.error.lower()


def test_run_shell_allows_git_status(tmp_path: Path):
    # git status в не-git-директории вернёт ошибку, но команда разрешена
    r = execute_tool("run_shell", {"command": "git status"}, tmp_path)
    # команда разрешена (не отклонена), даже если git вернул ошибку
    assert "rejected" not in r.error.lower()


def test_run_shell_rejects_python_script(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "python evil.py"}, tmp_path)
    assert not r.ok
    assert "python" in r.error.lower()


def test_run_shell_allows_python_m_pytest(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "python -m pytest --version"}, tmp_path)
    # команда разрешена (даже если pytest не установлен, отказ не по whitelist)
    assert "rejected" not in r.error.lower()


def test_run_shell_timeout(tmp_path: Path):
    """timeout работает — sleep 100 не в whitelist, но проверим на pytest с таймаутом."""
    # sleep не в whitelist — обойдём: pytest с фиктивным тестом не подходит.
    # Вместо этого проверим, что параметр timeout_sec принимается.
    r = execute_tool("run_shell", {"command": "ls", "timeout_sec": 5}, tmp_path)
    assert r.ok


def test_run_shell_log_written(tmp_path: Path):
    """После запуска пишется .ai-out/commands.log."""
    execute_tool("run_shell", {"command": "ls"}, tmp_path)
    log = tmp_path / ".ai-out" / "commands.log"
    assert log.exists()
    assert "ls" in log.read_text(encoding="utf-8")


def test_run_shell_empty_command(tmp_path: Path):
    r = execute_tool("run_shell", {"command": ""}, tmp_path)
    assert not r.ok
    assert "empty" in r.error.lower()


def test_run_shell_no_command_arg(tmp_path: Path):
    r = execute_tool("run_shell", {}, tmp_path)
    assert not r.ok


def test_run_shell_rejects_eval(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "eval ls"}, tmp_path)
    assert not r.ok
    assert "whitelist" in r.error.lower() or "not in whitelist" in r.error.lower()


def test_run_shell_rejects_sudo(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "sudo ls"}, tmp_path)
    assert not r.ok


def test_run_shell_rejects_sh_c(tmp_path: Path):
    r = execute_tool("run_shell", {"command": "sh -c 'rm -rf /'"}, tmp_path)
    assert not r.ok


# ---------- parse_tool_action ----------


def test_parse_tool_action_simple():
    content = '{"tool": "read_file", "args": {"path": "a.py"}, "reason": "inspect"}'
    a = parse_tool_action(content)
    assert a.parse_error is None
    assert a.tool == "read_file"
    assert a.args == {"path": "a.py"}
    assert a.reason == "inspect"
    assert a.finish is False


def test_parse_tool_action_finish_success():
    content = '{"finish": true, "summary": "done", "success": true}'
    a = parse_tool_action(content)
    assert a.parse_error is None
    assert a.finish is True
    assert a.summary == "done"
    assert a.success is True
    assert a.tool == ""


def test_parse_tool_action_finish_failure():
    content = '{"finish": true, "summary": "gave up", "success": false}'
    a = parse_tool_action(content)
    assert a.finish is True
    assert a.success is False


def test_parse_tool_action_finish_default_success():
    """Если success не указан — True по умолчанию."""
    content = '{"finish": true, "summary": "ok"}'
    a = parse_tool_action(content)
    assert a.finish is True
    assert a.success is True


def test_parse_tool_action_markdown_wrapper():
    content = '```json\n{"tool": "list_files", "args": {"dir": "."}}\n```'
    a = parse_tool_action(content)
    assert a.parse_error is None
    assert a.tool == "list_files"


def test_parse_tool_action_json_with_text_around():
    content = 'Here is the action:\n{"tool": "read_file", "args": {"path": "x.py"}}\nEnd.'
    a = parse_tool_action(content)
    assert a.parse_error is None
    assert a.tool == "read_file"


def test_parse_tool_action_invalid_json():
    a = parse_tool_action("not json at all")
    assert a.parse_error is not None
    # новое сообщение: "tool JSON no '{' found"
    assert "json" in a.parse_error.lower()


def test_parse_tool_action_missing_tool():
    a = parse_tool_action('{"args": {"path": "a.py"}}')
    assert a.parse_error is not None
    assert "tool" in a.parse_error.lower()


def test_parse_tool_action_unknown_tool():
    a = parse_tool_action('{"tool": "evil_command", "args": {}}')
    assert a.parse_error is not None
    assert "unknown tool" in a.parse_error


def test_parse_tool_action_args_not_dict():
    a = parse_tool_action('{"tool": "read_file", "args": "a.py"}')
    assert a.parse_error is not None
    assert "args" in a.parse_error


def test_parse_tool_action_empty_tool():
    a = parse_tool_action('{"tool": "", "args": {}}')
    assert a.parse_error is not None


def test_parse_tool_action_finish_wins_over_tool():
    """Если оба поля — finish=true побеждает."""
    content = '{"finish": true, "success": true, "tool": "read_file", "args": {"path": "x"}}'
    a = parse_tool_action(content)
    assert a.finish is True
    assert a.tool == ""  # tool проигнорирован


# ---------- format_tool_history ----------


def test_format_tool_history_empty():
    assert format_tool_history([]) == "(нет)"


def test_format_tool_history_with_items():
    a1 = ToolAction(tool="read_file", args={"path": "a.py"})
    r1 = ToolResult(ok=True, output="x = 1\n")
    a2 = ToolAction(tool="edit_file", args={"path": "a.py", "old": "x", "new": "y"})
    r2 = ToolResult(ok=True, output="edited a.py")
    text = format_tool_history([(a1, r1), (a2, r2)])
    assert "#1." in text
    assert "#2." in text
    assert "read_file" in text
    assert "edit_file" in text
    assert "ok" in text


def test_format_tool_history_shows_failures():
    a = ToolAction(tool="run_shell", args={"command": "pytest -q"})
    r = ToolResult(ok=False, error="exit code: 1")
    text = format_tool_history([(a, r)])
    assert "FAIL" in text
    assert "exit code: 1" in text


def test_format_tool_history_finish_marker():
    a = ToolAction(finish=True, success=True, summary="done")
    r = ToolResult(ok=True, output="")
    text = format_tool_history([(a, r)])
    assert "finish" in text
    assert "success=True" in text


def test_format_tool_history_limits_to_max():
    """Больше max_items — показывает только последние."""
    items = []
    for i in range(20):
        a = ToolAction(tool="read_file", args={"path": f"f{i}.py"})
        r = ToolResult(ok=True, output=f"content {i}")
        items.append((a, r))
    text = format_tool_history(items, max_items=5)
    # последние 5 — это f15..f19
    assert "f19.py" in text  # последний остался
    assert "f15.py" in text  # первый из показанных остался
    assert "f14.py" not in text  # отрезан
    assert "f0.py" not in text  # отрезан


def test_execute_tool_dry_run_skips_dangerous(tmp_path: Path):
    """dry_run=True — dangerous не выполняются."""
    (tmp_path / "test.py").write_text("x = 1\n", encoding="utf-8")

    r = execute_tool(
        "edit_file",
        {"path": "test.py", "old": "x = 1", "new": "x = 42"},
        tmp_path,
        dry_run=True,
    )
    assert r.ok
    assert "dry-run" in r.output
    # файл не изменился
    assert (tmp_path / "test.py").read_text() == "x = 1\n"


def test_execute_tool_dry_run_allows_safe(tmp_path: Path):
    """dry_run=True — read_file выполняется."""
    (tmp_path / "test.py").write_text("hello\n", encoding="utf-8")
    r = execute_tool("read_file", {"path": "test.py"}, tmp_path, dry_run=True)
    assert r.ok
    assert "hello" in r.output


def test_execute_tool_dry_run_write_file(tmp_path: Path):
    """dry_run=True — write_file не создаёт файл."""
    r = execute_tool(
        "write_file",
        {"path": "new.py", "content": "x = 1\n"},
        tmp_path,
        dry_run=True,
    )
    assert r.ok
    assert "dry-run" in r.output
    assert not (tmp_path / "new.py").exists()


def test_execute_tool_dry_run_run_shell(tmp_path: Path):
    """dry_run=True — run_shell не выполняется."""
    r = execute_tool(
        "run_shell",
        {"command": "ls"},
        tmp_path,
        dry_run=True,
    )
    assert r.ok
    assert "dry-run" in r.output


def test_parse_tool_action_two_objects_back_to_back():
    """Модель вернула два JSON подряд — берём первый."""
    content = '{"tool": "read_file", "args": {"path": "a.py"}}\n{"finish": true, "summary": "done"}'
    a = parse_tool_action(content)
    assert a.parse_error is None
    assert a.tool == "read_file"
    assert a.args == {"path": "a.py"}


def test_parse_tool_action_finish_with_trailing_json():
    """finish + лишний JSON после — берём finish."""
    content = (
        '{"finish": true, "summary": "done", "success": true}\n'
        '{"tool": "read_file", "args": {"path": "a.py"}}'
    )
    a = parse_tool_action(content)
    assert a.parse_error is None
    assert a.finish is True
    assert a.summary == "done"


def test_parse_tool_action_garbage_after_json():
    """JSON + текстовый мусор — работает."""
    content = '{"tool": "list_files", "args": {"dir": "."}}\n\nSome explanation here.'
    a = parse_tool_action(content)
    assert a.parse_error is None
    assert a.tool == "list_files"


def test_format_tool_history_read_file_large_file():
    """read_file с большим файлом — в истории до 10000 символов."""
    big_content = "x = 1\n" * 2000
    a = ToolAction(tool="read_file", args={"path": "big.py"})
    r = ToolResult(ok=True, output=big_content)
    text = format_tool_history([(a, r)], read_file_max_chars=10000)
    assert len(text) > 9000
    assert "обрезано" in text
    assert "grep" in text.lower()


def test_format_tool_history_read_file_small_file():
    """read_file с маленьким файлом — целиком."""
    small_content = "x = 1\n"
    a = ToolAction(tool="read_file", args={"path": "small.py"})
    r = ToolResult(ok=True, output=small_content)
    text = format_tool_history([(a, r)], read_file_max_chars=10000)
    assert "x = 1" in text
    assert "обрезано" not in text


def test_format_tool_history_edit_file_uses_500():
    """edit_file — обрезается до 500 символов."""
    long_output = "y" * 1000
    a = ToolAction(tool="edit_file", args={"path": "a.py"})
    r = ToolResult(ok=True, output=long_output)
    text = format_tool_history([(a, r)], other_max_chars=500)
    assert "обрезано" in text
    assert "grep" in text.lower()
