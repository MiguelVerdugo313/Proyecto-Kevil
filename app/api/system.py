"""Estado del sistema, panel, trabajos, eventos y ajustes."""

from __future__ import annotations

import json
import re
import shutil
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.api.common import event_to_dict, job_to_dict, post_to_dict
from app.bootstrap import current_settings, save_settings
from app.config import settings
from app.db import get_db
from app.models import (
    Account,
    Clip,
    ClipStatus,
    EventLog,
    Job,
    JobStatus,
    MetricSample,
    Platform,
    Post,
    PostStatus,
    Source,
    Video,
    utcnow,
)
from app.services import branding
from app.services import media as media_service
from app.services import (
    autopilot, brandkit, credenciales, events, pausa, storage, thumbnails, tiktok,
    timing,
    youtube_api,
)
from app.services.queue import enqueue
from app.version import VERSION

router = APIRouter(prefix="/api", tags=["sistema"])



class SettingsIn(BaseModel):
    tiktok_client_key: str | None = None
    tiktok_client_secret: str | None = None
    youtube_api_key: str | None = None
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    dry_run: bool | None = None
    workers: int | None = None
    watch_interval_minutes: int | None = None
    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None
    ai_primary: str | None = None
    openrouter_api_key: str | None = None
    openrouter_text_model: str | None = None
    openrouter_image_model: str | None = None
    nvidia_api_key: str | None = None
    nvidia_text_model: str | None = None
    nvidia_image_model: str | None = None
    light_mode: bool | None = None
    keep_originals: bool | None = None
    keep_clips: bool | None = None
    disk_budget_gb: float | None = None
    window_mode: str | None = None
    brand_accent: str | None = None
    brand_accent_2: str | None = None
    brand_source: str | None = None
    channel_topic: str | None = None
    channel_language: str | None = None
    target_uploads_per_week: float | None = None
    notifications_desktop: bool | None = None


def _count(db: Session, model, *conditions) -> int:
    query = select(func.count()).select_from(model)
    for condition in conditions:
        query = query.where(condition)
    return int(db.scalar(query) or 0)


@router.get("/status")
def status(db: Session = Depends(get_db)):
    usage = shutil.disk_usage(settings.data_path)
    return {
        "version": VERSION,
        "ffmpeg": media_service.ffmpeg_ready(),
        "ffmpeg_path": settings.ffmpeg_path,
        "tiktok_configured": tiktok.is_configured(),
        "dry_run": settings.dry_run,
        "data_dir": str(settings.data_path),
        "disk_free_gb": round(usage.free / 1024**3, 1),
        "accounts": {
            "youtube": _count(db, Account, Account.platform == Platform.youtube.value),
            "tiktok": _count(db, Account, Account.platform == Platform.tiktok.value),
        },
        "jobs_running": _count(db, Job, Job.status == JobStatus.running.value),
        "jobs_pending": _count(db, Job, Job.status == JobStatus.pending.value),
        "clips_ready": _count(db, Clip, Clip.status == ClipStatus.rendered.value),
        "paused": pausa.activa(),
    }


# --------------------------------------------------------------------------
# Pausa del motor
# --------------------------------------------------------------------------
def _estado_motor(db: Session, parados: int = 0) -> dict[str, Any]:
    esperando = _count(
        db, Job, Job.status == JobStatus.pending.value, Job.kind.in_(pausa.PESADOS)
    )
    return {
        "paused": pausa.activa(),
        "running": _count(db, Job, Job.status == JobStatus.running.value),
        "waiting": esperando,
        "stopped": parados,
    }


@router.get("/motor")
def motor(db: Session = Depends(get_db)):
    return _estado_motor(db)


@router.post("/motor/pausa")
def pausar_motor(db: Session = Depends(get_db)):
    """Para en seco descargas, cortes y renders, y no empieza ninguno nuevo.

    Lo que estaba a medias vuelve a la cola: al reanudar se retoma sin perder
    nada. Las publicaciones programadas siguen saliendo a su hora.
    """
    parados = pausa.pausar(db)
    events.log(
        db,
        "Motor en pausa" + (f": {parados} proceso(s) detenido(s)" if parados else ""),
        level="info",
        scope="sistema",
    )
    db.commit()
    return _estado_motor(db, parados)


