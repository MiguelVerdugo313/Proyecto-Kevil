"""Estado del sistema, panel, trabajos, eventos y ajustes."""

from __future__ import annotations

import shutil
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.common import event_to_dict, job_to_dict, post_to_dict
from app.bootstrap import current_settings, save_settings
from app.config import settings
from app.db import get_db
from app.models import (
    Account,
    Clip,
    ClipStatus,
    EventLog,
    Job,
    JobStatus,
    MetricSample,
    Platform,
    Post,
    PostStatus,
    Source,
    Video,
    utcnow,
)
from app.services import branding
from app.services import media as media_service
from app.services import tiktok, timing
from app.services.queue import enqueue

router = APIRouter(prefix="/api", tags=["sistema"])

VERSION = "1.0.0"


class SettingsIn(BaseModel):
    tiktok_client_key: str | None = None
    tiktok_client_secret: str | None = None
    youtube_api_key: str | None = None
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    dry_run: bool | None = None
    workers: int | None = None
    watch_interval_minutes: int | None = None
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    ai_primary: str | None = None
    openrouter_api_key: str | None = None
    openrouter_text_model: str | None = None
    openrouter_image_model: str | None = None
    nvidia_api_key: str | None = None
    nvidia_text_model: str | None = None
    nvidia_image_model: str | None = None
    brand_accent: str | None = None
    brand_accent_2: str | None = None
    brand_source: str | None = None
    channel_topic: str | None = None
    channel_language: str | None = None
    target_uploads_per_week: float | None = None
    notifications_desktop: bool | None = None


