from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pathspec


OperationType = Literal["edit_file", "create_file"]


@dataclass
class Operation:
    type: OperationType
    path: str                       # POSIX-путь относительно project_root
    old: str | None = None          # для edit_file
    new: str | None = None          # для edit_file
    content: str | None = None      # для create_file


@dataclass
class WritePlan:
    explanation: str = ""
    operations: list[Operation] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    diff: str = ""
    raw_json: str = ""
    parse_error: str | None = None

    @property
    def valid(self) -> bool:
        return self.parse_error is None and not self.problems


# ---------- парсинг ответа модели ----------

def parse_response(content: str) -> WritePlan:
    """
    Парсит JSON-ответ модели. Устойчив к типичным «обёрткам»:
      ```json ... ```
      ``` ... ```
      текст до/после JSON
    """
    plan = WritePlan(raw_json=content)

    text = content.strip()

    # снимаем markdown-обёртку, если есть
    if text.startswith("```"):
        lines = text.splitlines()
        # первая строка — ``` или ```json
        lines = lines[1:]
        # последняя ``` — если есть
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    # если модель добавила текст до/после JSON — вырежем первый {...}
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        plan.parse_error = f"Не удалось распарсить JSON: {e}"
        return plan

    if not isinstance(data, dict):
        plan.parse_error = f"Ожидался JSON-объект, получено {type(data).__name__}"
        return plan

    plan.explanation = str(data.get("explanation", "")).strip()

    ops_raw = data.get("operations", [])
    if not isinstance(ops_raw, list):
        plan.parse_error = "Поле 'operations' должно быть списком"
        return plan

    for i, raw in enumerate(ops_raw):
        if not isinstance(raw, dict):
            plan.problems.append(f"operations[{i}]: не объект")
            continue
        op_type = raw.get("type")
        if op_type not in ("edit_file", "create_file"):
            plan.problems.append(f"operations[{i}]: неизвестный type '{op_type}'")
            continue
        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            plan.problems.append(f"operations[{i}]: пустой path")
            continue

        if op_type == "edit_file":
            old = raw.get("old")
            new = raw.get("new")
            if not isinstance(old, str) or not isinstance(new, str):
                plan.problems.append(f"operations[{i}] ({path}): old/new должны быть строками")
                continue
            plan.operations.append(Operation(type="edit_file", path=path, old=old, new=new))
        else:  # create_file
            content_val = raw.get("content")
            if not isinstance(content_val, str):
                plan.problems.append(f"operations[{i}] ({path}): content должен быть строкой")
                continue
            plan.operations.append(Operation(type="create_file", path=path, content=content_val))

    return plan


# ---------- валидация ----------

def _path_is_blacklisted(rel_path: str, cfg) -> bool:
    patterns = list(cfg.write.blacklist_paths)
    if not patterns:
        return False
    spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)
    if spec.match_file(rel_path) or spec.match_file(rel_path + "/"):
        return True
    if rel_path in cfg.write.blacklist_files:
        return True
    return False


def validate_operations(plan: WritePlan, project_root: Path, cfg) -> None:
    """
    Дополняет plan.problems найденными проблемами.
    """
    root = project_root.resolve()

    if len(plan.operations) > cfg.write.max_operations:
        plan.problems.append(
            f"Слишком много операций: {len(plan.operations)} > {cfg.write.max_operations}"
        )

    seen_paths: set[str] = set()

    for i, op in enumerate(plan.operations):
        tag = f"operations[{i}] ({op.path})"

        # --- нормализация пути ---
        if op.path.startswith("/") or ".." in Path(op.path).parts:
            plan.problems.append(f"{tag}: путь должен быть относительным и без '..'")
            continue

        rel = Path(op.path).as_posix()

        # --- дубликаты ---
        if rel in seen_paths:
            plan.problems.append(f"{tag}: путь повторяется в плане")
            continue
        seen_paths.add(rel)

        # --- blacklist ---
        if _path_is_blacklisted(rel, cfg):
            plan.problems.append(f"{tag}: путь в blacklist")
            continue

        abs_path = (root / rel).resolve()

        # --- внутри project_root? ---
        try:
            abs_path.relative_to(root)
        except ValueError:
            plan.problems.append(f"{tag}: путь вне проекта")
            continue

        if op.type == "create_file":
            if abs_path.exists():
                plan.problems.append(f"{tag}: файл уже существует (create_file)")
                continue
            if op.content is None or op.content == "":
                plan.problems.append(f"{tag}: пустое содержимое")
                continue
        elif op.type == "edit_file":
            if not abs_path.exists():
                plan.problems.append(f"{tag}: файл не найден (edit_file)")
                continue
            try:
                text = abs_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                plan.problems.append(f"{tag}: не удалось прочитать файл: {e}")
                continue

            if op.old is None or op.old == "":
                plan.problems.append(f"{tag}: пустой old")
                continue

            count = text.count(op.old)
            if count == 0:
                plan.problems.append(f"{tag}: фрагмент old не найден в файле")
                continue
            if count > 1:
                plan.problems.append(
                    f"{tag}: фрагмент old встречается {count} раз — правка неоднозначна"
                )
                continue

            if op.old == op.new:
                plan.problems.append(f"{tag}: old и new идентичны")


# ---------- рендер diff ----------
def render_diff(plan: WritePlan, project_root: Path) -> str:
    """
    Строит читаемый diff для показа. Не применяет ничего.
    Формат: pseudo-unified diff (для create_file — все строки с '+',
    для edit_file — '-old' / '+new').
    """
    root = project_root.resolve()
    chunks: list[str] = []

    for op in plan.operations:
        rel = Path(op.path).as_posix()
        abs_path = root / rel

        if op.type == "create_file":
            content = op.content or ""
            chunks.append(_render_create_diff(rel, content))
        elif op.type == "edit_file":
            try:
                original = abs_path.read_text(encoding="utf-8")
            except OSError:
                chunks.append(f"# не удалось прочитать {rel}\n")
                continue

            if not op.old:
                chunks.append(f"# пустой old для {rel}\n")
                continue

            count = original.count(op.old)
            if count != 1:
                chunks.append(
                    f"# пропущено: old встречается {count} раз(а) в {rel} — diff неоднозначен\n"
                )
                continue

            chunks.append(_render_edit_diff(rel, op.old, op.new or ""))

    return "\n".join(chunks).strip()


def _render_create_diff(path: str, content: str) -> str:
    lines = [f"--- /dev/null", f"+++ b/{path}"]
    for line in content.splitlines():
        lines.append("+" + line)
    return "\n".join(lines) + "\n"


def _render_edit_diff(path: str, old: str, new: str) -> str:
    lines = [f"--- a/{path}", f"+++ b/{path}"]
    for line in old.splitlines():
        lines.append("-" + line)
    for line in new.splitlines():
        lines.append("+" + line)
    return "\n".join(lines) + "\n"

def build_plan(content: str, project_root: Path, cfg) -> WritePlan:
    """
    Полный цикл: парсинг → валидация → diff.
    """
    plan = parse_response(content)
    if plan.parse_error is None:
        validate_operations(plan, project_root, cfg)
    if plan.parse_error is None:
        plan.diff = render_diff(plan, project_root)
    return plan