@router.post("/motor/reanudar")
def reanudar_motor(db: Session = Depends(get_db)):
    pausa.reanudar(db)
    events.log(db, "Motor en marcha otra vez", level="success", scope="sistema")
    db.commit()
    return _estado_motor(db)


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    now = utcnow()
    week_ago = now - timedelta(days=7)

    upcoming = db.scalars(
        select(Post)
        .where(Post.status == PostStatus.scheduled.value)
        .order_by(Post.scheduled_at)
        .limit(8)
    ).all()

    review = db.scalars(
        select(Clip)
        .where(Clip.status == ClipStatus.rendered.value)
        .order_by(Clip.score.desc())
        .limit(8)
    ).all()

    jobs = db.scalars(
        select(Job)
        .where(Job.status.in_([JobStatus.running.value, JobStatus.pending.value]))
        .order_by(Job.priority, Job.created_at)
        .limit(8)
    ).all()

    recent_events = db.scalars(
        select(EventLog).order_by(EventLog.created_at.desc()).limit(12)
    ).all()

    views_week = int(
        db.scalar(
            select(func.coalesce(func.sum(MetricSample.views), 0)).where(
                MetricSample.captured_at >= week_ago
            )
        )
        or 0
    )

    # Se muestran las cuentas a las que se publica: TikTok y los canales de
    # YouTube que tengan permiso de subida.
    accounts = [
        cuenta for cuenta in db.scalars(
            select(Account).where(Account.enabled.is_(True))
        ).all()
        if cuenta.platform == Platform.tiktok.value
        or (cuenta.credentials or {}).get("access_token")
    ]
    account_cards = []
    for account in accounts:
        state = timing.account_state(db, account)
        account_cards.append(
            {
                "id": account.id,
                "platform": account.platform,
                "name": account.display_name,
                "handle": account.handle,
                "avatar_url": account.avatar_url,
                "followers": state["followers"],
                "health": timing.health_score(state),
                "maturity": state["maturity"],
                "recommended_per_day": state["recommended_per_day"],
                "published_7d": state["published_7d"],
                "scheduled": state["scheduled"],
                "using_history": state["using_history"],
                "best_hours": timing.best_hours(db, account, top=3),
            }
        )

    return {
        "counters": {
            "channels": _count(db, Source),
            "videos": _count(db, Video),
            "clips": _count(db, Clip),
            "clips_ready": _count(db, Clip, Clip.status == ClipStatus.rendered.value),
            "scheduled": _count(db, Post, Post.status == PostStatus.scheduled.value),
            "published_7d": _count(
                db,
                Post,
                Post.status == PostStatus.published.value,
                Post.published_at >= week_ago,
            ),
            "failed": _count(db, Post, Post.status == PostStatus.failed.value),
            "views_week": views_week,
        },
        "upcoming": [post_to_dict(p) for p in upcoming],
        "review": [
            {
                "id": clip.id,
                "title": clip.title,
                "score": round(clip.score, 2),
                "duration_s": round(clip.duration_s, 1),
                "video_title": clip.video.title if clip.video else "",
                "has_thumb": bool(clip.thumb_path),
            }
            for clip in review
        ],
        "jobs": [job_to_dict(j) for j in jobs],
        "events": [event_to_dict(e) for e in recent_events],
        "accounts": account_cards,
    }


# --------------------------------------------------------------------------
# Trabajos
# --------------------------------------------------------------------------
@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = 60, db: Session = Depends(get_db)):
    query = select(Job).order_by(Job.created_at.desc()).limit(max(1, min(300, limit)))
    if status:
        query = query.where(Job.status == status)
    return [job_to_dict(j) for j in db.scalars(query).all()]


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        return {"ok": False}
    job.status = JobStatus.pending.value
    job.error = ""
    job.progress = 0.0
    job.message = "Reintentando…"
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        return {"ok": False}
    if job.status == JobStatus.pending.value:
        job.status = JobStatus.cancelled.value
        db.commit()
    return {"ok": True}


@router.delete("/jobs/finished")
def clear_jobs(db: Session = Depends(get_db)):
    db.execute(
        delete(Job).where(
            Job.status.in_(
                [JobStatus.done.value, JobStatus.failed.value, JobStatus.cancelled.value]
            )
        )
    )
    db.commit()
    return {"ok": True}


