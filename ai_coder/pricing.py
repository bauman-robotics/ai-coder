from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from .config import ApiConfig, CurrencyConfig, ModelPricing


# ---------- peak / off-peak ----------

def is_peak_now(schedule) -> tuple[bool, str | None]:
    """
    Возвращает (is_peak, name_of_window).
    schedule — ApiConfig.peak_schedule.
    Время проверяется в schedule.timezone (UTC по конфигу).
    """
    tz = ZoneInfo(schedule.timezone)
    now = datetime.now(tz)

    if schedule.weekdays_only and now.weekday() >= 5:
        return False, None

    current = now.time()
    for w in schedule.windows:
        sh, sm = map(int, w.start.split(":"))
        eh, em = map(int, w.end.split(":"))
        start = dtime(sh, sm)
        end = dtime(eh, em)
        if start <= current < end:
            return True, f"{w.start}-{w.end} {schedule.timezone}"
    return False, None


# ---------- курсы валют ----------

@dataclass
class Rate:
    value: float
    source: str  # cbr | cache | fallback
    fetched_at: float


def _cache_path(root: Path) -> Path:
    return root / ".ai-out" / "rates_cache.json"


def _load_cache(root: Path) -> dict:
    p = _cache_path(root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(root: Path, data: dict) -> None:
    p = _cache_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_cbr_rates() -> dict[str, float]:
    """
    Забирает курсы с cbr-xml-daily.ru.
    Возвращает {'CNY': <rub per 1 cny>, 'USD': <rub per 1 usd>}.
    """
    url = "https://www.cbr-xml-daily.ru/daily_json.js"
    r = httpx.get(url, timeout=10)
    r.raise_for_status()
    data = r.json()
    vals = data.get("Valute", {})
    out: dict[str, float] = {}
    if "CNY" in vals:
        # у ЦБ котировка за N единиц (обычно 1, но бывает 10)
        cny = vals["CNY"]
        out["CNY"] = cny["Value"] / cny.get("Nominal", 1)
    if "USD" in vals:
        usd = vals["USD"]
        out["USD"] = usd["Value"] / usd.get("Nominal", 1)
    return out


def get_rate(
    root: Path,
    currency_cfg,
    *,
    key: str,  # 'CNY' или 'USD'
) -> Rate:
    """
    Возвращает курс к рублю с учётом кэша и фолбэка.
    currency_cfg — CurrencyPair из конфига.
    """
    cache = _load_cache(root)
    now = time.time()
    cache_hours = currency_cfg.cache_hours
    cache_entry = cache.get(key)

    if cache_entry and (now - cache_entry.get("fetched_at", 0)) < cache_hours * 3600:
        return Rate(cache_entry["value"], "cache", cache_entry["fetched_at"])

    if currency_cfg.fetch_online:
        try:
            rates = _fetch_cbr_rates()
            if key in rates:
                value = rates[key]
                cache[key] = {"value": value, "fetched_at": now}
                _save_cache(root, cache)
                return Rate(value, "cbr", now)
        except Exception:
            pass

    # фолбэк из конфига
    fallback = currency_cfg.fallback
    return Rate(fallback, "fallback", now)


# ---------- расчёт стоимости ----------

@dataclass
class CostBreakdown:
    is_peak: bool
    peak_window: str | None
    prompt_hit_tokens: int
    prompt_miss_tokens: int
    completion_tokens: int
    cost_cny: float
    cost_rub: float
    cost_usd: float
    cny_to_rub_rate: float
    usd_to_rub_rate: float
    rate_source: str


def calculate_cost(
    *,
    pricing: ModelPricing,
    is_peak: bool,
    peak_window: str | None,
    prompt_hit_tokens: int,
    prompt_miss_tokens: int,
    completion_tokens: int,
    cny_to_rub: Rate,
    usd_to_rub: Rate,
) -> CostBreakdown:
    price_hit = pricing.cache_hit_per_1m_cny.get(is_peak)
    price_miss = pricing.cache_miss_per_1m_cny.get(is_peak)
    price_out = pricing.output_per_1m_cny.get(is_peak)

    cost_cny = (
        prompt_hit_tokens / 1_000_000 * price_hit
        + prompt_miss_tokens / 1_000_000 * price_miss
        + completion_tokens / 1_000_000 * price_out
    )
    cost_rub = cost_cny * cny_to_rub.value
    cost_usd = cost_rub / usd_to_rub.value if usd_to_rub.value else 0.0

    return CostBreakdown(
        is_peak=is_peak,
        peak_window=peak_window,
        prompt_hit_tokens=prompt_hit_tokens,
        prompt_miss_tokens=prompt_miss_tokens,
        completion_tokens=completion_tokens,
        cost_cny=cost_cny,
        cost_rub=cost_rub,
        cost_usd=cost_usd,
        cny_to_rub_rate=cny_to_rub.value,
        usd_to_rub_rate=usd_to_rub.value,
        rate_source=f"{cny_to_rub.source}/{usd_to_rub.source}",
    )