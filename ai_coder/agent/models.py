"""Dataclass-ы агента ai_coder.

Вынесено из agent/_legacy.py (10.65.2 split-file).
Порядок: сначала простые, затем зависимые от них.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..llm import LLMResponse

if TYPE_CHECKING:
    from ..apply import WritePlan
    from ..tools import ToolAction, ToolResult


# ---------- простые (без зависимостей) ----------


@dataclass
class AgentStep:
    n: int
    title: str
    type: str  # "edit" (пока единственный)
    details: str
    target_files: list[str] = field(default_factory=list)


@dataclass
class Subtask:
    """Одна подзадача в декомпозиции."""

    n: int
    goal: str
    files: list[str] = field(default_factory=list)


@dataclass
class ReverseCheckResult:
    """Результат reverse-check: проверка diff на соответствие goal."""

    ok: bool
    problems: list[str] = field(default_factory=list)
    suggestion: str | None = None
    cost_rub: float = 0.0
    cost_cny: float = 0.0
    cost_usd: float = 0.0
    raw_response: str = ""
    parse_error: str | None = None


@dataclass
class SplitIssue:
    """Одна независимая задача из --split-goals."""

    n: int
    title: str
    goal: str


@dataclass
class AutoFixResult:
    """Результат auto-fix."""

    success: bool = False
    attempts: int = 0
    total_cost_rub: float = 0.0
    total_cost_cny: float = 0.0
    total_cost_usd: float = 0.0
    initial_errors: list[str] = field(default_factory=list)
    final_errors: list[str] = field(default_factory=list)
    journal_dir: Path | None = None
    stopped_reason: str = "completed"


# ---------- зависимые от простых ----------


@dataclass
class AgentPlan:
    goal: str
    explanation: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    parse_error: str | None = None
    empty: bool = False
    raw_json: str = ""

    @property
    def valid(self) -> bool:
        return self.parse_error is None and bool(self.steps)


@dataclass
class ReplanResult:
    """Результат перепланирования при провале подзадачи."""

    action: str = "stop"  # "skip" | "modify" | "stop"
    explanation: str = ""
    new_subtasks: list[Subtask] = field(default_factory=list)
    llm: LLMResponse | None = None
    cost_rub: float = 0.0
    cost_cny: float = 0.0
    cost_usd: float = 0.0
    parse_error: str | None = None
    raw_json: str = ""


@dataclass
class DecomposeResult:
    """Результат декомпозиции большой задачи."""

    explanation: str = ""
    subtasks: list[Subtask] = field(default_factory=list)
    parse_error: str | None = None
    raw_json: str = ""
    llm: LLMResponse | None = None
    cost_rub: float = 0.0
    cost_cny: float = 0.0
    cost_usd: float = 0.0
    skipped_subtasks: list[Subtask] = field(default_factory=list)
    journal_dir: Path | None = None
    subtask_results: list[dict] = field(default_factory=list)
    rolled_back: bool = False


@dataclass
class SplitGoalsResult:
    """Результат --split-goals."""

    issues: list[SplitIssue] = field(default_factory=list)
    parse_error: str | None = None
    raw_json: str = ""
    llm: LLMResponse | None = None
    cost_rub: float = 0.0
    cost_cny: float = 0.0
    cost_usd: float = 0.0
    output_dir: Path | None = None


# ---------- зависимые от LLMResponse ----------


@dataclass
class PlannerResult:
    plan: AgentPlan
    llm: LLMResponse
    cost_rub: float
    cost_cny: float
    cost_usd: float
    is_peak: bool
    peak_window: str | None
    started_at: datetime
    finished_at: datetime


@dataclass
class PlannerPhase1Result:
    """Результат phase1: какие файлы затронет задача."""

    target_files: list[str]
    llm: LLMResponse | None  # None при cache hit
    cost_rub: float
    cost_cny: float
    cost_usd: float
    parse_error: str | None = None
    from_cache: bool = False


@dataclass
class StepResult:
    step: AgentStep
    llm: LLMResponse
    applied: bool
    applied_count: int
    errors: list[str]
    verify_errors: list[str]
    rolled_back: bool
    cost_rub: float
    cost_cny: float
    cost_usd: float
    from_cache: bool
    write_plan: "WritePlan | None" = None
    skipped: bool = False
    skip_reason: str = ""
    read_answer: str = ""  # 10.33: текстовый ответ read-шага (step_type="read")


@dataclass
class AgentRunResult:
    goal: str
    plan: AgentPlan
    planner_llm: LLMResponse
    planner_cost_rub: float
    planner_cost_cny: float
    planner_cost_usd: float
    steps: list[StepResult]
    started_at: datetime
    finished_at: datetime
    stopped_reason: str = "completed"
    # completed | max_iterations | max_cost | parse_error | error | cancelled
    journal_dir: Path | None = None

    @property
    def total_cost_rub(self) -> float:
        return self.planner_cost_rub + sum(s.cost_rub for s in self.steps)


# ---------- зависимые от ToolAction, ToolResult ----------


@dataclass
class ToolLoopResult:
    success: bool
    summary: str
    iterations: int
    history: list[tuple[ToolAction, ToolResult]] = field(default_factory=list)
    total_cost_rub: float = 0.0
    total_cost_cny: float = 0.0
    total_cost_usd: float = 0.0
    stopped_reason: str = "completed"
    journal_dir: Path | None = None
    dry_run: bool = False
    backup_dir: Path | None = None
    commit_hash: str | None = None  # NEW
    verify_errors: list[str] = field(default_factory=list)
    applied_ops: int = 0  # NEW: число успешных write_file/edit_file
    read_ops: int = 0  # NEW: число успешных read_file/read_symbol/list_files
    warnings: list[str] = field(default_factory=list)  # NEW: partial / blacklist
    reverse_check_result: ReverseCheckResult | None = None  # NEW


__all__ = [
    "AgentStep",
    "AgentPlan",
    "Subtask",
    "DecomposeResult",
    "ReplanResult",
    "ReverseCheckResult",
    "ToolLoopResult",
    "SplitIssue",
    "SplitGoalsResult",
    "PlannerResult",
    "PlannerPhase1Result",
    "StepResult",
    "AgentRunResult",
    "AutoFixResult",
]
