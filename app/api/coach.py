"""Asistente del canal: cadencia, avisos e ideas de contenido."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import iso
from app.db import get_db
from app.models import Idea, Notification
from app.services import ai, coach, notifications
from app.services.queue import enqueue

router = APIRouter(prefix="/api", tags=["coach"])


class IdeasRequest(BaseModel):
    count: int = 6
    validate_demand: bool = True


class IdeaPatch(BaseModel):
    status: str | None = None


class AITest(BaseModel):
    provider: str | None = None


def idea_to_dict(idea: Idea) -> dict:
    return {
        "id": idea.id,
        "created_at": iso(idea.created_at),
        "topic": idea.topic,
        "title": idea.title,
        "hook": idea.hook,
        "angle": idea.angle,
        "reason": idea.reason,
        "tags": idea.tags or [],
        "score": round(idea.score, 3),
        "demand": round(idea.demand, 3),
        "competition": round(idea.competition, 3),
        "evidence": idea.evidence or {},
        "source": idea.source,
        "status": idea.status,
    }


def notification_to_dict(item: Notification) -> dict:
    return {
        "id": item.id,
        "created_at": iso(item.created_at),
        "kind": item.kind,
        "level": item.level,
        "title": item.title,
        "body": item.body,
        "action_label": item.action_label,
        "action_url": item.action_url,
        "read": item.read_at is not None,
        "data": item.data or {},
    }


# --------------------------------------------------------------------------
# Coach
# --------------------------------------------------------------------------
@router.get("/coach")
def get_coach(db: Session = Depends(get_db)):
    data = coach.recommendation(db)
    data["days"] = coach.DAYS
    data["ai"] = ai.status()
    return data


@router.post("/coach/check")
def run_check(db: Session = Depends(get_db)):
    job = enqueue(db, "coach_check", {}, priority=60, message="Revisar el canal")
    db.commit()
    return {"job_id": job.id}


# --------------------------------------------------------------------------
# Avisos
# --------------------------------------------------------------------------
@router.get("/notifications")
def list_notifications(limit: int = 30, only_unread: bool = False, db: Session = Depends(get_db)):
    query = select(Notification).order_by(Notification.created_at.desc()).limit(
        max(1, min(200, limit))
    )
    if only_unread:
        query = query.where(Notification.read_at.is_(None))
    rows = db.scalars(query).all()
    return {
        "unread": notifications.unread_count(db),
        "items": [notification_to_dict(row) for row in rows],
    }


@router.post("/notifications/read")
def read_notifications(notification_id: int | None = None, db: Session = Depends(get_db)):
    total = notifications.mark_read(db, notification_id)
    db.commit()
    return {"marked": total, "unread": notifications.unread_count(db)}


# --------------------------------------------------------------------------
# Ideas
# --------------------------------------------------------------------------
@router.get("/ideas")
def list_ideas(status: str | None = None, limit: int = 40, db: Session = Depends(get_db)):
    query = (
        select(Idea)
        .order_by(Idea.status == "descartada", Idea.score.desc(), Idea.created_at.desc())
        .limit(max(1, min(200, limit)))
    )
    if status:
        query = query.where(Idea.status == status)
    return [idea_to_dict(row) for row in db.scalars(query).all()]


@router.post("/ideas/generate")
def generate_ideas(body: IdeasRequest, db: Session = Depends(get_db)):
    job = enqueue(
        db,
        "generate_ideas",
        {"count": max(1, min(12, body.count)), "validate": body.validate_demand},
        priority=70,
        message="Buscar ideas de contenido",
        dedupe=False,
    )
    db.commit()
    return {"job_id": job.id}


@router.patch("/ideas/{idea_id}")
def patch_idea(idea_id: int, body: IdeaPatch, db: Session = Depends(get_db)):
    idea = db.get(Idea, idea_id)
    if not idea:
        raise HTTPException(404, "Idea no encontrada")
    if body.status in {"nueva", "guardada", "descartada"}:
        idea.status = body.status
    db.commit()
    return idea_to_dict(idea)


@router.delete("/ideas/{idea_id}")
def delete_idea(idea_id: int, db: Session = Depends(get_db)):
    idea = db.get(Idea, idea_id)
    if not idea:
        raise HTTPException(404, "Idea no encontrada")
    db.delete(idea)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Inteligencia artificial
# --------------------------------------------------------------------------
@router.get("/ai/status")
def ai_status():
    return ai.status()


@router.post("/ai/test")
def ai_test():
    try:
        return ai.test_connection()
    except ai.AINotConfigured as exc:
        raise HTTPException(400, str(exc)) from exc
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc
