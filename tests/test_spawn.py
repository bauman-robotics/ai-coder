"""Тесты spawn_subagent (Направление 12, D4).

Часть A — схема конфига и валидация (SubagentConfig).
Часть B — ToolSpec, allowlist, секция в промпте.
Часть C/D — добавляются в соответствующих issue.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

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
