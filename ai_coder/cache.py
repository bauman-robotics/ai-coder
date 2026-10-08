from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from .apply import Operation, WritePlan
from .llm import LLMResponse
from .scanner import ScanResult


def compute_hash(
    scan: ScanResult,
    prompt_system: str,
    prompt_user: str,
    model: str,
    depth: str,
    write_blacklist_paths: list[str] | None = None,
    write_blacklist_files: list[str] | None = None,
    write_max_operations: int | None = None,
) -> str:
    """
    Считает sha256 от содержимого файлов, шаблонов промптов, модели, глубины
    и настроек write (blacklist, max_operations).
    Файлы и списки сортируются, чтобы хэш не зависел от порядка обхода.
    """
    h = hashlib.sha256()

    # версия схемы — если поменяем алгоритм, старые кэши не подойдут
    h.update(b"ai-coder-cache-v2\n")

    h.update(f"model:{model}\n".encode())
    h.update(f"depth:{depth}\n".encode())

    # шаблон промпта
    h.update(b"---SYSTEM---\n")
    h.update(prompt_system.encode("utf-8"))
    h.update(b"\n---USER---\n")
    h.update(prompt_user.encode("utf-8"))

    # настройки write (blacklist/max_operations) — влияют на валидность плана
    h.update(b"\n---WRITE---\n")
    for p in sorted(write_blacklist_paths or []):
        h.update(f"blacklist_path:{p}\n".encode("utf-8"))
    for f in sorted(write_blacklist_files or []):
        h.update(f"blacklist_file:{f}\n".encode("utf-8"))
    h.update(f"max_operations:{write_max_operations}\n".encode("utf-8"))

    # файлы
    h.update(b"\n---FILES---\n")
    for rel in sorted(scan.files.keys()):
        h.update(f"### {rel}\n".encode())
        h.update(scan.files[rel].encode("utf-8"))
        h.update(b"\n")

    return h.hexdigest()


def _cache_path(project_root: Path, output_dir: str, cache_dir_name: str, hash_hex: str) -> Path:
    return project_root / output_dir / project_root.name / cache_dir_name / f"{hash_hex}.json"


def load(
    project_root: Path,
    output_dir: str,
    cache_dir_name: str,
    hash_hex: str,
) -> dict | None:
    p = _cache_path(project_root, output_dir, cache_dir_name, hash_hex)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save(
    project_root: Path,
    output_dir: str,
    cache_dir_name: str,
    hash_hex: str,
    *,
    action: str,
    model: str,
    depth: str,
    prompt_name: str,
    llm: LLMResponse,
    write_plan: WritePlan | None,
    report_path: Path | None = None,
) -> Path:
    p = _cache_path(project_root, output_dir, cache_dir_name, hash_hex)
    p.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "hash": hash_hex,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "model": model,
        "depth": depth,
        "prompt_name": prompt_name,
        "report_path": str(report_path) if report_path else None,
        "llm": {
            "content": llm.content,
            "model": llm.model,
            "prompt_tokens": llm.prompt_tokens,
            "prompt_cache_hit_tokens": llm.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": llm.prompt_cache_miss_tokens,
            "completion_tokens": llm.completion_tokens,
            "total_tokens": llm.total_tokens,
            "duration_ms": llm.duration_ms,
            "finish_reason": llm.finish_reason,
        },
        "write_plan": _serialize_plan(write_plan) if write_plan else None,
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _serialize_plan(plan: WritePlan) -> dict:
    return {
        "explanation": plan.explanation,
        "operations": [
            {
                "type": op.type,
                "path": op.path,
                "old": op.old,
                "new": op.new,
                "content": op.content,
            }
            for op in plan.operations
        ],
        "problems": plan.problems,
        "diff": plan.diff,
        "raw_json": plan.raw_json,
        "parse_error": plan.parse_error,
    }


def _deserialize_plan(data: dict) -> WritePlan:
    plan = WritePlan(
        explanation=data.get("explanation", ""),
        problems=data.get("problems", []),
        diff=data.get("diff", ""),
        raw_json=data.get("raw_json", ""),
        parse_error=data.get("parse_error"),
    )
    for op in data.get("operations", []):
        plan.operations.append(
            Operation(
                type=op["type"],
                path=op["path"],
                old=op.get("old"),
                new=op.get("new"),
                content=op.get("content"),
            )
        )
    return plan


def _deserialize_llm(data: dict) -> LLMResponse:
    return LLMResponse(
        content=data.get("content", ""),
        model=data.get("model", ""),
        prompt_tokens=data.get("prompt_tokens", 0),
        prompt_cache_hit_tokens=data.get("prompt_cache_hit_tokens", 0),
        prompt_cache_miss_tokens=data.get("prompt_cache_miss_tokens", 0),
        completion_tokens=data.get("completion_tokens", 0),
        total_tokens=data.get("total_tokens", 0),
        duration_ms=data.get("duration_ms", 0),
        finish_reason=data.get("finish_reason"),
    )


def from_cache(
    project_root: Path,
    output_dir: str,
    cache_dir_name: str,
    hash_hex: str,
    scan: ScanResult,
) -> tuple[LLMResponse, WritePlan | None] | None:
    """
    Восстанавливает (LLMResponse, WritePlan|None) из кэша.
    Возвращает None, если кэш не найден или испорчен.
    """
    data = load(project_root, output_dir, cache_dir_name, hash_hex)
    if data is None:
        return None
    try:
        llm = _deserialize_llm(data["llm"])
        plan = _deserialize_plan(data["write_plan"]) if data.get("write_plan") else None
        return llm, plan
    except (KeyError, TypeError):
        return None
