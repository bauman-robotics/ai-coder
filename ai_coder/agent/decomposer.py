"""Decomposer агента ai_coder.

Декомпозиция задач + split-goals.
Вынесено из agent/_legacy.py (10.65.5 split-file).
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from ..config import AppConfig, PromptsConfig
from ..llm import LLMClient
from ..pricing import calculate_cost, get_rate, is_peak_now
from ..prompts import render_prompt
from ..scanner import (
    ScanResult,
    render_metadata_block,
    scan_project_metadata,
)
from ..usage import append_usage
from .models import DecomposeResult, SplitGoalsResult, Subtask
from .planner import (
    _slug_for_issue,
    parse_split_goals_response,
    run_planner_decompose,
    run_planner_replan,
)
from .reverse import _collect_subtask_diff, run_reverse_check
from .tool_loop import run_tool_loop


def _git_stash_create(project_root: Path) -> str | None:
    """git stash create → SHA или None."""
    try:
        r = subprocess.run(
            ["git", "stash", "create"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    sha = r.stdout.strip()
    return sha or None


def _list_untracked(project_root: Path) -> set[str]:
    """git status --porcelain → set untracked-путей (без кавычек)."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return set()
    out: set[str] = set()
    for line in r.stdout.splitlines():
        if line.startswith("?? "):
            rel = line[3:].strip()
            if len(rel) >= 2 and rel[0] == '"' and rel[-1] == '"':
                rel = rel[1:-1]
            if rel:
                out.add(rel)
    return out


_FEEDBACK_GOAL_MAX_CHARS = 200


def _build_feedback(subtask_results: list[dict], max_items: int = 7) -> str:
    """Собирает краткий summary предыдущих подзадач для промпта.

    Пустой список (или max_items <= 0) → "". Иначе — последние max_items
    записей в виде Markdown-секции "## Предыдущие подзадачи".
    """
    if not subtask_results or max_items <= 0:
        return ""

    lines = ["## Предыдущие подзадачи", ""]
    for r in subtask_results[-max_items:]:
        n = r.get("n", "?")
        mark = "✅" if r.get("success") else "❌"
        goal = " ".join(str(r.get("goal", "")).split())
        if len(goal) > _FEEDBACK_GOAL_MAX_CHARS:
            goal = goal[:_FEEDBACK_GOAL_MAX_CHARS] + "…"
        files = r.get("files") or []
        files_str = ", ".join(str(f) for f in files) if files else "—"
        summary = r.get("stopped_reason") or f"{r.get('cost_rub') or 0.0:.4f} RUB"

        lines.append(f"### {n} — {mark}")
        lines.append(f"Goal: {goal}")
        lines.append(f"Файлы: {files_str}")
        lines.append(f"Результат: {summary}")
        lines.append("")

    return "\n".join(lines).rstrip()


_SUBAGENT_MODEL = {
    "explore": "deepseek-flash",
    "edit-simple": "deepseek-flash",
    "edit-complex": "deepseek-v4-pro",
    "verify": "deepseek-flash",
}
# Лимиты итераций tool loop по типу подзадачи.
# ВАЖНО: max_iterations считает ВСЕ вызовы LLM, включая тот, в котором
# модель возвращает finish. Поэтому лимит должен покрывать «K вызовов
# инструментов + 1 итерация на finish».
# D10.1: verify было 3 — модель тратила все 3 на run_shell (pytest)
# и не успевала finish → max_iterations → падение подзадачи (и retry).
_SUBAGENT_ITERS = {
    "explore": 5,
    "edit-simple": 10,
    "edit-complex": 15,
    "verify": 5,
}


