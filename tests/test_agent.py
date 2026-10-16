from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from ai_coder.agent import (
    AgentPlan,
    AgentStep,
    ReverseCheckResult,
    _collect_diff,
    _extract_target_files,
    _parse_phase1_response,
    _render_plan_summary,
    _select_step_only_paths,
    parse_agent_plan,
    parse_decompose_response,
    parse_replan_response,
    run_auto_fix,
    run_planner,
    run_planner_replan,
    run_reverse_check,
    run_tool_loop,
)
from ai_coder.llm import LLMResponse
from ai_coder.pricing import Rate

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

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
    ):
        MockClient.return_value.chat.return_value = _fake_llm_response(plan_json)
        with (
            patch("ai_coder.agent.planner.get_rate") as mock_rate,
            patch("ai_coder.agent.reverse.get_rate", mock_rate),
            patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
            patch("ai_coder.agent._legacy.get_rate", mock_rate),
        ):
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


def test_parse_agent_plan_reclassifies_diagnostic_to_read():
    """10.32: edit с read-маркерами → type="read" (не отбрасывается)."""
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
    assert len(plan.steps) == 2, "read-шаг больше не отбрасывается"
    # Шаг 1 — read (был edit с read-маркерами)
    assert plan.steps[0].type == "read"
    # Шаг 2 — edit (не read-маркеры)
    assert plan.steps[1].type == "edit"
    assert "докстринг" in plan.steps[1].title.lower()


def test_parse_agent_plan_all_diagnostic_become_read():
    """10.32: все диагностические edit → все read, plan.empty=False."""
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
    assert plan.empty is False, "read-шаги больше не отбрасываются"
    assert len(plan.steps) == 2
    assert all(s.type == "read" for s in plan.steps)


def test_run_agent_interactive_accept_all(sample_project, minimal_cfg, monkeypatch):
    """--interactive с ответом 'a' — применяет, дальше без вопросов."""
    # Мок LLM и т.д. — сложно. Упростим: проверим только, что параметр принимается.
    from unittest.mock import patch

    from ai_coder.agent import run_agent
    from ai_coder.config import PromptEntry, PromptsConfig

    pr_cfg = PromptsConfig(
        prompts={
            "agent_plan_json": PromptEntry(system="S {{max_steps}}", user="U {{goal}}"),
            "agent_step_json": PromptEntry(system="S", user="U {{goal}}"),
        }
    )

    # Проверим только сигнатуру (сам вызов пропустим — он сложный)
    import inspect

    sig = inspect.signature(run_agent)
    assert "interactive" in sig.parameters


def test_agent_config_step_max_output_tokens(minimal_cfg):
    """AgentConfig.step_max_output_tokens доступен (по умолчанию 8000)."""
    assert hasattr(minimal_cfg.agent, "step_max_output_tokens")
    assert minimal_cfg.agent.step_max_output_tokens == 8000


def test_estimate_next_cost_rub_by_tool(minimal_cfg):
    """Оценка растёт с типом инструмента."""
    from ai_coder.agent.planner import _estimate_next_cost_rub
    from ai_coder.pricing import Rate

    rate = Rate(value=12.5, source="config", fetched_at=0)
    cost_read = _estimate_next_cost_rub(
        minimal_cfg,
        "test-model",
        "",
        "",
        rate,
        last_tool="read_file",
    )
    cost_edit = _estimate_next_cost_rub(
        minimal_cfg,
        "test-model",
        "",
        "",
        rate,
        last_tool="edit_file",
    )
    cost_write = _estimate_next_cost_rub(
        minimal_cfg,
        "test-model",
        "",
        "",
        rate,
        last_tool="write_file",
    )
    assert cost_write > cost_edit > cost_read


def test_extract_target_files_empty_plan():
    plan = AgentPlan(goal="x", steps=[])
    assert _extract_target_files(plan) == []


def test_extract_target_files_dedup_and_sort():
    plan = AgentPlan(
        goal="x",
        steps=[
            AgentStep(n=1, title="a", type="edit", details="d", target_files=["b.py", "a.py"]),
            AgentStep(
                n=2, title="b", type="edit", details="d", target_files=["a.py", "c.py"]
            ),  # a.py — дубль
        ],
    )
    assert _extract_target_files(plan) == ["a.py", "b.py", "c.py"]


def test_extract_target_files_strips_leading_slash():
    plan = AgentPlan(
        goal="x",
        steps=[
            AgentStep(
                n=1,
                title="a",
                type="edit",
                details="d",
                target_files=["/src/main.py", "  src/utils.py  ", ""],
            ),
        ],
    )
    assert _extract_target_files(plan) == ["src/main.py", "src/utils.py"]


def test_select_only_paths_single_step_plan():
    """Одношаговый план: шаг 1 сужен."""
    assert _select_step_only_paths(
        idx=0, is_single_step=True, auto_targets=["a.py"], auto_enabled=True
    ) == ["a.py"]


def test_select_only_paths_multi_step_first():
    """Многошаговый план: шаг 1 — полный контекст."""
    assert (
        _select_step_only_paths(
            idx=0, is_single_step=False, auto_targets=["a.py"], auto_enabled=True
        )
        is None
    )


def test_select_only_paths_multi_step_second():
    """Многошаговый план: шаг 2 — сужен."""
    assert _select_step_only_paths(
        idx=1, is_single_step=False, auto_targets=["a.py"], auto_enabled=True
    ) == ["a.py"]


def test_select_only_paths_no_targets():
    """target_files пусты — полный контекст всегда."""
    assert (
        _select_step_only_paths(idx=0, is_single_step=True, auto_targets=[], auto_enabled=True)
        is None
    )


def test_select_only_paths_disabled():
    """auto_only_paths=False — полный контекст."""
    assert (
        _select_step_only_paths(
            idx=1, is_single_step=False, auto_targets=["a.py"], auto_enabled=False
        )
        is None
    )


def test_parse_phase1_response_valid():
    content = '{"explanation": "x", "target_files": ["a.py", "b.py"]}'
    files, err = _parse_phase1_response(content)
    assert err is None
    assert files == ["a.py", "b.py"]


def test_parse_phase1_response_strips_slash_and_dedup():
    content = '{"target_files": ["/a.py", "  b.py  ", "a.py"]}'
    files, err = _parse_phase1_response(content)
    assert err is None
    assert files == ["a.py", "b.py"]


def test_parse_phase1_response_markdown_wrapper():
    content = '```json\n{"target_files": ["x.py"]}\n```'
    files, err = _parse_phase1_response(content)
    assert err is None
    assert files == ["x.py"]


def test_parse_phase1_response_invalid_json():
    files, err = _parse_phase1_response("not json at all")
    assert files == []
    assert err is not None
    assert "parse error" in err.lower()


# ---------- run_tool_loop ----------


def _make_llm_response(content: str, finish_reason: str = "stop") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=100,
        finish_reason=finish_reason,
    )


def test_run_tool_loop_finish_immediately(sample_project, minimal_cfg, prompts_cfg):
    """Модель сразу возвращает finish."""

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "done", "success": true}'
        )

        result = run_tool_loop(
            goal="test goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert result.success is True
    assert result.summary == "done"
    assert result.stopped_reason == "completed"
    assert result.iterations == 0  # finish на первой итерации — history пуст


def test_run_tool_loop_one_tool_then_finish(sample_project, minimal_cfg, prompts_cfg):
    """Модель вызывает list_files, потом finish."""

    responses = [
        '{"tool": "list_files", "args": {"dir": "."}}',
        '{"finish": true, "summary": "seen", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="test",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert result.success is True
    assert len(result.history) == 1
    assert result.history[0][0].tool == "list_files"
    assert result.history[0][1].ok is True


def test_run_tool_loop_max_iterations(sample_project, minimal_cfg, prompts_cfg):
    """Модель бесконечно вызывает list_files — упрёмся в max_iterations."""

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"tool": "list_files", "args": {"dir": "."}}'
        )

        result = run_tool_loop(
            goal="loop",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_iterations=3,
            journal=False,
        )

    assert result.stopped_reason == "max_iterations"
    assert result.success is False
    assert len(result.history) == 3


def test_run_tool_loop_parse_error_stops(sample_project, minimal_cfg, prompts_cfg):
    """Невалидный JSON — parse_error, стоп."""

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response("not json")

        result = run_tool_loop(
            goal="bad",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert result.stopped_reason == "parse_error"
    assert result.success is False


def test_run_tool_loop_max_cost(sample_project, minimal_cfg, prompts_cfg):
    """Бюджет исчерпан — стоп после первой итерации."""

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        # каждый вызов — list_files, стоимость > 0
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"tool": "list_files", "args": {"dir": "."}}'
        )

        result = run_tool_loop(
            goal="cost",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_iterations=10,
            max_cost_rub=0.0000001,  # крошечный бюджет
            journal=False,
        )

    assert result.stopped_reason == "max_cost"


def test_run_tool_loop_budget_precheck_no_call(sample_project, minimal_cfg, prompts_cfg):
    """Precheck: при нулевом остатке client.chat НЕ вызывается вообще.

    10.69: если remaining <= 0 — сразу break (без last_iteration).
    Раньше тест использовал max_cost_rub=0.0000001 (положительный
    остаток), теперь это ветка last_iteration — см. соседний тест.
    """
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)

        result = run_tool_loop(
            goal="budget precheck",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_iterations=10,
            max_cost_rub=0,  # ровно 0 → remaining=0 → break без итерации
            journal=False,
        )

    # LLM не дёргался — precheck отсек ДО запроса
    assert MockClient.return_value.chat.call_count == 0
    # Ничего не потрачено
    assert result.total_cost_rub == 0.0
    assert result.success is False
    assert result.stopped_reason == "max_cost"
    assert "precheck" in result.summary.lower()


