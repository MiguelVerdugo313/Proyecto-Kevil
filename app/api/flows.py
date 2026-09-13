"""Flujos de trabajo editables."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import flow_to_dict
from app.db import get_db
from app.flow_schema import (
    FLOW_PRESETS,
    STEP_DEFINITIONS,
    default_steps,
    normalize_steps,
)
from app.models import Flow

router = APIRouter(prefix="/api/flows", tags=["flujos"])


class FlowIn(BaseModel):
    name: str
    description: str = ""
    icon: str = "⚡"
    preset: int | None = None
    steps: list[dict[str, Any]] | None = None


class FlowPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    icon: str | None = None
    enabled: bool | None = None
    steps: list[dict[str, Any]] | None = None


@router.get("/schema")
def get_schema():
    return {
        "steps": STEP_DEFINITIONS,
        "presets": [
            {"index": index, "name": p["name"], "icon": p["icon"], "description": p["description"]}
            for index, p in enumerate(FLOW_PRESETS)
        ],
    }


@router.get("")
def list_flows(db: Session = Depends(get_db)):
    flows = db.scalars(select(Flow).order_by(Flow.is_default.desc(), Flow.id)).all()
    return [flow_to_dict(f) for f in flows]


@router.get("/{flow_id}")
def get_flow(flow_id: int, db: Session = Depends(get_db)):
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(404, "Flujo no encontrado")
    flow.steps = normalize_steps(flow.steps)
    return flow_to_dict(flow)


@router.post("")
def create_flow(body: FlowIn, db: Session = Depends(get_db)):
    if body.steps is not None:
        steps = normalize_steps(body.steps)
    elif body.preset is not None and 0 <= body.preset < len(FLOW_PRESETS):
        steps = normalize_steps(FLOW_PRESETS[body.preset]["steps"])
    else:
        steps = default_steps()

    first = db.scalars(select(Flow).limit(1)).first() is None
    flow = Flow(
        name=body.name,
        description=body.description,
        icon=body.icon,
        steps=steps,
        is_default=first,
    )
    db.add(flow)
    db.commit()
    return flow_to_dict(flow)


@router.put("/{flow_id}")
@router.patch("/{flow_id}")
def update_flow(flow_id: int, body: FlowPatch, db: Session = Depends(get_db)):
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(404, "Flujo no encontrado")
    data = body.model_dump(exclude_none=True)
    if "steps" in data:
        data["steps"] = normalize_steps(data["steps"])
    for field, value in data.items():
        setattr(flow, field, value)
    db.commit()
    return flow_to_dict(flow)


@router.post("/{flow_id}/duplicate")
def duplicate_flow(flow_id: int, db: Session = Depends(get_db)):
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(404, "Flujo no encontrado")
    copy = Flow(
        name=f"{flow.name} (copia)",
        description=flow.description,
        icon=flow.icon,
        steps=normalize_steps(flow.steps),
    )
    db.add(copy)
    db.commit()
    return flow_to_dict(copy)


@router.post("/{flow_id}/default")
def set_default(flow_id: int, db: Session = Depends(get_db)):
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(404, "Flujo no encontrado")
    for other in db.scalars(select(Flow)).all():
        other.is_default = other.id == flow.id
    db.commit()
    return flow_to_dict(flow)


@router.delete("/{flow_id}")
def delete_flow(flow_id: int, db: Session = Depends(get_db)):
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(404, "Flujo no encontrado")
    remaining = db.scalars(select(Flow).where(Flow.id != flow.id).limit(1)).first()
    if remaining is None:
        raise HTTPException(400, "Debe quedar al menos un flujo.")
    was_default = flow.is_default
    db.delete(flow)
    db.flush()
    if was_default:
        remaining.is_default = True
    db.commit()
    return {"ok": True}
