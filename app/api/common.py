"""Serializadores compartidos por la API."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import Account, Clip, EventLog, Flow, Job, Post, Source, Video


def iso(value: datetime | None) -> str | None:
    """Fecha en ISO marcada como UTC (así el navegador la pinta en hora local)."""
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


def naive_utc(value: datetime | None) -> datetime | None:
    """Normaliza a UTC sin zona: es como se guarda todo en la base de datos."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0)


def exists(path: str | None) -> bool:
    return bool(path) and Path(path).exists()


def account_to_dict(account: Account, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    credentials = account.credentials or {}
    data = {
        "id": account.id,
        "platform": account.platform,
        "display_name": account.display_name,
        "handle": account.handle,
        "external_id": account.external_id,
        "avatar_url": account.avatar_url,
        "status": account.status,
        "status_detail": account.status_detail,
        "enabled": account.enabled,
        "stats": account.stats or {},
        "strategy": account.strategy or {},
        "has_token": bool(credentials.get("access_token")),
        "created_at": iso(account.created_at),
    }
    if extra:
        data.update(extra)
    return data


def source_to_dict(source: Source) -> dict[str, Any]:
    return {
        "id": source.id,
        "account_id": source.account_id,
        "name": source.name,
        "url": source.url,
        "channel_id": source.channel_id,
        "kind": source.kind,
        "auto_ingest": source.auto_ingest,
        "include_lives": source.include_lives,
        "include_shorts": source.include_shorts,
        "min_duration_s": source.min_duration_s,
        "backfill_limit": source.backfill_limit,
        "flow_id": source.flow_id,
        "target_account_id": source.target_account_id,
        "last_checked_at": iso(source.last_checked_at),
        "last_error": source.last_error,
        "enabled": source.enabled,
    }


def video_to_dict(video: Video, *, with_transcript: bool = False) -> dict[str, Any]:
    transcript = video.transcript or {}
    data = {
        "id": video.id,
        "source_id": video.source_id,
        "source_name": video.source.name if video.source else "",
        "external_id": video.external_id,
        "origin": video.origin,
        "views": video.views,
        "title": video.title,
        "url": video.url,
        "thumbnail_url": video.thumbnail_url,
        "duration_s": round(video.duration_s or 0, 1),
        "published_at": iso(video.published_at),
        "was_live": video.was_live,
        "status": video.status,
        "error": video.error,
        "downloaded": exists(video.local_path),
        "clips_count": len(video.clips),
        "transcript_words": len(transcript.get("words") or []),
        "transcript_source": transcript.get("source", ""),
        "created_at": iso(video.created_at),
    }
    if with_transcript:
        data["transcript"] = transcript
        data["probe"] = video.probe or {}
    return data


def flow_to_dict(flow: Flow) -> dict[str, Any]:
    return {
        "id": flow.id,
        "name": flow.name,
        "description": flow.description,
        "icon": flow.icon,
        "is_default": flow.is_default,
        "enabled": flow.enabled,
        "steps": flow.steps or [],
        "updated_at": iso(flow.updated_at),
    }


def clip_to_dict(clip: Clip, *, with_words: bool = False) -> dict[str, Any]:
    post = clip.posts[0] if clip.posts else None
    data = {
        "id": clip.id,
        "video_id": clip.video_id,
        "video_title": clip.video.title if clip.video else "",
        "flow_id": clip.flow_id,
        "index": clip.index,
        "title": clip.title,
        "hook": clip.hook,
        "caption": clip.caption,
        "hashtags": clip.hashtags or [],
        "start_s": round(clip.start_s, 2),
        "end_s": round(clip.end_s, 2),
        "duration_s": round(clip.duration_s, 2),
        "score": round(clip.score, 3),
        "reason": clip.reason,
        "status": clip.status,
        "error": clip.error,
        "has_file": exists(clip.render_path),
        "has_thumb": exists(clip.thumb_path),
        "render_config": clip.render_config or {},
        "created_at": iso(clip.created_at),
        "post": post_to_dict(post) if post else None,
    }
    if with_words:
        data["words"] = clip.words or []
    return data


def post_to_dict(post: Post) -> dict[str, Any]:
    return {
        "id": post.id,
        "clip_id": post.clip_id,
        "account_id": post.account_id,
        "account_name": post.account.display_name if post.account else "",
        "account_handle": post.account.handle if post.account else "",
        "clip_title": post.clip.title if post.clip else "",
        "scheduled_at": iso(post.scheduled_at),
        "published_at": iso(post.published_at),
        "caption": post.caption,
        "status": post.status,
        "slot_score": round(post.slot_score, 3),
        "slot_reason": post.slot_reason,
        "share_url": post.share_url,
        "error": post.error,
        "metrics": post.metrics or {},
    }


def job_to_dict(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "kind": job.kind,
        "payload": job.payload or {},
        "status": job.status,
        "progress": round(job.progress or 0, 3),
        "message": job.message,
        "error": (job.error or "")[:600],
        "log": job.log or "",
        "attempts": job.attempts,
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
    }


def event_to_dict(event: EventLog) -> dict[str, Any]:
    return {
        "id": event.id,
        "created_at": iso(event.created_at),
        "level": event.level,
        "scope": event.scope,
        "message": event.message,
        "data": event.data or {},
    }