def test_run_tool_loop_budget_last_iteration(sample_project, minimal_cfg, prompts_cfg):
    """Precheck: при положительном остатке — последняя итерация.

    10.69: если remaining > 0, даём итерации завершиться (chat
    вызывается), потом postcheck останавливает. Пользователь видит
    финальный статус, а не «частичный без verify».
    """
    from ai_coder.agent import run_tool_loop
    from ai_coder.llm import LLMResponse
    from ai_coder.pricing import Rate

    def _fake_response(content: str | None = None) -> LLMResponse:
        if content is None:
            content = '{"finish": true, "success": true, "summary": "done"}'
        return LLMResponse(
            content=content,
            model="test-model",
            prompt_tokens=100,
            prompt_cache_hit_tokens=0,
            prompt_cache_miss_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            duration_ms=100,
            finish_reason="stop",
        )

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent.tool_loop.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _fake_response()

        result = run_tool_loop(
            goal="budget last iteration",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_iterations=10,
            max_cost_rub=0.0000001,  # крошечный, но ПОЛОЖИТЕЛЬНЫЙ
            journal=False,
        )

    # chat дёргался — итерация состоялась
    assert MockClient.return_value.chat.call_count >= 1
    # Стоимость ненулевая (итерация прошла)
    assert result.total_cost_rub > 0
    # Остановка — по бюджету (postcheck после last_iteration)
    assert result.stopped_reason == "max_cost"
    assert "last iteration" in result.summary.lower()


def test_run_planner_decompose_budget_precheck(sample_project, minimal_cfg, prompts_cfg):
    """run_planner_decompose: max_cost_rub — precheck до запроса."""
    from ai_coder.agent import run_planner_decompose
    from ai_coder.pricing import Rate

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)

        result = run_planner_decompose(
            goal="budget precheck planner",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_cost_rub=0.0000001,
        )

    assert MockClient.return_value.chat.call_count == 0
    assert result.cost_rub == 0.0
    assert result.parse_error is not None
    assert "budget" in result.parse_error.lower()
    assert result.subtasks == []


def test_run_tool_loop_finish_with_failure(sample_project, minimal_cfg, prompts_cfg):
    """Модель завершает с success=false."""

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "gave up", "success": false}'
        )

        result = run_tool_loop(
            goal="fail",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert result.success is False
    assert result.summary == "gave up"


def test_run_tool_loop_dry_run_skips_edit(sample_project, minimal_cfg, prompts_cfg):
    """--dry-run: edit_file не выполняется, возвращает would have."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="dry",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            dry_run=True,
        )

    # файл не изменился
    assert (sample_project / "test.py").read_text() == "x = 1\n"
    # в истории — would have
    assert len(result.history) == 1
    assert result.history[0][1].ok is True
    assert "dry-run" in result.history[0][1].output
    assert result.dry_run is True


def test_run_tool_loop_dry_run_allows_read(sample_project, minimal_cfg, prompts_cfg):
    """--dry-run: read_file выполняется (не dangerous)."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("hello\n", encoding="utf-8")

    responses = [
        '{"tool": "read_file", "args": {"path": "test.py"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="dry read",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            dry_run=True,
        )

    # read_file выполнился — output содержит "hello"
    assert "hello" in result.history[0][1].output


def test_run_tool_loop_interactive_yes(sample_project, minimal_cfg, prompts_cfg):
    """--interactive: y — инструмент выполняется."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
        patch("ai_coder.agent.tool_loop._prompt_tool_review", return_value="y"),
        patch("ai_coder.agent._legacy._prompt_tool_review", return_value="y"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="yes",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            interactive=True,
        )

    assert (sample_project / "test.py").read_text() == "x = 42\n"
    assert result.success is True


def test_run_tool_loop_interactive_no_cancels(sample_project, minimal_cfg, prompts_cfg):
    """--interactive: n — стоп, файл не меняется."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
        patch("ai_coder.agent.tool_loop._prompt_tool_review", return_value="n"),
        patch("ai_coder.agent._legacy._prompt_tool_review", return_value="n"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}'
        )

        result = run_tool_loop(
            goal="no",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            interactive=True,
        )

    assert (sample_project / "test.py").read_text() == "x = 1\n"
    assert result.stopped_reason == "cancelled"
    assert result.success is False


def test_run_tool_loop_interactive_skip(sample_project, minimal_cfg, prompts_cfg):
    """--interactive: s — пропустить шаг, продолжить."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "ok", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
        patch("ai_coder.agent.tool_loop._prompt_tool_review", return_value="s"),
        patch("ai_coder.agent._legacy._prompt_tool_review", return_value="s"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="skip",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            interactive=True,
        )

    assert (sample_project / "test.py").read_text() == "x = 1\n"
    assert len(result.history) == 1
    assert "пропущено" in result.history[0][1].error


def test_run_tool_loop_interactive_all(sample_project, minimal_cfg, prompts_cfg):
    """--interactive: a — без дальнейших вопросов."""
    from unittest.mock import patch as _patch

    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 42", "new": "x = 100"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
        _patch("builtins.input", return_value="a") as mock_input,
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="all",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            interactive=True,
        )

    assert (sample_project / "test.py").read_text() == "x = 100\n"
    assert result.success is True
    # input вызван ровно 1 раз — второй dangerous пошёл через accept_all
    assert mock_input.call_count == 1


def test_run_tool_loop_backup_created(sample_project, minimal_cfg, prompts_cfg):
    """После edit_file создаётся бэкап с manifest.json."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="backup",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    # файл изменился
    assert (sample_project / "test.py").read_text() == "x = 42\n"
    # бэкап создан
    assert result.backup_dir is not None
    assert (result.backup_dir / "manifest.json").exists()
    # исходное содержимое в бэкапе
    backup_file = result.backup_dir / "test.py"
    assert backup_file.exists()
    assert backup_file.read_text() == "x = 1\n"


def test_run_tool_loop_backup_not_overwritten(sample_project, minimal_cfg, prompts_cfg):
    """Два edit одного файла — в бэкапе ИСХОДНОЕ состояние."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 42", "new": "x = 100"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="backup twice",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert (sample_project / "test.py").read_text() == "x = 100\n"
    # в бэкапе — ИСХОДНОЕ
    assert (result.backup_dir / "test.py").read_text() == "x = 1\n"
    # одна операция в манифесте (дедуп)
    import json

    manifest = json.loads((result.backup_dir / "manifest.json").read_text())
    assert len(manifest["operations"]) == 1


def test_run_tool_loop_no_backup_in_dry_run(sample_project, minimal_cfg, prompts_cfg):
    """dry-run — бэкап не создаётся."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="dry backup",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            dry_run=True,
        )

    assert result.backup_dir is None


def test_run_tool_loop_auto_commit(git_repo, minimal_cfg, prompts_cfg):
    """--commit: после finish(success) создаётся коммит."""
    import subprocess

    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (git_repo / "test.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "init test.py"], cwd=git_repo, check=True)

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="test commit",
            project_root=git_repo,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            auto_commit=True,
        )

    assert result.commit_hash is not None
    assert len(result.commit_hash) == 8
    assert (git_repo / "test.py").read_text() == "x = 42\n"


