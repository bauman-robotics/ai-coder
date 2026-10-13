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
) -> str:
    """Собирает строку команды ai-coder agent из полей формы."""
    parts: list[str] = ["ai-coder", "agent", f'"{_escape_shell(goal)}"']

    # path — всегда (второй позиционный аргумент agent_cmd).
    # Пустой path → "." (как дефолт CLI), иначе --tool-loop окажется
    # на месте path и Typer его не распознает.
    parts.append(path.strip() if path.strip() else ".")
    if mode.strip() and mode.strip() != "plain":
        mode_val = mode.strip()
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
    # Только первые ~30 строк — метаданные всегда в шапке.
    for line in text.splitlines()[:30]:
        m = re.match(r"-\s*\*\*(?P<key>[^:*]+):\*\*\s*(?P<val>.*)", line)
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
                    "success": meta.get("Успех", "—"),
                    "cost": meta.get("Стоимость", "—"),
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
