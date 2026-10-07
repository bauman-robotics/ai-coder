from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import cache as cache_mod
from .apply import WritePlan, build_plan
from .config import WEB_ASSET_EXTENSIONS, AppConfig, PromptsConfig
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
    write_plan: WritePlan | None = None
    from_cache: bool = False


def run_action(
    *,
    action_name: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    use_cache: bool = True,
    refresh: bool = False,
    web_assets_override: bool | None = None,
) -> ActionResult:
    if depth not in VALID_DEPTHS:
        raise ValueError(f"depth должен быть один из {sorted(VALID_DEPTHS)}, получено '{depth}'")

    action = cfg.actions.get(action_name)
    if action is None:
        raise KeyError(f"Действие '{action_name}' не найдено в конфиге")
    if not action.enabled:
        raise RuntimeError(f"Действие '{action_name}' отключено (enabled: false)")

    model = model or cfg.api.model

    # 1. скан проекта
    # --exclude-web / --include-web переопределяют авто-настройку действия
    if web_assets_override is True:
        exclude_web = False
    elif web_assets_override is False:
        exclude_web = True
    else:
        exclude_web = action.exclude_web_assets

    effective_exclude = list(extra_exclude or [])
    if exclude_web:
        effective_exclude += list(WEB_ASSET_EXTENSIONS)

    scan = scan_project(
        project_root,
        cfg.scanning,
        extra_exclude=effective_exclude or None,
    )

    # 2. шаблон промпта (без подстановки {{files}}, {{tree}})
    prompt_entry = prompts_cfg.get(action.prompt)

    # 3. кэш
    cache_enabled = use_cache and cfg.output.use_cache
    hash_hex: str | None = None
    if cache_enabled:
        hash_hex = cache_mod.compute_hash(
            scan=scan,
            prompt_system=prompt_entry.system,
            prompt_user=prompt_entry.user,
            model=model,
            depth=depth,
        )
        if not refresh:
            cached = cache_mod.from_cache(
                project_root=project_root,
                output_dir=cfg.output.dir,
                cache_dir_name=cfg.output.cache_dir_name,
                hash_hex=hash_hex,
                scan=scan,
            )
            if cached is not None:
                llm_resp, cached_plan = cached

                # Перепроверяем план: blacklist и содержимое файлов могли измениться
                if cached_plan is not None:
                    from .apply import render_diff, validate_operations

                    cached_plan.problems = []
                    validate_operations(cached_plan, project_root, cfg)
                    cached_plan.diff = render_diff(cached_plan, project_root)

                    if not cached_plan.valid:
                        # кэш устарел — идём в API заново
                        cached = None
                    else:
                        started_at = datetime.now(ZoneInfo("UTC"))
                        return ActionResult(
                            action=action_name,
                            model=model,
                            depth=depth,
                            scan=scan,
                            llm=llm_resp,
                            cost_rub=0.0,
                            cost_cny=0.0,
                            cost_usd=0.0,
                            is_peak=False,
                            peak_window=None,
                            started_at=started_at,
                            finished_at=started_at,
                            write_plan=cached_plan,
                            from_cache=True,
                        )
                else:
                    started_at = datetime.now(ZoneInfo("UTC"))
                    return ActionResult(
                        action=action_name,
                        model=model,
                        depth=depth,
                        scan=scan,
                        llm=llm_resp,
                        cost_rub=0.0,
                        cost_cny=0.0,
                        cost_usd=0.0,
                        is_peak=False,
                        peak_window=None,
                        started_at=started_at,
                        finished_at=started_at,
                        write_plan=None,
                        from_cache=True,
                    )
    # 4. рендер и запрос к LLM (как было)
    system, user = render_prompt(prompt_entry, depth=depth, scan=scan)
    started_at = datetime.now(ZoneInfo("UTC"))
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    client = LLMClient(cfg.api)
    json_mode = action.mode == "write"
    llm_resp = client.chat(
        system=system,
        user=user,
        model=model,
        json_mode=json_mode,
        max_tokens=action.max_output_tokens,
        temperature=action.temperature,
    )
    finished_at = datetime.now(ZoneInfo("UTC"))

    write_plan: WritePlan | None = None
    if action.mode == "write":
        write_plan = build_plan(llm_resp.content, project_root, cfg)

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

    # сохраняем в кэш
    if cache_enabled and hash_hex:
        cache_mod.save(
            project_root=project_root,
            output_dir=cfg.output.dir,
            cache_dir_name=cfg.output.cache_dir_name,
            hash_hex=hash_hex,
            action=action_name,
            model=model,
            depth=depth,
            prompt_name=action.prompt,
            llm=llm_resp,
            write_plan=write_plan,
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
        write_plan=write_plan,
        from_cache=False,
    )


