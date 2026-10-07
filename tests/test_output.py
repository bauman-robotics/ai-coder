from __future__ import annotations

from pathlib import Path

import pytest

from ai_coder.apply import Operation, WritePlan
from ai_coder.output import (
    _fmt_float,
    _render_write_section,
    _resolve_output_path,
    render_report,
    save_report,
)

# ---------- _fmt_float ----------

def test_fmt_float_default():
    assert _fmt_float(1.23456789) == "1.234568"
    assert _fmt_float(0.0) == "0.000000"


def test_fmt_float_custom_digits():
    assert _fmt_float(1.5, digits=2) == "1.50"
    assert _fmt_float(123.456, digits=0) == "123"


# ---------- _resolve_output_path ----------

def test_resolve_output_path_with_per_project(tmp_path: Path):
    p = _resolve_output_path(
        project_root=tmp_path / "myproj",
        output_dir=".ai-out",
        per_project_subdir=True,
        filename_pattern="{action}-{timestamp}.md",
        action="greet",
        timestamp="2026-10-07T10-00-00",
    )
    assert p == tmp_path / "myproj" / ".ai-out" / "myproj" / "greet-2026-10-07T10-00-00.md"


def test_resolve_output_path_without_per_project(tmp_path: Path):
    p = _resolve_output_path(
        project_root=tmp_path / "myproj",
        output_dir=".ai-out",
        per_project_subdir=False,
        filename_pattern="{action}-{timestamp}.md",
        action="greet",
        timestamp="T1",
    )
    assert p == tmp_path / "myproj" / ".ai-out" / "greet-T1.md"


# ---------- render_report: базовое (read-действие) ----------

def test_render_report_read_action(fake_action_result):
    result = fake_action_result(action="greet", write_plan=None)
    md = render_report(result)

    assert "# greet" in md
    assert "**Модель:** test-model" in md
    assert "**Глубина:** shallow" in md
    assert "off-peak" in md
    assert "## Расход" in md
    assert "## Ответ модели" in md
    assert "test response" in md
    # нет секции с предложением изменений
    assert "## ⚠️ Предложение изменений" not in md


def test_render_report_with_write_plan(fake_action_result):
    plan = WritePlan(
        explanation="do stuff",
        operations=[Operation(type="create_file", path="x.py", content="y = 1\n")],
        problems=[],
        diff="--- /dev/null\n+++ b/x.py\n+y = 1\n",
        raw_json="{}",
    )
    result = fake_action_result(action="write_readme", write_plan=plan)
    md = render_report(result)

    assert "# write_readme" in md
    assert "## ⚠️ Предложение изменений" in md
    assert "do stuff" in md
    assert "create_file" in md
    assert "x.py" in md
    # НЕ должно быть «## Ответ модели»
    assert "## Ответ модели" not in md


# ---------- render_report: applied_info ----------

def test_render_report_applied_success(fake_action_result):
    plan = WritePlan(
        explanation="",
        operations=[Operation(type="create_file", path="x.py", content="y")],
        problems=[],
        diff="",
        raw_json="",
    )
    result = fake_action_result(action="write_readme", write_plan=plan)

    md = render_report(result, applied_info={
        "applied": 3,
        "errors": [],
        "rolled_back": False,
        "backup_dir": Path("/tmp/backup"),
        "attempts": 1,
        "fix_cost_rub": 0.05,
    })

    assert "✅ применено операций: 3" in md
    assert "/tmp/backup" in md
    assert "Fix-итераций" in md
    assert "0.050000 RUB" in md


def test_render_report_applied_rolled_back(fake_action_result):
    plan = WritePlan(
        explanation="",
        operations=[],
        problems=[],
        diff="",
        raw_json="",
    )
    result = fake_action_result(action="write_readme", write_plan=plan)

    md = render_report(result, applied_info={
        "applied": 0,
        "errors": ["syntax error"],
        "rolled_back": True,
        "backup_dir": Path("/tmp/backup"),
        "attempts": 0,
        "fix_cost_rub": 0.0,
    })

    assert "❌ откат" in md
    assert "**Ошибки:** 1" in md


