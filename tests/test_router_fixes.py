"""D10: фиксы Router — fallback по pricing (баг A) и лимиты итераций (баг B).

Баг A: `_resolve_subagent` возвращал захардкоженные deepseek-flash /
deepseek-v4-pro, не проверяя наличие цен → `KeyError` в СЕРЕДИНЕ прогона
(в `_estimate_next_cost_rub` и `calculate_cost`).

Баг B: `--max-iterations` имел default 20 (не None) и всегда перекрывал
лимиты Router (explore 5 / edit-simple 10 / edit-complex 15 / verify 5).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ai_coder.agent.decomposer import _resolve_subagent, run_agent_decompose
from ai_coder.agent.models import DecomposeResult, Subtask, ToolLoopResult
from ai_coder.agent.planner import _estimate_next_cost_rub
from ai_coder.cli import _iters_or_default
from ai_coder.config import AppConfig, load_config
from ai_coder.pricing import Rate

REPO = Path(__file__).resolve().parent.parent


def _st(t: str) -> Subtask:
    return Subtask(n=1, goal="g", type=t)


def _cfg_without(cfg: AppConfig, model: str) -> AppConfig:
    """Копия конфига без цен для указанной модели.

    Заодно убираем subagent'ов на эту модель: валидатор D6 не пропустит
    конфиг, где модель subagent'а не оценена (это его штатное поведение —
    и как раз та самая последовательность, которой не хватало Router).
    """
    data = cfg.model_dump()
    data["api"]["pricing"].pop(model, None)
    assert model not in data["api"]["pricing"], f"{model} не было в pricing и так"
    data["agent"]["subagents"] = [s for s in data["agent"]["subagents"] if s.get("model") != model]
    return AppConfig.model_validate(data)


# ---------- Баг A: fallback по pricing ----------


def test_resolve_subagent_uses_router_model_when_priced():
    """Реальный конфиг: Router отдаёт свои модели, если цены есть."""
    cfg = load_config(REPO / "config" / "config.yaml")
    assert _resolve_subagent(_st("explore"), cfg)[0] == "deepseek-flash"
    assert _resolve_subagent(_st("edit-complex"), cfg)[0] == "deepseek-v4-pro"
    assert _resolve_subagent(_st("verify"), cfg)[0] == "deepseek-flash"


def test_resolve_subagent_falls_back_when_model_not_priced():
    """Нет цен для v4-pro → базовая модель, а НЕ KeyError."""
    cfg = load_config(REPO / "config" / "config.yaml")
    cfg = _cfg_without(cfg, "deepseek-v4-pro")

    model, iters = _resolve_subagent(_st("edit-complex"), cfg)

    assert model == cfg.api.model  # fallback
    assert model in cfg.api.pricing  # и он точно оценён
    assert iters == 15  # лимит итераций не меняется


def test_resolve_subagent_fallback_prints_warning(capsys):
    cfg = load_config(REPO / "config" / "config.yaml")
    cfg = _cfg_without(cfg, "deepseek-v4-pro")

    _resolve_subagent(_st("edit-complex"), cfg)

    out = capsys.readouterr().out
    assert "deepseek-v4-pro" in out
    assert "базовую" in out or "fallback" in out.lower()


def test_bug_a_no_keyerror_in_budget_precheck():
    """Регрессия бага A: раньше precheck падал KeyError в середине прогона."""
    cfg = load_config(REPO / "config" / "config.yaml")
    cfg = _cfg_without(cfg, "deepseek-v4-pro")
    rate = Rate(12.5, "config", 0)

    # до фикса: _estimate_next_cost_rub(cfg, "deepseek-v4-pro", ...) → KeyError
    with pytest.raises(KeyError):
        _estimate_next_cost_rub(cfg, "deepseek-v4-pro", "s", "u", rate)

    # после фикса резолвер не отдаёт неоценённую модель
    model, _ = _resolve_subagent(_st("edit-complex"), cfg)
    assert _estimate_next_cost_rub(cfg, model, "s", "u", rate) >= 0.0


def test_resolve_subagent_unknown_type_uses_edit_simple():
    """Неизвестный type → edit-simple (фолбэк Router), а не падение."""
    cfg = load_config(REPO / "config" / "config.yaml")
    model, iters = _resolve_subagent(_st("nonsense"), cfg)
    assert model == "deepseek-flash"  # edit-simple → flash
    assert iters == 10


# ---------- Баг B: лимиты итераций ----------


def test_iters_or_default():
    assert _iters_or_default(None) == 20
    assert _iters_or_default(7) == 7
    assert _iters_or_default(0) == 0


def _capture_iters(cfg, prompts_cfg, project_root, subtasks, **kwargs):
    captured: list[dict] = []

    def fake_loop(**kw):
        captured.append({"goal": kw.get("goal"), "max_iterations": kw.get("max_iterations")})
        return ToolLoopResult(success=True, summary="ok", iterations=1)

    plan = DecomposeResult(subtasks=subtasks)
    with patch("ai_coder.agent.decomposer.run_tool_loop", fake_loop):
        run_agent_decompose(
            goal="big",
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            plan=plan,
            journal=False,
            **kwargs,
        )
    return captured


_SUBTASKS = [
    Subtask(n=1, goal="explore", type="explore"),
    Subtask(n=2, goal="simple", type="edit-simple"),
    Subtask(n=3, goal="complex", type="edit-complex"),
    Subtask(n=4, goal="verify", type="verify"),
]


def test_router_iters_applied_when_max_iterations_none(minimal_cfg, prompts_cfg, sample_project):
    """Баг B: при max_iterations=None действуют лимиты Router."""
    captured = _capture_iters(
        minimal_cfg, prompts_cfg, sample_project, list(_SUBTASKS), max_iterations=None
    )
    assert [c["max_iterations"] for c in captured] == [5, 10, 15, 5]


def test_explicit_max_iterations_wins(minimal_cfg, prompts_cfg, sample_project):
    """Явный --max-iterations N перекрывает лимиты Router (как и раньше)."""
    captured = _capture_iters(
        minimal_cfg, prompts_cfg, sample_project, list(_SUBTASKS), max_iterations=7
    )
    assert [c["max_iterations"] for c in captured] == [7, 7, 7, 7]


def test_verify_subtask_gets_three_iterations(minimal_cfg, prompts_cfg, sample_project):
    """Acceptance D10/D10.1: verify получает лимит 5.

    5 = «K вызовов pytest + 1 итерация на finish»: при 3 модель
    тратила все итерации на run_shell и не успевала finish (баг C).
    """
    captured = _capture_iters(
        minimal_cfg,
        prompts_cfg,
        sample_project,
        [Subtask(n=1, goal="прогони тесты", type="verify")],
        max_iterations=None,
    )
    assert captured[0]["max_iterations"] == 5
