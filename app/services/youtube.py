"""Acceso a YouTube mediante yt-dlp.

No hace falta ninguna clave de API: basta con la URL del canal. Para vídeos
privados o no listados se pueden reutilizar las cookies del navegador.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.config import settings

try:  # yt-dlp se importa de forma perezosa para que la app arranque sin él
    import yt_dlp
except Exception:  # pragma: no cover
    yt_dlp = None  # type: ignore[assignment]


class YouTubeError(RuntimeError):
    pass


def _require_ytdlp():
    if yt_dlp is None:  # pragma: no cover
        raise YouTubeError(
            "Falta yt-dlp. Instálalo con: pip install -U yt-dlp"
        )
    return yt_dlp


def _base_opts(cookies_from_browser: str = "") -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ignoreerrors": True,
        "retries": 5,
        "socket_timeout": 30,
        "extractor_args": {"youtubetab": {"skip": ["authcheck"]}},
    }
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


# --------------------------------------------------------------------------
# Canales
# --------------------------------------------------------------------------
def normalize_channel_url(raw: str) -> str:
    """Acepta @handle, URL de canal, /c/, /user/ o un enlace a un vídeo."""
    raw = (raw or "").strip()
    if not raw:
        raise YouTubeError("Indica la URL o el @usuario del canal.")
    if raw.startswith("@"):
        return f"https://www.youtube.com/{raw}"
    if not raw.startswith("http"):
        if re.fullmatch(r"UC[\w-]{20,}", raw):
            return f"https://www.youtube.com/channel/{raw}"
        return f"https://www.youtube.com/@{raw.lstrip('/')}"
    return raw


def channel_tab(url: str, tab: str) -> str:
    url = url.rstrip("/")
    for suffix in ("/videos", "/streams", "/shorts", "/featured", "/live"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return f"{url}/{tab}"


def resolve_channel(raw_url: str, cookies_from_browser: str = "") -> dict[str, Any]:
    """Devuelve los datos básicos del canal (nombre, id, avatar)."""
    ydl = _require_ytdlp()
    url = normalize_channel_url(raw_url)
    opts = _base_opts(cookies_from_browser) | {
        "extract_flat": "in_playlist",
        "playlistend": 1,
        "skip_download": True,
    }
    with ydl.YoutubeDL(opts) as dl:
        info = dl.extract_info(channel_tab(url, "videos"), download=False)
    if not info:
        raise YouTubeError("No se ha podido leer el canal. Revisa la URL.")

    thumbnails = info.get("thumbnails") or []
    avatar = ""
    if thumbnails:
        avatar = sorted(thumbnails, key=lambda t: t.get("height") or 0)[-1].get("url", "")

    return {
        "channel_id": info.get("channel_id") or info.get("uploader_id") or "",
        "name": info.get("channel") or info.get("uploader") or info.get("title") or url,
        "handle": info.get("uploader_id") or "",
        "url": info.get("channel_url") or url,
        "avatar_url": avatar or (info.get("thumbnail") or ""),
        "subscribers": info.get("channel_follower_count") or 0,
    }


def _entry_to_video(entry: dict[str, Any], was_live: bool = False) -> dict[str, Any] | None:
    if not entry or not entry.get("id"):
        return None
    live_status = entry.get("live_status") or ""
    if live_status in {"is_live", "is_upcoming"}:
        return None  # aún emitiendo: se procesará cuando termine

    timestamp = entry.get("timestamp") or entry.get("release_timestamp")
    published_at = None
    if timestamp:
        published_at = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).replace(tzinfo=None)
    elif entry.get("upload_date"):
        try:
            published_at = datetime.strptime(str(entry["upload_date"]), "%Y%m%d")
        except ValueError:
            published_at = None

    return {
        "external_id": entry["id"],
        "title": entry.get("title") or "(sin título)",
        "description": entry.get("description") or "",
        "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry['id']}",
        "duration_s": float(entry.get("duration") or 0),
        "thumbnail_url": (entry.get("thumbnails") or [{}])[-1].get("url", "")
        or entry.get("thumbnail")
        or f"https://i.ytimg.com/vi/{entry['id']}/hqdefault.jpg",
        "published_at": published_at,
        "was_live": was_live or bool(entry.get("was_live")) or live_status == "was_live",
        "views": int(entry.get("view_count") or 0),
        "likes": int(entry.get("like_count") or 0),
    }


def list_channel_videos(
    raw_url: str,
    *,
    limit: int = 30,
    include_lives: bool = True,
    include_shorts: bool = False,
    cookies_from_browser: str = "",
) -> list[dict[str, Any]]:
    """Lista los vídeos publicados de un canal (y sus directos ya emitidos)."""
    ydl = _require_ytdlp()
    url = normalize_channel_url(raw_url)
    opts = _base_opts(cookies_from_browser) | {
        "extract_flat": "in_playlist",
        "playlistend": max(1, limit),
        "skip_download": True,
    }

    tabs: list[tuple[str, bool]] = [("videos", False)]
    if include_lives:
        tabs.append(("streams", True))
    if include_shorts:
        tabs.append(("shorts", False))

    results: dict[str, dict[str, Any]] = {}
    with ydl.YoutubeDL(opts) as dl:
        for tab, was_live in tabs:
            try:
                info = dl.extract_info(channel_tab(url, tab), download=False)
            except Exception:
                continue
            if not info:
                continue
            entries = info.get("entries") or []
            # Los canales devuelven a veces una lista de listas
            if entries and isinstance(entries[0], dict) and entries[0].get("_type") == "playlist":
                nested: list[Any] = []
                for sub in entries:
                    nested.extend(sub.get("entries") or [])
                entries = nested
            for entry in entries[:limit]:
                video = _entry_to_video(entry or {}, was_live=was_live)
                if video:
                    results.setdefault(video["external_id"], video)

    videos = list(results.values())
    videos.sort(key=lambda v: v["published_at"] or datetime.min, reverse=True)
    return videos[: limit * 2]


def search_videos(query: str, *, limit: int = 15) -> list[dict[str, Any]]:
    """Busca en YouTube y devuelve los resultados con sus visitas.

    Se usa para medir si un tema tiene demanda real antes de recomendarlo.
    """
    ydl = _require_ytdlp()
    opts = _base_opts() | {
        "extract_flat": True,
        "skip_download": True,
        "playlistend": max(1, limit),
    }
    with ydl.YoutubeDL(opts) as dl:
        info = dl.extract_info(f"ytsearch{max(1, limit)}:{query}", download=False)

    resultados: list[dict[str, Any]] = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        resultados.append(
            {
                "id": entry.get("id", ""),
                "title": entry.get("title") or "",
                "channel": entry.get("channel") or entry.get("uploader") or "",
                "views": int(entry.get("view_count") or 0),
                "duration_s": float(entry.get("duration") or 0),
                "url": entry.get("url") or "",
            }
        )
    return resultados


def fetch_video_info(url: str, cookies_from_browser: str = "") -> dict[str, Any]:
    """Metadatos completos de un vídeo suelto."""
    ydl = _require_ytdlp()
    opts = _base_opts(cookies_from_browser) | {"skip_download": True}
    with ydl.YoutubeDL(opts) as dl:
        info = dl.extract_info(url, download=False)
    if not info:
        raise YouTubeError("No se ha podido leer el vídeo.")
    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise YouTubeError("La lista está vacía.")
        info = entries[0]

    video = _entry_to_video(info) or {}
    video.update(
        {
            "channel": info.get("channel") or info.get("uploader") or "",
            "channel_id": info.get("channel_id") or "",
            "channel_url": info.get("channel_url") or "",
            "duration_s": float(info.get("duration") or 0),
            "description": info.get("description") or "",
            "was_live": bool(info.get("was_live")),
        }
    )
    if not video.get("external_id"):
        raise YouTubeError("No se ha podido identificar el vídeo.")
    return video


# --------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------
def download_video(
    url: str,
    *,
    quality: str = "1080",
    download_subtitles: bool = True,
    subtitle_langs: list[str] | None = None,
    cookies_from_browser: str = "",
    on_progress: Callable[[float, str], None] | None = None,
) -> dict[str, Any]:
    """Descarga el vídeo a data/media/originales y devuelve la ruta y metadatos."""
    ydl = _require_ytdlp()
    dest = settings.sources_path
    dest.mkdir(parents=True, exist_ok=True)
    langs = subtitle_langs or ["es", "en"]

    def hook(status: dict[str, Any]) -> None:
        if not on_progress:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            done = status.get("downloaded_bytes") or 0
            ratio = (done / total) if total else 0.0
            speed = status.get("speed") or 0
            label = f"Descargando… {ratio * 100:.0f}%"
            if speed:
                label += f" ({speed / 1024 / 1024:.1f} MB/s)"
            on_progress(min(0.98, ratio), label)
        elif status.get("status") == "finished":
            on_progress(0.99, "Uniendo pistas…")

    height = re.sub(r"\D", "", quality) or "1080"
    opts = _base_opts(cookies_from_browser) | {
        "ignoreerrors": False,
        "outtmpl": str(dest / "%(id)s.%(ext)s"),
        "format": (
            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={height}]+ba/b[height<={height}]/b"
        ),
        "merge_output_format": "mp4",
        "progress_hooks": [hook],
        "concurrent_fragment_downloads": 4,
        "writesubtitles": download_subtitles,
        "writeautomaticsub": download_subtitles,
        "subtitleslangs": langs + [f"{lang}-orig" for lang in langs],
        "subtitlesformat": "json3/vtt/best",
        "skip_unavailable_fragments": True,
        "overwrites": False,
        "continuedl": True,
    }

    with ydl.YoutubeDL(opts) as dl:
        info = dl.extract_info(url, download=True)
    if not info:
        raise YouTubeError("La descarga no ha devuelto ningún resultado.")
    if info.get("_type") == "playlist":
        info = (info.get("entries") or [None])[0] or {}

    video_id = info.get("id", "")
    path = Path(info.get("requested_downloads", [{}])[0].get("filepath", "")) if info.get(
        "requested_downloads"
    ) else None
    if not path or not path.exists():
        candidates = sorted(dest.glob(f"{video_id}.*"))
        candidates = [c for c in candidates if c.suffix.lower() in {".mp4", ".mkv", ".webm"}]
        if not candidates:
            raise YouTubeError("No se encuentra el archivo descargado.")
        path = candidates[0]

    subtitle_files = sorted(
        p for p in dest.glob(f"{video_id}.*") if p.suffix in {".json3", ".vtt", ".srt"}
    )

    return {
        "path": str(path),
        "subtitles": [str(p) for p in subtitle_files],
        "info": {
            "external_id": video_id,
            "title": info.get("title") or "",
            "description": info.get("description") or "",
            "duration_s": float(info.get("duration") or 0),
            "was_live": bool(info.get("was_live")),
            "channel": info.get("channel") or "",
            "channel_id": info.get("channel_id") or "",
            "thumbnail_url": info.get("thumbnail") or "",
        },
    }
