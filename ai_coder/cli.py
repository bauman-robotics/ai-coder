from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .actions import run_action, run_fix_action
from .agent import run_agent
from .apply import apply_plan, check_python_files, list_backups
from .apply import rollback as do_rollback
from .config import load_config, load_prompts
from .output import save_report

app = typer.Typer(
    name="ai-coder",
    help="AI-ассистированный анализ git-проектов через DeepSeek API",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


DEFAULT_CONFIG = Path("config/config.yaml")
DEFAULT_PROMPTS = Path("config/prompts.yaml")


def _load(config: Path, prompts: Path):
    if not config.exists():
        console.print(f"[red]Конфиг не найден:[/red] {config}")
        raise typer.Exit(1)
    if not prompts.exists():
        console.print(f"[red]Промпты не найдены:[/red] {prompts}")
        raise typer.Exit(1)
    return load_config(config), load_prompts(prompts)


@app.command("actions")
def list_actions(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    prompts: Path = typer.Option(DEFAULT_PROMPTS, "--prompts", "-p"),
    path: Path = typer.Option(Path("."), "--path", help="Проект для оценки (только с --verbose)"),
    model: str | None = typer.Option(None, "--model", "-m", help="Модель для оценки (с --verbose)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Показать оценку стоимости для текущего проекта"),
):
    """Показать доступные действия из конфига."""
    cfg, pr_cfg = _load(config, prompts)

    if not verbose:
        table = Table(title="Доступные действия", show_lines=False)
        table.add_column("Имя", style="cyan")
        table.add_column("Режим", style="magenta")
        table.add_column("Промпт", style="green")
        table.add_column("Описание")

        for name, act in cfg.enabled_actions().items():
            table.add_row(name, act.mode, act.prompt, act.description)

        console.print(table)
        console.print("\n[dim]Подсказка: `actions --verbose` покажет оценку стоимости на текущем проекте.[/dim]")
        return

    # --- verbose-режим ---
    from .pricing import calculate_cost, get_rate, is_peak_now
    from .prompts import render_prompt
    from .scanner import scan_project

    project_root = path.resolve()
    if not project_root.is_dir():
        console.print(f"[red]Не директория:[/red] {project_root}")
        raise typer.Exit(1)

    model_name = model or cfg.api.model

    with console.status("[cyan]Сканирую проект..."):
        scan = scan_project(project_root, cfg.scanning)

    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    console.print(Panel.fit(
        f"[bold]Проект:[/bold] {project_root}\n"
        f"[bold]Файлов в контексте:[/bold] {len(scan.files)}\n"
        f"[bold]Модель:[/bold] {model_name}\n"
        f"[bold]Тариф:[/bold] {'peak (' + peak_window + ')' if is_peak else 'off-peak'}",
        title="Оценка действий",
    ))

    table = Table(title="Действия и оценка стоимости", show_lines=False)
    table.add_column("Имя", style="cyan")
    table.add_column("Режим", style="magenta")
    table.add_column("Prompt", justify="right")
    table.add_column("Completion", justify="right")
    table.add_column("CNY", justify="right")
    table.add_column("RUB", justify="right")
    table.add_column("Описание", style="dim")

    for name, act in cfg.enabled_actions().items():
        try:
            prompt_entry = pr_cfg.get(act.prompt)
            system, user = render_prompt(prompt_entry, depth="normal", scan=scan)
            prompt_text = system + "\n" + user
            est_prompt = max(1, len(prompt_text) // 3)
        except Exception:
            est_prompt = 0

        est_completion = cfg.api.max_output_tokens // 2

        cost = calculate_cost(
            pricing=cfg.api.pricing_for(model_name),
            is_peak=is_peak,
            peak_window=peak_window,
            prompt_hit_tokens=0,
            prompt_miss_tokens=est_prompt,
            completion_tokens=est_completion,
            cny_to_rub=cny_to_rub,
            usd_to_rub=usd_to_rub,
        )

        table.add_row(
            name,
            act.mode,
            f"~{est_prompt}",
            f"~{est_completion}",
            f"{cost.cost_cny:.4f}",
            f"{cost.cost_rub:.4f}",
            act.description,
        )

    console.print(table)
    console.print(
        "\n[dim]Оценка консервативная (весь prompt как miss, "
        "completion ~ половина max_output_tokens). "
        "Реальный cache hit может снизить стоимость в разы.[/dim]"
    )

@app.command("run")
def run(
    action: str = typer.Argument(..., help="Имя действия из config.yaml"),
    path: Path = typer.Argument(Path("."), help="Путь к проекту"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    prompts: Path = typer.Option(DEFAULT_PROMPTS, "--prompts", "-p"),
    model: str | None = typer.Option(None, "--model", "-m", help="Модель (переопределить)"),
    depth: str = typer.Option("normal", "--depth", "-d", help="shallow|normal|deep"),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Доп. паттерны исключения"),
    apply: bool = typer.Option(False, "--apply", help="Применить план изменений (для write-действий)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждения при --apply"),
    no_verify: bool = typer.Option(False, "--no-verify", help="Не запускать py_compile после применения"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Только оценка: файлы, токены, стоимость — без запроса к API"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Не использовать кэш отчётов"),
    refresh: bool = typer.Option(False, "--refresh", help="Игнорировать кэш и заново спросить API"),
    max_fix_attempts: int | None = typer.Option(None, "--max-fix-attempts", help="Сколько раз пробовать авто-исправление (0 = выключено)"),
    no_auto_fix: bool = typer.Option(False, "--no-auto-fix", help="Отключить авто-исправление ошибок"),
):
    """Выполнить действие над проектом."""
    cfg, pr_cfg = _load(config, prompts)

    project_root = path.resolve()
    if not project_root.is_dir():
        console.print(f"[red]Не директория:[/red] {project_root}")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold]Действие:[/bold] {action}\n"
        f"[bold]Проект:[/bold] {project_root}\n"
        f"[bold]Модель:[/bold] {model or cfg.api.model}\n"
        f"[bold]Глубина:[/bold] {depth}"
        + ("\n[bold]Режим:[/bold] dry-run" if dry_run else "")
        + ("\n[bold]Кэш:[/bold] выключен" if no_cache else ("\n[bold]Кэш:[/bold] refresh" if refresh else "")),
        title="ai-coder",
    ))

    # ---------- dry-run ----------
    if dry_run:
        _run_dry(
            action,
            project_root,
            cfg,
            pr_cfg,
            model=model,
            depth=depth,
            extra_exclude=list(exclude) or None,
        )
        return

    try:
        with console.status("[cyan]Сканирую проект и обращаюсь к DeepSeek..."):
            result = run_action(
                action_name=action,
                project_root=project_root,
                cfg=cfg,
                prompts_cfg=pr_cfg,
                model=model,
                depth=depth,
                extra_exclude=list(exclude) or None,
                use_cache=not no_cache,
                refresh=refresh,
            )
    except Exception as e:
        console.print(f"[red]Ошибка:[/red] {e}")
        raise typer.Exit(1)

    # ---------- применение (для write-действий) ----------
    applied_info: dict | None = None
    plan = result.write_plan

    if plan is not None and apply:
        if not plan.valid:
            console.print("[red]План невалиден, применение отменено.[/red]")
            if plan.parse_error:
                console.print(f"  parse_error: {plan.parse_error}")
            for p in plan.problems:
                console.print(f"  - {p}")
        else:
            _print_plan_summary(plan)

            if not yes:
                proceed = typer.confirm("Применить эти изменения?", default=False)
                if not proceed:
                    console.print("[yellow]Отменено пользователем.[/yellow]")
                    apply = False

            if apply:
                ts_base = datetime.now().strftime("%Y%m%d-%H%M%S")
                base_dir = project_root / cfg.output.dir / project_root.name
                backup_base_name = f"{cfg.write.backup_dir_name}-{ts_base}"

                # --- сколько раз пробовать fix ---
                fix_attempts = 0 if no_auto_fix else (
                    max_fix_attempts if max_fix_attempts is not None else cfg.fix.max_attempts
                )
                if no_verify:
                    fix_attempts = 0

                # --- бэкап №0 и первое применение ---
                backup0 = base_dir / f"{backup_base_name}-attempt0"
                console.print(f"[cyan]Бэкап →[/cyan] {backup0}")
                applied, errors = apply_plan(plan, project_root, backup0)

                if errors:
                    console.print("[red]Не удалось применить:[/red]")
                    for e in errors:
                        console.print(f"  - {e}")
                    applied_info = {
                        "applied": 0,
                        "errors": errors,
                        "rolled_back": False,
                        "backup_dir": backup0,
                        "attempts": 0,
                        "fix_cost_rub": 0.0,
                    }
                else:
                    console.print(f"[green]Применено операций:[/green] {len(applied)}")

                    verify_errors: list[str] = []
                    if cfg.write.verify_after_apply and not no_verify:
                        verify_errors = check_python_files(applied, project_root)

                    # --- цикл авто-исправления ---
                    current_plan = plan
                    current_applied = applied
                    iteration = 0
                    total_fix_cost_rub = 0.0

                    while verify_errors and iteration < fix_attempts:
                        iteration += 1
                        console.print()
                        console.print(Panel.fit(
                            f"[bold]Итерация[/bold] {iteration}/{fix_attempts}\n"
                            f"Ошибок: {len(verify_errors)}\n"
                            f"Отправляю модели на исправление...",
                            title="Авто-исправление",
                        ))

                        try:
                            fix_result = run_fix_action(
                                parent_action=action,
                                iteration=iteration,
                                project_root=project_root,
                                cfg=cfg,
                                prompts_cfg=pr_cfg,
                                errors=verify_errors,
                                previous_plan=current_plan,
                                model=model,
                                depth=depth,
                                extra_exclude=list(exclude) or None,
                                use_cache=not no_cache,
                            )
                        except Exception as e:
                            console.print(f"[red]Ошибка fix-итерации:[/red] {e}")
                            break

                        total_fix_cost_rub += fix_result.cost_rub

                        if fix_result.from_cache:
                            console.print("[yellow]ℹ fix-план из кэша[/yellow]")

                        fix_plan = fix_result.write_plan
                        if fix_plan is None or not fix_plan.valid:
                            console.print("[red]Fix-план невалиден, прекращаю попытки.[/red]")
                            if fix_plan is not None:
                                for p in fix_plan.problems:
                                    console.print(f"  - {p}")
                            break

                        backupN = base_dir / f"{backup_base_name}-attempt{iteration}"
                        console.print(f"[cyan]Бэкап →[/cyan] {backupN}")
                        fix_applied, fix_errors = apply_plan(fix_plan, project_root, backupN)

                        if fix_errors:
                            console.print("[red]Не удалось применить fix-план:[/red]")
                            for e in fix_errors:
                                console.print(f"  - {e}")
                            break

                        console.print(f"[green]Применено операций:[/green] {len(fix_applied)}")
                        current_plan = fix_plan
                        current_applied = fix_applied

                        verify_errors = check_python_files(fix_applied, project_root)

                    # --- итог ---
                    if verify_errors:
                        console.print()
                        console.print("[red]Не удалось исправить автоматически.[/red]")
                        console.print(f"[yellow]Откат к[/yellow] {backup0}")
                        restored = do_rollback(backup0, project_root)
                        console.print(f"[yellow]Изменено путей:[/yellow] {len(restored)}")
                        applied_info = {
                            "applied": 0,
                            "errors": verify_errors,
                            "rolled_back": True,
                            "backup_dir": backup0,
                            "attempts": iteration,
                            "fix_cost_rub": total_fix_cost_rub,
                        }
                    else:
                        console.print("[green]Проверка пройдена.[/green]")
                        if iteration > 0:
                            console.print(f"[dim]Авто-исправлений применено: {iteration}[/dim]")
                        applied_info = {
                            "applied": len(current_applied),
                            "errors": [],
                            "rolled_back": False,
                            "backup_dir": backup0,
                            "attempts": iteration,
                            "fix_cost_rub": total_fix_cost_rub,
                        }

    # ---------- сохраняем отчёт ----------
    report_path = save_report(
        result,
        output_dir=cfg.output.dir,
        per_project_subdir=cfg.output.per_project_subdir,
        filename_pattern=cfg.output.filename_pattern,
        save_raw=cfg.output.save_raw_response,
        applied_info=applied_info,
    )

    # ---------- сводка ----------
    _print_result_summary(result, report_path)

    if result.llm.finish_reason == "length":
        console.print(
            "[yellow]⚠️ Ответ модели обрезан по лимиту max_output_tokens. "
            "Проверьте отчёт — результат может быть неполным.[/yellow]"
        )

    if getattr(result, "from_cache", False):
        console.print("[yellow]ℹ Результат из кэша — API не вызывался, стоимость 0.[/yellow]")

