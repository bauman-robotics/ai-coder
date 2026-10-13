"""FastAPI-приложение веб-панели ai-coder."""

import shlex
import signal
import subprocess
import sys
import uuid
from collections.abc import Iterator
from html import escape as html_escape
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="ai-coder GUI")

# Реестр запущенных процессов: run_id -> Popen.
RUNNING: dict[str, subprocess.Popen] = {}

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
    dry_run: bool,
    max_cost_rub: str,
    advanced_flags: str,
) -> str:
    """Собирает строку команды ai-coder agent из полей формы."""
    parts: list[str] = ["ai-coder", "agent", f'"{_escape_shell(goal)}"']

    if path.strip():
        parts.append(path.strip())
    if mode.strip() and mode.strip() != "plain":
        mode_val = mode.strip()
        parts.append(mode_val if mode_val.startswith("--") else f"--{mode_val}")
    if model.strip() and model.strip() != "default":
        parts.extend(["--model", model.strip()])
    if apply:
        parts.append("--apply")
    if commit:
        parts.append("--commit")
    if dry_run:
        parts.append("--dry-run")
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
    dry_run: bool = Form(False),
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
        dry_run=dry_run,
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
    dry_run: bool,
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
        dry_run=dry_run,
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
    dry_run: bool = Form(False),
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
        dry_run=dry_run,
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
