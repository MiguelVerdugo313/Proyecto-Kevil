"""Acceso a YouTube mediante yt-dlp.

No hace falta ninguna clave de API: basta con la URL del canal. Para vídeos
privados o no listados se pueden reutilizar las cookies del navegador.
"""

from __future__ import annotations

import re
import threading
import time
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
        # YouTube corta el grifo si le llueven peticiones: mejor insistir
        # despacio que ir rápido y que te bloquee media hora.
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "retry_sleep_functions": {
            "http": lambda intento: min(60, 2 ** intento),
            "fragment": lambda intento: min(30, 2 ** intento),
            "extractor": lambda intento: min(60, 5 * (intento + 1)),
        },
        "sleep_interval_requests": 1,      # un respiro entre peticiones
        "socket_timeout": 30,
        "extractor_args": {"youtubetab": {"skip": ["authcheck"]}},
    }
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


# Entre llamada y llamada a YouTube se deja pasar un momento. Es la diferencia
# entre que te dé todo o que te conteste «too many requests» y no baje nada.
_ultima_llamada = 0.0
_turno = threading.Lock()
PAUSA_ENTRE_LLAMADAS = 1.5


def _esperar_turno() -> None:
    global _ultima_llamada
    with _turno:
        espera = PAUSA_ENTRE_LLAMADAS - (time.monotonic() - _ultima_llamada)
        if espera > 0:
            time.sleep(espera)
        _ultima_llamada = time.monotonic()


def traducir_error(exc: Exception) -> str:
    """Convierte el ladrillo de yt-dlp en algo que se entienda."""
    texto = str(exc)
    bajo = texto.lower()
    if "429" in bajo or "too many requests" in bajo:
        return (
            "YouTube ha cortado las peticiones por un rato («too many requests»). "
            "No es culpa tuya ni un fallo de Kevil: pasa cuando se piden muchos "
            "vídeos seguidos o cuando compartes salida a internet. Kevil lo "
            "reintentará solo más tarde; si te pasa a menudo, baja «vídeos "
            "antiguos a traer» y activa las cookies de tu navegador en el paso "
            "«Descarga del original»."
        )
    if "sign in to confirm" in bajo or "bot" in bajo and "confirm" in bajo:
        return (
            "YouTube pide comprobar que no eres un robot. Activa las cookies de "
            "tu navegador en el paso «Descarga del original» del flujo."
        )
    if "private video" in bajo:
        return "El vídeo es privado. Con las cookies de tu navegador sí se puede leer."
    if "video unavailable" in bajo or "removed" in bajo:
        return "Ese vídeo ya no está disponible en YouTube."
    if "age" in bajo and "restrict" in bajo:
        return "El vídeo tiene restricción de edad: hacen falta las cookies de tu navegador."
    return texto[:400]


class RateLimited(YouTubeError):
    """YouTube ha dicho «too many requests»: hay que esperar, no reintentar ya."""


def _lanzar_bonito(exc: Exception) -> None:
    mensaje = traducir_error(exc)
    bajo = str(exc).lower()
    if "429" in bajo or "too many requests" in bajo:
        raise RateLimited(mensaje) from exc
    raise YouTubeError(mensaje) from exc


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
    only_shorts: bool = False,
    cookies_from_browser: str = "",
) -> list[dict[str, Any]]:
    """Lista los vídeos publicados de un canal (y sus directos ya emitidos).

    Con `only_shorts` se mira únicamente la pestaña de Shorts, que es lo que
    interesa para republicarlos en TikTok.
    """
    ydl = _require_ytdlp()
    url = normalize_channel_url(raw_url)
    opts = _base_opts(cookies_from_browser) | {
        "extract_flat": "in_playlist",
        "playlistend": max(1, limit),
        "skip_download": True,
    }

    if only_shorts:
        tabs: list[tuple[str, bool]] = [("shorts", False)]
    else:
        tabs = [("videos", False)]
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

    _esperar_turno()
    try:
        with ydl.YoutubeDL(opts) as dl:
            info = dl.extract_info(url, download=True)
    except Exception as exc:                    # noqa: BLE001
        _lanzar_bonito(exc)
        raise
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


# --------------------------------------------------------------------------
# Descarga ligera: sólo lo justo, y se borra al terminar
# --------------------------------------------------------------------------
def _info_basica(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "external_id": info.get("id") or "",
        "title": info.get("title") or "",
        "description": info.get("description") or "",
        "duration_s": float(info.get("duration") or 0),
        "was_live": bool(info.get("was_live")),
        "channel": info.get("channel") or "",
        "channel_id": info.get("channel_id") or "",
        "thumbnail_url": info.get("thumbnail") or "",
    }


def fetch_subtitles_only(
    url: str,
    *,
    subtitle_langs: list[str] | None = None,
    cookies_from_browser: str = "",
) -> dict[str, Any]:
    """Baja los subtítulos y los datos del vídeo, pero **no el vídeo**.

    Son unos kilobytes. Con eso ya se puede decidir dónde están los mejores
    momentos, y sólo después se bajan esos segundos concretos.
    """
    ydl = _require_ytdlp()
    dest = settings.work_path
    dest.mkdir(parents=True, exist_ok=True)
    langs = subtitle_langs or ["es", "en"]

    opts = _base_opts(cookies_from_browser) | {
        "ignoreerrors": False,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": langs + [f"{lang}-orig" for lang in langs],
        "subtitlesformat": "json3/vtt/best",
        "outtmpl": str(dest / "%(id)s.%(ext)s"),
    }

    _esperar_turno()
    try:
        with ydl.YoutubeDL(opts) as dl:
            info = dl.extract_info(url, download=True)
    except Exception as exc:                    # noqa: BLE001
        _lanzar_bonito(exc)
        raise
    if not info:
        raise YouTubeError("No se ha podido leer el vídeo.")
    if info.get("_type") == "playlist":
        info = (info.get("entries") or [None])[0] or {}

    video_id = info.get("id", "")
    subtitulos = sorted(
        p for p in dest.glob(f"{video_id}.*") if p.suffix in {".json3", ".vtt", ".srt"}
    )
    return {"subtitles": [str(p) for p in subtitulos], "info": _info_basica(info)}


