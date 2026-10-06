from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .actions import run_action
from .apply import apply_plan, check_python_files, list_backups, rollback as do_rollback
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
):
    """Показать доступные действия из конфига."""
    cfg, _ = _load(config, prompts)

    table = Table(title="Доступные действия", show_lines=False)
    table.add_column("Имя", style="cyan")
    table.add_column("Режим", style="magenta")
    table.add_column("Промпт", style="green")
    table.add_column("Описание")

    for name, act in cfg.enabled_actions().items():
        table.add_row(name, act.mode, act.prompt, act.description)

    console.print(table)

@app.command("run")
def run(
    action: str = typer.Argument(..., help="Имя действия из config.yaml"),
    path: Path = typer.Argument(Path("."), help="Путь к проекту"),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", "-c"),
    prompts: Path = typer.Option(DEFAULT_PROMPTS, "--prompts", "-p"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Модель (переопределить)"),
    depth: str = typer.Option("normal", "--depth", "-d", help="shallow|normal|deep"),
    exclude: list[str] = typer.Option([], "--exclude", "-x", help="Доп. паттерны исключения"),
    apply: bool = typer.Option(False, "--apply", help="Применить план изменений (для write-действий)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Не спрашивать подтверждения при --apply"),
    no_verify: bool = typer.Option(False, "--no-verify", help="Не запускать py_compile после применения"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Только оценка: файлы, токены, стоимость — без запроса к API"),
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
        + ("\n[bold]Режим:[/bold] dry-run" if dry_run else ""),
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
                ts = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup_dir = project_root / cfg.output.dir / project_root.name / f"{cfg.write.backup_dir_name}-{ts}"

                console.print(f"[cyan]Бэкап →[/cyan] {backup_dir}")
                applied, errors = apply_plan(plan, project_root, backup_dir)

                if errors:
                    console.print("[red]Не удалось применить:[/red]")
                    for e in errors:
                        console.print(f"  - {e}")
                else:
                    console.print(f"[green]Применено операций:[/green] {len(applied)}")

                    verify_errors: list[str] = []
                    if cfg.write.verify_after_apply and not no_verify:
                        verify_errors = check_python_files(applied, project_root)

                    if verify_errors:
                        console.print("[red]Проверка не пройдена — откат:[/red]")
                        for e in verify_errors:
                            console.print(f"  - {e}")
                        restored = do_rollback(backup_dir, project_root)
                        console.print(f"[yellow]Откат выполнен:[/yellow] изменено путей {len(restored)}")
                        applied_info = {"applied": 0, "errors": verify_errors, "rolled_back": True, "backup_dir": backup_dir}
                    else:
                        console.print("[green]Проверка пройдена.[/green]")
                        applied_info = {"applied": len(applied), "errors": [], "rolled_back": False, "backup_dir": backup_dir}

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
    table = Table(title="Результат", show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Файлов:", str(len(result.scan.files)))
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
    from .scanner import scan_project
    from .prompts import render_prompt
    from .pricing import is_peak_now, get_rate, calculate_cost

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
):
    """Показать сводку расходов."""
    import json
    cfg = load_config(config)
    summary_path = Path(cfg.usage.summary)
    if not summary_path.exists():
        console.print("[yellow]Сводка пуста — ещё не было запросов.[/yellow]")
        raise typer.Exit(0)

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    total = data.get("total", {})

    table = Table(title="Итого", show_header=False, box=None)
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

    by_action = data.get("by_action", {})
    if by_action:
        t = Table(title="По действиям")
        t.add_column("Действие", style="cyan")
        t.add_column("Запросов", justify="right")
        t.add_column("Токенов", justify="right")
        t.add_column("RUB", justify="right")
        for name, slot in sorted(by_action.items()):
            t.add_row(name, str(slot["requests"]), str(slot["total_tokens"]), f"{slot['cost_rub']:.4f}")
        console.print(t)


if __name__ == "__main__":
    app()