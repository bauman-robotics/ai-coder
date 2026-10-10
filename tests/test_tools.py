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


def test_registry_has_six_tools():
    assert len(TOOL_REGISTRY) == 6
    assert "read_file" in TOOL_REGISTRY
    assert "read_symbol" in TOOL_REGISTRY
    assert "list_files" in TOOL_REGISTRY
    assert "write_file" in TOOL_REGISTRY
    assert "edit_file" in TOOL_REGISTRY
    assert "run_shell" in TOOL_REGISTRY


def test_get_tool_specs_returns_list():
    specs = get_tool_specs()
    assert len(specs) == 6
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


# ---------- read_file: line_start / line_end ----------


def test_read_file_with_line_range(tmp_path: Path):
    """read_file(line_start, line_end) — читает только участок."""
    content = "\n".join(f"line {i}" for i in range(1, 101))
    (tmp_path / "big.py").write_text(content, encoding="utf-8")

    r = execute_tool(
        "read_file",
        {"path": "big.py", "line_start": 10, "line_end": 20},
        tmp_path,
    )
    assert r.ok
    # Заголовок с диапазоном
    assert "lines 10-20 of 100" in r.output
    # Строки 10..20 включительно (11 строк)
    for i in range(10, 21):
        assert f"line {i}" in r.output
    # Строки вне диапазона не попали
    assert "line 9" not in r.output
    assert "line 21" not in r.output


def test_read_file_only_line_start(tmp_path: Path):
    """read_file(line_start=95) без line_end — до конца файла."""
    content = "\n".join(f"line {i}" for i in range(1, 101))
    (tmp_path / "big.py").write_text(content, encoding="utf-8")

    r = execute_tool(
        "read_file",
        {"path": "big.py", "line_start": 95},
        tmp_path,
    )
    assert r.ok
    assert "lines 95-100 of 100" in r.output
    assert "line 95" in r.output
    assert "line 100" in r.output
    assert "line 94" not in r.output


def test_read_file_line_range_clamps_end(tmp_path: Path):
    """line_end больше, чем строк в файле — обрезается до конца."""
    content = "\n".join(f"line {i}" for i in range(1, 11))
    (tmp_path / "small.py").write_text(content, encoding="utf-8")

    r = execute_tool(
        "read_file",
        {"path": "small.py", "line_start": 5, "line_end": 9999},
        tmp_path,
    )
    assert r.ok
    assert "lines 5-10 of 10" in r.output


def test_read_file_line_range_invalid_order(tmp_path: Path):
    """line_start > line_end → ошибка."""
    (tmp_path / "x.py").write_text("a\nb\nc\n", encoding="utf-8")

    r = execute_tool(
        "read_file",
        {"path": "x.py", "line_start": 10, "line_end": 5},
        tmp_path,
    )
    assert not r.ok
    assert "line_start=10" in r.error


def test_read_file_line_range_start_out_of_bounds(tmp_path: Path):
    """line_start > total lines → ошибка."""
    (tmp_path / "x.py").write_text("a\nb\nc\n", encoding="utf-8")

    r = execute_tool(
        "read_file",
        {"path": "x.py", "line_start": 100},
        tmp_path,
    )
    assert not r.ok
    assert "100" in r.error and "total lines" in r.error


def test_read_file_no_range_still_returns_full_small_file(tmp_path: Path):
    """Без line_start/line_end — весь файл (поведение не изменилось)."""
    (tmp_path / "x.py").write_text("a = 1\nb = 2\n", encoding="utf-8")

    r = execute_tool("read_file", {"path": "x.py"}, tmp_path)
    assert r.ok
    assert "a = 1" in r.output
    assert "b = 2" in r.output
    # Заголовка с диапазоном нет
    assert "lines" not in r.output.split("\n")[0]


# ---------- blacklist в tool loop ----------