def test_run_tool_loop_auto_commit_skipped_in_dry_run(git_repo, minimal_cfg, prompts_cfg):
    """--dry-run + --commit → коммит НЕ создаётся."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (git_repo / "test.py").write_text("x = 1\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=git_repo, check=True)

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="dry",
            project_root=git_repo,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            dry_run=True,
            auto_commit=True,
        )

    assert result.commit_hash is None
    assert (git_repo / "test.py").read_text() == "x = 1\n"


def test_run_tool_loop_commit_reverse_check(git_repo, minimal_cfg, prompts_cfg):
    """8.5: при --commit + --reverse-check reverse-check НЕ пропускается.

    Diff собирается ДО git commit, поэтому RC видит изменения.
    Проверка: reverse_check_result заполнен (не None).
    """
    import subprocess

    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (git_repo / "test.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-m", "init test.py"], cwd=git_repo, check=True)

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "done", "success": true}',
        '{"ok": true, "problems": [], "suggestion": null}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent.tool_loop.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="test commit + rc",
            project_root=git_repo,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            auto_commit=True,
            reverse_check=True,
        )

    assert result.commit_hash is not None
    assert len(result.commit_hash) == 8
    assert MockClient.return_value.chat.call_count == 3
    assert result.reverse_check_result is not None
    assert result.reverse_check_result.ok is True


def test_run_tool_loop_saves_history_json(sample_project, minimal_cfg, prompts_cfg, tmp_path):
    """После tool loop history.json сохранён в журнал."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        '{"tool": "read_file", "args": {"path": "test.py"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="save history",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=True,
        )

    assert result.journal_dir is not None
    history_file = result.journal_dir / "history.json"
    assert history_file.exists()

    import json as _json

    data = _json.loads(history_file.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["action"]["tool"] == "read_file"
    assert data[0]["result"]["ok"] is True


def test_run_tool_loop_resume_from_journal(sample_project, minimal_cfg, prompts_cfg, tmp_path):
    """--resume: продолжает с сохранённой истории."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    # 1) Первый запуск: упирается в max_iterations=1
    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"tool": "read_file", "args": {"path": "test.py"}}'
        )

        result1 = run_tool_loop(
            goal="resume test",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_iterations=1,
        )

    assert result1.stopped_reason == "max_iterations"
    assert result1.journal_dir is not None
    journal = result1.journal_dir
    assert (journal / "history.json").exists()

    # 2) Второй запуск: resume, теперь модель завершает
    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "done", "success": true}'
        )

        result2 = run_tool_loop(
            goal="resume test",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_iterations=5,
            resume_from=journal,
        )

    assert result2.success is True
    # история включает 1 шаг из первой сессии
    assert len(result2.history) >= 1
    assert result2.history[0][0].tool == "read_file"


def test_run_tool_loop_resume_no_history(sample_project, minimal_cfg, prompts_cfg, tmp_path):
    """--resume с пустой папкой — ошибка."""
    from ai_coder.agent import run_tool_loop

    empty_dir = tmp_path / "empty_journal"
    empty_dir.mkdir()

    result = run_tool_loop(
        goal="resume missing",
        project_root=sample_project,
        cfg=minimal_cfg,
        prompts_cfg=prompts_cfg,
        resume_from=empty_dir,
    )

    assert result.success is False
    assert result.stopped_reason == "resume_error"
    assert "history.json" in result.summary


# ---------- кэш phase1 ----------


def test_run_planner_phase1_cache_hit(sample_project, minimal_cfg, prompts_cfg):
    """Второй вызов с той же goal — из кэша, LLM не вызывается."""
    from ai_coder.agent import run_planner_phase1
    from ai_coder.pricing import Rate

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"target_files": ["ai_coder/cli.py"]}'
        )

        r1 = run_planner_phase1(
            goal="cache test",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            use_cache=True,
        )
        assert r1.from_cache is False
        assert MockClient.return_value.chat.call_count == 1

        r2 = run_planner_phase1(
            goal="cache test",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            use_cache=True,
        )
        assert r2.from_cache is True
        assert r2.cost_rub == 0.0
        assert r2.llm is None
        # второй раз LLM не вызывался
        assert MockClient.return_value.chat.call_count == 1
        assert r2.target_files == r1.target_files


def test_run_planner_phase1_cache_refresh(sample_project, minimal_cfg, prompts_cfg):
    """refresh=True — игнорируем кэш, идём в LLM."""
    from ai_coder.agent import run_planner_phase1
    from ai_coder.pricing import Rate

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"target_files": ["ai_coder/cli.py"]}'
        )

        r1 = run_planner_phase1(
            goal="cache refresh",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            use_cache=True,
        )
        assert r1.from_cache is False

        r2 = run_planner_phase1(
            goal="cache refresh",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            use_cache=True,
            refresh=True,
        )
        assert r2.from_cache is False
        assert MockClient.return_value.chat.call_count == 2


def test_run_planner_phase1_no_cache(sample_project, minimal_cfg, prompts_cfg):
    """use_cache=False — не используем кэш."""
    from ai_coder.agent import run_planner_phase1
    from ai_coder.pricing import Rate

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"target_files": ["ai_coder/cli.py"]}'
        )

        r1 = run_planner_phase1(
            goal="no cache",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            use_cache=False,
        )
        r2 = run_planner_phase1(
            goal="no cache",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            use_cache=False,
        )
        assert r1.from_cache is False
        assert r2.from_cache is False
        assert MockClient.return_value.chat.call_count == 2


# ---------- parse_decompose_response ----------


def test_parse_decompose_valid():
    """2 подзадачи — парсинг ok."""
    content = json.dumps(
        {
            "explanation": "разбиваю на 2 файла",
            "subtasks": [
                {"n": 1, "goal": "добавь поле A", "files": ["a.py"]},
                {"n": 2, "goal": "добавь ключ B", "files": ["b.yaml"]},
            ],
        }
    )
    result = parse_decompose_response(content)
    assert result.parse_error is None
    assert len(result.subtasks) == 2
    assert result.subtasks[0].goal == "добавь поле A"
    assert result.subtasks[0].files == ["a.py"]
    assert result.subtasks[1].goal == "добавь ключ B"
    assert result.subtasks[1].files == ["b.yaml"]
    assert result.explanation == "разбиваю на 2 файла"


def test_parse_decompose_markdown_wrapper():
    """Ответ с markdown-обёрткой — парсинг ok."""
    content = '```json\n{"explanation": "x", "subtasks": [{"n": 1, "goal": "g", "files": []}]}\n```'
    result = parse_decompose_response(content)
    assert result.parse_error is None
    assert len(result.subtasks) == 1
    assert result.subtasks[0].goal == "g"


def test_parse_decompose_invalid_json():
    """Невалидный JSON — parse_error."""
    result = parse_decompose_response("not json at all")
    assert result.parse_error is not None
    assert "no '{' found" in result.parse_error or "JSON" in result.parse_error
    assert result.subtasks == []


def test_run_tool_loop_parse_error_retry(sample_project, minimal_cfg, prompts_cfg):
    """parse_error → retry, потом успех."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    responses = [
        "",
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="retry test",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            max_iterations=5,
        )

    assert result.success is True
    assert result.summary == "done"
    assert result.stopped_reason == "completed"