def _resolve_subagent(st: Subtask, cfg: AppConfig) -> tuple[str, int]:
    """Модель и лимит итераций для подзадачи по её `type` (Router, 10.70).

    **Fallback (D10, баг A).** Модели Router захардкожены
    (`deepseek-flash` / `deepseek-v4-pro`), и раньше их отсутствие в
    `cfg.api.pricing` приводило к `KeyError` **в середине прогона**
    (в `_estimate_next_cost_rub` и `calculate_cost`) — то есть уже
    после потраченных денег.

    Почему fallback, а не валидация на старте (как у `SubagentConfig`):
    модели subagent'ов задаёт **пользователь** — их логично проверять
    при загрузке конфига. Модели Router — **встроенная** деталь
    реализации: требовать цены на `deepseek-v4-pro` от конфига с другим
    провайдером/именованием нельзя, это сломало бы на старте то, что
    раньше работало (когда `edit-complex` не встречался). Поэтому
    деградируем на базовую модель `cfg.api.model` с предупреждением.
    """
    t = st.type if st.type in _SUBAGENT_MODEL else "edit-simple"
    model = _SUBAGENT_MODEL[t]

    if model not in cfg.api.pricing:
        _console.print(
            f"[yellow]Router: нет цен для модели '{model}' "
            f"(type={t}) — использую базовую '{cfg.api.model}'[/yellow]"
        )
        model = cfg.api.model

    return model, _SUBAGENT_ITERS[t]


def _step_type_for(st: Subtask) -> str | None:
    """`type` подзадачи → `step_type` для run_tool_loop.

    До D8 decomposer передавал ВСЕМ подзадачам `step_type="edit"`,
    а `_handle_finish` при "edit" требует `applied_ops > 0`. Поэтому
    подзадачи `explore` (только читает) и `verify` (только запускает
    тесты) не могли завершиться успешно в принципе — Router (10.70)
    создавал 4 типа, а работал фактически один.

    Соответствие:
      explore / read        → "read" (критерий: read_ops > 0)
      verify                → None   (критерий: finish модели; ниже
                                      всё равно отработает verify_commands)
      edit / edit-simple /
      edit-complex / прочее → "edit" (критерий: applied_ops > 0)
    """
    if st.type in ("explore", "read"):
        return "read"
    if st.type == "verify":
        return None
    return "edit"


_console = Console()


def run_split_goals(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    out_dir: Path | None = None,
) -> SplitGoalsResult:
    """
    Разбивает одну фразу на N независимых issues.

    Не выполняет — сохраняет issues/N-<slug>.md.

    Модель: `cfg.agent.split_goals_model` или переданный `model`,
    иначе `cfg.api.model`.
    """
    model = model or getattr(cfg.agent, "split_goals_model", None) or cfg.api.model

    # metadata-scan
    scan_meta = scan_project_metadata(project_root, cfg.scanning, extra_exclude=extra_exclude)

    prompt_entry = prompts_cfg.get("agent_split_goals_json")
    metadata_block = render_metadata_block(scan_meta)
    empty_scan = ScanResult(root=project_root)
    system, user = render_prompt(
        prompt_entry,
        depth=depth,
        scan=empty_scan,
        extra={
            "goal": goal,
            "tree": scan_meta.tree,
            "metadata": metadata_block,
        },
    )

    # тариф и курсы
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    client = LLMClient(cfg.api)
    llm_resp = client.chat(
        system=system,
        user=user,
        model=model,
        json_mode=True,
        max_tokens=cfg.agent.step_max_output_tokens,
    )

    result = parse_split_goals_response(llm_resp.content)
    result.llm = llm_resp

    # стоимость
    cost = calculate_cost(
        pricing=cfg.api.pricing_for(model),
        is_peak=is_peak,
        peak_window=peak_window,
        prompt_hit_tokens=llm_resp.prompt_cache_hit_tokens,
        prompt_miss_tokens=llm_resp.prompt_cache_miss_tokens,
        completion_tokens=llm_resp.completion_tokens,
        cny_to_rub=cny_to_rub,
        usd_to_rub=usd_to_rub,
    )
    result.cost_rub = cost.cost_rub
    result.cost_cny = cost.cost_cny
    result.cost_usd = cost.cost_usd

    # учёт
    output_root = project_root / cfg.output.dir
    append_usage(
        project_root=project_root,
        output_root=output_root,
        action="agent:split-goals",
        project_name=project_root.name,
        model=model,
        depth=depth,
        files_count=scan_meta.total_files,
        prompt_tokens=llm_resp.prompt_tokens,
        completion_tokens=llm_resp.completion_tokens,
        total_tokens=llm_resp.total_tokens,
        cost=cost,
        duration_ms=llm_resp.duration_ms,
        status="ok" if result.parse_error is None else "parse_error",
        usage_cfg=cfg.usage,
        iteration=0,
        parent_action="agent",
    )

    if result.parse_error is not None or not result.issues:
        return result

    # --- сохранение issue-файлов ---
    if out_dir is None:
        out_dir = project_root / "issues"
        if out_dir.exists() and any(out_dir.iterdir()):
            ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
            out_dir = project_root / f"issues-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    result.output_dir = out_dir

    for iss in result.issues:
        slug = _slug_for_issue(iss.title)
        fname = f"{iss.n}-{slug}.md"
        content = f"# task: {iss.title}\n\n{iss.goal}\n"
        (out_dir / fname).write_text(content, encoding="utf-8")

    return result


