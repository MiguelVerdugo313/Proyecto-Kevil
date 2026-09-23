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
    desaparece son los vídeos, que es lo que ocupa. Las publicaciones que
    estaban programadas se cancelan: sin su archivo no podrían salir, y es
    mejor verlo claro ahora que como un fallo raro dentro de tres días.
    """
    liberado = clear_temp()
    for clip in session.scalars(select(Clip)).all():
        if clip.render_path:
            for post in clip.posts:
                if post.status == PostStatus.scheduled.value:
                    post.status = PostStatus.cancelled.value
        liberado += cleanup_clip(session, clip, force=True)
    for video in session.scalars(select(Video)).all():
        liberado += cleanup_video(session, video, force=True)
    return {"freed_mb": round(liberado / 1024**2, 1)}


# --------------------------------------------------------------------------
# «Liberar espacio»: el botón que se puede pulsar sin miedo
# --------------------------------------------------------------------------
# Archivos sueltos más recientes que esto no se tocan: podrían ser de un
# trabajo que está escribiéndolos ahora mismo.
MARGEN_HUERFANOS_S = 30 * 60

VIVOS = {PostStatus.scheduled.value, PostStatus.publishing.value}


def _sobra(clip: Clip) -> str:
    """Por qué el archivo de este clip ya no hace falta, o «» si aún se usa.

    Se queda todo lo que todavía tiene futuro: lo que se está montando, lo que
    está por revisar, lo aprobado, lo programado, lo que se está subiendo y lo
    que falló al publicar (puede que quieras reintentarlo).
    """
    if any(post.status in VIVOS for post in clip.posts):
        return ""
    if clip.status == ClipStatus.rejected.value:
        return "descartado"
    publicados = [p for p in clip.posts if p.status == PostStatus.published.value]
    cerrados = {PostStatus.published.value, PostStatus.cancelled.value}
    if publicados and all(p.status in cerrados for p in clip.posts):
        return "publicado"
    return ""


def _original_pendiente(video: Video) -> bool:
    """¿Hace falta aún el vídeo original?

    Mientras quede algún clip por montar, sí. Y si todavía no se ha cortado en
    clips —recién bajado o recién subido desde el estudio—, también: aún no se
    ha sacado nada de él.
    """
    if not video.clips:
        return True
    pendientes = {ClipStatus.draft.value, ClipStatus.rendering.value}
    return any(clip.status in pendientes for clip in video.clips)


def _referenciados(session: Session) -> set[str]:
    rutas: set[str] = set()
    for clip in session.scalars(select(Clip)).all():
        rutas.update(p for p in (clip.render_path, clip.thumb_path) if p)
    for video in session.scalars(select(Video)).all():
        if video.local_path:
            rutas.add(video.local_path)
        for miniatura in (video.kit or {}).get("thumbnails") or []:
            if miniatura.get("path"):
                rutas.add(miniatura["path"])
    return {str(Path(r).resolve()) for r in rutas}


def _huerfanos(session: Session) -> list[Path]:
    """Archivos de las carpetas de medios que ya no son de nadie.

    Suelen ser restos de descargas cortadas, renders que fallaron o versiones
    anteriores del programa. No los usa nada y sólo ocupan.
    """
    import time

    en_uso = _referenciados(session)
    limite = time.time() - MARGEN_HUERFANOS_S
    sueltos: list[Path] = []
    for carpeta in (settings.sources_path, settings.clips_path):
        try:
            archivos = [a for a in carpeta.rglob("*") if a.is_file()]
        except OSError:
            continue
        for archivo in archivos:
            try:
                if archivo.stat().st_mtime > limite:
                    continue
            except OSError:
                continue
            if str(archivo.resolve()) not in en_uso:
                sueltos.append(archivo)
    return sueltos


def _tamano(ruta: str | Path | None) -> int:
    try:
        return Path(ruta).stat().st_size if ruta else 0
    except OSError:
        return 0


def plan_de_limpieza(session: Session) -> dict[str, Any]:
    """Qué se borraría y cuánto se liberaría, sin tocar nada todavía."""
    temporales = folder_size(settings.work_path)

    descartados = publicados = 0
    for clip in session.scalars(select(Clip).where(Clip.render_path != "")).all():
        motivo = _sobra(clip)
        if motivo == "descartado":
            descartados += _tamano(clip.render_path)
        elif motivo == "publicado":
            publicados += _tamano(clip.render_path)

    originales = 0
    for video in session.scalars(select(Video).where(Video.local_path != "")).all():
        if not _original_pendiente(video):
            originales += _tamano(video.local_path)

    huerfanos = sum(_tamano(a) for a in _huerfanos(session))

    partes = {
        "temporales": temporales,
        "descartados": descartados,
        "publicados": publicados,
        "originales": originales,
        "huerfanos": huerfanos,
    }
    return {
        "parts": {k: round(v / 1024**2, 1) for k, v in partes.items()},
        "total_mb": round(sum(partes.values()) / 1024**2, 1),
    }


def liberar_espacio(session: Session) -> dict[str, Any]:
    """Borra todo lo que sobra y nada de lo que hace falta.

    Se va: lo temporal, los clips descartados, los ya publicados, los
    originales de los que ya no queda nada por montar y los archivos sueltos
    que no son de nadie.

    No se toca: los clips por revisar, los programados ni los que se están
    montando. Esos todavía los necesitas.
    """
    plan = plan_de_limpieza(session)
    liberado = clear_temp()

    for clip in session.scalars(select(Clip).where(Clip.render_path != "")).all():
        if _sobra(clip):
            liberado += cleanup_clip(session, clip, force=True)

    for video in session.scalars(select(Video).where(Video.local_path != "")).all():
        if not _original_pendiente(video):
            liberado += cleanup_video(session, video, force=True)

    for archivo in _huerfanos(session):
        liberado += _borrar(str(archivo))

    return {"freed_mb": round(liberado / 1024**2, 1), "plan": plan}


def borrar_clips(session: Session, ids: list[int]) -> dict[str, Any]:
    """Quita del todo los clips elegidos: archivo, miniatura y registro.

    Sus publicaciones programadas se van con ellos. Los que se están subiendo
    en este momento no se tocan: cortarlos a medias dejaría la publicación en
    un estado raro en TikTok.
    """
    borrados, saltados, liberado = 0, 0, 0
    for clip in session.scalars(select(Clip).where(Clip.id.in_(ids or []))).all():
        if any(post.status == PostStatus.publishing.value for post in clip.posts):
            saltados += 1
            continue
        liberado += _borrar(clip.render_path) + _borrar(clip.thumb_path)
        session.delete(clip)
        borrados += 1
    return {
        "deleted": borrados,
        "skipped": saltados,
        "freed_mb": round(liberado / 1024**2, 1),
    }
