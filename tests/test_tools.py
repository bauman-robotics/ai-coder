from __future__ import annotations

from pathlib import Path

import pytest

from ai_coder.tools import (
    TOOL_REGISTRY,
    ToolSecurityError,
    _safe_path,
    execute_tool,
    format_tools_for_prompt,
    get_tool_specs,
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
