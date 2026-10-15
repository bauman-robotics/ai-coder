"""Auto-fix агента ai_coder.

Цикл verify → fix (tool loop) → verify.
Вынесено из agent/_legacy.py (10.65.7 split-file).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from ..apply import run_verify_commands
from ..config import AppConfig, PromptsConfig
from .models import AutoFixResult
from .tool_loop import run_tool_loop

_console = Console()


def run_auto_fix(
    *,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    verify_commands: list[str] | None = None,
    max_attempts: int = 3,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    journal: bool = True,
    interactive: bool = False,
    max_cost_rub: float | None = None,
    allow_blacklist: bool = False,  # NEW: обход blacklist (opt-in)
) -> AutoFixResult:
    """
    Цикл: verify → fix (tool loop) → verify → ...
    """
    verify_commands = verify_commands or cfg.agent.verify_commands
    if not verify_commands:
        return AutoFixResult(
            success=False,
            stopped_reason="no_verify_commands",
        )

    result = AutoFixResult()
    started_at = datetime.now(ZoneInfo("UTC"))

    journal_dir: Path | None = None
    if journal:
        ts = started_at.strftime("%Y-%m-%dT%H-%M-%S")
        journal_dir = project_root / cfg.output.dir / project_root.name / f"autofix-{ts}"
        journal_dir.mkdir(parents=True, exist_ok=True)
        result.journal_dir = journal_dir

    for attempt in range(1, max_attempts + 1):
        _console.print(f"[dim]Попытка {attempt}/{max_attempts}: проверка...[/dim]")
        errors = run_verify_commands(
            verify_commands,
            project_root,
            timeout_sec=cfg.agent.verify_timeout_sec,
            max_output_chars=cfg.agent.verify_max_output_chars,
        )

        if attempt == 1:
            result.initial_errors = list(errors)

        if not errors:
            result.success = True
            result.attempts = attempt
            result.final_errors = []
            if journal_dir is not None:
                _save_auto_fix_report(journal_dir, result, verify_commands)
            return result

        errors_text = "\n".join(errors[:20])
        goal = (
            f"Исправь ошибки, найденные проверкой:\n\n"
            f"{errors_text}\n\n"
            f"После исправления — верни finish(success=true)."
        )
        _console.print(f"[yellow]Ошибок: {len(errors)}. Запускаю fix через tool loop...[/yellow]")

        subdir: Path | None = None
        if journal_dir is not None:
            subdir = journal_dir / f"attempt-{attempt}"

        # Остаток бюджета: сколько ещё можно потратить в этой попытке.
        # max_cost_rub — общий лимит на весь run_auto_fix.
        remaining_budget: float | None = None
        if max_cost_rub is not None:
            remaining_budget = max(0.0, max_cost_rub - result.total_cost_rub)

        loop_result = run_tool_loop(
            goal=goal,
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            model=model,
            depth=depth,
            extra_exclude=extra_exclude,
            max_iterations=cfg.agent.max_steps,
            interactive=interactive,
            journal=journal,
            journal_subdir=subdir,
            max_cost_rub=remaining_budget,
            allow_blacklist=allow_blacklist,
        )
        result.total_cost_rub += loop_result.total_cost_rub
        result.total_cost_cny += loop_result.total_cost_cny
        result.total_cost_usd += loop_result.total_cost_usd

        # Бюджет исчерпан — останавливаемся, не делаем следующую попытку.
        if max_cost_rub is not None and result.total_cost_rub >= max_cost_rub:
            result.stopped_reason = "max_cost"
            result.final_errors = errors
            result.attempts = attempt
            if journal_dir is not None:
                _save_auto_fix_report(journal_dir, result, verify_commands)
            return result

        if not loop_result.success:
            result.stopped_reason = "loop_failed"
            result.final_errors = errors
            result.attempts = attempt
            if journal_dir is not None:
                _save_auto_fix_report(journal_dir, result, verify_commands)
            return result

    # достигли max_attempts — финальная проверка
    result.attempts = max_attempts
    result.stopped_reason = "max_attempts"
    result.final_errors = run_verify_commands(
        verify_commands,
        project_root,
        timeout_sec=cfg.agent.verify_timeout_sec,
        max_output_chars=cfg.agent.verify_max_output_chars,
    )
    if not result.final_errors:
        result.success = True
        result.stopped_reason = "completed"
    if journal_dir is not None:
        _save_auto_fix_report(journal_dir, result, verify_commands)
    return result


def _save_auto_fix_report(
    journal_dir: Path,
    result: AutoFixResult,
    verify_commands: list[str],
) -> None:
    """Сохраняет отчёт auto-fix."""
    lines: list[str] = []
    lines.append("# Auto-fix\n")
    lines.append(f"- **Успех:** {result.success}")
    lines.append(f"- **Попыток:** {result.attempts}")
    lines.append(f"- **Стоимость:** {result.total_cost_rub:.4f} RUB")
    lines.append(f"- **Причина остановки:** {result.stopped_reason}")
    lines.append("")
    lines.append("## Проверки\n")
    for c in verify_commands:
        lines.append(rf"- \`{c}\`")
    lines.append("")
    if result.initial_errors:
        lines.append(f"## Начальные ошибки ({len(result.initial_errors)})\n")
        for e in result.initial_errors[:10]:
            lines.append(f"- {e}")
        lines.append("")
    if result.final_errors:
        lines.append(f"## Финальные ошибки ({len(result.final_errors)})\n")
        for e in result.final_errors[:10]:
            lines.append(f"- {e}")
    (journal_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    "_save_auto_fix_report",
    "run_auto_fix",
]
