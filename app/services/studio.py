"""Estudio: lo que ocurre cuando subes un vídeo tuyo.

Trabajos en segundo plano:

* `analyze_local`  — analiza el archivo que has subido y lo transcribe.
* `build_kit`      — genera títulos, descripción, etiquetas y miniaturas.
* `upload_youtube` — sube el vídeo al canal con ese kit puesto.
* `generate_ideas` — propone temas para los próximos vídeos.
* `coach_check`    — repaso diario de la cadencia del canal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.flow_schema import step_config
from app.models import Account, Platform, Video, VideoStatus, utcnow
from app.services import (
    coach, events, ideas, notifications, seo, thumbnails, transcript, youtube_api,
)
from app.services import media as media_service
from app.services.pipeline import resolve_flow
from app.services.queue import JobContext, enqueue, register


# --------------------------------------------------------------------------
# 1. Analizar un vídeo subido desde el disco
# --------------------------------------------------------------------------
@register("analyze_local")
def job_analyze_local(session: Session, ctx: JobContext) -> None:
    video = session.get(Video, int(ctx.payload["video_id"]))
    if not video:
        raise RuntimeError("El vídeo ya no existe.")
    if not video.local_path or not Path(video.local_path).exists():
        raise RuntimeError("No se encuentra el archivo subido.")

    video.status = VideoStatus.downloading.value
    session.commit()
    ctx.progress(0.1, "Analizando el archivo…")

    probe = media_service.probe(video.local_path)
    video.probe = probe
    video.duration_s = probe.get("duration") or 0

    flow = resolve_flow(session, ctx.payload.get("flow_id"))
    config = step_config(flow.steps, "transcribe")
    motor = str(config.get("engine", "youtube"))

    # Un archivo local no tiene subtítulos de YouTube: se usa Whisper si está.
    if motor in {"youtube", "youtube_then_whisper"}:
        motor = "whisper" if motor == "youtube_then_whisper" else "none"

    if motor == "whisper":
        ctx.progress(0.25, "Transcribiendo con Whisper (puede tardar)…")
        try:
            video.transcript = transcript.build_transcript(
                engine="whisper",
                media_path=video.local_path,
                subtitle_files=[],
                language=str(config.get("language", "es")),
                whisper_model=str(config.get("whisper_model", "small")),
            )
            ctx.log(f"Transcritas {len(video.transcript.get('words') or [])} palabras.")
        except Exception as exc:
            video.transcript = {"words": [], "segments": [], "source": "error"}
            ctx.log(f"Sin transcripción: {exc}")
    else:
        video.transcript = {"words": [], "segments": [], "source": "none"}
        ctx.log(
            "Sin transcripción: activa Whisper en el flujo para que el kit sea mucho mejor."
        )

    video.status = VideoStatus.ready.value
    session.commit()
    ctx.progress(0.6, "Preparando el kit de publicación…")

    enqueue(
        session,
        "build_kit",
        {"video_id": video.id, "use_ai": bool(ctx.payload.get("use_ai", True))},
        priority=95,
        message=f"Kit de «{video.title[:50]}»",
    )
    if ctx.payload.get("make_clips"):
        enqueue(
            session,
            "process",
            {"video_id": video.id, "flow_id": flow.id},
            priority=115,
            message=f"Cortar «{video.title[:50]}»",
        )


# --------------------------------------------------------------------------
# 2. Kit de publicación
# --------------------------------------------------------------------------
@register("build_kit")
def job_build_kit(session: Session, ctx: JobContext) -> None:
    video = session.get(Video, int(ctx.payload["video_id"]))
    if not video:
        raise RuntimeError("El vídeo ya no existe.")

    usar_ia = bool(ctx.payload.get("use_ai", True))
    ctx.progress(0.15, "Escribiendo títulos y descripción…")

    kit = seo.build_kit(
        title=video.title,
        transcript=video.transcript or {},
        duration=float(video.duration_s or 0),
        topic=settings.channel_topic,
        language=settings.channel_language,
        use_ai=usar_ia,
    )

    # Miniaturas (sólo si tenemos el archivo en el disco)
    miniaturas: list[dict[str, Any]] = []
    if video.local_path and Path(video.local_path).exists():
        ctx.progress(0.45, "Generando miniaturas…")
        try:
            miniaturas = thumbnails.generate(
                video_path=video.local_path,
                duration=float(video.duration_s or 0),
                texts=kit.get("thumbnail_texts") or [video.title[:24]],
                out_dir=settings.thumbs_path / "youtube",
                prefix=f"video-{video.id:05d}",
                count=int(ctx.payload.get("thumbnail_count", 3)),
                ai_prompt=kit.get("thumbnail_prompt", ""),
                use_ai_image=bool(ctx.payload.get("ai_image", False)),
                on_progress=lambda ratio: ctx.progress(ratio),
            )
        except Exception as exc:
            ctx.log(f"No se han podido generar las miniaturas: {exc}")
    else:
        ctx.log("El vídeo no está descargado: no se generan miniaturas.")

    kit["thumbnails"] = [m for m in miniaturas if m.get("path")]
    kit["thumbnail_errors"] = [m["error"] for m in miniaturas if m.get("error")]
    kit["review"] = seo.review_kit(kit, duration=float(video.duration_s or 0))
    kit["updated_at"] = utcnow().isoformat() + "Z"
    video.kit = kit
    session.commit()

    aviso = kit.get("warning") or ""
    events.log(
        session,
        f"Kit listo para «{video.title[:50]}»" + (f" ({aviso})" if aviso else ""),
        level="warn" if aviso else "success",
        scope="estudio",
        data={"video_id": video.id},
    )
    notifications.notify(
        session,
        "Tu kit de publicación está listo",
        f"«{video.title[:60]}»: {len(kit.get('titles') or [])} títulos, "
        f"{len(kit.get('tags') or [])} etiquetas y "
        f"{len(kit.get('thumbnails') or [])} miniaturas.",
        kind="kit",
        level="success",
        action_label="Abrir el estudio",
        action_url="#estudio",
        dedupe_hours=0,
    )
    ctx.progress(1.0, "Kit listo")


# --------------------------------------------------------------------------
# 3. Subir el vídeo a YouTube con su kit
# --------------------------------------------------------------------------
def canal_para_subir(session: Session) -> Account:
    """El canal de YouTube conectado con permiso de subida."""
    cuentas = session.scalars(
        select(Account).where(Account.platform == Platform.youtube.value)
    ).all()
    for cuenta in cuentas:
        if (cuenta.credentials or {}).get("access_token"):
            return cuenta
    raise RuntimeError(
        "Ningún canal de YouTube con permiso para subir. Conéctalo en "
        "Ajustes → YouTube."
    )


@register("upload_youtube")
def job_upload_youtube(session: Session, ctx: JobContext) -> None:
    """Sube a YouTube el vídeo tal cual, con el título, la descripción, las
    etiquetas y la miniatura que se hayan elegido en el estudio."""
    video = session.get(Video, int(ctx.payload["video_id"]))
    if not video:
        raise RuntimeError("El vídeo ya no existe.")
    if not video.local_path or not Path(video.local_path).exists():
        raise RuntimeError("El archivo del vídeo ya no está en el disco.")

    cuenta = canal_para_subir(session)
    kit = dict(video.kit or {})
    datos = ctx.payload

    titulo = str(datos.get("title") or kit.get("title") or video.title)[:100]
    descripcion = str(datos.get("description") or kit.get("description") or "")
    etiquetas = list(datos.get("tags") or kit.get("tags") or [])
    privacidad = str(datos.get("privacy_status") or "private")
    cuando = datos.get("publish_at") or None

    ctx.progress(0.05, f"Subiendo «{titulo[:40]}»…")
    resultado = youtube_api.upload_video(
        cuenta.credentials or {},
        video_path=video.local_path,
        title=titulo,
        description=descripcion,
        tags=etiquetas,
        privacy_status=privacidad,
        publish_at=cuando,
        made_for_kids=bool(datos.get("made_for_kids", False)),
        dry_run=bool(settings.dry_run),
        on_progress=lambda ratio: ctx.progress(0.05 + 0.9 * ratio),
    )

    # las credenciales pueden haberse renovado durante la subida
    try:
        cuenta.credentials = youtube_api.valid_credentials(cuenta.credentials or {})
    except Exception:
        pass

    # La miniatura va después: YouTube la quiere con el vídeo ya creado.
    aviso_miniatura = ""
    indice = datos.get("thumbnail_index")
    if indice is not None and resultado.get("video_id") and not resultado.get("dry_run"):
        miniaturas = kit.get("thumbnails") or []
        ruta = ""
        if 0 <= int(indice) < len(miniaturas):
            ruta = str(miniaturas[int(indice)].get("path") or "")
        if ruta and Path(ruta).exists():
            ctx.progress(0.97, "Poniendo la miniatura…")
            puesta = youtube_api.set_thumbnail(
                cuenta.credentials or {}, resultado["video_id"], ruta
            )
            if not puesta:
                # Es lo más habitual: hasta que no verificas el canal por
                # teléfono, YouTube no deja poner miniatura propia.
                aviso_miniatura = (
                    "El vídeo ha subido bien, pero YouTube no ha aceptado la "
                    "miniatura. Suele ser que el canal no está verificado por "
                    "teléfono: verifícalo y ponla a mano desde YouTube Studio."
                )

    kit["youtube"] = {
        "video_id": resultado.get("video_id", ""),
        "url": resultado.get("url", ""),
        "privacy": privacidad,
        "publish_at": cuando or "",
        "uploaded_at": utcnow().isoformat() + "Z",
        "dry_run": bool(resultado.get("dry_run")),
        "warning": aviso_miniatura,
    }
    video.kit = kit
    session.commit()

    events.log(
        session,
        f"Subido a YouTube: «{titulo[:50]}»" + (f" · {aviso_miniatura}" if aviso_miniatura else ""),
        level="warn" if aviso_miniatura else "success",
        scope="youtube",
        data={"video_id": video.id, "quota": youtube_api.COST_UPLOAD},
    )
    notifications.notify(
        session,
        "Vídeo subido a YouTube",
        f"«{titulo[:60]}» está en tu canal como {ETIQUETA_PRIVACIDAD.get(privacidad, privacidad)}.",
        kind="youtube",
        level="success",
        action_label="Abrirlo en YouTube",
        action_url=resultado.get("url", "") or "#estudio",
        dedupe_hours=0,
    )
    ctx.progress(1.0, "Subido")


ETIQUETA_PRIVACIDAD = {
    "public": "público",
    "unlisted": "oculto",
    "private": "privado",
}


# --------------------------------------------------------------------------
# 4. Ideas de contenido
# --------------------------------------------------------------------------
@register("generate_ideas")
def job_generate_ideas(session: Session, ctx: JobContext) -> None:
    ctx.progress(0.1, "Buscando ideas…")
    creadas = ideas.generate(
        session,
        count=int(ctx.payload.get("count", 6)),
        validate=bool(ctx.payload.get("validate", True)),
        on_progress=lambda ratio: ctx.progress(ratio, "Comprobando la demanda…"),
    )
    session.commit()

    if creadas:
        mejor = creadas[0]
        notifications.notify(
            session,
            f"{len(creadas)} ideas nuevas para tu canal",
            f"La mejor: «{mejor.title}» (nota {int(mejor.score * 100)}/100).",
            kind="ideas",
            level="info",
            action_label="Ver las ideas",
            action_url="#coach",
            dedupe_hours=1,
        )
    events.log(
        session,
        f"{len(creadas)} idea(s) generadas",
        level="success" if creadas else "warn",
        scope="ideas",
    )
    ctx.progress(1.0, f"{len(creadas)} ideas")


# --------------------------------------------------------------------------
# 5. Repaso del canal
# --------------------------------------------------------------------------
@register("coach_check")
def job_coach_check(session: Session, ctx: JobContext) -> None:
    ctx.progress(0.3, "Revisando tu ritmo de publicación…")
    creados = coach.daily_check(session)
    session.commit()
    ctx.progress(1.0, f"{len(creados)} aviso(s)")
