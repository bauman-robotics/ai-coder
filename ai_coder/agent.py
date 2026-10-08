from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from rich.console import Console
from rich.panel import Panel

from .apply import (
    WritePlan,
    apply_plan,
    build_plan,
    check_python_files,
    run_verify_commands,  # NEW
)
from .config import WEB_ASSET_EXTENSIONS, AppConfig, PromptsConfig
from .llm import LLMClient, LLMResponse
from .pricing import calculate_cost, get_rate, is_peak_now
from .prompts import render_prompt
from .scanner import scan_project
from .usage import append_usage

if TYPE_CHECKING:
    from .apply import WritePlan
# ---------- структуры ----------

_console = Console()


@dataclass
class AgentStep:
    n: int
    title: str
    type: str  # "edit" (пока единственный)
    details: str
    target_files: list[str] = field(default_factory=list)


@dataclass
class AgentPlan:
    goal: str
    explanation: str = ""
    steps: list[AgentStep] = field(default_factory=list)
    parse_error: str | None = None
    empty: bool = False
    raw_json: str = ""

    @property
    def valid(self) -> bool:
        return self.parse_error is None and bool(self.steps)


_DIAGNOSTIC_MARKERS = (
    # "диагностика", "продиагностировать"
    "диагност",
    # "проанализировать", "проанализируй", "анализ", "анализировать"
    "проанализир",
    "анализ",
    # "составь список" (буквально)
    "составь список",
    # "проверь", "проверить", "проверка"
    "проверь",
    "проверить",
    "проверк",
    # "изучить", "изучение"
    "изуч",
    # "прочитать", "прочти"
    "прочита",
    "прочти",
    # "опиши", "описать", "описание"
    "опиши",
    "описа",
    # "исследовать", "исследуй"
    "исследу",
)


def _is_diagnostic_step(title: str, details: str) -> bool:
    """
    Определяет, является ли шаг «диагностическим» (по сути read, а не edit).
    Такие шаги пропускаем: они не порождают правок и жгут токены.
    """
    text = (title + " " + details).lower()
    return any(marker in text for marker in _DIAGNOSTIC_MARKERS)


def _extract_target_files(plan: AgentPlan) -> list[str]:
    """
    Извлекает уникальные пути файлов, которые план собирается править.

    Источники:
      - step.target_files (если модель их указала);
      - (в будущем) write_plan.operations — пока плана операций нет,
        ограничиваемся target_files.

    Возвращает отсортированный список без дублей.
    Используется для сужения контекста шагов 2+ (cfg.scanning.only_paths).
    """
    paths: set[str] = set()
    for step in plan.steps:
        for p in step.target_files:
            p = p.strip().lstrip("/")
            if p:
                paths.add(p)
    return sorted(paths)


def _select_step_only_paths(
    *,
    idx: int,
    is_single_step: bool,
    auto_targets: list[str],
    auto_enabled: bool,
) -> list[str] | None:
    """
    Возвращает only_paths для шага или None (полный контекст).

    Одношаговый план: сужаем шаг 1 (idx == 0).
    Многошаговый: шаг 1 — полный, шаги 2+ — сужены.
    """
    if not auto_enabled or not auto_targets:
        return None
    if idx > 0 or is_single_step:
        return auto_targets
    return None


# ---------- парсинг плана ----------


def parse_agent_plan(content: str, goal: str) -> AgentPlan:
    """
    Устойчивый парсинг JSON-плана от модели.
    Снимает markdown-обёртки, извлекает {...}, валидирует структуру.
    """
    plan = AgentPlan(goal=goal, raw_json=content)
    text = content.strip()

    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        plan.parse_error = f"Не удалось распарсить JSON плана: {e}"
        return plan

    if not isinstance(data, dict):
        plan.parse_error = f"Ожидался JSON-объект, получено {type(data).__name__}"
        return plan

    plan.explanation = str(data.get("explanation", "")).strip()

    steps_raw = data.get("steps", [])
    if not isinstance(steps_raw, list):
        plan.parse_error = "Поле 'steps' должно быть списком"
        return plan

    for i, s in enumerate(steps_raw, 1):
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", "")).strip()
        stype = str(s.get("type", "edit")).strip().lower()
        if stype not in ("edit",):
            continue
        if not title:
            continue
        details = str(s.get("details", "")).strip()

        # NEW: пропускаем диагностические шаги (по сути read, не edit)
        if _is_diagnostic_step(title, details):
            continue

        tf = s.get("target_files", [])
        target_files = [str(x) for x in tf] if isinstance(tf, list) else []

        plan.steps.append(
            AgentStep(
                n=i,
                title=title,
                type=stype,
                details=details,
                target_files=target_files,
            )
        )

    if not plan.steps:
        plan.empty = True
    return plan