def _print_plan_summary(plan) -> None:
    console.print()
    console.print(Panel.fit(
        f"[bold]Операций:[/bold] {len(plan.operations)}\n"
        f"[bold]Файлов затронуто:[/bold] {len({op.path for op in plan.operations})}",
        title="План изменений",
    ))
    files_table = Table(title="Файлы", show_header=True, box=None)
    files_table.add_column("Тип", style="magenta")
    files_table.add_column("Путь", style="cyan")
    seen: set[tuple[str, str]] = set()
    for op in plan.operations:
        key = (op.type, op.path)
        if key in seen:
            continue
        seen.add(key)
        files_table.add_row(op.type, op.path)
    console.print(files_table)


def _print_result_summary(result, report_path: Path) -> None:
    llm = result.llm
    from_cache = getattr(result, "from_cache", False)

    table = Table(title="Результат", show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Файлов:", str(len(result.scan.files)))

    if from_cache:
        table.add_row("Источник:", "[yellow]кэш[/yellow] (API не вызывался)")
        table.add_row("Токенов (из кэша):", f"{llm.total_tokens}")
        table.add_row("Стоимость:", "0.000000 CNY / 0.000000 RUB / 0.000000 USD")
    else:
        table.add_row(
            "Токенов prompt:",
            f"{llm.prompt_tokens} (hit: {llm.prompt_cache_hit_tokens}, miss: {llm.prompt_cache_miss_tokens})",
        )
        table.add_row("Токенов completion:", str(llm.completion_tokens))
        table.add_row("Всего токенов:", str(llm.total_tokens))
        table.add_row("Тариф:", "peak" if result.is_peak else "off-peak")
        table.add_row(
            "Стоимость:",
            f"{result.cost_cny:.6f} CNY / {result.cost_rub:.6f} RUB / {result.cost_usd:.6f} USD",
        )
        table.add_row("Длительность:", f"{llm.duration_ms / 1000:.1f} c")

    try:
        rel = report_path.relative_to(Path.cwd())
        table.add_row("Отчёт:", str(rel))
    except ValueError:
        table.add_row("Отчёт:", str(report_path))

    console.print(table)

def _run_dry(
    action: str,
    project_root: Path,
    cfg,
    pr_cfg,
    *,
    model: str | None,
    depth: str,
    extra_exclude: list[str] | None,
) -> None:
    """Оценка без запроса к API."""
    from .pricing import calculate_cost, get_rate, is_peak_now
    from .prompts import render_prompt
    from .scanner import scan_project

    action_cfg = cfg.actions.get(action)
    if action_cfg is None:
        console.print(f"[red]Действие '{action}' не найдено в конфиге[/red]")
        raise typer.Exit(1)
    if not action_cfg.enabled:
        console.print(f"[red]Действие '{action}' отключено[/red]")
        raise typer.Exit(1)

    model = model or cfg.api.model

    with console.status("[cyan]Сканирую проект..."):
        scan = scan_project(project_root, cfg.scanning, extra_exclude=extra_exclude)

    try:
        prompt_entry = pr_cfg.get(action_cfg.prompt)
    except KeyError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    system, user = render_prompt(prompt_entry, depth=depth, scan=scan)
    prompt_text = system + "\n" + user

    est_prompt_tokens = max(1, len(prompt_text) // 3)
    est_completion_tokens = cfg.api.max_output_tokens // 2

    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    cost = calculate_cost(
        pricing=cfg.api.pricing_for(model),
        is_peak=is_peak,
        peak_window=peak_window,
        prompt_hit_tokens=0,
        prompt_miss_tokens=est_prompt_tokens,
        completion_tokens=est_completion_tokens,
        cny_to_rub=cny_to_rub,
        usd_to_rub=usd_to_rub,
    )

    table = Table(title="Оценка (dry-run)", show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Файлов в контексте:", str(len(scan.files)))
    table.add_row("Отсеяно:", str(len(scan.skipped)))
    table.add_row("Обрезано по бюджету:", "да" if scan.truncated else "нет")
    table.add_row("Оценка prompt-токенов:", f"~{est_prompt_tokens}")
    table.add_row("Оценка completion:", f"~{est_completion_tokens}")
    table.add_row("Тариф:", f"peak ({peak_window})" if is_peak else "off-peak")
    table.add_row("Курс CNY/RUB:", f"{cny_to_rub.value:.4f} ({cny_to_rub.source})")
    table.add_row("Курс USD/RUB:", f"{usd_to_rub.value:.4f} ({usd_to_rub.source})")
    table.add_row(
        "Оценка стоимости:",
        f"{cost.cost_cny:.6f} CNY / {cost.cost_rub:.6f} RUB / {cost.cost_usd:.6f} USD",
    )
    console.print(table)

    console.print(
        "\n[dim]Оценка консервативная (весь prompt как miss, "
        "completion ~ половина max_output_tokens). "
        "Реальный cache hit может снизить стоимость в разы.[/dim]"
    )

@app.command("agent")
def agent_cmd(
    goal: str = typer.Argument(..., help="Цель агента (что нужно сделать)"),
    path: Path = typer.Argument(Path("."), help="Путь к проекту"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    prompts: Path = typer.Option(DEFAULT_PROMPTS, "--prompts", "-p"),
    model: str | None = typer.Option(None, "--model", "-m", help="Модель (переопределить)"),
    depth: str = typer.Option("normal", "--depth", "-d", help="shallow|normal|deep"),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Доп. паттерны исключения"),
    apply: bool = typer.Option(False, "--apply", help="Применять шаги (по умолчанию — только план и предложения)"),
    verify: bool = typer.Option(True, "--verify/--no-verify", help="Проверять py_compile после каждого шага"),
    max_steps: int | None = typer.Option(None, "--max-steps", help="Максимум шагов (по умолчанию из конфига)"),
    max_minutes: int | None = typer.Option(None, "--max-minutes", help="Максимум минут (по умолчанию из конфига)"),
    max_fix_attempts: int = typer.Option(0, "--max-fix-attempts", help="Попыток fix на шаг (0 = без fix)"),
    journal: bool = typer.Option(True, "--journal/--no-journal", help="Сохранять журнал агента в .ai-out/<project>/agent-<ts>/"),
    preview_only: bool = typer.Option(False, "--preview-only", help="Только план и оценка, без выполнения шагов (экономит токены)"),
):

    """Запустить агента: LLM строит план шагов и выполняет их по цели."""
    cfg, pr_cfg = _load(config, prompts)

    project_root = path.resolve()
    if not project_root.is_dir():
        console.print(f"[red]Не директория:[/red] {project_root}")
        raise typer.Exit(1)

    if preview_only and apply:
        console.print("[red]Нельзя одновременно --preview-only и --apply[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold]Цель:[/bold] {goal}\n"
        f"[bold]Проект:[/bold] {project_root}\n"
        f"[bold]Модель:[/bold] {model or cfg.api.model}\n"
        f"[bold]Глубина:[/bold] {depth}\n"
        f"[bold]Режим:[/bold] {'apply' if apply else 'preview (без применения)'}"
        + ("\n[bold]Только план:[/bold] да (--preview-only)" if preview_only else "")
        + f"\n[bold]Верификация:[/bold] {'вкл' if verify else 'выкл'}",
        title="ai-coder agent",
    ))

    try:
        with console.status("[cyan]Планирую и выполняю..."):
            result = run_agent(
                goal=goal,
                project_root=project_root,
                cfg=cfg,
                prompts_cfg=pr_cfg,
                model=model,
                depth=depth,
                extra_exclude=list(exclude) or None,
                apply=apply,
                verify=verify,
                max_fix_attempts=max_fix_attempts,
                max_steps=max_steps,
                max_minutes=max_minutes,
                journal=journal,
                preview_only=preview_only,
            )
    except Exception as e:
        console.print(f"[red]Ошибка агента:[/red] {e}")
        raise typer.Exit(1)

    # --- шапка с планом ---
    _print_agent_plan(result)

    if result.plan.valid:
        # --- шапка прогресса ---
        for sr in result.steps:
            _print_agent_step_summary(sr)

    # --- итог ---
    _print_agent_summary(result)

@app.command("rollback")
def rollback_cmd(
    backup_dir: Path = typer.Argument(..., help="Папка бэкапа (из .ai-out/<project>/backup-*)"),
    path: Path = typer.Argument(Path("."), help="Путь к проекту"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждения"),
):
    """Откатить изменения проекта из указанного бэкапа."""
    project_root = path.resolve()
    backup_dir = backup_dir.resolve()

    if not backup_dir.is_dir():
        console.print(f"[red]Бэкап не найден:[/red] {backup_dir}")
        raise typer.Exit(1)

    # читаем манифест, если есть
    manifest_path = backup_dir / "manifest.json"
    ops_count = 0
    if manifest_path.exists():
        try:
            import json as _json
            manifest = _json.loads(manifest_path.read_text(encoding="utf-8"))
            ops_count = len(manifest.get("operations", []))
        except Exception:
            ops_count = 0

    files = [p for p in backup_dir.rglob("*") if p.is_file() and p.name != "manifest.json"]
    console.print(Panel.fit(
        f"[bold]Бэкап:[/bold] {backup_dir}\n"
        f"[bold]Файлов в бэкапе:[/bold] {len(files)}\n"
        f"[bold]Операций в манифесте:[/bold] {ops_count}\n"
        f"[bold]Проект:[/bold] {project_root}",
        title="Откат",
    ))

    if not yes:
        proceed = typer.confirm("Откатить изменения по этому бэкапу?", default=False)
        if not proceed:
            console.print("[yellow]Отменено.[/yellow]")
            raise typer.Exit(0)

    try:
        changed = do_rollback(backup_dir, project_root)
        console.print(f"[green]Изменено путей:[/green] {len(changed)}")
        for r in changed:
            # префиксы: '~' — восстановлено, '-' — удалено
            console.print(f"  {r}")
    except Exception as e:
        console.print(f"[red]Ошибка отката:[/red] {e}")
        raise typer.Exit(1)


@app.command("backups")
def backups_cmd(
    path: Path = typer.Argument(Path("."), help="Путь к проекту"),
):
    """Список бэкапов проекта."""
    project_root = path.resolve()
    backups = list_backups(project_root)

    if not backups:
        console.print("[yellow]Бэкапов нет.[/yellow]")
        raise typer.Exit(0)

    table = Table(title=f"Бэкапы — {project_root.name}")
    table.add_column("Имя", style="cyan")
    table.add_column("Файлов", justify="right")
    table.add_column("Операций", justify="right")
    table.add_column("Путь", style="dim")

    for b in backups:
        table.add_row(
            b["name"],
            str(b["files"]),
            str(b.get("operations", 0)),
            str(b["dir"]),
        )
    console.print(table)

@app.command("usage")
def usage_show(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    since: str | None = typer.Option(None, "--since", help="С какого дня (YYYY-MM-DD), в UTC"),
    until: str | None = typer.Option(None, "--until", help="По какой день (YYYY-MM-DD), в UTC"),
    action: str | None = typer.Option(None, "--action", "-a", help="Фильтр по действию"),
    project: str | None = typer.Option(None, "--project", help="Фильтр по имени проекта"),
    model: str | None = typer.Option(None, "--model", "-m", help="Фильтр по модели"),
    export: str | None = typer.Option(None, "--export", help="csv|json — выгрузить отфильтрованные записи"),
    out: Path | None = typer.Option(None, "--out", help="Файл для экспорта (по умолчанию stdout)"),
):
    """Показать сводку расходов с фильтрами."""
    import csv
    import io
    import json as _json

    cfg = load_config(config)
    jsonl_path = Path(cfg.usage.jsonl)
    if not jsonl_path.exists():
        console.print("[yellow]Журнал пуст — ещё не было запросов.[/yellow]")
        raise typer.Exit(0)

    # --- читаем все записи ---
    records: list[dict] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue

    # --- фильтры ---
    def _match(r: dict) -> bool:
        day = (r.get("ts_utc") or "")[:10]
        if since and day < since:
            return False
        if until and day > until:
            return False
        if action and r.get("action") != action:
            return False
        if project and r.get("project_name") != project:
            return False
        if model and r.get("model") != model:
            return False
        return True

    filtered = [r for r in records if _match(r)]

    if not filtered:
        console.print("[yellow]Под фильтры ничего не попало.[/yellow]")
        raise typer.Exit(0)

    # --- экспорт ---
    if export:
        if export not in ("csv", "json"):
            console.print(f"[red]Неизвестный формат: {export} (ожидается csv или json)[/red]")
            raise typer.Exit(1)

        if export == "json":
            payload = _json.dumps(filtered, ensure_ascii=False, indent=2)
        else:  # csv
            fields = [
                "ts_utc", "ts_msk", "action", "project_name", "model", "depth",
                "files_count", "prompt_tokens", "prompt_cache_hit_tokens",
                "prompt_cache_miss_tokens", "completion_tokens", "total_tokens",
                "is_peak", "cost_cny", "cost_rub", "cost_usd",
                "cny_to_rub_rate", "usd_to_rub_rate", "rate_source",
                "duration_ms", "status",
            ]
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for r in filtered:
                writer.writerow(r)
            payload = buf.getvalue()

        if out:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(payload, encoding="utf-8")
            console.print(f"[green]Экспортировано:[/green] {out} ({len(filtered)} записей)")
        else:
            console.print(payload)
        return

    # --- агрегаты по отфильтрованному ---
    total = _aggregate(filtered)
    _print_usage_table("Итого (по фильтру)", total)

    # группировки
    by_action = _group(filtered, "action")
    by_model = _group(filtered, "model")
    by_project = _group(filtered, "project_name")
    by_day = _group(filtered, "ts_utc", key_fn=lambda v: (v or "")[:10])

    _print_group_table("По действиям", by_action)
    _print_group_table("По моделям", by_model)
    _print_group_table("По проектам", by_project)

    # по дням — последние 14
    days_sorted = sorted(by_day.items(), reverse=True)[:14]
    _print_group_table("По дням (последние 14)", dict(days_sorted))

    # --- контекст фильтров ---
    if any([since, until, action, project, model]):
        console.print()
        parts = []
        if since:
            parts.append(f"since={since}")
        if until:
            parts.append(f"until={until}")
        if action:
            parts.append(f"action={action}")
        if project:
            parts.append(f"project={project}")
        if model:
            parts.append(f"model={model}")
        console.print(f"[dim]Фильтры: {', '.join(parts)}. Записей: {len(filtered)} из {len(records)}[/dim]")


def _aggregate(records: list[dict]) -> dict:
    total = {
        "requests": len(records),
        "prompt_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_cny": 0.0,
        "cost_rub": 0.0,
        "cost_usd": 0.0,
    }
    for r in records:
        for k in (
            "prompt_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
            "completion_tokens", "total_tokens",
        ):
            total[k] += r.get(k, 0)
        for k in ("cost_cny", "cost_rub", "cost_usd"):
            total[k] += r.get(k, 0.0)
    return total


def _group(records: list[dict], field: str, key_fn=None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in records:
        key = key_fn(r.get(field)) if key_fn else r.get(field, "?")
        if key not in out:
            out[key] = {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_cny": 0.0,
                "cost_rub": 0.0,
            }
        slot = out[key]
        slot["requests"] += 1
        slot["prompt_tokens"] += r.get("prompt_tokens", 0)
        slot["completion_tokens"] += r.get("completion_tokens", 0)
        slot["total_tokens"] += r.get("total_tokens", 0)
        slot["cost_cny"] += r.get("cost_cny", 0.0)
        slot["cost_rub"] += r.get("cost_rub", 0.0)
    return out


def _print_usage_table(title: str, total: dict) -> None:
    table = Table(title=title, show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Запросов:", str(total.get("requests", 0)))
    table.add_row("Prompt токенов:", str(total.get("prompt_tokens", 0)))
    table.add_row("  — hit:", str(total.get("prompt_cache_hit_tokens", 0)))
    table.add_row("  — miss:", str(total.get("prompt_cache_miss_tokens", 0)))
    table.add_row("Completion токенов:", str(total.get("completion_tokens", 0)))
    table.add_row("Всего токенов:", str(total.get("total_tokens", 0)))
    table.add_row("Стоимость CNY:", f"{total.get('cost_cny', 0):.6f}")
    table.add_row("Стоимость RUB:", f"{total.get('cost_rub', 0):.6f}")
    table.add_row("Стоимость USD:", f"{total.get('cost_usd', 0):.6f}")
    console.print(table)


def _print_group_table(title: str, data: dict[str, dict]) -> None:
    if not data:
        return
    t = Table(title=title)
    t.add_column("Ключ", style="cyan")
    t.add_column("Запросов", justify="right")
    t.add_column("Токенов", justify="right")
    t.add_column("RUB", justify="right")
    for key, slot in data.items():
        t.add_row(str(key), str(slot["requests"]), str(slot["total_tokens"]), f"{slot['cost_rub']:.4f}")
    console.print(t)

def _print_agent_plan(result) -> None:
    console.print()
    console.print(Panel.fit(
        f"[bold]План:[/bold] {len(result.plan.steps)} шагов\n"
        f"[bold]Стоимость планировщика:[/bold] {result.planner_cost_rub:.6f} RUB",
        title="План агента",
    ))
    if result.plan.explanation:
        console.print(f"[dim]{result.plan.explanation}[/dim]\n")

    if result.plan.parse_error is not None:
        console.print(f"[red]Ошибка парсинга плана:[/red] {result.plan.parse_error}")
        return

    if result.plan.empty:
        console.print("[yellow]Модель считает, что цель уже достигнута (план пуст).[/yellow]")
        if result.plan.explanation:
            console.print(f"[dim]{result.plan.explanation}[/dim]")
        return

    if not result.plan.steps:
        return

    table = Table(title="Шаги", show_lines=False)
    table.add_column("#", justify="right")
    table.add_column("Название", style="cyan")
    table.add_column("Файлы", style="dim")
    for s in result.plan.steps:
        files = ", ".join(s.target_files[:3])
        if len(s.target_files) > 3:
            files += f" … (+{len(s.target_files) - 3})"
        table.add_row(str(s.n), s.title, files or "—")
    console.print(table)

    if result.stopped_reason == "preview_only":
        console.print(
            "\n[yellow]Режим --preview-only:[/yellow] шаги не выполнены. "
            "Запустите без флага, чтобы выполнить план (с --apply для применения)."
        )

def _print_agent_step_summary(sr) -> None:
    s = sr.step
    status_parts: list[str] = []
    if sr.applied:
        n = sr.applied_count
        status_parts.append(f"[green]применено ({n} операций)[/green]")
    elif sr.skipped:
        reason = f": {sr.skip_reason}" if sr.skip_reason else ""
        status_parts.append(f"[yellow]пропущено{reason}[/yellow]")
    if sr.errors:
        status_parts.append("[red]ошибки[/red]")
    if sr.verify_errors:
        status_parts.append("[red]verify failed[/red]")
    if sr.rolled_back:
        status_parts.append("[yellow]откат[/yellow]")

    status = " / ".join(status_parts) or "[dim]только предложение[/dim]"

    console.print(f"\n[bold]Шаг {s.n}:[/bold] {s.title} — {status}")
    console.print(f"  [dim]Токенов: {sr.llm.total_tokens}, стоимость: {sr.cost_rub:.6f} RUB[/dim]")
    if sr.errors:
        for e in sr.errors:
            console.print(f"  [red]✗[/red] {e}")
    if sr.verify_errors:
        for e in sr.verify_errors[:3]:
            console.print(f"  [red]✗[/red] {e}")
        if len(sr.verify_errors) > 3:
            console.print(f"  [dim]... ещё {len(sr.verify_errors) - 3}[/dim]")

def _print_agent_summary(result) -> None:
    duration = (result.finished_at - result.started_at).total_seconds()
    console.print()
    table = Table(title="Итог", show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Длительность:", f"{duration:.1f} c")
    table.add_row("Причина остановки:", result.stopped_reason)
    table.add_row("Выполнено шагов:", f"{len(result.steps)} из {len(result.plan.steps)}")
    table.add_row("Стоимость планировщика:", f"{result.planner_cost_rub:.6f} RUB")
    table.add_row("Стоимость шагов:", f"{sum(s.cost_rub for s in result.steps):.6f} RUB")
    table.add_row("**Всего:**", f"{result.total_cost_rub:.6f} RUB")

    if result.journal_dir:
        try:
            rel = result.journal_dir.relative_to(Path.cwd())
            table.add_row("Журнал:", str(rel))
        except ValueError:
            table.add_row("Журнал:", str(result.journal_dir))
    console.print(table)

    if not result.steps or any(not s.applied for s in result.steps):
        if not result.plan.valid:
            pass
        elif not any(s.applied for s in result.steps) and result.plan.steps:
            console.print(
                "\n[dim]Совет: запустите с `--apply`, чтобы применить предложенные изменения.[/dim]"
            )

if __name__ == "__main__":
    app()
