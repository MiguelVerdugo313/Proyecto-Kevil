"""«Crear»: de un enlace o un archivo a clips, eligiendo cómo quedan.

Lo que eliges aquí (plantilla de rótulos, encuadre, limpieza, que la IA
elija) se guarda en el vídeo y manda sobre el flujo sólo para ese vídeo.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import video_to_dict
from app.config import settings
from app.db import get_db
from app.flow_schema import STEP_INDEX, normalize_steps, step_config, step_enabled
from app.models import Clip, ClipStatus, Flow, Job, Video, VideoStatus
from app.services import ai, events, plantillas, transcript
from app.services import youtube as youtube_service
from app.services.queue import enqueue

router = APIRouter(prefix="/api/crear", tags=["crear"])

# Lo que se puede cambiar desde «Crear», paso a paso, y de qué tipo es
PERMITIDOS: dict[str, dict[str, type]] = {
    "subtitles": {"template": str, "enabled": bool, "position_y": float, "font_size": int},
    "reframe": {"mode": str},
    "cleanup": {"remove_fillers": bool, "remove_silences": bool, "max_pause": float},
    "segment": {"ai_pick": bool, "min_duration": int, "max_duration": int, "max_clips": int},
}
ENCUADRES = {"blur", "smart", "crop", "split"}
EXTENSIONES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def limpiar_ajustes(ajustes: dict[str, Any] | None) -> dict[str, Any]:
    """Sólo lo permitido, con su tipo; lo raro se descarta sin error."""
    limpio: dict[str, Any] = {}
    for paso, campos in (ajustes or {}).items():
        tipos = PERMITIDOS.get(paso)
        if not tipos or not isinstance(campos, dict):
            continue
        bueno: dict[str, Any] = {}
        for campo, valor in campos.items():
            tipo = tipos.get(campo)
            if tipo is None or valor is None:
                continue
            try:
                bueno[campo] = bool(valor) if tipo is bool else tipo(valor)
            except (TypeError, ValueError):
                continue
        if bueno:
            limpio[paso] = bueno
    plantilla = (limpio.get("subtitles") or {}).get("template")
    if plantilla and not plantillas.existe(plantilla):
        limpio["subtitles"].pop("template")
    modo = (limpio.get("reframe") or {}).get("mode")
    if modo and modo not in ENCUADRES:
        limpio["reframe"].pop("mode")
    return {paso: campos for paso, campos in limpio.items() if campos}


def _flujo(db: Session, flow_id: int | None) -> Flow | None:
    if flow_id:
        return db.get(Flow, flow_id)
    return db.scalars(select(Flow).where(Flow.is_default.is_(True)).limit(1)).first() or \
        db.scalars(select(Flow).order_by(Flow.id).limit(1)).first()


# --------------------------------------------------------------------------
# Opciones de la pantalla
# --------------------------------------------------------------------------
@router.get("/opciones")
def opciones(flow_id: int | None = None, db: Session = Depends(get_db)):
    flujos = db.scalars(select(Flow).order_by(Flow.is_default.desc(), Flow.id)).all()
    flujo = _flujo(db, flow_id)
    pasos = normalize_steps(flujo.steps if flujo else [])
    rotulos = step_config(pasos, "subtitles")
    limpieza = step_config(pasos, "cleanup")
    momentos = step_config(pasos, "segment")
    encuadre = next(f for f in STEP_INDEX["reframe"]["fields"] if f["key"] == "mode")
    return {
        "flujos": [
            {"id": f.id, "name": f.name, "icon": f.icon, "is_default": f.is_default}
            for f in flujos
        ],
        "flow_id": flujo.id if flujo else None,
        "encuadres": encuadre["options"],
        "ia": ai.is_enabled(),
        "voz_en_la_nube": transcript.proveedor_en_la_nube() is not None,
        "valores": {
            "subtitles": {
                "enabled": step_enabled(pasos, "subtitles"),
                "template": rotulos.get("template", plantillas.POR_DEFECTO),
                "position_y": rotulos.get("position_y", 66),
            },
            "reframe": {"mode": step_config(pasos, "reframe").get("mode", "blur")},
            "cleanup": {
                "remove_fillers": bool(limpieza.get("remove_fillers")),
                "remove_silences": bool(limpieza.get("remove_silences")),
                "max_pause": float(limpieza.get("max_pause", 0.8) or 0.8),
            },
            "segment": {
                "ai_pick": bool(momentos.get("ai_pick", True)),
                "min_duration": momentos.get("min_duration", 30),
                "max_duration": momentos.get("max_duration", 90),
            },
        },
    }


# --------------------------------------------------------------------------
# Crear desde un enlace
# --------------------------------------------------------------------------
class EnlaceIn(BaseModel):
    url: str
    flow_id: int | None = None
    ajustes: dict[str, Any] | None = None
    contexto: str = ""


@router.post("/enlace")
def crear_desde_enlace(body: EnlaceIn, db: Session = Depends(get_db)):
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "Pega el enlace del vídeo de YouTube.")
    try:
        info = youtube_service.fetch_video_info(url)
    except Exception as exc:
        raise HTTPException(
            400, f"No se ha podido leer el vídeo: {youtube_service.traducir_error(exc)}"
        ) from exc

    video = db.scalars(select(Video).where(Video.external_id == info["external_id"])).first()
    if video is None:
        video = Video(
            external_id=info["external_id"],
            title=info["title"],
            description=info.get("description", ""),
            url=info["url"],
            thumbnail_url=info.get("thumbnail_url", ""),
            duration_s=info.get("duration_s") or 0,
            published_at=info.get("published_at"),
            was_live=bool(info.get("was_live")),
        )
        db.add(video)
        db.flush()
    video.ajustes = limpiar_ajustes(body.ajustes)
    if body.contexto.strip():
        video.contexto = body.contexto.strip()[:2000]
    flujo = _flujo(db, body.flow_id)
    video.status = VideoStatus.queued.value
    video.error = ""
    enqueue(
        db, "ingest", {"video_id": video.id, "flow_id": flujo.id if flujo else None},
        priority=90, message=f"Descargar «{video.title[:60]}»",
    )
    events.log(db, f"Creando clips de «{video.title[:70]}»", level="info", scope="video")
    db.commit()
    return video_to_dict(video)


# --------------------------------------------------------------------------
# Crear desde un archivo del PC
# --------------------------------------------------------------------------
@router.post("/archivo")
async def crear_desde_archivo(
    file: UploadFile = File(...),
    flow_id: int | None = Form(None),
    ajustes: str = Form("{}"),
    contexto: str = Form(""),
    db: Session = Depends(get_db),
):
    nombre = Path(file.filename or "video.mp4").name
    extension = Path(nombre).suffix.lower()
    if extension not in EXTENSIONES:
        raise HTTPException(
            400, f"Formato no admitido ({extension or 'sin extensión'}). "
            f"Usa uno de: {', '.join(sorted(EXTENSIONES))}",
        )
    try:
        elegidos = json.loads(ajustes or "{}")
    except ValueError:
        elegidos = {}

    carpeta = settings.sources_path
    carpeta.mkdir(parents=True, exist_ok=True)
    identificador = f"local-{uuid.uuid4().hex[:12]}"
    destino = carpeta / f"{identificador}{extension}"
    try:
        with destino.open("wb") as salida:
            shutil.copyfileobj(file.file, salida, length=4 * 1024 * 1024)
    finally:
        await file.close()
    if destino.stat().st_size < 1024:
        destino.unlink(missing_ok=True)
        raise HTTPException(400, "El archivo está vacío o no se ha subido bien.")

    flujo = _flujo(db, flow_id)
    video = Video(
        external_id=identificador,
        origin="local",
        title=Path(nombre).stem[:400],
        contexto=contexto.strip()[:2000],
        url="",
        local_path=str(destino),
        status=VideoStatus.queued.value,
        ajustes=limpiar_ajustes(elegidos if isinstance(elegidos, dict) else {}),
    )
    db.add(video)
    db.flush()
    enqueue(
        db, "analyze_local",
        {"video_id": video.id, "flow_id": flujo.id if flujo else None,
         "make_clips": True, "kit": False},
        priority=85, message=f"Analizar «{video.title[:50]}»",
    )
    events.log(db, f"Creando clips de «{video.title[:60]}» (archivo del PC)",
               level="info", scope="video")
    db.commit()
    return video_to_dict(video)


# --------------------------------------------------------------------------
# Progreso por pasos
# --------------------------------------------------------------------------
PASOS = (
    ("descargar", "Descargar"),
    ("transcribir", "Transcribir"),
    ("momentos", "Elegir los momentos"),
    ("montar", "Montar los clips"),
    ("listo", "Listo"),
)
LISTOS = {
    ClipStatus.rendered.value, ClipStatus.approved.value, ClipStatus.scheduled.value,
    ClipStatus.publishing.value, ClipStatus.published.value,
}


def _trabajos(db: Session, video: Video, clips: list[Clip]) -> dict[str, list[Job]]:
    ids = {c.id for c in clips}
    recientes = db.scalars(
        select(Job)
        .where(Job.kind.in_(["ingest", "analyze_local", "process", "render"]))
        .order_by(Job.id.desc())
        .limit(400)
    ).all()
    por_tipo: dict[str, list[Job]] = {}
    for job in recientes:
        payload = job.payload or {}
        if payload.get("video_id") == video.id or payload.get("clip_id") in ids:
            por_tipo.setdefault(job.kind, []).append(job)
    return por_tipo


@router.get("/{video_id}/progreso")
def progreso(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    clips = [c for c in video.clips if c.status != ClipStatus.rejected.value]
    trabajos = _trabajos(db, video, clips)
    activos = {"pending", "running"}

    def ultimo(*tipos: str) -> Job | None:
        candidatos = [j for t in tipos for j in trabajos.get(t, [])]
        return max(candidatos, key=lambda j: j.id) if candidatos else None

    bajada = ultimo("ingest", "analyze_local")
    corte = ultimo("process")
    renders = trabajos.get("render", [])
    montados = sum(1 for c in clips if c.status in LISTOS)
    fallidos = sum(1 for c in clips if c.status == ClipStatus.failed.value)
    palabras = len((video.transcript or {}).get("words") or [])
    tiene_voz = palabras > 0 or (video.transcript or {}).get("source") not in (None, "")

    estados: dict[str, dict[str, Any]] = {}
    descargado = bool(video.transcript) or video.status in {
        VideoStatus.ready.value, VideoStatus.processing.value, VideoStatus.done.value,
    } or bool(clips)
    if video.status == VideoStatus.error.value and not descargado:
        estados["descargar"] = {"estado": "error", "detalle": video.error[:200]}
    elif descargado:
        estados["descargar"] = {"estado": "hecho", "detalle": ""}
    elif bajada and bajada.status in activos:
        estados["descargar"] = {"estado": "ahora", "detalle": bajada.message,
                                "progreso": round(min(0.7, bajada.progress) / 0.7, 2)}
    else:
        estados["descargar"] = {"estado": "pendiente", "detalle": ""}

    if descargado and tiene_voz:
        estados["transcribir"] = {
            "estado": "hecho",
            "detalle": f"{palabras} palabras" if palabras else "sin voz que transcribir",
        }
    elif bajada and bajada.status in activos and bajada.progress >= 0.7:
        estados["transcribir"] = {"estado": "ahora", "detalle": bajada.message}
    else:
        estados["transcribir"] = {"estado": "pendiente", "detalle": ""}

    if clips:
        estados["momentos"] = {"estado": "hecho", "detalle": f"{len(clips)} momentos"}
    elif corte and corte.status in activos:
        estados["momentos"] = {"estado": "ahora", "detalle": corte.message,
                               "progreso": round(corte.progress, 2)}
    elif corte and corte.status == "failed":
        estados["momentos"] = {"estado": "error", "detalle": corte.error[:200]}
    elif video.status == VideoStatus.done.value:
        estados["momentos"] = {"estado": "hecho", "detalle": "ningún momento nuevo"}
    else:
        estados["momentos"] = {"estado": "pendiente", "detalle": ""}

    if clips and montados + fallidos >= len(clips):
        estados["montar"] = {
            "estado": "hecho",
            "detalle": f"{montados} de {len(clips)}" + (f" · {fallidos} con fallo" if fallidos else ""),
        }
    elif clips:
        en_marcha = next((j for j in renders if j.status == "running"), None)
        estados["montar"] = {
            "estado": "ahora",
            "detalle": f"{montados} de {len(clips)}" + (f" · {en_marcha.message}" if en_marcha else ""),
            "progreso": round(montados / len(clips), 2),
        }
    else:
        estados["montar"] = {"estado": "pendiente", "detalle": ""}

    terminado = (clips and montados + fallidos >= len(clips)) or (
        video.status == VideoStatus.done.value and not clips and estados["momentos"]["estado"] == "hecho"
    )
    estados["listo"] = {"estado": "hecho" if terminado else "pendiente", "detalle": ""}

    pasos = [{"clave": clave, "nombre": nombre, **estados[clave]} for clave, nombre in PASOS]
    if video.origin == "local":
        pasos[0]["nombre"] = "Analizar el archivo"
    hechos = sum(1 for p in pasos if p["estado"] == "hecho")
    ahora = next((p for p in pasos if p["estado"] == "ahora"), None)
    porcentaje = (hechos + (ahora or {}).get("progreso", 0)) / len(pasos)
    return {
        "video": video_to_dict(video),
        "pasos": pasos,
        "porcentaje": round(min(1.0, porcentaje), 3),
        "terminado": bool(terminado),
        "error": any(p["estado"] == "error" for p in pasos),
        "clips": len(clips),
        "montados": montados,
    }
