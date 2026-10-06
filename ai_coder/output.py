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


def render_report(result: ActionResult, applied_info: dict | None = None) -> str:
    """
    Формирует MD-отчёт с метаданными, телом ответа и приложениями.
    Для write-действий дополнительно выводит план изменений и diff.
    applied_info — если план применялся: {'applied': N, 'errors': [...],
    'rolled_back': bool, 'backup_dir': Path | None}.
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

    # --- блок про кэш отчётов ---
    cache_note = ""
    if getattr(result, "from_cache", False):
        cache_note = "\n- **Источник:** результат из кэша (API не вызывался, стоимость 0)\n"

    # --- блок про применение (для write-действий) ---
    apply_note = ""
    if applied_info is not None:
        n = applied_info.get("applied", 0)
        rolled = applied_info.get("rolled_back", False)
        backup_dir = applied_info.get("backup_dir")
        errs = applied_info.get("errors", [])
        if rolled:
            apply_note = (
                f"\n- **Применение:** ❌ откат (проверка не пройдена)\n"
                f"- **Бэкап:** `{backup_dir}`\n"
            )
        elif n > 0:
            apply_note = (
                f"\n- **Применение:** ✅ применено операций: {n}\n"
                f"- **Бэкап:** `{backup_dir}`\n"
            )
        else:
            apply_note = f"\n- **Применение:** не выполнено\n"
        if errs:
            apply_note += f"- **Ошибки:** {len(errs)}\n"

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
{cache_note}{apply_note}
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
"""

    if result.write_plan is not None:
        report += _render_write_section(result.write_plan)
    else:
        report += f"""
## Ответ модели

{llm.content}

---
"""

    report += f"""
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


def _render_write_section(plan) -> str:
    """
    Секция отчёта для write-действий.
    plan — WritePlan из ai_coder.apply.
    """
    parts: list[str] = []

    parts.append("\n## ⚠️ Предложение изменений (НЕ применено)\n")
    parts.append(
        "Этот отчёт содержит **предложение** правок. "
        "Никакие файлы не изменены. Применение — отдельной командой (в следующих версиях).\n"
    )

    # --- объяснение ---
    if plan.explanation:
        parts.append("\n### Что и зачем\n")
        parts.append(plan.explanation + "\n")

    # --- сводка операций ---
    parts.append(f"\n### Операции ({len(plan.operations)})\n")
    if plan.operations:
        parts.append("\n| # | Тип | Путь |\n|---:|---|---|\n")
        for i, op in enumerate(plan.operations, 1):
            parts.append(f"| {i} | `{op.type}` | `{op.path}` |\n")
    else:
        parts.append("\n_Операций нет._\n")

    # --- проблемы валидации ---
    if plan.parse_error:
        parts.append("\n### ❌ Ошибка парсинга JSON\n")
        parts.append(f"\n```\n{plan.parse_error}\n```\n")
    if plan.problems:
        parts.append("\n### ❌ Проблемы валидации\n")
        for p in plan.problems:
            parts.append(f"- {p}\n")

    # --- diff ---
    if plan.diff:
        parts.append("\n### Diff\n")
        parts.append("\n```diff\n")
        parts.append(plan.diff)
        if not plan.diff.endswith("\n"):
            parts.append("\n")
        parts.append("```\n")

    # --- сырой ответ модели (для аудита) ---
    if plan.raw_json:
        parts.append("\n<details><summary>Сырой ответ модели</summary>\n\n```json\n")
        raw = plan.raw_json
        if len(raw) > 50000:
            raw = raw[:50000] + f"\n... [обрезано, всего {len(plan.raw_json)} символов]"
        parts.append(raw)
        if not raw.endswith("\n"):
            parts.append("\n")
        parts.append("```\n\n</details>\n")

    parts.append("\n---\n")
    return "".join(parts)


def save_report(
    result: ActionResult,
    *,
    output_dir: str,
    per_project_subdir: bool,
    filename_pattern: str,
    save_raw: bool,
    applied_info: dict | None = None,
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
    path.write_text(render_report(result, applied_info=applied_info), encoding="utf-8")

    if save_raw:
        raw_path = path.with_suffix(path.suffix + ".raw.txt")
        raw_path.write_text(result.llm.content, encoding="utf-8")

    return path