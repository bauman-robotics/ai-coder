"""Тесты spawn_subagent (Направление 12, D4).

Часть A — схема конфига и валидация (SubagentConfig).
Часть B/C/D — добавляются в соответствующих issue.
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from ai_coder.config import AppConfig, SubagentConfig, load_config

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
