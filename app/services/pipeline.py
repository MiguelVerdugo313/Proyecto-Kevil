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
    Platform,
    Post,
    PostStatus,
    Source,
    Video,
    VideoStatus,
    utcnow,
)
from app.services import events, metadata, renderer, segmenter, timing, tiktok, transcript
from app.services import media as media_service
from app.services import youtube as youtube_service
from app.services.queue import JobContext, enqueue, register


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def resolve_flow(session: Session, flow_id: int | None) -> Flow:
    flow: Flow | None = None
    if flow_id:
        flow = session.get(Flow, flow_id)
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
    flow = resolve_flow(session, ctx.payload.get("flow_id"))
    ingest_config = step_config(flow.steps, "ingest")

    video.status = VideoStatus.downloading.value
    video.error = ""
    session.commit()
    ctx.log(f"Descargando {video.url}")

    def on_progress(ratio: float, label: str) -> None:
        ctx.progress(ratio * 0.7, label)

    try:
        result = youtube_service.download_video(
            video.url,
            quality=str(ingest_config.get("quality", "1080")),
            download_subtitles=bool(ingest_config.get("download_subtitles", True)),
            subtitle_langs=list(ingest_config.get("subtitle_langs") or ["es", "en"]),
            cookies_from_browser=ingest_config.get("cookies_from_browser", ""),
            on_progress=on_progress,
        )
    except Exception as exc:
        video.status = VideoStatus.error.value
        video.error = str(exc)[:1000]
        events.log(session, f"Error al descargar «{video.title}»: {exc}", level="error", scope="video")
        raise

    video.local_path = result["path"]
    info = result.get("info") or {}
    video.title = video.title or info.get("title", "")
    video.was_live = video.was_live or bool(info.get("was_live"))
    ctx.progress(0.75, "Analizando el archivo…")

    probe = media_service.probe(video.local_path)
    video.probe = probe
    video.duration_s = probe.get("duration") or video.duration_s

    # --- transcripción ---------------------------------------------------
    if step_enabled(flow.steps, "transcribe"):
        transcribe_config = step_config(flow.steps, "transcribe")
        ctx.progress(0.8, "Obteniendo la transcripción…")
        try:
            data = transcript.build_transcript(
                engine=str(transcribe_config.get("engine", "youtube")),
                media_path=video.local_path,
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

    enqueue(
        session,
        "process",
        {"video_id": video.id, "flow_id": flow.id},
        priority=110,
        message=f"Cortar «{video.title[:60]}»",
    )
    events.log(
        session,
        f"Descargado «{video.title[:70]}»",
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
    if not video.local_path or not Path(video.local_path).exists():
        raise RuntimeError("El vídeo original no está descargado.")

    flow = resolve_flow(session, ctx.payload.get("flow_id"))
    video.status = VideoStatus.processing.value
    session.commit()

    segment_config = step_config(flow.steps, "segment")
    metadata_config = step_config(flow.steps, "metadata")
    schedule_config = step_config(flow.steps, "schedule")
    reframe_config = step_config(flow.steps, "reframe")

    ctx.progress(0.1, "Buscando los mejores momentos…")
    candidates = segmenter.find_segments(
        media_path=video.local_path,
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
    if not video.local_path or not Path(video.local_path).exists():
        raise RuntimeError("Falta el vídeo original: vuelve a descargarlo.")

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
        source_path=video.local_path,
        start=clip.start_s,
        end=clip.end_s,
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

    mode = str(publish_config.get("mode", "review"))
    if mode in {"auto", "draft"} and schedule_config.get("auto_schedule", True):
        account = target_account_for(session, video)
        if account:
            schedule_clip(session, clip, account, schedule_config)
        else:
            ctx.log("No hay ninguna cuenta de TikTok conectada: el clip queda pendiente.")

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

    post.status = PostStatus.publishing.value
    clip.status = ClipStatus.publishing.value
    session.commit()
    ctx.progress(0.15, "Subiendo a TikTok…")

    simulate = settings.dry_run or not tiktok.is_configured() or not (
        account.credentials or {}
    ).get("access_token")

    try:
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
    except Exception as exc:
        post.status = PostStatus.failed.value
        post.error = str(exc)[:1000]
        clip.status = ClipStatus.failed.value
        clip.error = str(exc)[:1000]
        events.log(
            session,
            f"Fallo al publicar «{clip.title[:50]}»: {exc}",
            level="error",
            scope="tiktok",
            data={"post_id": post.id},
        )
        raise

    # las credenciales pueden haberse renovado durante la subida
    if not simulate:
        try:
            account.credentials = tiktok.valid_credentials(account.credentials or {})
        except Exception:
            pass

    post.status = PostStatus.published.value
    post.published_at = utcnow()
    post.publish_id = str(result.get("publish_id", ""))
    post.share_url = str(result.get("share_url", ""))
    post.error = ""
    clip.status = ClipStatus.published.value
    ctx.progress(1.0, "Publicado")

    events.log(
        session,
        ("[simulación] " if result.get("dry_run") else "")
        + f"Publicado «{clip.title[:50]}» en @{account.handle or account.display_name}",
        level="success",
        scope="tiktok",
        data={"post_id": post.id, "dry_run": bool(result.get("dry_run"))},
    )


# --------------------------------------------------------------------------
# 7. Métricas
# --------------------------------------------------------------------------
@register("refresh_metrics")
def job_refresh_metrics(session: Session, ctx: JobContext) -> None:
    from app.models import MetricSample

    account_id = ctx.payload.get("account_id")
    accounts = (
        [session.get(Account, int(account_id))]
        if account_id
        else session.scalars(
            select(Account).where(
                Account.platform == Platform.tiktok.value, Account.enabled.is_(True)
            )
        ).all()
    )

    for account in [a for a in accounts if a]:
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