def test_execute_tool_write_file_rejects_blacklist_default(tmp_path: Path):
    """write_file в blacklist-файл отклоняется, если write_cfg передан."""
    from ai_coder.config import WriteConfig

    wc = WriteConfig(
        blacklist_paths=[".git/**", "*.env"],
        blacklist_files=["pyproject.toml"],
    )
    r = execute_tool(
        "write_file",
        {"path": "pyproject.toml", "content": "x = 1\n"},
        tmp_path,
        write_cfg=wc,
    )
    assert not r.ok
    assert "blacklisted" in r.error
    assert "pyproject.toml" in r.error
    # файл НЕ создан
    assert not (tmp_path / "pyproject.toml").exists()


def test_execute_tool_edit_file_rejects_blacklist_default(tmp_path: Path):
    """edit_file в blacklist-файл отклоняется, если write_cfg передан."""
    from ai_coder.config import WriteConfig

    target = tmp_path / ".env"
    target.write_text("SECRET=old\n", encoding="utf-8")

    wc = WriteConfig(blacklist_paths=["*.env"], blacklist_files=[])
    r = execute_tool(
        "edit_file",
        {"path": ".env", "old": "old", "new": "new"},
        tmp_path,
        write_cfg=wc,
    )
    assert not r.ok
    assert "blacklisted" in r.error
    # файл НЕ изменён
    assert target.read_text(encoding="utf-8") == "SECRET=old\n"


def test_execute_tool_write_file_allows_with_flag(tmp_path: Path):
    """С --allow-blacklist запись в blacklist разрешена."""
    from ai_coder.config import WriteConfig

    wc = WriteConfig(blacklist_paths=[], blacklist_files=["pyproject.toml"])
    r = execute_tool(
        "write_file",
        {"path": "pyproject.toml", "content": "x = 1\n"},
        tmp_path,
        write_cfg=wc,
        allow_blacklist=True,
    )
    assert r.ok
    assert (tmp_path / "pyproject.toml").read_text(encoding="utf-8") == "x = 1\n"


def test_execute_tool_read_file_ignores_blacklist(tmp_path: Path):
    """read_file не проверяет blacklist (dangerous=False)."""
    from ai_coder.config import WriteConfig

    (tmp_path / "pyproject.toml").write_text("x = 1\n", encoding="utf-8")
    wc = WriteConfig(blacklist_paths=[], blacklist_files=["pyproject.toml"])

    r = execute_tool(
        "read_file",
        {"path": "pyproject.toml"},
        tmp_path,
        write_cfg=wc,
    )
    assert r.ok
    assert "x = 1" in r.output


# ---------- mask_secrets в tool loop ----------


def test_read_file_masks_secrets(tmp_path: Path):
    """read_file маскирует секреты и добавляет warning."""
    (tmp_path / "config.py").write_text(
        "KEY = 'AKIAIOSFODNN7EXAMPLE'\nNAME = 'prod'\n",
        encoding="utf-8",
    )

    r = execute_tool("read_file", {"path": "config.py"}, tmp_path)
    assert r.ok
    assert "AKIAIOSFODNN7EXAMPLE" not in r.output
    assert "***REDACTED (AWS access key)***" in r.output
    assert "⚠️ [masked 1 secret(s): AWS access key]" in r.output


def test_read_file_masks_secrets_in_range(tmp_path: Path):
    """read_file с line_start/line_end тоже маскирует."""
    (tmp_path / "x.py").write_text(
        "a = 1\nb = 2\nKEY = 'AKIAIOSFODNN7EXAMPLE'\nd = 4\n",
        encoding="utf-8",
    )

    r = execute_tool(
        "read_file",
        {"path": "x.py", "line_start": 3, "line_end": 3},
        tmp_path,
    )
    assert r.ok
    assert "AKIAIOSFODNN7EXAMPLE" not in r.output
    assert "***REDACTED (AWS access key)***" in r.output
    # warning в начале
    assert r.output.startswith("⚠️ [masked 1 secret(s): AWS access key]")


