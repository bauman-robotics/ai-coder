from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from .config import ScanningConfig

# ---------- результат ----------

@dataclass
class SkippedFile:
    path: str
    reason: str  # gitignore | extra_ignore | secret_ignore | binary | too_large | not_included | budget


@dataclass
class ScanResult:
    root: Path
    files: dict[str, str] = field(default_factory=dict)   # rel_path -> content
    tree: str = ""
    skipped: list[SkippedFile] = field(default_factory=list)
    total_bytes: int = 0
    estimated_tokens: int = 0
    truncated: bool = False


# ---------- вспомогательное ----------

def _load_specs_recursive(root: Path) -> list[tuple[Path, pathspec.PathSpec]]:
    """
    Собирает все .gitignore в проекте (корень + подпапки).
    Пропускает служебные каталоги (.venv, .git, node_modules, ...).
    """
    specs: list[tuple[Path, pathspec.PathSpec]] = []

    def walk(dir_path: Path) -> None:
        try:
            entries = sorted(dir_path.iterdir())
        except OSError:
            return

        for entry in entries:
            if entry.is_dir():
                if entry.name in _SERVICE_DIRS:
                    continue
                walk(entry)
                continue

            if entry.name == ".gitignore":
                try:
                    lines = entry.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                specs.append((entry.parent, pathspec.PathSpec.from_lines("gitignore", lines)))

    walk(root)
    return specs


def _is_gitignored(rel_path: str, specs: list[tuple[Path, pathspec.PathSpec]], root: Path) -> bool:
    """
    Проверяет, попадает ли файл/директория под какой-либо .gitignore.
    rel_path — путь относительно root, POSIX-формат ('a/b/c.py' или 'a/b/').
    """
    if not specs:
        return False
    abs_path = root / rel_path.rstrip("/")
    for base_dir, spec in specs:
        try:
            sub_rel = abs_path.relative_to(base_dir).as_posix()
        except ValueError:
            continue
        # для директорий pathspec-матч требует слэш на конце
        if spec.match_file(sub_rel) or spec.match_file(sub_rel + "/"):
            return True
    return False


def _compile_spec(patterns: list[str]) -> pathspec.PathSpec | None:
    """
    Компилирует gitignore-паттерны один раз. Возвращает None, если пусто.
    """
    if not patterns:
        return None
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def _match_any(path_posix: str, spec: pathspec.PathSpec | None) -> bool:
    """
    Проверяет путь против скомпилированного PathSpec.
    Принимает уже готовый spec, а не список паттернов.
    """
    if spec is None:
        return False
    # пробуем и как файл, и как директорию
    return spec.match_file(path_posix) or spec.match_file(path_posix + "/")

# ---------- content-фильтр секретов ----------

# Узкие паттерны: реальные ключи и токены, минимум ложных срабатываний.
# Каждый — кортеж (regex, человекочитаемое название).
_SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI/DeepSeek API key"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub personal access token"),
    (r"github_pat_[a-zA-Z0-9_]{82}", "GitHub fine-grained PAT"),
    (r"xox[baprs]-[a-zA-Z0-9-]{10,}", "Slack token"),
    (r"-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key (PEM)"),
    (r"AIza[0-9A-Za-z_\-]{35}", "Google API key"),
)


def _contains_secret(text: str) -> str | None:
    """
    Проверяет содержимое на типичные секреты (ключи, токены, PEM-ключи).
    Возвращает название найденного паттерна или None.
    """
    for pattern, name in _SECRET_PATTERNS:
        if re.search(pattern, text):
            return name
    return None


def _expand_dir_patterns(patterns: list[str]) -> list[str]:
    """
    Для паттернов вида ".venv/" или ".venv" добавляет варианты,
    которые матчат и содержимое: ".venv/**", ".venv/", ".venv".
    """
    out: list[str] = []
    for p in patterns:
        out.append(p)
        if p.endswith("/"):
            out.append(p + "**")
            out.append(p.rstrip("/"))
        elif "/" not in p and not p.startswith("*") and not p.startswith("!"):
            out.append(p + "/**")
            out.append(p + "/")
    return out


