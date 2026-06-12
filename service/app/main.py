"""Luna Marketplaces Service — main FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .database import init_db
from .routers.core import router as core_router
from .routers.plugins import router as plugins_router

STATIC_DIR = Path(__file__).parent.parent / "static"
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Luna Marketplaces",
    description="Plugin marketplace service for the Luna agent platform",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(core_router, prefix="/api")
app.include_router(plugins_router, prefix="/api")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request=request, name="app.html")


@app.get("/browse/{mp_slug}", response_class=HTMLResponse)
async def marketplace_catalog(request: Request, mp_slug: str):
    return templates.TemplateResponse(request=request, name="catalog.html")


@app.get("/browse/{mp_slug}/plugin/{plugin_name}", response_class=HTMLResponse)
async def plugin_detail(request: Request, mp_slug: str, plugin_name: str):
    return templates.TemplateResponse(request=request, name="plugin_detail.html")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "luna-marketplaces", "version": "0.1.0"}
