"""Тесты spawn_subagent (Направление 12, D4).

Часть A — схема конфига и валидация (SubagentConfig).
Часть B — ToolSpec, allowlist, секция в промпте.
Часть C/D — добавляются в соответствующих issue.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from ai_coder.agent.spawn import run_spawn_subagent
from ai_coder.agent.tool_loop import run_tool_loop
from ai_coder.config import AppConfig, SubagentConfig, load_config, load_prompts
from ai_coder.llm import LLMResponse
from ai_coder.pricing import Rate
from ai_coder.tools import (
    TOOL_REGISTRY,
    execute_tool,
    format_tools_for_prompt,
    get_tool_specs,
)

REPO = Path(__file__).resolve().parent.parent

# ---------- A. SubagentConfig + валидация ----------

_EXPLORER = {
    "name": "code-explorer",
    "description": "Ищет определения символов и вызовы. Read-only.",
    "tools": ["read_file", "read_symbol", "list_files", "run_shell"],
    "model": "test-model",
    "max_iterations": 5,
    "instructions": "Отвечай списком файл:строка.",
    "max_cost_rub": 1.0,
}
_TEST_RUNNER = {
    "name": "test-runner",
    "description": "Запускает pytest и возвращает только упавшие тесты.",
    "tools": ["run_shell"],
    "model": "test-model",
    "max_iterations": 3,
    "max_cost_rub": 0.5,
}
_MD_WRITER = {
    "name": "markdown-writer",
    "description": "Пишет и правит markdown-документы.",
    "tools": ["read_file", "write_file"],
    "model": "test-model",
    "max_iterations": 8,
    "max_cost_rub": 2.0,
}


def _cfg_with_subagents(minimal_cfg: AppConfig, subagents: list[dict]) -> AppConfig:
    """Пересобирает конфиг с subagents — с прогоном всех валидаторов."""
    data = minimal_cfg.model_dump()
    data["agent"]["subagents"] = subagents
    return AppConfig.model_validate(data)


def test_subagents_parse_from_yaml(tmp_path, minimal_cfg):
    """3 subagents из примера парсятся из YAML."""
    data = minimal_cfg.model_dump()
    data["agent"]["subagents"] = [_EXPLORER, _TEST_RUNNER, _MD_WRITER]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")

    cfg = load_config(path)

    assert [s.name for s in cfg.agent.subagents] == [
        "code-explorer",
        "test-runner",
        "markdown-writer",
    ]
    explorer = cfg.agent.subagents[0]
    assert explorer.tools == ["read_file", "read_symbol", "list_files", "run_shell"]
    assert explorer.model == "test-model"
    assert explorer.max_iterations == 5
    assert explorer.max_cost_rub == 1.0
    assert explorer.instructions == "Отвечай списком файл:строка."
    # дефолты
    assert cfg.agent.subagent_max_per_task == 3
    assert cfg.agent.subagent_max_total_cost_rub == 3.0
    assert cfg.agent.subagent_default_max_cost_rub == 1.5


def test_subagents_empty_by_default(minimal_cfg):
    """subagents=[] по умолчанию — обратная совместимость."""
    assert minimal_cfg.agent.subagents == []


def test_subagent_defaults():
    s = SubagentConfig(name="explorer", description="d", tools=["read_file"])
    assert s.model is None
    assert s.max_iterations == 5
    assert s.instructions is None
    assert s.max_cost_rub is None


def test_subagent_frozen():
    s = SubagentConfig(name="explorer", description="d", tools=["read_file"])
    with pytest.raises(ValidationError):
        s.name = "other"  # type: ignore[misc]


def test_duplicate_name_raises(minimal_cfg):
    dup = dict(_TEST_RUNNER)
    dup["name"] = "code-explorer"
    with pytest.raises(ValidationError, match="дубликаты имён subagents"):
        _cfg_with_subagents(minimal_cfg, [_EXPLORER, dup])


def test_unknown_tool_raises(minimal_cfg):
    bad = dict(_TEST_RUNNER)
    bad["tools"] = ["run_shell", "no_such_tool"]
    with pytest.raises(ValidationError, match="неизвестные инструменты"):
        _cfg_with_subagents(minimal_cfg, [bad])


def test_spawn_subagent_in_tools_raises(minimal_cfg):
    """depth=1: subagent не может включать spawn_subagent."""
    bad = dict(_TEST_RUNNER)
    bad["tools"] = ["run_shell", "spawn_subagent"]
    with pytest.raises(ValidationError, match=r"depth=1"):
        _cfg_with_subagents(minimal_cfg, [bad])


def test_model_without_pricing_raises(minimal_cfg):
    bad = dict(_TEST_RUNNER)
    bad["model"] = "no-such-model"
    with pytest.raises(ValidationError, match="нет цен для модели"):
        _cfg_with_subagents(minimal_cfg, [bad])


def test_empty_tools_raises(minimal_cfg):
    bad = dict(_TEST_RUNNER)
    bad["tools"] = []
    with pytest.raises(ValidationError, match="не может быть пустым"):
        _cfg_with_subagents(minimal_cfg, [bad])


@pytest.mark.parametrize("bad_name", ["Code-Explorer", "1explorer", "a", "explorer_x", ""])
def test_invalid_name_raises(minimal_cfg, bad_name):
    bad = dict(_TEST_RUNNER)
    bad["name"] = bad_name
    with pytest.raises(ValidationError):
        _cfg_with_subagents(minimal_cfg, [bad])


@pytest.mark.parametrize("bad_iters", [0, 31])
def test_max_iterations_bounds(minimal_cfg, bad_iters):
    bad = dict(_TEST_RUNNER)
    bad["max_iterations"] = bad_iters
    with pytest.raises(ValidationError):
        _cfg_with_subagents(minimal_cfg, [bad])


def test_max_cost_rub_must_be_positive(minimal_cfg):
    bad = dict(_TEST_RUNNER)
    bad["max_cost_rub"] = 0
    with pytest.raises(ValidationError):
        _cfg_with_subagents(minimal_cfg, [bad])


# ---------- B. ToolSpec + allowlist + промпт ----------


def _response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=1,
        finish_reason="stop",
    )


def _run_loop(cfg, prompts_cfg, project_root, responses, **kwargs):
    """Прогон run_tool_loop с замоканными LLM/курсами/usage."""
    with (
        patch("ai_coder.agent.tool_loop.LLMClient") as MockClient,
        patch("ai_coder.agent.tool_loop.get_rate") as mock_rate,
        patch("ai_coder.agent.tool_loop.append_usage"),
        patch("ai_coder.agent.tool_loop.is_peak_now", return_value=(False, None)),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_response(r) for r in responses]
        result = run_tool_loop(
            goal="test goal",
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            **kwargs,
        )
        user_prompt = MockClient.return_value.chat.call_args.kwargs["user"]
    return result, user_prompt


def test_get_tool_specs_allowlist():
    names = [s.name for s in get_tool_specs(["read_file", "run_shell"])]
    assert names == ["read_file", "run_shell"]
    # порядок — как в TOOL_REGISTRY, а не как в allowlist
    names_rev = [s.name for s in get_tool_specs(["run_shell", "read_file"])]
    assert names_rev == ["read_file", "run_shell"]


def test_get_tool_specs_default_is_all():
    assert [s.name for s in get_tool_specs()] == list(TOOL_REGISTRY)


def test_format_tools_for_prompt_allowlist():
    text = format_tools_for_prompt(["read_file"])
    assert "read_file(" in text
    assert "run_shell(" not in text
    assert "spawn_subagent(" not in text


def test_format_tools_for_prompt_default_unchanged():
    """Дефолт None → все инструменты (обратная совместимость)."""
    text = format_tools_for_prompt()
    for name in TOOL_REGISTRY:
        assert f"{name}(" in text


def test_spawn_stub_returns_error(tmp_path):
    """Заглушка в TOOL_REGISTRY не исполняет spawn."""
    r = execute_tool("spawn_subagent", {"name": "x", "goal": "y" * 20}, tmp_path)
    assert r.ok is False
    assert "только внутри tool loop" in r.error


def test_spawn_subagent_absent_without_subagents(minimal_cfg, prompts_cfg, sample_project):
    """subagents=[] → spawn_subagent НЕ рекламируется (реальный промпт)."""
    prompts = load_prompts(REPO / "config" / "prompts.yaml")
    _, user_prompt = _run_loop(
        minimal_cfg,
        prompts,
        sample_project,
        ['{"finish": true, "summary": "d", "success": true}'],
    )
    assert "run_shell(" in user_prompt  # инструменты вообще показаны
    assert "spawn_subagent(" not in user_prompt
    assert "ДОСТУПНЫЕ SUBAGENTS" not in user_prompt


def test_spawn_subagent_present_with_subagents(minimal_cfg, sample_project):
    """С subagents → spawn_subagent и секция есть в промпте (реальный промпт)."""
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER, _TEST_RUNNER])
    prompts = load_prompts(REPO / "config" / "prompts.yaml")
    _, user_prompt = _run_loop(
        cfg,
        prompts,
        sample_project,
        ['{"finish": true, "summary": "d", "success": true}'],
    )
    assert "spawn_subagent(" in user_prompt
    assert "ДОСТУПНЫЕ SUBAGENTS" in user_prompt
    assert "code-explorer" in user_prompt
    assert "test-runner" in user_prompt
    assert "tools: read_file, read_symbol, list_files, run_shell" in user_prompt
    assert "tools: run_shell" in user_prompt


def test_spawn_not_advertised_at_depth(minimal_cfg, sample_project):
    """spawn_depth>0 → subagent не может спавнить (даже если subagents есть)."""
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    prompts = load_prompts(REPO / "config" / "prompts.yaml")
    _, user_prompt = _run_loop(
        cfg,
        prompts,
        sample_project,
        ['{"finish": true, "summary": "d", "success": true}'],
        spawn_depth=1,
    )
    assert "run_shell(" in user_prompt
    assert "spawn_subagent(" not in user_prompt


def test_real_prompts_yaml_renders_without_keyerror(minimal_cfg, sample_project):
    """Интеграция: реальный prompts.yaml (урок D3 — KeyError на {{var}})."""
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    prompts = load_prompts(REPO / "config" / "prompts.yaml")

    result, user_prompt = _run_loop(
        cfg,
        prompts,
        sample_project,
        ['{"finish": true, "summary": "d", "success": true}'],
    )

    assert result.success is True
    # все плейсхолдеры подставлены
    assert "{{" not in user_prompt
    assert "ДОСТУПНЫЕ SUBAGENTS" in user_prompt
    assert "code-explorer" in user_prompt
    # max_spawns подставлен числом (3 по умолчанию)
    assert "не более 3 за задачу" in user_prompt


def test_real_prompts_yaml_renders_without_subagents(minimal_cfg, sample_project):
    """Без subagents реальный prompts.yaml тоже рендерится."""
    prompts = load_prompts(REPO / "config" / "prompts.yaml")
    result, user_prompt = _run_loop(
        minimal_cfg,
        prompts,
        sample_project,
        ['{"finish": true, "summary": "d", "success": true}'],
    )
    assert result.success is True
    assert "{{" not in user_prompt
    assert "spawn_subagent(" not in user_prompt


def test_max_spawns_from_config(minimal_cfg, sample_project):
    """max_spawns берётся из cfg.agent.subagent_max_per_task (не хардкод)."""
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    cfg.agent.subagent_max_per_task = 7
    prompts = load_prompts(REPO / "config" / "prompts.yaml")
    _, user_prompt = _run_loop(
        cfg,
        prompts,
        sample_project,
        ['{"finish": true, "summary": "d", "success": true}'],
    )
    assert "не более 7 за задачу" in user_prompt


def test_allowlist_enforcement_denies_tool(minimal_cfg, prompts_cfg, sample_project):
    """Запрещённый tool → ok=False, файл НЕ создан (enforcement, не промпт)."""
    responses = [
        '{"tool": "write_file", "args": {"path": "denied.txt", "content": "x"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]
    result, _ = _run_loop(
        minimal_cfg,
        prompts_cfg,
        sample_project,
        responses,
        allowed_tools=["read_file"],
    )

    denied_action, denied_result = result.history[0]
    assert denied_action.tool == "write_file"
    assert denied_result.ok is False
    assert "не разрешён" in denied_result.error
    assert not (sample_project / "denied.txt").exists()


def test_allowlist_allows_listed_tool(minimal_cfg, prompts_cfg, sample_project):
    responses = [
        '{"tool": "list_files", "args": {"dir": "."}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]
    result, _ = _run_loop(
        minimal_cfg,
        prompts_cfg,
        sample_project,
        responses,
        allowed_tools=["list_files"],
    )
    assert result.history[0][1].ok is True


# ---------- C. Исполнение spawn ----------


def _parent_ctx(cfg, prompts_cfg, project_root, **over):
    """Собирает _ToolLoopCtx родителя для прямых тестов run_spawn_subagent."""
    from ai_coder.agent.tool_loop import _ToolLoopCtx
    from ai_coder.scanner import scan_project_metadata

    ctx = _ToolLoopCtx(
        goal=over.pop("goal", "большая задача родителя целиком"),
        project_root=project_root,
        cfg=cfg,
        prompts_cfg=prompts_cfg,
        client=None,
        model=cfg.api.model,
        depth="normal",
        extra_exclude=None,
        max_iterations=5,
        max_cost_rub=over.pop("max_cost_rub", 10.0),
        dry_run=over.pop("dry_run", False),
        dry_read=over.pop("dry_read", False),
        interactive=over.pop("interactive", False),
        auto_commit=False,
        allow_blacklist=False,
        verify_commands=over.pop("verify_commands", None),
        step_type=None,
        reverse_check=False,
        feedback_section="",
        subagents_section="",
        allowed_tools=frozenset(TOOL_REGISTRY),
        subagents_by_name={s.name: s for s in cfg.agent.subagents},
        spawn_depth=over.pop("spawn_depth", 0),
        max_spawns=over.pop("max_spawns", 3),
        usage_action_prefix="agent",
        prompt_entry=prompts_cfg.get("agent_tool_json"),
        tools_block="",
        scan_meta=scan_project_metadata(project_root, cfg.scanning),
    )
    for k, v in over.items():
        setattr(ctx, k, v)
    return ctx


def _child_result(**over):
    from ai_coder.agent.models import ToolLoopResult

    base = dict(
        success=True,
        summary="нашёл 3 вызова",
        iterations=2,
        total_cost_rub=0.4,
        total_cost_cny=0.03,
        total_cost_usd=0.004,
        applied_ops=0,
        read_ops=3,
        stopped_reason="completed",
    )
    base.update(over)
    return ToolLoopResult(**base)


GOAL = "найди все вызовы _collect_diff в ai_coder/"


def test_spawn_passes_props_to_child(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _child_result()

    with patch("ai_coder.agent.spawn.run_tool_loop", fake):
        r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert r.ok is True
    assert captured["allowed_tools"] == _EXPLORER["tools"]
    assert captured["spawn_depth"] == 1
    assert captured["usage_action_prefix"] == "agent:spawn:code-explorer"
    assert captured["model"] == "test-model"
    assert captured["max_iterations"] == 5
    assert captured["max_cost_rub"] == 1.0  # spec.max_cost_rub
    assert captured["verify_commands"] == []  # read-only → pytest не нужен
    assert captured["dry_run"] is False
    assert captured["dry_read"] is False
    assert captured["allow_blacklist"] is False
    assert captured["journal_subdir"] is None  # у родителя journal=False
    assert captured["project_root"] == sample_project
    assert "code-explorer" in r.output and "✅" in r.output


def test_spawn_sums_cost_and_counters(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)
    ctx.total_cost_rub = 0.1

    with patch("ai_coder.agent.spawn.run_tool_loop", lambda **kw: _child_result()):
        run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert ctx.total_cost_rub == pytest.approx(0.5)
    assert ctx.total_cost_cny == pytest.approx(0.03)
    assert ctx.total_cost_usd == pytest.approx(0.004)
    assert ctx.spawn_count == 1
    assert ctx.spawn_cost_rub == pytest.approx(0.4)
    # баг 1 (D4 §7): spawn засчитывается родителю как одно продуктивное
    # действие (+1), иначе explorer-родитель не пройдёт _handle_finish.
    assert ctx.read_ops == 1
    assert ctx.applied_ops == 0


def test_spawn_applied_ops_from_child(minimal_cfg, prompts_cfg, sample_project):
    """Ребёнок писал файлы → родитель может finish (step_type=edit)."""
    cfg = _cfg_with_subagents(minimal_cfg, [_MD_WRITER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)

    res = _child_result(applied_ops=4, read_ops=0)
    with patch("ai_coder.agent.spawn.run_tool_loop", lambda **kw: res):
        run_spawn_subagent(ctx, {"name": "markdown-writer", "goal": "запиши README-раздел"})

    assert ctx.applied_ops == 1
    assert ctx.read_ops == 0


def test_spawn_write_spec_inherits_verify(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_MD_WRITER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project, verify_commands=["pytest -q"])
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _child_result()

    with patch("ai_coder.agent.spawn.run_tool_loop", fake):
        run_spawn_subagent(ctx, {"name": "markdown-writer", "goal": "запиши README-раздел"})

    assert captured["verify_commands"] == ["pytest -q"]


def test_spawn_instructions_go_into_goal(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _child_result()

    with patch("ai_coder.agent.spawn.run_tool_loop", fake):
        run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert GOAL in captured["goal"]
    assert "[ИНСТРУКЦИЯ]" in captured["goal"]
    assert "Отвечай списком файл:строка." in captured["goal"]


def test_spawn_journal_subdir_nested(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    parent_journal = sample_project / ".ai-out" / "tool-loop-parent"
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project, journal_dir=parent_journal)
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _child_result()

    with patch("ai_coder.agent.spawn.run_tool_loop", fake):
        run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert captured["journal"] is True
    assert captured["journal_subdir"] == parent_journal / "spawn-code-explorer"


def test_spawn_unknown_name(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)

    r = run_spawn_subagent(ctx, {"name": "nope", "goal": GOAL})

    assert r.ok is False
    assert "unknown subagent" in r.error
    assert "code-explorer" in r.error
    assert ctx.spawn_count == 0


def test_spawn_depth_guard(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project, spawn_depth=1)

    r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert r.ok is False
    assert "depth=1" in r.error


def test_spawn_count_guard(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project, max_spawns=2)
    ctx.spawn_count = 2

    r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert r.ok is False
    assert "spawn-лимит исчерпан (2/2)" in r.error


def test_spawn_interactive_guard(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project, interactive=True)

    r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert r.ok is False
    assert "interactive" in r.error


def test_spawn_budget_fail_closed(minimal_cfg, prompts_cfg, sample_project):
    """cap <= 0 → отказ, run_tool_loop НЕ вызывается."""
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project, max_cost_rub=0.05)
    ctx.total_cost_rub = 0.10  # уже перерасход

    with patch("ai_coder.agent.spawn.run_tool_loop") as mock:
        r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert r.ok is False
    assert "бюджет исчерпан" in r.error
    mock.assert_not_called()


def test_spawn_cap_limits_total_spawn_budget(minimal_cfg, prompts_cfg, sample_project):
    """cap учитывает subagent_max_total_cost_rub - spawn_cost_rub."""
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    cfg.agent.subagent_max_total_cost_rub = 1.0
    cfg.agent.subagent_default_max_cost_rub = 5.0
    spec_no_cap = dict(_EXPLORER)
    spec_no_cap.pop("max_cost_rub")
    cfg = _cfg_with_subagents(cfg, [spec_no_cap])  # type: ignore[arg-type]
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)
    ctx.spawn_cost_rub = 0.75
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return _child_result()

    with patch("ai_coder.agent.spawn.run_tool_loop", fake):
        run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert captured["max_cost_rub"] == pytest.approx(0.25)  # 1.0 - 0.75


def test_spawn_short_goal_rejected(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)

    r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": "коротко"})

    assert r.ok is False
    assert "короткий" in r.error


def test_spawn_parent_goal_rejected(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project, goal="сделай всю работу целиком")

    r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": "  Сделай  всю работу целиком "})

    assert r.ok is False
    assert "совпадает с задачей родителя" in r.error


def test_spawn_child_failure_is_ok_false_with_digest(minimal_cfg, prompts_cfg, sample_project):
    """Провал ребёнка не роняет родителя, но digest явно провальный."""
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)
    failed = _child_result(success=False, stopped_reason="max_iterations", summary="не успел")

    with patch("ai_coder.agent.spawn.run_tool_loop", lambda **kw: failed):
        r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert r.ok is False
    assert "❌" in r.error
    assert "max_iterations" in r.error
    # стоимость всё равно учтена
    assert ctx.spawn_cost_rub == pytest.approx(0.4)


def test_spawn_crash_does_not_raise(minimal_cfg, prompts_cfg, sample_project):
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    ctx = _parent_ctx(cfg, prompts_cfg, sample_project)

    def boom(**kwargs):
        raise RuntimeError("child exploded")

    with patch("ai_coder.agent.spawn.run_tool_loop", boom):
        r = run_spawn_subagent(ctx, {"name": "code-explorer", "goal": GOAL})

    assert r.ok is False
    assert "spawn crashed" in r.error
    assert "child exploded" in r.error


def test_spawn_e2e_via_parent_tool_loop(minimal_cfg, prompts_cfg, sample_project):
    """E2E: родитель вызывает spawn_subagent, получает digest и finish."""
    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER])
    responses = [
        json.dumps(
            {
                "tool": "spawn_subagent",
                "args": {"name": "code-explorer", "goal": GOAL},
                "reason": "нужна разведка",
            }
        ),
        '{"finish": true, "summary": "готово", "success": true}',
    ]

    with patch("ai_coder.agent.spawn.run_tool_loop", lambda **kw: _child_result()):
        result, user_prompt = _run_loop(cfg, prompts_cfg, sample_project, responses)

    assert result.success is True
    spawn_action, spawn_result = result.history[0]
    assert spawn_action.tool == "spawn_subagent"
    assert spawn_result.ok is True
    assert "code-explorer" in spawn_result.output
    # стоимость ребёнка попала в итог родителя
    assert result.total_cost_rub >= 0.4


def test_spawn_dry_run_does_not_write_files(minimal_cfg, prompts_cfg, sample_project):
    """dry_run пробрасывается в ребёнка: файлы НЕ создаются."""
    cfg = _cfg_with_subagents(minimal_cfg, [_MD_WRITER])
    responses = [
        json.dumps(
            {
                "tool": "spawn_subagent",
                "args": {"name": "markdown-writer", "goal": "создай файл spawn_out.txt"},
                "reason": "делегирую",
            }
        ),
        '{"tool": "write_file", "args": {"path": "spawn_out.txt", "content": "hello"}}',
        '{"finish": true, "summary": "записал", "success": true}',
        '{"finish": true, "summary": "готово", "success": true}',
    ]

    result, _ = _run_loop(cfg, prompts_cfg, sample_project, responses, dry_run=True)

    assert result.history[0][1].ok is True
    assert not (sample_project / "spawn_out.txt").exists()


def test_spawn_real_child_writes_when_not_dry_run(minimal_cfg, prompts_cfg, sample_project):
    """Контроль: без dry_run реальный ребёнок пишет файл."""
    cfg = _cfg_with_subagents(minimal_cfg, [_MD_WRITER])
    responses = [
        json.dumps(
            {
                "tool": "spawn_subagent",
                "args": {"name": "markdown-writer", "goal": "создай файл spawn_out.txt"},
                "reason": "делегирую",
            }
        ),
        '{"tool": "write_file", "args": {"path": "spawn_out.txt", "content": "hello"}}',
        '{"finish": true, "summary": "записал", "success": true}',
        '{"finish": true, "summary": "готово", "success": true}',
    ]

    result, _ = _run_loop(cfg, prompts_cfg, sample_project, responses)

    assert result.history[0][1].ok is True
    assert (sample_project / "spawn_out.txt").read_text(encoding="utf-8") == "hello"


# ---------- D. Наблюдаемость ----------


def _spawn_responses(name: str = "markdown-writer") -> list[str]:
    return [
        json.dumps(
            {
                "tool": "spawn_subagent",
                "args": {"name": name, "goal": "создай файл spawn_out.txt"},
                "reason": "делегирую",
            }
        ),
        '{"tool": "write_file", "args": {"path": "spawn_out.txt", "content": "hello"}}',
        '{"finish": true, "summary": "записал", "success": true}',
        '{"finish": true, "summary": "готово", "success": true}',
    ]


def _run_loop_real_usage(cfg, prompts_cfg, project_root, responses, **kwargs):
    """run_tool_loop с РЕАЛЬНЫМ append_usage (пишет usage.jsonl)."""
    with (
        patch("ai_coder.agent.tool_loop.LLMClient") as MockClient,
        patch("ai_coder.agent.tool_loop.get_rate") as mock_rate,
        patch("ai_coder.agent.tool_loop.is_peak_now", return_value=(False, None)),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_response(r) for r in responses]
        return run_tool_loop(
            goal="test goal",
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            **kwargs,
        )


def _read_usage(cfg, project_root):
    path = project_root / cfg.usage.jsonl
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_usage_action_prefix_attribution(minimal_cfg, prompts_cfg, sample_project):
    """Запросы subagent'а отличимы в usage.jsonl от запросов родителя."""
    cfg = _cfg_with_subagents(minimal_cfg, [_MD_WRITER])

    result = _run_loop_real_usage(
        cfg, prompts_cfg, sample_project, _spawn_responses(), journal=False
    )

    assert result.success is True
    records = _read_usage(cfg, sample_project)
    actions = [r["action"] for r in records]
    print("\nusage actions:", actions)

    # родитель
    assert "agent:tool0" in actions or "agent:tool1" in actions
    # subagent — своя категория
    child = [r for r in records if r["action"].startswith("agent:spawn:markdown-writer:tool")]
    assert child, actions
    assert child[0]["parent_action"] == "agent:spawn:markdown-writer"
    assert child[0]["model"] == "test-model"
    # родительская запись не помечена как spawn
    parent = [
        r
        for r in records
        if r["action"] in ("agent:tool0", "agent:tool1") and r["parent_action"] == "agent"
    ]
    assert parent, records


