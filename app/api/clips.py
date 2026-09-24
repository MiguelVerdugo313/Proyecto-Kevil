"""Clips verticales: revisión, edición, render y aprobación."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import clip_to_dict, naive_utc
from app.db import get_db
from app.models import Account, Clip, ClipStatus, Post, PostStatus
from app.services import events, pipeline, storage
from app.services.queue import enqueue

router = APIRouter(prefix="/api/clips", tags=["clips"])

CHUNK = 512 * 1024


class ClipPatch(BaseModel):
    title: str | None = None
    hook: str | None = None
    caption: str | None = None
    hashtags: list[str] | None = None
    start_s: float | None = None
    end_s: float | None = None
    status: str | None = None
    reframe: dict[str, Any] | None = None


class DestinoIn(BaseModel):
    account_id: int
    scheduled_at: datetime | None = None
    slot_reason: str = ""


class ApproveIn(BaseModel):
    account_id: int | None = None
    scheduled_at: datetime | None = None
    # la hora la propuso el motor y no se ha tocado: sigue siendo «suya»
    slot_reason: str = ""
    # varias cuentas a la vez (TikTok y Shorts), cada una con su hora
    destinos: list[DestinoIn] = []


@router.get("")
def list_clips(
    status: str | None = None,
    video_id: int | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    query = (
        select(Clip)
        .order_by(Clip.created_at.desc(), Clip.index)
        .limit(max(1, min(500, limit)))
    )
    if status:
        query = query.where(Clip.status == status)
    if video_id:
        query = query.where(Clip.video_id == video_id)
    return [clip_to_dict(c) for c in db.scalars(query).all()]


@router.get("/{clip_id}")
def get_clip(clip_id: int, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(404, "Clip no encontrado")
    return clip_to_dict(clip, with_words=True)


@router.patch("/{clip_id}")
def patch_clip(clip_id: int, body: ClipPatch, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(404, "Clip no encontrado")

    data = body.model_dump(exclude_none=True)
    reframe = data.pop("reframe", None)
    timing_changed = False

    for field, value in data.items():
        if field in {"start_s", "end_s"} and abs(getattr(clip, field) - float(value)) > 0.01:
            timing_changed = True
        setattr(clip, field, value)

    if reframe:
        config = dict(clip.render_config or {})
        config["reframe"] = {**(config.get("reframe") or {}), **reframe}
        clip.render_config = config
        timing_changed = True

    if clip.end_s <= clip.start_s:
        raise HTTPException(400, "El final debe ser posterior al inicio.")

    if timing_changed and clip.status in {
        ClipStatus.rendered.value,
        ClipStatus.approved.value,
        ClipStatus.failed.value,
    }:
        clip.status = ClipStatus.draft.value  # habrá que volver a renderizar

    db.commit()
    return clip_to_dict(clip)


@router.post("/{clip_id}/render")
def render_clip(clip_id: int, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(404, "Clip no encontrado")
    job = enqueue(
        db, "render", {"clip_id": clip.id}, priority=90, message=f"Renderizar #{clip.id}"
    )
    db.commit()
    return {"job_id": job.id}


@router.post("/{clip_id}/approve")
def approve_clip(clip_id: int, body: ApproveIn, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(404, "Clip no encontrado")

    from app.flow_schema import step_config

    flow = pipeline.resolve_flow(db, clip.flow_id)
    schedule_config = step_config(flow.steps, "schedule")
    publish_config = step_config(flow.steps, "publish")

    # Las cuentas que marques; si no marcas nada, los destinos del flujo
    horas: dict[int, tuple[datetime | None, str]] = {}
    if body.destinos:
        cuentas = []
        for destino in body.destinos:
            elegida = db.get(Account, destino.account_id)
            if elegida:
                cuentas.append(elegida)
                horas[elegida.id] = (destino.scheduled_at, destino.slot_reason)
    elif body.account_id:
        elegida = db.get(Account, body.account_id)
        cuentas = [elegida] if elegida else []
    else:
        cuentas = pipeline.destinations_for(db, clip.video, publish_config)
    if not cuentas:
        raise HTTPException(
            400,
            "No hay ninguna cuenta conectada para publicar. Conecta TikTok o tu canal "
            "de YouTube en «Cuentas».",
        )

    # No se duplica lo que ya esté programado en esa misma cuenta
    ya_programadas = {
        post.account_id
        for post in db.scalars(
            select(Post).where(
                Post.clip_id == clip.id, Post.status == PostStatus.scheduled.value
            )
        ).all()
    }

    creados = []
    for cuenta in cuentas:
        if cuenta.id in ya_programadas:
            continue
        cuando, motivo = horas.get(cuenta.id, (body.scheduled_at, body.slot_reason))
        post = pipeline.schedule_clip(
            db, clip, cuenta, schedule_config, when=naive_utc(cuando),
            reason=motivo[:300],
        )
        creados.append(post.id)

    db.commit()
    return {
        "clip": clip_to_dict(clip),
        "post_ids": creados,
        "post_id": creados[0] if creados else None,
    }


@router.get("/{clip_id}/propuesta")
def propuesta(clip_id: int, account_id: int, db: Session = Depends(get_db)):
    """Cuándo publicaría el motor este clip en esa cuenta, para enseñarlo ya."""
    clip = db.get(Clip, clip_id)
    cuenta = db.get(Account, account_id)
    if not clip or not cuenta:
        raise HTTPException(404, "Clip o cuenta no encontrados")
    from app.flow_schema import step_config

    flow = pipeline.resolve_flow(db, clip.flow_id)
    hueco = pipeline.proponer_hora(db, cuenta, step_config(flow.steps, "schedule"))
    return {
        "scheduled_at": hueco["utc"].isoformat() + "Z",
        "reason": hueco["reason"],
        "score": hueco["score"],
    }


@router.post("/{clip_id}/reject")
def reject_clip(clip_id: int, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(404, "Clip no encontrado")
    clip.status = ClipStatus.rejected.value
    for post in clip.posts:
        if post.status == PostStatus.scheduled.value:
            pipeline.mover_en_plataforma(db, post, cancelar=True)
            post.status = PostStatus.cancelled.value
    events.log(db, f"Clip descartado: {clip.title[:50]}", level="info", scope="clips")
    db.commit()
    return clip_to_dict(clip)


class BorrarClipsIn(BaseModel):
    ids: list[int] = []
    status: str = ""          # p. ej. «rejected» para vaciar los descartados


@router.post("/delete")
def delete_clips(body: BorrarClipsIn, db: Session = Depends(get_db)):
    """Borra del disco y de la lista los clips elegidos (o todos los de un estado)."""
    ids = list(body.ids or [])
    if body.status:
        ids += [
            clip.id for clip in db.scalars(
                select(Clip).where(Clip.status == body.status)
            ).all()
        ]
    if not ids:
        raise HTTPException(400, "No has elegido ningún clip.")
    resultado = storage.borrar_clips(db, ids)
    if resultado["deleted"]:
        events.log(
            db,
            f"{resultado['deleted']} clip(s) borrados · {resultado['freed_mb']} MB liberados",
            level="info",
            scope="clips",
        )
    db.commit()
    return resultado


@router.delete("/{clip_id}")
def delete_clip(clip_id: int, db: Session = Depends(get_db)):
    if not db.get(Clip, clip_id):
        raise HTTPException(404, "Clip no encontrado")
    resultado = storage.borrar_clips(db, [clip_id])
    if resultado["skipped"]:
        raise HTTPException(409, "Ese clip se está subiendo ahora mismo: espera a que termine.")
    db.commit()
    return {"ok": True, **resultado}


# --------------------------------------------------------------------------
# Archivos
# --------------------------------------------------------------------------
def _stream_file(path: Path, request: Request) -> Response:
    """Envía el vídeo admitiendo saltos (Range) para que el reproductor vaya fino."""
    size = path.stat().st_size
    range_header = request.headers.get("range")
    headers = {
        "accept-ranges": "bytes",
        "content-type": "video/mp4",
        "cache-control": "no-cache",
    }

    if not range_header:
        headers["content-length"] = str(size)
        return FileResponse(path, headers=headers, media_type="video/mp4")

    try:
        units, _, span = range_header.partition("=")
        start_text, _, end_text = span.partition("-")
        start = int(start_text) if start_text else 0
        end = int(end_text) if end_text else size - 1
    except ValueError:
        raise HTTPException(416, "Rango no válido")
    if units.strip() != "bytes" or start >= size:
        raise HTTPException(416, "Rango no válido")
    end = min(end, size - 1)
    length = end - start + 1

    def iterator() -> Iterator[bytes]:
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                data = handle.read(min(CHUNK, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers.update(
        {
            "content-range": f"bytes {start}-{end}/{size}",
            "content-length": str(length),
        }
    )
    return StreamingResponse(iterator(), status_code=206, headers=headers)


@router.get("/{clip_id}/file")
def clip_file(clip_id: int, request: Request, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip or not clip.render_path or not os.path.exists(clip.render_path):
        raise HTTPException(404, "El clip todavía no está renderizado")
    return _stream_file(Path(clip.render_path), request)


@router.get("/{clip_id}/download")
def clip_download(clip_id: int, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip or not clip.render_path or not os.path.exists(clip.render_path):
        raise HTTPException(404, "El clip todavía no está renderizado")
    safe = "".join(c for c in (clip.title or f"clip-{clip.id}") if c.isalnum() or c in " -_")[:60]
    return FileResponse(
        clip.render_path, media_type="video/mp4", filename=f"{safe or 'clip'}.mp4"
    )


@router.get("/{clip_id}/thumb")
def clip_thumb(clip_id: int, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip or not clip.thumb_path or not os.path.exists(clip.thumb_path):
        raise HTTPException(404, "Sin miniatura")
    return FileResponse(clip.thumb_path, media_type="image/jpeg")