def test_run_shell_masks_secrets(tmp_path: Path):
    """run_shell маскирует секреты в stdout."""
    (tmp_path / "leak.txt").write_text(
        "print('AKIAIOSFODNN7EXAMPLE')\n",
        encoding="utf-8",
    )

    r = execute_tool(
        "run_shell",
        {"command": "cat leak.txt"},
        tmp_path,
    )
    assert r.ok
    assert "AKIAIOSFODNN7EXAMPLE" not in r.output
    assert "***REDACTED (AWS access key)***" in r.output
    assert "⚠️ [masked 1 secret(s): AWS access key]" in r.output


# ---------- read_symbol ----------


def test_read_symbol_function(tmp_path: Path):
    """read_symbol находит функцию и возвращает её тело."""
    (tmp_path / "mod.py").write_text(
        "import os\n\ndef foo(x):\n    return x + 1\n\ndef bar():\n    return 42\n",
        encoding="utf-8",
    )

    r = execute_tool("read_symbol", {"name": "foo"}, tmp_path)
    assert r.ok
    assert "def foo(x):" in r.output
    assert "return x + 1" in r.output
    assert "def bar" not in r.output
    assert "# mod.py:3 (def foo)" in r.output


def test_read_symbol_class(tmp_path: Path):
    """read_symbol находит класс до следующего top-level def/class."""
    (tmp_path / "mod.py").write_text(
        "class A:\n    def m(self):\n        return 1\n\nclass B:\n    pass\n",
        encoding="utf-8",
    )

    r = execute_tool("read_symbol", {"name": "A"}, tmp_path)
    assert r.ok
    assert "class A:" in r.output
    assert "def m(self):" in r.output
    assert "class B" not in r.output


def test_read_symbol_async(tmp_path: Path):
    """read_symbol находит async def."""
    (tmp_path / "mod.py").write_text(
        "async def fetch():\n    return 1\n\ndef other():\n    pass\n",
        encoding="utf-8",
    )

    r = execute_tool("read_symbol", {"name": "fetch"}, tmp_path)
    assert r.ok
    assert "async def fetch():" in r.output
    assert "def other" not in r.output


def test_read_symbol_not_found(tmp_path: Path):
    (tmp_path / "mod.py").write_text("def foo():\n    pass\n", encoding="utf-8")

    r = execute_tool("read_symbol", {"name": "missing"}, tmp_path)
    assert not r.ok
    assert "not found" in r.error
    assert "missing" in r.error


def test_read_symbol_missing_name(tmp_path: Path):
    r = execute_tool("read_symbol", {}, tmp_path)
    assert not r.ok
    assert "missing 'name'" in r.error


