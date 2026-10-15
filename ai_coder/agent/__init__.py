"""Пакет ai_coder.agent.

Шаг 1 split-file (10.65): тонкая обёртка над _legacy.py.
Реэкспортирует всё, что импортируется из ai_coder.agent в cli.py,
history.py и тестах — включая приватные имена, которые патчатся
через `patch("ai_coder.agent.X")`.
"""

from __future__ import annotations

# Внешние импорты, которые патчатся через ai_coder.agent.X
from ai_coder.apply import (
    WritePlan,
    apply_plan,
    build_plan,
    check_python_files,
    run_verify_commands,
)
from ai_coder.config import WEB_ASSET_EXTENSIONS, AppConfig, PromptsConfig
from ai_coder.llm import LLMClient, LLMResponse
from ai_coder.pricing import Rate, calculate_cost, get_rate, is_peak_now
from ai_coder.prompts import render_prompt
from ai_coder.scanner import (
    ScanResult,
    render_metadata_block,
    scan_project,
    scan_project_metadata,
)
from ai_coder.tools import (
    TOOL_REGISTRY,
    ToolAction,
    ToolResult,
    _safe_path,
    execute_tool,
    format_tool_history,
    format_tools_for_prompt,
    parse_tool_action,
)
from ai_coder.usage import append_usage

from ._legacy import *  # noqa: F401,F403
from ._legacy import __all__ as _legacy_all  # noqa: F401

# Всё содержимое _legacy (включая приватное — через __all__ в _legacy)
from .models import *  # noqa: F401,F403
from .models import __all__ as _models_all  # noqa: F401
from .planner import *  # noqa: F401,F403
from .planner import __all__ as _planner_all  # noqa: F401
from .reverse import *  # noqa: F401,F403
from .reverse import __all__ as _reverse_all  # noqa: F401
from .tool_loop import *  # noqa: F401,F403
from .tool_loop import __all__ as _tool_loop_all  # noqa: F401

# Расширяем __all__ внешними именами
__all__ = (
    list(_models_all)
    + list(_planner_all)
    + list(_reverse_all)
    + list(_tool_loop_all)
    + list(_legacy_all)
    + [
        "WritePlan",
        "apply_plan",
        "build_plan",
        "check_python_files",
        "run_verify_commands",
        "WEB_ASSET_EXTENSIONS",
        "AppConfig",
        "PromptsConfig",
        "LLMClient",
        "LLMResponse",
        "Rate",
        "calculate_cost",
        "get_rate",
        "is_peak_now",
        "render_prompt",
        "ScanResult",
        "render_metadata_block",
        "scan_project",
        "scan_project_metadata",
        "TOOL_REGISTRY",
        "ToolAction",
        "ToolResult",
        "_safe_path",
        "execute_tool",
        "format_tool_history",
        "format_tools_for_prompt",
        "parse_tool_action",
        "append_usage",
    ]
)