def _count(db: Session, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    for condition in conditions:
        query = query.where(condition)
    return int(db.scalar(query) or 0)


@router.get("/status")
def status(db: Session = Depends(get_db)):
    usage = shutil.disk_usage(settings.data_path)
    return {
        "version": VERSION,
        "ffmpeg": media_service.ffmpeg_ready(),
        "ffmpeg_path": settings.ffmpeg_path,
        "tiktok_configured": tiktok.is_configured(),
        "dry_run": settings.dry_run,
        "data_dir": str(settings.data_path),
        "disk_free_gb": round(usage.free / 1024**3, 1),
        "accounts": {
            "youtube": _count(db, Account, Account.platform == Platform.youtube.value),
            "tiktok": _count(db, Account, Account.platform == Platform.tiktok.value),
        },
        "jobs_running": _count(db, Job, Job.status == JobStatus.running.value),
        "jobs_pending": _count(db, Job, Job.status == JobStatus.pending.value),
        "clips_ready": _count(db, Clip, Clip.status == ClipStatus.rendered.value),
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    now = utcnow()
    week_ago = now - timedelta(days=7)

    upcoming = db.scalars(
        select(Post)
        .where(Post.status == PostStatus.scheduled.value)
        .order_by(Post.scheduled_at)
        .limit(8)
    ).all()

    review = db.scalars(
        select(Clip)
        .where(Clip.status == ClipStatus.rendered.value)
        .order_by(Clip.score.desc())
        .limit(8)
    ).all()

    jobs = db.scalars(
        select(Job)
        .where(Job.status.in_([JobStatus.running.value, JobStatus.pending.value]))
        .order_by(Job.priority, Job.created_at)
        .limit(8)
    ).all()

    recent_events = db.scalars(
        select(EventLog).order_by(EventLog.created_at.desc()).limit(12)
    ).all()

    views_week = int(
        db.scalar(
            select(func.coalesce(func.sum(MetricSample.views), 0)).where(
                MetricSample.captured_at >= week_ago
            )
        )
        or 0
    )

    # Se muestran las cuentas a las que se publica: TikTok y los canales de
    # YouTube que tengan permiso de subida.
    accounts = [
        cuenta for cuenta in db.scalars(
            select(Account).where(Account.enabled.is_(True))
        ).all()
        if cuenta.platform == Platform.tiktok.value
        or (cuenta.credentials or {}).get("access_token")
    ]
    account_cards = []
    for account in accounts:
        state = timing.account_state(db, account)
        account_cards.append(
            {
                "id": account.id,
                "platform": account.platform,
                "name": account.display_name,
                "handle": account.handle,
                "avatar_url": account.avatar_url,
                "followers": state["followers"],
                "health": timing.health_score(state),
                "maturity": state["maturity"],
                "recommended_per_day": state["recommended_per_day"],
                "published_7d": state["published_7d"],
                "scheduled": state["scheduled"],
                "using_history": state["using_history"],
                "best_hours": timing.best_hours(db, account, top=3),
            }
        )

    return {
        "counters": {
            "channels": _count(db, Source),
            "videos": _count(db, Video),
            "clips": _count(db, Clip),
            "clips_ready": _count(db, Clip, Clip.status == ClipStatus.rendered.value),
            "scheduled": _count(db, Post, Post.status == PostStatus.scheduled.value),
            "published_7d": _count(
                db,
                Post,
                Post.status == PostStatus.published.value,
                Post.published_at >= week_ago,
            ),
            "failed": _count(db, Post, Post.status == PostStatus.failed.value),
            "views_week": views_week,
        },
        "upcoming": [post_to_dict(p) for p in upcoming],
        "review": [
            {
                "id": clip.id,
                "title": clip.title,
                "score": round(clip.score, 2),
                "duration_s": round(clip.duration_s, 1),
                "video_title": clip.video.title if clip.video else "",
                "has_thumb": bool(clip.thumb_path),
            }
            for clip in review
        ],
        "jobs": [job_to_dict(j) for j in jobs],
        "events": [event_to_dict(e) for e in recent_events],
        "accounts": account_cards,
    }


# --------------------------------------------------------------------------
# Trabajos
# --------------------------------------------------------------------------
@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = 60, db: Session = Depends(get_db)):
    query = select(Job).order_by(Job.created_at.desc()).limit(max(1, min(300, limit)))
    if status:
        query = query.where(Job.status == status)
    return [job_to_dict(j) for j in db.scalars(query).all()]


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        return {"ok": False}
    job.status = JobStatus.pending.value
    job.error = ""
    job.progress = 0.0
    job.message = "Reintentando…"
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        return {"ok": False}
    if job.status == JobStatus.pending.value:
        job.status = JobStatus.cancelled.value
        db.commit()
    return {"ok": True}


@router.delete("/jobs/finished")
def clear_jobs(db: Session = Depends(get_db)):
    db.execute(
        delete(Job).where(
            Job.status.in_(
                [JobStatus.done.value, JobStatus.failed.value, JobStatus.cancelled.value]
            )
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/events")
def list_events(limit: int = 60, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(EventLog).order_by(EventLog.created_at.desc()).limit(max(1, min(300, limit)))
    ).all()
    return [event_to_dict(e) for e in rows]


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------
@router.get("/settings")
def get_settings_endpoint(db: Session = Depends(get_db)):
    return {
        "settings": current_settings(db),
        "ffmpeg": media_service.ffmpeg_ready(),
        "tiktok_redirect_uri": tiktok.redirect_uri(),
        "data_dir": str(settings.data_path),
        "version": VERSION,
    }


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db)):
    values: dict[str, Any] = {
        key: value for key, value in body.model_dump().items() if value is not None
    }
    # el marcador de secreto oculto no debe sobrescribir la clave real
    values = {k: v for k, v in values.items() if v != "••••••••"}
    applied = save_settings(db, values)
    db.commit()
    return {"applied": list(applied), "settings": current_settings(db)}


# --------------------------------------------------------------------------
# Colores de tu marca
# --------------------------------------------------------------------------
class BrandIn(BaseModel):
    accent: str | None = None
    accent_2: str | None = None
    account_id: int | None = None


@router.get("/branding")
def get_branding(db: Session = Depends(get_db)):
    """Tema actual y de qué canales se pueden sacar los colores."""
    canales = [
        {
            "id": account.id,
            "name": account.display_name,
            "avatar_url": account.avatar_url,
            "platform": account.platform,
        }
        for account in db.scalars(
            select(Account).where(Account.avatar_url != "").order_by(Account.id)
        ).all()
    ]
    return {
        "theme": branding.current_theme(),
        "accent": settings.brand_accent,
        "accent_2": settings.brand_accent_2,
        "source": settings.brand_source,
        "channels": canales,
        "default_accent": "#34D399",
    }


@router.post("/branding")
def set_branding(body: BrandIn, db: Session = Depends(get_db)):
    """Aplica un color a mano o lo saca del avatar de un canal."""
    if body.account_id:
        account = db.get(Account, body.account_id)
        if not account or not account.avatar_url:
            raise HTTPException(404, "Ese canal no tiene imagen de la que sacar colores.")
        try:
            tema = branding.extract_from_url(account.avatar_url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        origen = f"canal:{account.display_name}"
        principal = tema["source_accent"]
        secundario = (tema.get("palette") or [{}, {}])[1].get("hex", "") if tema.get("palette") else ""
    elif body.accent:
        principal = body.accent.strip()
        secundario = (body.accent_2 or "").strip()
        tema = branding.build_theme(principal, secundario)
        origen = "manual"
    else:
        raise HTTPException(400, "Indica un color o el canal del que sacarlo.")

    save_settings(
        db,
        {"brand_accent": principal, "brand_accent_2": secundario, "brand_source": origen},
    )
    db.commit()
    tema["custom"] = True
    tema["source"] = origen
    return {"theme": tema, "accent": principal, "accent_2": secundario, "source": origen}


@router.delete("/branding")
def reset_branding(db: Session = Depends(get_db)):
    save_settings(db, {"brand_accent": "", "brand_accent_2": "", "brand_source": ""})
    db.commit()
    return {"theme": {"custom": False}}


@router.post("/maintenance/refresh-metrics")
def refresh_metrics(db: Session = Depends(get_db)):
    enqueue(db, "refresh_metrics", {}, priority=200, message="Actualizar métricas")
    db.commit()
    return {"ok": True}
