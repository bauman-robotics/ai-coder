"""FastAPI-приложение веб-панели ai-coder."""

import re
import shlex
import signal
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone
from html import escape as html_escape
from pathlib import Path

import markdown
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
# .ai-out — рабочие артефакты (журналы, отчёты). CWD при запуске uvicorn.
AI_OUT_DIR = Path.cwd() / ".ai-out"
USAGE_JSONL = AI_OUT_DIR / "usage.jsonl"

# Справочник команд (docs/cli/). CWD при запуске uvicorn.
DOCS_CLI_DIR = Path.cwd() / "docs" / "cli"

app = FastAPI(title="ai-coder GUI")

# Реестр запущенных процессов: run_id -> Popen.
RUNNING: dict[str, subprocess.Popen] = {}

# Whitelist префиксов журналов для /reports (backup/cache отсекаются).
JOURNAL_PREFIXES = (
    "tool-loop-",
    "agent-",
    "decompose-",
    "chain-plan-",  # до chain-, чтобы не перехватить chain-plan
    "chain-",
    "autofix-",
    "plan-",
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Отчёты/журналы из .ai-out — статикой. Только localhost; .ai-out может
# содержать секреты (usage.jsonl, raw-ответы LLM). Позже — фильтр *.md.
if AI_OUT_DIR.is_dir():
    app.mount(
        "/ai-out",
        StaticFiles(directory=str(AI_OUT_DIR)),
        name="ai-out",
    )


def _escape_shell(text: str) -> str:
    """Экранирует текст для вставки в двойные кавычки shell."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _build_command(
    goal: str,
    path: str,
    mode: str,
    model: str,
    apply: bool,
    commit: bool,
    check_mode: str,
    max_cost_rub: str,
    advanced_flags: str,
    task_type: str = "agent",
    run_action: str = "",
    reverse_check: bool = False,
    chain_path: str = "",
) -> str:
    """Собирает строку команды ai-coder из полей формы."""
    path_val = path.strip() if path.strip() else "."

    # Ветка run: `ai-coder run <action> <path>`. У команды run нет флагов
    # --max-cost-rub и --commit, поэтому их не добавляем.
    if task_type == "run":
        parts: list[str] = ["ai-coder", "run", _escape_shell(run_action)]
        parts.append(path_val)
        if model.strip() and model.strip() != "default":
            parts.extend(["--model", model.strip()])
        if apply:
            parts.append("--apply")
        if check_mode == "dry-run":
            parts.append("--dry-run")
        if advanced_flags.strip():
            parts.append(advanced_flags.strip())
        return " ".join(parts)

    mode_val = mode.strip()

    if mode_val == "chain":
        # --chain <dir>: path передаётся на месте goal (hack в cli.py,
        # строка ~1477: если goal — директория, а есть --chain/--issue,
        # cli сам считает это path и обнуляет goal). goal НЕ используется.
        # Формат: ai-coder agent <path> --chain <dir> --tool-loop
        chain_val = chain_path.strip() or "issues"
        parts: list[str] = [
            "ai-coder",
            "agent",
            _escape_shell(path_val),
            "--chain",
            _escape_shell(chain_val),
            "--tool-loop",
        ]
    else:
        parts = ["ai-coder", "agent", f'"{_escape_shell(goal)}"']
        # path — всегда (второй позиционный аргумент agent_cmd).
        # Пустой path → "." (как дефолт CLI), иначе --tool-loop окажется
        # на месте path и Typer его не распознает.
        parts.append(path_val)
        if mode_val and mode_val != "plain":
            parts.append(mode_val if mode_val.startswith("--") else f"--{mode_val}")
    if model.strip() and model.strip() != "default":
        parts.extend(["--model", model.strip()])
    if apply:
        parts.append("--apply")
    if commit:
        parts.append("--commit")
    if check_mode == "dry-run":
        parts.append("--dry-run")
    elif check_mode == "dry-read":
        parts.append("--dry-read")
    if max_cost_rub.strip():
        parts.extend(["--max-cost-rub", max_cost_rub.strip()])
    if reverse_check:
        parts.append("--reverse-check")
    if advanced_flags.strip():
        parts.append(advanced_flags.strip())

    return " ".join(parts)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Главная страница панели."""
    # FastAPI >=0.108: request передаётся первым аргументом,
    # context — третьим. Старый вызов TemplateResponse("index.html", {"request": request})
    # в FastAPI 0.143+ падает с 500.
    return templates.TemplateResponse(request, "index.html", {})


@app.get("/docs/cli/help", response_class=HTMLResponse)
async def docs_cli_help_page(request: Request) -> HTMLResponse:
    """Справка (режимы, примеры) — под общим nav справочника."""
    return templates.TemplateResponse(request, "help.html", {})


@app.get("/help", response_class=HTMLResponse)
async def help_redirect() -> HTMLResponse:
    """Старый URL /help — редирект на /docs/cli/help."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/docs/cli/help", status_code=301)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health-check."""
    return {"status": "ok"}


@app.post("/build", response_class=HTMLResponse)
async def build(
    goal: str = Form(""),
    path: str = Form(""),
    mode: str = Form("plain"),
    model: str = Form("default"),
    apply: bool = Form(False),
    commit: bool = Form(False),
    check_mode: str = Form("normal"),
    max_cost_rub: str = Form(""),
    advanced_flags: str = Form(""),
    task_type: str = Form("agent"),
    run_action: str = Form(""),
    reverse_check: bool = Form(False),
    chain_path: str = Form(""),
) -> HTMLResponse:
    """Собирает команду из формы и возвращает её как <pre>-фрагмент."""
    command = _build_command(
        goal=goal,
        path=path,
        mode=mode,
        model=model,
        apply=apply,
        commit=commit,
        check_mode=check_mode,
        max_cost_rub=max_cost_rub,
        advanced_flags=advanced_flags,
        task_type=task_type,
        run_action=run_action,
        reverse_check=reverse_check,
        chain_path=chain_path,
    )
    return HTMLResponse(
        f'<pre id="command-output" class="command-output">{html_escape(command)}</pre>'
    )


def _build_argv(
    goal: str,
    path: str,
    mode: str,
    model: str,
    apply: bool,
    commit: bool,
    check_mode: str,
    max_cost_rub: str,
    advanced_flags: str,
    task_type: str = "agent",
    run_action: str = "",
    reverse_check: bool = False,
    chain_path: str = "",
) -> list[str]:
    """Собирает argv для запуска агента через python -m ai_coder.cli."""
    command = _build_command(
        goal=goal,
        path=path,
        mode=mode,
        model=model,
        apply=apply,
        commit=commit,
        check_mode=check_mode,
        max_cost_rub=max_cost_rub,
        advanced_flags=advanced_flags,
        task_type=task_type,
        run_action=run_action,
        reverse_check=reverse_check,
        chain_path=chain_path,
    )
    parts = shlex.split(command)
    # parts[0] == "ai-coder" -> заменяем на sys.executable -m ai_coder.cli
    return [sys.executable, "-m", "ai_coder.cli", *parts[1:]]


def _stream_process(run_id: str, proc: subprocess.Popen) -> Iterator[str]:
    """Генератор SSE-строк с выводом процесса."""
    yield f"data: run_id: {run_id}\n\n"
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                yield f"data: {line.rstrip(chr(10))}\n\n"
    finally:
        proc.wait()
        RUNNING.pop(run_id, None)
        yield f"data: [exit {proc.returncode}]\n\n"


def _collect_docs_cli() -> list[dict]:
    """Список .md файлов в docs/cli/ (README первым)."""
    if not DOCS_CLI_DIR.is_dir():
        return []
    items: list[dict] = []
    for f in sorted(DOCS_CLI_DIR.glob("*.md")):
        page = f.stem
        title = f.name
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0].strip()
            if first.startswith("# "):
                title = first[2:].strip()
        except (OSError, IndexError):
            pass
        items.append({"page": page, "title": title, "filename": f.name})
    items.sort(key=lambda x: (x["page"] != "README", x["page"].lower()))
    return items


