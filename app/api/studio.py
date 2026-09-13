"""Estudio: subir un vídeo propio y trabajar con su kit de publicación."""

from __future__ import annotations

import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import video_to_dict
from app.config import settings
from app.db import get_db
from app.models import Video, VideoStatus
from app.services import ai, events, seo
from app.services.queue import enqueue

router = APIRouter(prefix="/api", tags=["estudio"])

EXTENSIONES = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".mpg", ".mpeg", ".flv"}


class KitRequest(BaseModel):
    use_ai: bool = True
    ai_image: bool = False
    thumbnail_count: int = 3


class KitPatch(BaseModel):
    titles: list[str] | None = None
    description: str | None = None
    tags: list[str] | None = None
    hashtags: list[str] | None = None
    chosen_title: str | None = None
    chosen_thumbnail: int | None = None


def _safe_name(name: str) -> str:
    limpio = re.sub(r"[^\w.\- ]+", "", Path(name or "video").name).strip()
    return limpio[:80] or "video"


# --------------------------------------------------------------------------
# Subida
# --------------------------------------------------------------------------
@router.post("/videos/upload")
async def upload_video(
    file: UploadFile = File(...),
    title: str = Form(""),
    use_ai: bool = Form(True),
    ai_image: bool = Form(False),
    make_clips: bool = Form(False),
    db: Session = Depends(get_db),
):
    """Sube un vídeo desde tu ordenador y lanza todo el proceso."""
    nombre = _safe_name(file.filename or "video.mp4")
    extension = Path(nombre).suffix.lower()
    if extension not in EXTENSIONES:
        raise HTTPException(
            400,
            f"Formato no admitido ({extension or 'sin extensión'}). "
            f"Usa uno de: {', '.join(sorted(EXTENSIONES))}",
        )

    destino_dir = settings.sources_path
    destino_dir.mkdir(parents=True, exist_ok=True)
    identificador = f"local-{uuid.uuid4().hex[:12]}"
    destino = destino_dir / f"{identificador}{extension}"

    try:
        with destino.open("wb") as salida:
            shutil.copyfileobj(file.file, salida, length=4 * 1024 * 1024)
    finally:
        await file.close()

    tamano = destino.stat().st_size
    if tamano < 1024:
        destino.unlink(missing_ok=True)
        raise HTTPException(400, "El archivo está vacío o no se ha subido bien.")

    video = Video(
        external_id=identificador,
        origin="local",
        title=(title.strip() or Path(nombre).stem)[:400],
        url="",
        local_path=str(destino),
        status=VideoStatus.ready.value,
    )
    db.add(video)
    db.flush()

    enqueue(
        db,
        "analyze_local",
        {
            "video_id": video.id,
            "use_ai": bool(use_ai),
            "ai_image": bool(ai_image),
            "make_clips": bool(make_clips),
        },
        priority=85,
        message=f"Analizar «{video.title[:50]}»",
    )
    events.log(
        db,
        f"Vídeo subido: {video.title[:60]} ({tamano / 1024 / 1024:.1f} MB)",
        level="success",
        scope="estudio",
        data={"video_id": video.id},
    )
    db.commit()
    return video_to_dict(video)


# --------------------------------------------------------------------------
# Kit de publicación
# --------------------------------------------------------------------------
@router.get("/videos/{video_id}/kit")
def get_kit(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    kit = dict(video.kit or {})
    if kit:
        kit["review"] = seo.review_kit(kit, duration=float(video.duration_s or 0))
    return {
        "video": video_to_dict(video),
        "kit": kit,
        "ai": ai.status(),
        "has_transcript": bool((video.transcript or {}).get("words")),
    }


@router.post("/videos/{video_id}/kit")
def build_kit(video_id: int, body: KitRequest, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    job = enqueue(
        db,
        "build_kit",
        {
            "video_id": video.id,
            "use_ai": body.use_ai,
            "ai_image": body.ai_image,
            "thumbnail_count": max(1, min(5, body.thumbnail_count)),
        },
        priority=90,
        message=f"Kit de «{video.title[:50]}»",
        dedupe=False,
    )
    db.commit()
    return {"job_id": job.id}


@router.patch("/videos/{video_id}/kit")
def patch_kit(video_id: int, body: KitPatch, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    kit: dict[str, Any] = dict(video.kit or {})
    for campo, valor in body.model_dump(exclude_none=True).items():
        kit[campo] = valor
    kit["review"] = seo.review_kit(kit, duration=float(video.duration_s or 0))
    video.kit = kit
    db.commit()
    return {"kit": kit}


@router.get("/videos/{video_id}/kit/thumbnail/{index}")
def kit_thumbnail(
    video_id: int, index: int, download: bool = False, db: Session = Depends(get_db)
):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    miniaturas = (video.kit or {}).get("thumbnails") or []
    if index < 0 or index >= len(miniaturas):
        raise HTTPException(404, "Miniatura no encontrada")
    ruta = miniaturas[index].get("path", "")
    if not ruta or not os.path.exists(ruta):
        raise HTTPException(404, "El archivo de la miniatura ya no está")
    if download:
        seguro = _safe_name(video.title) or f"miniatura-{video_id}"
        return FileResponse(ruta, media_type="image/jpeg", filename=f"{seguro}-{index + 1}.jpg")
    return FileResponse(ruta, media_type="image/jpeg")


@router.get("/studio/videos")
def studio_videos(limit: int = 40, db: Session = Depends(get_db)):
    """Vídeos con kit o subidos por ti, que es lo que interesa en el estudio."""
    videos = db.scalars(
        select(Video).order_by(Video.created_at.desc()).limit(max(1, min(200, limit)))
    ).all()
    salida = []
    for video in videos:
        kit = video.kit or {}
        salida.append(
            {
                **video_to_dict(video),
                "origin": video.origin,
                "has_kit": bool(kit),
                "kit_titles": (kit.get("titles") or [])[:1],
                "kit_thumbnails": len(kit.get("thumbnails") or []),
                "kit_generated_by": kit.get("generated_by", ""),
            }
        )
    return salida