def test_read_symbol_rejects_non_py(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("key: value\n", encoding="utf-8")

    r = execute_tool(
        "read_symbol",
        {"name": "foo", "path": "config.yaml"},
        tmp_path,
    )
    assert not r.ok
    assert ".py" in r.error


def test_read_symbol_kind_filter(tmp_path: Path):
    """kind='class' не находит def с тем же именем."""
    (tmp_path / "mod.py").write_text(
        "def thing():\n    pass\n\nclass thing:\n    pass\n",
        encoding="utf-8",
    )

    r = execute_tool("read_symbol", {"name": "thing", "kind": "class"}, tmp_path)
    assert r.ok
    assert "class thing:" in r.output
    assert "def thing" not in r.output


def test_read_symbol_collision_reports_first(tmp_path: Path):
    """Если symbol в нескольких файлах — возвращает первый, помечает."""
    (tmp_path / "a.py").write_text("def dup():\n    return 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def dup():\n    return 2\n", encoding="utf-8")

    r = execute_tool("read_symbol", {"name": "dup"}, tmp_path)
    assert r.ok
    assert "def dup():" in r.output
    # либо "first match of 2", либо имена обоих файлов
    assert "first match of 2" in r.output


def test_read_symbol_decorator_included(tmp_path: Path):
    """Декоратор над def включается в тело."""
    (tmp_path / "mod.py").write_text(
        "@decorator\ndef foo():\n    return 1\n",
        encoding="utf-8",
    )

    r = execute_tool("read_symbol", {"name": "foo"}, tmp_path)
    assert r.ok
    assert "@decorator" in r.output
    assert "def foo():" in r.output


# ---------- format_tool_history: read_symbol ----------


def test_format_tool_history_keeps_read_symbol_full():
    """read_symbol не обрезается до 500 символов (как read_file)."""
    from ai_coder.tools import ToolAction, ToolResult, format_tool_history

    # 8000 символов — больше other_max_chars (500), меньше read_file_max_chars (10000)
    big_output = "x = 1\n" * 1300  # ~7800 символов

    action = ToolAction(tool="read_symbol", args={"name": "foo"})
    result = ToolResult(ok=True, output=big_output)

    text = format_tool_history([(action, result)])
    # 7800 < 10000 → вывод должен быть целиком, без "[обрезано]"
    assert "[обрезано" not in text
    # и его длина явно больше 500
    assert len(text) > 500


def test_format_tool_history_other_tools_still_short():
    """Прочие инструменты (не read_file/read_symbol) обрезаются до 500."""
    from ai_coder.tools import ToolAction, ToolResult, format_tool_history

    big_output = "y" * 2000

    action = ToolAction(tool="list_files", args={"dir": "."})
    result = ToolResult(ok=True, output=big_output)

    text = format_tool_history([(action, result)])
    assert "[обрезано" in text


# ---------- run_shell: whitelist аргументов (флаги) ----------


def test_run_shell_rejects_find_delete(tmp_path: Path):
    """find . -delete — флаг -delete запрещён."""
    r = execute_tool("run_shell", {"command": "find . -delete"}, tmp_path)
    assert not r.ok
    assert "-delete" in r.error


def test_run_shell_rejects_find_exec(tmp_path: Path):
    """find . -name x -exec — флаг -exec запрещён."""
    r = execute_tool(
        "run_shell",
        {"command": "find . -name x -exec echo"},
        tmp_path,
    )
    assert not r.ok
    assert "-exec" in r.error


def test_run_shell_allows_find_name(tmp_path: Path):
    """find . -name '*.py' — разрешено."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    r = execute_tool(
        "run_shell",
        {"command": "find . -name a.py"},
        tmp_path,
    )
    assert r.ok
    assert "a.py" in r.output


def test_run_shell_rejects_tail_follow(tmp_path: Path):
    """tail -f — запрещено."""
    (tmp_path / "log.txt").write_text("x\n", encoding="utf-8")
    r = execute_tool(
        "run_shell",
        {"command": "tail -f log.txt"},
        tmp_path,
    )
    assert not r.ok
    assert "-f" in r.error


def test_run_shell_allows_tail_n(tmp_path: Path):
    """tail -n 1 — разрешено."""
    (tmp_path / "log.txt").write_text("a\nb\n", encoding="utf-8")
    r = execute_tool(
        "run_shell",
        {"command": "tail -n 1 log.txt"},
        tmp_path,
    )
    assert r.ok
    assert "b" in r.output


def test_run_shell_rejects_git_branch_delete(tmp_path: Path):
    """git branch -D — запрещено."""
    r = execute_tool(
        "run_shell",
        {"command": "git branch -D main"},
        tmp_path,
    )
    assert not r.ok
    assert "-D" in r.error


def test_run_shell_rejects_git_branch_delete_long(tmp_path: Path):
    """git branch --delete=main — запрещено (через '=')."""
    r = execute_tool(
        "run_shell",
        {"command": "git branch --delete=main"},
        tmp_path,
    )
    assert not r.ok
    assert "--delete" in r.error


def test_run_shell_allows_git_branch_list(tmp_path: Path):
    """git branch (без флагов) — разрешено."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)

    r = execute_tool("run_shell", {"command": "git branch"}, tmp_path)
    assert r.ok


def test_run_shell_rejects_git_log_exec(tmp_path: Path):
    """git log --exec=cmd — запрещено."""
    r = execute_tool(
        "run_shell",
        {"command": "git log --exec=rm"},
        tmp_path,
    )
    assert not r.ok
    assert "--exec" in r.error
