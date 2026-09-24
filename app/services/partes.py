"""Cada clip se llama como su parte del vídeo: «Nombre del vídeo · Parte 3».

La parte es la posición del trozo **dentro del vídeo** (la 1 es la que va
antes), no la nota de viralidad: así «Parte 1» es de verdad el principio. Ese
título es el que se sube a YouTube y la primera línea en TikTok.

Sólo se tocan los títulos que puso Kevil («… · Parte N»): si escribiste uno a
mano, se respeta. Y lo ya publicado no se renombra.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.flow_schema import step_config
from app.models import Clip, ClipStatus, PostStatus, Video
from app.services import metadata

AUTOMATICO = re.compile(r"·\s*parte\s*\d+\s*$", re.IGNORECASE)


def titulo_base(video: Video) -> str:
    """El nombre del vídeo; si es un nombre de archivo, lo que contaste de él."""
    from app.services import fidelidad, seo

    if fidelidad.titulo_generico(video.title) and video.contexto:
        return seo._frase_principal(video.contexto) or video.title
    return video.title


def es_automatico(clip: Clip, base: str = "") -> bool:
    """¿Lo puso Kevil? («Vídeo · Parte N», el título del vídeo a secas o el gancho)."""
    titulo = (clip.title or "").strip()
    return (
        not titulo
        or bool(AUTOMATICO.search(titulo))
        or titulo in {(clip.hook or "").strip(), metadata.acortar(base)}
    )


def es_entero(clip: Clip, video: Video) -> bool:
    """El clip es el vídeo entero (un vídeo corto publicado tal cual)."""
    duracion = float(video.duration_s or 0)
    return duracion > 0 and (clip.end_s - clip.start_s) >= 0.9 * duracion


def _texto_automatico(clip: Clip, titulo_anterior: str) -> bool:
    primera = (clip.caption or "").strip().split("\n", 1)[0].strip()
    return not primera or primera in {(clip.hook or "").strip(), titulo_anterior.strip()}


def _ya_fuera(clip: Clip) -> bool:
    """Publicado o subido ya a una plataforma: su título ya no se toca."""
    return clip.status == ClipStatus.published.value or any(
        post.status == PostStatus.published.value or post.en_plataforma
        for post in clip.posts
    )


def numerar(session: Session, video: Video) -> int:
    """Numera las partes por orden en el vídeo y pone los títulos. Devuelve cuántos cambian."""
    from app.services.pipeline import resolve_flow

    clips = sorted(
        (c for c in video.clips if c.status != ClipStatus.rejected.value),
        key=lambda c: (c.start_s, c.id or 0),
    )
    total = len(clips)
    base = titulo_base(video)
    canal = video.source.name if video.source else ""
    cambiados = 0
    for numero, clip in enumerate(clips, start=1):
        clip.index = numero
        if _ya_fuera(clip) or not es_automatico(clip, base):
            continue
        flow = resolve_flow(session, clip.flow_id, video)
        meta = metadata.build_metadata(
            config=step_config(flow.steps, "metadata"),
            video_title=base,
            channel=canal,
            hook=clip.hook or "",
            text=f"{video.contexto or ''} {clip.hook or ''}".strip(),
            index=numero,
            total=total,
            entero=es_entero(clip, video),
        )
        anterior_titulo, anterior_texto = clip.title or "", clip.caption or ""
        if meta["title"] == anterior_titulo:
            continue
        # se recuerdan los títulos viejos: con ellos se reconoce lo que ya se subió
        config = dict(clip.render_config or {})
        anteriores = list(config.get("titulos_anteriores") or [])
        if anterior_titulo and anterior_titulo not in anteriores:
            anteriores.append(anterior_titulo)
        config["titulos_anteriores"] = anteriores[-5:]
        clip.render_config = config
        clip.title = meta["title"]
        if _texto_automatico(clip, anterior_titulo):
            clip.caption = meta["caption"]
            for post in clip.posts:
                if (post.status == PostStatus.scheduled.value and not post.en_plataforma
                        and (post.caption or "") in {anterior_texto, ""}):
                    post.caption = clip.caption
        cambiados += 1
    session.flush()
    return cambiados


def numerar_todo(session: Session) -> int:
    """Al actualizar: los clips aún sin publicar pasan a «Vídeo · Parte N»."""
    from sqlalchemy import select

    total = 0
    for video in session.scalars(select(Video).where(Video.clips.any())).all():
        total += numerar(session, video)
    return total
