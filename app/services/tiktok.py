"""Cliente de la API de TikTok (login, publicación y métricas).

Se usa la API oficial *Content Posting API v2*. Para que funcione hay que crear
una app en https://developers.tiktok.com con los permisos:

    user.info.basic, user.info.profile, user.info.stats,
    video.publish, video.upload, video.list

y añadir como *Redirect URI*:  http://127.0.0.1:8756/api/oauth/tiktok/callback

Si no hay credenciales configuradas, o si está activado el modo simulación, la
aplicación sigue funcionando de principio a fin sin publicar nada de verdad.
"""

from __future__ import annotations

import math
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import settings

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
API_BASE = "https://open.tiktokapis.com/v2"

SCOPES = [
    "user.info.basic",
    "user.info.profile",
    "user.info.stats",
    "video.publish",
    "video.upload",
    "video.list",
]

CHUNK_SIZE = 32 * 1024 * 1024  # 32 MB (el límite de TikTok es 64 MB)
TIMEOUT = httpx.Timeout(60.0, read=300.0)


class TikTokError(RuntimeError):
    pass


def is_configured() -> bool:
    return bool(settings.tiktok_client_key and settings.tiktok_client_secret)


def redirect_uri() -> str:
    return f"{settings.redirect_base}/api/oauth/tiktok/callback"


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------
def build_auth_url(state: str) -> str:
    if not is_configured():
        raise TikTokError(
            "Faltan las credenciales de TikTok. Añádelas en Ajustes → TikTok."
        )
    params = {
        "client_key": settings.tiktok_client_key,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    data = {
        "client_key": settings.tiktok_client_key,
        "client_secret": settings.tiktok_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    payload = _json(response)
    if "access_token" not in payload:
        raise TikTokError(f"TikTok no ha devuelto el token: {payload}")
    payload["expires_at"] = time.time() + float(payload.get("expires_in", 86400))
    return payload


def refresh_token(credentials: dict[str, Any]) -> dict[str, Any]:
    token = credentials.get("refresh_token")
    if not token:
        raise TikTokError("La cuenta no tiene refresh_token: vuelve a conectarla.")
    data = {
        "client_key": settings.tiktok_client_key,
        "client_secret": settings.tiktok_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": token,
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    payload = _json(response)
    if "access_token" not in payload:
        raise TikTokError(f"No se ha podido renovar el acceso: {payload}")
    payload["expires_at"] = time.time() + float(payload.get("expires_in", 86400))
    merged = dict(credentials)
    merged.update(payload)
    return merged


def valid_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    """Devuelve credenciales vigentes, renovándolas si están a punto de caducar."""
    credentials = dict(credentials or {})
    if not credentials.get("access_token"):
        raise TikTokError("La cuenta de TikTok no está conectada.")
    expires_at = float(credentials.get("expires_at") or 0)
    if expires_at and expires_at - time.time() < 300:
        credentials = refresh_token(credentials)
    return credentials


# --------------------------------------------------------------------------
# Llamadas
# --------------------------------------------------------------------------
def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        raise TikTokError(f"Respuesta inesperada de TikTok ({response.status_code}).")
    error = (payload or {}).get("error")
    if isinstance(error, dict) and error.get("code") not in (None, "ok"):
        raise TikTokError(f"{error.get('code')}: {error.get('message')}")
    if response.status_code >= 400:
        raise TikTokError(f"TikTok respondió {response.status_code}: {payload}")
    return payload


def _headers(credentials: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {credentials['access_token']}",
        "Content-Type": "application/json; charset=UTF-8",
    }


def fetch_user_info(credentials: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "open_id,union_id,avatar_url,display_name,username,"
        "follower_count,following_count,likes_count,video_count"
    )
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.get(
            f"{API_BASE}/user/info/",
            params={"fields": fields},
            headers=_headers(credentials),
        )
    return (_json(response).get("data") or {}).get("user") or {}


def fetch_creator_info(credentials: dict[str, Any]) -> dict[str, Any]:
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{API_BASE}/post/publish/creator_info/query/", headers=_headers(credentials)
        )
    return _json(response).get("data") or {}


def fetch_recent_videos(credentials: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    fields = "id,title,create_time,view_count,like_count,comment_count,share_count,share_url"
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            f"{API_BASE}/video/list/",
            params={"fields": fields},
            headers=_headers(credentials),
            json={"max_count": max(1, min(20, limit))},
        )
    return (_json(response).get("data") or {}).get("videos") or []


# --------------------------------------------------------------------------
# Publicación
# --------------------------------------------------------------------------
def _upload_file(upload_url: str, path: Path, size: int, chunk_size: int) -> None:
    total_chunks = max(1, math.ceil(size / chunk_size))
    with open(path, "rb") as handle, httpx.Client(timeout=TIMEOUT) as client:
        for index in range(total_chunks):
            start = index * chunk_size
            end = min(size, start + chunk_size) - 1
            handle.seek(start)
            data = handle.read(end - start + 1)
            response = client.put(
                upload_url,
                content=data,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                },
            )
            if response.status_code not in (200, 201, 206):
                raise TikTokError(
                    f"Fallo al subir el vídeo ({response.status_code}): {response.text[:300]}"
                )


def publish_video(
    credentials: dict[str, Any],
    *,
    video_path: str | Path,
    caption: str,
    mode: str = "auto",
    privacy_level: str = "PUBLIC_TO_EVERYONE",
    allow_comments: bool = True,
    allow_duet: bool = True,
    allow_stitch: bool = True,
    commercial_content: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sube el clip a TikTok. `mode="draft"` lo deja en la bandeja de borradores."""
    path = Path(video_path)
    if not path.exists():
        raise TikTokError(f"No se encuentra el archivo del clip: {path}")
    size = path.stat().st_size

    if dry_run or settings.dry_run:
        time.sleep(0.4)
        fake_id = uuid.uuid4().hex[:16]
        return {
            "publish_id": f"simulado-{fake_id}",
            "status": "PUBLISH_COMPLETE",
            "share_url": "",
            "dry_run": True,
            "size": size,
        }

    credentials = valid_credentials(credentials)
    chunk_size = min(CHUNK_SIZE, size) if size > 0 else CHUNK_SIZE
    total_chunks = max(1, math.ceil(size / chunk_size))
    source_info = {
        "source": "FILE_UPLOAD",
        "video_size": size,
        "chunk_size": chunk_size,
        "total_chunk_count": total_chunks,
    }

    if mode == "draft":
        endpoint = f"{API_BASE}/post/publish/inbox/video/init/"
        body: dict[str, Any] = {"source_info": source_info}
    else:
        endpoint = f"{API_BASE}/post/publish/video/init/"
        body = {
            "post_info": {
                "title": caption[:2200],
                "privacy_level": privacy_level,
                "disable_comment": not allow_comments,
                "disable_duet": not allow_duet,
                "disable_stitch": not allow_stitch,
                "video_cover_timestamp_ms": 1000,
                "brand_content_toggle": bool(commercial_content),
                "brand_organic_toggle": False,
            },
            "source_info": source_info,
        }

    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(endpoint, headers=_headers(credentials), json=body)
    data = _json(response).get("data") or {}
    publish_id = data.get("publish_id")
    upload_url = data.get("upload_url")
    if not publish_id or not upload_url:
        raise TikTokError(f"TikTok no ha aceptado la publicación: {data}")

    _upload_file(upload_url, path, size, chunk_size)

    status = poll_status(credentials, publish_id)
    return {
        "publish_id": publish_id,
        "status": status.get("status", "PROCESSING_UPLOAD"),
        "share_url": status.get("share_url", ""),
        "dry_run": False,
        "size": size,
        "raw": status,
    }


def poll_status(
    credentials: dict[str, Any], publish_id: str, *, attempts: int = 20, delay: float = 6.0
) -> dict[str, Any]:
    last: dict[str, Any] = {}
    with httpx.Client(timeout=TIMEOUT) as client:
        for _ in range(attempts):
            response = client.post(
                f"{API_BASE}/post/publish/status/fetch/",
                headers=_headers(credentials),
                json={"publish_id": publish_id},
            )
            last = _json(response).get("data") or {}
            status = last.get("status", "")
            if status in {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"}:
                return last
            if status == "FAILED":
                raise TikTokError(
                    f"TikTok ha rechazado el vídeo: {last.get('error_code') or last}"
                )
            time.sleep(delay)
    return last
