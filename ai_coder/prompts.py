from __future__ import annotations

import re

from .config import PromptEntry, PromptsConfig
from .scanner import ScanResult, render_files_block

_VAR_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")

_DEPTH_HINTS: dict[str, str] = {
    "shallow": ("Дай краткий обзор: только самое главное, без деталей реализации."),
    "normal": (
        "Дай сбалансированный обзор: достаточно деталей, чтобы понять, "
        "как всё устроено, но без излишеств."
    ),
    "deep": (
        "Разбирай ключевые модули детально, показывай связи между абстракциями, "
        "приводи конкретные примеры из кода. Отвечай максимально полно."
    ),
}


def render_prompt(
    entry: PromptEntry,
    *,
    depth: str,
    scan: ScanResult,
    extra: dict[str, str] | None = None,
) -> tuple[str, str]:
    """
    Возвращает (system, user) с подставленными переменными.
    Поддерживаемые переменные:
      {{depth}}       — shallow | normal | deep
      {{depth_hint}}  — текстовая подсказка модели
      {{tree}}        — дерево файлов
      {{files}}       — содержимое файлов
      плюс любые из extra
    """
    values: dict[str, str] = {
        "depth": depth,
        "depth_hint": _DEPTH_HINTS.get(depth, _DEPTH_HINTS["normal"]),
        "tree": scan.tree,
        "files": render_files_block(scan),
    }
    if extra:
        values.update(extra)

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Неизвестная переменная в промпте: {{{{{key}}}}}")
        return values[key]

    system = _VAR_RE.sub(_sub, entry.system)
    user = _VAR_RE.sub(_sub, entry.user)
    return system, user


def validate_prompt_vars(cfg: PromptsConfig, known_vars: set[str]) -> list[str]:
    """
    Проверяет, что во всех промптах используются только известные переменные.
    Возвращает список проблем (пустой = всё ок).
    """
    problems: list[str] = []
    for name, entry in cfg.prompts.items():
        used = set(_VAR_RE.findall(entry.system)) | set(_VAR_RE.findall(entry.user))
        unknown = used - known_vars
        if unknown:
            problems.append(f"{name}: неизвестные переменные {sorted(unknown)}")
    return problems
