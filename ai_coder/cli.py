from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .actions import run_action
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
        f"[bold]Глубина:[/bold] {depth}",
        title="ai-coder",
    ))

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

    # сохраняем отчёт
    report_path = save_report(
        result,
        output_dir=cfg.output.dir,
        per_project_subdir=cfg.output.per_project_subdir,
        filename_pattern=cfg.output.filename_pattern,
        save_raw=cfg.output.save_raw_response,
    )

    # сводка
    llm = result.llm
    table = Table(title="Результат", show_header=False, box=None)
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Файлов:", str(len(result.scan.files)))
    table.add_row("Токенов prompt:", f"{llm.prompt_tokens} (hit: {llm.prompt_cache_hit_tokens}, miss: {llm.prompt_cache_miss_tokens})")
    table.add_row("Токенов completion:", str(llm.completion_tokens))
    table.add_row("Всего токенов:", str(llm.total_tokens))
    table.add_row("Тариф:", "peak" if result.is_peak else "off-peak")
    table.add_row("Стоимость:", f"{result.cost_cny:.6f} CNY / {result.cost_rub:.6f} RUB / {result.cost_usd:.6f} USD")
    table.add_row("Длительность:", f"{llm.duration_ms / 1000:.1f} c")
    table.add_row("Отчёт:", str(report_path.relative_to(Path.cwd()) if report_path.is_relative_to(Path.cwd()) else report_path))
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