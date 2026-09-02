"""Preparación inicial: flujos de ejemplo y ajustes guardados."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.flow_schema import FLOW_PRESETS, normalize_steps
from app.models import Flow, Setting

# Ajustes que se pueden cambiar desde la interfaz y se guardan en la base de datos
EDITABLE_SETTINGS = {
    "tiktok_client_key": str,
    "tiktok_client_secret": str,
    "youtube_api_key": str,
    "dry_run": bool,
    "workers": int,
    "watch_interval_minutes": int,
    "ffmpeg_path": str,
    "ffprobe_path": str,
}

SECRET_SETTINGS = {"tiktok_client_secret", "youtube_api_key"}


def seed_flows(session: Session) -> None:
    if session.scalars(select(Flow).limit(1)).first():
        return
    for index, preset in enumerate(FLOW_PRESETS):
        session.add(
            Flow(
                name=preset["name"],
                description=preset["description"],
                icon=preset["icon"],
                steps=normalize_steps(preset["steps"]),
                is_default=index == 0,
            )
        )


def load_setting_overrides(session: Session) -> None:
    """Aplica los ajustes guardados sobre la configuración en memoria."""
    rows = session.scalars(select(Setting)).all()
    for row in rows:
        if row.key not in EDITABLE_SETTINGS or row.value in (None, ""):
            continue
        caster = EDITABLE_SETTINGS[row.key]
        try:
            setattr(settings, row.key, caster(row.value))
        except (TypeError, ValueError):
            continue


def save_settings(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    applied: dict[str, Any] = {}
    for key, value in values.items():
        if key not in EDITABLE_SETTINGS:
            continue
        caster = EDITABLE_SETTINGS[key]
        try:
            value = caster(value)
        except (TypeError, ValueError):
            continue
        row = session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=value)
            session.add(row)
        else:
            row.value = value
        setattr(settings, key, value)
        applied[key] = value
    return applied


def current_settings(session: Session) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in EDITABLE_SETTINGS:
        value = getattr(settings, key, None)
        if key in SECRET_SETTINGS and value:
            value = "••••••••"
        result[key] = value
    return result


def run() -> None:
    with session_scope() as session:
        load_setting_overrides(session)
        seed_flows(session)
