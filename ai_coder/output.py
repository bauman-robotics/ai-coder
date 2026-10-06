from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .actions import ActionResult


def _fmt_float(value: float, digits: int = 6) -> str:
    return f"{value:.{digits}f}"


def _resolve_output_path(
    project_root: Path,
    output_dir: str,
    per_project_subdir: bool,
    filename_pattern: str,
    action: str,
    timestamp: str,
) -> Path:
    base = project_root / output_dir
    if per_project_subdir:
        base = base / project_root.name
    filename = filename_pattern.format(action=action, timestamp=timestamp)
    return base / filename


def render_report(result: ActionResult) -> str:
    """
    Формирует MD-отчёт с метаданными, телом ответа и приложениями.
    """
    scan = result.scan
    llm = result.llm

    started_utc = result.started_at
    finished_utc = result.finished_at
    started_msk = started_utc.astimezone(ZoneInfo("Europe/Moscow"))
    duration_s = (finished_utc - started_utc).total_seconds()

    peak_label = f"peak ({result.peak_window})" if result.is_peak else "off-peak"

    savings_note = ""
    if llm.prompt_cache_hit_tokens > 0:
        savings_note = (
            f"\n- Экономия за счёт кэша: "
            f"{llm.prompt_cache_hit_tokens} hit / {llm.prompt_cache_miss_tokens} miss"
        )

    report = f"""# {result.action} — {scan.root.name}

- **Модель:** {result.model}
- **Глубина:** {result.depth}
- **Тариф:** {peak_label}
- **Файлов проанализировано:** {len(scan.files)}
- **Оценка токенов контента:** ~{scan.estimated_tokens}
- **Начало (UTC):** {started_utc.isoformat(timespec="seconds")}
- **Начало (МСК):** {started_msk.isoformat(timespec="seconds")}
- **Длительность:** {duration_s:.1f} c
- **finish_reason:** {llm.finish_reason}

## Расход

| Показатель | Токены |
|---|---:|
| Prompt (всего) | {llm.prompt_tokens} |
| — cache hit | {llm.prompt_cache_hit_tokens} |
| — cache miss | {llm.prompt_cache_miss_tokens} |
| Completion | {llm.completion_tokens} |
| **Всего** | {llm.total_tokens} |

| Валюта | Стоимость |
|---|---:|
| CNY | {_fmt_float(result.cost_cny)} |
| RUB | {_fmt_float(result.cost_rub)} |
| USD | {_fmt_float(result.cost_usd)} |
{savings_note}

---

## Ответ модели

{llm.content}

---

## Приложение: файлы в контексте

~~~
{scan.tree}
~~~
"""

    if scan.skipped:
        from collections import Counter
        reasons = Counter(s.reason for s in scan.skipped)
        report += "\n## Отсеянные файлы\n\n"
        report += "| Причина | Кол-во |\n|---|---:|\n"
        for reason, count in reasons.most_common():
            report += f"| {reason} | {count} |\n"
        report += "\nПодробнее (первые 50):\n\n```\n"
        for s in scan.skipped[:50]:
            report += f"{s.reason:15} {s.path}\n"
        if len(scan.skipped) > 50:
            report += f"... ещё {len(scan.skipped) - 50}\n"
        report += "```\n"

    if scan.truncated:
        report += "\n> ⚠️ Часть файлов не вошла в бюджет токенов (см. `budget` в отсеянных).\n"

    return report


def save_report(
    result: ActionResult,
    *,
    output_dir: str,
    per_project_subdir: bool,
    filename_pattern: str,
    save_raw: bool,
) -> Path:
    timestamp = result.started_at.strftime("%Y-%m-%dT%H-%M-%S")
    path = _resolve_output_path(
        project_root=result.scan.root,
        output_dir=output_dir,
        per_project_subdir=per_project_subdir,
        filename_pattern=filename_pattern,
        action=result.action,
        timestamp=timestamp,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(result), encoding="utf-8")

    if save_raw:
        raw_path = path.with_suffix(path.suffix + ".raw.txt")
        raw_path.write_text(result.llm.content, encoding="utf-8")

    return path