def run_agent_decompose(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    journal: bool = True,
    dry_run: bool = False,
    dry_read: bool = False,
    interactive: bool = False,
    replan: bool = False,
    rollback_on_fail: bool = False,
    max_cost_rub: float | None = None,
    allow_blacklist: bool = False,  # NEW: обход blacklist (opt-in)
    plan: DecomposeResult | None = None,  # NEW: готовый план (--plan)
    max_iterations: int | None = None,  # NEW: лимит tool loop на подзадачу
    verify_commands: list[str] | None = None,  # NEW: явный verify (fallback на cfg)
    decompose_reverse_check: bool | None = None,  # NEW: обратная проверка декомпозиции
    report_subdir: str | None = None,  # NEW: <date>/<NN>_decompose_<slug>
) -> DecomposeResult:
    """
    Декомпозирует задачу и выполняет каждую подзадачу через run_tool_loop.

    Если передан `plan` — повторно не декомпозирует, использует его
    (для workflow `--plan`: показать → подтвердить → выполнить).
    """

    rc_flag = (
        decompose_reverse_check
        if decompose_reverse_check is not None
        else getattr(cfg.agent, "decompose_reverse_check", False)
    )

    # 1. Декомпозиция (через v4-pro, если задано)
    decompose_model = getattr(cfg.agent, "decompose_model", None) or model
    if plan is not None:
        dec_result = plan
    else:
        dec_result = run_planner_decompose(
            goal=goal,
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            model=decompose_model,
            depth=depth,
            extra_exclude=extra_exclude,
        )

    if dec_result.parse_error is not None:
        _console.print(f"[red]Декомпозиция не удалась:[/red] {dec_result.parse_error}")
        return dec_result

    if not dec_result.subtasks:
        _console.print("[yellow]Декомпозиция: пусто — нечего выполнять.[/yellow]")
        return dec_result

    _console.print(f"[dim]Декомпозиция: {len(dec_result.subtasks)} подзадач[/dim]")

    # --- NEW: decompose-журнал ---
    decompose_ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    decompose_dir: Path | None = None
    if journal:
        if report_subdir:
            decompose_dir = project_root / cfg.output.dir / project_root.name / report_subdir
        else:
            decompose_dir = (
                project_root / cfg.output.dir / project_root.name / f"decompose-{decompose_ts}"
            )
        decompose_dir.mkdir(parents=True, exist_ok=True)
        dec_result.journal_dir = decompose_dir

    # 2. Выполнить каждую подзадачу через tool loop
    subtasks = list(dec_result.subtasks)
    i = 0
    while i < len(subtasks):
        st = subtasks[i]
        _console.print()
        _console.print(
            Panel.fit(
                f"[bold]Подзадача {st.n}/{len(dec_result.subtasks)}[/bold]\n{st.goal}",
                title=f"subtask {st.n}",
            )
        )

        baseline_sha: str | None = None
        untracked_before: set[str] = set()
        if rc_flag and not dry_run:
            baseline_sha = _git_stash_create(project_root)
            untracked_before = _list_untracked(project_root)

        # Feedback loop: подзадача N видит результат подзадач 1..N-1.
        # Считаем один раз на итерацию (до первого run_tool_loop), чтобы
        # retry той же подзадачи не видел собственную неудачную попытку.
        feedback = ""
        if getattr(cfg.agent, "feedback_enabled", True):
            feedback = _build_feedback(
                dec_result.subtask_results,
                max_items=getattr(cfg.agent, "feedback_max_subtasks", 7),
            )

        subtask_subdir: Path | None = None
        if decompose_dir is not None:
            subtask_subdir = decompose_dir / f"subtask-{st.n}"

        remaining = (
            max(0.0, max_cost_rub - dec_result.cost_rub) if max_cost_rub is not None else None
        )
        subtask_model, subtask_iters = _resolve_subagent(st, cfg)
        step_type = _step_type_for(st)  # D8: explore→read, verify→None, edit→edit
        final_iters = max_iterations if max_iterations is not None else subtask_iters
        loop_result = run_tool_loop(
            goal=st.goal,
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            model=subtask_model,
            depth=depth,
            extra_exclude=extra_exclude,
            max_iterations=final_iters,
            max_cost_rub=remaining,
            dry_run=dry_run,
            dry_read=dry_read,
            interactive=interactive,
            journal=journal,
            journal_subdir=subtask_subdir,
            allow_blacklist=allow_blacklist,
            verify_commands=verify_commands,
            step_type=step_type,
            feedback_section=feedback,
        )

        dec_result.cost_rub += loop_result.total_cost_rub
        dec_result.cost_cny += loop_result.total_cost_cny
        dec_result.cost_usd += loop_result.total_cost_usd

        # --- NEW: записать результат подзадачи ---
        dec_result.subtask_results.append(
            {
                "n": st.n,
                "goal": st.goal,
                "files": st.files,
                "success": loop_result.success,
                "stopped_reason": loop_result.stopped_reason,
                "cost_rub": loop_result.total_cost_rub,
                "backup_dir": str(loop_result.backup_dir) if loop_result.backup_dir else None,
                "journal_dir": str(loop_result.journal_dir) if loop_result.journal_dir else None,
            }
        )

        # --- NEW: retry через v4-pro при fail ---
        if not loop_result.success and not dry_run:
            fallback_model = getattr(cfg.agent, "decompose_model", None)
            if fallback_model and fallback_model != model:
                _console.print(
                    f"[yellow]Подзадача {st.n} не выполнена "
                    f"({loop_result.stopped_reason}). "
                    f"Повтор через {fallback_model}...[/yellow]"
                )
                remaining = (
                    max(0.0, max_cost_rub - dec_result.cost_rub)
                    if max_cost_rub is not None
                    else None
                )
                loop_result = run_tool_loop(
                    goal=st.goal,
                    project_root=project_root,
                    cfg=cfg,
                    prompts_cfg=prompts_cfg,
                    model=fallback_model,
                    depth=depth,
                    extra_exclude=extra_exclude,
                    max_iterations=final_iters,
                    max_cost_rub=remaining,
                    dry_run=dry_run,
                    dry_read=dry_read,
                    interactive=interactive,
                    journal=journal,
                    journal_subdir=subtask_subdir,
                    allow_blacklist=allow_blacklist,
                    verify_commands=verify_commands,
                    step_type=step_type,
                    feedback_section=feedback,
                )
                dec_result.cost_rub += loop_result.total_cost_rub
                dec_result.cost_cny += loop_result.total_cost_cny
                dec_result.cost_usd += loop_result.total_cost_usd

                if dec_result.subtask_results:
                    # Суммируем стоимость: первая попытка (flash) +
                    # retry (v4-pro). Иначе flash-попытка теряется
                    # в отчёте (см. experiments 2026-10-09, 10.14.13).
                    prev_cost = dec_result.subtask_results[-1].get("cost_rub", 0.0)
                    dec_result.subtask_results[-1] = {
                        "n": st.n,
                        "goal": st.goal,
                        "files": st.files,
                        "success": loop_result.success,
                        "stopped_reason": loop_result.stopped_reason,
                        "cost_rub": prev_cost + loop_result.total_cost_rub,
                        "backup_dir": str(loop_result.backup_dir)
                        if loop_result.backup_dir
                        else None,
                        "journal_dir": str(loop_result.journal_dir)
                        if loop_result.journal_dir
                        else None,
                    }

        if rc_flag and loop_result.success and not dry_run:
            sub_diff = _collect_subtask_diff(project_root, baseline_sha, untracked_before)
            if sub_diff.strip():
                rc = run_reverse_check(
                    goal=st.goal,
                    diff=sub_diff,
                    project_root=project_root,
                    cfg=cfg,
                    prompts_cfg=prompts_cfg,
                )
                dec_result.cost_rub += rc.cost_rub
                dec_result.cost_cny += rc.cost_cny
                dec_result.cost_usd += rc.cost_usd
                if dec_result.subtask_results:
                    dec_result.subtask_results[-1]["reverse_ok"] = rc.ok
                    dec_result.subtask_results[-1]["reverse_problems"] = rc.problems
                    dec_result.subtask_results[-1]["reverse_suggestion"] = rc.suggestion
                    dec_result.subtask_results[-1]["reverse_cost_rub"] = rc.cost_rub
                if not rc.ok:
                    _console.print(f"[yellow]Validator subtask {st.n}: найдены проблемы[/yellow]")

        if max_cost_rub is not None and dec_result.cost_rub >= max_cost_rub:
            dec_result.parse_error = "max_cost exceeded"
            if decompose_dir is not None:
                _save_decompose_report(decompose_dir, dec_result, goal)
            return dec_result

        if not loop_result.success:
            # --- NEW: replan ---
            if replan and not dry_run:
                replan_model = getattr(cfg.agent, "decompose_model", None) or model
                replan_result = run_planner_replan(
                    goal=goal,
                    project_root=project_root,
                    cfg=cfg,
                    prompts_cfg=prompts_cfg,
                    failed_subtask=st,
                    failed_error=loop_result.summary,
                    completed_subtasks=subtasks[:i],
                    remaining_subtasks=subtasks[i + 1 :],
                    model=replan_model,
                    depth=depth,
                )
                dec_result.cost_rub += replan_result.cost_rub
                dec_result.cost_cny += replan_result.cost_cny
                dec_result.cost_usd += replan_result.cost_usd

                if replan_result.parse_error is not None:
                    _console.print(f"[red]Replan parse_error:[/red] {replan_result.parse_error}")
                    dec_result.parse_error = f"replan parse_error: {replan_result.parse_error}"
                    if decompose_dir is not None:
                        _save_decompose_report(decompose_dir, dec_result, goal)
                    return dec_result

                if replan_result.action == "skip":
                    _console.print(
                        f"[yellow]Replan: skip подзадачи {st.n} "
                        f"({replan_result.explanation})[/yellow]"
                    )
                    dec_result.skipped_subtasks.append(st)
                    i += 1
                    continue
                elif replan_result.action == "modify":
                    _console.print(
                        f"[yellow]Replan: modify — новых подзадач "
                        f"{len(replan_result.new_subtasks)}[/yellow]"
                    )
                    subtasks = subtasks[:i] + replan_result.new_subtasks
                    continue
                elif replan_result.action == "stop":
                    _console.print(f"[red]Replan: stop ({replan_result.explanation})[/red]")
                    dec_result.parse_error = f"subtask {st.n} failed, replan=stop"
                    if decompose_dir is not None:
                        _save_decompose_report(decompose_dir, dec_result, goal)
                    return dec_result

            # --- Страховка: откат упавшей подзадачи ---
            # run_tool_loop уже откатил свой backup_dir при verify_failed.
            # Но если fail случился по другой причине (и backup_dir есть) —
            # откатываем здесь, чтобы не оставлять мусор.
            if not dry_run and loop_result.backup_dir:
                from ..apply import rollback as do_rollback_fail

                try:
                    restored = do_rollback_fail(loop_result.backup_dir, project_root)
                    if restored:
                        _console.print(
                            f"[yellow]Откат упавшей подзадачи {st.n}: "
                            f"{len(restored)} файлов[/yellow]"
                        )
                except Exception as e:
                    _console.print(f"[red]Ошибка отката подзадачи {st.n}: {e}[/red]")

            # --- NEW: откат при fail ---
            if rollback_on_fail and not dry_run:
                _console.print("[yellow]Откат всех успешных подзадач...[/yellow]")
                from ..apply import rollback as do_rollback

                for prev in dec_result.subtask_results:
                    if prev.get("success") and prev.get("backup_dir"):
                        try:
                            do_rollback(Path(prev["backup_dir"]), project_root)
                            _console.print(f"  [dim]Откат subtask-{prev['n']} ✅[/dim]")
                        except Exception as e:
                            _console.print(f"  [red]Ошибка отката subtask-{prev['n']}: {e}[/red]")
                dec_result.rolled_back = True

            _console.print(f"[red]Подзадача {st.n} не выполнена — стоп.[/red]")
            dec_result.parse_error = f"subtask {st.n} failed"

            if decompose_dir is not None:
                _save_decompose_report(decompose_dir, dec_result, goal)
            return dec_result

        i += 1

    _console.print()
    skipped_info = ""
    if dec_result.skipped_subtasks:
        skipped_info = f"\n[yellow]Пропущено: {len(dec_result.skipped_subtasks)}[/yellow]"
    _console.print(
        Panel.fit(
            f"[green]✅ Декомпозиция завершена[/green]\n"
            f"[bold]Подзадач:[/bold] {len(subtasks)}"
            f"{skipped_info}\n"
            f"[bold]Стоимость всего:[/bold] {dec_result.cost_rub:.4f} RUB",
            title="Декомпозиция — итог",
        )
    )

    if decompose_dir is not None:
        _save_decompose_report(decompose_dir, dec_result, goal)
        try:
            rel = decompose_dir.relative_to(Path.cwd())
            _console.print(f"[dim]Журнал decompose: {rel}[/dim]")
        except ValueError:
            _console.print(f"[dim]Журнал decompose: {decompose_dir}[/dim]")

    return dec_result


