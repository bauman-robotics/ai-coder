from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import AppConfig, PromptsConfig
from .llm import LLMClient, LLMResponse
from .pricing import calculate_cost, get_rate, is_peak_now
from .prompts import render_prompt
from .scanner import ScanResult, scan_project
from .usage import append_usage


VALID_DEPTHS = {"shallow", "normal", "deep"}


@dataclass
class ActionResult:
    action: str
    model: str
    depth: str
    scan: ScanResult
    llm: LLMResponse
    cost_rub: float
    cost_cny: float
    cost_usd: float
    is_peak: bool
    peak_window: str | None
    started_at: datetime
    finished_at: datetime


def run_action(
    *,
    action_name: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
) -> ActionResult:
    if depth not in VALID_DEPTHS:
        raise ValueError(f"depth должен быть один из {sorted(VALID_DEPTHS)}, получено '{depth}'")

    action = cfg.actions.get(action_name)
    if action is None:
        raise KeyError(f"Действие '{action_name}' не найдено в конфиге")
    if not action.enabled:
        raise RuntimeError(f"Действие '{action_name}' отключено (enabled: false)")

    model = model or cfg.api.model

    # 1. сканируем проект
    scan = scan_project(project_root, cfg.scanning, extra_exclude=extra_exclude)

    # 2. рендерим промпт
    prompt_entry = prompts_cfg.get(action.prompt)
    system, user = render_prompt(prompt_entry, depth=depth, scan=scan)

    # 3. определяем peak/off-peak и курсы — ДО запроса, чтобы зафиксировать время
    started_at = datetime.now(ZoneInfo("UTC"))
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)

    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    # 4. запрос к LLM
    client = LLMClient(cfg.api)
    llm_resp = client.chat(system=system, user=user, model=model)

    finished_at = datetime.now(ZoneInfo("UTC"))

    # 5. стоимость
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

    # 6. учёт
    output_root = project_root / cfg.output.dir
    append_usage(
        project_root=project_root,
        output_root=output_root,
        action=action_name,
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
    )

    return ActionResult(
        action=action_name,
        model=model,
        depth=depth,
        scan=scan,
        llm=llm_resp,
        cost_rub=cost.cost_rub,
        cost_cny=cost.cost_cny,
        cost_usd=cost.cost_usd,
        is_peak=is_peak,
        peak_window=peak_window,
        started_at=started_at,
        finished_at=finished_at,
    )