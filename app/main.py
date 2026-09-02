"""Kevil Studio — servidor local.

Arranca con:  python run.py
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from app import bootstrap
from app.api import ROUTERS
from app.config import settings
from app.db import init_db, session_scope
from app.services import events, pipeline, scheduler  # noqa: F401  (registra los trabajos)
from app.services.queue import runner

WEB_DIR = Path(__file__).resolve().parent / "web"


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    init_db()
    bootstrap.run()
    runner.size = max(1, settings.workers)
    runner.start()
    scheduler.start()
    with session_scope() as session:
        events.log(session, "Kevil Studio en marcha", level="success", scope="sistema")
    try:
        yield
    finally:
        scheduler.stop()
        runner.stop()


app = FastAPI(
    title="Kevil Studio",
    description="De tus vídeos y directos de YouTube a TikTok, en automático.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in ROUTERS:
    app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_error(_request, exc: Exception):  # pragma: no cover
    return JSONResponse(status_code=500, content={"detail": str(exc)})


if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(WEB_DIR / "favicon.svg")
