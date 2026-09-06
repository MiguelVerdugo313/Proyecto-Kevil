"""No dejar rastro: el disco se limpia solo.

La idea es que Kevil no te llene el ordenador de vídeos. Por eso:

* del vídeo original se bajan **sólo los tramos** que van a salir en un clip
  (ver ``youtube.download_sections``), no las dos horas de directo;
* cuando un clip ya está publicado, su ``.mp4`` se borra;
* cuando de un vídeo ya no queda nada por renderizar, se borra el original;
* y si aun así la carpeta de medios pasa del tope que hayas puesto, se borra
  lo más antiguo que ya esté publicado hasta volver por debajo.

Todo esto se puede desactivar en Ajustes si prefieres guardarlo todo.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Clip, ClipStatus, Post, PostStatus, Video


# --------------------------------------------------------------------------
# Utilidades de disco
# --------------------------------------------------------------------------
def _borrar(ruta: str | None) -> int:
    """Borra un archivo si existe. Devuelve los bytes liberados."""
    if not ruta:
        return 0
    archivo = Path(ruta)
    try:
        if not archivo.is_file():
            return 0
        tamano = archivo.stat().st_size
        archivo.unlink()
        return tamano
    except OSError:
        return 0


def folder_size(path: Path) -> int:
    total = 0
    try:
        for hijo in path.rglob("*"):
            try:
                if hijo.is_file():
                    total += hijo.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total


def usage() -> dict[str, Any]:
    """Cuánto ocupa cada cosa, para enseñarlo en Ajustes."""
    partes = {
        "originales": folder_size(settings.sources_path),
        "clips": folder_size(settings.clips_path),
        "miniaturas": folder_size(settings.thumbs_path),
        "temporales": folder_size(settings.work_path),
    }
    total = sum(partes.values())
    tope = float(settings.disk_budget_gb or 0) * 1024**3
    return {
        "parts": {k: round(v / 1024**2, 1) for k, v in partes.items()},   # en MB
        "total_mb": round(total / 1024**2, 1),
        "total_gb": round(total / 1024**3, 2),
        "budget_gb": float(settings.disk_budget_gb or 0),
        "over_budget": bool(tope and total > tope),
        "light_mode": settings.light_mode,
        "keeps_files": settings.keep_originals or settings.keep_clips,
    }


# --------------------------------------------------------------------------
# Limpieza dirigida
# --------------------------------------------------------------------------
def _clip_terminado(clip: Clip) -> bool:
    """El clip ya no necesita su archivo: todo lo suyo está publicado o muerto."""
    if not clip.posts:
        return False
    vivos = {PostStatus.scheduled.value, PostStatus.publishing.value}
    return not any(post.status in vivos for post in clip.posts)


def cleanup_clip(session: Session, clip: Clip, *, force: bool = False) -> int:
    """Borra el vídeo del clip cuando ya se ha publicado en todas partes."""
    if settings.keep_clips and not force:
        return 0
    if not force and not _clip_terminado(clip):
        return 0

    liberado = _borrar(clip.render_path)
    if liberado:
        clip.render_path = ""
    return liberado


def cleanup_video(session: Session, video: Video, *, force: bool = False) -> int:
    """Borra el original cuando ya no queda ningún clip por renderizar."""
    if settings.keep_originals and not force:
        return 0
    if not video.local_path:
        return 0

    if not force:
        pendientes = {ClipStatus.draft.value, ClipStatus.rendering.value}
        if any(clip.status in pendientes for clip in video.clips):
            return 0

    liberado = _borrar(video.local_path)
    if liberado:
        video.local_path = ""
    return liberado


def after_publish(session: Session, clip: Clip) -> int:
    """Se llama al terminar de publicar: limpia el clip y, si toca, el original."""
    liberado = cleanup_clip(session, clip)
    if clip.video is not None:
        liberado += cleanup_video(session, clip.video)
    return liberado


def clear_temp() -> int:
    """Vacía la carpeta de trabajo: son archivos de un solo uso."""
    liberado = 0
    try:
        for hijo in settings.work_path.iterdir():
            if hijo.is_file():
                liberado += _borrar(str(hijo))
    except OSError:
        pass
    return liberado


# --------------------------------------------------------------------------
# Tope de disco
# --------------------------------------------------------------------------
def enforce_budget(session: Session) -> dict[str, Any]:
    """Si la carpeta de medios se pasa del tope, borra lo más viejo ya publicado."""
    tope = float(settings.disk_budget_gb or 0) * 1024**3
    liberado = clear_temp()
    if not tope:
        return {"freed_mb": round(liberado / 1024**2, 1), "budget_gb": 0}

    total = folder_size(settings.media_path)
    if total - liberado <= tope:
        return {"freed_mb": round(liberado / 1024**2, 1), "budget_gb": settings.disk_budget_gb}

    # Primero los clips ya publicados, del más antiguo al más nuevo
    publicados = session.scalars(
        select(Clip)
        .join(Post, Post.clip_id == Clip.id)
        .where(Post.status == PostStatus.published.value)
        .order_by(Clip.created_at)
    ).unique().all()
    for clip in publicados:
        if total - liberado <= tope:
            break
        liberado += cleanup_clip(session, clip, force=True)

    # Después los originales de vídeos que ya no tienen nada pendiente
    if total - liberado > tope:
        videos = session.scalars(
            select(Video).where(Video.local_path != "").order_by(Video.created_at)
        ).all()
        for video in videos:
            if total - liberado <= tope:
                break
            liberado += cleanup_video(session, video)

    return {
        "freed_mb": round(liberado / 1024**2, 1),
        "budget_gb": settings.disk_budget_gb,
        "still_over": total - liberado > tope,
    }


def purge_everything(session: Session) -> dict[str, Any]:
    """Borrón y cuenta nueva: se van todos los archivos de medios.

    La base de datos se queda: sigues viendo qué se publicó y cuándo, lo que
    desaparece son los vídeos, que es lo que ocupa.
    """
    liberado = clear_temp()
    for clip in session.scalars(select(Clip)).all():
        liberado += cleanup_clip(session, clip, force=True)
    for video in session.scalars(select(Video)).all():
        liberado += cleanup_video(session, video, force=True)
    return {"freed_mb": round(liberado / 1024**2, 1)}