def test_spawn_journal_nested_on_disk(minimal_cfg, prompts_cfg, sample_project):
    """Журнал subagent'а лежит ВНУТРИ родительского: spawn-<name>/tool-loop-<ts>/."""
    cfg = _cfg_with_subagents(minimal_cfg, [_MD_WRITER])

    with patch("ai_coder.agent.tool_loop.append_usage"):
        result = _run_loop_real_usage(
            cfg, prompts_cfg, sample_project, _spawn_responses(), journal=True
        )

    assert result.success is True
    base = sample_project / cfg.output.dir / sample_project.name
    nested = list(base.glob("tool-loop-*/spawn-markdown-writer/tool-loop-*"))
    assert nested, [str(p) for p in base.glob("tool-loop-*")]
    # в журнале ребёнка есть шаги
    assert list(nested[0].glob("step-*.md")) or list(nested[0].glob("*.md"))


# ---------- D6 #3: правило «когда делегировать» в секции ----------


def test_build_subagents_section_has_delegation_guidance(minimal_cfg):
    """D6 #3: без явного правила модель не делегирует даже на большой задаче.

    Эксперимент D6 (scripts/d6_delegation_ab.py): со старым текстом секции
    делегирование на задаче с 30 файлами — 0/3, с новым — 3/3.
    """
    from ai_coder.agent.spawn import build_subagents_section

    cfg = _cfg_with_subagents(minimal_cfg, [_EXPLORER, _TEST_RUNNER])
    section = build_subagents_section(cfg.agent.subagents)

    assert "Делегируй, когда" in section
    assert "НЕ делегируй мелочи" in section
    # роли по-прежнему перечислены
    assert "code-explorer" in section
    assert "test-runner" in section
    assert "tools: run_shell" in section


