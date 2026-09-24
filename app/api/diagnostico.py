"""Tareas con problemas y tu sesión de YouTube: lo que hace falta para arreglarlos."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Job, JobStatus, Video
from app.services import diagnostico, events
from app.services import youtube as youtube_service

router = APIRouter(prefix="/api", tags=["diagnóstico"])

# Un vídeo público de siempre para probar la sesión cuando no hay otro a mano.
VIDEO_DE_PRUEBA = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


# --------------------------------------------------------------------------
# Tareas con problemas
# --------------------------------------------------------------------------
class GrupoIn(BaseModel):
    tipo: str | None = None
    job_id: int | None = None


@router.get("/problemas")
def problemas(db: Session = Depends(get_db)):
    return diagnostico.problemas(db)


@router.post("/problemas/reintentar")
def reintentar(body: GrupoIn, db: Session = Depends(get_db)):
    if body.job_id:
        job = db.get(Job, body.job_id)
        if not job:
            raise HTTPException(404, "Tarea no encontrada")
        diagnostico.reintentar(db, job)
        cuantos = 1
    else:
        cuantos = diagnostico.reintentar_grupo(db, body.tipo)
    db.commit()
    return {"reintentados": cuantos}


@router.post("/problemas/descartar")
def descartar(body: GrupoIn, db: Session = Depends(get_db)):
    cuantos = diagnostico.descartar_grupo(db, body.tipo)
    db.commit()
    return {"descartados": cuantos}


@router.get("/diagnostico")
def diagnosticar(texto: str):
    """Explica un error suelto (el de un vídeo o un clip)."""
    return diagnostico.diagnosticar(texto)


# --------------------------------------------------------------------------
# Tu sesión de YouTube
# --------------------------------------------------------------------------
def _estado_sesion() -> dict:
    from app.config import settings

    modo = (settings.youtube_cookies or "auto").lower()
    archivo = youtube_service.ruta_cookies_txt()
    instalados = youtube_service.navegadores_instalados()
    if archivo.is_file() and modo in {"auto", "archivo"}:
        usando = "Tu archivo cookies.txt"
    elif modo in youtube_service.NOMBRES_NAVEGADOR:
        usando = f"La sesión de {youtube_service.NOMBRES_NAVEGADOR[modo]}"
    elif modo == "no":
        usando = "Ninguna (desactivado)"
    else:
        usando = "Ninguna todavía: se probará sola si YouTube la pide"
    return {
        "modo": modo,
        "usando": usando,
        "archivo": archivo.is_file(),
        "navegadores": [
            {"id": n, "nombre": youtube_service.NOMBRES_NAVEGADOR[n]} for n in instalados
        ],
        "motor_js": bool(youtube_service.motores_js()),
    }


@router.get("/youtube/sesion")
def sesion():
    return _estado_sesion()


class ProbarIn(BaseModel):
    url: str | None = None
    navegador: str | None = None


def _reintentar_lo_de_youtube(db: Session) -> int:
    """Con la sesión ya puesta, lo que falló por el «robot» vuelve a la cola."""
    cuantos = 0
    for tipo in ("robot", "privado", "limite"):
        cuantos += diagnostico.reintentar_grupo(db, tipo)
    # y lo que estaba esperando su reintento de cada hora, ya mismo
    from app.models import utcnow

    for job in db.scalars(
        select(Job).where(Job.status == JobStatus.pending.value, Job.run_at > utcnow())
    ).all():
        if (job.payload or {}).get("reintentos_robot"):
            job.run_at = utcnow()
            cuantos += 1
    return cuantos


@router.post("/youtube/sesion/probar")
def probar(body: ProbarIn, db: Session = Depends(get_db)):
    """Prueba tus navegadores (o uno) hasta dar con una sesión que YouTube acepte."""
    url = (body.url or "").strip()
    if not url:
        # mejor un vídeo tuyo que haya fallado: es el que de verdad hay que bajar
        video = db.scalars(
            select(Video).where(Video.error != "").order_by(Video.id.desc()).limit(1)
        ).first() or db.scalars(select(Video).order_by(Video.id.desc()).limit(1)).first()
        url = video.url if video and video.url.startswith("http") else VIDEO_DE_PRUEBA
    navegadores = [body.navegador] if body.navegador else None
    if navegadores == [] or (not navegadores and not youtube_service.navegadores_instalados()):
        return {
            "ok": False,
            "intentos": [],
            "mensaje": "No se encuentra ningún navegador con perfil en este ordenador. "
                       "Sube un cookies.txt.",
            "estado": _estado_sesion(),
        }
    try:
        resultado = youtube_service.probar_navegadores(url, navegadores)
    except youtube_service.YouTubeError as exc:
        raise HTTPException(400, str(exc)) from exc

    reintentados = 0
    if resultado["ok"]:
        reintentados = _reintentar_lo_de_youtube(db)
        nombre = youtube_service.NOMBRES_NAVEGADOR.get(resultado["navegador"], resultado["navegador"])
        events.log(db, f"Kevil usará tu sesión de YouTube de {nombre}", level="success",
                   scope="youtube")
        db.commit()
    return {
        **resultado,
        "reintentados": reintentados,
        "mensaje": (
            f"Listo: se usará tu sesión de {youtube_service.NOMBRES_NAVEGADOR.get(resultado['navegador'], '')}."
            + (f" {reintentados} tarea(s) vuelven a la cola." if reintentados else "")
            if resultado["ok"]
            else "Ningún navegador ha servido. Mira abajo por qué y, si hace falta, sube un cookies.txt."
        ),
        "estado": _estado_sesion(),
    }


@router.post("/youtube/sesion/archivo")
async def subir_cookies(archivo: UploadFile = File(...), db: Session = Depends(get_db)):
    contenido = (await archivo.read())[: 2 * 1024 * 1024]
    texto = contenido.decode("utf-8", errors="ignore")
    if not youtube_service.cookies_txt_valido(texto):
        raise HTTPException(
            400,
            "Ese archivo no trae las cookies de YouTube. Exporta con «Get cookies.txt "
            "LOCALLY» estando en youtube.com (con tu sesión iniciada).",
        )
    destino = youtube_service.ruta_cookies_txt()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    youtube_service.guardar_modo_cookies("archivo")
    reintentados = _reintentar_lo_de_youtube(db)
    events.log(db, "Cookies de YouTube guardadas (cookies.txt)", level="success", scope="youtube")
    db.commit()
    return {"ok": True, "reintentados": reintentados, "estado": _estado_sesion()}


@router.delete("/youtube/sesion/archivo")
def borrar_cookies():
    youtube_service.ruta_cookies_txt().unlink(missing_ok=True)
    youtube_service.guardar_modo_cookies("auto")
    return _estado_sesion()


class ModoIn(BaseModel):
    modo: str


@router.post("/youtube/sesion/modo")
def elegir_modo(body: ModoIn):
    modo = body.modo.strip().lower()
    if modo not in {"auto", "no", "archivo", *youtube_service.NOMBRES_NAVEGADOR}:
        raise HTTPException(400, "Opción no válida")
    youtube_service.guardar_modo_cookies(modo)
    return _estado_sesion()