def _safe_docs_cli_path(page: str) -> Path | None:
    """docs/cli/<page>.md, если внутри DOCS_CLI_DIR (без слэшей)."""
    if not page or "/" in page or "\\" in page or page.startswith("."):
        return None
    if not re.match(r"^[A-Za-z0-9_.-]+$", page):
        return None
    f = (DOCS_CLI_DIR / f"{page}.md").resolve()
    try:
        f.relative_to(DOCS_CLI_DIR.resolve())
    except ValueError:
        return None
    if not f.is_file():
        return None
    return f


def _render_docs_cli_md(md_text: str) -> str:
    """Рендер markdown + правка локальных ссылок .md → /docs/cli/<page>."""
    html = markdown.markdown(
        md_text,
        extensions=["fenced_code", "tables", "sane_lists"],
    )

    def _fix(match: re.Match) -> str:
        href = match.group(1)
        if href.startswith(("http://", "https://", "#", "/", "../", "mailto:")):
            return match.group(0)
        page = href[:-3] if href.endswith(".md") else href
        if "/" in page:
            return match.group(0)
        return f'href="/docs/cli/{page}"'

    return re.sub(r'href="([^"]+)"', _fix, html)


@app.get("/docs/cli", response_class=HTMLResponse)
async def docs_cli_index(request: Request) -> HTMLResponse:
    """Справочник: рендер README.md + список файлов."""
    items = _collect_docs_cli()
    if not items:
        return HTMLResponse("<h1>docs/cli/ не найден</h1>", status_code=404)
    readme = _safe_docs_cli_path("README") or _safe_docs_cli_path(items[0]["page"])
    content = ""
    if readme is not None:
        content = _render_docs_cli_md(readme.read_text(encoding="utf-8"))
    return templates.TemplateResponse(
        request,
        "docs_cli.html",
        {
            "items": items,
            "current": "README",
            "current_title": "Справочник команд ai-coder",
            "content": content,
        },
    )


