"""Tool loop агента ai_coder.

Итеративный цикл: LLM → инструмент → результат → LLM.
Вынесено из agent/_legacy.py (10.65.4b split-file).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.panel import Panel

from ..apply import (
    run_verify_commands,
)
from ..config import (
    AppConfig,
    PromptEntry,
    PromptsConfig,
    SubagentConfig,
)
from ..llm import LLMClient, LLMResponse
from ..pricing import calculate_cost, get_rate, is_peak_now
from ..prompts import render_prompt
from ..scanner import (
    MetadataScanResult,
    ScanResult,
    scan_project_metadata,
)
from ..tools import (
    TOOL_REGISTRY,
    ToolAction,
    ToolResult,
    _safe_path,
    execute_tool,
    format_tool_history,
    format_tools_for_prompt,
    parse_tool_action,
)
from ..usage import append_usage
from .models import ReverseCheckResult, ToolLoopResult
from .planner import _estimate_next_cost_rub
from .reverse import _collect_diff, run_reverse_check

_console = Console()


_REQUIRED_ARGS: dict[str, list[str]] = {
    "read_file": ["path"],
    "write_file": ["path", "content"],
    "edit_file": ["path", "old", "new"],
    "list_files": [],
    "run_shell": ["command"],
    "spawn_subagent": ["name", "goal"],
}


@dataclass
class _ToolLoopCtx:
    """Контекст одной сессии tool loop. Мутируется в цикле."""

    # --- входные (не меняются) ---
    goal: str
    project_root: Path
    cfg: AppConfig
    prompts_cfg: PromptsConfig
    client: LLMClient
    model: str
    depth: str
    extra_exclude: list[str] | None
    max_iterations: int
    max_cost_rub: float | None
    dry_run: bool
    dry_read: bool
    interactive: bool
    auto_commit: bool
    allow_blacklist: bool
    verify_commands: list[str] | None
    step_type: str | None
    reverse_check: bool
    feedback_section: str
    subagents_section: str
    allowed_tools: frozenset[str]
    subagents_by_name: dict[str, SubagentConfig]
    spawn_depth: int
    max_spawns: int
    usage_action_prefix: str
    prompt_entry: PromptEntry
    tools_block: str
    scan_meta: MetadataScanResult

    # --- выходные (меняются) ---
    journal_dir: Path | None = None
    history: list = field(default_factory=list)
    total_cost_rub: float = 0.0
    total_cost_cny: float = 0.0
    total_cost_usd: float = 0.0
    backup_dir: Path | None = None
    backup_manifest: dict = field(default_factory=dict)
    backed_up: set = field(default_factory=set)
    success: bool = False
    stopped_reason: str = "completed"
    summary: str = ""
    applied_ops: int = 0
    read_ops: int = 0
    warnings: list = field(default_factory=list)
    parse_retries: int = 0
    max_parse_retries: int = 2
    arg_retries: int = 0
    max_arg_retries: int = 3
    accept_all_ref: list = field(default_factory=lambda: [False])
    verify_errors: list = field(default_factory=list)
    commit_hash: str | None = None
    reverse_result: ReverseCheckResult | None = None
    result: ToolLoopResult | None = None
    last_iteration: bool = False
    start_iteration: int = 1
    end_iteration: int = 0
    spawn_count: int = 0
    spawn_cost_rub: float = 0.0


def _has_missing_args(action: ToolAction) -> bool:
    """True, если инструмент не получил обязательные args."""
    required = _REQUIRED_ARGS.get(action.tool, [])
    return any(not action.args.get(k) for k in required)


def _required_args_hint(tool: str) -> str:
    return ", ".join(_REQUIRED_ARGS.get(tool, []))


def _backup_file_for_tool_loop(
    *,
    action: ToolAction,
    project_root: Path,
    backup_dir: Path | None,  # ← принимает
    backed_up: set[str],
    backup_manifest: dict,
) -> Path | None:  # ← возвращает (может создать)
    """
    Делает бэкап файла перед изменением.
    Возвращает backup_dir (созданный или существующий).
    """
    rel = str(action.args.get("path", "")).strip()
    if not rel or rel in backed_up:
        return backup_dir

    try:
        target = _safe_path(project_root, rel)
    except Exception:
        return backup_dir

    # создаём backup_dir при первом вызове
    if backup_dir is None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = project_root / ".ai-out" / project_root.name / f"tool-loop-backup-{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_manifest["timestamp"] = datetime.now().isoformat(timespec="seconds")
        backup_manifest["project_root"] = str(project_root.resolve())
        backup_manifest["operations"] = []

    if target.exists():
        rel_posix = target.relative_to(project_root.resolve()).as_posix()
        dst = backup_dir / rel_posix
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(target, dst)
        except OSError:
            return backup_dir
        backup_manifest["operations"].append({"type": "edit_file", "path": rel_posix})
        backed_up.add(rel)
    else:
        backup_manifest["operations"].append({"type": "create_file", "path": rel})
        backed_up.add(rel)

    return backup_dir


def _prompt_tool_review(
    action: ToolAction,
    accept_all_ref: list[bool],
) -> str:
    """
    Показывает панель с dangerous-инструментом и запрашивает подтверждение.

    Возвращает: 'y' (apply) / 'n' (cancel) / 'a' (apply all) / 's' (skip).
    'd' (diff) — показать args полностью и переспросить.
    """
    if accept_all_ref[0]:
        return "y"

    _console.print()

    # Формируем отображение args
    args_lines: list[str] = []
    for k, v in action.args.items():
        v_str = str(v)
        if len(v_str) > 200:
            v_str = v_str[:200] + "..."
        args_lines.append(f"[bold]{k}:[/bold] {v_str}")

    _console.print(
        Panel.fit(
            f"[bold cyan]{action.tool}[/bold cyan]\n" + "\n".join(args_lines),
            title="Подтверждение инструмента",
        )
    )
    if action.reason:
        _console.print(f"[dim]Причина: {action.reason}[/dim]")

    while True:
        try:
            answer = (
                input("\nПрименить? yes(y) / no(n) / all(a) / skip(s) / diff(d): ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return "n"

        if answer in ("y", "n", "a", "s"):
            return answer

        if answer == "d":
            _console.print("\n[bold]Полные args:[/bold]")
            for k, v in action.args.items():
                _console.print(f"  {k}: {v!r}")
            continue

        print("Не понял. Ответь: y / n / a / s / d")


def _accumulate_cost_and_usage(
    ctx, iteration, llm_resp, is_peak, peak_window, cny_to_rub, usd_to_rub
) -> None:
    """Стоимость + append_usage — точная копия оригинала."""
    cost = calculate_cost(
        pricing=ctx.cfg.api.pricing_for(ctx.model),
        is_peak=is_peak,
        peak_window=peak_window,
        prompt_hit_tokens=llm_resp.prompt_cache_hit_tokens,
        prompt_miss_tokens=llm_resp.prompt_cache_miss_tokens,
        completion_tokens=llm_resp.completion_tokens,
        cny_to_rub=cny_to_rub,
        usd_to_rub=usd_to_rub,
    )
    ctx.total_cost_rub += cost.cost_rub
    ctx.total_cost_cny += cost.cost_cny
    ctx.total_cost_usd += cost.cost_usd

    output_root = ctx.project_root / ctx.cfg.output.dir
    append_usage(
        project_root=ctx.project_root,
        output_root=output_root,
        action=f"agent:tool{iteration}",
        project_name=ctx.project_root.name,
        model=ctx.model,
        depth=ctx.depth,
        files_count=0,
        prompt_tokens=llm_resp.prompt_tokens,
        completion_tokens=llm_resp.completion_tokens,
        total_tokens=llm_resp.total_tokens,
        cost=cost,
        duration_ms=llm_resp.duration_ms,
        status="ok",
        usage_cfg=ctx.cfg.usage,
        iteration=iteration,
        parent_action="agent",
    )


def _stop_on_last_iteration(ctx: _ToolLoopCtx) -> None:
    """Установить stopped_reason=max_cost, если исчерпали бюджет на
    последней разрешённой итерации (last_iteration)."""
    ctx.stopped_reason = "max_cost"
    ctx.summary = (
        f"budget last iteration: {ctx.total_cost_rub:.4f} RUB spent, "
        f"limit {ctx.max_cost_rub:.4f} RUB"
    )


def _handle_finish(ctx: _ToolLoopCtx, action: ToolAction, iteration: int, llm_resp) -> None:
    """Обработка finish: success, warnings, сохранение шага."""
    ctx.summary = action.summary or "(no summary)"
    if not action.success:
        ctx.success = False
    elif ctx.step_type is None:
        ctx.success = True
    elif ctx.step_type == "read":
        ctx.success = ctx.read_ops > 0
    else:
        ctx.success = ctx.applied_ops > 0

    if ctx.success:
        write_attempts = sum(1 for a, _ in ctx.history if a.tool in ("write_file", "edit_file"))
        if write_attempts > 0 and write_attempts > ctx.applied_ops:
            ctx.warnings.append(
                f"applied {ctx.applied_ops}/{write_attempts} (часть операций отклонена)"
            )

    # 10.69: если это была последняя разрешённая итерация — перезаписать
    # stopped_reason на max_cost (postcheck не выполнится — finish
    # возвращает break раньше).
    if ctx.last_iteration:
        _stop_on_last_iteration(ctx)

    if ctx.journal_dir is not None:
        _save_tool_loop_step(ctx.journal_dir, iteration, action, None, llm_resp)
        _save_tool_loop_history(ctx.journal_dir, ctx.history)


def _save_tool_loop_history(
    journal_dir: Path,
    history: list[tuple[ToolAction, ToolResult]],
) -> None:
    """
    Сохраняет history.json — машиночитаемый список шагов.

    Формат:
      [
        {
          "iteration": 1,
          "action": {"tool": "read_file", "args": {...}, "finish": false, ...},
          "result": {"ok": true, "output": "...", "error": "", "dry_run": false}
        },
        ...
      ]
    """
    items: list[dict] = []
    for i, (action, result) in enumerate(history, 1):
        items.append(
            {
                "iteration": i,
                "action": {
                    "tool": action.tool,
                    "args": action.args,
                    "reason": action.reason,
                    "finish": action.finish,
                    "summary": action.summary,
                    "success": action.success,
                    "parse_error": action.parse_error,
                },
                "result": {
                    "ok": result.ok,
                    "output": result.output,
                    "error": result.error,
                    "dry_run": result.dry_run,
                },
            }
        )
    try:
        (journal_dir / "history.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _load_tool_loop_history(
    resume_from: Path,
) -> tuple[list[tuple[ToolAction, ToolResult]], str | None]:
    """
    Загружает history.json для продолжения tool loop.

    Returns:
        (history, error). error=None при успехе.
    """
    history_path = resume_from / "history.json"
    if not history_path.exists():
        return [], f"history.json не найден в {resume_from}"

    try:
        items = json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return [], f"не удалось прочитать history.json: {e}"

    if not isinstance(items, list):
        return [], "history.json: ожидался список"

    history: list[tuple[ToolAction, ToolResult]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        a_data = item.get("action", {})
        r_data = item.get("result", {})

        action = ToolAction(
            tool=str(a_data.get("tool", "")),
            args=dict(a_data.get("args", {})),
            reason=str(a_data.get("reason", "")),
            finish=bool(a_data.get("finish", False)),
            summary=str(a_data.get("summary", "")),
            success=bool(a_data.get("success", True)),
            parse_error=a_data.get("parse_error"),
        )
        result = ToolResult(
            ok=bool(r_data.get("ok", False)),
            output=str(r_data.get("output", "")),
            error=str(r_data.get("error", "")),
            dry_run=bool(r_data.get("dry_run", False)),
        )
        history.append((action, result))

    return history, None


def _save_tool_loop_step(
    journal_dir: Path,
    iteration: int,
    action: ToolAction,
    tool_result: ToolResult | None,
    llm: LLMResponse,
) -> None:
    """Сохраняет шаг tool loop в журнал."""
    lines: list[str] = []
    lines.append(f"# Итерация {iteration}\n")
    lines.append(f"- **Модель:** {llm.model}")
    lines.append(f"- **Токены:** prompt {llm.prompt_tokens} / completion {llm.completion_tokens}")
    lines.append(f"- **finish_reason:** {llm.finish_reason}")
    lines.append("")

    if action.parse_error:
        lines.append(f"## ❌ parse_error\n\n{action.parse_error}\n")
        lines.append("\n### Сырой ответ модели\n")
        lines.append("```")
        lines.append(action.raw_json[:5000])
        if len(action.raw_json) > 5000:
            lines.append(f"... [обрезано, всего {len(action.raw_json)} символов]")
        lines.append("```\n")
    elif action.finish:
        lines.append(f"## ✅ finish (success={action.success})\n")
        lines.append(f"{action.summary}\n")
    else:
        lines.append(f"## Инструмент: `{action.tool}`\n")
        lines.append(f"- **Причина:** {action.reason or '(нет)'}")
        lines.append(f"- **Args:** `{action.args}`\n")
        if tool_result is not None:
            status = "✅ ok" if tool_result.ok else "❌ FAIL"
            lines.append(f"## Результат: {status}\n")
            output = tool_result.output or tool_result.error
            lines.append("```")
            lines.append(output[:5000])
            if len(output) > 5000:
                lines.append(f"... [обрезано, всего {len(output)} символов]")
            lines.append("```")

    (journal_dir / f"step-{iteration}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _tool_loop_one_iteration(ctx: _ToolLoopCtx, iteration: int) -> str:
    """Одна итерация цикла. Возвращает "ok" | "continue" | "break".

    Мутирует ctx. НЕ вызывает break/continue — возвращает строку.
    """
    cfg = ctx.cfg
    goal = ctx.goal
    project_root = ctx.project_root
    max_cost_rub = ctx.max_cost_rub
    dry_run = ctx.dry_run
    dry_read = ctx.dry_read
    interactive = ctx.interactive
    allow_blacklist = ctx.allow_blacklist
    max_iterations = ctx.max_iterations

    # --- промпт с текущей историей ---
    history_block = format_tool_history(
        ctx.history,
        read_file_max_chars=cfg.agent.tool_loop_history_max_chars,
        other_max_chars=cfg.agent.tool_loop_history_other_max_chars,
    )
    system, user = render_prompt(
        ctx.prompt_entry,
        depth=ctx.depth,
        scan=ScanResult(root=project_root),
        extra={
            "goal": goal,
            "tools": ctx.tools_block,
            "tree": ctx.scan_meta.tree,
            "history": history_block,
            "max_iterations": str(max_iterations),
            "feedback_section": ctx.feedback_section,
            "subagents_section": ctx.subagents_section,
            "max_spawns": str(ctx.max_spawns),
        },
    )

    # --- тариф ---
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    # --- precheck бюджета ---
    if max_cost_rub is not None and not ctx.last_iteration:
        remaining = max_cost_rub - ctx.total_cost_rub
        last_tool = None
        if ctx.history:
            last_tool = ctx.history[-1][0].tool
        est = _estimate_next_cost_rub(
            cfg,
            ctx.model,
            system,
            user,
            cny_to_rub,
            last_tool=last_tool,
        )
        if est >= remaining:
            if remaining > 0:
                # Остаток положительный — дать итерации завершиться,
                # но это последняя. Postcheck остановит после.
                ctx.last_iteration = True
                _console.print(
                    f"[yellow]Бюджет: последняя итерация (остаток {remaining:.4f} RUB)[/yellow]"
                )
            else:
                # Бюджет исчерпан — стоп сейчас
                ctx.stopped_reason = "max_cost"
                ctx.summary = (
                    f"budget precheck: оценка {est:.4f} RUB >= остатка "
                    f"{remaining:.4f} RUB (лимит {max_cost_rub:.4f}, "
                    f"потрачено {ctx.total_cost_rub:.4f})"
                )
                _console.print(f"[yellow]Бюджет: {ctx.summary}[/yellow]")
                return "break"

    # --- запрос ---
    try:
        llm_resp = ctx.client.chat(
            system=system,
            user=user,
            model=ctx.model,
            json_mode=True,
            max_tokens=cfg.agent.step_max_output_tokens,
        )
    except Exception as e:  # noqa: BLE001
        ctx.stopped_reason = "error"
        ctx.summary = f"LLM call failed: {type(e).__name__}: {e}"
        return "break"

    # --- стоимость + учёт ---
    _accumulate_cost_and_usage(
        ctx, iteration, llm_resp, is_peak, peak_window, cny_to_rub, usd_to_rub
    )

    # --- парсинг ---
    action = parse_tool_action(llm_resp.content)
    if action.parse_error:
        ctx.parse_retries += 1
        if ctx.parse_retries > ctx.max_parse_retries:
            ctx.stopped_reason = "parse_error"
            ctx.summary = (
                f"parse error at iteration {iteration}: "
                f"{action.parse_error} (после {ctx.parse_retries} попыток)"
            )
            ctx.history.append((action, ToolResult(ok=False, error=action.parse_error)))
            if ctx.journal_dir is not None:
                _save_tool_loop_step(ctx.journal_dir, iteration, action, None, llm_resp)
            return "break"
        # retry
        ctx.history.append((action, ToolResult(ok=False, error=action.parse_error)))
        if ctx.journal_dir is not None:
            _save_tool_loop_step(ctx.journal_dir, iteration, action, None, llm_resp)
        return "continue"

    # --- retry missing args ---
    if _has_missing_args(action):
        ctx.arg_retries += 1
        if ctx.arg_retries <= ctx.max_arg_retries:
            hint = _required_args_hint(action.tool)
            ctx.history.append(
                (
                    action,
                    ToolResult(
                        ok=False,
                        error=f"missing args: {hint}. Повтори вызов с полными аргументами.",
                    ),
                )
            )
            if ctx.journal_dir is not None:
                _save_tool_loop_step(ctx.journal_dir, iteration, action, None, llm_resp)
            return "continue"

    # arg_retries сброс при успешной итерации (не finish)
    if not action.finish:
        ctx.arg_retries = 0

    # --- finish ---
    if action.finish:
        _handle_finish(ctx, action, iteration, llm_resp)
        return "break"

    # --- allowlist: enforcement на исполнении, не только в промпте ---
    if action.tool not in ctx.allowed_tools:
        allowed_hint = ", ".join(sorted(ctx.allowed_tools)) or "(нет)"
        denied = ToolResult(
            ok=False,
            error=f"tool '{action.tool}' не разрешён. Доступные: {allowed_hint}",
        )
        ctx.history.append((action, denied))
        if ctx.journal_dir is not None:
            _save_tool_loop_step(ctx.journal_dir, iteration, action, denied, llm_resp)
        return "continue"

    # --- interactive ---
    if interactive:
        spec, _ = TOOL_REGISTRY.get(action.tool, (None, None))
        if spec is not None and spec.dangerous:
            answer = _prompt_tool_review(action, ctx.accept_all_ref)
            if answer == "n":
                ctx.stopped_reason = "cancelled"
                ctx.summary = "отменено пользователем"
                if ctx.journal_dir is not None:
                    _save_tool_loop_step(ctx.journal_dir, iteration, action, None, llm_resp)
                return "break"
            if answer == "s":
                skip_result = ToolResult(ok=False, error="пропущено пользователем")
                ctx.history.append((action, skip_result))
                if ctx.journal_dir is not None:
                    _save_tool_loop_step(ctx.journal_dir, iteration, action, skip_result, llm_resp)
                return "continue"
            if answer == "a":
                ctx.accept_all_ref[0] = True

    # --- бэкап ---
    if not dry_run and action.tool in ("write_file", "edit_file"):
        ctx.backup_dir = _backup_file_for_tool_loop(
            action=action,
            project_root=project_root,
            backup_dir=ctx.backup_dir,
            backed_up=ctx.backed_up,
            backup_manifest=ctx.backup_manifest,
        )

    # --- исполнение ---
    if action.tool == "spawn_subagent":
        # Ленивый импорт: spawn.py импортирует run_tool_loop из этого модуля.
        # spawn_subagent — второй оркестратор, а не обычный tool:
        # execute_tool не видит cfg/ctx/бюджет.
        from .spawn import run_spawn_subagent

        tool_result = run_spawn_subagent(ctx, action.args)
    else:
        tool_result = execute_tool(
            action.tool,
            action.args,
            project_root,
            dry_run=dry_run,
            dry_read=dry_read,
            write_cfg=cfg.write,
            allow_blacklist=allow_blacklist,
        )
    ctx.history.append((action, tool_result))
    if action.tool in ("write_file", "edit_file") and tool_result.ok:
        ctx.applied_ops += 1
    if action.tool in ("read_file", "read_symbol", "list_files") and tool_result.ok:
        ctx.read_ops += 1

    if ctx.journal_dir is not None:
        _save_tool_loop_step(ctx.journal_dir, iteration, action, tool_result, llm_resp)
        _save_tool_loop_history(ctx.journal_dir, ctx.history)

    # --- post-check бюджета ---
    if ctx.last_iteration:
        _stop_on_last_iteration(ctx)
        return "break"
    if max_cost_rub is not None and ctx.total_cost_rub >= max_cost_rub:
        ctx.stopped_reason = "max_cost"
        ctx.summary = f"budget exceeded: {ctx.total_cost_rub:.4f} RUB >= {max_cost_rub:.4f} RUB"
        return "break"

    return "ok"


def _tool_loop_finalize(ctx: _ToolLoopCtx) -> None:
    """Хвост: манифест, verify, откат, коммит, RC, отчёт. Мутирует ctx."""
    # --- манифест бэкапа ---
    if ctx.backup_dir is not None and not ctx.dry_run:
        try:
            (ctx.backup_dir / "manifest.json").write_text(
                json.dumps(ctx.backup_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # --- verify ---
    eff_verify = (
        ctx.verify_commands if ctx.verify_commands is not None else ctx.cfg.agent.verify_commands
    )
    if ctx.success and eff_verify and not ctx.dry_run:
        _console.print(f"[dim]Проверка: {'; '.join(eff_verify)}[/dim]")
        ctx.verify_errors = run_verify_commands(
            eff_verify,
            ctx.project_root,
            timeout_sec=ctx.cfg.agent.verify_timeout_sec,
            max_output_chars=ctx.cfg.agent.verify_max_output_chars,
        )
        if ctx.verify_errors:
            ctx.success = False
            ctx.stopped_reason = "verify_failed"
            ctx.summary = f"verify failed: {len(ctx.verify_errors)} ошибок"
            _console.print(f"[red]Проверка не прошла ({len(ctx.verify_errors)}):[/red]")
            for err in ctx.verify_errors[:5]:
                _console.print(f"  [red]✗[/red] {err}")
            if len(ctx.verify_errors) > 5:
                _console.print(f"  [dim]... ещё {len(ctx.verify_errors) - 5}[/dim]")
            if ctx.backup_dir is not None:
                from ..apply import rollback as _do_rollback

                try:
                    _restored = _do_rollback(ctx.backup_dir, ctx.project_root)
                    if _restored:
                        _console.print(
                            f"[yellow]Откат после verify_failed: {len(_restored)} файлов[/yellow]"
                        )
                except Exception as _e:  # noqa: BLE001
                    _console.print(f"[red]Ошибка отката: {_e}[/red]")
        else:
            _console.print("[green]✅ Проверка пройдена[/green]")

    # --- diff для reverse-check (ДО коммита) ---
    diff_before_commit = ""
    if ctx.reverse_check and ctx.success and not ctx.dry_run and ctx.stopped_reason == "completed":
        diff_before_commit = _collect_diff(ctx.project_root)

    # --- автокоммит ---
    if ctx.auto_commit and ctx.success and not ctx.dry_run and ctx.stopped_reason == "completed":
        from ..git import commit as git_commit
        from ..git import format_commit_message, status_porcelain

        dirty = status_porcelain(ctx.project_root)
        if dirty:
            ops_total = len(ctx.history)
            msg = format_commit_message(goal=ctx.goal, ops=ops_total, cost_rub=ctx.total_cost_rub)
            ctx.commit_hash = git_commit(ctx.project_root, msg)
            if ctx.commit_hash:
                _console.print(f"[green]Коммит:[/green] {ctx.commit_hash}")
        else:
            _console.print("[dim]Автокоммит: нечего коммитить (дерево чистое)[/dim]")

    # --- reverse-check ---
    if ctx.reverse_check and ctx.success and not ctx.dry_run and ctx.stopped_reason == "completed":
        diff = diff_before_commit
        if diff:
            _console.print("[dim]Reverse-check...[/dim]")
            ctx.reverse_result = run_reverse_check(
                goal=ctx.goal,
                diff=diff,
                project_root=ctx.project_root,
                cfg=ctx.cfg,
                prompts_cfg=ctx.prompts_cfg,
            )
            ctx.total_cost_rub += ctx.reverse_result.cost_rub
            ctx.total_cost_cny += ctx.reverse_result.cost_cny
            ctx.total_cost_usd += ctx.reverse_result.cost_usd
            if not ctx.reverse_result.ok:
                for pr in ctx.reverse_result.problems:
                    ctx.warnings.append(f"reverse-check: {pr}")
                _console.print("[yellow]Reverse-check нашёл проблемы:[/yellow]")
                for pr in ctx.reverse_result.problems:
                    _console.print(f"[yellow]   - {pr}[/yellow]")
                if ctx.reverse_result.suggestion:
                    _console.print(f"[yellow]   -> {ctx.reverse_result.suggestion}[/yellow]")
            else:
                _console.print("[green]Reverse-check: ок[/green]")
        else:
            _console.print("[dim]Reverse-check: diff пустой — пропуск[/dim]")

    # --- результат ---
    ctx.result = ToolLoopResult(
        success=ctx.success,
        summary=ctx.summary,
        iterations=len(ctx.history),
        history=ctx.history,
        total_cost_rub=ctx.total_cost_rub,
        total_cost_cny=ctx.total_cost_cny,
        total_cost_usd=ctx.total_cost_usd,
        stopped_reason=ctx.stopped_reason,
        journal_dir=ctx.journal_dir,
        dry_run=ctx.dry_run,
        backup_dir=ctx.backup_dir,
        commit_hash=ctx.commit_hash,
        verify_errors=ctx.verify_errors,
        applied_ops=ctx.applied_ops,
        read_ops=ctx.read_ops,
        warnings=ctx.warnings,
        reverse_check_result=ctx.reverse_result,
    )

    if ctx.journal_dir is not None:
        _save_tool_loop_report(ctx.journal_dir, ctx.result, ctx.goal)


def _save_tool_loop_report(
    journal_dir: Path,
    result: ToolLoopResult,
    goal: str,
) -> None:
    """Сохраняет итоговый отчёт tool loop."""
    lines: list[str] = []
    lines.append(f"# Tool Loop — {goal}\n")
    lines.append(f"- **Успех:** {result.success}")
    lines.append(f"- **Причина остановки:** {result.stopped_reason}")
    lines.append(f"- **Итераций:** {result.iterations}")
    lines.append(f"- **Стоимость:** {result.total_cost_rub:.6f} RUB")
    if result.dry_run:
        lines.append("- **Режим:** dry-run (dangerous-инструменты не выполнялись)")
    if result.backup_dir is not None:
        lines.append(f"- **Бэкап:** {result.backup_dir}")
    if result.commit_hash is not None:
        lines.append(f"- **Коммит:** {result.commit_hash}")
    lines.append(f"- **Summary:** {result.summary}\n")
    if result.warnings:
        lines.append("## Предупреждения\n")
        for w in result.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")
    if result.reverse_check_result is not None:
        rc = result.reverse_check_result
        lines.append("## Reverse-check\n")
        if rc.ok:
            lines.append("- ✅ Проблем не найдено.")
        else:
            lines.append("- ⚠️ Найдены проблемы:")
            for p in rc.problems:
                lines.append(f"  - {p}")
            if rc.suggestion:
                lines.append(f"- **Рекомендация:** {rc.suggestion}")
        if rc.parse_error:
            lines.append(f"- parse_error: {rc.parse_error}")
        lines.append(f"- **Стоимость:** {rc.cost_rub:.6f} RUB")
        lines.append("")
    lines.append("## История\n")
    for i, (action, tool_result) in enumerate(result.history, 1):
        if action.finish:
            lines.append(f"{i}. finish(success={action.success})")
        else:
            status = "ok" if tool_result.ok else "FAIL"
            lines.append(f"{i}. {action.tool}({action.args}) → {status}")
    (journal_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_tool_loop(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    max_iterations: int = 20,
    max_cost_rub: float | None = None,
    journal: bool = True,
    dry_run: bool = False,
    dry_read: bool = False,
    interactive: bool = False,
    auto_commit: bool = False,
    resume_from: Path | None = None,
    journal_subdir: Path | None = None,
    allow_blacklist: bool = False,
    verify_commands: list[str] | None = None,
    step_type: str | None = None,
    reverse_check: bool = False,
    feedback_section: str = "",
    subagents_section: str | None = None,
    allowed_tools: list[str] | None = None,
    spawn_depth: int = 0,
    max_spawns: int | None = None,
    usage_action_prefix: str = "agent",
) -> ToolLoopResult:
    """Tool loop: модель сама вызывает инструменты до завершения.

    Оркестратор: setup + цикл + finalize.
    """
    started_at = datetime.now(ZoneInfo("UTC"))
    model = model or cfg.api.model

    # --- журнал ---
    journal_dir: Path | None = None
    if journal:
        ts = started_at.strftime("%Y-%m-%dT%H-%M-%S")
        if journal_subdir is not None:
            journal_dir = journal_subdir / f"tool-loop-{ts}"
        else:
            journal_dir = project_root / cfg.output.dir / project_root.name / f"tool-loop-{ts}"
        journal_dir.mkdir(parents=True, exist_ok=True)

    # --- metadata-scan ---
    scan_meta = scan_project_metadata(
        project_root,
        cfg.scanning,
        extra_exclude=extra_exclude,
    )

    # --- промпт ---
    prompt_entry = prompts_cfg.get("agent_tool_json")

    # --- effective allowlist (D4 §3.4) ---
    # allowlist enforce'ится и в промпте, и на исполнении: parse_tool_action
    # пропускает любой tool из TOOL_REGISTRY, даже не показанный модели.
    if allowed_tools is not None:
        effective_tools = [t for t in TOOL_REGISTRY if t in set(allowed_tools)]
    else:
        effective_tools = list(TOOL_REGISTRY)
        if not cfg.agent.subagents or spawn_depth > 0:
            # не рекламируем то, что нельзя вызвать
            effective_tools = [t for t in effective_tools if t != "spawn_subagent"]
    tools_block = format_tools_for_prompt(effective_tools)

    if subagents_section is None:
        # Ленивый импорт: spawn.py импортирует run_tool_loop из этого модуля.
        from .spawn import build_subagents_section

        subagents_section = build_subagents_section(cfg.agent.subagents)

    if max_spawns is None:
        max_spawns = cfg.agent.subagent_max_per_task

    # --- resume ---
    history: list = []
    start_iteration = 0
    end_iteration = max_iterations
    loaded_history, err = None, None
    if resume_from is not None:
        loaded_history, err = _load_tool_loop_history(resume_from)
        if err is not None:
            return ToolLoopResult(
                success=False,
                summary=f"resume failed: {err}",
                iterations=0,
                stopped_reason="resume_error",
            )
        history = loaded_history or []
        # пересчёт applied_ops / read_ops из загруженной истории
        _applied = sum(
            1 for act, res in history if act.tool in ("write_file", "edit_file") and res.ok
        )
        _read = sum(
            1
            for act, res in history
            if act.tool in ("read_file", "read_symbol", "list_files") and res.ok
        )
    else:
        _applied = 0
        _read = 0

    # --- client (только если resume ok) ---
    client = LLMClient(cfg.api)

    # --- ctx ---
    ctx = _ToolLoopCtx(
        goal=goal,
        project_root=project_root,
        cfg=cfg,
        prompts_cfg=prompts_cfg,
        client=client,
        model=model,
        depth=depth,
        extra_exclude=extra_exclude,
        max_iterations=max_iterations,
        max_cost_rub=max_cost_rub,
        dry_run=dry_run,
        dry_read=dry_read,
        interactive=interactive,
        auto_commit=auto_commit,
        allow_blacklist=allow_blacklist,
        verify_commands=verify_commands,
        step_type=step_type,
        reverse_check=reverse_check,
        feedback_section=feedback_section,
        subagents_section=subagents_section,
        allowed_tools=frozenset(effective_tools),
        subagents_by_name={s.name: s for s in cfg.agent.subagents},
        spawn_depth=spawn_depth,
        max_spawns=max_spawns,
        usage_action_prefix=usage_action_prefix,
        prompt_entry=prompt_entry,
        tools_block=tools_block,
        scan_meta=scan_meta,
        journal_dir=journal_dir,
        history=history,
        start_iteration=start_iteration,
        end_iteration=end_iteration,
    )
    ctx.applied_ops = _applied
    ctx.read_ops = _read

    # --- цикл ---
    for iteration in range(ctx.start_iteration, ctx.end_iteration):
        action = _tool_loop_one_iteration(ctx, iteration)
        if action == "break":
            break
    else:
        # цикл дошёл до конца без break
        if ctx.stopped_reason == "completed":
            ctx.stopped_reason = "max_iterations"

    # --- хвост ---
    _tool_loop_finalize(ctx)
    assert ctx.result is not None
    return ctx.result


__all__ = [
    "_ToolLoopCtx",
    "_accumulate_cost_and_usage",
    "_backup_file_for_tool_loop",
    "_handle_finish",
    "_has_missing_args",
    "_load_tool_loop_history",
    "_prompt_tool_review",
    "_required_args_hint",
    "_save_tool_loop_history",
    "_save_tool_loop_report",
    "_save_tool_loop_step",
    "_tool_loop_finalize",
    "_tool_loop_one_iteration",
    "run_tool_loop",
]