@router.get("/events")
def list_events(limit: int = 60, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(EventLog).order_by(EventLog.created_at.desc()).limit(max(1, min(300, limit)))
    ).all()
    return [event_to_dict(e) for e in rows]


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------
@router.get("/settings")
def get_settings_endpoint(db: Session = Depends(get_db)):
    return {
        "settings": current_settings(db),
        "ffmpeg": media_service.ffmpeg_ready(),
        "tiktok_redirect_uri": tiktok.redirect_uri(),
        "data_dir": str(settings.data_path),
        "version": VERSION,
    }


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db)):
    values: dict[str, Any] = {
        key: value for key, value in body.model_dump().items() if value is not None
    }
    # el marcador de secreto oculto no debe sobrescribir la clave real
    values = {k: v for k, v in values.items() if v != "••••••••"}
    applied = save_settings(db, values)
    db.commit()
    return {"applied": list(applied), "settings": current_settings(db)}


# --------------------------------------------------------------------------
# Credenciales pegadas de una sola vez
# --------------------------------------------------------------------------
class PastedCredentials(BaseModel):
    text: str


_buscar_par = credenciales.buscar_par


@router.post("/credentials/youtube/buscar")
def find_youtube_credentials(db: Session = Depends(get_db)):
    """Busca él solo el «client_secret_….json» que Google acaba de descargar.

    Es el paso que más se atraganta: abrir el archivo, seleccionarlo entero y
    pegarlo. Como casi siempre está en Descargas, Kevil mira ahí (y en el
    escritorio, y junto al programa) y lo guarda sin que haya que tocarlo.
    """
    hallazgo = credenciales.buscar_de_google()
    if hallazgo is None:
        raise HTTPException(
            404,
            "No he encontrado el archivo de Google. Suele quedarse en "
            "«Descargas» y se llama «client_secret_….json». Si lo tienes en "
            "otro sitio, déjalo en la carpeta de Kevil o pégalo aquí abajo.",
        )

    ruta, client_id, client_secret = hallazgo
    save_settings(
        db, {"youtube_client_id": client_id, "youtube_client_secret": client_secret}
    )
    db.commit()
    return {
        "ok": True,
        "file": ruta.name,
        "folder": str(ruta.parent),
        "client_id": client_id,
        "ready": youtube_api.is_configured(),
        "redirect_uri": youtube_api.redirect_uri(),
    }


@router.post("/credentials/youtube")
def paste_youtube_credentials(body: PastedCredentials, db: Session = Depends(get_db)):
    """Pega el archivo JSON que descargas de Google y listo.

    Google entrega un «client_secret_….json» con el identificador y el secreto
    dentro. Así no hay que copiar dos campos a mano ni equivocarse de cuál es cuál.
    """
    try:
        datos = json.loads(body.text or "")
    except json.JSONDecodeError:
        raise HTTPException(
            400,
            "Eso no es el archivo de Google. Descárgalo con el botón de la flecha "
            "(⤓) en «Credenciales» y pega aquí su contenido entero.",
        ) from None

    client_id = _buscar_par(datos, ("client_id",))
    client_secret = _buscar_par(datos, ("client_secret",))
    if not client_id or not client_secret:
        raise HTTPException(
            400, "Al archivo le falta el identificador o el secreto de cliente."
        )
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise HTTPException(
            400,
            "Ese identificador no parece de Google. Asegúrate de crear las "
            "credenciales como «ID de cliente de OAuth» de tipo «Aplicación de escritorio».",
        )

    save_settings(
        db, {"youtube_client_id": client_id, "youtube_client_secret": client_secret}
    )
    db.commit()
    return {
        "ok": True,
        "client_id": client_id,
        "ready": youtube_api.is_configured(),
        "redirect_uri": youtube_api.redirect_uri(),
    }


class TikTokKeysIn(BaseModel):
    text: str = ""
    client_key: str = ""
    client_secret: str = ""


AVISO_DIRECCION = (
    "Eso es una dirección web, no una clave. La «Client key» y el «Client "
    "secret» son cadenas de letras y números de la pantalla de tu app. La "
    "dirección de retorno va en TikTok, en el campo «Redirect URI» de Login Kit."
)