# ---------- запрос плана у LLM ----------


@dataclass
class PlannerResult:
    plan: AgentPlan
    llm: LLMResponse
    cost_rub: float
    cost_cny: float
    cost_usd: float
    is_peak: bool
    peak_window: str | None
    started_at: datetime
    finished_at: datetime


def run_planner(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    max_steps: int | None = None,
) -> PlannerResult:
    """
    Один запрос к LLM: получаем план шагов для достижения цели.
    """
    model = model or cfg.api.model
    if max_steps is None:
        max_steps = cfg.agent.max_steps

    # 1. сканируем проект
    scan = scan_project(project_root, cfg.scanning, extra_exclude=extra_exclude)

    # 2. промпт планировщика
    prompt_entry = prompts_cfg.get("agent_plan_json")
    system, user = render_prompt(
        prompt_entry,
        depth=depth,
        scan=scan,
        extra={
            "goal": goal,
            "max_steps": str(max_steps),
        },
    )

    # 3. тариф и курсы
    started_at = datetime.now(ZoneInfo("UTC"))
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    # 4. запрос
    client = LLMClient(cfg.api)
    llm_resp = client.chat(
        system=system,
        user=user,
        model=model,
        json_mode=True,
        max_tokens=cfg.agent.step_max_output_tokens,
    )
    finished_at = datetime.now(ZoneInfo("UTC"))

    # 5. парсим
    plan = parse_agent_plan(llm_resp.content, goal)

    # 6. стоимость
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

    # 7. учёт
    output_root = project_root / cfg.output.dir
    append_usage(
        project_root=project_root,
        output_root=output_root,
        action="agent:plan",
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
        iteration=0,
        parent_action="agent",
    )

    return PlannerResult(
        plan=plan,
        llm=llm_resp,
        cost_rub=cost.cost_rub,
        cost_cny=cost.cost_cny,
        cost_usd=cost.cost_usd,
        is_peak=is_peak,
        peak_window=peak_window,
        started_at=started_at,
        finished_at=finished_at,
    )


# ---------- журнал агента ----------


@dataclass
class StepResult:
    step: AgentStep
    llm: LLMResponse
    applied: bool
    applied_count: int
    errors: list[str]
    verify_errors: list[str]
    rolled_back: bool
    cost_rub: float
    cost_cny: float
    cost_usd: float
    from_cache: bool
    write_plan: "WritePlan | None" = None
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class AgentRunResult:
    goal: str
    plan: AgentPlan
    planner_llm: LLMResponse
    planner_cost_rub: float
    planner_cost_cny: float
    planner_cost_usd: float
    steps: list[StepResult]
    started_at: datetime
    finished_at: datetime
    stopped_reason: str = "completed"  # completed | error | max_steps | verify_failed | parse_error
    journal_dir: Path | None = None

    @property
    def total_cost_rub(self) -> float:
        return self.planner_cost_rub + sum(s.cost_rub for s in self.steps)


# ---------- исполнитель одного шага ----------


