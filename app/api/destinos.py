"""Dónde se publica cada clip (TikTok, YouTube Shorts o los dos)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Clip, Flow
from app.services import destinos, events

router = APIRouter(prefix="/api", tags=["destinos"])


class DestinosIn(BaseModel):
    tiktok: bool | None = None
    shorts: bool | None = None


@router.get("/destinos")
def ver_destinos(db: Session = Depends(get_db)):
    return destinos.resumen(db)


@router.put("/destinos/{flow_id}")
def cambiar_destinos(flow_id: int, body: DestinosIn, db: Session = Depends(get_db)):
    flow = db.get(Flow, flow_id)
    if not flow:
        raise HTTPException(404, "Flujo no encontrado")
    destinos.cambiar(flow, tiktok=body.tiktok, shorts=body.shorts)
    marcas = destinos.de_flujo(flow)
    donde = " y ".join(
        nombre for nombre, activo in (("TikTok", marcas["tiktok"]), ("YouTube Shorts", marcas["shorts"]))
        if activo
    ) or "ningún sitio (sólo se exportan)"
    events.log(db, f"«{flow.name}» publica ahora en {donde}", level="info", scope="flujos")
    db.commit()
    return destinos.resumen(db)


@router.get("/clips/{clip_id}/destinos")
def destinos_del_clip(clip_id: int, db: Session = Depends(get_db)):
    clip = db.get(Clip, clip_id)
    if not clip:
        raise HTTPException(404, "Clip no encontrado")
    return destinos.para_clip(db, clip)
