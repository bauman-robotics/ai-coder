"""Subagents (Направление 12, D4).

Оркестрация spawn_subagent: родительский tool loop делегирует подцель
настроенному subagent'у (отдельный run_tool_loop со своим контекстом).

Вынесено в отдельный модуль, чтобы разорвать цикл импортов:
`tools.py` ← `tool_loop.py`, а этот модуль импортирует `run_tool_loop`.
"""

from __future__ import annotations

from ..config import SubagentConfig

__all__ = [
    "build_subagents_section",
]


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
