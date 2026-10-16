"""Subagents (Направление 12, D4).

Оркестрация spawn_subagent: родительский tool loop делегирует подцель
настроенному subagent'у (отдельный run_tool_loop со своим контекстом).

Вынесено в отдельный модуль, чтобы разорвать цикл импортов:
`tools.py` ← `tool_loop.py`, а этот модуль импортирует `run_tool_loop`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..config import SubagentConfig
from ..tools import ToolResult
from .tool_loop import run_tool_loop

if TYPE_CHECKING:
    from .models import ToolLoopResult
    from .tool_loop import _ToolLoopCtx

__all__ = [
    "build_subagents_section",
    "run_spawn_subagent",
    "summarize_subagent_result",
]

# Инструменты, меняющие файлы, — по ним решаем, нужен ли subagent'у verify.
_WRITE_TOOLS = ("write_file", "edit_file")


def build_subagents_section(subagents: list[SubagentConfig]) -> str:
    """Markdown-секция со списком subagents для промпта родителя.

    Пусто → "" (тогда инструмент spawn_subagent вообще не рекламируется).
    """
    if not subagents:
        return ""

    lines = ["## ДОСТУПНЫЕ SUBAGENTS (инструмент spawn_subagent)", ""]
    for s in subagents:
        lines.append(f"- {s.name} — {s.description}")
        lines.append(f"  tools: {', '.join(s.tools)}")
    return "\n".join(lines).rstrip()


def _remaining_budget(ctx: _ToolLoopCtx) -> float | None:
    """Сколько родителю осталось до своего max_cost_rub (None — без лимита)."""
    if ctx.max_cost_rub is None:
        return None
    return ctx.max_cost_rub - ctx.total_cost_rub


def _spawn_cap(ctx: _ToolLoopCtx, spec: SubagentConfig) -> float:
    """Лимит стоимости одного spawn — минимум из всех ограничений."""
    agent = ctx.cfg.agent
    per_spawn = (
        spec.max_cost_rub if spec.max_cost_rub is not None else agent.subagent_default_max_cost_rub
    )
    candidates = [per_spawn, agent.subagent_max_total_cost_rub - ctx.spawn_cost_rub]
    remaining = _remaining_budget(ctx)
    if remaining is not None:
        candidates.append(remaining)
    return min(candidates)


def _is_read_only(spec: SubagentConfig) -> bool:
    return not any(t in _WRITE_TOOLS for t in spec.tools)


def summarize_subagent_result(
    spec: SubagentConfig,
    res: ToolLoopResult,
    cap_chars: int = 1500,
) -> str:
    """Краткая выжимка результата subagent'а для родителя.

    Только digest: история ребёнка в родителя НЕ попадает (изоляция
    контекста). При провале выжимка явно провальная — иначе родитель
    решит, что делегирование удалось.
    """
    mark = "✅" if res.success else "❌"
    parts = [
        f"[subagent {spec.name}] {mark} {res.stopped_reason}, "
        f"{res.iterations} итер, {res.total_cost_rub:.4f} RUB",
        f"summary: {res.summary[:300]}",
    ]
    if res.applied_ops:
        parts.append(f"изменений: {res.applied_ops}")
    if res.read_ops:
        parts.append(f"прочитано: {res.read_ops}")
    if res.verify_errors:
        parts.append("verify: " + "; ".join(res.verify_errors[:3]))
    if res.journal_dir:
        parts.append(f"журнал: {res.journal_dir.name}")
    return "\n".join(parts)[:cap_chars]


def run_spawn_subagent(ctx: _ToolLoopCtx, args: dict) -> ToolResult:
    """Исполняет spawn_subagent внутри родительского tool loop.

    Бюджет — fail-closed (spawn отклоняется), сам subagent — fail-open
    (его провал не роняет родителя, а возвращается как ok=False).
    """
    name = str(args.get("name", "")).strip()
    goal = str(args.get("goal", "")).strip()

    # --- guard: depth (subagent не может спавнить) ---
    if ctx.spawn_depth > 0:
        return ToolResult(ok=False, error="вложенный spawn запрещён (depth=1)")

    # --- guard: interactive (subagent повиснет на prompt без TTY) ---
    if ctx.interactive:
        return ToolResult(ok=False, error="spawn недоступен в interactive-режиме")

    # --- spec ---
    spec = ctx.subagents_by_name.get(name)
    if spec is None:
        available = ", ".join(sorted(ctx.subagents_by_name)) or "(нет)"
        return ToolResult(ok=False, error=f"unknown subagent: {name!r}. Доступные: {available}")

    # --- guard: лимит spawn на задачу ---
    if ctx.spawn_count >= ctx.max_spawns:
        return ToolResult(
            ok=False,
            error=f"spawn-лимит исчерпан ({ctx.spawn_count}/{ctx.max_spawns})",
        )

    # --- guard: осмысленность goal ---
    if len(goal) < 10:
        return ToolResult(ok=False, error="goal слишком короткий (нужно >= 10 символов)")
    if " ".join(goal.lower().split()) == " ".join(ctx.goal.lower().split()):
        return ToolResult(
            ok=False,
            error="goal совпадает с задачей родителя — сделай это сам, без spawn",
        )

    # --- бюджет: fail-closed ---
    cap = _spawn_cap(ctx, spec)
    if cap <= 0:
        return ToolResult(ok=False, error="бюджет исчерпан — spawn запрещён (fail-closed)")

    sub_goal = goal
    if spec.instructions:
        sub_goal = f"{goal}\n\n[ИНСТРУКЦИЯ]\n{spec.instructions}"

    read_only = _is_read_only(spec)

    # Журнал ребёнка — внутри родительского: <parent>/spawn-<name>/tool-loop-<ts>/
    journal_subdir: Path | None = None
    if ctx.journal_dir is not None:
        journal_subdir = ctx.journal_dir / f"spawn-{spec.name}"

    try:
        sub = run_tool_loop(
            goal=sub_goal,
            project_root=ctx.project_root,
            cfg=ctx.cfg,
            prompts_cfg=ctx.prompts_cfg,
            model=spec.model or ctx.cfg.api.model,
            depth=ctx.depth,
            extra_exclude=ctx.extra_exclude,
            max_iterations=spec.max_iterations,
            max_cost_rub=cap,
            journal=journal_subdir is not None,
            journal_subdir=journal_subdir,
            dry_run=ctx.dry_run,
            dry_read=ctx.dry_read,
            interactive=ctx.interactive,
            allow_blacklist=ctx.allow_blacklist,
            allowed_tools=spec.tools,
            spawn_depth=ctx.spawn_depth + 1,
            usage_action_prefix=f"agent:spawn:{spec.name}",
            # read-only subagent'у pytest не нужен — это потерянные минуты.
            verify_commands=[] if read_only else ctx.verify_commands,
        )
    except Exception as e:  # noqa: BLE001 — fail-open: родитель не должен падать
        return ToolResult(ok=False, error=f"spawn crashed: {type(e).__name__}: {e}")

    # --- стоимость в родителя, немедленно (до его postcheck бюджета) ---
    ctx.total_cost_rub += sub.total_cost_rub
    ctx.total_cost_cny += sub.total_cost_cny
    ctx.total_cost_usd += sub.total_cost_usd
    ctx.spawn_count += 1
    ctx.spawn_cost_rub += sub.total_cost_rub

    # Баг 1 (D4 §7): без этого explorer-родитель не пройдёт _handle_finish
    # (step_type="edit" требует applied_ops > 0).
    if sub.success:
        if sub.applied_ops > 0:
            ctx.applied_ops += 1
        if sub.read_ops > 0:
            ctx.read_ops += 1

    digest = summarize_subagent_result(spec, sub)
    return ToolResult(ok=sub.success, output=digest, error="" if sub.success else digest)
