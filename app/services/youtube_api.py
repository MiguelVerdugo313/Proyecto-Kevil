"""Publicación en YouTube (Shorts) con la API oficial de datos v3.

Hace falta un proyecto en Google Cloud con la **YouTube Data API v3** activada
y unas credenciales OAuth de tipo «aplicación web» con esta URL de retorno:

    http://127.0.0.1:8756/api/oauth/youtube/callback

**Aviso importante sobre la cuota.** Google da 10.000 unidades al día por
proyecto y cada subida cuesta 1.600, así que salen **6 subidas diarias**. Es un
límite de Google, no del programa; se puede pedir ampliación en la consola.
La aplicación lleva la cuenta y avisa antes de que te quedes sin cuota.

La subida es reanudable (resumable): se manda el archivo por trozos, así que
un corte de red no obliga a empezar de cero.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import httpx

from app.config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/youtube/v3"
UPLOAD_BASE = "https://www.googleapis.com/upload/youtube/v3"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# Coste en unidades de cuota de cada operación (lo fija Google)
COST_UPLOAD = 1600
COST_LIST = 1
DAILY_QUOTA = 10000

CHUNK = 8 * 1024 * 1024          # 8 MB por trozo
TIMEOUT = httpx.Timeout(30.0, read=600.0)

# Límites del formato Shorts
SHORT_MAX_SECONDS = 180
MAX_TITLE = 100
MAX_DESCRIPTION = 5000


class YouTubeAPIError(RuntimeError):
    pass


class YouTubeNotConfigured(YouTubeAPIError):
    pass


def is_configured() -> bool:
    return bool(settings.youtube_client_id and settings.youtube_client_secret)


def redirect_uri() -> str:
    return f"{settings.redirect_base}/api/oauth/youtube/callback"


# --------------------------------------------------------------------------
# OAuth
# --------------------------------------------------------------------------
def build_auth_url(state: str) -> str:
    if not is_configured():
        raise YouTubeNotConfigured(
            "Faltan las credenciales de YouTube. Añádelas en Ajustes → YouTube."
        )
    params = {
        "client_id": settings.youtube_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",       # necesario para obtener refresh_token
        "prompt": "consent",            # fuerza a que lo devuelva siempre
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    data = {
        "code": code,
        "client_id": settings.youtube_client_id,
        "client_secret": settings.youtube_client_secret,
        "redirect_uri": redirect_uri(),
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(TOKEN_URL, data=data)
    payload = _json(response)
    if "access_token" not in payload:
        raise YouTubeAPIError(f"Google no ha devuelto el token: {payload}")
    payload["expires_at"] = time.time() + float(payload.get("expires_in", 3600))
    return payload


def refresh_token(credentials: dict[str, Any]) -> dict[str, Any]:
    token = credentials.get("refresh_token")
    if not token:
        raise YouTubeAPIError(
            "La cuenta no tiene permiso de larga duración: vuelve a conectarla."
        )
    data = {
        "refresh_token": token,
        "client_id": settings.youtube_client_id,
        "client_secret": settings.youtube_client_secret,
        "grant_type": "refresh_token",
    }
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(TOKEN_URL, data=data)
    payload = _json(response)
    if "access_token" not in payload:
        raise YouTubeAPIError(f"No se ha podido renovar el acceso: {payload}")
    merged = dict(credentials)
    merged.update(payload)
    merged["expires_at"] = time.time() + float(payload.get("expires_in", 3600))
    merged["refresh_token"] = payload.get("refresh_token") or token
    return merged


def valid_credentials(credentials: dict[str, Any]) -> dict[str, Any]:
    credentials = dict(credentials or {})
    if not credentials.get("access_token"):
        raise YouTubeAPIError("La cuenta de YouTube no está conectada.")
    if float(credentials.get("expires_at") or 0) - time.time() < 120:
        credentials = refresh_token(credentials)
    return credentials


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        raise YouTubeAPIError(
            f"Respuesta inesperada de YouTube ({response.status_code}): {response.text[:200]}"
        )
    if response.status_code >= 400:
        error = (payload or {}).get("error") or {}
        mensaje = error.get("message") or str(payload)[:300]
        motivos = [d.get("reason", "") for d in (error.get("errors") or [])]
        if "quotaExceeded" in motivos or "dailyLimitExceeded" in motivos:
            raise YouTubeAPIError(
                "Se ha agotado la cuota diaria de la API de YouTube (10.000 unidades, "
                "1.600 por subida). Vuelve a intentarlo mañana o pide ampliación de cuota."
            )
        if "uploadLimitExceeded" in motivos:
            raise YouTubeAPIError(
                "YouTube ha limitado las subidas de esta cuenta por hoy. Prueba mañana."
            )
        raise YouTubeAPIError(f"YouTube respondió {response.status_code}: {mensaje}")
    return payload


def _headers(credentials: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {credentials['access_token']}"}


def fetch_channel(credentials: dict[str, Any]) -> dict[str, Any]:
    """Datos del canal del usuario conectado."""
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.get(
            f"{API_BASE}/channels",
            params={"part": "snippet,statistics,contentDetails", "mine": "true"},
            headers=_headers(credentials),
        )
    datos = _json(response)
    items = datos.get("items") or []
    if not items:
        raise YouTubeAPIError("La cuenta no tiene ningún canal asociado.")
    canal = items[0]
    snippet = canal.get("snippet") or {}
    stats = canal.get("statistics") or {}
    return {
        "channel_id": canal.get("id", ""),
        "name": snippet.get("title", ""),
        "handle": (snippet.get("customUrl") or "").lstrip("@"),
        "avatar_url": ((snippet.get("thumbnails") or {}).get("default") or {}).get("url", ""),
        "subscribers": int(stats.get("subscriberCount") or 0),
        "videos": int(stats.get("videoCount") or 0),
        "views": int(stats.get("viewCount") or 0),
    }


def fetch_video_stats(credentials: dict[str, Any], video_ids: list[str]) -> dict[str, dict]:
    """Estadísticas de varios vídeos propios (para la analítica)."""
    if not video_ids:
        return {}
    resultado: dict[str, dict] = {}
    for inicio in range(0, len(video_ids), 50):
        lote = video_ids[inicio : inicio + 50]
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(
                f"{API_BASE}/videos",
                params={"part": "statistics,snippet", "id": ",".join(lote)},
                headers=_headers(credentials),
            )
        for item in _json(response).get("items") or []:
            stats = item.get("statistics") or {}
            resultado[item["id"]] = {
                "views": int(stats.get("viewCount") or 0),
                "likes": int(stats.get("likeCount") or 0),
                "comments": int(stats.get("commentCount") or 0),
                "title": (item.get("snippet") or {}).get("title", ""),
            }
    return resultado


# --------------------------------------------------------------------------
# Subida
# --------------------------------------------------------------------------
def validate_short(width: int, height: int, duration: float) -> list[str]:
    """Comprueba que el archivo cumple lo que YouTube pide para un Short."""
    avisos: list[str] = []
    if duration > SHORT_MAX_SECONDS:
        avisos.append(
            f"Dura {duration:.0f} s: por encima de {SHORT_MAX_SECONDS} s YouTube lo "
            f"trata como vídeo normal, no como Short."
        )
    if width and height and width >= height:
        avisos.append(
            "El vídeo no es vertical: para que sea un Short debe ser más alto que ancho."
        )
    return avisos


def upload_short(
    credentials: dict[str, Any],
    *,
    video_path: str | Path,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy_status: str = "public",
    made_for_kids: bool = False,
    publish_at: str | None = None,
    category_id: str = "22",
    dry_run: bool = False,
    on_progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Sube un vídeo vertical como Short. Devuelve el id y la URL."""
    path = Path(video_path)
    if not path.exists():
        raise YouTubeAPIError(f"No se encuentra el archivo: {path}")
    size = path.stat().st_size

    if dry_run or settings.dry_run:
        time.sleep(0.4)
        return {
            "video_id": "simulado",
            "url": "",
            "status": "uploaded",
            "dry_run": True,
            "size": size,
            "quota_used": 0,
        }

    credentials = valid_credentials(credentials)

    titulo = (title or "Short").strip()[:MAX_TITLE].replace("<", "(").replace(">", ")")
    cuerpo: dict[str, Any] = {
        "snippet": {
            "title": titulo,
            "description": (description or "")[:MAX_DESCRIPTION],
            "tags": _limit_tags(tags or []),
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }
    if publish_at:
        # Para programar en YouTube el vídeo debe subirse como privado
        cuerpo["status"]["privacyStatus"] = "private"
        cuerpo["status"]["publishAt"] = publish_at

    # 1) se abre la sesión de subida
    with httpx.Client(timeout=TIMEOUT) as client:
        inicio = client.post(
            f"{UPLOAD_BASE}/videos",
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                **_headers(credentials),
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/*",
            },
            content=json.dumps(cuerpo).encode("utf-8"),
        )
    if inicio.status_code >= 400:
        _json(inicio)  # lanza el error con el mensaje bueno
    destino = inicio.headers.get("location") or inicio.headers.get("Location")
    if not destino:
        raise YouTubeAPIError("YouTube no ha devuelto la dirección de subida.")

    # 2) se envía el archivo por trozos
    resultado: dict[str, Any] = {}
    with open(path, "rb") as archivo, httpx.Client(timeout=TIMEOUT) as client:
        enviado = 0
        while enviado < size:
            archivo.seek(enviado)
            datos = archivo.read(CHUNK)
            fin = enviado + len(datos) - 1
            respuesta = client.put(
                destino,
                content=datos,
                headers={
                    "Content-Length": str(len(datos)),
                    "Content-Range": f"bytes {enviado}-{fin}/{size}",
                },
            )
            if respuesta.status_code in (200, 201):
                resultado = respuesta.json()
                enviado = size
            elif respuesta.status_code == 308:      # falta por enviar
                rango = respuesta.headers.get("range") or respuesta.headers.get("Range")
                enviado = int(rango.split("-")[-1]) + 1 if rango else fin + 1
            else:
                raise YouTubeAPIError(
                    f"Fallo al subir el vídeo ({respuesta.status_code}): {respuesta.text[:300]}"
                )
            if on_progress and size:
                on_progress(min(1.0, enviado / size))

    video_id = resultado.get("id", "")
    if not video_id:
        raise YouTubeAPIError(f"La subida no ha devuelto un identificador: {resultado}")

    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/shorts/{video_id}",
        "status": ((resultado.get("status") or {}).get("uploadStatus")) or "uploaded",
        "dry_run": False,
        "size": size,
        "quota_used": COST_UPLOAD,
    }


def set_thumbnail(credentials: dict[str, Any], video_id: str, image_path: str | Path) -> bool:
    """Pone una miniatura personalizada (necesita el canal verificado)."""
    path = Path(image_path)
    if not path.exists():
        return False
    credentials = valid_credentials(credentials)
    with httpx.Client(timeout=TIMEOUT) as client:
        respuesta = client.post(
            f"{UPLOAD_BASE}/thumbnails/set",
            params={"videoId": video_id},
            headers={**_headers(credentials), "Content-Type": "image/jpeg"},
            content=path.read_bytes(),
        )
    return respuesta.status_code < 400


def _limit_tags(tags: list[str]) -> list[str]:
    """YouTube admite 500 caracteres en total entre todas las etiquetas."""
    salida: list[str] = []
    total = 0
    for tag in tags:
        limpio = str(tag).strip()[:60]
        if not limpio:
            continue
        if total + len(limpio) + 1 > 480:
            break
        salida.append(limpio)
        total += len(limpio) + 1
    return salida
