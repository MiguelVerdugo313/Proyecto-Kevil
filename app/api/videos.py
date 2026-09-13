"""Vídeos originales: importar, descargar y cortar."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.common import video_to_dict
from app.db import get_db
from app.models import Video, VideoStatus
from app.services import events
from app.services import youtube as youtube_service
from app.services.queue import enqueue

router = APIRouter(prefix="/api/videos", tags=["vídeos"])


class ImportIn(BaseModel):
    url: str
    flow_id: int | None = None
    start_now: bool = True


class ProcessIn(BaseModel):
    flow_id: int | None = None


@router.get("")
def list_videos(
    status: str | None = None,
    q: str | None = None,
    source_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = select(Video).order_by(Video.created_at.desc()).limit(max(1, min(500, limit)))
    if status:
        query = query.where(Video.status == status)
    if source_id:
        query = query.where(Video.source_id == source_id)
    if q:
        needle = f"%{q.lower()}%"
        query = query.where(or_(Video.title.ilike(needle), Video.external_id.ilike(needle)))
    return [video_to_dict(v) for v in db.scalars(query).all()]


@router.get("/{video_id}")
def get_video(video_id: int, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    return video_to_dict(video, with_transcript=True)


@router.post("/import")
def import_video(body: ImportIn, db: Session = Depends(get_db)):
    try:
        info = youtube_service.fetch_video_info(body.url)
    except Exception as exc:
        raise HTTPException(400, f"No se ha podido leer el vídeo: {exc}") from exc

    video = db.scalars(
        select(Video).where(Video.external_id == info["external_id"])
    ).first()
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

    if body.start_now:
        video.status = VideoStatus.queued.value
        enqueue(
            db,
            "ingest",
            {"video_id": video.id, "flow_id": body.flow_id},
            priority=100,
            message=f"Descargar «{video.title[:60]}»",
        )
    events.log(db, f"Vídeo importado: {video.title[:70]}", level="info", scope="video")
    db.commit()
    return video_to_dict(video)


@router.post("/{video_id}/ingest")
def ingest_video(video_id: int, body: ProcessIn, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    video.status = VideoStatus.queued.value
    job = enqueue(
        db,
        "ingest",
        {"video_id": video.id, "flow_id": body.flow_id},
        priority=100,
        message=f"Descargar «{video.title[:60]}»",
    )
    db.commit()
    return {"job_id": job.id}


@router.post("/{video_id}/process")
def process_video(video_id: int, body: ProcessIn, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    if not video.local_path or not Path(video.local_path).exists():
        raise HTTPException(400, "El vídeo aún no está descargado.")
    job = enqueue(
        db,
        "process",
        {"video_id": video.id, "flow_id": body.flow_id},
        priority=100,
        message=f"Cortar «{video.title[:60]}»",
    )
    db.commit()
    return {"job_id": job.id}


@router.delete("/{video_id}")
def delete_video(video_id: int, delete_file: bool = False, db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Vídeo no encontrado")
    if delete_file and video.local_path:
        Path(video.local_path).unlink(missing_ok=True)
    db.delete(video)
    db.commit()
    return {"ok": True}