# ---------- render_report: warnings ----------

def test_render_report_length_warning(fake_action_result):
    from ai_coder.llm import LLMResponse
    llm = LLMResponse(
        content="cut off",
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=100,
        completion_tokens=8000,
        total_tokens=8100,
        duration_ms=1000,
        finish_reason="length",
    )
    result = fake_action_result(action="greet", llm=llm)
    md = render_report(result)

    assert "Ответ модели обрезан" in md
    assert "max_output_tokens" in md


def test_render_report_from_cache(fake_action_result):
    result = fake_action_result(action="greet", from_cache=True)
    md = render_report(result)

    assert "результат из кэша" in md
    assert "стоимость 0" in md


def test_render_report_with_savings_note(fake_action_result):
    from ai_coder.llm import LLMResponse
    llm = LLMResponse(
        content="ok",
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=80,
        prompt_cache_miss_tokens=20,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=1000,
        finish_reason="stop",
    )
    result = fake_action_result(action="greet", llm=llm)
    md = render_report(result)

    assert "Экономия за счёт кэша" in md
    assert "80 hit / 20 miss" in md


# ---------- _render_write_section ----------

def test_render_write_section_basic():
    plan = WritePlan(
        explanation="test explanation",
        operations=[
            Operation(type="create_file", path="a.py", content="x = 1"),
            Operation(type="edit_file", path="b.py", old="x", new="y"),
        ],
        problems=[],
        diff="--- a/b.py\n+++ b/b.py\n-x\n+y\n",
        raw_json='{"explanation": "test"}',
    )
    md = _render_write_section(plan)

    assert "## ⚠️ Предложение изменений" in md
    assert "test explanation" in md
    assert "Операции (2)" in md
    assert "`create_file`" in md
    assert "`edit_file`" in md
    assert "### Diff" in md


def test_render_write_section_with_problems():
    plan = WritePlan(
        explanation="",
        operations=[],
        problems=["path outside project", "old not found"],
        diff="",
        raw_json="",
    )
    md = _render_write_section(plan)

    assert "❌ Проблемы валидации" in md
    assert "path outside project" in md
    assert "old not found" in md
    assert "Операций нет" in md


def test_render_write_section_parse_error():
    plan = WritePlan(
        explanation="",
        operations=[],
        problems=[],
        diff="",
        raw_json="not json",
        parse_error="Invalid JSON at position 0",
    )
    md = _render_write_section(plan)

    assert "❌ Ошибка парсинга JSON" in md
    assert "Invalid JSON" in md


def test_render_write_section_raw_json_too_long():
    plan = WritePlan(
        explanation="",
        operations=[],
        problems=[],
        diff="",
        raw_json="x" * 100_000,
    )
    md = _render_write_section(plan)
    # должно быть обрезано до 50000 символов + пометка
    assert "обрезано" in md


# ---------- save_report ----------

def test_save_report_writes_file(tmp_path: Path, fake_action_result):
    result = fake_action_result(action="greet")
    # подменим root скана
    result.scan.root = tmp_path / "myproj"
    (tmp_path / "myproj").mkdir()

    p = save_report(
        result,
        output_dir=".ai-out",
        per_project_subdir=True,
        filename_pattern="{action}-{timestamp}.md",
        save_raw=False,
    )

    assert p.exists()
    content = p.read_text(encoding="utf-8")
    assert "# greet" in content
    assert "test response" in content


def test_save_report_with_raw(tmp_path: Path, fake_action_result):
    result = fake_action_result(action="greet")
    result.scan.root = tmp_path / "myproj"
    (tmp_path / "myproj").mkdir()

    p = save_report(
        result,
        output_dir=".ai-out",
        per_project_subdir=True,
        filename_pattern="{action}-{timestamp}.md",
        save_raw=True,
    )

    raw = p.with_suffix(p.suffix + ".raw.txt")
    assert raw.exists()
    assert raw.read_text(encoding="utf-8") == "test response"
