"""Фильтрация путей по blacklist (общий модуль для apply и tools)."""

from __future__ import annotations

import pathspec


def is_blacklisted(
    rel_path: str,
    blacklist_paths: list[str],
    blacklist_files: list[str],
) -> bool:
    """
    True, если rel_path попадает в blacklist_paths (gitignore-паттерны)
    или точно совпадает с одним из blacklist_files.
    """
    patterns = list(blacklist_paths)
    if patterns:
        spec = pathspec.PathSpec.from_lines("gitignore", patterns)
        if spec.match_file(rel_path) or spec.match_file(rel_path + "/"):
            return True
    if rel_path in blacklist_files:
        return True
    return False