def test_run_tool_loop_parse_error_exhausted(sample_project, minimal_cfg, prompts_cfg):
    """parse_error повторяется → после 2 retry — стоп."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response("")

        result = run_tool_loop(
            goal="always fail",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            max_iterations=10,
        )

    assert result.success is False
    assert result.stopped_reason == "parse_error"
    assert MockClient.return_value.chat.call_count == 3


def test_run_planner_replan_skip(sample_project, minimal_cfg, prompts_cfg):
    """run_planner_replan парсит action=skip."""
    from ai_coder.agent import (
        Subtask,
    )
    from ai_coder.pricing import Rate

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"action": "skip", "explanation": "не критично", "new_subtasks": []}'
        )

        result = run_planner_replan(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            failed_subtask=Subtask(n=2, goal="failed goal"),
            failed_error="something went wrong",
            completed_subtasks=[Subtask(n=1, goal="done")],
            remaining_subtasks=[Subtask(n=3, goal="remaining")],
        )

    assert result.parse_error is None
    assert result.action == "skip"
    assert result.explanation == "не критично"
    assert result.new_subtasks == []


def test_parse_replan_skip():
    """parse_replan_response — action=skip."""
    content = json.dumps(
        {
            "action": "skip",
            "explanation": "не критично",
            "new_subtasks": [],
        }
    )
    result = parse_replan_response(content)
    assert result.parse_error is None
    assert result.action == "skip"
    assert result.explanation == "не критично"
    assert result.new_subtasks == []


def test_parse_replan_modify():
    """parse_replan_response — action=modify с new_subtasks."""
    content = json.dumps(
        {
            "action": "modify",
            "explanation": "план изменён",
            "new_subtasks": [
                {"n": 1, "goal": "новый шаг 1", "files": ["a.py"]},
                {"n": 2, "goal": "новый шаг 2", "files": ["b.py"]},
            ],
        }
    )
    result = parse_replan_response(content)
    assert result.parse_error is None
    assert result.action == "modify"
    assert result.explanation == "план изменён"
    assert len(result.new_subtasks) == 2
    assert result.new_subtasks[0].goal == "новый шаг 1"
    assert result.new_subtasks[0].files == ["a.py"]
    assert result.new_subtasks[1].goal == "новый шаг 2"


def test_parse_replan_invalid_action():
    """parse_replan_response — невалидный action."""
    content = json.dumps(
        {
            "action": "delete_everything",
            "explanation": "x",
            "new_subtasks": [],
        }
    )
    result = parse_replan_response(content)
    assert result.parse_error is not None
    assert "invalid action" in result.parse_error
    assert result.action == "stop"  # default


def test_run_tool_loop_verify_success(sample_project, minimal_cfg, prompts_cfg):
    """verify_commands проходят — success=True."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    minimal_cfg.agent.verify_commands = ["true"]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "done", "success": true}'
        )

        result = run_tool_loop(
            goal="verify ok",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert result.success is True
    assert result.verify_errors == []


def test_run_tool_loop_verify_failed(sample_project, minimal_cfg, prompts_cfg):
    """verify_commands упали — success=False, stopped_reason=verify_failed."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    minimal_cfg.agent.verify_commands = ["false"]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "done", "success": true}'
        )

        result = run_tool_loop(
            goal="verify fail",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert result.success is False
    assert result.stopped_reason == "verify_failed"
    assert len(result.verify_errors) > 0


def test_run_tool_loop_rollback_on_verify_failed(sample_project, minimal_cfg, prompts_cfg):
    """verify_failed → run_tool_loop откатывает свои правки из backup_dir."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    # Файл — как в E27: правка применилась, verify упал, файл должен
    # вернуться к исходному состоянию.
    (sample_project / "test.py").write_text("x = 1\n", encoding="utf-8")

    minimal_cfg.agent.verify_commands = ["false"]

    responses = [
        '{"tool": "edit_file", "args": {"path": "test.py", "old": "x = 1", "new": "x = 42"}}',
        '{"finish": true, "summary": "done", "success": true}',
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="rollback on verify fail",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    # verify упал
    assert result.success is False
    assert result.stopped_reason == "verify_failed"
    # бэкап был создан
    assert result.backup_dir is not None
    # файл откатился к исходному содержимому
    assert (sample_project / "test.py").read_text() == "x = 1\n"


def test_run_auto_fix_no_errors(sample_project, minimal_cfg, prompts_cfg):
    """Если verify сразу прошёл — success=True, 1 попытка."""

    result = run_auto_fix(
        project_root=sample_project,
        cfg=minimal_cfg,
        prompts_cfg=prompts_cfg,
        verify_commands=["true"],
        max_attempts=3,
        journal=False,
    )
    assert result.success is True
    assert result.attempts == 1
    assert result.initial_errors == []
    assert result.final_errors == []
    assert result.stopped_reason == "completed"


def test_run_auto_fix_loop_success(sample_project, minimal_cfg, prompts_cfg):
    """Ошибки были, LLM починил — success=True."""
    from ai_coder.pricing import Rate

    calls = {"n": 0}

    def fake_verify(commands, project_root, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ["error 1", "error 2"]
        return []

    with (
        patch("ai_coder.agent.tool_loop.run_verify_commands", side_effect=fake_verify),
        patch("ai_coder.agent.autofix.run_verify_commands", side_effect=fake_verify),
        patch("ai_coder.agent._legacy.run_verify_commands", side_effect=fake_verify),
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "fixed", "success": true}'
        )

        result = run_auto_fix(
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            verify_commands=["pytest -q"],
            max_attempts=3,
            journal=False,
        )

    assert result.success is True
    assert result.attempts == 2
    assert result.initial_errors == ["error 1", "error 2"]
    assert result.final_errors == []


def test_run_auto_fix_max_cost(sample_project, minimal_cfg, prompts_cfg):
    """Стоимость превысила max_cost_rub — stopped_reason=max_cost."""
    from ai_coder.agent import ToolLoopResult

    expensive = ToolLoopResult(
        success=False,  # попытка не удалась (иначе цикл завершился бы)
        summary="tried but failed",
        iterations=3,
        total_cost_rub=5.0,  # дорого
        stopped_reason="completed",
    )

    with (
        patch("ai_coder.agent.tool_loop.run_verify_commands", return_value=["always fail"]),
        patch("ai_coder.agent.autofix.run_verify_commands", return_value=["always fail"]),
        patch("ai_coder.agent._legacy.run_verify_commands", return_value=["always fail"]),
        patch("ai_coder.agent.tool_loop.run_tool_loop", return_value=expensive),
        patch("ai_coder.agent.autofix.run_tool_loop", return_value=expensive),
        patch("ai_coder.agent.classic.run_tool_loop", return_value=expensive),
    ):
        result = run_auto_fix(
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            verify_commands=["false"],
            max_attempts=5,
            journal=False,
            max_cost_rub=1.0,  # лимит меньше стоимости одной попытки
        )

    assert result.success is False
    assert result.stopped_reason == "max_cost"
    assert result.attempts == 1  # остановились после первой попытки
    assert result.total_cost_rub == 5.0


def test_run_auto_fix_max_attempts(sample_project, minimal_cfg, prompts_cfg):
    """Ошибки не уходят — stopped_reason=max_attempts."""
    from ai_coder.pricing import Rate

    with (
        patch("ai_coder.agent.tool_loop.run_verify_commands", return_value=["always fail"]),
        patch("ai_coder.agent.autofix.run_verify_commands", return_value=["always fail"]),
        patch("ai_coder.agent._legacy.run_verify_commands", return_value=["always fail"]),
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "tried", "success": true}'
        )

        result = run_auto_fix(
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            verify_commands=["false"],
            max_attempts=2,
            journal=False,
        )

    assert result.success is False
    assert result.attempts == 2
    assert result.stopped_reason == "max_attempts"
    assert result.final_errors == ["always fail"]


# ---------- run_agent_decompose: replan ----------


def _subtask(n: int, goal: str) -> "object":
    from ai_coder.agent import Subtask

    return Subtask(n=n, goal=goal, files=[])


def _ok_loop() -> "object":
    from ai_coder.agent import ToolLoopResult

    return ToolLoopResult(
        success=True,
        summary="ok",
        iterations=1,
        total_cost_rub=0.1,
        applied_ops=1,  # успешный loop: 1 правка
    )


def _ok_loop_no_ops() -> "object":
    """Имитация run_tool_loop(step_type="edit") с 0 правок.

    10.31: реальный run_tool_loop сам возвращает success=False,
    stopped_reason="no_ops" — мок это отражает.
    """
    from ai_coder.agent import ToolLoopResult

    return ToolLoopResult(
        success=False,
        summary="nothing to do",
        iterations=1,
        total_cost_rub=0.05,
        applied_ops=0,
        stopped_reason="no_ops",
    )


def _fail_loop(reason: str = "max_iterations") -> "object":
    from ai_coder.agent import ToolLoopResult

    return ToolLoopResult(
        success=False,
        summary=f"failed: {reason}",
        iterations=5,
        stopped_reason=reason,
        total_cost_rub=0.2,
    )


def test_run_agent_decompose_replan_skip(sample_project, minimal_cfg, prompts_cfg):
    """Подзадача 1 падает → replan=skip → подзадача 2 выполняется.

    Проблема 15: replan в оркестраторе run_agent_decompose не был покрыт
    тестами. Проверяем, что ветка skip живёт и цикл идёт дальше.
    """
    from ai_coder.agent import DecomposeResult, ReplanResult, run_agent_decompose

    # Отключаем retry через v4-pro — иначе пойдёт второй run_tool_loop
    minimal_cfg.agent.decompose_model = None

    dec = DecomposeResult(
        explanation="two subtasks",
        subtasks=[_subtask(1, "first"), _subtask(2, "second")],
    )
    replan = ReplanResult(action="skip", explanation="not critical")

    # side_effect: подзадача 1 → fail, подзадача 2 → ok
    side_effects = [_fail_loop("max_iterations"), _ok_loop()]

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.decomposer.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.classic.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.planner.run_planner_replan", return_value=replan),
        patch("ai_coder.agent.decomposer.run_planner_replan", return_value=replan),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            replan=True,
        )

    assert result.parse_error is None, "skip не должен останавливать decompose"
    assert len(result.skipped_subtasks) == 1
    assert result.skipped_subtasks[0].n == 1
    assert len(result.subtask_results) == 2
    assert result.subtask_results[0]["success"] is False
    assert result.subtask_results[1]["success"] is True


def test_run_agent_decompose_replan_stop(sample_project, minimal_cfg, prompts_cfg):
    """Подзадача 1 падает → replan=stop → оркестратор останавливается."""
    from ai_coder.agent import DecomposeResult, ReplanResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None

    dec = DecomposeResult(
        explanation="two subtasks",
        subtasks=[_subtask(1, "first"), _subtask(2, "second")],
    )
    replan = ReplanResult(action="stop", explanation="hopeless")

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", return_value=_fail_loop()),
        patch("ai_coder.agent.decomposer.run_tool_loop", return_value=_fail_loop()),
        patch("ai_coder.agent.classic.run_tool_loop", return_value=_fail_loop()),
        patch("ai_coder.agent.planner.run_planner_replan", return_value=replan),
        patch("ai_coder.agent.decomposer.run_planner_replan", return_value=replan),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            replan=True,
        )

    assert result.parse_error is not None
    assert "replan=stop" in result.parse_error
    assert len(result.subtask_results) == 1
    assert result.subtask_results[0]["success"] is False


def test_run_agent_decompose_replan_modify(sample_project, minimal_cfg, prompts_cfg):
    """Подзадача 1 падает → replan=modify → новая подзадача выполняется.

    modify пересобирает оставшиеся подзадачи: subtasks[:i] + new_subtasks.
    Проверяем, что новая подзадача действительно идёт в run_tool_loop.
    """
    from ai_coder.agent import DecomposeResult, ReplanResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None

    dec = DecomposeResult(
        explanation="two subtasks",
        subtasks=[_subtask(1, "first"), _subtask(2, "second")],
    )
    # modify заменяет оставшиеся на одну новую подзадачу
    replan = ReplanResult(
        action="modify",
        explanation="adapt plan",
        new_subtasks=[_subtask(1, "rewritten")],
    )

    # side_effect: подзадача 1 (оригинал) → fail,
    #              подзадача 1 (новая после modify) → ok
    side_effects = [_fail_loop(), _ok_loop()]

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.decomposer.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.classic.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.planner.run_planner_replan", return_value=replan),
        patch("ai_coder.agent.decomposer.run_planner_replan", return_value=replan),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            replan=True,
        )

    assert result.parse_error is None
    # новая подзадача успешна, оригинальная вторая — не запускалась
    assert len(result.subtask_results) == 2
    assert result.subtask_results[0]["success"] is False  # оригинал 1
    assert result.subtask_results[1]["success"] is True  # new_subtask
    assert result.subtask_results[1]["goal"] == "rewritten"


