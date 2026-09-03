"""Analítica: qué se ha publicado y cómo ha funcionado."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import iso
from app.db import get_db
from app.models import Account, Platform, Post, PostStatus, utcnow
from app.services import timing

router = APIRouter(prefix="/api/analytics", tags=["analítica"])


@router.get("/overview")
def overview(days: int = 30, account_id: int | None = None, db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=max(1, min(180, days)))

    query = select(Post).where(
        Post.status == PostStatus.published.value, Post.published_at >= since
    )
    if account_id:
        query = query.where(Post.account_id == account_id)
    posts = db.scalars(query.order_by(Post.published_at)).all()

    by_day: dict[str, dict[str, float]] = {}
    for post in posts:
        key = post.published_at.date().isoformat()
        bucket = by_day.setdefault(key, {"posts": 0, "views": 0, "likes": 0})
        bucket["posts"] += 1
        bucket["views"] += float((post.metrics or {}).get("views") or 0)
        bucket["likes"] += float((post.metrics or {}).get("likes") or 0)

    series = [
        {"date": day, **{k: int(v) for k, v in values.items()}}
        for day, values in sorted(by_day.items())
    ]

    top = sorted(
        posts, key=lambda p: float((p.metrics or {}).get("views") or 0), reverse=True
    )[:10]

    accounts = []
    for account in db.scalars(select(Account)).all():
        if account.platform != Platform.tiktok.value and not (
            account.credentials or {}
        ).get("access_token"):
            continue
        state = timing.account_state(db, account)
        accounts.append(
            {
                "id": account.id,
                "platform": account.platform,
                "name": account.display_name,
                "handle": account.handle,
                "state": state,
                "health": timing.health_score(state),
                "best_hours": timing.best_hours(db, account, top=5),
            }
        )

    total_views = sum(float((p.metrics or {}).get("views") or 0) for p in posts)
    return {
        "range_days": days,
        "totals": {
            "published": len(posts),
            "views": int(total_views),
            "avg_views": int(total_views / len(posts)) if posts else 0,
            "likes": int(sum(float((p.metrics or {}).get("likes") or 0) for p in posts)),
        },
        "series": series,
        "top": [
            {
                "id": post.id,
                "clip_id": post.clip_id,
                "title": post.clip.title if post.clip else "",
                "published_at": iso(post.published_at),
                "views": int((post.metrics or {}).get("views") or 0),
                "likes": int((post.metrics or {}).get("likes") or 0),
                "share_url": post.share_url,
            }
            for post in top
        ],
        "accounts": accounts,
    }
