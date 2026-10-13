"""FastAPI-приложение веб-панели ai-coder."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="ai-coder GUI")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
