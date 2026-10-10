from __future__ import annotations

import json
import py_compile
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

OperationType = Literal["edit_file", "create_file"]


@dataclass
class Operation:
    """Одна операция записи: edit_file (замена old→new) или create_file (новый файл)."""

    type: OperationType
    path: str  # POSIX-путь относительно project_root
    old: str | None = None  # для edit_file
    new: str | None = None  # для edit_file
    content: str | None = None  # для create_file


@dataclass
class WritePlan:
    """Разобранный план изменений от модели: операции, проблемы валидации и diff."""

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
            text = text[start : end + 1]

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
    from .pathfilter import is_blacklisted

    return is_blacklisted(
        rel_path,
        cfg.write.blacklist_paths,
        cfg.write.blacklist_files,
    )


def validate_operations(plan: WritePlan, project_root: Path, cfg) -> None:
    """
    Дополняет plan.problems найденными проблемами.
    Разрешает несколько операций на один путь (например, несколько
    edit_file в одном файле), но требует уникальный old для каждого.
    """
    root = project_root.resolve()

    if len(plan.operations) > cfg.write.max_operations:
        plan.problems.append(
            f"Слишком много операций: {len(plan.operations)} > {cfg.write.max_operations}"
        )

    # для каждого файла — накапливаем old-фрагменты, чтобы проверить
    # уникальность внутри самого плана и отсутствие вложенности
    edits_by_path: dict[str, list[str]] = {}
    created_paths: set[str] = set()

    for i, op in enumerate(plan.operations):
        tag = f"operations[{i}] ({op.path})"

        # --- нормализация пути ---
        if op.path.startswith("/") or ".." in Path(op.path).parts:
            plan.problems.append(f"{tag}: путь должен быть относительным и без '..'")
            continue

        rel = Path(op.path).as_posix()

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
            if rel in created_paths:
                plan.problems.append(f"{tag}: файл уже создаётся другой операцией")
                continue
            created_paths.add(rel)
            if abs_path.exists():
                plan.problems.append(f"{tag}: файл уже существует (create_file)")
                continue
            if op.content is None or op.content == "":
                plan.problems.append(f"{tag}: пустое содержимое")
                continue
            if rel in edits_by_path:
                plan.problems.append(f"{tag}: файл одновременно создаётся и редактируется")
                continue

        elif op.type == "edit_file":
            if rel in created_paths:
                plan.problems.append(f"{tag}: файл одновременно создаётся и редактируется")
                continue
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
            if op.old == op.new:
                plan.problems.append(f"{tag}: old и new идентичны")
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

            # проверяем пересечение old-фрагментов в рамках одного файла
            for j, existing in enumerate(edits_by_path.get(rel, [])):
                if op.old in existing or existing in op.old:
                    plan.problems.append(
                        f"{tag}: фрагмент old пересекается с другой правкой этого файла"
                    )
                    break
            else:
                edits_by_path.setdefault(rel, []).append(op.old)


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
    lines = ["--- /dev/null", f"+++ b/{path}"]
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


# ---------- применение ----------


def _copy_to_backup(abs_path: Path, project_root: Path, backup_dir: Path) -> Path:
    """
    Копирует файл (если он есть) в backup_dir с сохранением относительного пути.
    Возвращает путь в бэкапе.
    """
    rel = abs_path.relative_to(project_root)
    dst = backup_dir / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if abs_path.exists():
        shutil.copy2(abs_path, dst)
    return dst


