"""Automatismos periódicos: vigilar canales, publicar a su hora y medir."""

from __future__ import annotations

from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.models import Post, PostStatus, Source, utcnow
from app.services import events
from app.services.queue import enqueue

scheduler = BackgroundScheduler(timezone="UTC")


def watch_sources() -> None:
    """Revisa los canales activos en busca de vídeos y directos nuevos."""
    with session_scope() as session:
        interval = timedelta(minutes=max(1, settings.watch_interval_minutes))
        sources = session.scalars(
            select(Source).where(Source.enabled.is_(True), Source.auto_ingest.is_(True))
        ).all()
        for source in sources:
            if source.last_checked_at and utcnow() - source.last_checked_at < interval:
                continue
            enqueue(
                session,
                "sync_source",
                {"source_id": source.id},
                priority=90,
                message=f"Revisar «{source.name}»",
            )


def dispatch_due_posts() -> None:
    """Manda a la cola las publicaciones cuya hora ya ha llegado."""
    with session_scope() as session:
        due = session.scalars(
            select(Post).where(
                Post.status == PostStatus.scheduled.value,
                Post.scheduled_at <= utcnow(),
            )
        ).all()
        for post in due:
            enqueue(
                session,
                "publish",
                {"post_id": post.id},
                priority=50,
                message=f"Publicar #{post.id}",
            )


def refresh_metrics() -> None:
    with session_scope() as session:
        enqueue(session, "refresh_metrics", {}, priority=200, message="Actualizar métricas")


def coach_check() -> None:
    """Repaso diario del canal: avisa si te retrasas con las subidas."""
    with session_scope() as session:
        enqueue(session, "coach_check", {}, priority=180, message="Revisar el canal")


def start() -> None:
    if scheduler.running:  # pragma: no cover
        return
    scheduler.add_job(
        watch_sources,
        "interval",
        minutes=max(1, settings.watch_interval_minutes),
        id="watch_sources",
        replace_existing=True,
    )
    scheduler.add_job(
        dispatch_due_posts,
        "interval",
        seconds=max(15, settings.publisher_interval_seconds),
        id="dispatch_posts",
        replace_existing=True,
    )
    scheduler.add_job(
        refresh_metrics,
        "interval",
        hours=6,
        id="refresh_metrics",
        replace_existing=True,
    )
    scheduler.add_job(
        coach_check,
        "interval",
        hours=12,
        id="coach_check",
        replace_existing=True,
    )
    scheduler.start()
    with session_scope() as session:
        events.log(session, "Automatismos en marcha", level="info", scope="sistema")


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
