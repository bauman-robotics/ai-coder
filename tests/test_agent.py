from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ai_coder.agent import (
    AgentPlan,
    AgentStep,
    _render_plan_summary,
    parse_agent_plan,
    run_planner,
)
from ai_coder.llm import LLMResponse

# ---------- parse_agent_plan ----------


def test_parse_agent_plan_valid():
    content = json.dumps(
        {
            "explanation": "do things",
            "steps": [
                {
                    "n": 1,
                    "title": "step one",
                    "type": "edit",
                    "details": "details 1",
                    "target_files": ["a.py"],
                },
                {
                    "n": 2,
                    "title": "step two",
                    "type": "edit",
                    "details": "details 2",
                    "target_files": ["b.py"],
                },
            ],
        }
    )
    plan = parse_agent_plan(content, "goal")
    assert plan.parse_error is None
    assert plan.goal == "goal"
    assert plan.explanation == "do things"
    assert len(plan.steps) == 2
    assert plan.steps[0].title == "step one"
    assert plan.steps[1].target_files == ["b.py"]


def test_parse_agent_plan_in_markdown_fence():
    content = '```json\n{"explanation": "x", "steps": [{"title": "t", "type": "edit"}]}\n```'
    plan = parse_agent_plan(content, "goal")
    assert plan.parse_error is None
    assert len(plan.steps) == 1


def test_parse_agent_plan_surrounding_text():
    content = 'Here:\n{"explanation": "", "steps": [{"title": "t", "type": "edit"}]}\nEnd.'
    plan = parse_agent_plan(content, "goal")
    assert plan.parse_error is None
    assert len(plan.steps) == 1


def test_parse_agent_plan_invalid_json():
    plan = parse_agent_plan("nope", "goal")
    assert plan.parse_error is not None


def test_parse_agent_plan_empty_steps():
    content = json.dumps({"explanation": "nothing to do", "steps": []})
    plan = parse_agent_plan(content, "goal")
    assert plan.parse_error is None
    assert plan.empty is True
    assert plan.steps == []


def test_parse_agent_plan_unknown_type_skipped():
    content = json.dumps(
        {
            "explanation": "",
            "steps": [
                {"title": "skip me", "type": "verify"},
                {"title": "keep me", "type": "edit"},
            ],
        }
    )
    plan = parse_agent_plan(content, "goal")
    assert plan.parse_error is None
    assert len(plan.steps) == 1
    assert plan.steps[0].title == "keep me"


def test_parse_agent_plan_valid_json_with_steps():
    content = json.dumps(
        {
            "explanation": "",
            "steps": [
                {"n": 1, "title": "do", "type": "edit", "details": "d", "target_files": ["x.py"]}
            ],
        }
    )
    plan = parse_agent_plan(content, "goal")
    assert plan.parse_error is None
    assert plan.empty is False
    assert len(plan.steps) == 1


# ---------- _render_plan_summary ----------


def test_render_plan_summary():
    plan = AgentPlan(
        goal="g",
        explanation="short explanation",
        steps=[
            AgentStep(n=1, title="first", type="edit", details=""),
            AgentStep(n=2, title="second", type="edit", details=""),
        ],
    )
    text = _render_plan_summary(plan)
    assert "short explanation" in text
    assert "1. first" in text
    assert "2. second" in text


# ---------- run_planner (мок LLM) ----------


def _fake_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=500,
        prompt_cache_hit_tokens=400,
        prompt_cache_miss_tokens=100,
        completion_tokens=200,
        total_tokens=700,
        duration_ms=1500,
        finish_reason="stop",
    )


def test_run_planner_returns_plan(sample_project: Path, minimal_cfg):
    plan_json = json.dumps(
        {
            "explanation": "test plan",
            "steps": [
                {
                    "n": 1,
                    "title": "fix stuff",
                    "type": "edit",
                    "details": "d",
                    "target_files": ["src/main.py"],
                },
            ],
        }
    )

    # минимальный prompts_cfg с нужным ключом
    from ai_coder.config import PromptEntry, PromptsConfig

    pr_cfg = PromptsConfig(
        prompts={
            "agent_plan_json": PromptEntry(system="S {{max_steps}}", user="U {{goal}}"),
        }
    )

    with patch("ai_coder.agent.LLMClient") as MockClient:
        MockClient.return_value.chat.return_value = _fake_llm_response(plan_json)
        with patch("ai_coder.agent.get_rate") as mock_rate:
            from ai_coder.pricing import Rate

            mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)

            result = run_planner(
                goal="test goal",
                project_root=sample_project,
                cfg=minimal_cfg,
                prompts_cfg=pr_cfg,
                model="test-model",
                depth="shallow",
                max_steps=5,
            )

    assert result.plan.parse_error is None
    assert len(result.plan.steps) == 1
    assert result.plan.steps[0].title == "fix stuff"
    assert result.plan.goal == "test goal"
    assert result.llm.content == plan_json


def test_parse_agent_plan_skips_diagnostic_steps():
    content = json.dumps(
        {
            "explanation": "",
            "steps": [
                {
                    "n": 1,
                    "title": "Продиагностировать README",
                    "type": "edit",
                    "details": "Составить список потерянной разметки",
                },
                {
                    "n": 2,
                    "title": "Добавить докстринг к add",
                    "type": "edit",
                    "details": "В math.py добавить докстринг",
                    "target_files": ["math.py"],
                },
            ],
        }
    )
    plan = parse_agent_plan(content, "goal")
    assert plan.parse_error is None
    assert plan.empty is False
    assert len(plan.steps) == 1
    assert "докстринг" in plan.steps[0].title.lower()


def test_parse_agent_plan_all_steps_diagnostic_becomes_empty():
    content = json.dumps(
        {
            "explanation": "",
            "steps": [
                {
                    "n": 1,
                    "title": "Проанализировать проект",
                    "type": "edit",
                    "details": "Изучить структуру",
                },
                {"n": 2, "title": "Проверить код", "type": "edit", "details": "Проверить качество"},
            ],
        }
    )
    plan = parse_agent_plan(content, "goal")
    assert plan.parse_error is None
    assert plan.empty is True
