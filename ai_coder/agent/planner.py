"""Планировщик агента ai_coder.

Парсеры планов, декомпозиции, replan, split-goals.
Вынесено из agent/_legacy.py (10.65.3a split-file).
"""

from __future__ import annotations

import json
import re

from .models import (
    AgentPlan,
    AgentStep,
    DecomposeResult,
    ReplanResult,
    SplitGoalsResult,
    SplitIssue,
    Subtask,
)

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


__all__ = [
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
