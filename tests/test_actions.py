from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ai_coder.actions import ActionResult, run_action, run_fix_action
from ai_coder.config import ActionConfig, PromptEntry, PromptsConfig
from ai_coder.llm import LLMResponse


def _make_llm_response(content: str, finish_reason: str = "stop") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=80,
        prompt_cache_miss_tokens=20,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=500,
        finish_reason=finish_reason,
    )


@pytest.fixture
def actions_cfg(minimal_cfg):
    """Дополняем minimal_cfg реальными действиями."""
    minimal_cfg.actions = {
        "greet": ActionConfig(
            description="greet",
            prompt="greet",
            mode="read",
            enabled=True,
        ),
        "write_readme": ActionConfig(
            description="write readme",
            prompt="write_readme_json",
            mode="write",
            enabled=True,
        ),
        "disabled_action": ActionConfig(
            description="off",
            prompt="greet",
            mode="read",
            enabled=False,
        ),
    }
    return minimal_cfg


@pytest.fixture
def actions_prompts():
    return PromptsConfig(prompts={
        "greet": PromptEntry(system="S {{depth}}", user="U {{files}}"),
        "write_readme_json": PromptEntry(system="S", user="U {{files}}"),
        "fix_errors_json": PromptEntry(system="S {{errors}}", user="U {{files}}"),
    })


# ---------- run_action: ошибки на входе ----------

def test_run_action_bad_depth(actions_cfg, actions_prompts, sample_project):
    with pytest.raises(ValueError, match="depth должен быть"):
        run_action(
            action_name="greet",
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
            depth="oops",
        )


def test_run_action_unknown_action(actions_cfg, actions_prompts, sample_project):
    with pytest.raises(KeyError, match="не найдено"):
        run_action(
            action_name="unknown",
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
        )


def test_run_action_disabled(actions_cfg, actions_prompts, sample_project):
    with pytest.raises(RuntimeError, match="отключено"):
        run_action(
            action_name="disabled_action",
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
        )


# ---------- run_action: read-действие ----------

def test_run_action_read_success(actions_cfg, actions_prompts, sample_project):
    with patch("ai_coder.actions.LLMClient") as MockLLM, \
         patch("ai_coder.actions.get_rate") as mock_rate, \
         patch("ai_coder.actions.is_peak_now", return_value=(False, None)):
        from ai_coder.pricing import Rate
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockLLM.return_value.chat.return_value = _make_llm_response("# hello")

        result = run_action(
            action_name="greet",
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
            use_cache=False,  # отключаем кэш для чистоты
        )

    assert isinstance(result, ActionResult)
    assert result.action == "greet"
    assert result.model == "test-model"
    assert result.llm.content == "# hello"
    assert result.write_plan is None
    assert result.from_cache is False
    assert result.cost_rub > 0


# ---------- run_action: write-действие ----------

def test_run_action_write_valid_plan(actions_cfg, actions_prompts, sample_project):
    plan_json = '{"explanation": "test", "operations": [{"type": "create_file", "path": "new.py", "content": "x = 1\\n"}]}'

    with patch("ai_coder.actions.LLMClient") as MockLLM, \
         patch("ai_coder.actions.get_rate") as mock_rate, \
         patch("ai_coder.actions.is_peak_now", return_value=(False, None)):
        from ai_coder.pricing import Rate
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockLLM.return_value.chat.return_value = _make_llm_response(plan_json)

        result = run_action(
            action_name="write_readme",
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
            use_cache=False,
        )

    assert result.write_plan is not None
    assert result.write_plan.valid
    assert len(result.write_plan.operations) == 1
    assert result.write_plan.operations[0].type == "create_file"


def test_run_action_write_invalid_json(actions_cfg, actions_prompts, sample_project):
    with patch("ai_coder.actions.LLMClient") as MockLLM, \
         patch("ai_coder.actions.get_rate") as mock_rate, \
         patch("ai_coder.actions.is_peak_now", return_value=(False, None)):
        from ai_coder.pricing import Rate
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockLLM.return_value.chat.return_value = _make_llm_response("not json at all")

        result = run_action(
            action_name="write_readme",
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
            use_cache=False,
        )

    assert result.write_plan is not None
    assert result.write_plan.parse_error is not None
    assert not result.write_plan.valid


# ---------- run_action: cache hit ----------

def test_run_action_cache_hit(actions_cfg, actions_prompts, sample_project):
    """Первый вызов пишет в кэш, второй — возвращает from_cache=True."""
    with patch("ai_coder.actions.LLMClient") as MockLLM, \
         patch("ai_coder.actions.get_rate") as mock_rate, \
         patch("ai_coder.actions.is_peak_now", return_value=(False, None)):
        from ai_coder.pricing import Rate
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockLLM.return_value.chat.return_value = _make_llm_response("# cached")

        # первый — промах, пишет в кэш
        r1 = run_action(
            action_name="greet",
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
            use_cache=True,
        )
        assert r1.from_cache is False

        # второй — попадание
        r2 = run_action(
            action_name="greet",
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
            use_cache=True,
        )
        assert r2.from_cache is True
        # LLM должен быть вызван ТОЛЬКО ОДИН раз
        assert MockLLM.return_value.chat.call_count == 1


def test_run_action_cache_disabled(actions_cfg, actions_prompts, sample_project):
    with patch("ai_coder.actions.LLMClient") as MockLLM, \
         patch("ai_coder.actions.get_rate") as mock_rate, \
         patch("ai_coder.actions.is_peak_now", return_value=(False, None)):
        from ai_coder.pricing import Rate
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockLLM.return_value.chat.return_value = _make_llm_response("answer")

        r1 = run_action(action_name="greet", project_root=sample_project,
                        cfg=actions_cfg, prompts_cfg=actions_prompts, use_cache=False)
        r2 = run_action(action_name="greet", project_root=sample_project,
                        cfg=actions_cfg, prompts_cfg=actions_prompts, use_cache=False)

        assert r1.from_cache is False
        assert r2.from_cache is False
        assert MockLLM.return_value.chat.call_count == 2


# ---------- run_fix_action ----------

def test_run_fix_action_basic(actions_cfg, actions_prompts, sample_project):
    plan_json = '{"explanation": "fix", "operations": []}'

    with patch("ai_coder.actions.LLMClient") as MockLLM, \
         patch("ai_coder.actions.get_rate") as mock_rate, \
         patch("ai_coder.actions.is_peak_now", return_value=(False, None)):
        from ai_coder.pricing import Rate
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockLLM.return_value.chat.return_value = _make_llm_response(plan_json)

        from ai_coder.apply import Operation, WritePlan
        prev_plan = WritePlan(
            explanation="prev",
            operations=[Operation(type="create_file", path="x.py", content="y")],
        )

        result = run_fix_action(
            parent_action="greet",
            iteration=1,
            project_root=sample_project,
            cfg=actions_cfg,
            prompts_cfg=actions_prompts,
            errors=["syntax error in x.py"],
            previous_plan=prev_plan,
            use_cache=False,
        )

    assert result.action == "greet:fix1"
    assert result.write_plan is not None
