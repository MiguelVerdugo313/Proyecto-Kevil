"""Kevil Studio — servidor local.

Arranca con:  python run.py
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import bootstrap
from app.api import ROUTERS
from app.config import settings
from app.db import init_db, session_scope
from app.rutas import raiz_recursos
from app.version import VERSION
from app.services import (  # noqa: F401  (registran trabajos)
    events, pausa, pipeline, repetidos, scheduler, studio,
)
from app.services.queue import runner

# Dentro del .exe la interfaz vive en la carpeta que descomprime PyInstaller
WEB_DIR = raiz_recursos() / "app" / "web"
if not WEB_DIR.is_dir():
    WEB_DIR = Path(__file__).resolve().parent / "web"


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.ensure_dirs()
    init_db()
    bootstrap.run()
    with session_scope() as session:
        pausa.cargar(session)       # si se cerró en pausa, se abre en pausa
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
    version=VERSION,
    lifespan=lifespan,
)

# Nombres con los que se llega a este ordenador (y el del cliente de pruebas)
LOCALES = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}


def _nombre(valor: str) -> str:
    """«127.0.0.1:8756» → «127.0.0.1»; «[::1]:8756» → «[::1]»."""
    valor = (valor or "").strip().lower()
    if valor.startswith("["):
        return valor.split("]")[0] + "]"
    return valor.rsplit(":", 1)[0] if valor.count(":") == 1 else valor


@app.middleware("http")
async def solo_desde_kevil(request, call_next):
    """La API sólo atiende a la ventana de Kevil.

    El servidor escucha en tu propio ordenador, y cualquier página que abras en
    el navegador podría intentar hablar con él: leer tus datos, publicar,
    borrar… Se corta de dos maneras:

    * el nombre con el que se llega tiene que ser el del propio equipo (así no
      sirve el truco de apuntar un dominio ajeno a 127.0.0.1);
    * lo que cambia algo (POST, PUT, PATCH, DELETE) sólo se acepta desde la
      propia interfaz de Kevil, no desde otra web.

    Las vueltas de TikTok y de Google al conectar son visitas normales (GET)
    a la dirección del equipo, así que siguen funcionando.
    """
    abierto = settings.host not in LOCALES          # lo abriste a la red a propósito
    if not abierto and _nombre(request.headers.get("host", "")) not in LOCALES:
        return JSONResponse(status_code=403, content={"detail": "Acceso no permitido"})
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origen = request.headers.get("origin")
        if origen is not None:
            from urllib.parse import urlsplit

            partes = urlsplit(origen)
            propio = _nombre(request.headers.get("host", ""))
            if partes.hostname is None or (
                _nombre(partes.netloc) not in LOCALES | {propio}
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Sólo la ventana de Kevil puede hacer cambios"},
                )
    return await call_next(request)

for router in ROUTERS:
    app.include_router(router)


@app.exception_handler(Exception)
async def unhandled_error(_request, exc: Exception):  # pragma: no cover
    return JSONResponse(status_code=500, content={"detail": str(exc)})


class SinCache(StaticFiles):
    """Archivos de la interfaz sin guardar en caché.

    La ventana es un Chromium con perfil propio y se queda con el código
    anterior durante días: se actualiza el programa y se sigue viendo la
    pantalla vieja. Aquí no compensa cachear nada —los archivos están en el
    disco de al lado— así que se sirven siempre frescos.
    """

    def file_response(self, *args, **kwargs):  # type: ignore[override]
        respuesta = super().file_response(*args, **kwargs)
        respuesta.headers["Cache-Control"] = "no-store, must-revalidate"
        return respuesta


if WEB_DIR.exists():
    app.mount("/static", SinCache(directory=WEB_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        # La página se sirve sin caché y con la versión pegada a los archivos de
        # estilo y de código. Así, al actualizar el programa, la ventana no se
        # queda enseñando la interfaz anterior.
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            html.replace("__V__", VERSION),
            headers={"Cache-Control": "no-store, must-revalidate"},
        )

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        return FileResponse(WEB_DIR / "favicon.svg")

    @app.get("/favicon.png", include_in_schema=False)
    def favicon_png():
        # Es el que acaba en la barra de tareas cuando Kevil se abre como app
        return FileResponse(WEB_DIR / "favicon.png")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon_ico():
        return FileResponse(WEB_DIR / "img" / "kevil.ico")