def run_fix_action(
    *,
    parent_action: str,
    iteration: int,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    errors: list[str],
    previous_plan: WritePlan,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    use_cache: bool = True,
) -> ActionResult:
    """
    Одна итерация авто-исправления: отправляет модели список ошибок
    от py_compile + предыдущий план + текущее содержимое проекта.
    Возвращает ActionResult с новым WritePlan.
    """
    model = model or cfg.api.model

    # 1. пересканируем проект — файлы изменились после apply
    scan = scan_project(project_root, cfg.scanning, extra_exclude=extra_exclude)

    # 2. промпт fix
    prompt_entry = prompts_cfg.get(cfg.fix.prompt)

    # 3. текстовые блоки для подстановки
    errors_text = "\n".join(f"- {e}" for e in errors) or "- (нет)"
    previous_plan_text = _render_previous_plan(previous_plan)

    # 4. рендер
    system, user = render_prompt(
        prompt_entry,
        depth=depth,
        scan=scan,
        extra={
            "errors": errors_text,
            "previous_plan": previous_plan_text,
        },
    )

    # 5. кэш (по хэшу: файлы + шаблон + errors + previous_plan + модель + depth)
    cache_enabled = use_cache and cfg.output.use_cache
    hash_hex: str | None = None
    if cache_enabled:
        hash_hex = cache_mod.compute_hash(
            scan=scan,
            prompt_system=prompt_entry.system
            + "\nERRORS:\n"
            + errors_text
            + "\nPREV:\n"
            + previous_plan_text,
            prompt_user=prompt_entry.user,
            model=model,
            depth=depth,
        )
        cached = cache_mod.from_cache(
            project_root=project_root,
            output_dir=cfg.output.dir,
            cache_dir_name=cfg.output.cache_dir_name,
            hash_hex=hash_hex,
            scan=scan,
        )
        if cached is not None:
            llm_resp, cached_plan = cached

            # Перепроверяем fix-план: blacklist и содержимое файлов могли измениться
            if cached_plan is not None:
                from .apply import render_diff, validate_operations

                cached_plan.problems = []
                validate_operations(cached_plan, project_root, cfg)
                cached_plan.diff = render_diff(cached_plan, project_root)

                if not cached_plan.valid:
                    # кэш устарел — идём в API заново
                    cached = None
                else:
                    now = datetime.now(ZoneInfo("UTC"))
                    return ActionResult(
                        action=f"{parent_action}:fix{iteration}",
                        model=model,
                        depth=depth,
                        scan=scan,
                        llm=llm_resp,
                        cost_rub=0.0,
                        cost_cny=0.0,
                        cost_usd=0.0,
                        is_peak=False,
                        peak_window=None,
                        started_at=now,
                        finished_at=now,
                        write_plan=cached_plan,
                        from_cache=True,
                    )
            else:
                now = datetime.now(ZoneInfo("UTC"))
                return ActionResult(
                    action=f"{parent_action}:fix{iteration}",
                    model=model,
                    depth=depth,
                    scan=scan,
                    llm=llm_resp,
                    cost_rub=0.0,
                    cost_cny=0.0,
                    cost_usd=0.0,
                    is_peak=False,
                    peak_window=None,
                    started_at=now,
                    finished_at=now,
                    write_plan=None,
                    from_cache=True,
                )

    # 6. запрос
    started_at = datetime.now(ZoneInfo("UTC"))
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    client = LLMClient(cfg.api)
    llm_resp = client.chat(system=system, user=user, model=model, json_mode=True)
    finished_at = datetime.now(ZoneInfo("UTC"))

    write_plan = build_plan(llm_resp.content, project_root, cfg)

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

    # 7. usage с iteration/parent_action
    output_root = project_root / cfg.output.dir
    append_usage(
        project_root=project_root,
        output_root=output_root,
        action=f"{parent_action}:fix{iteration}",
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
        iteration=iteration,
        parent_action=parent_action,
    )

    if cache_enabled and hash_hex:
        cache_mod.save(
            project_root=project_root,
            output_dir=cfg.output.dir,
            cache_dir_name=cfg.output.cache_dir_name,
            hash_hex=hash_hex,
            action=f"{parent_action}:fix{iteration}",
            model=model,
            depth=depth,
            prompt_name=cfg.fix.prompt,
            llm=llm_resp,
            write_plan=write_plan,
        )

    return ActionResult(
        action=f"{parent_action}:fix{iteration}",
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
        write_plan=write_plan,
        from_cache=False,
    )


def _render_previous_plan(plan: WritePlan) -> str:
    """
    Краткое текстовое представление предыдущего плана для промпта.
    Включает explanation + список операций, без diff (он избыточен и дорог).
    """
    parts: list[str] = []
    if plan.explanation:
        parts.append(f"Explanation: {plan.explanation}")
    parts.append(f"Operations ({len(plan.operations)}):")
    for i, op in enumerate(plan.operations, 1):
        parts.append(f"  {i}. {op.type} {op.path}")
    return "\n".join(parts) or "(пусто)"