def _run_agent_step(
    *,
    goal: str,
    step: AgentStep,
    plan: AgentPlan,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    completed_titles: list[str] | None = None,
    apply: bool = False,
    verify: bool = True,
    max_fix_attempts: int = 0,
    web_assets_override: bool | None = None,
    interactive: bool = False,  # NEW
    accept_all_ref: list[bool] | None = None,  # NEW
    only_paths: list[str] | None = None,  # NEW
) -> StepResult:
    """
    Выполняет один шаг: запрос к LLM → парсинг плана → (опц.) применение → верификация.
    Ничего не решает про контроль бюджета/шагов — только делает свою работу.
    """
    from .actions import run_fix_action
    from .apply import rollback as do_rollback

    model = model or cfg.api.model

    # --- пересканируем проект (файлы могли измениться предыдущими шагами) ---
    effective_exclude = list(extra_exclude or [])
    if web_assets_override is False:  # --exclude-web
        effective_exclude += list(WEB_ASSET_EXTENSIONS)

    scan = scan_project(
        project_root,
        cfg.scanning,
        extra_exclude=effective_exclude or None,
        only_paths=only_paths,  # NEW
    )

    # --- промпт шага ---
    prompt_entry = prompts_cfg.get("agent_step_json")
    plan_summary = _render_plan_summary(plan)
    completed = "\n".join(f"- {t}" for t in (completed_titles or [])) or "(нет)"

    system, user = render_prompt(
        prompt_entry,
        depth=depth,
        scan=scan,
        extra={
            "goal": goal,
            "plan_summary": plan_summary,
            "step_index": str(step.n),
            "total_steps": str(len(plan.steps)),
            "step_title": step.title,
            "step_details": step.details or step.title,
            "step_target_files": ", ".join(step.target_files) or "(не указаны)",
            "completed_steps": completed,
        },
    )

    # --- тариф/курсы ---
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    # --- запрос ---
    client = LLMClient(cfg.api)
    llm_resp = client.chat(
        system=system,
        user=user,
        model=model,
        json_mode=True,
        max_tokens=cfg.agent.step_max_output_tokens,
    )

    # --- план операций ---
    write_plan = build_plan(llm_resp.content, project_root, cfg)

    # --- стоимость ---
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

    # --- учёт ---
    output_root = project_root / cfg.output.dir
    append_usage(
        project_root=project_root,
        output_root=output_root,
        action=f"agent:step{step.n}",
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
        iteration=step.n,
        parent_action="agent",
    )

    result = StepResult(
        step=step,
        llm=llm_resp,
        write_plan=write_plan,
        applied=False,
        applied_count=0,
        errors=[],
        verify_errors=[],
        rolled_back=False,
        cost_rub=cost.cost_rub,
        cost_cny=cost.cost_cny,
        cost_usd=cost.cost_usd,
        from_cache=False,
    )

    # --- проверка finish_reason: если модель обрезалась — это важно увидеть
    if llm_resp.finish_reason == "length":
        result.errors.append(
            f"⚠️ Ответ модели обрезан по max_output_tokens "
            f"(completion={llm_resp.completion_tokens}). "
            f"Увеличь step_max_output_tokens или разбей задачу."
        )

    if not apply:
        # Даже без применения — если план пустой, помечаем как skipped
        if write_plan is not None and not write_plan.operations:
            result.skipped = True
            result.skip_reason = "план не содержит операций"
        return result

    # --- interactive: подтверждение перед применением ---
    if apply and interactive:
        accept_all = accept_all_ref is not None and accept_all_ref[0]
        if not accept_all:
            while True:
                _print_step_for_review(step, write_plan, step.n, len(plan.steps))
                answer = _prompt_review()

                if answer == "y":
                    break  # применяем
                if answer == "d":
                    continue  # показываем diff снова
                if answer == "n":
                    result.skipped = True
                    result.skip_reason = "отменено пользователем"
                    result.errors.append("отменено пользователем")
                    return result
                if answer == "s":
                    result.skipped = True
                    result.skip_reason = "пропущено пользователем"
                    return result
                if answer == "a":
                    if accept_all_ref is not None:
                        accept_all_ref[0] = True
                    break  # применяем, дальше без вопросов

    # --- применение ---
    if write_plan is None or not write_plan.valid:
        if write_plan is None:
            result.errors.append("План не сгенерирован (write_plan is None)")
        else:
            if write_plan.parse_error:
                result.errors.append(f"parse_error: {write_plan.parse_error}")
            for p in write_plan.problems:
                result.errors.append(p)
            if not write_plan.parse_error and not write_plan.problems:
                result.errors.append("План невалиден (без деталей)")
        return result
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = (
        project_root / cfg.output.dir / project_root.name / f"agent-backup-{ts}-step{step.n}"
    )

    applied, apply_errors = apply_plan(write_plan, project_root, backup_dir)
    if apply_errors:
        result.errors.extend(apply_errors)
        return result

    if not applied:
        # Нечего применять — модель вернула пустой план
        result.skipped = True
        result.skip_reason = "план не содержит операций"
        return result

    result.applied = True
    result.applied_count = len(applied)

    # --- верификация ---
    if verify and applied:
        verify_errors = check_python_files(applied, project_root)
        # NEW: verify-команды
        if cfg.agent.verify_commands:
            verify_errors += run_verify_commands(
                cfg.agent.verify_commands,
                project_root,
                timeout_sec=cfg.agent.verify_timeout_sec,
            )
        # fix-цикл
        fix_iter = 0
        while verify_errors and fix_iter < max_fix_attempts:
            fix_iter += 1
            try:
                fix_result = run_fix_action(
                    parent_action=f"agent:step{step.n}",
                    iteration=fix_iter,
                    project_root=project_root,
                    cfg=cfg,
                    prompts_cfg=prompts_cfg,
                    errors=verify_errors,
                    previous_plan=write_plan,
                    model=model,
                    depth=depth,
                    extra_exclude=extra_exclude,
                    use_cache=False,
                )
            except Exception as e:
                result.errors.append(f"Ошибка fix-итерации: {e}")
                break

            fix_plan = fix_result.write_plan
            if fix_plan is None or not fix_plan.valid:
                result.errors.append("Fix-план невалиден")
                break

            fix_backup = (
                project_root
                / cfg.output.dir
                / project_root.name
                / f"agent-backup-{ts}-step{step.n}-fix{fix_iter}"
            )
            fix_applied, fix_errors = apply_plan(fix_plan, project_root, fix_backup)
            if fix_errors:
                result.errors.extend(fix_errors)
                break

            verify_errors = check_python_files(fix_applied, project_root)

        result.verify_errors = verify_errors

        if verify_errors:
            # откатываем шаг к состоянию до его применения
            do_rollback(backup_dir, project_root)
            result.rolled_back = True
            result.applied = False

    return result