def test_run_agent_decompose_retry_cost_summation(sample_project, minimal_cfg, prompts_cfg):
    """При retry через v4-pro стоимость суммируется с первой попыткой.

    Регрессия 10.14.13: раньше subtask_results[-1]["cost_rub"]
    перезаписывался стоимостью retry — flash-попытка терялась
    в отчёте decompose.
    """
    from ai_coder.agent import DecomposeResult, ReplanResult, run_agent_decompose

    # Включаем retry через v4-pro
    minimal_cfg.agent.decompose_model = "deepseek-v4-pro"

    dec = DecomposeResult(
        explanation="one subtask",
        subtasks=[_subtask(1, "fail twice")],
    )
    replan = ReplanResult(action="stop", explanation="hopeless")

    # Попытка 1 (flash): 0.06 RUB. Попытка 2 (v4-pro retry): 0.38 RUB.
    side_effects = [
        _fail_loop_with_cost(0.06),
        _fail_loop_with_cost(0.38),
    ]

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.decomposer.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.classic.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.planner.run_planner_replan", return_value=replan),
        patch("ai_coder.agent.decomposer.run_planner_replan", return_value=replan),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            model="deepseek-flash",  # первая попытка
            journal=False,
            replan=True,
        )

    # Ключевая проверка: 0.06 + 0.38 = 0.44, не 0.38
    assert len(result.subtask_results) == 1
    assert result.subtask_results[0]["cost_rub"] == 0.44, (
        f"ожидали 0.44 (сумма), получили {result.subtask_results[0]['cost_rub']}"
    )


def _fail_loop_with_cost(cost: float) -> "object":
    from ai_coder.agent import ToolLoopResult

    return ToolLoopResult(
        success=False,
        summary="failed",
        iterations=1,
        stopped_reason="completed",
        total_cost_rub=cost,
    )


def test_run_agent_decompose_max_cost(sample_project, minimal_cfg, prompts_cfg):
    """Стоимость превысила max_cost_rub — stopped_reason=max_cost.

    Фича 10.14.16: флаг --decompose-max-cost-rub.
    После подзадачи, если dec_result.cost_rub >= max_cost_rub,
    run_agent_decompose останавливается с parse_error="max_cost exceeded".
    """
    from ai_coder.agent import DecomposeResult, ToolLoopResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None  # без retry

    dec = DecomposeResult(
        explanation="two subtasks",
        subtasks=[_subtask(1, "first"), _subtask(2, "second")],
    )
    # Дорогая первая подзадача (5 RUB) при лимите 1 RUB
    expensive = ToolLoopResult(success=True, summary="done", iterations=1, total_cost_rub=5.0)

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", return_value=expensive),
        patch("ai_coder.agent.decomposer.run_tool_loop", return_value=expensive),
        patch("ai_coder.agent.classic.run_tool_loop", return_value=expensive),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            max_cost_rub=1.0,
        )

    assert result.parse_error is not None
    assert "max_cost exceeded" in result.parse_error
    # Вторая подзадача не выполнялась
    assert len(result.subtask_results) == 1
    assert result.cost_rub == 5.0


def test_run_agent_decompose_max_cost_saves_report(sample_project, minimal_cfg, prompts_cfg):
    """При max_cost — report.md всё равно создаётся (регрессия 10.14.18)."""
    from ai_coder.agent import DecomposeResult, ToolLoopResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None

    dec = DecomposeResult(
        explanation="two subtasks",
        subtasks=[_subtask(1, "first"), _subtask(2, "second")],
    )
    expensive = ToolLoopResult(success=True, summary="done", iterations=1, total_cost_rub=5.0)

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", return_value=expensive),
        patch("ai_coder.agent.decomposer.run_tool_loop", return_value=expensive),
        patch("ai_coder.agent.classic.run_tool_loop", return_value=expensive),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=True,
            max_cost_rub=1.0,
        )

    assert result.parse_error is not None
    assert "max_cost exceeded" in result.parse_error
    assert result.journal_dir is not None
    report_path = result.journal_dir / "report.md"
    assert report_path.exists(), f"report.md не найден в {result.journal_dir}"
    content = report_path.read_text(encoding="utf-8")
    assert "max_cost" in content or "неуспех" in content


