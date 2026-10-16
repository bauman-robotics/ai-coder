"""D8: проброс `type` подзадачи в `step_type` (decompose).

До D8 decomposer передавал всем подзадачам `step_type="edit"`, а
`_handle_finish` при "edit" требует `applied_ops > 0`. Поэтому
подзадачи `explore` (только читает) и `verify` (только запускает тесты)
не могли завершиться успешно в принципе.
"""

from __future__ import annotations

from unittest.mock import patch

from ai_coder.agent.decomposer import _step_type_for, run_agent_decompose
from ai_coder.agent.models import DecomposeResult, Subtask, ToolLoopResult

# ---------- юнит: _step_type_for ----------


def _st(t: str) -> Subtask:
    return Subtask(n=1, goal="g", type=t)


def test_step_type_explore_is_read():
    assert _step_type_for(_st("explore")) == "read"


def test_step_type_verify_is_none():
    """verify → None: критерий успеха — finish модели.

    Отдельный `step_type="verify"` не заводим: он потребовал бы своего
    критерия, а роль «проверить» уже закрывается verify_commands
    в конце tool loop (pytest).
    """
    assert _step_type_for(_st("verify")) is None


def test_step_type_edit_variants():
    assert _step_type_for(_st("edit")) == "edit"
    assert _step_type_for(_st("edit-simple")) == "edit"
    assert _step_type_for(_st("edit-complex")) == "edit"


def test_step_type_unknown_is_edit():
    """Неизвестный тип → "edit" (как и фолбэк _resolve_subagent)."""
    assert _step_type_for(_st("")) == "edit"
    assert _step_type_for(_st("nonsense")) == "edit"


# ---------- поведенческий: что реально уходит в run_tool_loop ----------


def _run(cfg, prompts_cfg, project_root, subtasks, captured):
    def fake_loop(**kwargs):
        captured.append({"goal": kwargs.get("goal"), "step_type": kwargs.get("step_type")})
        return ToolLoopResult(success=True, summary="ok", iterations=1)

    plan = DecomposeResult(subtasks=subtasks)
    with patch("ai_coder.agent.decomposer.run_tool_loop", fake_loop):
        return run_agent_decompose(
            goal="big",
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            plan=plan,
            journal=False,
        )


def test_decompose_passes_step_type_per_subtask(minimal_cfg, prompts_cfg, sample_project):
    captured: list[dict] = []
    _run(
        minimal_cfg,
        prompts_cfg,
        sample_project,
        [
            Subtask(n=1, goal="исследуй", type="explore"),
            Subtask(n=2, goal="правь", type="edit-simple"),
            Subtask(n=3, goal="прогони тесты", type="verify"),
        ],
        captured,
    )

    assert [c["step_type"] for c in captured] == ["read", "edit", None]


def test_decompose_retry_uses_same_step_type(minimal_cfg, prompts_cfg, sample_project):
    """Retry через v4-pro не должен возвращать step_type="edit"."""
    captured: list[dict] = []

    def fake_loop(**kwargs):
        captured.append({"step_type": kwargs.get("step_type")})
        # первая попытка падает → должен случиться retry
        success = len(captured) > 1
        return ToolLoopResult(
            success=success, summary="s", iterations=1, stopped_reason="completed"
        )

    minimal_cfg.agent.decompose_model = "deepseek-v4-pro"
    plan = DecomposeResult(subtasks=[Subtask(n=1, goal="прогони тесты", type="verify")])
    with patch("ai_coder.agent.decomposer.run_tool_loop", fake_loop):
        run_agent_decompose(
            goal="big",
            project_root=sample_project,
            cfg=minimal_cfg,
            prompts_cfg=prompts_cfg,
            plan=plan,
            journal=False,
        )

    assert len(captured) == 2, "ожидался retry"
    assert [c["step_type"] for c in captured] == [None, None]


# ---------- ROOT CAUSE: парсер не пропускал типы Router ----------


def test_parser_preserves_router_types():
    """D8: parse_decompose_response обязан сохранять типы Router (10.70).

    До D8 whitelist был ("edit", "read"), поэтому explore / edit-simple /
    edit-complex / verify приводились к "edit" — Router не работал.
    """
    import json

    from ai_coder.agent.planner import parse_decompose_response

    content = json.dumps(
        {
            "explanation": "e",
            "subtasks": [
                {"n": 1, "type": "explore", "goal": "изучи", "files": []},
                {"n": 2, "type": "edit-simple", "goal": "правь", "files": ["a.py"]},
                {"n": 3, "type": "edit-complex", "goal": "сложно", "files": ["b.py"]},
                {"n": 4, "type": "verify", "goal": "тесты", "files": []},
            ],
        }
    )
    result = parse_decompose_response(content)

    assert result.parse_error is None
    assert [s.type for s in result.subtasks] == [
        "explore",
        "edit-simple",
        "edit-complex",
        "verify",
    ]


def test_parser_keeps_legacy_types_and_rejects_unknown():
    import json

    from ai_coder.agent.planner import parse_decompose_response

    content = json.dumps(
        {
            "subtasks": [
                {"n": 1, "type": "EDIT", "goal": "g1", "files": []},
                {"n": 2, "type": "read", "goal": "g2", "files": []},
                {"n": 3, "type": "nonsense", "goal": "g3", "files": []},
                {"n": 4, "goal": "g4", "files": []},
            ]
        }
    )
    result = parse_decompose_response(content)

    # регистр нормализуется, legacy "read" сохраняется, мусор → "edit"
    assert [s.type for s in result.subtasks] == ["edit", "read", "edit", "edit"]


def test_step_type_for_legacy_read():
    assert _step_type_for(_st("read")) == "read"


def test_router_type_flows_to_step_type_end_to_end(minimal_cfg, prompts_cfg, sample_project):
    """Полный путь: JSON планировщика → type → step_type в run_tool_loop."""
    import json

    from ai_coder.agent.planner import parse_decompose_response

    parsed = parse_decompose_response(
        json.dumps(
            {
                "subtasks": [
                    {"n": 1, "type": "explore", "goal": "изучи", "files": []},
                    {"n": 2, "type": "edit-complex", "goal": "правь", "files": ["a.py"]},
                    {"n": 3, "type": "verify", "goal": "прогони тесты", "files": []},
                ]
            }
        )
    )
    captured: list[dict] = []
    _run(minimal_cfg, prompts_cfg, sample_project, parsed.subtasks, captured)

    assert [c["step_type"] for c in captured] == ["read", "edit", None]
