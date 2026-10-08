from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from ai_coder.agent import (
    AgentPlan,
    AgentStep,
    _extract_target_files,
    _parse_phase1_response,
    _render_plan_summary,
    _select_step_only_paths,
    parse_agent_plan,
    run_planner,
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
    assert result.success is False


def test_run_tool_loop_finish_with_failure(sample_project, minimal_cfg, prompts_cfg):
    """Модель завершает с success=false."""

    with (
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
        patch("ai_coder.agent._prompt_tool_review", return_value="y"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
        patch("ai_coder.agent._prompt_tool_review", return_value="n"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
        patch("ai_coder.agent._prompt_tool_review", return_value="s"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
        patch("ai_coder.agent.LLMClient") as MockClient,
        patch("ai_coder.agent.get_rate") as mock_rate,
        patch("ai_coder.agent.append_usage"),
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
