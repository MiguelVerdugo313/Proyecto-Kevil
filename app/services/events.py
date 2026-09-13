"""Registro de actividad que se muestra en el panel."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import EventLog

MAX_EVENTS = 500


def log(
    session: Session,
    message: str,
    *,
    level: str = "info",
    scope: str = "app",
    data: dict[str, Any] | None = None,
) -> EventLog:
    event = EventLog(level=level, scope=scope, message=message, data=data or {})
    session.add(event)
    session.flush()

    # recorte del histórico para que la base de datos no crezca sin control
    total = session.scalar(select(EventLog.id).order_by(EventLog.id.desc()).limit(1)) or 0
    if total % 50 == 0:
        old = session.scalars(
            select(EventLog.id).order_by(EventLog.id.desc()).offset(MAX_EVENTS)
        ).all()
        if old:
            session.execute(delete(EventLog).where(EventLog.id.in_(old)))
    return event