def apply_plan(
    plan: WritePlan,
    project_root: Path,
    backup_dir: Path,
) -> tuple[list[str], list[str]]:
    if plan.parse_error is not None:
        return [], [f"План невалиден (parse_error): {plan.parse_error}"]
    if plan.problems:
        return [], [f"План невалиден: {len(plan.problems)} проблем"]

    root = project_root.resolve()
    backup_dir = backup_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)

    applied: list[str] = []
    backed_up_paths: set[str] = set()  # rel-пути, уже забэкапленные
    backups_made: list[tuple[Path, Path]] = []  # для отката при ошибке
    created_files: list[Path] = []
    operations_log: list[dict] = []

    try:
        for i, op in enumerate(plan.operations):
            rel = Path(op.path).as_posix()
            abs_path = (root / rel).resolve()

            try:
                abs_path.relative_to(root)
            except ValueError:
                raise RuntimeError(f"operations[{i}] ({rel}): путь вне проекта")

            existed_before = abs_path.exists()

            # --- бэкап ТОЛЬКО если файл ещё не бэкапили в этой сессии ---
            if rel not in backed_up_paths:
                backup_path = _copy_to_backup(abs_path, root, backup_dir)
                if existed_before:
                    backups_made.append((abs_path, backup_path))
                backed_up_paths.add(rel)

            if op.type == "create_file":
                content = op.content or ""
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.write_text(content, encoding="utf-8")
                created_files.append(abs_path)
                applied.append(rel)
                operations_log.append({"type": "create_file", "path": rel})
            elif op.type == "edit_file":
                text = abs_path.read_text(encoding="utf-8")
                if text.count(op.old or "") != 1:
                    raise RuntimeError(f"operations[{i}] ({rel}): old встречается не один раз")
                new_text = text.replace(op.old or "", op.new or "", 1)
                abs_path.write_text(new_text, encoding="utf-8")
                applied.append(rel)
                operations_log.append({"type": "edit_file", "path": rel})
            else:
                raise RuntimeError(f"operations[{i}]: неизвестный тип {op.type}")

        manifest = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "project_root": str(root),
            "operations": operations_log,
        }
        (backup_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return applied, []

    except Exception as e:
        for abs_path, backup_path in backups_made:
            try:
                shutil.copy2(backup_path, abs_path)
            except OSError:
                pass
        for abs_path in created_files:
            try:
                abs_path.unlink()
            except OSError:
                pass
        return [], [f"Ошибка применения, выполнен откат: {e}"]


def rollback(backup_dir: Path, project_root: Path) -> list[str]:
    """
    Восстанавливает проект из backup_dir.
    Для create_file — удаляет файл.
    Для edit_file — восстанавливает из копии.
    Если манифеста нет (старый бэкап) — только восстанавливает копии.
    Возвращает список изменённых путей (относительных, с префиксом ~ или -).
    """
    backup_dir = backup_dir.resolve()
    root = project_root.resolve()
    if not backup_dir.is_dir():
        raise NotADirectoryError(f"Бэкап не найден: {backup_dir}")

    manifest_path = backup_dir / "manifest.json"
    restored: list[str] = []

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        operations = manifest.get("operations", [])

        done: set[str] = set()
        for op in operations:
            rel = Path(op.get("path", "")).as_posix()
            if not rel or rel in done:
                continue
            done.add(rel)

            dst = root / rel
            op_type = op.get("type")

            if op_type == "create_file":
                try:
                    dst.unlink()
                    restored.append(f"-{rel}")
                except FileNotFoundError:
                    pass
                except OSError:
                    pass
            elif op_type == "edit_file":
                src = backup_dir / rel
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    restored.append(f"~{rel}")

        return restored

    # фолбэк: старые бэкапы без манифеста
    for src in sorted(backup_dir.rglob("*")):
        if src.is_dir() or src.name == "manifest.json":
            continue
        rel_path = src.relative_to(backup_dir)
        dst = root / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        restored.append(f"~{rel_path.as_posix()}")
    return restored


def check_python_files(paths: list[str], project_root: Path) -> list[str]:
    errors: list[str] = []
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        abs_path = project_root / rel
        try:
            py_compile.compile(str(abs_path), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f"{rel}: {e.msg}")
        except OSError as e:
            errors.append(f"{rel}: {e}")
    return errors


def list_backups(project_root: Path) -> list[dict]:
    """
    Возвращает список бэкапов проекта: путь, имя, кол-во файлов, кол-во операций.
    """
    root = project_root.resolve()
    base = root / ".ai-out" / root.name
    if not base.is_dir():
        return []
    out: list[dict] = []
    for d in sorted(base.glob("backup-*"), reverse=True):
        if not d.is_dir():
            continue
        files = [p for p in d.rglob("*") if p.is_file() and p.name != "manifest.json"]
        ops = 0
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                ops = len(manifest.get("operations", []))
            except (OSError, json.JSONDecodeError):
                pass
        out.append(
            {
                "dir": d,
                "name": d.name,
                "files": len(files),
                "operations": ops,
            }
        )
    return out


def run_verify_commands(
    commands: list[str],
    project_root: Path,
    *,
    timeout_sec: int = 60,
    max_output_chars: int = 10_000,
) -> list[str]:
    """
    Запускает список shell-команд в project_root.
    Возвращает список сообщений об ошибках (пустой — всё ок).
    """
    import subprocess

    root = project_root.resolve()
    errors: list[str] = []

    for cmd in commands:
        cmd = cmd.strip()
        if not cmd:
            continue

        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
        except subprocess.TimeoutExpired:
            errors.append(f"$ {cmd}\n  ТАЙМАУТ ({timeout_sec} с)")
            continue
        except Exception as e:
            errors.append(f"$ {cmd}\n  не удалось запустить: {e}")
            continue

        if proc.returncode == 0:
            continue

        output = (proc.stdout or "") + (proc.stderr or "")
        if len(output) > max_output_chars:
            output = output[:max_output_chars] + f"\n... [обрезано, всего {len(output)} символов]"

        errors.append(f"$ {cmd}\n  exit code: {proc.returncode}\n{output.rstrip()}")

    return errors