def _estimate_tokens(text: str) -> int:
    """
    Грубая консервативная оценка: ~3 символа на токен.
    Точные значения берём из usage ответа API.
    """
    return max(1, len(text) // 3)


# ---------- служебные директории ----------

_SERVICE_DIRS = {".git", ".ai-out", "__pycache__", "node_modules", ".venv", "venv", ".mypy_cache", ".ruff_cache", ".pytest_cache"}


# ---------- основной обход ----------

def scan_project(
    root: Path,
    cfg: ScanningConfig,
    *,
    extra_exclude: list[str] | None = None,
) -> ScanResult:
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Не директория: {root}")

    # 1. specs из .gitignore
    gi_specs = _load_specs_recursive(root) if cfg.use_gitignore else []

    # 2. доп. паттерны (с расширением под директории) — компилируем один раз
    extra_patterns = _expand_dir_patterns(list(cfg.extra_ignore) + (extra_exclude or []))
    secret_patterns = _expand_dir_patterns(list(cfg.secret_ignore))
    extra_spec = _compile_spec(extra_patterns)
    secret_spec = _compile_spec(secret_patterns)
    binary_ext = set(cfg.binary_extensions)
    include_ext = set(cfg.include_extensions)
    max_bytes = cfg.max_file_size_kb * 1024

    result = ScanResult(root=root)
    collected: list[tuple[str, str, int]] = []

    def should_skip_dir(rel_dir: str, name: str) -> bool:
        """Директории, в которые не надо заходить."""
        if name in _SERVICE_DIRS:
            return True
        rel_posix = f"{rel_dir}/{name}" if rel_dir else name
        if _match_any(rel_posix, extra_spec):
            return True
        if _match_any(rel_posix, secret_spec):
            return True
        if cfg.use_gitignore and _is_gitignored(rel_posix, gi_specs, root):
            return True
        return False

    def walk(dir_path: Path, rel_dir: str) -> None:
        try:
            entries = sorted(dir_path.iterdir(), key=lambda p: (p.is_file(), p.name))
        except OSError:
            return

        for entry in entries:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name

            if entry.is_dir():
                if should_skip_dir(rel_dir, entry.name):
                    continue
                walk(entry, rel)
                continue

            # --- файл ---
            if cfg.use_gitignore and _is_gitignored(rel, gi_specs, root):
                result.skipped.append(SkippedFile(rel, "gitignore"))
                continue
            if _match_any(rel, extra_spec):
                result.skipped.append(SkippedFile(rel, "extra_ignore"))
                continue
            if _match_any(rel, secret_spec):
                result.skipped.append(SkippedFile(rel, "secret_ignore"))
                continue

            ext = entry.suffix.lower()
            if ext in binary_ext:
                result.skipped.append(SkippedFile(rel, "binary"))
                continue
            if include_ext and ext not in include_ext:
                result.skipped.append(SkippedFile(rel, "not_included"))
                continue

            try:
                size = entry.stat().st_size
            except OSError:
                result.skipped.append(SkippedFile(rel, "binary"))
                continue

            if size > max_bytes:
                result.skipped.append(SkippedFile(rel, "too_large"))
                continue

            try:
                text = entry.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    text = entry.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    result.skipped.append(SkippedFile(rel, "binary"))
                    continue
            except OSError:
                result.skipped.append(SkippedFile(rel, "binary"))
                continue

            # content-проверка на секреты (review 1.4)
            found = _contains_secret(text)
            if found is not None:
                result.skipped.append(SkippedFile(rel, f"secret_content: {found}"))
                continue

            collected.append((rel, text, size))

    walk(root, "")

    # --- бюджет токенов ---
    total_tokens = 0
    kept: dict[str, str] = {}
    for rel, text, size in collected:
        t = _estimate_tokens(text)
        if total_tokens + t > cfg.max_total_tokens:
            result.truncated = True
            result.skipped.append(SkippedFile(rel, "budget"))
            continue
        kept[rel] = text
        total_tokens += t
        result.total_bytes += size

    result.files = kept
    result.estimated_tokens = total_tokens
    result.tree = build_tree(list(kept.keys()))
    return result


# ---------- дерево ----------

def build_tree(paths: list[str]) -> str:
    """
    Строит текстовое дерево из списка относительных POSIX-путей.
    Сначала директории, потом файлы, всё по алфавиту.
    """
    if not paths:
        return ""

    tree: dict = {}
    for p in sorted(paths):
        parts = p.split("/")
        cur = tree
        for part in parts:
            cur = cur.setdefault(part, {})

    lines: list[str] = []

    def walk_node(node: dict, prefix: str = "") -> None:
        items = sorted(node.items(), key=lambda kv: (not kv[1], kv[0]))
        for i, (name, child) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{name}")
            if child:
                extension = "    " if is_last else "│   "
                walk_node(child, prefix + extension)

    walk_node(tree)
    return "\n".join(lines)


# ---------- рендер файлов для промпта ----------

def render_files_block(result: ScanResult, max_file_chars: int = 20000) -> str:
    """
    Формирует блок содержимого файлов для подстановки в {{files}}.
    Порядок фиксирован (sorted) — важно для cache hit.
    """
    parts: list[str] = []
    for rel in sorted(result.files.keys()):
        content = result.files[rel]
        if len(content) > max_file_chars:
            content = content[:max_file_chars] + f"\n... [обрезано, всего {len(content)} символов]"
        parts.append(f"### {rel}\n```\n{content}\n```\n")
    return "\n".join(parts)