@router.post("/credentials/tiktok")
def paste_tiktok_credentials(body: TikTokKeysIn, db: Session = Depends(get_db)):
    """Guarda la client key y el client secret de TikTok.

    Lo normal es que lleguen en sus dos campos. Se admite también pegar de golpe
    lo que salga de la pantalla de TikTok (con etiquetas, en dos líneas, separado
    por comas…) para el que prefiera seleccionar y pegar.
    """
    clave = (body.client_key or "").strip()
    secreto = (body.client_secret or "").strip()
    texto = (body.text or "").strip()

    if not clave and not secreto and not texto:
        raise HTTPException(400, "Pon aquí la client key y el client secret.")

    # Es fácil confundirse y pegar aquí la dirección de retorno: sin este aviso
    # se guardaría como si fuera una clave y el fallo saldría mucho después.
    for valor in (clave, secreto, texto):
        if "http://" in valor or "https://" in valor:
            raise HTTPException(400, AVISO_DIRECCION)

    if texto and not (clave and secreto):
        clave = clave or _buscar_etiqueta(
            texto, ("client key", "client_key", "clientkey", "key")
        )
        secreto = secreto or _buscar_etiqueta(
            texto, ("client secret", "client_secret", "clientsecret", "secret")
        )
        if not clave or not secreto:
            # sin etiquetas: dos palabras sueltas, la primera es la clave
            piezas = [p for p in re.split(r"[\s,;]+", texto) if len(p) >= 8]
            if len(piezas) == 2:
                clave, secreto = piezas

    if not clave or not secreto:
        raise HTTPException(
            400,
            "Faltan datos: necesito la «Client key» y el «Client secret», los dos.",
        )
    if clave == secreto:
        raise HTTPException(
            400,
            "Has puesto lo mismo en los dos campos. Son valores distintos: en la "
            "pantalla de tu app, «Client key» arriba y «Client secret» debajo.",
        )
    if len(clave) < 8 or len(secreto) < 8:
        raise HTTPException(
            400,
            "Esas claves son demasiado cortas. Cópialas enteras de la pantalla de "
            "tu app de TikTok, sin espacios.",
        )

    save_settings(db, {"tiktok_client_key": clave, "tiktok_client_secret": secreto})
    db.commit()
    return {
        "ok": True,
        "client_key": clave,
        "ready": tiktok.is_configured(),
        "redirect_uri": tiktok.redirect_uri(),
    }


def _buscar_etiqueta(texto: str, etiquetas: tuple[str, ...]) -> str:
    """Saca el valor que sigue a «client key:», «Client Secret =», etc."""
    for etiqueta in etiquetas:
        patron = re.compile(
            rf"{re.escape(etiqueta)}\s*[:=]?\s*([A-Za-z0-9_\-.]{{8,}})", re.I
        )
        encontrado = patron.search(texto)
        if encontrado:
            return encontrado.group(1)
    return ""


# --------------------------------------------------------------------------
# Piloto automático
# --------------------------------------------------------------------------
class AutopilotIn(BaseModel):
    enabled: bool


@router.get("/autopilot")
def get_autopilot(db: Session = Depends(get_db)):
    """Si Kevil está trabajando solo y, si no, qué le falta."""
    return autopilot.estado(db)


@router.post("/autopilot")
def set_autopilot(body: AutopilotIn, db: Session = Depends(get_db)):
    if body.enabled:
        falta = autopilot.falta_algo(db)
        if falta:
            raise HTTPException(
                400,
                "Antes de que Kevil pueda trabajar solo le falta: " + "; ".join(falta),
            )
        resultado = autopilot.activar(db)
    else:
        resultado = autopilot.desactivar(db)
    db.commit()
    return resultado


# --------------------------------------------------------------------------
# Espacio en disco
# --------------------------------------------------------------------------
@router.get("/storage")
def storage_status():
    """Cuánto ocupa Kevil ahora mismo y con qué reglas se limpia."""
    datos = storage.usage()
    datos["branding"] = brandkit.scan()["counts"]
    return datos


@router.post("/storage/clean")
def storage_clean(db: Session = Depends(get_db)):
    """Limpieza normal: temporales y lo que ya esté publicado."""
    resultado = storage.enforce_budget(db)
    db.commit()
    return resultado | {"usage": storage.usage()}


@router.get("/storage/free")
def storage_free_preview(db: Session = Depends(get_db)):
    """Lo que se liberaría con «Liberar espacio», sin tocar nada."""
    return storage.plan_de_limpieza(db) | {"usage": storage.usage()}


@router.post("/storage/free")
def storage_free(db: Session = Depends(get_db)):
    """Borra lo que sobra y nada de lo que hace falta.

    Se van los temporales, los clips descartados y los ya publicados, los
    originales de los que ya no queda nada por montar y los archivos sueltos
    que no son de nadie. Lo programado y lo que está por revisar se queda.
    """
    resultado = storage.liberar_espacio(db)
    if resultado["freed_mb"]:
        events.log(
            db,
            f"Espacio liberado: {resultado['freed_mb']} MB",
            level="success",
            scope="disco",
        )
    db.commit()
    return resultado | {"usage": storage.usage()}