def test_build_subagents_section_empty_without_subagents():
    from ai_coder.agent.spawn import build_subagents_section

    assert build_subagents_section([]) == ""


# ---------- D11 (#5): непустой digest при обрыве до finish ----------


def _spec():
    return SubagentConfig(name="test-runner", description="тесты", tools=["run_shell"])


def test_digest_not_empty_when_max_iterations():
    """#5: при max_iterations summary ребёнка пуст — родитель не знал, что упало.

    Выжимка должна объяснять причину остановки сама.
    """
    from ai_coder.agent.models import ToolLoopResult
    from ai_coder.agent.spawn import summarize_subagent_result
    from ai_coder.tools import ToolAction, ToolResult

    res = ToolLoopResult(
        success=False,
        summary="",  # именно так приходит обрыв до finish
        iterations=3,
        stopped_reason="max_iterations",
        total_cost_rub=0.5,
        history=[
            (
                ToolAction(tool="run_shell", args={"command": "pytest -q"}, reason="r"),
                ToolResult(ok=True, output="1 passed"),
            )
        ],
    )

    digest = summarize_subagent_result(_spec(), res)

    assert "summary: остановлено: max_iterations" in digest
    assert "max_iterations" in digest
    assert "run_shell" in digest  # последний шаг
    assert "остановлено:" in digest


def test_digest_reports_last_step_failure():
    """Если последний шаг ребёнка упал — это видно в выжимке."""
    from ai_coder.agent.models import ToolLoopResult
    from ai_coder.agent.spawn import summarize_subagent_result
    from ai_coder.tools import ToolAction, ToolResult

    res = ToolLoopResult(
        success=False,
        summary="",
        iterations=1,
        stopped_reason="error",
        total_cost_rub=0.01,
        history=[
            (
                ToolAction(tool="run_shell", args={"command": "pytest -q"}, reason="r"),
                ToolResult(ok=False, error="command not found: pytest"),
            )
        ],
    )

    digest = summarize_subagent_result(_spec(), res)

    assert "command not found: pytest" in digest


def test_digest_keeps_existing_summary():
    """Нормальный finish не переписывается — выжимка как была."""
    from ai_coder.agent.models import ToolLoopResult
    from ai_coder.agent.spawn import summarize_subagent_result

    res = ToolLoopResult(
        success=True,
        summary="всё сделано",
        iterations=2,
        stopped_reason="completed",
        total_cost_rub=0.02,
    )

    digest = summarize_subagent_result(_spec(), res)

    assert "summary: всё сделано" in digest
    assert "остановлено:" not in digest
