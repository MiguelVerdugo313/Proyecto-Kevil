"""Automatismos periódicos: vigilar canales, publicar a su hora y medir."""

from __future__ import annotations

from datetime import timedelta, timezone

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


def avisar_comunidad() -> None:
    """Las publicaciones de comunidad programadas cuya hora ha llegado."""
    from app.services import comunidad

    with session_scope() as session:
        comunidad.avisar_las_que_tocan(session)


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
    scheduler.add_job(
        avisar_comunidad,
        "interval",
        minutes=5,
        id="avisar_comunidad",
        replace_existing=True,
    )
    scheduler.start()
    with session_scope() as session:
        events.log(session, "Automatismos en marcha", level="info", scope="sistema")


def agenda_del_motor(session) -> dict:
    """Qué va a hacer el motor y cuándo, para que «sin tareas» no parezca parado.

    * la próxima vez que mira tus canales en busca de vídeos nuevos;
    * la próxima publicación programada;
    * lo que está esperando su reintento (YouTube que pidió calma, etc.).
    """
    from app.models import Job, JobStatus

    ahora = utcnow()
    intervalo = timedelta(minutes=max(1, settings.watch_interval_minutes))
    fuentes = session.scalars(
        select(Source).where(Source.enabled.is_(True), Source.auto_ingest.is_(True))
    ).all()

    revision = None
    tic = scheduler.get_job("watch_sources") if scheduler.running else None
    siguiente_tic = (
        tic.next_run_time.astimezone(timezone.utc).replace(tzinfo=None)
        if tic and tic.next_run_time else None
    )
    for fuente in fuentes:
        toca = (fuente.last_checked_at or ahora) + intervalo
        if siguiente_tic and toca < siguiente_tic:
            toca = siguiente_tic           # se mira en el siguiente repaso
        revision = toca if revision is None or toca < revision else revision

    post = session.scalars(
        select(Post)
        .where(Post.status == PostStatus.scheduled.value, Post.scheduled_at > ahora)
        .order_by(Post.scheduled_at)
        .limit(1)
    ).first()

    en_espera = session.scalars(
        select(Job)
        .where(Job.status == JobStatus.pending.value, Job.run_at > ahora)
        .order_by(Job.run_at)
        .limit(1)
    ).first()
    esperando = len(session.execute(
        select(Job.id).where(Job.status == JobStatus.pending.value, Job.run_at > ahora)
    ).all())

    def iso(fecha):
        return fecha.isoformat() + "Z" if fecha else None

    from app.services import canales

    return {
        "canales": len(fuentes),
        # conectado para publicar pero nadie lo vigila: eso no saca clips
        "sin_vigilar": [
            {"id": cuenta.id, "nombre": cuenta.display_name}
            for cuenta in canales.cuentas_sin_vigilar(session)
        ],
        "canal_con_error": next(
            (f.name for f in fuentes if f.last_error), ""
        ),
        "proxima_revision": iso(max(revision, ahora) if revision else None),
        "proxima_publicacion": iso(post.scheduled_at) if post else None,
        "proxima_publicacion_titulo": post.clip.title if post and post.clip else "",
        "reintento": iso(en_espera.run_at) if en_espera else None,
        "reintento_que": en_espera.message if en_espera else "",
        "esperando": esperando,
    }


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