# ---------- рендер вспомогательных текстов ----------


def _render_plan_summary(plan: AgentPlan) -> str:
    parts: list[str] = []
    if plan.explanation:
        parts.append(plan.explanation)
    for s in plan.steps:
        parts.append(f"{s.n}. {s.title}")
    return "\n".join(parts)


# ---------- главный цикл ----------


def run_agent(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    apply: bool = False,
    verify: bool = True,
    max_fix_attempts: int = 0,
    max_steps: int | None = None,
    max_minutes: int | None = None,
    journal: bool = True,
    preview_only: bool = False,
    web_assets_override: bool | None = None,
    interactive: bool = False,  # NEW
) -> AgentRunResult:
    """
    Полный цикл агента: план → шаги → журнал.
    """
    started_at = datetime.now(ZoneInfo("UTC"))

    if max_steps is None:
        max_steps = cfg.agent.max_steps
    if max_minutes is None:
        max_minutes = cfg.agent.max_minutes

    # --- журнал ---
    journal_dir: Path | None = None
    if journal:
        ts = started_at.strftime("%Y-%m-%dT%H-%M-%S")
        journal_dir = project_root / cfg.output.dir / project_root.name / f"agent-{ts}"
        journal_dir.mkdir(parents=True, exist_ok=True)

    # --- планировщик ---
    planner = run_planner(
        goal=goal,
        project_root=project_root,
        cfg=cfg,
        prompts_cfg=prompts_cfg,
        model=model,
        depth=depth,
        extra_exclude=extra_exclude,
        max_steps=max_steps,
    )

    if journal_dir is not None:
        _save_plan_json(journal_dir, planner.plan, planner.llm)

    result = AgentRunResult(
        goal=goal,
        plan=planner.plan,
        planner_llm=planner.llm,
        planner_cost_rub=planner.cost_rub,
        planner_cost_cny=planner.cost_cny,
        planner_cost_usd=planner.cost_usd,
        steps=[],
        started_at=started_at,
        finished_at=started_at,
        journal_dir=journal_dir,
    )

    if planner.plan.parse_error is not None:
        result.stopped_reason = "parse_error"
        result.finished_at = datetime.now(ZoneInfo("UTC"))
        return result

    if planner.plan.empty:
        result.stopped_reason = "empty_plan"
        result.finished_at = datetime.now(ZoneInfo("UTC"))
        return result

    # NEW: preview-only — не выполняем шаги
    if preview_only:
        result.stopped_reason = "preview_only"
        result.finished_at = datetime.now(ZoneInfo("UTC"))
        if journal_dir is not None:
            _save_agent_report(journal_dir, result, apply=False)
        return result

    # --- NEW: автовыбор only_paths из плана ---
    auto_targets: list[str] = []
    single_step_plan = len(planner.plan.steps) == 1
    if cfg.agent.auto_only_paths:
        auto_targets = _extract_target_files(planner.plan)
        if auto_targets:
            if single_step_plan:
                _console.print(
                    f"[dim]Авто-контекст: одношаговый план — "
                    f"сужен до {len(auto_targets)} файл(ов)[/dim]"
                )
            else:
                _console.print(
                    f"[dim]Авто-контекст: шаги 2+ увидят только "
                    f"{len(auto_targets)} файл(ов) из плана[/dim]"
                )
        else:
            _console.print(
                "[dim yellow]Авто-контекст: планировщик не указал "
                "target_files — шаги пойдут с полным контекстом[/dim yellow]"
            )

    # --- цикл по шагам ---
    completed_titles: list[str] = []
    step_results: list[StepResult] = []
    accept_all_ref: list[bool] = [False]

    for idx, step in enumerate(planner.plan.steps):
        # --- NEW: селективный контекст ---
        # Одношаговый план: шаг 1 сужен до target_files.
        # Многошаговый: шаг 1 видит всё (может «доисследовать»),
        # шаги 2+ сужены до target_files.
        use_only_paths = (
            cfg.agent.auto_only_paths and auto_targets and (idx > 0 or single_step_plan)
        )
        step_only_paths = auto_targets if use_only_paths else None
        # None → берётся cfg.scanning.only_paths

        ...
        step_result = _run_agent_step(
            goal=goal,
            step=step,
            plan=planner.plan,
            project_root=project_root,
            cfg=cfg,
            prompts_cfg=prompts_cfg,
            model=model,
            depth=depth,
            extra_exclude=extra_exclude,
            completed_titles=completed_titles,
            apply=apply,
            verify=verify,
            max_fix_attempts=max_fix_attempts,
            web_assets_override=web_assets_override,
            interactive=interactive,
            accept_all_ref=accept_all_ref,
            only_paths=step_only_paths,  # NEW
        )
        step_results.append(step_result)

        # --- журнал по шагу ---
        if journal_dir is not None:
            _save_step_md(journal_dir, step_result, apply=apply)

        # --- решаем, продолжать ли ---
        if apply:
            if step_result.errors:
                result.stopped_reason = "error"
                break
            if step_result.verify_errors and cfg.agent.stop_on_verify_failure:
                result.stopped_reason = "verify_failed"
                break

        completed_titles.append(step.title)

    result.steps = step_results
    result.finished_at = datetime.now(ZoneInfo("UTC"))

    # --- итоговый отчёт ---
    if journal_dir is not None:
        _save_agent_report(journal_dir, result, apply=apply)

    return result


