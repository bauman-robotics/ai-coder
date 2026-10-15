"""Reverse-check агента ai_coder.

Вторая LLM-проверка diff после успешного tool loop.
Вынесено из agent/_legacy.py (10.65.4a split-file).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ..config import AppConfig, PromptsConfig
from ..git import is_git_repo
from ..llm import LLMClient
from ..pricing import calculate_cost, get_rate, is_peak_now
from .models import ReverseCheckResult

_MAX_DIFF_CHARS = 15000


def _collect_diff(project_root: Path) -> str:
    """
    Собирает git diff рабочего дерева (uncommitted).

    Включает новые (untracked) файлы: git diff их не показывает,
    поэтому они добавляются вручную по данным git status --porcelain.
    """

    if not is_git_repo(project_root):
        return ""
    try:
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""

    diff = result.stdout

    # Untracked-файлы добавляются вручную.
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return diff

    untracked = [line[3:].strip() for line in status.stdout.splitlines() if line.startswith("?? ")]
    if not untracked:
        return diff

    extra = ""
    for rel_path in untracked:
        if not rel_path:
            continue
        # git экранирует пути с не-ASCII в кавычки: "?? \"path\"".
        if len(rel_path) >= 2 and rel_path[0] == '"' and rel_path[-1] == '"':
            rel_path = rel_path[1:-1]
        try:
            content = (project_root / rel_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        section = (
            f"diff --git a/{rel_path} b/{rel_path}\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/{rel_path}\n"
        )
        if content:
            section += "\n".join("+" + line for line in content.splitlines())
            section += "\n"
        extra += section

    # Не превышаем лимит: добавляем untracked ровно столько, сколько влезает.
    budget = _MAX_DIFF_CHARS - len(diff)
    if budget <= 0:
        return diff
    if len(extra) > budget:
        extra = extra[:budget]
    return diff + extra


def run_reverse_check(
    *,
    goal: str,
    diff: str,
    project_root: Path,
    cfg: AppConfig,
    prompts_cfg: PromptsConfig,
    model: str | None = None,
) -> ReverseCheckResult:
    """
    Проверяет diff на соответствие goal через вторую LLM-проверку.

    Возвращает ReverseCheckResult. При ошибке парсинга — ok=True
    (не блокируем, чтобы не ломать пайплайн).
    """
    max_chars = getattr(cfg.agent, "reverse_check_max_diff_chars", 15000)
    if len(diff) > max_chars:
        diff = diff[:max_chars] + f"\n\n[... обрезано, всего {len(diff)} символов]"

    prompt_entry = prompts_cfg.get("agent_reverse_check")
    # render_prompt требует depth+scan — для reverse-check не нужны.
    # Подставляем переменные вручную (промпт простой: {{goal}}, {{diff}}).
    system = prompt_entry.system.replace("{{goal}}", goal).replace("{{diff}}", diff)
    user = prompt_entry.user.replace("{{goal}}", goal).replace("{{diff}}", diff)

    rc_model = (
        model
        or getattr(cfg.agent, "reverse_check_model", None)
        or getattr(cfg.agent, "decompose_model", None)
        or cfg.api.model
    )

    client = LLMClient(cfg.api)
    try:
        llm_resp = client.chat(
            model=rc_model,
            system=system,
            user=user,
            temperature=0.0,
        )
    except Exception as e:
        return ReverseCheckResult(ok=True, parse_error=f"LLM error: {e}")

    is_peak, peak_window = is_peak_now(cfg.api.peak_schedule)
    cny_to_rub = get_rate(project_root, cfg.currency.cny_to_rub, key="CNY")
    usd_to_rub = get_rate(project_root, cfg.currency.usd_to_rub, key="USD")
    cost = calculate_cost(
        pricing=cfg.api.pricing_for(rc_model),
        is_peak=is_peak,
        peak_window=peak_window,
        prompt_hit_tokens=llm_resp.prompt_cache_hit_tokens,
        prompt_miss_tokens=llm_resp.prompt_cache_miss_tokens,
        completion_tokens=llm_resp.completion_tokens,
        cny_to_rub=cny_to_rub,
        usd_to_rub=usd_to_rub,
    )

    content = llm_resp.content.strip()
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) >= 2:
            content = parts[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

    try:
        data = json.loads(content)
        return ReverseCheckResult(
            ok=bool(data.get("ok", True)),
            problems=list(data.get("problems", []) or []),
            suggestion=data.get("suggestion"),
            cost_rub=cost.cost_rub,
            cost_cny=cost.cost_cny,
            cost_usd=cost.cost_usd,
            raw_response=llm_resp.content,
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return ReverseCheckResult(
            ok=True,
            parse_error=str(e),
            cost_rub=cost.cost_rub,
            cost_cny=cost.cost_cny,
            cost_usd=cost.cost_usd,
            raw_response=llm_resp.content,
        )


__all__ = [
    "_MAX_DIFF_CHARS",
    "_collect_diff",
    "run_reverse_check",
]
