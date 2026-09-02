"""Calendario de publicaciones."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import naive_utc, post_to_dict
from app.db import get_db
from app.models import Account, ClipStatus, Platform, Post, PostStatus, utcnow
from app.services import events, timing
from app.services.queue import enqueue

router = APIRouter(prefix="/api", tags=["agenda"])


class PostPatch(BaseModel):
    scheduled_at: datetime | None = None
    caption: str | None = None


class PlanIn(BaseModel):
    account_id: int
    count: int = 5
    spread_days: int = 7
    max_per_day: int | None = None
    min_gap_hours: float | None = None
    start_delay_hours: float = 2


@router.get("/posts")
def list_posts(
    status: str | None = None,
    account_id: int | None = None,
    days: int = 21,
    include_past: bool = True,
    db: Session = Depends(get_db),
):
    query = select(Post).order_by(Post.scheduled_at)
    if status:
        query = query.where(Post.status == status)
    if account_id:
        query = query.where(Post.account_id == account_id)
    start = utcnow() - timedelta(days=days if include_past else 0)
    query = query.where(Post.scheduled_at >= start)
    query = query.where(Post.scheduled_at <= utcnow() + timedelta(days=max(1, days)))
    return [post_to_dict(p) for p in db.scalars(query).all()]


@router.patch("/posts/{post_id}")
def patch_post(post_id: int, body: PostPatch, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Publicación no encontrada")
    if post.status not in {PostStatus.scheduled.value, PostStatus.failed.value}:
        raise HTTPException(400, "Sólo se pueden cambiar las publicaciones pendientes.")
    if body.scheduled_at is not None:
        post.scheduled_at = naive_utc(body.scheduled_at)
        post.slot_reason = "Movido a mano"
        post.status = PostStatus.scheduled.value
    if body.caption is not None:
        post.caption = body.caption
    db.commit()
    return post_to_dict(post)


@router.post("/posts/{post_id}/publish-now")
def publish_now(post_id: int, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Publicación no encontrada")
    post.scheduled_at = utcnow()
    post.status = PostStatus.scheduled.value
    job = enqueue(db, "publish", {"post_id": post.id}, priority=10, message="Publicar ahora")
    db.commit()
    return {"job_id": job.id}


@router.delete("/posts/{post_id}")
def cancel_post(post_id: int, db: Session = Depends(get_db)):
    post = db.get(Post, post_id)
    if not post:
        raise HTTPException(404, "Publicación no encontrada")
    post.status = PostStatus.cancelled.value
    if post.clip and post.clip.status == ClipStatus.scheduled.value:
        post.clip.status = ClipStatus.rendered.value
    events.log(db, f"Publicación cancelada #{post.id}", level="info", scope="agenda")
    db.commit()
    return {"ok": True}


@router.post("/schedule/plan")
def plan(body: PlanIn, db: Session = Depends(get_db)):
    """Vista previa de los próximos huecos que elegiría el motor."""
    account = db.get(Account, body.account_id)
    if not account or account.platform != Platform.tiktok.value:
        raise HTTPException(404, "Cuenta de TikTok no encontrada")
    slots = timing.plan_slots(
        db,
        account,
        max(1, min(30, body.count)),
        max_per_day=body.max_per_day,
        min_gap_hours=body.min_gap_hours,
        spread_days=body.spread_days,
        start_delay_hours=body.start_delay_hours,
    )
    return [
        {
            "utc": slot["utc"].replace(microsecond=0).isoformat() + "Z",
            "local": slot["local"].replace(microsecond=0).isoformat(),
            "score": slot["score"],
            "reason": slot["reason"],
        }
        for slot in slots
    ]


@router.get("/schedule/heatmap")
def heatmap(account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Cuenta no encontrada")
    data = timing.combined_heatmap(db, account)
    data["days"] = timing.DAYS
    data["best_hours"] = timing.best_hours(db, account, top=6)
    return data
