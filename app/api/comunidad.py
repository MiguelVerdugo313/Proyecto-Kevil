"""Contenido de comunidad: propuestas de encuestas, avisos y carruseles."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.services import ai, comunidad

router = APIRouter(prefix="/api/comunidad", tags=["comunidad"])


class ProponerIn(BaseModel):
    ia: bool = True


class CambioIn(BaseModel):
    estado: str | None = None
    cuando: str | None = None
    titulo: str | None = None
    texto: str | None = None
    opciones: list[str] | None = None


@router.get("")
def ver(db: Session = Depends(get_db)):
    ideas = comunidad.asegurar(db)
    db.commit()
    return {
        "ideas": ideas,
        "resumen": comunidad.resumen(db),
        "ia": ai.is_enabled(),
        "tipos": comunidad.TIPOS,
    }


@router.post("/proponer")
def proponer(body: ProponerIn, db: Session = Depends(get_db)):
    ideas = comunidad.proponer(db, usar_ia=body.ia)
    db.commit()
    return {"ideas": ideas, "resumen": comunidad.resumen(db)}


@router.patch("/{idea_id}")
def cambiar(idea_id: str, body: CambioIn, db: Session = Depends(get_db)):
    cambios: dict[str, Any] = body.model_dump(exclude_unset=True)
    idea = comunidad.cambiar(db, idea_id, **cambios)
    if idea is None:
        raise HTTPException(404, "Esa propuesta ya no existe")
    db.commit()
    return {"idea": idea, "resumen": comunidad.resumen(db)}