# ---------- сохранение журнала ----------


def _save_plan_json(journal_dir: Path, plan: AgentPlan, llm: LLMResponse) -> None:
    data = {
        "goal": plan.goal,
        "explanation": plan.explanation,
        "steps": [
            {
                "n": s.n,
                "title": s.title,
                "type": s.type,
                "details": s.details,
                "target_files": s.target_files,
            }
            for s in plan.steps
        ],
        "llm": {
            "model": llm.model,
            "prompt_tokens": llm.prompt_tokens,
            "completion_tokens": llm.completion_tokens,
            "total_tokens": llm.total_tokens,
            "duration_ms": llm.duration_ms,
        },
        "parse_error": plan.parse_error,
    }
    (journal_dir / "plan.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _save_step_md(journal_dir: Path, step_result: StepResult, apply: bool) -> None:
    s = step_result.step
    lines: list[str] = []
    lines.append(f"# Шаг {s.n}: {s.title}\n")
    lines.append(f"- **Тип:** {s.type}")
    lines.append(f"- **Details:** {s.details or '(нет)'}")
    lines.append(f"- **Target files:** {', '.join(s.target_files) or '(нет)'}")
    lines.append(f"- **Модель:** {step_result.llm.model}")
    lines.append(
        f"- **Токены:** prompt {step_result.llm.prompt_tokens} / completion {step_result.llm.completion_tokens}"
    )
    lines.append(f"- **Стоимость:** {step_result.cost_rub:.6f} RUB")
    lines.append(f"- **Применено:** {'да' if step_result.applied else 'нет'}")
    if step_result.applied_count:
        lines.append(f"- **Операций:** {step_result.applied_count}")
    if step_result.errors:
        lines.append("\n## ❌ Ошибки применения\n")
        for e in step_result.errors:
            lines.append(f"- {e}")
    if step_result.verify_errors:
        lines.append("\n## ❌ Ошибки верификации\n")
        for e in step_result.verify_errors:
            lines.append(f"- {e}")
    if step_result.rolled_back:
        lines.append("\n> ⚠️ Шаг откачен.\n")

    plan = step_result.write_plan
    if plan is not None:
        lines.append("\n## Explanation\n")
        lines.append(plan.explanation or "(нет)")
        lines.append(f"\n## Операции ({len(plan.operations)})\n")
        for i, op in enumerate(plan.operations, 1):
            lines.append(f"{i}. `{op.type}` `{op.path}`")
        if plan.diff:
            lines.append("\n## Diff\n")
            lines.append("```diff")
            lines.append(plan.diff)
            if not plan.diff.endswith("\n"):
                lines.append("")
            lines.append("```")

    (journal_dir / f"step-{s.n}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _save_agent_report(journal_dir: Path, result: AgentRunResult, apply: bool) -> None:
    lines: list[str] = []
    lines.append(f"# Agent — {result.plan.goal}\n")
    lines.append(f"- **Начало (UTC):** {result.started_at.isoformat(timespec='seconds')}")
    lines.append(f"- **Конец (UTC):** {result.finished_at.isoformat(timespec='seconds')}")
    duration = (result.finished_at - result.started_at).total_seconds()
    lines.append(f"- **Длительность:** {duration:.1f} c")
    lines.append(f"- **Режим:** {'apply' if apply else 'preview (без применения)'}")
    lines.append(f"- **Причина остановки:** {result.stopped_reason}")
    lines.append(f"- **Стоимость всего:** {result.total_cost_rub:.6f} RUB")
    lines.append(f"- **Стоимость планировщика:** {result.planner_cost_rub:.6f} RUB")

    lines.append("\n## План\n")
    if result.plan.explanation:
        lines.append(result.plan.explanation + "\n")
    for s in result.plan.steps:
        lines.append(f"{s.n}. {s.title}")

    lines.append("\n## Выполненные шаги\n")
    if not result.steps:
        lines.append("(нет)")
    else:
        lines.append("| # | Название | Применено | Ошибок | Стоимость RUB |")
        lines.append("|---:|---|:---:|---:|---:|")
        for sr in result.steps:
            ok = "✅" if sr.applied else "—"
            lines.append(
                f"| {sr.step.n} | {sr.step.title} | {ok} | {len(sr.errors) + len(sr.verify_errors)} | {sr.cost_rub:.6f} |"
            )

    (journal_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_step_for_review(step: AgentStep, plan, index: int, total: int) -> None:
    """Показывает шаг и diff перед подтверждением."""
    _console.print()
    _console.print(
        Panel.fit(
            f"[bold]Шаг {index}/{total}:[/bold] {step.title}\n"
            f"Операций: [cyan]{len(plan.operations)}[/cyan]",
            title="Подтверждение",
        )
    )

    if plan.explanation:
        _console.print(f"\n[dim]{plan.explanation}[/dim]\n")

    # Список операций
    files_table_lines: list[str] = []
    for i, op in enumerate(plan.operations, 1):
        files_table_lines.append(f"  {i}. {op.type} {op.path}")
    _console.print("\n".join(files_table_lines))

    # Diff
    if plan.diff:
        _console.print("\n[bold]Diff:[/bold]\n")
        _console.print("```diff", style="dim")
        _console.print(plan.diff, style="dim")
        _console.print("```", style="dim")


def _prompt_review() -> str:
    """
    Спрашивает y/n/a/s/d. Возвращает одну из букв.
    Цикл: если ответ неизвестен — переспрашиваем.
    """
    while True:
        try:
            answer = (
                input("\nПрименить? yes(y) / no(n) / all(a) / skip(s) / diff(d): ").strip().lower()
            )
        except (EOFError, KeyboardInterrupt):
            print()
            return "n"
        if answer in ("y", "n", "a", "s", "d"):
            return answer
        print("Не понял. Ответь: y / n / a / s / d")
