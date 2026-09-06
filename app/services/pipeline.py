"""Orquestación completa: de un vídeo de YouTube a una publicación en TikTok."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.flow_schema import normalize_steps, step_config, step_enabled
from app.models import (
    Account,
    AccountStatus,
    Clip,
    ClipStatus,
    Flow,
    MetricSample,
    Platform,
    Post,
    PostStatus,
    Source,
    Video,
    VideoStatus,
    utcnow,
)
from app.services import (
    events, metadata, notifications, renderer, segmenter, storage, timing,
    tiktok, transcript, youtube_api,
)
from app.services import media as media_service
from app.services import youtube as youtube_service
from app.services.queue import JobContext, enqueue, register


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def resolve_flow(
    session: Session, flow_id: int | None, video: Video | None = None
) -> Flow:
    """El flujo que toca: el pedido, el del canal del vídeo o el predeterminado."""
    flow: Flow | None = None
    if flow_id:
        flow = session.get(Flow, flow_id)
    if flow is None and video is not None and video.source and video.source.flow_id:
        # Si el canal tiene su propio flujo, manda ese aunque no venga en la orden.
        flow = session.get(Flow, video.source.flow_id)
    if flow is None:
        flow = session.scalars(
            select(Flow).where(Flow.is_default.is_(True)).limit(1)
        ).first()
    if flow is None:
        flow = session.scalars(select(Flow).order_by(Flow.id).limit(1)).first()
    if flow is None:
        raise RuntimeError("No hay ningún flujo configurado.")
    flow.steps = normalize_steps(flow.steps)
    return flow


# --------------------------------------------------------------------------
# Modo ligero: no bajar el vídeo entero si no hace falta
# --------------------------------------------------------------------------
# Estrategias de corte que necesitan oír el audio para decidir dónde cortar.
ESTRATEGIAS_CON_AUDIO = {"smart", "silence"}


def usa_modo_ligero(flow: Flow) -> bool:
    """¿Se puede evitar bajar el vídeo entero para este flujo?

    Con la estrategia «vídeo completo» (republicar un Short tal cual) no hay
    nada que elegir: el tramo es todo el vídeo, así que da igual. En el resto
    sí compensa: se leen los subtítulos, se eligen los momentos y sólo después
    se bajan esos segundos.
    """
    if not settings.light_mode:
        return False
    estrategia = str(step_config(flow.steps, "segment").get("strategy", "smart"))
    return estrategia != "completo"


def necesita_audio(flow: Flow) -> bool:
    """La estrategia elegida, ¿tiene que oír el vídeo o le basta el texto?"""
    estrategia = str(step_config(flow.steps, "segment").get("strategy", "smart"))
    return estrategia in ESTRATEGIAS_CON_AUDIO


def _borrar_temporal(ctx: JobContext, ruta: str | None) -> None:
    if not ruta:
        return
    try:
        archivo = Path(ruta)
        if archivo.is_file():
            tamano = archivo.stat().st_size
            archivo.unlink()
            ctx.log(f"Borrado {archivo.name} ({tamano / 1024 / 1024:.1f} MB)")
    except OSError:
        pass


def _aplazar_por_limite(
    session: Session, ctx: JobContext, video: Video, flow: Flow, motivo: str
) -> None:
    """YouTube ha dicho «too many requests»: se vuelve a intentar más tarde."""
    enqueue(
        session,
        "ingest",
        {"video_id": video.id, "flow_id": flow.id},
        priority=140,
        run_at=utcnow() + timedelta(minutes=45),
        message=f"Reintentar «{video.title[:50]}» (YouTube nos frenó)",
    )
    notifications.notify(
        session,
        "YouTube nos ha frenado un rato",
        motivo,
        kind="limite",
        level="warn",
        dedupe_hours=6,
    )
    events.log(session, motivo, level="warn", scope="video", data={"video_id": video.id})
    ctx.progress(1.0, "Aplazado 45 minutos")


def default_tiktok_account(session: Session) -> Account | None:
    return session.scalars(
        select(Account)
        .where(
            Account.platform == Platform.tiktok.value,
            Account.enabled.is_(True),
        )
        .order_by(Account.id)
        .limit(1)
    ).first()


def target_account_for(session: Session, video: Video) -> Account | None:
    if video.source and video.source.target_account_id:
        account = session.get(Account, video.source.target_account_id)
        if account and account.enabled:
            return account
    return default_tiktok_account(session)


def publishable_youtube_account(session: Session) -> Account | None:
    """Primer canal de YouTube conectado con permiso para subir."""
    for account in session.scalars(
        select(Account)
        .where(Account.platform == Platform.youtube.value, Account.enabled.is_(True))
        .order_by(Account.id)
    ).all():
        if (account.credentials or {}).get("access_token"):
            return account
    return None


def destinations_for(
    session: Session, video: Video, publish_config: dict[str, Any]
) -> list[Account]:
    """Cuentas a las que hay que publicar este clip, según el flujo."""
    cuentas: list[Account] = []
    if publish_config.get("publish_tiktok", True):
        tiktok_account = target_account_for(session, video)
        if tiktok_account:
            cuentas.append(tiktok_account)
    if publish_config.get("publish_youtube_shorts", False):
        youtube_account = publishable_youtube_account(session)
        if youtube_account:
            cuentas.append(youtube_account)
    return cuentas


# --------------------------------------------------------------------------
# 1. Sincronizar un canal
# --------------------------------------------------------------------------
@register("sync_source")
def job_sync_source(session: Session, ctx: JobContext) -> None:
    source = session.get(Source, int(ctx.payload["source_id"]))
    if not source:
        raise RuntimeError("La fuente ya no existe.")

    ctx.progress(0.05, f"Leyendo {source.name}…")
    flow = resolve_flow(session, source.flow_id)
    ingest_config = step_config(flow.steps, "ingest")

    try:
        videos = youtube_service.list_channel_videos(
            source.url,
            limit=max(1, int(source.backfill_limit or 20)),
            include_lives=bool(source.include_lives),
            include_shorts=bool(source.include_shorts),
            only_shorts=source.kind == "shorts",
            cookies_from_browser=ingest_config.get("cookies_from_browser", ""),
        )
    except Exception as exc:
        source.last_error = str(exc)[:500]
        source.last_checked_at = utcnow()
        raise

    source.last_error = ""
    source.last_checked_at = utcnow()
    ctx.progress(0.5, f"{len(videos)} vídeos encontrados")

    created = 0
    for index, item in enumerate(videos):
        existing = session.scalars(
            select(Video).where(Video.external_id == item["external_id"])
        ).first()
        if existing:
            continue
        if item["duration_s"] and item["duration_s"] < float(source.min_duration_s or 0):
            continue

        video = Video(
            source_id=source.id,
            external_id=item["external_id"],
            title=item["title"],
            description=item.get("description", ""),
            url=item["url"],
            thumbnail_url=item.get("thumbnail_url", ""),
            duration_s=item.get("duration_s") or 0,
            published_at=item.get("published_at"),
            was_live=bool(item.get("was_live")),
            views=int(item.get("views") or 0),
            likes=int(item.get("likes") or 0),
            status=VideoStatus.discovered.value,
        )
        session.add(video)
        session.flush()
        created += 1

        if source.auto_ingest and created <= int(source.backfill_limit or 20):
            video.status = VideoStatus.queued.value
            enqueue(
                session,
                "ingest",
                {"video_id": video.id, "flow_id": source.flow_id},
                priority=120,
                message=f"Descargar «{video.title[:60]}»",
            )
        ctx.progress(0.5 + 0.5 * (index + 1) / max(1, len(videos)))

    events.log(
        session,
        f"«{source.name}»: {created} vídeo(s) nuevo(s)"
        if created
        else f"«{source.name}»: sin novedades",
        level="success" if created else "info",
        scope="canal",
        data={"source_id": source.id, "created": created},
    )
    ctx.progress(1.0, f"{created} nuevo(s)")


# --------------------------------------------------------------------------
# 2. Descargar y transcribir
# --------------------------------------------------------------------------
@register("ingest")
def job_ingest(session: Session, ctx: JobContext) -> None:
    video = session.get(Video, int(ctx.payload["video_id"]))
    if not video:
        raise RuntimeError("El vídeo ya no existe.")
    flow = resolve_flow(session, ctx.payload.get("flow_id"), video)
    ingest_config = step_config(flow.steps, "ingest")

    video.status = VideoStatus.downloading.value
    video.error = ""
    session.commit()

    def on_progress(ratio: float, label: str) -> None:
        ctx.progress(ratio * 0.7, label)

    # ¿Modo ligero? Entonces aquí no se baja el vídeo: sólo los subtítulos (unos
    # kilobytes) y, si el flujo necesita oír los silencios, la pista de audio.
    # Los segundos de vídeo se bajan luego, uno a uno, sólo los que salen.
    ligero = usa_modo_ligero(flow)
    audio_temporal = ""

    try:
        if ligero:
            ctx.log(f"Modo ligero: leyendo {video.url} sin bajar el vídeo")
            ctx.progress(0.15, "Leyendo el vídeo…")
            result = youtube_service.fetch_subtitles_only(
                video.url,
                subtitle_langs=list(ingest_config.get("subtitle_langs") or ["es", "en"]),
                cookies_from_browser=ingest_config.get("cookies_from_browser", ""),
            )
            if necesita_audio(flow):
                ctx.progress(0.3, "Bajando sólo el audio para elegir momentos…")
                audio_temporal = youtube_service.download_audio_only(
                    video.url,
                    cookies_from_browser=ingest_config.get("cookies_from_browser", ""),
                    on_progress=on_progress,
                )
        else:
            ctx.log(f"Descargando {video.url}")
            result = youtube_service.download_video(
                video.url,
                quality=str(ingest_config.get("quality", "1080")),
                download_subtitles=bool(ingest_config.get("download_subtitles", True)),
                subtitle_langs=list(ingest_config.get("subtitle_langs") or ["es", "en"]),
                cookies_from_browser=ingest_config.get("cookies_from_browser", ""),
                on_progress=on_progress,
            )
    except youtube_service.RateLimited as exc:
        # YouTube ha dicho «espera»: no es un fallo del vídeo, se reintenta luego.
        video.status = VideoStatus.queued.value
        video.error = str(exc)[:1000]
        _aplazar_por_limite(session, ctx, video, flow, str(exc))
        return
    except Exception as exc:
        video.status = VideoStatus.error.value
        video.error = youtube_service.traducir_error(exc)[:1000]
        events.log(
            session,
            f"Error al descargar «{video.title}»: {video.error}",
            level="error",
            scope="video",
        )
        raise

    info = result.get("info") or {}
    video.local_path = result.get("path", "")        # vacío en modo ligero
    video.title = video.title or info.get("title", "")
    video.was_live = video.was_live or bool(info.get("was_live"))
    if info.get("duration_s"):
        video.duration_s = float(info["duration_s"])

    # Para analizar sirve el audio; si se bajó el vídeo entero, sirve el vídeo.
    analizable = video.local_path or audio_temporal
    if analizable:
        ctx.progress(0.75, "Analizando el archivo…")
        probe = media_service.probe(analizable)
        if video.local_path:
            video.probe = probe
        video.duration_s = probe.get("duration") or video.duration_s

    # --- transcripción ---------------------------------------------------
    if step_enabled(flow.steps, "transcribe"):
        transcribe_config = step_config(flow.steps, "transcribe")
        ctx.progress(0.8, "Obteniendo la transcripción…")
        try:
            data = transcript.build_transcript(
                engine=str(transcribe_config.get("engine", "youtube")),
                media_path=analizable,
                subtitle_files=result.get("subtitles") or [],
                language=str(transcribe_config.get("language", "es")),
                whisper_model=str(transcribe_config.get("whisper_model", "small")),
            )
        except Exception as exc:  # la transcripción nunca debe tumbar el proceso
            ctx.log(f"Sin transcripción: {exc}")
            data = {"words": [], "segments": [], "source": "error", "error": str(exc)[:300]}
        video.transcript = data
        ctx.log(f"Transcripción: {len(data.get('words') or [])} palabras ({data.get('source')})")

    video.status = VideoStatus.ready.value
    ctx.progress(0.95, "Listo para cortar")

    # Los subtítulos ya han cumplido. El audio se lo queda el paso siguiente,
    # que aún lo necesita para oír los silencios, y lo borra al terminar.
    if ligero:
        for subtitulo in result.get("subtitles") or []:
            _borrar_temporal(ctx, subtitulo)

    enqueue(
        session,
        "process",
        {"video_id": video.id, "flow_id": flow.id, "audio_path": audio_temporal},
        priority=110,
        message=f"Cortar «{video.title[:60]}»",
    )
    events.log(
        session,
        f"Leído «{video.title[:70]}»" if ligero else f"Descargado «{video.title[:70]}»",
        level="success",
        scope="video",
        data={"video_id": video.id},
    )


# --------------------------------------------------------------------------
# 3. Cortar en clips
# --------------------------------------------------------------------------
@register("process")
def job_process(session: Session, ctx: JobContext) -> None:
    video = session.get(Video, int(ctx.payload["video_id"]))
    if not video:
        raise RuntimeError("El vídeo ya no existe.")

    flow = resolve_flow(session, ctx.payload.get("flow_id"), video)
    # En modo ligero no hay vídeo en el disco: se analiza sobre el audio, que
    # es lo único que se bajó, y se borra en cuanto se han elegido los momentos.
    audio_temporal = str(ctx.payload.get("audio_path") or "")
    analizable = video.local_path or audio_temporal
    if not analizable or not Path(analizable).exists():
        if not (video.transcript or {}).get("words") and not (video.transcript or {}).get("segments"):
            raise RuntimeError(
                "No hay ni vídeo ni transcripción con la que decidir dónde cortar."
            )
        analizable = ""          # sólo texto: suficiente para las estrategias de texto

    video.status = VideoStatus.processing.value
    session.commit()

    segment_config = step_config(flow.steps, "segment")
    metadata_config = step_config(flow.steps, "metadata")
    schedule_config = step_config(flow.steps, "schedule")
    reframe_config = step_config(flow.steps, "reframe")

    ctx.progress(0.1, "Buscando los mejores momentos…")
    candidates = segmenter.find_segments(
        media_path=analizable,
        duration=float(video.duration_s or 0),
        transcript=video.transcript or {},
        config=segment_config,
    )
    if not candidates:
        video.status = VideoStatus.done.value
        events.log(
            session,
            f"«{video.title[:60]}»: no se han generado clips (estrategia manual o vídeo corto)",
            level="warn",
            scope="clips",
        )
        return

    candidates = segmenter.shuffle_order(candidates, str(schedule_config.get("order", "score")))
    if schedule_config.get("order") == "score":
        candidates = sorted(candidates, key=lambda c: c["score"], reverse=True)

    # borramos los borradores anteriores del mismo vídeo (reprocesado)
    for old in list(video.clips):
        if old.status in {ClipStatus.draft.value, ClipStatus.failed.value}:
            session.delete(old)
    session.flush()

    channel = video.source.name if video.source else ""
    total = len(candidates)
    created: list[int] = []

    for index, candidate in enumerate(candidates, start=1):
        meta = metadata.build_metadata(
            config=metadata_config,
            video_title=video.title,
            channel=channel,
            hook=candidate.get("hook", ""),
            text=candidate.get("text", ""),
            index=index,
            total=total,
        )
        clip = Clip(
            video_id=video.id,
            flow_id=flow.id,
            index=index,
            title=meta["title"],
            hook=candidate.get("hook", "")[:300],
            caption=meta["caption"],
            hashtags=meta["hashtags"],
            start_s=candidate["start"],
            end_s=candidate["end"],
            score=candidate["score"],
            reason=candidate.get("reason", "")[:300],
            status=ClipStatus.draft.value,
            render_config={"reframe": reframe_config},
            words=transcript.slice_words(
                (video.transcript or {}).get("words") or [],
                candidate["start"],
                candidate["end"],
            ),
        )
        session.add(clip)
        session.flush()
        created.append(clip.id)
        ctx.progress(0.1 + 0.6 * index / total, f"{index}/{total} clips preparados")

    session.commit()

    # todos los clips se renderizan; el modo de publicación sólo decide qué
    # pasa después (publicar solo, revisar, borrador o exportar el archivo)
    for clip_id in created:
        enqueue(
            session,
            "render",
            {"clip_id": clip_id},
            priority=130,
            message="Renderizar clip",
        )

    video.status = VideoStatus.done.value

    # El audio ya ha cumplido su papel: los momentos están elegidos.
    _borrar_temporal(ctx, audio_temporal)

    events.log(
        session,
        f"«{video.title[:60]}»: {total} clip(s) generados",
        level="success",
        scope="clips",
        data={"video_id": video.id, "clips": total},
    )
    ctx.progress(1.0, f"{total} clips")


# --------------------------------------------------------------------------
# 4. Renderizar un clip
# --------------------------------------------------------------------------
@register("render")
def job_render(session: Session, ctx: JobContext) -> None:
    clip = session.get(Clip, int(ctx.payload["clip_id"]))
    if not clip:
        raise RuntimeError("El clip ya no existe.")
    video = clip.video
    flow = resolve_flow(session, clip.flow_id)
    reframe_config = dict(step_config(flow.steps, "reframe"))
    reframe_config.update((clip.render_config or {}).get("reframe") or {})
    subtitles_config = step_config(flow.steps, "subtitles")
    overlays_config = step_config(flow.steps, "overlays")
    audio_config = step_config(flow.steps, "audio")
    publish_config = step_config(flow.steps, "publish")
    schedule_config = step_config(flow.steps, "schedule")

    clip.status = ClipStatus.rendering.value
    clip.error = ""
    session.commit()

    # Sin original en el disco se baja **sólo este tramo**: unos segundos en
    # lugar del vídeo entero. El archivo es temporal y se borra al terminar.
    fuente = video.local_path if video.local_path and Path(video.local_path).exists() else ""
    tramo_temporal = ""
    desplazamiento = 0.0
    if not fuente:
        margen = 1.5      # un pelín de aire por si el corte cae entre keyframes
        desde = max(0.0, clip.start_s - margen)
        hasta = clip.end_s + margen
        ctx.progress(0.05, f"Bajando {hasta - desde:.0f}s de vídeo…")
        try:
            tramo_temporal = youtube_service.download_sections(
                video.url,
                [(desde, hasta)],
                quality=str(step_config(flow.steps, "ingest").get("quality", "1080")),
                cookies_from_browser=step_config(flow.steps, "ingest").get(
                    "cookies_from_browser", ""
                ),
                destination=settings.work_path,
                on_progress=lambda ratio, etiqueta: ctx.progress(0.05 + ratio * 0.2, etiqueta),
            )
        except youtube_service.RateLimited as exc:
            clip.status = ClipStatus.draft.value
            clip.error = str(exc)[:1000]
            enqueue(
                session, "render", {"clip_id": clip.id}, priority=140,
                run_at=utcnow() + timedelta(minutes=45),
                message="Reintentar el clip (YouTube nos frenó)",
            )
            ctx.progress(1.0, "Aplazado 45 minutos")
            return
        except Exception as exc:
            clip.status = ClipStatus.failed.value
            clip.error = youtube_service.traducir_error(exc)[:1000]
            raise RuntimeError(clip.error) from exc
        fuente = tramo_temporal
        desplazamiento = desde       # el tramo empieza en 0, no en clip.start_s
        ctx.log(
            f"Tramo descargado: {Path(fuente).stat().st_size / 1024 / 1024:.1f} MB "
            f"en vez del vídeo entero"
        )

    output = settings.clips_path / f"clip-{clip.id:05d}-{video.external_id}.mp4"
    ctx.log(f"Renderizando {clip.start_s:.1f}s → {clip.end_s:.1f}s")

    hook_variables = {
        "hook": clip.hook or clip.title,
        "titulo": video.title,
        "n": clip.index,
        "total": len(video.clips) or 1,
    }
    hook_text = metadata.render_template(
        str(overlays_config.get("hook_template", "{hook}")), hook_variables
    )

    result = renderer.render_clip(
        source_path=fuente,
        # si la fuente es un tramo suelto, sus tiempos empiezan en cero
        start=clip.start_s - desplazamiento,
        end=clip.end_s - desplazamiento,
        output_path=output,
        reframe=reframe_config,
        audio=audio_config,
        subtitles=subtitles_config,
        subtitles_enabled=step_enabled(flow.steps, "subtitles"),
        overlays=overlays_config,
        overlays_enabled=step_enabled(flow.steps, "overlays"),
        words=clip.words or [],
        hook_text=hook_text,
        has_audio=bool((video.probe or {}).get("has_audio", True)),
        on_progress=lambda ratio: ctx.progress(ratio * 0.95, f"Renderizando… {ratio * 100:.0f}%"),
    )

    clip.render_path = result["path"]
    clip.thumb_path = result.get("thumb", "")
    clip.render_config = {
        "reframe": reframe_config | {"focus_x": result.get("focus_x", 0.5)},
        "output": {
            "width": result.get("width"),
            "height": result.get("height"),
            "size": result.get("size"),
            "duration": result.get("duration"),
        },
    }
    clip.status = ClipStatus.rendered.value
    session.commit()
    ctx.progress(0.97, "Clip listo")

    # El tramo descargado ya está montado dentro del clip: fuera del disco.
    _borrar_temporal(ctx, tramo_temporal)

    mode = str(publish_config.get("mode", "review"))
    if mode in {"auto", "draft"} and schedule_config.get("auto_schedule", True):
        cuentas = destinations_for(session, video, publish_config)
        if cuentas:
            for cuenta in cuentas:
                schedule_clip(session, clip, cuenta, schedule_config)
        else:
            ctx.log("No hay ninguna cuenta conectada para publicar: el clip queda pendiente.")

    events.log(
        session,
        f"Clip listo: «{clip.title[:60]}»",
        level="success",
        scope="render",
        data={"clip_id": clip.id},
    )


# --------------------------------------------------------------------------
# 5. Programar
# --------------------------------------------------------------------------
def schedule_clip(
    session: Session,
    clip: Clip,
    account: Account,
    schedule_config: dict[str, Any] | None = None,
    *,
    when: datetime | None = None,
) -> Post:
    """Crea la publicación programada de un clip en una cuenta."""
    schedule_config = schedule_config or {}

    if when is None:
        slots = timing.plan_slots(
            session,
            account,
            1,
            max_per_day=int(schedule_config.get("max_per_day") or 0) or None,
            min_gap_hours=float(schedule_config.get("min_gap_hours") or 0) or None,
            spread_days=int(schedule_config.get("spread_days", 7) or 7),
            start_delay_hours=float(schedule_config.get("start_delay_hours", 2) or 0),
        )
        if slots:
            slot = slots[0]
        else:  # sin hueco válido: al día siguiente a la mejor hora disponible
            slot = {
                "utc": utcnow() + timedelta(days=1),
                "score": 0.0,
                "reason": "Sin hueco disponible en la ventana elegida",
            }
    else:
        slot = {"utc": when, "score": 0.0, "reason": "Programado a mano"}

    post = Post(
        clip_id=clip.id,
        account_id=account.id,
        scheduled_at=slot["utc"],
        caption=clip.caption,
        status=PostStatus.scheduled.value,
        slot_score=float(slot.get("score", 0)),
        slot_reason=str(slot.get("reason", ""))[:300],
    )
    session.add(post)
    clip.status = ClipStatus.scheduled.value
    session.flush()
    events.log(
        session,
        f"Programado «{clip.title[:50]}» en @{account.handle or account.display_name}",
        level="info",
        scope="agenda",
        data={"post_id": post.id, "clip_id": clip.id},
    )
    return post


# --------------------------------------------------------------------------
# 6. Publicar
# --------------------------------------------------------------------------
@register("publish")
def job_publish(session: Session, ctx: JobContext) -> None:
    post = session.get(Post, int(ctx.payload["post_id"]))
    if not post:
        raise RuntimeError("La publicación ya no existe.")
    if post.status in {PostStatus.published.value, PostStatus.cancelled.value}:
        return

    clip = post.clip
    account = post.account
    if not clip.render_path or not Path(clip.render_path).exists():
        raise RuntimeError("El clip no está renderizado.")

    flow = resolve_flow(session, clip.flow_id)
    publish_config = step_config(flow.steps, "publish")

    es_youtube = account.platform == Platform.youtube.value
    destino = "YouTube Shorts" if es_youtube else "TikTok"

    post.status = PostStatus.publishing.value
    clip.status = ClipStatus.publishing.value
    session.commit()
    ctx.progress(0.15, f"Subiendo a {destino}…")

    try:
        if es_youtube:
            result = _publish_to_youtube(session, ctx, post, clip, account, publish_config)
        else:
            result = _publish_to_tiktok(session, ctx, post, clip, account, publish_config)
    except QuotaAgotada as exc:
        # No es un error: simplemente hoy ya no toca. Se mueve a mañana.
        post.status = PostStatus.scheduled.value
        post.scheduled_at = utcnow() + timedelta(hours=24, minutes=5)
        post.slot_reason = "Aplazado: cuota diaria de YouTube agotada"
        clip.status = ClipStatus.scheduled.value
        notifications.notify(
            session,
            "Cuota de YouTube agotada por hoy",
            f"«{clip.title[:60]}» se publicará mañana. {exc}",
            kind="cuota",
            level="warn",
            action_label="Ver la agenda",
            action_url="#agenda",
            dedupe_hours=12,
        )
        events.log(session, str(exc), level="warn", scope="youtube")
        ctx.progress(1.0, "Aplazado a mañana")
        return
    except Exception as exc:
        post.status = PostStatus.failed.value
        post.error = str(exc)[:1000]
        clip.error = str(exc)[:1000]
        # El clip sólo se da por fallido si no le queda ninguna publicación viva:
        # con dos destinos, que falle TikTok no invalida el Short de YouTube.
        vivas = [
            otra for otra in clip.posts
            if otra.id != post.id
            and otra.status in {PostStatus.scheduled.value, PostStatus.published.value,
                                PostStatus.publishing.value}
        ]
        clip.status = (
            ClipStatus.published.value if any(
                o.status == PostStatus.published.value for o in vivas
            )
            else ClipStatus.scheduled.value if vivas
            else ClipStatus.failed.value
        )
        events.log(
            session,
            f"Fallo al publicar «{clip.title[:50]}» en {destino}: {exc}",
            level="error",
            scope="youtube" if es_youtube else "tiktok",
            data={"post_id": post.id},
        )
        raise

    post.status = PostStatus.published.value
    post.published_at = utcnow()
    post.publish_id = str(result.get("publish_id", ""))
    post.external_post_id = str(result.get("external_id", ""))
    post.share_url = str(result.get("share_url", ""))
    post.error = ""
    clip.status = ClipStatus.published.value
    ctx.progress(1.0, "Publicado")

    # Ya está publicado: el archivo no pinta nada en tu disco. Sólo se borra si
    # no le queda ninguna publicación pendiente en otra plataforma.
    session.flush()
    liberado = storage.after_publish(session, clip)
    if liberado:
        ctx.log(f"Liberados {liberado / 1024 / 1024:.1f} MB del disco")

    events.log(
        session,
        ("[simulación] " if result.get("dry_run") else "")
        + f"Publicado «{clip.title[:50]}» en {destino} "
        + f"(@{account.handle or account.display_name})",
        level="success",
        scope="youtube" if es_youtube else "tiktok",
        data={"post_id": post.id, "dry_run": bool(result.get("dry_run"))},
    )


def _publish_to_tiktok(session, ctx, post, clip, account, publish_config) -> dict[str, Any]:
    simulate = settings.dry_run or not tiktok.is_configured() or not (
        account.credentials or {}
    ).get("access_token")

    result = tiktok.publish_video(
        account.credentials or {},
        video_path=clip.render_path,
        caption=post.caption or clip.caption,
        mode="draft" if publish_config.get("mode") == "draft" else "auto",
        privacy_level=str(publish_config.get("privacy_level", "PUBLIC_TO_EVERYONE")),
        allow_comments=bool(publish_config.get("allow_comments", True)),
        allow_duet=bool(publish_config.get("allow_duet", True)),
        allow_stitch=bool(publish_config.get("allow_stitch", True)),
        commercial_content=bool(publish_config.get("commercial_content", False)),
        dry_run=simulate,
    )

    # las credenciales pueden haberse renovado durante la subida
    if not simulate:
        try:
            account.credentials = tiktok.valid_credentials(account.credentials or {})
        except Exception:
            pass

    return {
        "publish_id": result.get("publish_id", ""),
        "external_id": "",
        "share_url": result.get("share_url", ""),
        "dry_run": result.get("dry_run", False),
    }


def youtube_uploads_today(session: Session) -> int:
    """Shorts subidos en las últimas 24 h (la cuota de Google es diaria)."""
    desde = utcnow() - timedelta(hours=24)
    return len(
        session.execute(
            select(Post.id)
            .join(Account, Post.account_id == Account.id)
            .where(
                Account.platform == Platform.youtube.value,
                Post.status == PostStatus.published.value,
                Post.published_at >= desde,
            )
        ).all()
    )


class QuotaAgotada(RuntimeError):
    """La cuota diaria de YouTube no da para más subidas hoy."""


def _publish_to_youtube(session, ctx, post, clip, account, publish_config) -> dict[str, Any]:
    """Sube el clip vertical como Short al canal conectado."""
    simulate = settings.dry_run or not youtube_api.is_configured() or not (
        account.credentials or {}
    ).get("access_token")

    # Google sólo da para unas 6 subidas al día: si no queda cuota, se aplaza
    if not simulate:
        maximo = youtube_api.DAILY_QUOTA // youtube_api.COST_UPLOAD
        if youtube_uploads_today(session) >= maximo:
            raise QuotaAgotada(
                f"Hoy ya se han subido {maximo} Shorts, que es lo que da la cuota diaria "
                f"de la API de YouTube. Se reintentará mañana."
            )

    salida = (clip.render_config or {}).get("output") or {}
    avisos = youtube_api.validate_short(
        int(salida.get("width") or 0),
        int(salida.get("height") or 0),
        float(salida.get("duration") or clip.duration_s),
    )
    for aviso in avisos:
        ctx.log(f"Aviso: {aviso}")

    sufijo = str(publish_config.get("youtube_title_suffix", " #Shorts"))
    titulo = f"{clip.title}{sufijo}"[: youtube_api.MAX_TITLE]

    result = youtube_api.upload_short(
        account.credentials or {},
        video_path=clip.render_path,
        title=titulo,
        description=post.caption or clip.caption,
        tags=list(clip.hashtags or []),
        privacy_status=str(publish_config.get("youtube_privacy", "public")),
        made_for_kids=bool(publish_config.get("youtube_made_for_kids", False)),
        dry_run=simulate,
        on_progress=lambda ratio: ctx.progress(0.15 + ratio * 0.8, f"Subiendo… {ratio * 100:.0f}%"),
    )

    if not simulate:
        try:
            account.credentials = youtube_api.valid_credentials(account.credentials or {})
        except Exception:
            pass
        # la miniatura del clip sirve de portada si el canal está verificado
        if clip.thumb_path and result.get("video_id"):
            try:
                youtube_api.set_thumbnail(
                    account.credentials or {}, result["video_id"], clip.thumb_path
                )
            except Exception:
                pass

    return {
        "publish_id": result.get("video_id", ""),
        "external_id": result.get("video_id", ""),
        "share_url": result.get("url", ""),
        "dry_run": result.get("dry_run", False),
    }


# --------------------------------------------------------------------------
# 7. Métricas
# --------------------------------------------------------------------------
@register("refresh_metrics")
def job_refresh_metrics(session: Session, ctx: JobContext) -> None:
    account_id = ctx.payload.get("account_id")
    accounts = (
        [session.get(Account, int(account_id))]
        if account_id
        else session.scalars(select(Account).where(Account.enabled.is_(True))).all()
    )

    # --- YouTube: estadísticas de los Shorts que hemos subido -------------
    for account in [
        a for a in accounts if a and a.platform == Platform.youtube.value
    ]:
        credentials = account.credentials or {}
        if not credentials.get("access_token") or settings.dry_run:
            continue
        try:
            credentials = youtube_api.valid_credentials(credentials)
            account.credentials = credentials
            canal = youtube_api.fetch_channel(credentials)
            account.stats = {
                **(account.stats or {}),
                "subscribers": canal.get("subscribers", 0),
                "videos": canal.get("videos", 0),
                "views": canal.get("views", 0),
                "updated_at": utcnow().isoformat(),
            }

            publicaciones = session.scalars(
                select(Post).where(
                    Post.account_id == account.id,
                    Post.status == PostStatus.published.value,
                    Post.external_post_id != "",
                )
            ).all()
            estadisticas = youtube_api.fetch_video_stats(
                credentials, [p.external_post_id for p in publicaciones]
            )
            for post in publicaciones:
                datos = estadisticas.get(post.external_post_id)
                if not datos:
                    continue
                post.metrics = {
                    "views": datos["views"],
                    "likes": datos["likes"],
                    "comments": datos["comments"],
                }
                session.add(
                    MetricSample(
                        account_id=account.id,
                        post_id=post.id,
                        posted_at=post.published_at,
                        views=datos["views"],
                        likes=datos["likes"],
                        comments=datos["comments"],
                        followers=account.stats.get("subscribers", 0),
                        extra={"video_id": post.external_post_id},
                    )
                )
        except Exception as exc:
            account.status = AccountStatus.error.value
            account.status_detail = str(exc)[:400]
            ctx.log(f"{account.display_name}: {exc}")

    # --- TikTok -----------------------------------------------------------
    for account in [
        a for a in accounts if a and a.platform == Platform.tiktok.value
    ]:
        credentials = account.credentials or {}
        if not credentials.get("access_token") or settings.dry_run:
            continue
        try:
            credentials = tiktok.valid_credentials(credentials)
            account.credentials = credentials
            user = tiktok.fetch_user_info(credentials)
            account.stats = {
                **(account.stats or {}),
                "followers": user.get("follower_count", 0),
                "likes": user.get("likes_count", 0),
                "videos": user.get("video_count", 0),
                "updated_at": utcnow().isoformat(),
            }
            account.status = AccountStatus.connected.value
            account.status_detail = ""

            videos = tiktok.fetch_recent_videos(credentials, limit=20)
            by_publish_id = {
                post.external_post_id or post.publish_id: post
                for post in session.scalars(
                    select(Post).where(Post.account_id == account.id)
                ).all()
            }
            for item in videos:
                metrics = {
                    "views": item.get("view_count", 0),
                    "likes": item.get("like_count", 0),
                    "comments": item.get("comment_count", 0),
                    "shares": item.get("share_count", 0),
                }
                post = by_publish_id.get(item.get("id", ""))
                if post:
                    post.metrics = metrics
                    post.share_url = post.share_url or item.get("share_url", "")
                session.add(
                    MetricSample(
                        account_id=account.id,
                        post_id=post.id if post else None,
                        posted_at=(
                            datetime.fromtimestamp(
                                int(item["create_time"]), tz=timezone.utc
                            ).replace(tzinfo=None)
                            if item.get("create_time")
                            else None
                        ),
                        views=metrics["views"],
                        likes=metrics["likes"],
                        comments=metrics["comments"],
                        shares=metrics["shares"],
                        followers=account.stats.get("followers", 0),
                        extra={"video_id": item.get("id", "")},
                    )
                )
        except Exception as exc:  # no rompemos el ciclo por una cuenta
            account.status = AccountStatus.error.value
            account.status_detail = str(exc)[:400]
            ctx.log(f"{account.display_name}: {exc}")

    ctx.progress(1.0, "Métricas actualizadas")
