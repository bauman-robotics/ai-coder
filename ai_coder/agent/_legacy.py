from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.panel import Panel

from ..apply import (
    apply_plan,
    build_plan,
    check_python_files,
    run_verify_commands,  # NEW
)
from ..config import (
    WEB_ASSET_EXTENSIONS,
    AppConfig,
    PromptsConfig,
)
from ..llm import LLMClient, LLMResponse
from ..pricing import calculate_cost, get_rate, is_peak_now
from ..prompts import render_prompt
from ..scanner import (
    ScanResult,
    render_metadata_block,
    scan_project,
    scan_project_metadata,
)
from ..tools import (
    ToolAction,
    ToolResult,
)
from ..usage import append_usage

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
from .planner import (
    _extract_target_files,
    _slug_for_issue,
    parse_split_goals_response,
    run_planner,
    run_planner_decompose,
    run_planner_phase1,
    run_planner_replan,
)

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
) -> DecomposeResult:
    """
    Декомпозирует задачу и выполняет каждую подзадачу через run_tool_loop.

    Если передан `plan` — повторно не декомпозирует, использует его
    (для workflow `--plan`: показать → подтвердить → выполнить).
    """
    eff_iters = max_iterations if max_iterations is not None else cfg.agent.max_steps

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

        subtask_subdir: Path | None = None
        if decompose_dir is not None:
            subtask_subdir = decompose_dir / f"subtask-{st.n}"

        remaining = (
            max(0.0, max_cost_rub - dec_result.cost_rub) if max_cost_rub is not None else None
        )
        loop_result = run_tool_loop(
            goal=st.goal,
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            model=model,  # для tool loop — flash
            depth=depth,
            extra_exclude=extra_exclude,
            max_iterations=eff_iters,
            max_cost_rub=remaining,
            dry_run=dry_run,
            dry_read=dry_read,
            interactive=interactive,
            journal=journal,
            journal_subdir=subtask_subdir,
            allow_blacklist=allow_blacklist,
            verify_commands=verify_commands,
            step_type="edit",
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
                    max_iterations=eff_iters,
                    max_cost_rub=remaining,
                    dry_run=dry_run,
                    dry_read=dry_read,
                    interactive=interactive,
                    journal=journal,
                    journal_subdir=subtask_subdir,
                    allow_blacklist=allow_blacklist,
                    verify_commands=verify_commands,
                    step_type="edit",
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
    lines.append("| # | Goal | Статус | Стоимость | Журнал |")
    lines.append("|---|---|---|---|---|")
    for r in result.subtask_results:
        st_status = "✅" if r.get("success") else "❌"
        jrel = Path(r["journal_dir"]).name if r.get("journal_dir") else "—"
        lines.append(
            f"| {r['n']} | {r['goal'][:60]} | {st_status} | {r['cost_rub']:.4f} | {jrel} |"
        )
    lines.append("")

    if result.skipped_subtasks:
        lines.append(f"**Пропущено:** {len(result.skipped_subtasks)}\n")
        for s in result.skipped_subtasks:
            lines.append(f"- {s.n}. {s.goal}")
        lines.append("")

    if result.parse_error:
        lines.append(f"## Ошибка\n\n```\n{result.parse_error}\n```\n")

    (decompose_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- кэш phase1 ----------
# ---------- журнал агента ----------
# ---------- декомпозиция задач ----------
# ---------- split-goals (10F) ----------
# ---------- исполнитель одного шага ----------


def _run_agent_step(
    *,
    goal: str,
    step: AgentStep,
    plan: AgentPlan,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    completed_titles: list[str] | None = None,
    apply: bool = False,
    verify: bool = True,
    max_fix_attempts: int = 0,
    web_assets_override: bool | None = None,
    interactive: bool = False,  # NEW
    accept_all_ref: list[bool] | None = None,  # NEW
    only_paths: list[str] | None = None,  # NEW
    journal_subdir: Path | None = None,  # NEW: куда писать журнал read-шага
) -> StepResult:
    """
    Выполняет один шаг: запрос к LLM → парсинг плана → (опц.) применение → верификация.
    Ничего не решает про контроль бюджета/шагов — только делает свою работу.

    10.33: для read-шагов (step.type == "read") — вызывается _run_read_step
    (через run_tool_loop), не обычный edit-путь.
    """
    from ..actions import run_fix_action
    from ..apply import rollback as do_rollback

    model = model or cfg.api.model

    # --- 10.33: read-шаг → отдельный путь через tool loop ---
    if step.type == "read":
        return _run_read_step(
            step=step,
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            model=model,
            depth=depth,
            extra_exclude=extra_exclude,
            only_paths=only_paths,
            journal_subdir=journal_subdir,
        )

    # --- пересканируем проект (файлы могли измениться предыдущими шагами) ---
    effective_exclude = list(extra_exclude or [])
    if web_assets_override is False:  # --exclude-web
        effective_exclude += list(WEB_ASSET_EXTENSIONS)

    scan = scan_project(
        project_root,
        cfg.scanning,
        extra_exclude=effective_exclude or None,
        only_paths=only_paths,  # NEW
    )

    # --- промпт шага ---
    prompt_entry = prompts_cfg.get("agent_step_json")
    plan_summary = _render_plan_summary(plan)
    completed = "\n".join(f"- {t}" for t in (completed_titles or [])) or "(нет)"

    system, user = render_prompt(
        prompt_entry,
        depth=depth,
        scan=scan,
        extra={
            "goal": goal,
            "plan_summary": plan_summary,
            "step_index": str(step.n),
            "total_steps": str(len(plan.steps)),
            "step_title": step.title,
            "step_details": step.details or step.title,
            "step_target_files": ", ".join(step.target_files) or "(не указаны)",
            "completed_steps": completed,
        },
    )

    # --- тариф/курсы ---
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    # --- запрос ---
    client = LLMClient(cfg.api)
    llm_resp = client.chat(
        system=system,
        user=user,
        model=model,
        json_mode=True,
        max_tokens=cfg.agent.step_max_output_tokens,
    )

    # --- план операций ---
    write_plan = build_plan(llm_resp.content, project_root, cfg)

    # --- стоимость ---
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

    # --- учёт ---
    output_root = project_root / cfg.output.dir
    append_usage(
        project_root=project_root,
        output_root=output_root,
        action=f"agent:step{step.n}",
        project_name=project_root.name,
        model=model,
        depth=depth,
        files_count=len(scan.files),
        prompt_tokens=llm_resp.prompt_tokens,
        completion_tokens=llm_resp.completion_tokens,
        total_tokens=llm_resp.total_tokens,
        cost=cost,
        duration_ms=llm_resp.duration_ms,
        status="ok",
        usage_cfg=cfg.usage,
        iteration=step.n,
        parent_action="agent",
    )

    result = StepResult(
        step=step,
        llm=llm_resp,
        write_plan=write_plan,
        applied=False,
        applied_count=0,
        errors=[],
        verify_errors=[],
        rolled_back=False,
        cost_rub=cost.cost_rub,
        cost_cny=cost.cost_cny,
        cost_usd=cost.cost_usd,
        from_cache=False,
    )

    # --- проверка finish_reason: если модель обрезалась — это важно увидеть
    if llm_resp.finish_reason == "length":
        result.errors.append(
            f"⚠️ Ответ модели обрезан по max_output_tokens "
            f"(completion={llm_resp.completion_tokens}). "
            f"Увеличь step_max_output_tokens или разбей задачу."
        )

    if not apply:
        # Даже без применения — если план пустой, помечаем как skipped
        if write_plan is not None and not write_plan.operations:
            result.skipped = True
            result.skip_reason = "план не содержит операций"
        return result

    # --- interactive: подтверждение перед применением ---
    if apply and interactive:
        accept_all = accept_all_ref is not None and accept_all_ref[0]
        if not accept_all:
            while True:
                _print_step_for_review(step, write_plan, step.n, len(plan.steps))
                answer = _prompt_review()

                if answer == "y":
                    break  # применяем
                if answer == "d":
                    continue  # показываем diff снова
                if answer == "n":
                    result.skipped = True
                    result.skip_reason = "отменено пользователем"
                    result.errors.append("отменено пользователем")
                    return result
                if answer == "s":
                    result.skipped = True
                    result.skip_reason = "пропущено пользователем"
                    return result
                if answer == "a":
                    if accept_all_ref is not None:
                        accept_all_ref[0] = True
                    break  # применяем, дальше без вопросов

    # --- применение ---
    if write_plan is None or not write_plan.valid:
        if write_plan is None:
            result.errors.append("План не сгенерирован (write_plan is None)")
        else:
            if write_plan.parse_error:
                result.errors.append(f"parse_error: {write_plan.parse_error}")
            for p in write_plan.problems:
                result.errors.append(p)
            if not write_plan.parse_error and not write_plan.problems:
                result.errors.append("План невалиден (без деталей)")
        return result
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = (
        project_root / cfg.output.dir / project_root.name / f"agent-backup-{ts}-step{step.n}"
    )

    applied, apply_errors = apply_plan(write_plan, project_root, backup_dir)
    if apply_errors:
        result.errors.extend(apply_errors)
        return result

    if not applied:
        # Нечего применять — модель вернула пустой план
        result.skipped = True
        result.skip_reason = "план не содержит операций"
        return result

    result.applied = True
    result.applied_count = len(applied)

    # --- верификация ---
    if verify and applied:
        verify_errors = check_python_files(applied, project_root)
        # NEW: verify-команды
        if cfg.agent.verify_commands:
            verify_errors += run_verify_commands(
                cfg.agent.verify_commands,
                project_root,
                timeout_sec=cfg.agent.verify_timeout_sec,
            )
        # fix-цикл
        fix_iter = 0
        while verify_errors and fix_iter < max_fix_attempts:
            fix_iter += 1
            try:
                fix_result = run_fix_action(
                    parent_action=f"agent:step{step.n}",
                    iteration=fix_iter,
                    project_root=project_root,
                    cfg=cfg,
                    prompts_cfg=prompts_cfg,
                    errors=verify_errors,
                    previous_plan=write_plan,
                    model=model,
                    depth=depth,
                    extra_exclude=extra_exclude,
                    use_cache=False,
                )
            except Exception as e:
                result.errors.append(f"Ошибка fix-итерации: {e}")
                break

            fix_plan = fix_result.write_plan
            if fix_plan is None or not fix_plan.valid:
                result.errors.append("Fix-план невалиден")
                break

            fix_backup = (
                project_root
                / cfg.output.dir
                / project_root.name
                / f"agent-backup-{ts}-step{step.n}-fix{fix_iter}"
            )
            fix_applied, fix_errors = apply_plan(fix_plan, project_root, fix_backup)
            if fix_errors:
                result.errors.extend(fix_errors)
                break

            verify_errors = check_python_files(fix_applied, project_root)

        result.verify_errors = verify_errors

        if verify_errors:
            # откатываем шаг к состоянию до его применения
            do_rollback(backup_dir, project_root)
            result.rolled_back = True
            result.applied = False

    return result


# ---------- рендер вспомогательных текстов ----------


def _render_plan_summary(plan: AgentPlan) -> str:
    parts: list[str] = []
    if plan.explanation:
        parts.append(plan.explanation)
    for s in plan.steps:
        parts.append(f"{s.n}. {s.title}")
    return "\n".join(parts)


# ---------- with-tests: извлечение изменённых файлов ----------


def extract_changed_files(history: list[tuple[ToolAction, ToolResult]]) -> list[str]:
    """
    Возвращает отсортированный список .py-файлов, изменённых в tool loop
    (edit_file / write_file, ok=True). Исключает тестовые файлы.
    """
    files: set[str] = set()
    for action, result in history:
        if action.finish or not result.ok:
            continue
        if action.tool not in ("edit_file", "write_file"):
            continue
        path = action.args.get("path")
        if not isinstance(path, str) or not path:
            continue
        if not path.endswith(".py"):
            continue
        # исключаем тесты
        parts = path.replace("\\", "/").split("/")
        name = parts[-1]
        if name.startswith("test_") or name.endswith("_test.py"):
            continue
        if "tests" in parts or "test" in parts:
            continue
        files.add(path)
    return sorted(files)


# ---------- главный цикл ----------


def run_agent(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    apply: bool = False,
    verify: bool = True,
    max_fix_attempts: int = 0,
    max_steps: int | None = None,
    max_minutes: int | None = None,
    journal: bool = True,
    preview_only: bool = False,
    web_assets_override: bool | None = None,
    interactive: bool = False,  # NEW
    max_cost_rub: float | None = None,  # NEW
) -> AgentRunResult:
    """
    Полный цикл агента: план → шаги → журнал.
    """
    started_at = datetime.now(ZoneInfo("UTC"))

    if max_steps is None:
        max_steps = cfg.agent.max_steps
    if max_minutes is None:
        max_minutes = cfg.agent.max_minutes

    # --- журнал ---
    journal_dir: Path | None = None
    if journal:
        ts = started_at.strftime("%Y-%m-%dT%H-%M-%S")
        journal_dir = project_root / cfg.output.dir / project_root.name / f"agent-{ts}"
        journal_dir.mkdir(parents=True, exist_ok=True)

    # --- NEW: phase1 — планировщик видит только дерево + метаданные ---
    phase1_targets: list[str] = []
    phase1_result = None
    if cfg.agent.phase1_enabled:
        try:
            phase1_result = run_planner_phase1(
                goal=goal,
                project_root=project_root,
                cfg=cfg,
                prompts_cfg=prompts_cfg,
                model=model,
                depth=depth,
                extra_exclude=extra_exclude,
            )
            phase1_targets = phase1_result.target_files
            if phase1_result.parse_error:
                _console.print(
                    f"[yellow]Фаза 1: parse_error ({phase1_result.parse_error}), "
                    f"phase2 пойдёт без сужения[/yellow]"
                )
                phase1_targets = []
            elif phase1_targets:
                _console.print(
                    f"[dim]Фаза 1: определены {len(phase1_targets)} файл(ов): "
                    f"{', '.join(phase1_targets[:3])}"
                    f"{'...' if len(phase1_targets) > 3 else ''}[/dim]"
                )
            else:
                _console.print(
                    "[dim yellow]Фаза 1: target_files пуст — "
                    "phase2 пойдёт с полным контекстом[/dim yellow]"
                )
        except Exception as e:
            _console.print(
                f"[yellow]Фаза 1: ошибка ({type(e).__name__}: {e}), "
                f"phase2 пойдёт без сужения[/yellow]"
            )
            phase1_targets = []

    # --- планировщик (phase2) ---
    planner = run_planner(
        goal=goal,
        project_root=project_root,
        cfg=cfg,
        prompts_cfg=prompts_cfg,
        model=model,
        depth=depth,
        extra_exclude=extra_exclude,
        max_steps=max_steps,
        only_paths=phase1_targets or None,  # NEW: сужение если phase1 дал файлы
    )

    if journal_dir is not None:
        _save_plan_json(journal_dir, planner.plan, planner.llm)

    result = AgentRunResult(
        goal=goal,
        plan=planner.plan,
        planner_llm=planner.llm,
        planner_cost_rub=planner.cost_rub,
        planner_cost_cny=planner.cost_cny,
        planner_cost_usd=planner.cost_usd,
        steps=[],
        started_at=started_at,
        finished_at=started_at,
        journal_dir=journal_dir,
    )

    if planner.plan.parse_error is not None:
        result.stopped_reason = "parse_error"
        result.finished_at = datetime.now(ZoneInfo("UTC"))
        return result

    if planner.plan.empty:
        result.stopped_reason = "empty_plan"
        result.finished_at = datetime.now(ZoneInfo("UTC"))
        return result

    # NEW: preview-only — не выполняем шаги
    if preview_only:
        result.stopped_reason = "preview_only"
        result.finished_at = datetime.now(ZoneInfo("UTC"))
        if journal_dir is not None:
            _save_agent_report(journal_dir, result, apply=False)
        return result

    # --- NEW: автовыбор only_paths из плана ---
    auto_targets: list[str] = []
    single_step_plan = len(planner.plan.steps) == 1
    if cfg.agent.auto_only_paths:
        auto_targets = _extract_target_files(planner.plan)
        if auto_targets:
            if single_step_plan:
                _console.print(
                    f"[dim]Авто-контекст: одношаговый план — "
                    f"сужен до {len(auto_targets)} файл(ов)[/dim]"
                )
            else:
                _console.print(
                    f"[dim]Авто-контекст: шаги 2+ увидят только "
                    f"{len(auto_targets)} файл(ов) из плана[/dim]"
                )
        else:
            _console.print(
                "[dim yellow]Авто-контекст: планировщик не указал "
                "target_files — шаги пойдут с полным контекстом[/dim yellow]"
            )

    # --- цикл по шагам ---
    completed_titles: list[str] = []
    step_results: list[StepResult] = []
    accept_all_ref: list[bool] = [False]

    for idx, step in enumerate(planner.plan.steps):
        # --- NEW: селективный контекст ---
        # Одношаговый план: шаг 1 сужен до target_files.
        # Многошаговый: шаг 1 видит всё (может «доисследовать»),
        # шаги 2+ сужены до target_files.
        use_only_paths = (
            cfg.agent.auto_only_paths and auto_targets and (idx > 0 or single_step_plan)
        )
        step_only_paths = auto_targets if use_only_paths else None
        # None → берётся cfg.scanning.only_paths

        # --- проверка таймаута ---
        elapsed_min = (datetime.now(ZoneInfo("UTC")) - started_at).total_seconds() / 60
        if elapsed_min > max_minutes:
            result.stopped_reason = "timeout"
            break

        if len(step_results) >= max_steps:
            result.stopped_reason = "max_steps"
            break

        # --- проверка бюджета ---
        if max_cost_rub is not None:
            cost_so_far = result.planner_cost_rub + sum(s.cost_rub for s in step_results)
            if cost_so_far >= max_cost_rub:
                _console.print(
                    f"[yellow]Бюджет исчерпан: {cost_so_far:.4f} RUB "
                    f">= {max_cost_rub:.4f} RUB[/yellow]"
                )
                result.stopped_reason = "max_cost"
                break

        step_result = _run_agent_step(
            goal=goal,
            step=step,
            plan=planner.plan,
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            model=model,
            depth=depth,
            extra_exclude=extra_exclude,
            completed_titles=completed_titles,
            apply=apply,
            verify=verify,
            max_fix_attempts=max_fix_attempts,
            web_assets_override=web_assets_override,
            interactive=interactive,
            accept_all_ref=accept_all_ref,
            only_paths=step_only_paths,  # NEW
            journal_subdir=journal_dir,  # NEW: журнал read-шага
        )
        step_results.append(step_result)

        # 10.33: показать ответ read-шага
        if step_result.read_answer:
            _console.print()
            _console.print(
                Panel.fit(
                    step_result.read_answer,
                    title=f"Ответ на шаг {step.n}: {step.title}",
                )
            )

        # --- журнал по шагу ---
        if journal_dir is not None:
            _save_step_md(journal_dir, step_result, apply=apply)

        # --- решаем, продолжать ли ---
        if apply:
            if step_result.errors:
                result.stopped_reason = "error"
                break
            if step_result.verify_errors and cfg.agent.stop_on_verify_failure:
                result.stopped_reason = "verify_failed"
                break

        completed_titles.append(step.title)

    result.steps = step_results
    result.finished_at = datetime.now(ZoneInfo("UTC"))

    # --- итоговый отчёт ---
    if journal_dir is not None:
        _save_agent_report(journal_dir, result, apply=apply)

    return result


# ---------- сохранение журнала ----------


def _save_plan_json(journal_dir: Path, plan: AgentPlan, llm: LLMResponse) -> None:
    data = {
        "goal": plan.goal,
        "explanation": plan.explanation,
        "steps": [
            {
                "n": s.n,
                "title": s.title,
                "type": s.type,
                "details": s.details,
                "target_files": s.target_files,
            }
            for s in plan.steps
        ],
        "llm": {
            "model": llm.model,
            "prompt_tokens": llm.prompt_tokens,
            "completion_tokens": llm.completion_tokens,
            "total_tokens": llm.total_tokens,
            "duration_ms": llm.duration_ms,
        },
        "parse_error": plan.parse_error,
    }
    (journal_dir / "plan.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _run_read_step(
    *,
    step: AgentStep,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None,
    depth: str,
    extra_exclude: list[str] | None,
    only_paths: list[str] | None,
    journal_subdir: Path | None,
    max_iterations: int = 10,
) -> StepResult:
    """10.33: read-шаг в простом агенте — через run_tool_loop(step_type="read").

    Не применяет правки. Возвращает StepResult с read_answer=summary.
    verify не запускается (read не меняет файлы).
    """
    goal_text = step.title
    if step.details:
        goal_text = f"{step.title}\n\n{step.details}"

    loop_result = run_tool_loop(
        goal=goal_text,
        project_root=project_root,
        cfg=cfg,
        prompts_cfg=prompts_cfg,
        model=model,
        depth=depth,
        extra_exclude=extra_exclude,
        max_iterations=max_iterations,
        journal=True,
        journal_subdir=journal_subdir,
        step_type="read",
    )

    from ..llm import LLMResponse

    synth_llm = LLMResponse(
        content=loop_result.summary,
        model=model or cfg.api.model,
        prompt_tokens=0,
        prompt_cache_hit_tokens=0,
        prompt_cache_miss_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        duration_ms=0,
        finish_reason="stop",
    )

    return StepResult(
        step=step,
        llm=synth_llm,
        write_plan=None,
        applied=False,
        applied_count=0,
        errors=[],
        verify_errors=[],  # read не проверяем
        rolled_back=False,
        cost_rub=loop_result.total_cost_rub,
        cost_cny=loop_result.total_cost_cny,
        cost_usd=loop_result.total_cost_usd,
        from_cache=False,
        read_answer=loop_result.summary,
        skipped=not loop_result.success,
        skip_reason="" if loop_result.success else loop_result.stopped_reason,
    )


def _save_step_md(journal_dir: Path, step_result: StepResult, apply: bool) -> None:
    s = step_result.step
    lines: list[str] = []
    lines.append(f"# Шаг {s.n}: {s.title}\n")
    lines.append(f"- **Тип:** {s.type}")
    lines.append(f"- **Details:** {s.details or '(нет)'}")
    lines.append(f"- **Target files:** {', '.join(s.target_files) or '(нет)'}")
    lines.append(f"- **Модель:** {step_result.llm.model}")
    lines.append(
        f"- **Токены:** prompt {step_result.llm.prompt_tokens} / completion {step_result.llm.completion_tokens}"
    )
    lines.append(f"- **Стоимость:** {step_result.cost_rub:.6f} RUB")
    lines.append(f"- **Применено:** {'да' if step_result.applied else 'нет'}")
    if step_result.applied_count:
        lines.append(f"- **Операций:** {step_result.applied_count}")
    if step_result.errors:
        lines.append("\n## ❌ Ошибки применения\n")
        for e in step_result.errors:
            lines.append(f"- {e}")
    if step_result.verify_errors:
        lines.append("\n## ❌ Ошибки верификации\n")
        for e in step_result.verify_errors:
            lines.append(f"- {e}")
    if step_result.rolled_back:
        lines.append("\n> ⚠️ Шаг откачен.\n")

    plan = step_result.write_plan
    if plan is not None:
        lines.append("\n## Explanation\n")
        lines.append(plan.explanation or "(нет)")
        lines.append(f"\n## Операции ({len(plan.operations)})\n")
        for i, op in enumerate(plan.operations, 1):
            lines.append(f"{i}. `{op.type}` `{op.path}`")
        if plan.diff:
            lines.append("\n## Diff\n")
            lines.append("```diff")
            lines.append(plan.diff)
            if not plan.diff.endswith("\n"):
                lines.append("")
            lines.append("```")

    (journal_dir / f"step-{s.n}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _save_agent_report(journal_dir: Path, result: AgentRunResult, apply: bool) -> None:
    lines: list[str] = []
    lines.append(f"# Agent — {result.plan.goal}\n")
    lines.append(f"- **Начало (UTC):** {result.started_at.isoformat(timespec='seconds')}")
    lines.append(f"- **Конец (UTC):** {result.finished_at.isoformat(timespec='seconds')}")
    duration = (result.finished_at - result.started_at).total_seconds()
    lines.append(f"- **Длительность:** {duration:.1f} c")
    lines.append(f"- **Режим:** {'apply' if apply else 'preview (без применения)'}")
    lines.append(f"- **Причина остановки:** {result.stopped_reason}")
    lines.append(f"- **Стоимость всего:** {result.total_cost_rub:.6f} RUB")
    lines.append(f"- **Стоимость планировщика:** {result.planner_cost_rub:.6f} RUB")

    lines.append("\n## План\n")
    if result.plan.explanation:
        lines.append(result.plan.explanation + "\n")
    for s in result.plan.steps:
        lines.append(f"{s.n}. {s.title}")

    lines.append("\n## Выполненные шаги\n")
    if not result.steps:
        lines.append("(нет)")
    else:
        lines.append("| # | Название | Применено | Ошибок | Стоимость RUB |")
        lines.append("|---:|---|:---:|---:|---:|")
        for sr in result.steps:
            ok = "✅" if sr.applied else "—"
            lines.append(
                f"| {sr.step.n} | {sr.step.title} | {ok} | {len(sr.errors) + len(sr.verify_errors)} | {sr.cost_rub:.6f} |"
            )

    (journal_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_step_for_review(step: AgentStep, plan, index: int, total: int) -> None:
    """Показывает шаг и diff перед подтверждением."""
    _console.print()
    _console.print(
        Panel.fit(
            f"[bold]Шаг {index}/{total}:[/bold] {step.title}\n"
            f"Операций: [cyan]{len(plan.operations)}[/cyan]",
            title="Подтверждение",
        )
    )

    if plan.explanation:
        _console.print(f"\n[dim]{plan.explanation}[/dim]\n")

    # Список операций
    files_table_lines: list[str] = []
    for i, op in enumerate(plan.operations, 1):
        files_table_lines.append(f"  {i}. {op.type} {op.path}")
    _console.print("\n".join(files_table_lines))

    # Diff
    if plan.diff:
        _console.print("\n[bold]Diff:[/bold]\n")
        _console.print("```diff", style="dim")
        _console.print(plan.diff, style="dim")
        _console.print("```", style="dim")


def _prompt_review() -> str:
    """
    Спрашивает y/n/a/s/d. Возвращает одну из букв.
    Цикл: если ответ неизвестен — переспрашиваем.
    """
    while True:
        try:
            answer = (
                input("\nПрименить? yes(y) / no(n) / all(a) / skip(s) / diff(d): ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return "n"
        if answer in ("y", "n", "a", "s", "d"):
            return answer
        print("Не понял. Ответь: y / n / a / s / d")


# history.json обновляется отдельно в run_tool_loop


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
    "_print_step_for_review",
    "_prompt_review",
    "_render_plan_summary",
    "_run_agent_step",
    "_run_read_step",
    "_save_agent_report",
    "_save_auto_fix_report",
    "_save_decompose_report",
    "_save_plan_json",
    "_save_step_md",
    "_select_step_only_paths",
    "extract_changed_files",
    "run_agent",
    "run_agent_decompose",
    "run_auto_fix",
    "run_split_goals",
]
