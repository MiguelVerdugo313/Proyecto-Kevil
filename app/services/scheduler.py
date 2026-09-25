"""Automatismos periódicos: vigilar canales, publicar a su hora y medir."""

from __future__ import annotations

from datetime import timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.models import Post, PostStatus, Source, utcnow
from app.services import events, pipeline
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


# Si el PC estaba apagado a la hora de publicar y han pasado más de esto, no se
# publica «a destiempo» (a las 3 de la mañana): se busca el siguiente buen hueco.
RETRASO_MAXIMO = timedelta(hours=2)
REINTENTO_PROGRAMAR = timedelta(minutes=60)


def dispatch_due_posts() -> None:
    """Manda a la cola lo que toca publicar y deja programado lo que se pueda."""
    with session_scope() as session:
        ahora = utcnow()
        due = session.scalars(
            select(Post).where(
                Post.status == PostStatus.scheduled.value,
                Post.scheduled_at <= ahora,
            )
        ).all()
        for post in due:
            if post.en_plataforma:
                # YouTube lo ha publicado él solo a su hora
                pipeline.marcar_salido_en_plataforma(session, post)
                continue
            if ahora - post.scheduled_at > RETRASO_MAXIMO and _recolocar(session, post):
                continue
            enqueue(
                session,
                "publish",
                {"post_id": post.id},
                priority=50,
                message=f"Publicar #{post.id}",
            )
        _programar_en_youtube(session)


def _recolocar(session, post: Post) -> bool:
    """El ordenador estaba apagado a su hora: al siguiente buen hueco."""
    from app.flow_schema import step_config

    clip = post.clip
    if clip is None or post.account is None:
        return False
    if _en_la_cola(session, post):
        # no es que el PC estuviera apagado: está esperando turno en la cola
        return False
    antes = post.scheduled_at
    flow = pipeline.resolve_flow(session, clip.flow_id)
    hueco = pipeline.proponer_hora(session, post.account, step_config(flow.steps, "schedule"))
    post.scheduled_at = hueco["utc"]
    post.slot_reason = f"Recolocado (el PC estaba apagado): {hueco['reason']}"[:300]
    from app.services import notifications, timing

    zona = timing.get_zone(timing.zona_local())

    def a_las(fecha) -> str:
        local = timing.to_local(fecha, zona)
        return f"{local:%d/%m} a las {timing.hora_12(local.hour, local.minute)}"

    notifications.notify(
        session,
        "Un clip no salió a su hora: lo he movido",
        f"«{clip.title[:60]}» tocaba el {a_las(antes)} y Kevil estaba cerrado. "
        f"Nueva hora: {a_las(post.scheduled_at)}. Para que no pase, deja Kevil en "
        "segundo plano o actívalo al arrancar Windows (Ajustes).",
        kind="agenda",
        level="warn",
        action_label="Ver la agenda",
        action_url="#agenda",
        dedupe_hours=0,
    )
    events.log(
        session,
        f"Recolocado «{clip.title[:50]}»: el PC estaba apagado a su hora",
        level="warn",
        scope="agenda",
        data={"post_id": post.id},
    )
    return True


def _en_la_cola(session, post: Post) -> bool:
    from app.models import Job, JobStatus

    return any(
        (job.payload or {}).get("post_id") == post.id
        for job in session.scalars(
            select(Job).where(
                Job.kind == "publish",
                Job.status.in_([JobStatus.pending.value, JobStatus.running.value]),
            )
        ).all()
    )


def _programar_en_youtube(session) -> None:
    """Los Shorts aprobados se suben ya, programados dentro de YouTube."""
    from app.models import Account, Clip, Platform

    ahora = utcnow()
    candidatos = session.scalars(
        select(Post)
        .join(Account, Post.account_id == Account.id)
        .join(Clip, Post.clip_id == Clip.id)
        .where(
            Account.platform == Platform.youtube.value,
            Post.status == PostStatus.scheduled.value,
            Post.en_plataforma.is_(False),
            Post.scheduled_at > ahora + pipeline.MARGEN_PROGRAMAR + timedelta(minutes=5),
            # sólo lo que ya tiene su vídeo montado (lo demás no ocupa sitio)
            Clip.render_path != "",
        )
        .order_by(Post.scheduled_at)
        .limit(12)
    ).all()
    for post in candidatos:
        if not pipeline.puede_programar_en_youtube(post.account, post):
            continue
        clip = post.clip
        if not clip or not clip.render_path:
            continue
        intento = (post.metrics or {}).get("intento_programar")
        if intento and ahora.isoformat() < _mas(intento, REINTENTO_PROGRAMAR):
            continue
        post.metrics = {**(post.metrics or {}), "intento_programar": ahora.isoformat()}
        enqueue(
            session,
            "publish",
            {"post_id": post.id, "programar": True},
            priority=60,
            message=f"Dejar programado en YouTube #{post.id}",
        )


def _mas(iso: str, delta: timedelta) -> str:
    from datetime import datetime

    try:
        return (datetime.fromisoformat(iso) + delta).isoformat()
    except ValueError:
        return ""


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
