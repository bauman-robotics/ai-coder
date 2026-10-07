from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .pricing import CostBreakdown


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append_usage(
    *,
    project_root: Path,
    output_root: Path,
    action: str,
    project_name: str,
    model: str,
    depth: str,
    files_count: int,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
    cost: CostBreakdown,
    duration_ms: int,
    status: str,
    usage_cfg,
    iteration: int = 0,  # NEW: 0 = основной запрос, 1..N = fix-итерации
    parent_action: str | None = None,  # NEW: имя исходного действия
) -> None:
    """
    Пишет строку в usage.jsonl (глобальный и, если настроено, по проекту).
    """
    ts_utc = _now_iso()
    tz_msk = None
    try:
        from zoneinfo import ZoneInfo

        tz_msk = datetime.now(ZoneInfo("Europe/Moscow")).isoformat(timespec="seconds")
    except Exception:
        pass

    record = {
        "ts_utc": ts_utc,
        "ts_msk": tz_msk,
        "action": action,
        "project": str(project_root),
        "project_name": project_name,
        "model": model,
        "depth": depth,
        "files_count": files_count,
        "prompt_tokens": prompt_tokens,
        "prompt_cache_hit_tokens": cost.prompt_hit_tokens,
        "prompt_cache_miss_tokens": cost.prompt_miss_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "is_peak": cost.is_peak,
        "peak_window": cost.peak_window,
        "cost_cny": round(cost.cost_cny, 6),
        "cost_rub": round(cost.cost_rub, 6),
        "cost_usd": round(cost.cost_usd, 6),
        "cny_to_rub_rate": cost.cny_to_rub_rate,
        "usd_to_rub_rate": cost.usd_to_rub_rate,
        "rate_source": cost.rate_source,
        "duration_ms": duration_ms,
        "status": status,
        "iteration": iteration,
        "parent_action": parent_action or action,
    }

    # глобальный jsonl — путь из конфига (относительно project_root)
    global_jsonl = project_root / usage_cfg.jsonl
    global_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with global_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # per-project jsonl — производная структура, рядом с отчётами проекта
    if usage_cfg.per_project:
        proj_jsonl = output_root / project_name / "usage.jsonl"
        proj_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with proj_jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # summary не пересчитывается при записи:
    # O(N^2) при каждом запросе; сводка строится командой `usage` на лету
    # из JSONL (review 1.3).