@router.post("/storage/purge")
def storage_purge(db: Session = Depends(get_db)):
    """Borra todos los vídeos. La base de datos y el historial se quedan."""
    resultado = storage.purge_everything(db)
    db.commit()
    return resultado | {"usage": storage.usage()}


# --------------------------------------------------------------------------
# Tu carpeta de marca
# --------------------------------------------------------------------------
@router.get("/brandkit")
def brandkit_status():
    """Qué has metido en data/branding y cómo lo ha entendido Kevil."""
    return brandkit.scan()


class LiveThumbIn(BaseModel):
    text: str
    topic: str = ""
    use_ai_image: bool = True


@router.post("/brandkit/live-thumbnail")
def live_thumbnail(body: LiveThumbIn):
    """Una sola miniatura para anunciar un directo que aún no has hecho."""
    texto = (body.text or "").strip()
    if not texto:
        raise HTTPException(400, "Escribe el texto que quieres que salga en la miniatura.")
    try:
        resultado = thumbnails.for_live(
            text=texto,
            out_dir=settings.thumbs_path,
            prefix=f"directo-{int(utcnow().timestamp())}",
            topic=body.topic or texto,
            use_ai_image=body.use_ai_image,
        )
    except Exception as exc:
        raise HTTPException(400, f"No se ha podido crear la miniatura: {exc}") from exc
    resultado["url"] = f"/api/brandkit/live-thumbnail/file?path={quote(resultado['path'])}"
    return resultado


@router.get("/brandkit/live-thumbnail/file")
def live_thumbnail_file(path: str):
    archivo = Path(path).resolve()
    # sólo se sirve lo que está dentro de la carpeta de miniaturas
    if not str(archivo).startswith(str(settings.thumbs_path.resolve())):
        raise HTTPException(404, "No encontrado")
    if not archivo.is_file():
        raise HTTPException(404, "No encontrado")
    return FileResponse(archivo)


# --------------------------------------------------------------------------
# Colores de tu marca
# --------------------------------------------------------------------------
class BrandIn(BaseModel):
    accent: str | None = None
    accent_2: str | None = None
    account_id: int | None = None


@router.get("/branding")
def get_branding(db: Session = Depends(get_db)):
    """Tema actual y de qué canales se pueden sacar los colores."""
    canales = [
        {
            "id": account.id,
            "name": account.display_name,
            "avatar_url": account.avatar_url,
            "platform": account.platform,
        }
        for account in db.scalars(
            select(Account).where(Account.avatar_url != "").order_by(Account.id)
        ).all()
    ]
    return {
        "theme": branding.current_theme(),
        "accent": settings.brand_accent,
        "accent_2": settings.brand_accent_2,
        "source": settings.brand_source,
        "channels": canales,
        "default_accent": "#A78B71",
    }


@router.post("/branding")
def set_branding(body: BrandIn, db: Session = Depends(get_db)):
    """Aplica un color a mano o lo saca del avatar de un canal."""
    if body.account_id:
        account = db.get(Account, body.account_id)
        if not account or not account.avatar_url:
            raise HTTPException(404, "Ese canal no tiene imagen de la que sacar colores.")
        try:
            tema = branding.extract_from_url(account.avatar_url)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        origen = f"canal:{account.display_name}"
        principal = tema["source_accent"]
        secundario = (tema.get("palette") or [{}, {}])[1].get("hex", "") if tema.get("palette") else ""
    elif body.accent:
        principal = body.accent.strip()
        secundario = (body.accent_2 or "").strip()
        tema = branding.build_theme(principal, secundario)
        origen = "manual"
    else:
        raise HTTPException(400, "Indica un color o el canal del que sacarlo.")

    save_settings(
        db,
        {"brand_accent": principal, "brand_accent_2": secundario, "brand_source": origen},
    )
    db.commit()
    tema["custom"] = True
    tema["source"] = origen
    return {"theme": tema, "accent": principal, "accent_2": secundario, "source": origen}


@router.delete("/branding")
def reset_branding(db: Session = Depends(get_db)):
    save_settings(db, {"brand_accent": "", "brand_accent_2": "", "brand_source": ""})
    db.commit()
    return {"theme": {"custom": False}}


@router.post("/maintenance/refresh-metrics")
def refresh_metrics(db: Session = Depends(get_db)):
    enqueue(db, "refresh_metrics", {}, priority=200, message="Actualizar métricas")
    db.commit()
    return {"ok": True}
