"""Canales y listas vigiladas."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import source_to_dict
from app.db import get_db
from app.models import Source
from app.services.queue import enqueue

router = APIRouter(prefix="/api/sources", tags=["fuentes"])


class SourceIn(BaseModel):
    name: str | None = None
    url: str | None = None
    auto_ingest: bool | None = None
    include_lives: bool | None = None
    include_shorts: bool | None = None
    min_duration_s: int | None = None
    backfill_limit: int | None = None
    flow_id: int | None = None
    target_account_id: int | None = None
    enabled: bool | None = None


@router.get("")
def list_sources(db: Session = Depends(get_db)):
    return [source_to_dict(s) for s in db.scalars(select(Source).order_by(Source.id)).all()]


@router.patch("/{source_id}")
def patch_source(source_id: int, body: SourceIn, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Fuente no encontrada")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(source, field, value)
    db.commit()
    return source_to_dict(source)


@router.post("/{source_id}/sync")
def sync_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Fuente no encontrada")
    job = enqueue(
        db,
        "sync_source",
        {"source_id": source.id},
        priority=70,
        message=f"Revisar «{source.name}»",
    )
    db.commit()
    return {"job_id": job.id}


@router.delete("/{source_id}")
def delete_source(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(404, "Fuente no encontrada")
    db.delete(source)
    db.commit()
    return {"ok": True}
