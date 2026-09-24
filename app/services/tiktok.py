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

import hashlib
import math
import secrets
import string
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
# TikTok exige PKCE en las aplicaciones de escritorio. Sin esto, autorizar la
# cuenta falla aunque la app esté bien dada de alta.
#
# Ojo con un detalle que se sale del estándar: el reto se calcula como el SHA-256
# del verificador **en hexadecimal**, no en base64url como en el resto de sitios.
_verificadores: dict[str, str] = {}


def nuevo_verificador(state: str) -> str:
    """Cadena aleatoria que demuestra, al canjear el código, que somos los mismos."""
    verificador = "".join(
        secrets.choice(string.ascii_letters + string.digits + "-._~") for _ in range(64)
    )
    _verificadores[state] = verificador
    # no dejamos que la memoria crezca sin fin si alguien empieza y no termina
    if len(_verificadores) > 20:
        for clave in list(_verificadores)[:-10]:
            _verificadores.pop(clave, None)
    return verificador


def reto_de(verificador: str) -> str:
    return hashlib.sha256(verificador.encode("utf-8")).hexdigest()


def build_auth_url(state: str) -> str:
    if not is_configured():
        raise TikTokError(
            "Faltan las credenciales de TikTok. Añádelas en Ajustes → TikTok."
        )
    verificador = nuevo_verificador(state)
    params = {
        "client_key": settings.tiktok_client_key,
        "scope": ",".join(SCOPES),
        "response_type": "code",
        "redirect_uri": redirect_uri(),
        "state": state,
        "code_challenge": reto_de(verificador),
        "code_challenge_method": "S256",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, state: str = "") -> dict[str, Any]:
    data = {
        "client_key": settings.tiktok_client_key,
        "client_secret": settings.tiktok_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri(),
    }
    verificador = _verificadores.pop(state, "")
    if verificador:
        data["code_verifier"] = verificador
    with httpx.Client(timeout=TIMEOUT) as client:
        response = client.post(
            TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    payload = _json(response)
    if "access_token" not in payload:
        raise TikTokError(
            "TikTok no ha devuelto el acceso. Revisa que la «Redirect URI» de "
            f"Login Kit sea exactamente {redirect_uri()} y que las dos claves "
            "sean las de esta misma app."
        )
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
# Errores en cristiano
# --------------------------------------------------------------------------
# TikTok contesta con códigos secos («invalid_client») que no dicen qué tocar.
# Aquí se traducen al problema real y al sitio exacto donde se arregla.
EXPLICACIONES: dict[str, str] = {
    "invalid_client": (
        "La clave o el secreto de tu app no son correctos. Cópialos otra vez "
        "de developers.tiktok.com → tu app → «Client key» y «Client secret», "
        "sin espacios ni saltos de línea."
    ),
    "invalid_request": (
        "TikTok no ha aceptado la petición. Casi siempre es la dirección de "
        "retorno: en tu app, dentro de «Login Kit», el campo «Redirect URI» "
        "tiene que ser exactamente la que te da Kevil."
    ),
    "invalid_grant": (
        "El código de autorización ya se había usado o ha caducado. Vuelve a "
        "pulsar «Conectar con TikTok»."
    ),
    "access_denied": (
        "Has cancelado la autorización en la pantalla de TikTok, o la cuenta "
        "no tiene permiso todavía. Vuelve a intentarlo y pulsa «Autorizar»."
    ),
    "invalid_scope": (
        "Tu app no tiene activados los permisos que pide Kevil. En "
        "developers.tiktok.com → tu app → «Scopes», añade user.info.basic, "
        "video.publish, video.upload y video.list."
    ),
    "scope_not_authorized": (
        "La cuenta no ha concedido alguno de los permisos. Vuelve a conectar y "
        "acepta todos los que te pida la pantalla de TikTok."
    ),
    "unauthorized_client": (
        "Tu app no tiene habilitado el inicio de sesión. Añádele el producto "
        "«Login Kit» en developers.tiktok.com."
    ),
    "access_token_invalid": (
        "El acceso ha caducado. Entra en Cuentas y vuelve a conectar tu TikTok."
    ),
    "unaudited_client_can_only_post_to_private_accounts": (
        "Mientras TikTok no revise tu app, sólo deja publicar en privado. Kevil "
        "lo deja como borrador en tu bandeja de TikTok para que lo publiques tú."
    ),
    "privacy_level_option_mismatch": (
        "La privacidad elegida no está permitida para esta cuenta. Kevil usará "
        "la primera que TikTok acepte."
    ),
    "spam_risk_too_many_posts": (
        "TikTok ha cortado por exceso de publicaciones seguidas. Prueba dentro "
        "de un rato o baja el ritmo en Ajustes."
    ),
    "spam_risk_user_banned_from_posting": (
        "TikTok ha bloqueado las publicaciones de esta cuenta. No es cosa de "
        "Kevil: revísalo dentro de la aplicación de TikTok."
    ),
    "rate_limit_exceeded": (
        "Demasiadas peticiones seguidas a TikTok. Kevil lo reintentará solo más "
        "tarde."
    ),
    "file_format_check_failed": (
        "TikTok ha rechazado el archivo. El clip tiene que ser un MP4 con vídeo "
        "y audio; prueba a volver a montarlo."
    ),
    "reached_active_user_cap": (
        "Tu app está en modo pruebas y ha llegado al tope de cuentas. Añade tu "
        "cuenta en el «Sandbox» de developers.tiktok.com o pide la revisión."
    ),
}


def traducir_error(codigo: str, mensaje: str = "") -> str:
    """Mensaje que se entiende, guardando el código por si hace falta buscarlo."""
    codigo = (codigo or "").strip()
    explicacion = EXPLICACIONES.get(codigo)
    if explicacion:
        return explicacion
    detalle = (mensaje or "").strip()
    if codigo and detalle:
        return f"TikTok ha respondido «{codigo}»: {detalle}"
    return f"TikTok ha respondido «{codigo or detalle or 'un error desconocido'}»."


# --------------------------------------------------------------------------
# Llamadas
# --------------------------------------------------------------------------
class TikTokRechazo(TikTokError):
    """Error con el código original a mano, para poder reaccionar a él."""

    def __init__(self, codigo: str, mensaje: str = "", log_id: str = ""):
        super().__init__(traducir_error(codigo, mensaje))
        self.codigo = codigo
        self.detalle = mensaje
        self.log_id = log_id


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        raise TikTokError(f"Respuesta inesperada de TikTok ({response.status_code}).")

    error = (payload or {}).get("error")
    if isinstance(error, dict) and error.get("code") not in (None, "ok"):
        raise TikTokRechazo(
            str(error.get("code") or ""),
            str(error.get("message") or ""),
            str(error.get("log_id") or ""),
        )
    # El endpoint de tokens contesta con error/error_description en la raíz
    if isinstance(error, str) and error:
        raise TikTokRechazo(
            error,
            str((payload or {}).get("error_description") or ""),
            str((payload or {}).get("log_id") or ""),
        )
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


# Códigos con los que TikTok dice «directamente no, pero por la bandeja sí».
CAEN_EN_BORRADOR = {
    "unaudited_client_can_only_post_to_private_accounts",
    "privacy_level_option_mismatch",
    "scope_not_authorized",
}


SOLO_PARA_MI = "SELF_ONLY"

AVISO_SIN_REVISAR = (
    "TikTok todavía no ha revisado tu app, así que por la API sólo dejaría "
    "publicar en privado. El clip se queda en tu bandeja de TikTok: ábrelo en "
    "el móvil, dale a publicar y ahí sí sale en público."
)


def opciones_de_privacidad(credentials: dict[str, Any]) -> list[str]:
    """Qué privacidades admite esta cuenta, según la propia TikTok."""
    try:
        info = fetch_creator_info(credentials)
    except TikTokError:
        return []            # si no se puede preguntar, se sigue a ciegas
    return [str(o) for o in (info.get("privacy_level_options") or []) if o]


def privacidad_valida(credentials: dict[str, Any], deseada: str) -> str:
    """La privacidad pedida, o la primera que esta cuenta admita.

    TikTok rechaza la publicación entera si se le manda una opción que la cuenta
    no tiene (las cuentas privadas, por ejemplo, no admiten «público»). Preguntar
    antes cuesta una llamada y evita perder el clip.
    """
    return elegir_privacidad(opciones_de_privacidad(credentials), deseada)


def elegir_privacidad(opciones: list[str], deseada: str) -> str:
    if not opciones or deseada in opciones:
        return deseada
    for preferida in ("PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", SOLO_PARA_MI):
        if preferida in opciones:
            return preferida
    return opciones[0]


def mejor_en_la_bandeja(opciones: list[str], deseada: str) -> bool:
    """¿Conviene dejarlo de borrador en vez de publicarlo en privado?

    Mientras TikTok no revise la app, lo único que deja es publicar «sólo para
    mí». Un clip así no lo ve nadie y además hay que ir a buscarlo para cambiarle
    la privacidad a mano. Dejarlo en la bandeja es mejor: llega igual y se
    publica en público con un toque desde el móvil.
    """
    return bool(opciones) and set(opciones) == {SOLO_PARA_MI} and deseada != SOLO_PARA_MI


def fetch_recent_videos(credentials: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
    fields = (
        "id,title,video_description,create_time,view_count,like_count,"
        "comment_count,share_count,share_url"
    )
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

    borrador = mode == "draft"
    aviso = ""
    if not borrador:
        opciones = opciones_de_privacidad(credentials)
        if mejor_en_la_bandeja(opciones, privacy_level):
            borrador = True
            aviso = AVISO_SIN_REVISAR
        else:
            privacy_level = elegir_privacidad(opciones, privacy_level)

    def iniciar(en_borrador: bool) -> dict[str, Any]:
        if en_borrador:
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
        return _json(response).get("data") or {}

    try:
        data = iniciar(borrador)
    except TikTokRechazo as rechazo:
        # Mientras TikTok no revise la app no deja publicar directamente. En vez
        # de dar el clip por perdido, se deja en la bandeja de TikTok: el vídeo
        # llega igual y sólo falta darle a publicar en el móvil.
        if borrador or rechazo.codigo not in CAEN_EN_BORRADOR:
            raise
        borrador = True
        aviso = str(rechazo)
        data = iniciar(True)

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
        "mode": "draft" if borrador else "direct",
        "notice": aviso,
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