@app.get("/docs/cli/{page}", response_class=HTMLResponse)
async def docs_cli_page(request: Request, page: str) -> HTMLResponse:
    """Рендер docs/cli/<page>.md."""
    items = _collect_docs_cli()
    f = _safe_docs_cli_path(page)
    if f is None:
        return HTMLResponse("<h1>Страница не найдена</h1>", status_code=404)
    content = _render_docs_cli_md(f.read_text(encoding="utf-8"))
    title = next((x["title"] for x in items if x["page"] == page), page)
    return templates.TemplateResponse(
        request,
        "docs_cli.html",
        {
            "items": items,
            "current": page,
            "current_title": title,
            "content": content,
        },
    )


@app.post("/diff")
async def diff(path: str = Form("")) -> dict[str, str]:
    """Возвращает `git diff HEAD` в указанном каталоге (project_root)."""
    root = Path(path.strip() or ".").resolve()
    if not root.is_dir():
        return {"diff": "", "error": f"каталог не найден: {root}"}
    try:
        proc = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"diff": "", "error": f"git diff не выполнился: {exc}"}
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or f"exit {proc.returncode}"
        return {"diff": "", "error": err}
    return {"diff": proc.stdout or ""}


@app.post("/run")
async def run(
    goal: str = Form(""),
    path: str = Form(""),
    mode: str = Form("plain"),
    model: str = Form("default"),
    apply: bool = Form(False),
    commit: bool = Form(False),
    check_mode: str = Form("normal"),
    max_cost_rub: str = Form(""),
    advanced_flags: str = Form(""),
    task_type: str = Form("agent"),
    run_action: str = Form(""),
    reverse_check: bool = Form(False),
    chain_path: str = Form(""),
) -> StreamingResponse:
    """Запускает агента и стримит его вывод в формате SSE."""
    run_id = uuid.uuid4().hex
    argv = _build_argv(
        goal=goal,
        path=path,
        mode=mode,
        model=model,
        apply=apply,
        commit=commit,
        check_mode=check_mode,
        max_cost_rub=max_cost_rub,
        advanced_flags=advanced_flags,
        task_type=task_type,
        run_action=run_action,
        reverse_check=reverse_check,
        chain_path=chain_path,
    )
    proc: subprocess.Popen = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    RUNNING[run_id] = proc
    return StreamingResponse(
        _stream_process(run_id, proc),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/stop/{run_id}")
async def stop(run_id: str) -> dict[str, bool]:
    """Останавливает запущенный процесс по SIGTERM."""
    proc = RUNNING.get(run_id)
    if proc is not None and proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
    return {"ok": True}


def _extract_success(meta: dict[str, str]) -> str:
    """
    Нормализует признак успеха из метаданных report.md.

    Источники (в порядке приоритета):
      1. "Успех" — True/False (tool-loop, autofix).
      2. "Статус" — ✅ успех / ❌ неуспех (decompose).
      3. "Причина остановки" — completed / error / max_iterations (agent).

    Возвращает 'True' / 'False' / '—'.
    """
    # 1. Явное поле "Успех"
    raw = meta.get("Успех", "").strip()
    low = raw.lower()
    if low in ("true", "success", "ok", "✅", "yes"):
        return "True"
    if low in ("false", "failed", "fail", "❌", "no"):
        return "False"

    # 2. Поле "Статус" (decompose) — содержит эмодзи
    status = meta.get("Статус", "").strip()
    if "✅" in status:
        return "True"
    if "❌" in status:
        return "False"

    # 3. Fallback по "Причина остановки" (agent).
    # Реальные значения из 83 журналов:
    #   completed (59), max_iterations (8), error (4), max_cost (3),
    #   cancelled (2), parse_error (2), preview_only (2).
    reason = meta.get("Причина остановки", "").strip().lower()
    if reason in ("completed", "success", "finish", "finished"):
        return "True"
    if reason in (
        "error",
        "failed",
        "cancelled",
        "canceled",
        "max_iterations",
        "max_iterations_reached",
        "max_cost",
        "parse_error",
    ):
        return "False"
    # preview_only — не провал, не успех: ничего не выполнялось.
    if reason == "preview_only":
        return "preview"

    return "—"


def _round_cost(raw: str) -> str:
    """
    Округляет стоимость из report.md до 4 знаков.

    Вход: '0.060524 RUB' → '0.0605 RUB'.
    Если не удалось распарсить — возвращает исходную строку.
    """
    if not raw or raw == "—":
        return raw
    parts = raw.split(maxsplit=1)
    try:
        num = float(parts[0])
    except (ValueError, IndexError):
        return raw
    rounded = f"{num:.4f}"
    return f"{rounded} {parts[1]}" if len(parts) > 1 else rounded


def _parse_report_meta(report_path: Path) -> dict[str, str]:
    """
    Грубый парсер метаданных из report.md.

    Ищет строки вида `- **Ключ:** значение`. Достаточно для
    Успех / Стоимость / Итераций / Причина остановки.
    """
    meta: dict[str, str] = {}
    try:
        text = report_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return meta
    # Первые ~40 строк — метаданные всегда в шапке.
    # Поддерживаем два формата:
    #   - **Ключ:** значение   (tool-loop, autofix)
    #   **Ключ:** значение      (decompose)
    for line in text.splitlines()[:40]:
        m = re.match(
            r"-?\s*\*\*(?P<key>[^:*]+):\*\*\s*(?P<val>.*)",
            line,
        )
        if m:
            meta[m.group("key").strip()] = m.group("val").strip()
    return meta


def _is_journal_dir(name: str) -> bool:
    """True, если имя директории похоже на журнал агента."""
    return name.startswith(JOURNAL_PREFIXES)


def _collect_journals() -> list[dict[str, str]]:
    """
    Обходит .ai-out/<project>/<journal>/report.md и собирает метаданные.

    Сортировка — по mtime (свежие сверху). Возвращает список словарей
    с ключами: project, journal, mtime, mtime_iso, url, success,
    cost, iterations, reason, title.
    """
    result: list[dict[str, str]] = []
    if not AI_OUT_DIR.is_dir():
        return result
    root = AI_OUT_DIR.resolve()
    for project_dir in sorted(AI_OUT_DIR.iterdir()):
        if not project_dir.is_dir():
            continue
        for journal_dir in sorted(project_dir.iterdir()):
            if not journal_dir.is_dir():
                continue
            if not _is_journal_dir(journal_dir.name):
                continue
            report = journal_dir / "report.md"
            if not report.is_file():
                continue
            try:
                # Защита от symlink-выхода за пределы AI_OUT_DIR.
                report.resolve().relative_to(root)
            except ValueError:
                continue
            meta = _parse_report_meta(report)
            # У agent-* поля "Стоимость" нет — есть "Стоимость всего".
            cost_raw = meta.get("Стоимость") or meta.get("Стоимость всего") or "—"
            cost = _round_cost(cost_raw)
            mtime = report.stat().st_mtime
            # Первая строка report.md — заголовок.
            try:
                first_line = report.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            except (OSError, IndexError):
                first_line = ""
            title = first_line.lstrip("# ").strip()
            result.append(
                {
                    "project": project_dir.name,
                    "journal": journal_dir.name,
                    "mtime": mtime,
                    "mtime_iso": datetime.fromtimestamp(mtime, tz=timezone.utc)
                    .astimezone()
                    .strftime("%Y-%m-%d %H:%M"),
                    "url": f"/reports/{project_dir.name}/{journal_dir.name}",
                    "success": _extract_success(meta),
                    "cost": cost,
                    "iterations": meta.get("Итераций", "—"),
                    "reason": meta.get("Причина остановки", "—"),
                    "title": title,
                }
            )
    result.sort(key=lambda x: x["mtime"], reverse=True)
    return result


def _safe_report_path(project: str, journal: str) -> Path | None:
    """
    Возвращает путь к report.md, если он внутри AI_OUT_DIR.
    Иначе None (защита от path traversal).
    """
    base = (AI_OUT_DIR / project / journal).resolve()
    try:
        base.relative_to(AI_OUT_DIR.resolve())
    except ValueError:
        return None
    report_path = base / "report.md"
    if not report_path.is_file():
        return None
    return report_path


def _collect_stats() -> dict:
    """
    Агрегирует usage.jsonl для графиков.

    Возвращает:
      {
        "summary": {total_rub, total_requests, total_tokens, days},
        "by_day": [{date, cost_rub, requests}, ...],
        "by_model": [{model, cost_rub, requests}, ...],
        "by_action": [{action, cost_rub, requests}, ...],
      }
    Если usage.jsonl нет — пустые списки и нули.
    """
    import json

    empty = {
        "summary": {
            "total_rub": 0.0,
            "total_requests": 0,
            "total_tokens": 0,
            "days": 0,
        },
        "by_day": [],
        "by_model": [],
        "by_action": [],
    }
    if not USAGE_JSONL.is_file():
        return empty

    by_day: dict[str, dict[str, float]] = {}
    by_model: dict[str, dict[str, float]] = {}
    by_action: dict[str, dict[str, float]] = {}
    total_rub = 0.0
    total_tokens = 0
    total_requests = 0

    try:
        with USAGE_JSONL.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                cost = float(rec.get("cost_rub") or 0.0)
                tokens = int(rec.get("total_tokens") or 0)
                total_rub += cost
                total_tokens += tokens
                total_requests += 1

                ts = rec.get("ts_msk") or rec.get("ts_utc") or ""
                day = ts[:10] if len(ts) >= 10 else "—"
                model = rec.get("model") or "unknown"
                action_raw = rec.get("action") or "unknown"
                action = action_raw.split(":", 1)[0]

                for bucket, key in (
                    (by_day, day),
                    (by_model, model),
                    (by_action, action),
                ):
                    entry = bucket.setdefault(key, {"cost_rub": 0.0, "requests": 0})
                    entry["cost_rub"] += cost
                    entry["requests"] += 1
    except OSError:
        return empty

    def _to_list(bucket: dict[str, dict[str, float]], key_name: str) -> list[dict]:
        items = [
            {
                key_name: k,
                "cost_rub": round(v["cost_rub"], 4),
                "requests": v["requests"],
            }
            for k, v in bucket.items()
        ]
        # Сортировка: дни — хронологически, остальные — по убыванию стоимости.
        if key_name == "date":
            items.sort(key=lambda x: x["date"])
        else:
            items.sort(key=lambda x: x["cost_rub"], reverse=True)
        return items

    return {
        "summary": {
            "total_rub": round(total_rub, 2),
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "days": len(by_day),
        },
        "by_day": _to_list(by_day, "date"),
        "by_model": _to_list(by_model, "model"),
        "by_action": _to_list(by_action, "action"),
    }


@app.get("/stats/data")
async def stats_data() -> dict:
    """JSON с агрегатами usage.jsonl (для Chart.js)."""
    return _collect_stats()


@app.get("/stats", response_class=HTMLResponse)
async def stats_view(request: Request) -> HTMLResponse:
    """Страница со графиками расходов (Chart.js)."""
    return templates.TemplateResponse(request, "stats.html", {})


@app.get("/reports", response_class=HTMLResponse)
async def reports_list(request: Request) -> HTMLResponse:
    """Список всех журналов из .ai-out (свежие сверху)."""
    journals = _collect_journals()
    return templates.TemplateResponse(
        request,
        "reports.html",
        {"journals": journals},
    )


@app.get("/reports/{project}/{journal}", response_class=HTMLResponse)
async def report_view(request: Request, project: str, journal: str) -> HTMLResponse:
    """Рендер report.md в HTML (markdown → HTML, тёмная тема)."""
    report_path = _safe_report_path(project, journal)
    if report_path is None:
        return HTMLResponse("<h1>Отчёт не найден</h1>", status_code=404)
    md_text = report_path.read_text(encoding="utf-8")
    html = markdown.markdown(
        md_text,
        extensions=["fenced_code", "tables", "sane_lists"],
    )
    return templates.TemplateResponse(
        request,
        "report.html",
        {
            "content": html,
            "project": project,
            "journal": journal,
        },
    )
