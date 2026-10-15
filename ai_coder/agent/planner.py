"""Планировщик агента ai_coder.

Парсеры планов, декомпозиции, replan, split-goals.
Вынесено из agent/_legacy.py (10.65.3a split-file).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from rich.console import Console

from ..config import AppConfig, PromptsConfig
from ..llm import LLMClient
from ..pricing import Rate, calculate_cost, get_rate, is_peak_now
from ..prompts import render_prompt
from ..scanner import (
    ScanResult,
    render_metadata_block,
    scan_project,
    scan_project_metadata,
)
from ..usage import append_usage
from .models import (
    AgentPlan,
    AgentStep,
    DecomposeResult,
    PlannerPhase1Result,
    PlannerResult,
    ReplanResult,
    SplitGoalsResult,
    SplitIssue,
    Subtask,
)

# Локальная Rich-консоль. Дублирует _console из _legacy, но избегает
# циклического импорта planner <-> _legacy.
_console = Console()


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


_CYR_TO_LAT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


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


def _slug_for_issue(text: str, max_len: int = 40) -> str:
    """Slug для имени issue-файла. Транслитерирует кириллицу."""

    # транслит посимвольно (нижний регистр)
    out_chars: list[str] = []
    for ch in text.lower():
        if ch in _CYR_TO_LAT:
            out_chars.append(_CYR_TO_LAT[ch])
        elif ch.isascii() and (ch.isalnum() or ch in "-_"):
            out_chars.append(ch)
        else:
            out_chars.append("-")
    s = "".join(out_chars)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return "task"
    return s[:max_len].rstrip("-")


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
        if stype not in ("edit", "read"):
            continue
        if not title:
            continue
        details = str(s.get("details", "")).strip()

        # 10.32: если LLM сказал "edit", но текст — read-маркеры,
        # переклассифицируем в "read". Явный "read" не трогаем.
        if stype == "edit" and _is_diagnostic_step(title, details):
            stype = "read"

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


def _parse_phase1_response(content: str) -> tuple[list[str], str | None]:
    """
    Парсит ответ phase1: ожидает {"explanation": ..., "target_files": [...]}.

    Возвращает (target_files, parse_error).
    Если парсинг не удался — target_files=[], parse_error="...".
    """
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
        return [], f"phase1 JSON parse error: {e}"

    if not isinstance(data, dict):
        return [], f"phase1: ожидался dict, получено {type(data).__name__}"

    tf = data.get("target_files", [])
    if not isinstance(tf, list):
        return [], "phase1: 'target_files' должен быть списком"

    paths: list[str] = []
    for p in tf:
        p_str = str(p).strip().lstrip("/")
        if p_str:
            paths.append(p_str)

    return sorted(set(paths)), None


def parse_decompose_response(content: str) -> DecomposeResult:
    """
    Парсит ответ планировщика-декомпозитора.

    Ожидает JSON:
      {"explanation": "...",
       "subtasks": [{"n": 1, "goal": "...", "files": ["..."]}, ...]}

    Устойчив к markdown-обёртке, мусору, двум JSON подряд.
    """
    result = DecomposeResult(raw_json=content)
    text = content.strip()

    # markdown-обёртка
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # вырезать первый {...}
    if not text.startswith("{"):
        start = text.find("{")
        if start == -1:
            result.parse_error = "no '{' found"
            return result
        text = text[start:]

    # raw_decode — берём первый JSON-объект
    decoder = json.JSONDecoder()
    try:
        data, _ = decoder.raw_decode(text)
    except json.JSONDecodeError as e:
        result.parse_error = f"JSON parse error: {e}"
        return result

    if not isinstance(data, dict):
        result.parse_error = f"expected dict, got {type(data).__name__}"
        return result

    result.explanation = str(data.get("explanation", "")).strip()

    subtasks_raw = data.get("subtasks", [])
    if not isinstance(subtasks_raw, list):
        result.parse_error = "'subtasks' must be a list"
        return result

    for i, s in enumerate(subtasks_raw, 1):
        if not isinstance(s, dict):
            continue
        goal = str(s.get("goal", "")).strip()
        if not goal:
            continue
        files_raw = s.get("files", [])
        files = [str(f) for f in files_raw] if isinstance(files_raw, list) else []
        result.subtasks.append(Subtask(n=i, goal=goal, files=files))

    if not result.subtasks and result.parse_error is None:
        result.parse_error = "empty subtasks"

    return result


def parse_split_goals_response(content: str) -> SplitGoalsResult:
    """
    Парсит ответ планировщика --split-goals.

    Ожидает JSON:
      {"issues": [{"title": "...", "goal": "..."}, ...]}

    Устойчив к markdown-обёртке, мусору.
    """
    result = SplitGoalsResult(raw_json=content)
    text = content.strip()

    # markdown-обёртка
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # вырезать первый {...}
    if not text.startswith("{"):
        start = text.find("{")
        if start == -1:
            result.parse_error = "no '{' found"
            return result
        text = text[start:]

    decoder = json.JSONDecoder()
    try:
        data, _ = decoder.raw_decode(text)
    except json.JSONDecodeError as e:
        result.parse_error = f"JSON parse error: {e}"
        return result

    if not isinstance(data, dict):
        result.parse_error = f"expected dict, got {type(data).__name__}"
        return result

    issues_raw = data.get("issues", [])
    if not isinstance(issues_raw, list):
        result.parse_error = "'issues' must be a list"
        return result

    for i, s in enumerate(issues_raw, 1):
        if not isinstance(s, dict):
            continue
        title = str(s.get("title", "")).strip()
        goal = str(s.get("goal", "")).strip()
        if not goal:
            continue
        if not title:
            title = goal[:40]
        result.issues.append(SplitIssue(n=i, title=title, goal=goal))

    if not result.issues and result.parse_error is None:
        result.parse_error = "empty issues"

    return result


def parse_replan_response(content: str) -> ReplanResult:
    """
    Парсит ответ планировщика-replan.

    Ожидает JSON:
      {"action": "skip" | "modify" | "stop",
       "explanation": "...",
       "new_subtasks": [{"n": 1, "goal": "...", "files": ["..."]}, ...]}

    При ошибке — action="stop" + parse_error.
    """
    result = ReplanResult(raw_json=content)
    text = content.strip()

    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    if not text.startswith("{"):
        start = text.find("{")
        if start == -1:
            result.parse_error = "no '{' found"
            return result
        text = text[start:]

    decoder = json.JSONDecoder()
    try:
        data, _ = decoder.raw_decode(text)
    except json.JSONDecodeError as e:
        result.parse_error = f"JSON parse error: {e}"
        return result

    if not isinstance(data, dict):
        result.parse_error = f"expected dict, got {type(data).__name__}"
        return result

    action = str(data.get("action", "")).strip().lower()
    if action not in ("skip", "modify", "stop"):
        result.parse_error = f"invalid action: {action!r}"
        return result

    result.action = action
    result.explanation = str(data.get("explanation", "")).strip()

    if action == "modify":
        subtasks_raw = data.get("new_subtasks", [])
        if not isinstance(subtasks_raw, list):
            result.parse_error = "'new_subtasks' must be a list"
            return result
        for i, s in enumerate(subtasks_raw, 1):
            if not isinstance(s, dict):
                continue
            goal = str(s.get("goal", "")).strip()
            if not goal:
                continue
            files_raw = s.get("files", [])
            files = [str(f) for f in files_raw] if isinstance(files_raw, list) else []
            result.new_subtasks.append(Subtask(n=i, goal=goal, files=files))

        if not result.new_subtasks:
            result.parse_error = "action=modify but new_subtasks empty"

    return result


def _estimate_next_cost_rub(
    cfg: AppConfig,
    model: str,
    system: str,
    user: str,
    cny_to_rub: Rate,
    *,
    expected_completion_tokens: int = 500,
    last_tool: str | None = None,
) -> float:
    """
    Грубая консервативная оценка стоимости следующего запроса.

    Считает prompt_tokens как len(text)//3 (см. scanner._estimate_tokens),
    берёт ХУДШУЮ ставку (peak, cache miss) — чтобы не превысить лимит.

    expected_completion_tokens — сколько примерно вернёт модель:
      - finish JSON: ~100–500;
      - decompose JSON (список подзадач): ~500–2000.
    last_tool — инструмент предыдущей итерации; если задан,
      пересчитывает ожидаемое число completion-токенов.
    """
    # Локальный импорт, чтобы не тянуть scanner на верхнем уровне.
    from ..scanner import _estimate_tokens

    prompt_tokens = _estimate_tokens(system) + _estimate_tokens(user)
    pricing = cfg.api.pricing_for(model)
    price_miss = max(
        pricing.cache_miss_per_1m_cny.off_peak,
        pricing.cache_miss_per_1m_cny.peak,
    )
    price_out = max(
        pricing.output_per_1m_cny.off_peak,
        pricing.output_per_1m_cny.peak,
    )

    completion_tokens = expected_completion_tokens
    if last_tool is not None:
        if last_tool in ("read_file", "read_symbol", "list_files"):
            completion_tokens = 500
        elif last_tool == "edit_file":
            completion_tokens = 2000
        elif last_tool == "write_file":
            completion_tokens = 8000
        elif last_tool == "run_shell":
            completion_tokens = 300
        else:
            completion_tokens = 500

    cost_cny = prompt_tokens / 1_000_000 * price_miss + completion_tokens / 1_000_000 * price_out
    return cost_cny * cny_to_rub.value


def _phase1_cache_key(goal: str, tree: str, model: str) -> str:
    """Хэш phase1: goal + tree + model. SHA256, первые 32 hex."""
    h = hashlib.sha256()
    h.update(b"ai-coder-phase1-v1\n")
    h.update(f"model:{model}\n".encode("utf-8"))
    h.update(f"goal:{goal}\n".encode("utf-8"))
    h.update(b"---TREE---\n")
    h.update(tree.encode("utf-8"))
    return h.hexdigest()[:32]


def _phase1_cache_dir(project_root: Path, cfg: AppConfig) -> Path:
    """Папка для кэша phase1 — та же, что у apply.py."""
    return project_root / cfg.output.dir / project_root.name / cfg.output.cache_dir_name


def _phase1_from_cache(cache_dir: Path, key: str) -> list[str] | None:
    """Читает target_files из кэша phase1. None — если нет/битый."""
    p = cache_dir / f"phase1-{key}.json"
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    tf = data.get("target_files", [])
    if not isinstance(tf, list):
        return None
    return [str(x) for x in tf if str(x).strip()]


def _phase1_save_cache(cache_dir: Path, key: str, target_files: list[str]) -> None:
    """Сохраняет target_files в кэш phase1."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        p = cache_dir / f"phase1-{key}.json"
        p.write_text(
            json.dumps(
                {
                    "target_files": target_files,
                    "ts": datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


def run_planner_phase1(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    use_cache: bool = True,  # NEW
    refresh: bool = False,  # NEW
) -> PlannerPhase1Result:
    """
    Первый проход планировщика: видит только дерево + метаданные,
    определяет target_files для phase2.

    Кэш: если use_cache и не refresh — сначала проверяем кэш по
    хэшу (goal + tree + model). При попадании — LLM не вызывается.
    """
    model = model or cfg.api.model

    # 1. metadata-scan (без содержимого)
    scan_meta = scan_project_metadata(
        project_root,
        cfg.scanning,
        extra_exclude=extra_exclude,
    )

    # --- NEW: кэш phase1 ---
    cache_dir = _phase1_cache_dir(project_root, cfg)
    cache_key: str | None = None
    cache_enabled = use_cache and cfg.output.use_cache

    if cache_enabled:
        cache_key = _phase1_cache_key(goal, scan_meta.tree, model)
        if not refresh:
            cached = _phase1_from_cache(cache_dir, cache_key)
            if cached is not None:
                _console.print(f"[dim]Фаза 1: из кэша ({len(cached)} файл(ов))[/dim]")
                return PlannerPhase1Result(
                    target_files=cached,
                    llm=None,
                    cost_rub=0.0,
                    cost_cny=0.0,
                    cost_usd=0.0,
                    parse_error=None,
                    from_cache=True,
                )

    # 2. промпт — scan обязателен как заглушка, {{tree}} переопределяется
    #    через extra (render_prompt: extra перезаписывает базовые values)
    prompt_entry = prompts_cfg.get("agent_plan_json_phase1")
    metadata_block = render_metadata_block(scan_meta)
    empty_scan = ScanResult(root=project_root)
    system, user = render_prompt(
        prompt_entry,
        depth=depth,
        scan=empty_scan,
        extra={
            "goal": goal,
            "tree": scan_meta.tree,
            "metadata": metadata_block,
        },
    )

    # 3. тариф и курсы
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
        max_tokens=cfg.agent.phase1_max_output_tokens,
    )

    # 5. парсим
    target_files, parse_error = _parse_phase1_response(llm_resp.content)

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
        action="agent:plan1",
        project_name=project_root.name,
        model=model,
        depth=depth,
        files_count=scan_meta.total_files,
        prompt_tokens=llm_resp.prompt_tokens,
        completion_tokens=llm_resp.completion_tokens,
        total_tokens=llm_resp.total_tokens,
        cost=cost,
        duration_ms=llm_resp.duration_ms,
        status="ok" if parse_error is None else "parse_error",
        usage_cfg=cfg.usage,
        iteration=0,
        parent_action="agent",
    )

    # --- NEW: сохраняем в кэш при успехе ---
    if cache_enabled and cache_key is not None and parse_error is None:
        _phase1_save_cache(cache_dir, cache_key, target_files)

    return PlannerPhase1Result(
        target_files=target_files,
        llm=llm_resp,
        cost_rub=cost.cost_rub,
        cost_cny=cost.cost_cny,
        cost_usd=cost.cost_usd,
        parse_error=parse_error,
        from_cache=False,
    )


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
    only_paths: list[str] | None = None,  # NEW
) -> PlannerResult:
    """
    Один запрос к LLM: получаем план шагов для достижения цели.
    """
    model = model or cfg.api.model
    if max_steps is None:
        max_steps = cfg.agent.max_steps

    # 1. сканируем проект (с учётом only_paths от phase1)
    scan = scan_project(
        project_root,
        cfg.scanning,
        extra_exclude=extra_exclude,
        only_paths=only_paths,  # NEW
    )

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