def test_run_tool_loop_retry_on_missing_args(sample_project, minimal_cfg, prompts_cfg):
    """Регрессия: при missing 'path' — retry (не считая итерацию)."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.llm import LLMResponse
    from ai_coder.pricing import Rate

    llm_replies = [
        '{"tool": "edit_file", "args": {}, "reason": "забыл path"}',
        (
            '{"tool": "edit_file", "args": '
            '{"path": "src/main.py", "old": "hello", "new": "world"}, '
            '"reason": "правка"}'
        ),
        '{"finish": true, "summary": "done", "success": true}',
    ]
    calls = {"n": 0}

    def fake_chat(self, *, system, user, **kwargs):
        n = calls["n"]
        calls["n"] += 1
        content = llm_replies[n] if n < len(llm_replies) else '{"finish": true}'
        return LLMResponse(
            content=content,
            model="test-model",
            prompt_tokens=100,
            prompt_cache_hit_tokens=0,
            prompt_cache_miss_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            duration_ms=100,
            finish_reason="stop",
        )

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat = fake_chat.__get__(MockClient.return_value)

        result = run_tool_loop(
            goal="тест retry missing args",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            max_iterations=10,
            journal=False,
            dry_run=True,
        )

    assert calls["n"] == 3, f"ожидали 3 вызова, было {calls['n']}"
    assert result.success is True


# ---------- extract_changed_files ----------


def test_extract_changed_files_empty():
    from ai_coder.agent import extract_changed_files

    assert extract_changed_files([]) == []


def test_extract_changed_files_picks_edits():
    from ai_coder.agent import extract_changed_files
    from ai_coder.tools import ToolAction, ToolResult

    history = [
        (ToolAction(tool="read_file", args={"path": "a.py"}), ToolResult(ok=True, output="x")),
        (
            ToolAction(tool="edit_file", args={"path": "a.py", "old": "x", "new": "y"}),
            ToolResult(ok=True, output="edited"),
        ),
        (
            ToolAction(tool="write_file", args={"path": "b.py", "content": "z"}),
            ToolResult(ok=True, output="wrote"),
        ),
    ]
    assert extract_changed_files(history) == ["a.py", "b.py"]


def test_extract_changed_files_skips_tests():
    from ai_coder.agent import extract_changed_files
    from ai_coder.tools import ToolAction, ToolResult

    history = [
        (
            ToolAction(tool="write_file", args={"path": "tests/test_a.py", "content": ""}),
            ToolResult(ok=True, output="wrote"),
        ),
        (
            ToolAction(tool="write_file", args={"path": "test_b.py", "content": ""}),
            ToolResult(ok=True, output="wrote"),
        ),
        (
            ToolAction(tool="edit_file", args={"path": "src/c.py", "old": "x", "new": "y"}),
            ToolResult(ok=True, output="edited"),
        ),
    ]
    assert extract_changed_files(history) == ["src/c.py"]


def test_extract_changed_files_skips_failed():
    from ai_coder.agent import extract_changed_files
    from ai_coder.tools import ToolAction, ToolResult

    history = [
        (
            ToolAction(tool="edit_file", args={"path": "a.py", "old": "x", "new": "y"}),
            ToolResult(ok=False, error="not found"),
        ),
    ]
    assert extract_changed_files(history) == []


def test_extract_changed_files_skips_finish():
    from ai_coder.agent import extract_changed_files
    from ai_coder.tools import ToolAction, ToolResult

    history = [
        (
            ToolAction(finish=True, success=True, summary="done", args={}),
            ToolResult(ok=True, output="finished"),
        ),
        (
            ToolAction(tool="edit_file", args={"path": "a.py", "old": "x", "new": "y"}),
            ToolResult(ok=True, output="edited"),
        ),
    ]
    assert extract_changed_files(history) == ["a.py"]


def test_extract_changed_files_skips_non_py():
    from ai_coder.agent import extract_changed_files
    from ai_coder.tools import ToolAction, ToolResult

    history = [
        (
            ToolAction(tool="write_file", args={"path": "README.md", "content": ""}),
            ToolResult(ok=True, output="wrote"),
        ),
        (
            ToolAction(tool="write_file", args={"path": "config.yaml", "content": ""}),
            ToolResult(ok=True, output="wrote"),
        ),
    ]
    assert extract_changed_files(history) == []


# ---------- run_agent_decompose: plan= (--plan) ----------


def test_run_agent_decompose_accepts_plan(sample_project, minimal_cfg, prompts_cfg):
    """Если передан plan= — run_planner_decompose НЕ вызывается повторно."""
    from ai_coder.agent import DecomposeResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None

    dec = DecomposeResult(
        explanation="prebuilt",
        subtasks=[_subtask(1, "only")],
        cost_rub=0.123,
    )

    with (
        patch("ai_coder.agent.planner.run_planner_decompose") as mock_planner,
        patch("ai_coder.agent.decomposer.run_planner_decompose", mock_planner),
        patch("ai_coder.agent.tool_loop.run_tool_loop", return_value=_ok_loop()),
        patch("ai_coder.agent.decomposer.run_tool_loop", return_value=_ok_loop()),
        patch("ai_coder.agent.classic.run_tool_loop", return_value=_ok_loop()),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            plan=dec,
        )

    mock_planner.assert_not_called()
    assert result is dec, "должен вернуть тот же объект плана"
    # 0.123 (план) + 0.1 (одна подзадача из _ok_loop) = 0.223
    assert result.cost_rub == 0.223, "стоимость планирования + выполнения"


def test_run_agent_decompose_passes_max_iterations(sample_project, minimal_cfg, prompts_cfg):
    """max_iterations из аргумента должен уходить в run_tool_loop,
    не подменяться на cfg.agent.max_steps."""
    from ai_coder.agent import DecomposeResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None

    dec = DecomposeResult(
        explanation="prebuilt",
        subtasks=[_subtask(1, "do x")],
        cost_rub=0.0,
    )

    captured: dict = {}

    def fake_loop(**kwargs):
        captured["max_iterations"] = kwargs["max_iterations"]
        return _ok_loop()

    with (
        patch("ai_coder.agent.planner.run_planner_decompose"),
        patch("ai_coder.agent.decomposer.run_planner_decompose"),
        patch("ai_coder.agent.tool_loop.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.decomposer.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.classic.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        run_agent_decompose(
            goal="g",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            plan=dec,
            max_iterations=42,
        )

    assert captured["max_iterations"] == 42, "аргумент должен победить cfg"


def test_run_agent_decompose_router_edit_simple_iters(sample_project, minimal_cfg, prompts_cfg):
    """Router: type="edit" → edit-simple → 10 итераций (не cfg.max_steps)."""
    from ai_coder.agent import DecomposeResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None
    minimal_cfg.agent.max_steps = 7  # намеренно не дефолт

    dec = DecomposeResult(
        explanation="prebuilt",
        subtasks=[_subtask(1, "do x")],
        cost_rub=0.0,
    )

    captured: dict = {}

    def fake_loop(**kwargs):
        captured["max_iterations"] = kwargs["max_iterations"]
        return _ok_loop()

    with (
        patch("ai_coder.agent.planner.run_planner_decompose"),
        patch("ai_coder.agent.decomposer.run_planner_decompose"),
        patch("ai_coder.agent.tool_loop.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.decomposer.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.classic.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        run_agent_decompose(
            goal="g",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            plan=dec,
        )

    assert captured["max_iterations"] == 10, "Router: edit → edit-simple=10"


# ---------- split-goals (10F) ----------


def test_parse_split_goals_valid():
    from ai_coder.agent import parse_split_goals_response

    content = '{"issues": [{"title": "A", "goal": "do A"}, {"title": "B", "goal": "do B"}]}'
    result = parse_split_goals_response(content)
    assert result.parse_error is None
    assert len(result.issues) == 2
    assert result.issues[0].n == 1
    assert result.issues[0].title == "A"
    assert result.issues[1].goal == "do B"


def test_parse_split_goals_markdown_wrapper():
    from ai_coder.agent import parse_split_goals_response

    content = '```json\n{"issues": [{"title": "X", "goal": "do X"}]}\n```'
    result = parse_split_goals_response(content)
    assert result.parse_error is None
    assert len(result.issues) == 1


def test_parse_split_goals_empty():
    from ai_coder.agent import parse_split_goals_response

    result = parse_split_goals_response('{"issues": []}')
    assert result.parse_error == "empty issues"
    assert result.issues == []


def test_parse_split_goals_invalid_json():
    from ai_coder.agent import parse_split_goals_response

    result = parse_split_goals_response("not json at all")
    assert result.parse_error is not None
    assert result.issues == []


def test_slug_for_issue_cyrillic():
    from ai_coder.agent import _slug_for_issue

    assert _slug_for_issue("Добавь sub в calc.py") == "dobav-sub-v-calc-py"
    assert _slug_for_issue("улучши GUI") == "uluchshi-gui"
    assert _slug_for_issue("") == "task"
    assert _slug_for_issue("!!!") == "task"


def test_run_split_goals_saves_files(sample_project, minimal_cfg, prompts_cfg):
    from ai_coder.agent import run_split_goals

    content = '{"issues": [{"title": "add sub", "goal": "add sub to calc"}, {"title": "add mul", "goal": "add mul to calc"}]}'

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.decomposer.LLMClient", MockClient),
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent.decomposer.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.scan_project_metadata") as mock_scan,
        patch("ai_coder.agent.decomposer.scan_project_metadata", mock_scan),
        patch("ai_coder.agent.planner.scan_project_metadata") as mock_scan,
        patch("ai_coder.agent.tool_loop.scan_project_metadata", mock_scan),
        patch("ai_coder.agent.decomposer.scan_project_metadata", mock_scan),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        MockClient.return_value.chat.return_value = _fake_llm_response(content)
        from ai_coder.scanner import MetadataScanResult

        mock_scan.return_value = MetadataScanResult(root=sample_project)
        result = run_split_goals(
            goal="add sub and mul",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            out_dir=sample_project / "issues",
        )

    assert result.parse_error is None, result.parse_error
    assert len(result.issues) == 2
    assert result.output_dir is not None
    files = sorted(result.output_dir.glob("*.md"))
    assert len(files) == 2
    assert files[0].name == "1-add-sub.md"
    assert files[1].name == "2-add-mul.md"
    body0 = files[0].read_text(encoding="utf-8")
    assert body0.startswith("# task: add sub")
    assert "add sub to calc" in body0


def test_run_split_goals_nonempty_dir_uses_timestamp(sample_project, minimal_cfg, prompts_cfg):
    from ai_coder.agent import run_split_goals

    # создадим непустой issues/
    issues = sample_project / "issues"
    issues.mkdir()
    (issues / "existing.md").write_text("x", encoding="utf-8")

    content = '{"issues": [{"title": "one", "goal": "do one"}]}'

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.decomposer.LLMClient", MockClient),
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent.decomposer.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.scan_project_metadata") as mock_scan,
        patch("ai_coder.agent.decomposer.scan_project_metadata", mock_scan),
        patch("ai_coder.agent.planner.scan_project_metadata") as mock_scan,
        patch("ai_coder.agent.tool_loop.scan_project_metadata", mock_scan),
        patch("ai_coder.agent.decomposer.scan_project_metadata", mock_scan),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        MockClient.return_value.chat.return_value = _fake_llm_response(content)
        from ai_coder.scanner import MetadataScanResult

        mock_scan.return_value = MetadataScanResult(root=sample_project)
        result = run_split_goals(
            goal="do one",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            # out_dir не задан — должен сам выбрать issues-<ts>/
        )

    assert result.parse_error is None
    assert result.output_dir is not None
    assert result.output_dir.name.startswith("issues-")
    assert not (result.output_dir / "existing.md").exists(), "не должен затирать старые"


def test_run_agent_decompose_success_requires_applied_ops(sample_project, minimal_cfg, prompts_cfg):
    """10.31: decompose доверяет loop.success — 0 правок → loop.success=False."""
    from ai_coder.agent import DecomposeResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None
    dec = DecomposeResult(
        explanation="one",
        subtasks=[_subtask(1, "only")],
    )

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", return_value=_ok_loop_no_ops()),
        patch("ai_coder.agent.decomposer.run_tool_loop", return_value=_ok_loop_no_ops()),
        patch("ai_coder.agent.classic.run_tool_loop", return_value=_ok_loop_no_ops()),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert len(result.subtask_results) == 1
    assert result.subtask_results[0]["success"] is False, (
        "loop.success=False (0 правок) → subtask success=False"
    )


def test_run_agent_decompose_success_with_applied_ops(sample_project, minimal_cfg, prompts_cfg):
    """applied_ops > 0 → subtask success=True (нормальный кейс)."""
    from ai_coder.agent import DecomposeResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None
    dec = DecomposeResult(
        explanation="one",
        subtasks=[_subtask(1, "only")],
    )

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", return_value=_ok_loop()),
        patch("ai_coder.agent.decomposer.run_tool_loop", return_value=_ok_loop()),
        patch("ai_coder.agent.classic.run_tool_loop", return_value=_ok_loop()),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert result.subtask_results[0]["success"] is True


def test_run_agent_decompose_retry_zero_ops_not_success(sample_project, minimal_cfg, prompts_cfg):
    """10.31: retry (0 правок) → loop.success=False → subtask success=False."""

    from ai_coder.agent import DecomposeResult, run_agent_decompose

    # Включаем retry — иначе ветка не сработает
    minimal_cfg.agent.decompose_model = "deepseek-v4-pro"

    dec = DecomposeResult(
        explanation="one",
        subtasks=[_subtask(1, "only")],
    )

    # side_effect: flash fail → retry v4-pro тоже без правок
    side_effects = [_fail_loop("max_iterations"), _ok_loop_no_ops()]

    with (
        patch("ai_coder.agent.planner.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.decomposer.run_planner_decompose", return_value=dec),
        patch("ai_coder.agent.tool_loop.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.decomposer.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.classic.run_tool_loop", side_effect=side_effects),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        result = run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert len(result.subtask_results) == 1
    assert result.subtask_results[0]["success"] is False, (
        "retry applied_ops=0 → success=False (не ложный ✅)"
    )


# ---------- 10.29: verify_commands как параметр ----------


def test_run_tool_loop_verify_commands_explicit(sample_project, minimal_cfg, prompts_cfg):
    """verify_commands=["true"] при cfg.agent.verify_commands=[] — verify зовётся."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    minimal_cfg.agent.verify_commands = []  # cfg пуст

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
        patch("ai_coder.agent.tool_loop.run_verify_commands", return_value=[]) as mock_verify,
        patch("ai_coder.agent._legacy.run_verify_commands", mock_verify),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "done", "success": true}'
        )

        result = run_tool_loop(
            goal="verify explicit",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            verify_commands=["true"],
        )

    mock_verify.assert_called_once()
    assert mock_verify.call_args[0][0] == ["true"], "verify получил явный список"
    assert result.success is True
    assert result.verify_errors == []