def _save_decompose_report(
    decompose_dir: Path,
    result: DecomposeResult,
    goal: str,
) -> None:
    """Сохраняет отчёт decompose."""
    lines: list[str] = []
    lines.append(f"# Decompose — {goal}\n")
    status = "✅ успех" if result.parse_error is None else "❌ неуспех"
    lines.append(f"**Статус:** {status}")
    lines.append(f"**Стоимость:** {result.cost_rub:.4f} RUB")
    if result.rolled_back:
        lines.append("**Откат:** все успешные подзадачи откачены")
    lines.append("")

    if result.explanation:
        lines.append(f"**Explanation:** {result.explanation}\n")

    lines.append("## Подзадачи\n")
    lines.append("| # | Goal | Статус | RC | Стоимость | Журнал |")
    lines.append("|---|---|---|---|---|---|")
    for r in result.subtask_results:
        st_status = "✅" if r.get("success") else "❌"
        rc_val = r.get("reverse_ok")
        rc_col = "—" if rc_val is None else ("✅" if rc_val else "❌")
        jrel = Path(r["journal_dir"]).name if r.get("journal_dir") else "—"
        lines.append(
            f"| {r['n']} | {r['goal'][:60]} | {st_status} | {rc_col} "
            f"| {r['cost_rub']:.4f} | {jrel} |"
        )
    lines.append("")

    rc_bad = [r for r in result.subtask_results if r.get("reverse_ok") is False]
    if rc_bad:
        lines.append("## Reverse-check\n")
        for r in rc_bad:
            lines.append(f"### Подзадача {r['n']} — ❌\n")
            for p in r.get("reverse_problems", []):
                lines.append(f"- {p}")
            sug = r.get("reverse_suggestion")
            if sug:
                lines.append(f"- **Suggestion:** {sug}")
            lines.append("")

    if result.skipped_subtasks:
        lines.append(f"**Пропущено:** {len(result.skipped_subtasks)}\n")
        for s in result.skipped_subtasks:
            lines.append(f"- {s.n}. {s.goal}")
        lines.append("")

    if result.parse_error:
        lines.append(f"## Ошибка\n\n```\n{result.parse_error}\n```\n")

    (decompose_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = [
    "_save_decompose_report",
    "run_agent_decompose",
    "run_split_goals",
]
