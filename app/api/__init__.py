"""Routers de la API."""

from app.api import (
    accounts, analytics, clips, coach, flows, schedule, sources, studio, system, videos,
)

ROUTERS = [
    system.router,
    accounts.router,
    sources.router,
    videos.router,
    flows.router,
    clips.router,
    schedule.router,
    analytics.router,
    studio.router,
    coach.router,
]

__all__ = ["ROUTERS"]