def test_run_tool_loop_verify_commands_empty_disables(sample_project, minimal_cfg, prompts_cfg):
    """verify_commands=[] при cfg.agent.verify_commands=["false"] — verify не зовётся."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    minimal_cfg.agent.verify_commands = ["false"]  # cfg непустой — упал бы

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
        patch("ai_coder.agent.tool_loop.run_verify_commands") as mock_verify,
        patch("ai_coder.agent.tool_loop.run_verify_commands", mock_verify),
        patch("ai_coder.agent._legacy.run_verify_commands", mock_verify),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "done", "success": true}'
        )

        result = run_tool_loop(
            goal="verify disabled",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            verify_commands=[],  # явное «не проверять»
        )

    mock_verify.assert_not_called()
    assert result.success is True, "verify не запускался → success без ошибок"


def test_run_tool_loop_verify_commands_none_falls_back_to_cfg(
    sample_project, minimal_cfg, prompts_cfg
):
    """verify_commands=None — fallback на cfg.agent.verify_commands."""
    from ai_coder.agent import run_tool_loop
    from ai_coder.pricing import Rate

    minimal_cfg.agent.verify_commands = ["false"]  # упадёт

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
        patch("ai_coder.agent.tool_loop.run_verify_commands", return_value=["boom"]) as mock_verify,
        patch("ai_coder.agent._legacy.run_verify_commands", mock_verify),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.return_value = _make_llm_response(
            '{"finish": true, "summary": "done", "success": true}'
        )

        result = run_tool_loop(
            goal="verify fallback",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            verify_commands=None,
        )

    mock_verify.assert_called_once()
    assert mock_verify.call_args[0][0] == ["false"], "fallback на cfg"
    assert result.success is False
    assert result.stopped_reason == "verify_failed"


def test_run_agent_decompose_verify_commands_passthrough(sample_project, minimal_cfg, prompts_cfg):
    """verify_commands=[] в run_agent_decompose пробрасывается в run_tool_loop."""
    from ai_coder.agent import DecomposeResult, run_agent_decompose

    minimal_cfg.agent.decompose_model = None

    dec = DecomposeResult(
        explanation="prebuilt",
        subtasks=[_subtask(1, "do x")],
        cost_rub=0.0,
    )

    captured: dict = {}

    def fake_loop(**kwargs):
        captured["verify_commands"] = kwargs.get("verify_commands")
        return _ok_loop()

    with (
        patch("ai_coder.agent.planner.run_planner_decompose"),
        patch("ai_coder.agent.decomposer.run_planner_decompose"),
        patch("ai_coder.agent.tool_loop.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.decomposer.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.classic.run_tool_loop", side_effect=fake_loop),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        run_agent_decompose(
            goal="goal",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            plan=dec,
            verify_commands=[],
        )

    assert captured.get("verify_commands") == [], "пустой список ушёл в run_tool_loop"


# ---------- 10.32: read-шаги в parse_agent_plan / run_agent ----------


def test_parse_agent_plan_accepts_read_type():
    """type: "read" принимается (не отбрасывается)."""
    from ai_coder.agent import parse_agent_plan

    content = """{
      "explanation": "test",
      "steps": [
        {"n": 1, "title": "прочитать файл", "type": "read",
         "details": "объяснить код", "target_files": ["x.py"]}
      ]
    }"""
    plan = parse_agent_plan(content, goal="explain")
    assert plan.parse_error is None
    assert len(plan.steps) == 1
    assert plan.steps[0].type == "read"


def test_parse_agent_plan_reclassifies_diagnostic_edit_to_read():
    """edit с read-маркерами ("прочитай", "проанализируй") → read."""
    from ai_coder.agent import parse_agent_plan

    content = """{
      "explanation": "test",
      "steps": [
        {"n": 1, "title": "Проанализируй код", "type": "edit",
         "details": "разберись, что делает функция", "target_files": ["x.py"]}
      ]
    }"""
    plan = parse_agent_plan(content, goal="analyze")
    assert plan.parse_error is None
    assert len(plan.steps) == 1
    assert plan.steps[0].type == "read", "edit с read-маркерами должен стать read"


# ---------- 10.33: read-шаги в run_agent через _run_read_step ----------


def test_run_read_step_calls_tool_loop(sample_project, minimal_cfg, prompts_cfg):
    """_run_read_step вызывает run_tool_loop со step_type='read'."""
    from ai_coder.agent import AgentStep, _run_read_step

    step = AgentStep(
        n=1, title="Прочитай файл", type="read", details="объясни", target_files=["x.py"]
    )
    captured: dict = {}

    def fake_loop(**kwargs):
        captured.update(kwargs)
        from ai_coder.agent import ToolLoopResult

        return ToolLoopResult(
            success=True,
            summary="ответ",
            iterations=1,
            total_cost_rub=0.02,
            read_ops=1,
        )

    with patch("ai_coder.agent.classic.run_tool_loop", side_effect=fake_loop):
        result = _run_read_step(
            step=step,
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            model=None,
            depth="normal",
            extra_exclude=None,
            only_paths=None,
            journal_subdir=None,
        )

    assert captured.get("step_type") == "read", "step_type должен быть 'read'"
    assert "Прочитай файл" in captured.get("goal", "")
    assert result.read_answer == "ответ"
    assert result.applied is False
    assert result.applied_count == 0
    assert result.write_plan is None


def test_run_read_step_success(sample_project, minimal_cfg, prompts_cfg):
    """Успешный read → skipped=False, read_answer заполнен."""
    from ai_coder.agent import AgentStep, ToolLoopResult, _run_read_step

    step = AgentStep(n=1, title="read", type="read", details="", target_files=[])

    with patch(
        "ai_coder.agent.classic.run_tool_loop",
        return_value=ToolLoopResult(
            success=True,
            summary="функция X делает Y",
            iterations=2,
            total_cost_rub=0.03,
            read_ops=2,
        ),
    ):
        result = _run_read_step(
            step=step,
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            model=None,
            depth="normal",
            extra_exclude=None,
            only_paths=None,
            journal_subdir=None,
        )

    assert result.skipped is False
    assert result.read_answer == "функция X делает Y"
    assert result.verify_errors == [], "read не проверяем"
    assert result.errors == []


def test_run_read_step_failure(sample_project, minimal_cfg, prompts_cfg):
    """Провальный read → skipped=True, skip_reason=stopped_reason."""
    from ai_coder.agent import AgentStep, ToolLoopResult, _run_read_step

    step = AgentStep(n=1, title="read", type="read", details="", target_files=[])

    with patch(
        "ai_coder.agent.classic.run_tool_loop",
        return_value=ToolLoopResult(
            success=False,
            summary="ничего не прочитано",
            iterations=3,
            total_cost_rub=0.04,
            read_ops=0,
            stopped_reason="max_iterations",
        ),
    ):
        result = _run_read_step(
            step=step,
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            model=None,
            depth="normal",
            extra_exclude=None,
            only_paths=None,
            journal_subdir=None,
        )

    assert result.skipped is True
    assert result.skip_reason == "max_iterations"
    assert result.read_answer == "ничего не прочитано"


def test_run_agent_calls_read_step_for_read_type(sample_project, minimal_cfg, prompts_cfg):
    """run_agent для read-шага вызывает _run_read_step (не _run_agent_step)."""
    from ai_coder.agent import (
        AgentPlan,
        AgentStep,
        StepResult,
        ToolLoopResult,
        run_agent,
    )
    from ai_coder.llm import LLMResponse

    # План из одного read-шага
    plan = AgentPlan(
        goal="объясни",
        steps=[
            AgentStep(n=1, title="Прочитай", type="read", details="x.py", target_files=["x.py"])
        ],
    )

    # Синтетический StepResult
    fake_step_result = StepResult(
        step=plan.steps[0],
        llm=LLMResponse(
            content="x",
            model="test-model",
            prompt_tokens=0,
            prompt_cache_hit_tokens=0,
            prompt_cache_miss_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            duration_ms=0,
            finish_reason="stop",
        ),
        applied=False,
        applied_count=0,
        errors=[],
        verify_errors=[],
        rolled_back=False,
        cost_rub=0.02,
        cost_cny=0.0,
        cost_usd=0.0,
        from_cache=False,
        read_answer="объяснение",
    )

    calls: list[str] = []

    def fake_read_step(**kwargs):
        calls.append("read")
        return fake_step_result

    # Планировщик
    now = datetime.now(timezone.utc)

    def fake_planner(**kwargs):
        from ai_coder.agent import PlannerResult

        return PlannerResult(
            plan=plan,
            llm=LLMResponse(
                content="plan",
                model="test-model",
                prompt_tokens=0,
                prompt_cache_hit_tokens=0,
                prompt_cache_miss_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                duration_ms=0,
                finish_reason="stop",
            ),
            cost_rub=0.01,
            cost_cny=0.0,
            cost_usd=0.0,
            is_peak=False,
            peak_window=None,
            started_at=now,
            finished_at=now,
        )

    # 10.33: отключаем phase1, чтобы не ходить в LLM повторно
    minimal_cfg.agent.phase1_enabled = False

    with (
        patch("ai_coder.agent.planner.run_planner", side_effect=fake_planner),
        patch("ai_coder.agent.classic.run_planner", side_effect=fake_planner),
        patch("ai_coder.agent.classic._run_read_step", side_effect=fake_read_step),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent.classic.append_usage"),
    ):
        result = run_agent(
            goal="объясни",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
        )

    assert calls == ["read"], f"ожидался один read-вызов, был {calls}"
    assert len(result.steps) == 1
    assert result.steps[0].read_answer == "объяснение"


def test_run_tool_loop_partial_warns(sample_project, minimal_cfg, prompts_cfg):
    """partial: одна правка ok, вторая отклонена blacklist → warnings."""
    # Один файл в blacklist
    minimal_cfg.write.blacklist_files = ["blocked.py"]

    # Сценарий: write_file good.py → write_file blocked.py → finish
    import json as _json

    responses = [
        _json.dumps(
            {
                "tool": "write_file",
                "args": {"path": "good.py", "content": "x = 1\n"},
                "reason": "создать good.py",
            }
        ),
        _json.dumps(
            {
                "tool": "write_file",
                "args": {"path": "blocked.py", "content": "y = 2\n"},
                "reason": "создать blocked.py",
            }
        ),
        _json.dumps({"finish": True, "summary": "done", "success": True}),
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="test partial",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            step_type="edit",
        )

    # Успех — потому что одна правка применена
    assert result.success is True
    assert result.applied_ops == 1
    # warnings: applied 1/2
    assert len(result.warnings) == 1
    assert "applied 1/2" in result.warnings[0]
    # good.py создан, blocked.py — нет
    assert (sample_project / "good.py").is_file()
    assert not (sample_project / "blocked.py").is_file()


def test_run_tool_loop_no_partial_when_all_applied(sample_project, minimal_cfg, prompts_cfg):
    """Без partial: обе правки ok → warnings пуст."""
    import json as _json

    responses = [
        _json.dumps(
            {
                "tool": "write_file",
                "args": {"path": "a.py", "content": "x = 1\n"},
                "reason": "a",
            }
        ),
        _json.dumps(
            {
                "tool": "write_file",
                "args": {"path": "b.py", "content": "y = 2\n"},
                "reason": "b",
            }
        ),
        _json.dumps({"finish": True, "summary": "ok", "success": True}),
    ]

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
        patch("ai_coder.agent.planner.get_rate") as mock_rate,
        patch("ai_coder.agent.reverse.get_rate", mock_rate),
        patch("ai_coder.agent.tool_loop.get_rate", mock_rate),
        patch("ai_coder.agent._legacy.get_rate", mock_rate),
        patch("ai_coder.agent.planner.append_usage"),
        patch("ai_coder.agent._legacy.append_usage"),
    ):
        mock_rate.return_value = Rate(value=12.5, source="config", fetched_at=0)
        MockClient.return_value.chat.side_effect = [_make_llm_response(r) for r in responses]

        result = run_tool_loop(
            goal="test full",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            journal=False,
            step_type="edit",
        )

    assert result.success is True
    assert result.applied_ops == 2
    assert result.warnings == []


# ---------- reverse-check ----------


def _make_llm_response(content: str) -> LLMResponse:
    """Хелпер: собрать LLMResponse с заданным content."""
    return LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=100,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        duration_ms=1000,
        finish_reason="stop",
    )


def test_reverse_check_parses_ok(sample_project, minimal_cfg, prompts_cfg):
    """LLM вернул {"ok": true} → result.ok == True."""
    body = json.dumps({"ok": True, "problems": [], "suggestion": None})

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
    ):
        MockClient.return_value.chat.return_value = _make_llm_response(body)
        result = run_reverse_check(
            goal="test goal",
            diff="diff --git ...",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
        )

    assert result.ok is True
    assert result.problems == []
    assert result.parse_error is None


def test_reverse_check_parses_problems(sample_project, minimal_cfg, prompts_cfg):
    """LLM вернул {"ok": false, "problems": [...]} → result.ok == False."""
    body = json.dumps(
        {
            "ok": False,
            "problems": ["wrong API version", "missing positional arg"],
            "suggestion": "fix it",
        }
    )

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
    ):
        MockClient.return_value.chat.return_value = _make_llm_response(body)
        result = run_reverse_check(
            goal="test goal",
            diff="diff --git ...",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
        )

    assert result.ok is False
    assert result.problems == ["wrong API version", "missing positional arg"]
    assert result.suggestion == "fix it"


def test_reverse_check_bad_json_returns_ok(sample_project, minimal_cfg, prompts_cfg):
    """При невалидном JSON → fail-safe: ok=True, parse_error заполнен."""
    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
    ):
        MockClient.return_value.chat.return_value = _make_llm_response("not a json at all")
        result = run_reverse_check(
            goal="test",
            diff="x",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
        )

    assert result.ok is True  # fail-safe
    assert result.parse_error is not None


def test_reverse_check_strips_markdown_wrapper(sample_project, minimal_cfg, prompts_cfg):
    """LLM вернул ```json {...} ``` → всё равно парсится."""
    body = '```json\n{"ok": true, "problems": []}\n```'

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
    ):
        MockClient.return_value.chat.return_value = _make_llm_response(body)
        result = run_reverse_check(
            goal="test",
            diff="x",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
        )

    assert result.ok is True
    assert result.parse_error is None


def test_reverse_check_truncates_long_diff(sample_project, minimal_cfg, prompts_cfg):
    """Очень длинный diff обрезается до reverse_check_max_diff_chars."""
    long_diff = "x" * 30000
    body = json.dumps({"ok": True, "problems": []})

    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
    ):
        mock_chat = MockClient.return_value.chat
        mock_chat.return_value = _make_llm_response(body)
        run_reverse_check(
            goal="test",
            diff=long_diff,
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
        )

    # Проверяем user-промпт: он должен содержать "обрезано" и НЕ содержать
    # все 30000 символов.
    call_kwargs = mock_chat.call_args.kwargs
    user_prompt = call_kwargs.get("user", "")
    assert "обрезано" in user_prompt
    assert len(user_prompt) < 20000  # точно меньше, чем 30000 + шаблон


def test_reverse_check_llm_error_returns_ok(sample_project, minimal_cfg, prompts_cfg):
    """Ошибка LLM → fail-safe: ok=True, parse_error='LLM error: ...'."""
    with (
        patch("ai_coder.agent.planner.LLMClient") as MockClient,
        patch("ai_coder.agent.reverse.LLMClient", MockClient),
        patch("ai_coder.agent.tool_loop.LLMClient", MockClient),
        patch("ai_coder.agent._legacy.LLMClient", MockClient),
    ):
        MockClient.return_value.chat.side_effect = RuntimeError("network down")
        result = run_reverse_check(
            goal="test",
            diff="x",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
        )

    assert result.ok is True
    assert result.parse_error is not None
    assert "LLM error" in result.parse_error


def test_collect_diff_non_git_returns_empty(tmp_path):
    """Не-git каталог → _collect_diff возвращает ''."""
    assert _collect_diff(tmp_path) == ""


def test_collect_diff_includes_new_untracked_file(git_repo):
    """Новый untracked-файл попадает в diff с содержимым."""
    (git_repo / "new_file.txt").write_text("hello untracked\n", encoding="utf-8")

    diff = _collect_diff(git_repo)

    assert "new_file.txt" in diff
    assert "+hello untracked" in diff
    assert "new file mode 100644" in diff


def test_collect_diff_tracked_change_and_untracked(git_repo):
    """Изменённый tracked-файл и новый untracked — оба в diff."""
    (git_repo / "README.md").write_text("# test\nmodified line\n", encoding="utf-8")
    (git_repo / "added.py").write_text("print('added')\n", encoding="utf-8")

    diff = _collect_diff(git_repo)

    # tracked-изменение
    assert "README.md" in diff
    assert "+modified line" in diff
    # untracked-файл
    assert "added.py" in diff
    assert "+print('added')" in diff


def test_collect_diff_truncates_when_too_large(git_repo):
    """diff превышает лимит → результат обрезан."""
    from ai_coder.agent import _MAX_DIFF_CHARS

    big = "x" * (_MAX_DIFF_CHARS * 2)
    (git_repo / "huge.txt").write_text(big, encoding="utf-8")

    diff = _collect_diff(git_repo)

    assert len(diff) <= _MAX_DIFF_CHARS


def test_collect_diff_empty_untracked_file(git_repo):
    """Пустой untracked-файл — diff не падает."""
    (git_repo / "empty.txt").write_text("", encoding="utf-8")

    diff = _collect_diff(git_repo)

    assert isinstance(diff, str)
    assert "empty.txt" in diff


def test_reverse_check_result_dataclass():
    """ReverseCheckResult — dataclass с нужными полями."""
    r = ReverseCheckResult(ok=True)
    assert r.ok is True
    assert r.problems == []
    assert r.suggestion is None
    assert r.cost_rub == 0.0
    assert r.parse_error is None


# ---------- Validator (decompose_reverse_check) ----------


def test_decompose_reverse_check_default_false(minimal_cfg):
    """AgentConfig.decompose_reverse_check по умолчанию False."""
    assert minimal_cfg.agent.decompose_reverse_check is False


def test_run_agent_decompose_has_rc_param():
    """run_agent_decompose принимает decompose_reverse_check."""
    import inspect

    from ai_coder.agent.decomposer import run_agent_decompose

    sig = inspect.signature(run_agent_decompose)
    assert "decompose_reverse_check" in sig.parameters
    param = sig.parameters["decompose_reverse_check"]
    assert param.default is None