def run_planner_decompose(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
    depth: str = "normal",
    extra_exclude: list[str] | None = None,
    max_cost_rub: float | None = None,
) -> DecomposeResult:
    """
    Планировщик-декомпозитор: одна задача → список подзадач.
    """
    model = model or cfg.api.model

    # metadata-scan (дерево + метаданные)
    scan_meta = scan_project_metadata(project_root, cfg.scanning, extra_exclude=extra_exclude)

    # промпт
    prompt_entry = prompts_cfg.get("agent_decompose_json")
    metadata_block = render_metadata_block(scan_meta)
    empty_scan = ScanResult(root=project_root)
    system, user = render_prompt(
        prompt_entry,
        depth=depth,
        scan=empty_scan,
        extra={
            "goal": goal,
            "tree": scan_meta.tree,
            "metadata": metadata_block,
        },
    )

    # тариф и курсы
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    # precheck бюджета — до запроса
    if max_cost_rub is not None:
        est = _estimate_next_cost_rub(
            cfg,
            model,
            system,
            user,
            cny_to_rub,
            expected_completion_tokens=1500,
        )
        if est >= max_cost_rub:
            _console.print(
                f"[red]Бюджет исчерпан до запроса:[/red] "
                f"оценка {est:.4f} RUB >= лимита {max_cost_rub:.4f} RUB"
            )
            return DecomposeResult(
                explanation="",
                subtasks=[],
                cost_rub=0.0,
                cost_cny=0.0,
                cost_usd=0.0,
                parse_error=(f"budget: оценка {est:.4f} RUB >= лимита {max_cost_rub:.4f} RUB"),
            )

    # запрос
    client = LLMClient(cfg.api)
    llm_resp = client.chat(
        system=system,
        user=user,
        model=model,
        json_mode=True,
        max_tokens=cfg.agent.step_max_output_tokens,
    )

    # парсим
    result = parse_decompose_response(llm_resp.content)
    result.llm = llm_resp

    # стоимость
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
    result.cost_rub = cost.cost_rub
    result.cost_cny = cost.cost_cny
    result.cost_usd = cost.cost_usd

    # учёт
    output_root = project_root / cfg.output.dir
    append_usage(
        project_root=project_root,
        output_root=output_root,
        action="agent:decompose",
        project_name=project_root.name,
        model=model,
        depth=depth,
        files_count=scan_meta.total_files,
        prompt_tokens=llm_resp.prompt_tokens,
        completion_tokens=llm_resp.completion_tokens,
        total_tokens=llm_resp.total_tokens,
        cost=cost,
        duration_ms=llm_resp.duration_ms,
        status="ok" if result.parse_error is None else "parse_error",
        usage_cfg=cfg.usage,
        iteration=0,
        parent_action="agent",
    )

    return result


