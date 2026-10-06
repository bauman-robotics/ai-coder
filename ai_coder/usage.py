from __future__ import annotations

import json
from dataclasses import asdict
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
    iteration: int = 0,               # NEW: 0 = основной запрос, 1..N = fix-итерации
    parent_action: str | None = None, # NEW: имя исходного действия
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

    # глобальный jsonl
    global_jsonl = output_root / "usage.jsonl"
    global_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with global_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # per-project jsonl
    if usage_cfg.per_project:
        proj_jsonl = output_root / project_name / "usage.jsonl"
        proj_jsonl.parent.mkdir(parents=True, exist_ok=True)
        with proj_jsonl.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # пересчёт summary
    _rebuild_summary(global_jsonl, output_root / "usage_summary.json")

def _rebuild_summary(jsonl_path: Path, summary_path: Path) -> None:
    if not jsonl_path.exists():
        return

    total = {
        "requests": 0,
        "prompt_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_cny": 0.0,
        "cost_rub": 0.0,
        "cost_usd": 0.0,
    }
    by_action: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    by_project: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    by_iteration: dict[str, dict] = {}

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue

            def bump(d: dict, key: str, rec: dict) -> None:
                slot = d.setdefault(key, {
                    "requests": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_cny": 0.0,
                    "cost_rub": 0.0,
                })
                slot["requests"] += 1
                slot["prompt_tokens"] += rec.get("prompt_tokens", 0)
                slot["completion_tokens"] += rec.get("completion_tokens", 0)
                slot["total_tokens"] += rec.get("total_tokens", 0)
                slot["cost_cny"] += rec.get("cost_cny", 0.0)
                slot["cost_rub"] += rec.get("cost_rub", 0.0)

            total["requests"] += 1
            for k in (
                "prompt_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
                "completion_tokens", "total_tokens",
            ):
                total[k] += r.get(k, 0)
            for k in ("cost_cny", "cost_rub", "cost_usd"):
                total[k] += r.get(k, 0.0)

            bump(by_action, r.get("action", "?"), r)
            bump(by_model, r.get("model", "?"), r)
            bump(by_project, r.get("project_name", "?"), r)
            bump(by_iteration, str(r.get("iteration", 0)), r)
            day = r.get("ts_utc", "")[:10]
            if day:
                bump(by_day, day, r)

    summary = {
        "total": total,
        "by_action": by_action,
        "by_model": by_model,
        "by_project": by_project,
        "by_day": by_day,
        "by_iteration": by_iteration,
        "updated_at": _now_iso(),
    }
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
