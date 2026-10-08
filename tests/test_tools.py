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


def test_registry_has_four_tools():
    assert len(TOOL_REGISTRY) == 4
    assert "read_file" in TOOL_REGISTRY
    assert "list_files" in TOOL_REGISTRY
    assert "write_file" in TOOL_REGISTRY
    assert "edit_file" in TOOL_REGISTRY


def test_get_tool_specs_returns_list():
    specs = get_tool_specs()
    assert len(specs) == 4
    names = [s.name for s in specs]
    assert "read_file" in names


def test_format_tools_for_prompt_contains_names():
    text = format_tools_for_prompt()
    for name in ("read_file", "list_files", "write_file", "edit_file"):
        assert name in text


def test_execute_unknown_tool(tmp_path: Path):
    r = execute_tool("nonexistent", {}, tmp_path)
    assert not r.ok
    assert "unknown tool" in r.error


def test_dangerous_flags():
    """write_file и edit_file должны быть помечены dangerous."""
    assert TOOL_REGISTRY["write_file"][0].dangerous is True
    assert TOOL_REGISTRY["edit_file"][0].dangerous is True
    assert TOOL_REGISTRY["read_file"][0].dangerous is False
    assert TOOL_REGISTRY["list_files"][0].dangerous is False
