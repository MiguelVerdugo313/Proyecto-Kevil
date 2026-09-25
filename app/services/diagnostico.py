"""Qué ha fallado, por qué y qué hacer, en cristiano.

Un error suelto de yt-dlp o de ffmpeg no le dice nada a nadie. Aquí cada fallo
conocido se traduce a: un título, el porqué, los pasos para arreglarlo y los
botones que lo arreglan. Lo usan las «Tareas con problemas», los vídeos y los
clips, así que el mismo fallo se explica igual en todas partes.

Además se distingue lo **pasajero** (un corte de red, un archivo que Windows
tenía cogido, YouTube que pide calma) de lo que necesita que hagas algo: lo
pasajero se reintenta solo, sin que tengas que tocar nada.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.models import Clip, ClipStatus, Job, JobStatus, Video, VideoStatus, utcnow

# Cada tipo: cómo reconocerlo, qué decir y si se arregla esperando.
TIPOS: list[dict[str, Any]] = [
    {
        "tipo": "robot",
        "marcas": ("sign in to confirm", "not a bot", "no eres un robot"),
        "titulo": "YouTube pide comprobar que no eres un robot",
        "por_que": (
            "Cuando se bajan muchos vídeos seguidos desde la misma conexión, YouTube "
            "pide que demuestres que eres tú. Se arregla dejando que Kevil use tu "
            "sesión de YouTube (las cookies de tu navegador), como si fueras tú viendo "
            "el vídeo."
        ),
        "pasos": [
            "Abre YouTube en Firefox, Edge o Chrome y comprueba que has iniciado sesión con tu cuenta.",
            "Cierra ese navegador del todo (Chrome y Edge no dejan leer su sesión mientras están abiertos).",
            "Pulsa «Usar mi sesión de YouTube»: Kevil prueba tus navegadores y se queda con el que funcione.",
            "Si ninguno sirve (el Chrome nuevo cifra su sesión): instala en Chrome la extensión "
            "«Get cookies.txt LOCALLY», entra en youtube.com, expórtalas y súbelas con «Subir cookies.txt».",
        ],
        "acciones": [
            {"id": "sesion_youtube", "label": "Usar mi sesión de YouTube"},
            {"id": "cookies_txt", "label": "Subir cookies.txt"},
            {"id": "reintentar", "label": "Reintentar"},
        ],
        "pasajero": False,          # tiene su propio reintento cada hora
    },
    {
        "tipo": "ocupado",
        "marcas": ("winerror 32", "being used by another process",
                   "siendo utilizado por otro proceso", "unable to rename file",
                   "otro programa lo tenía abierto"),
        "titulo": "Windows tenía el archivo ocupado",
        "por_que": (
            "Otro programa (casi siempre el antivirus o el indexador de Windows) estaba "
            "mirando el trozo de vídeo justo cuando Kevil lo iba a guardar. Desde la "
            "versión 1.5 cada descarga usa su propio archivo y se reintenta sola."
        ),
        "pasos": ["No tienes que hacer nada: se reintenta solo en unos minutos."],
        "acciones": [{"id": "reintentar", "label": "Reintentar ya"}],
        "pasajero": True,
    },
    {
        "tipo": "limite",
        "marcas": ("429", "too many requests", "ha cortado las peticiones"),
        "titulo": "YouTube ha pedido calma",
        "por_que": "Demasiadas peticiones seguidas. No es un fallo: hay que esperar un rato.",
        "pasos": [
            "Kevil lo reintenta solo pasados unos 45 minutos.",
            "Si pasa a menudo, baja «vídeos antiguos a traer» en el canal y usa tu sesión de YouTube.",
        ],
        "acciones": [{"id": "sesion_youtube", "label": "Usar mi sesión de YouTube"}],
        "pasajero": True,
    },
    {
        "tipo": "red",
        "marcas": ("timed out", "timeout", "connection reset", "connection aborted",
                   "temporary failure", "name resolution", "network is unreachable",
                   "remote end closed", "ssl", "incompleteread", "http error 5",
                   "getaddrinfo failed", "no se puede establecer una conexión"),
        "titulo": "Se cortó la conexión",
        "por_que": "Internet falló un momento mientras se bajaba o se subía algo.",
        "pasos": ["Se reintenta solo en unos minutos. Si sigue, revisa tu conexión."],
        "acciones": [{"id": "reintentar", "label": "Reintentar ya"}],
        "pasajero": True,
    },
    {
        "tipo": "privado",
        "marcas": ("private video", "es privado", "age-restricted", "confirm your age",
                   "restricción de edad", "members-only", "join this channel"),
        "titulo": "El vídeo necesita tu sesión",
        "por_que": "Es privado, sólo para miembros o con restricción de edad: sin tu sesión no se puede ver.",
        "pasos": ["Pulsa «Usar mi sesión de YouTube» con la cuenta que puede ver el vídeo."],
        "acciones": [
            {"id": "sesion_youtube", "label": "Usar mi sesión de YouTube"},
            {"id": "reintentar", "label": "Reintentar"},
        ],
        "pasajero": False,
    },
    {
        "tipo": "no_disponible",
        "marcas": ("video unavailable", "ya no está disponible", "has been removed",
                   "this video is not available"),
        "titulo": "El vídeo ya no está en YouTube",
        "por_que": "Lo han borrado o ocultado. No se puede hacer nada con él.",
        "pasos": ["Descarta el aviso: no se volverá a intentar."],
        "acciones": [{"id": "descartar", "label": "Descartar"}],
        "pasajero": False,
    },
    {
        "tipo": "disco",
        "marcas": ("no space left", "espacio en disco", "disk full", "errno 28"),
        "titulo": "El disco está lleno",
        "por_que": "No queda sitio para guardar el vídeo o el clip.",
        "pasos": ["Pulsa «Liberar espacio» en Clips o borra archivos que no necesites, y reintenta."],
        "acciones": [
            {"id": "liberar", "label": "Liberar espacio"},
            {"id": "reintentar", "label": "Reintentar"},
        ],
        "pasajero": False,
    },
    {
        "tipo": "ffmpeg",
        "marcas": ("ffmpeg", "invalid data found", "conversion failed", "error while decoding"),
        "titulo": "No se pudo montar el clip",
        "por_que": "ffmpeg no pudo leer o escribir el vídeo, casi siempre por un trozo mal bajado.",
        "pasos": ["Reintenta: se vuelve a bajar el trozo desde cero."],
        "acciones": [{"id": "reintentar", "label": "Reintentar"}],
        "pasajero": True,
    },
    {
        "tipo": "tiktok",
        "marcas": ("tiktok", "access_token", "spam_risk", "scope_not_authorized"),
        "titulo": "TikTok no aceptó la publicación",
        "por_que": "La cuenta necesita volver a autorizarse o TikTok rechazó el vídeo.",
        "pasos": ["Ve a Cuentas y vuelve a conectar TikTok si pone «Falta autorizar».", "Después, reintenta."],
        "acciones": [
            {"id": "cuentas", "label": "Ir a Cuentas"},
            {"id": "reintentar", "label": "Reintentar"},
        ],
        "pasajero": False,
    },
]

GENERICO = {
    "tipo": "otro",
    "titulo": "Algo falló",
    "por_que": "",
    "pasos": ["Reintenta. Si vuelve a fallar, el detalle de abajo dice exactamente qué pasó."],
    "acciones": [{"id": "reintentar", "label": "Reintentar"}],
    "pasajero": False,
}

# Espera antes de cada reintento automático de lo pasajero (minutos).
ESPERAS_MIN = (2, 10, 30)


def diagnosticar(texto: str) -> dict[str, Any]:
    bajo = (texto or "").lower()
    for tipo in TIPOS:
        if any(marca in bajo for marca in tipo["marcas"]):
            return {k: v for k, v in tipo.items() if k != "marcas"}
    return dict(GENERICO)


def resumen(texto: str) -> str:
    """La primera línea útil del error, sin la traza de Python."""
    for linea in (texto or "").splitlines():
        linea = linea.strip()
        if linea and not linea.startswith(("Traceback", "File ")):
            return linea[:300]
    return ""


# --------------------------------------------------------------------------
# Reintentos
# --------------------------------------------------------------------------
def reintentar_solo_si_toca(job: Job) -> bool:
    """Si el fallo es pasajero, deja el trabajo esperando su reintento.

    Devuelve True si se reprogramó (el trabajo NO queda como fallido).
    """
    diag = diagnosticar(job.error or job.message or "")
    automaticos = int((job.payload or {}).get("reintentos_auto") or 0)
    if not diag["pasajero"] or automaticos >= len(ESPERAS_MIN):
        return False
    espera = ESPERAS_MIN[automaticos]
    job.payload = {**(job.payload or {}), "reintentos_auto": automaticos + 1}
    job.status = JobStatus.pending.value
    job.run_at = utcnow() + timedelta(minutes=espera)
    job.progress = 0.0
    job.started_at = None
    job.finished_at = None
    job.message = f"{diag['titulo']}: se reintenta solo en {espera} min"
    sesion = object_session(job)
    if sesion is not None:
        _poner_en_marcha_lo_suyo(sesion, job)
    return True


def _poner_en_marcha_lo_suyo(session: Session, job: Job) -> None:
    """Al reintentar, el clip o el vídeo dejan de figurar como fallidos."""
    payload = job.payload or {}
    if payload.get("clip_id"):
        clip = session.get(Clip, int(payload["clip_id"]))
        if clip and clip.status == ClipStatus.failed.value:
            clip.status = ClipStatus.draft.value
            clip.error = ""
    if payload.get("video_id"):
        video = session.get(Video, int(payload["video_id"]))
        if video and video.status == VideoStatus.error.value:
            video.status = VideoStatus.queued.value
            video.error = ""


def reintentar(session: Session, job: Job) -> None:
    payload = dict(job.payload or {})
    # un reintento a mano empieza de cero la cuenta de reintentos automáticos
    payload.pop("reintentos_auto", None)
    payload.pop("reintentos_robot", None)
    job.payload = payload
    job.status = JobStatus.pending.value
    job.error = ""
    job.progress = 0.0
    job.run_at = utcnow()
    job.started_at = None
    job.finished_at = None
    job.message = "Reintentando…"
    _poner_en_marcha_lo_suyo(session, job)


def fallidos(session: Session) -> list[Job]:
    session.flush()          # que cuente lo que se acaba de reintentar o descartar
    return list(
        session.scalars(
            select(Job).where(Job.status == JobStatus.failed.value).order_by(Job.finished_at.desc())
        ).all()
    )


def _clave(job: Job) -> str:
    """Trabajos repetidos (mismo clip, mismo vídeo) cuentan como uno."""
    payload = job.payload or {}
    for campo in ("clip_id", "video_id", "post_id", "source_id"):
        if payload.get(campo):
            return f"{job.kind}:{campo}:{payload[campo]}"
    return f"{job.kind}:{job.id}"


ETIQUETAS_TRABAJO = {
    "sync_source": "Revisar el canal",
    "ingest": "Leer o bajar el vídeo",
    "process": "Elegir los momentos",
    "render": "Montar el clip",
    "publish": "Publicar",
    "refresh_metrics": "Actualizar métricas",
    "analyze_local": "Analizar el vídeo",
    "build_kit": "Crear el kit",
    "upload_youtube": "Subir a YouTube",
}


def problemas(session: Session) -> dict[str, Any]:
    """Los fallos agrupados por causa, sin repetir el mismo clip veinte veces."""
    vistos: dict[str, Job] = {}
    for job in fallidos(session):
        vistos.setdefault(_clave(job), job)   # el más reciente de cada uno

    grupos: dict[str, dict[str, Any]] = {}
    for job in vistos.values():
        diag = diagnosticar(job.error or job.message or "")
        grupo = grupos.setdefault(diag["tipo"], {**diag, "trabajos": []})
        grupo["trabajos"].append(
            {
                "id": job.id,
                "kind": job.kind,
                "que": ETIQUETAS_TRABAJO.get(job.kind, job.kind),
                "mensaje": (job.message or resumen(job.error))[:300],
                "detalle": resumen(job.error),
                "finished_at": job.finished_at.isoformat() + "Z" if job.finished_at else None,
                "titulo": _titulo_de(session, job),
            }
        )
    lista = sorted(grupos.values(), key=lambda g: len(g["trabajos"]), reverse=True)
    for grupo in lista:
        grupo["total"] = len(grupo["trabajos"])
    duplicados = len(fallidos(session)) - len(vistos)
    return {"grupos": lista, "total": len(vistos), "duplicados": duplicados}


def _titulo_de(session: Session, job: Job) -> str:
    payload = job.payload or {}
    if payload.get("clip_id"):
        clip = session.get(Clip, int(payload["clip_id"]))
        return clip.title if clip else ""
    if payload.get("video_id"):
        video = session.get(Video, int(payload["video_id"]))
        return video.title if video else ""
    return ""


def reintentar_grupo(session: Session, tipo: str | None = None) -> int:
    """Reintenta a la vez todo lo que falló (o sólo lo de una causa)."""
    vistos: dict[str, Job] = {}
    for job in fallidos(session):
        vistos.setdefault(_clave(job), job)
    reintentados = 0
    for job in vistos.values():
        if tipo and diagnosticar(job.error or job.message or "")["tipo"] != tipo:
            continue
        reintentar(session, job)
        reintentados += 1
    # los duplicados viejos del mismo clip ya no aportan nada
    for job in fallidos(session):
        if job not in vistos.values():
            if not tipo or diagnosticar(job.error or job.message or "")["tipo"] == tipo:
                job.status = JobStatus.cancelled.value
    return reintentados


def descartar_grupo(session: Session, tipo: str | None = None) -> int:
    """Quita de la lista los fallos de una causa (o todos) sin reintentarlos."""
    quitados = 0
    for job in fallidos(session):
        if tipo and diagnosticar(job.error or job.message or "")["tipo"] != tipo:
            continue
        job.status = JobStatus.cancelled.value
        quitados += 1
    return quitados


def reintentar_pasajeros_al_arrancar(session: Session) -> int:
    """Lo que falló por algo pasajero (o por el fallo de los tramos de la 1.4)
    se vuelve a intentar solo al abrir el programa."""
    reintentados = 0
    vistos: set[str] = set()
    for job in fallidos(session):
        clave = _clave(job)
        if clave in vistos:
            job.status = JobStatus.cancelled.value     # duplicado del mismo clip
            continue
        vistos.add(clave)
        diag = diagnosticar(job.error or job.message or "")
        if diag["pasajero"] and not (job.payload or {}).get("reintentado_al_arrancar"):
            reintentar(session, job)
            job.payload = {**(job.payload or {}), "reintentado_al_arrancar": True}
            reintentados += 1
    return reintentados
