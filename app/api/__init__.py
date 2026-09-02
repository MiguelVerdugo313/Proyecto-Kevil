"""Routers de la API."""

from app.api import accounts, analytics, clips, flows, schedule, sources, system, videos

ROUTERS = [
    system.router,
    accounts.router,
    sources.router,
    videos.router,
    flows.router,
    clips.router,
    schedule.router,
    analytics.router,
]

__all__ = ["ROUTERS"]