def run_planner_replan(
    *,
    goal: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    failed_subtask: Subtask,
    failed_error: str,
    completed_subtasks: list[Subtask],
    remaining_subtasks: list[Subtask],
    model: str | None = None,
    depth: str = "normal",
) -> ReplanResult:
    """
    Планировщик-replan: подзадача провалилась → решаем,
    что делать (skip / modify / stop).
    """
    model = model or cfg.api.model

    # форматируем списки подзадач
    completed_text = "\n".join(f"  {s.n}. {s.goal}" for s in completed_subtasks) or "(нет)"
    remaining_text = "\n".join(f"  {s.n}. {s.goal}" for s in remaining_subtasks) or "(нет)"

    # промпт
    prompt_entry = prompts_cfg.get("agent_replan_json")
    empty_scan = ScanResult(root=project_root)
    system, user = render_prompt(
        prompt_entry,
        depth=depth,
        scan=empty_scan,
        extra={
            "goal": goal,
            "completed": completed_text,
            "failed_n": str(failed_subtask.n),
            "failed_goal": failed_subtask.goal,
            "error": failed_error,
            "remaining": remaining_text,
        },
    )

    # тариф и курсы
    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")

    # запрос
    client = LLMClient(cfg.api)
    llm_resp = client.chat(
        system=system,
        user=user,
        model=model,
        json_mode=True,
        max_tokens=cfg.agent.step_max_output_tokens,
    )

    # парсим
    result = parse_replan_response(llm_resp.content)
    result.llm = llm_resp

    # стоимость
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
    result.cost_rub = cost.cost_rub
    result.cost_cny = cost.cost_cny
    result.cost_usd = cost.cost_usd

    # учёт
    output_root = project_root / cfg.output.dir
    append_usage(
        project_root=project_root,
        output_root=output_root,
        action="agent:replan",
        project_name=project_root.name,
        model=model,
        depth=depth,
        files_count=0,
        prompt_tokens=llm_resp.prompt_tokens,
        completion_tokens=llm_resp.completion_tokens,
        total_tokens=llm_resp.total_tokens,
        cost=cost,
        duration_ms=llm_resp.duration_ms,
        status="ok" if result.parse_error is None else "parse_error",
        usage_cfg=cfg.usage,
        iteration=0,
        parent_action="agent",
    )

    return result


__all__ = [
    "_estimate_next_cost_rub",
    "_phase1_cache_key",
    "_phase1_cache_dir",
    "_phase1_from_cache",
    "_phase1_save_cache",
    "run_planner_phase1",
    "run_planner",
    "run_planner_decompose",
    "run_planner_replan",
    "_DIAGNOSTIC_MARKERS",
    "_CYR_TO_LAT",
    "_is_diagnostic_step",
    "_extract_target_files",
    "_slug_for_issue",
    "parse_agent_plan",
    "_parse_phase1_response",
    "parse_decompose_response",
    "parse_split_goals_response",
    "parse_replan_response",
]