def download_audio_only(
    url: str,
    *,
    cookies_from_browser: str = "",
    on_progress: Callable[[float, str], None] | None = None,
) -> str:
    """Sólo la pista de audio, para analizar silencios sin bajar el vídeo.

    Un directo de dos horas ocupa unos 100 MB de audio frente a varios GB de
    vídeo, y se borra en cuanto se han elegido los momentos.
    """
    ydl = _require_ytdlp()
    dest = settings.work_path
    dest.mkdir(parents=True, exist_ok=True)

    opts = _base_opts(cookies_from_browser) | {
        "ignoreerrors": False,
        "format": "ba[ext=m4a]/ba/worstaudio",
        "outtmpl": str(dest / "audio-%(id)s.%(ext)s"),
        "progress_hooks": [_hook_progreso(on_progress, "Analizando el audio")],
        "overwrites": False,
        "continuedl": True,
    }

    _esperar_turno()
    try:
        with ydl.YoutubeDL(opts) as dl:
            info = dl.extract_info(url, download=True)
    except Exception as exc:                    # noqa: BLE001
        _lanzar_bonito(exc)
        raise
    if not info:
        raise YouTubeError("No se ha podido bajar el audio.")
    if info.get("_type") == "playlist":
        info = (info.get("entries") or [None])[0] or {}

    descargas = info.get("requested_downloads") or []
    if descargas and descargas[0].get("filepath"):
        return str(descargas[0]["filepath"])
    candidatos = sorted(dest.glob(f"audio-{info.get('id', '')}.*"))
    if not candidatos:
        raise YouTubeError("No se encuentra el audio descargado.")
    return str(candidatos[0])


def download_sections(
    url: str,
    ranges: list[tuple[float, float]],
    *,
    quality: str = "1080",
    cookies_from_browser: str = "",
    destination: Path | None = None,
    on_progress: Callable[[float, str], None] | None = None,
) -> str:
    """Baja **sólo** los tramos indicados, no el vídeo entero.

    Para sacar tres clips de treinta segundos de un directo de dos horas se
    bajan noventa segundos, no dos horas. Es la diferencia entre unos megas y
    varios gigas en el disco.
    """
    if not ranges:
        raise YouTubeError("No hay ningún tramo que descargar.")

    ydl = _require_ytdlp()
    dest = destination or settings.work_path
    dest.mkdir(parents=True, exist_ok=True)
    height = re.sub(r"\D", "", quality) or "1080"

    try:
        rango = ydl.utils.download_range_func(None, [(a, b) for a, b in ranges])
    except AttributeError:  # pragma: no cover - versiones muy viejas de yt-dlp
        raise YouTubeError(
            "Tu versión de yt-dlp no sabe bajar tramos sueltos. "
            "Actualízala con: pip install -U yt-dlp"
        ) from None

    opts = _base_opts(cookies_from_browser) | {
        "ignoreerrors": False,
        "outtmpl": str(dest / "tramo-%(id)s.%(ext)s"),
        "format": (
            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={height}]+ba/b[height<={height}]/b"
        ),
        "merge_output_format": "mp4",
        "download_ranges": rango,
        "force_keyframes_at_cuts": True,     # cortes limpios en los extremos
        "progress_hooks": [_hook_progreso(on_progress, "Bajando el tramo")],
        "concurrent_fragment_downloads": 2,
        "overwrites": True,
        "continuedl": False,
    }

    _esperar_turno()
    try:
        with ydl.YoutubeDL(opts) as dl:
            info = dl.extract_info(url, download=True)
    except Exception as exc:                    # noqa: BLE001
        _lanzar_bonito(exc)
        raise
    if not info:
        raise YouTubeError("La descarga del tramo no ha devuelto nada.")
    if info.get("_type") == "playlist":
        info = (info.get("entries") or [None])[0] or {}

    descargas = info.get("requested_downloads") or []
    if descargas and descargas[0].get("filepath"):
        ruta = Path(descargas[0]["filepath"])
        if ruta.exists():
            return str(ruta)
    candidatos = [
        p for p in sorted(dest.glob(f"tramo-{info.get('id', '')}.*"))
        if p.suffix.lower() in {".mp4", ".mkv", ".webm"}
    ]
    if not candidatos:
        raise YouTubeError("No se encuentra el tramo descargado.")
    return str(candidatos[0])


def _hook_progreso(
    on_progress: Callable[[float, str], None] | None, etiqueta: str
) -> Callable[[dict[str, Any]], None]:
    def hook(status: dict[str, Any]) -> None:
        if not on_progress:
            return
        if status.get("status") == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
            hecho = status.get("downloaded_bytes") or 0
            ratio = (hecho / total) if total else 0.0
            on_progress(min(0.95, ratio), f"{etiqueta}… {ratio * 100:.0f}%")
        elif status.get("status") == "finished":
            on_progress(0.97, "Uniendo pistas…")

    return hook
