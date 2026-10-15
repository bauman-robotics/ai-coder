from __future__ import annotations

from rich.console import Console

# Импорты для совместимости с патчами в тестах (10.65.6).
# Убираются в 10.65.8 вместе с _legacy.py.
from ..apply import run_verify_commands  # noqa: F401
from ..llm import LLMClient  # noqa: F401
from ..pricing import get_rate  # noqa: F401
from ..scanner import scan_project_metadata  # noqa: F401
from ..usage import append_usage  # noqa: F401

# --- dataclass-ы вынесены в models.py (10.65.2 split-file) ---
from .models import (
    AgentPlan,
    AgentRunResult,
    AgentStep,
    AutoFixResult,
    DecomposeResult,
    PlannerPhase1Result,
    PlannerResult,
    ReplanResult,
    ReverseCheckResult,
    SplitGoalsResult,
    SplitIssue,
    StepResult,
    Subtask,
    ToolLoopResult,
)

# --- парсеры/хелперы вынесены в planner.py (10.65.3a split-file) ---
# --- reverse-check вынесен в reverse.py (10.65.4a split-file) ---
# --- tool loop вынесен в tool_loop.py (10.65.4b split-file) ---
from .tool_loop import _prompt_tool_review, run_tool_loop  # noqa: F401

# ---------- структуры ----------

_console = Console()


def _select_step_only_paths(
    *,
    idx: int,
    is_single_step: bool,
    auto_targets: list[str],
    auto_enabled: bool,
) -> list[str] | None:
    """
    Возвращает only_paths для шага или None (полный контекст).

    Одношаговый план: сужаем шаг 1 (idx == 0).
    Многошаговый: шаг 1 — полный, шаги 2+ — сужены.
    """
    if not auto_enabled or not auto_targets:
        return None
    if idx > 0 or is_single_step:
        return auto_targets
    return None


# ---------- парсинг плана ----------
# ---------- запрос плана у LLM ----------
# Транслит кириллицы для slug (минимальный, только строчные + прописные)
# ---------- кэш phase1 ----------
# ---------- журнал агента ----------
# ---------- декомпозиция задач ----------
# ---------- split-goals (10F) ----------
# ---------- исполнитель одного шага ----------
# ---------- рендер вспомогательных текстов ----------
# ---------- with-tests: извлечение изменённых файлов ----------
# ---------- главный цикл ----------
# ---------- сохранение журнала ----------
# history.json обновляется отдельно в run_tool_loop
__all__ = [
    "AgentPlan",
    "AgentRunResult",
    "AgentStep",
    "AutoFixResult",
    "DecomposeResult",
    "PlannerPhase1Result",
    "PlannerResult",
    "ReplanResult",
    "ReverseCheckResult",
    "SplitGoalsResult",
    "SplitIssue",
    "StepResult",
    "Subtask",
    "ToolLoopResult",
    "_console",
    "_select_step_only_paths",
]
