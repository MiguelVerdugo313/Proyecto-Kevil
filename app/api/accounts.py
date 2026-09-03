"""Cuentas conectadas: canales de YouTube y perfiles de TikTok."""

from __future__ import annotations

import secrets
import time
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import account_to_dict, source_to_dict
from app.config import settings
from app.db import get_db
from app.models import Account, AccountStatus, Platform, Post, PostStatus, Source, utcnow
from app.services import events, pipeline, tiktok, timing, youtube_api
from app.services import youtube as youtube_service
from app.services.queue import enqueue

router = APIRouter(prefix="/api", tags=["cuentas"])

_oauth_states: dict[str, float] = {}


def _result_page(title: str, message: str, ok: bool) -> str:
    """Página que se ve al volver de autorizar (TikTok o YouTube)."""
    color = "#34D399" if ok else "#F87171"
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;700&display=swap" rel="stylesheet">
<style>
body{{margin:0;height:100vh;display:grid;place-items:center;background:#000;
color:#fafafa;font-family:'Inter',system-ui,sans-serif}}
.card{{max-width:460px;padding:48px 40px;border-radius:40px;
background:rgba(255,255,255,.05);backdrop-filter:blur(12px);
border:1px solid rgba(255,255,255,.1);text-align:center}}
h1{{font-size:22px;margin:0 0 14px;color:{color};font-weight:600;letter-spacing:-.05em}}
p{{color:#71717A;line-height:1.6;margin:0;font-weight:300}}
a{{color:{color};display:inline-block;margin-top:26px;text-decoration:none;
font-weight:500;font-size:14px}}
</style></head><body><div class="card"><h1>{title}</h1><p>{message}</p>
<a href="/#cuentas">Volver a Kevil Studio</a></div>
<script>setTimeout(()=>{{window.location='/#cuentas'}},2600)</script></body></html>"""


# --------------------------------------------------------------------------
# Modelos de entrada
# --------------------------------------------------------------------------
class YouTubeAccountIn(BaseModel):
    url: str = Field(..., description="URL o @usuario del canal")
    auto_ingest: bool = True
    include_lives: bool = True
    include_shorts: bool = False
    backfill_limit: int = 20
    min_duration_s: int = 120
    flow_id: int | None = None
    target_account_id: int | None = None


class TikTokManualIn(BaseModel):
    display_name: str
    handle: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_in: int = 86400


class AccountPatch(BaseModel):
    display_name: str | None = None
    handle: str | None = None
    enabled: bool | None = None
    strategy: dict[str, Any] | None = None


# --------------------------------------------------------------------------
# Listado
# --------------------------------------------------------------------------
@router.get("/accounts")
def list_accounts(platform: str | None = None, db: Session = Depends(get_db)):
    query = select(Account).order_by(Account.platform, Account.id)
    if platform:
        query = query.where(Account.platform == platform)
    result = []
    for account in db.scalars(query).all():
        extra: dict[str, Any] = {}
        if account.platform == Platform.tiktok.value:
            state = timing.account_state(db, account)
            extra = {"state": state, "health": timing.health_score(state)}
        result.append(account_to_dict(account, extra))
    return result


@router.get("/accounts/{account_id}")
def get_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Cuenta no encontrada")
    extra: dict[str, Any] = {}
    if account.platform == Platform.tiktok.value:
        state = timing.account_state(db, account)
        extra = {
            "state": state,
            "health": timing.health_score(state),
            "heatmap": timing.combined_heatmap(db, account),
            "best_hours": timing.best_hours(db, account, top=6),
            "strategy": timing.ensure_strategy(account.strategy),
        }
    return account_to_dict(account, extra)


# --------------------------------------------------------------------------
# YouTube
# --------------------------------------------------------------------------
@router.post("/accounts/youtube")
def add_youtube_account(body: YouTubeAccountIn, db: Session = Depends(get_db)):
    warning = ""
    try:
        info = youtube_service.resolve_channel(body.url)
    except Exception as exc:  # sin red o canal raro: se guarda igual
        warning = f"No se han podido leer los datos del canal ({exc}). Se guardará la URL tal cual."
        info = {
            "channel_id": "",
            "name": body.url,
            "handle": "",
            "url": youtube_service.normalize_channel_url(body.url),
            "avatar_url": "",
            "subscribers": 0,
        }

    existing = db.scalars(
        select(Account).where(
            Account.platform == Platform.youtube.value,
            Account.external_id == (info["channel_id"] or info["url"]),
        )
    ).first()
    if existing:
        raise HTTPException(409, "Ese canal ya está conectado")

    account = Account(
        platform=Platform.youtube.value,
        display_name=info["name"],
        handle=info.get("handle", ""),
        external_id=info["channel_id"] or info["url"],
        avatar_url=info.get("avatar_url", ""),
        status=AccountStatus.connected.value,
        stats={"subscribers": info.get("subscribers", 0)},
    )
    db.add(account)
    db.flush()

    source = Source(
        account_id=account.id,
        name=info["name"],
        url=info["url"],
        channel_id=info.get("channel_id", ""),
        kind="channel",
        auto_ingest=body.auto_ingest,
        include_lives=body.include_lives,
        include_shorts=body.include_shorts,
        backfill_limit=body.backfill_limit,
        min_duration_s=body.min_duration_s,
        flow_id=body.flow_id,
        target_account_id=body.target_account_id,
    )
    db.add(source)
    db.flush()

    enqueue(
        db,
        "sync_source",
        {"source_id": source.id},
        priority=80,
        message=f"Revisar «{source.name}»",
    )
    events.log(db, f"Canal conectado: {info['name']}", level="success", scope="canal")
    db.commit()
    return {
        "account": account_to_dict(account),
        "source": source_to_dict(source),
        "warning": warning,
    }


# --------------------------------------------------------------------------
# TikTok
# --------------------------------------------------------------------------
@router.get("/oauth/tiktok/start")
def tiktok_oauth_start():
    if not tiktok.is_configured():
        raise HTTPException(
            400,
            "Añade primero la clave y el secreto de tu app de TikTok en Ajustes.",
        )
    state = secrets.token_urlsafe(24)
    _oauth_states[state] = time.time()
    return RedirectResponse(tiktok.build_auth_url(state), status_code=302)


@router.get("/oauth/tiktok/callback", response_class=HTMLResponse)
def tiktok_oauth_callback(
    code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)
):
    page = _result_page

    if error:
        return HTMLResponse(page("No se ha podido conectar", error, False), status_code=400)
    if not code or state not in _oauth_states:
        return HTMLResponse(
            page("Petición no válida", "Vuelve a intentarlo desde la aplicación.", False),
            status_code=400,
        )
    _oauth_states.pop(state, None)

    try:
        credentials = tiktok.exchange_code(code)
        user = tiktok.fetch_user_info(credentials)
    except Exception as exc:
        return HTMLResponse(page("Error al conectar", str(exc), False), status_code=400)

    open_id = credentials.get("open_id") or user.get("open_id", "")
    account = db.scalars(
        select(Account).where(
            Account.platform == Platform.tiktok.value, Account.external_id == open_id
        )
    ).first()
    if account is None:
        account = Account(
            platform=Platform.tiktok.value,
            external_id=open_id,
            strategy=timing.default_strategy(),
        )
        db.add(account)

    account.display_name = user.get("display_name") or "Cuenta de TikTok"
    account.handle = user.get("username") or account.handle
    account.avatar_url = user.get("avatar_url", "")
    account.credentials = credentials
    account.status = AccountStatus.connected.value
    account.status_detail = ""
    account.stats = {
        "followers": user.get("follower_count", 0),
        "likes": user.get("likes_count", 0),
        "videos": user.get("video_count", 0),
        "updated_at": utcnow().isoformat(),
    }
    events.log(db, f"TikTok conectado: @{account.handle}", level="success", scope="tiktok")
    db.commit()
    return HTMLResponse(
        page("¡Cuenta conectada!", f"@{account.handle or account.display_name} ya está lista.", True)
    )


# --------------------------------------------------------------------------
# YouTube con permiso de subida (para publicar Shorts)
# --------------------------------------------------------------------------
@router.get("/oauth/youtube/start")
def youtube_oauth_start():
    if not youtube_api.is_configured():
        raise HTTPException(
            400,
            "Añade primero el ID y el secreto de cliente de Google en Ajustes → YouTube.",
        )
    state = secrets.token_urlsafe(24)
    _oauth_states[state] = time.time()
    return RedirectResponse(youtube_api.build_auth_url(state), status_code=302)


@router.get("/oauth/youtube/callback", response_class=HTMLResponse)
def youtube_oauth_callback(
    code: str = "", state: str = "", error: str = "", db: Session = Depends(get_db)
):
    if error:
        return HTMLResponse(_result_page("No se ha podido conectar", error, False), status_code=400)
    if not code or state not in _oauth_states:
        return HTMLResponse(
            _result_page("Petición no válida", "Vuelve a intentarlo desde la aplicación.", False),
            status_code=400,
        )
    _oauth_states.pop(state, None)

    try:
        credentials = youtube_api.exchange_code(code)
        canal = youtube_api.fetch_channel(credentials)
    except Exception as exc:
        return HTMLResponse(_result_page("Error al conectar", str(exc), False), status_code=400)

    account = db.scalars(
        select(Account).where(
            Account.platform == Platform.youtube.value,
            Account.external_id == canal["channel_id"],
        )
    ).first()
    if account is None:
        account = Account(
            platform=Platform.youtube.value,
            external_id=canal["channel_id"],
            strategy=timing.default_strategy(),
        )
        db.add(account)

    account.display_name = canal["name"] or "Canal de YouTube"
    account.handle = canal.get("handle") or account.handle
    account.avatar_url = canal.get("avatar_url", "")
    account.credentials = credentials
    account.status = AccountStatus.connected.value
    account.status_detail = ""
    account.stats = {
        **(account.stats or {}),
        "subscribers": canal.get("subscribers", 0),
        "videos": canal.get("videos", 0),
        "views": canal.get("views", 0),
        "updated_at": utcnow().isoformat(),
    }
    events.log(
        db, f"YouTube conectado para publicar: {account.display_name}",
        level="success", scope="youtube",
    )
    db.commit()
    return HTMLResponse(
        _result_page(
            "¡Canal conectado!",
            f"{account.display_name} ya puede recibir Shorts automáticamente.",
            True,
        )
    )


class ShortsImportIn(BaseModel):
    url: str = Field(..., description="URL o @usuario del canal cuyos Shorts se traen")
    limit: int = 30
    flow_id: int | None = None
    target_account_id: int | None = None
    auto_ingest: bool = True


@router.post("/sources/shorts")
def add_shorts_source(body: ShortsImportIn, db: Session = Depends(get_db)):
    """Vigila la pestaña de Shorts de un canal para republicarlos en TikTok."""
    warning = ""
    try:
        info = youtube_service.resolve_channel(body.url)
    except Exception as exc:
        warning = f"No se han podido leer los datos del canal ({exc}). Se guardará la URL tal cual."
        info = {
            "channel_id": "",
            "name": body.url,
            "url": youtube_service.normalize_channel_url(body.url),
        }

    flow_id = body.flow_id
    if flow_id is None:
        # se busca la plantilla de republicar Shorts
        from app.models import Flow

        flow = db.scalars(
            select(Flow).where(Flow.name.like("Shorts a TikTok%")).limit(1)
        ).first()
        flow_id = flow.id if flow else None

    source = Source(
        name=f"Shorts de {info['name']}",
        url=info["url"],
        channel_id=info.get("channel_id", ""),
        kind="shorts",
        auto_ingest=body.auto_ingest,
        include_lives=False,
        include_shorts=True,
        min_duration_s=0,            # un Short dura poco: no se filtra por duración
        backfill_limit=max(1, min(200, body.limit)),
        flow_id=flow_id,
        target_account_id=body.target_account_id,
    )
    db.add(source)
    db.flush()

    enqueue(
        db,
        "sync_source",
        {"source_id": source.id},
        priority=75,
        message=f"Traer los Shorts de «{info['name']}»",
    )
    events.log(db, f"Shorts vigilados: {info['name']}", level="success", scope="canal")
    db.commit()
    return {"source": source_to_dict(source), "warning": warning}


@router.get("/youtube/config")
def youtube_config(db: Session = Depends(get_db)):
    """Estado de la conexión con YouTube y cuánta cuota queda hoy."""
    cuenta = pipeline.publishable_youtube_account(db)
    usados = _uploads_today(db)
    return {
        "configured": youtube_api.is_configured(),
        "connected": cuenta is not None,
        "account": account_to_dict(cuenta) if cuenta else None,
        "redirect_uri": youtube_api.redirect_uri(),
        "scopes": youtube_api.SCOPES,
        "quota": {
            "daily_units": youtube_api.DAILY_QUOTA,
            "cost_per_upload": youtube_api.COST_UPLOAD,
            "uploads_today": usados,
            "uploads_left": max(0, youtube_api.DAILY_QUOTA // youtube_api.COST_UPLOAD - usados),
        },
    }


def _uploads_today(db: Session) -> int:
    """Shorts subidos hoy (la cuota de Google se reinicia a medianoche del Pacífico)."""
    desde = utcnow() - timedelta(hours=24)
    filas = db.execute(
        select(Post.id)
        .join(Account, Post.account_id == Account.id)
        .where(
            Account.platform == Platform.youtube.value,
            Post.status == PostStatus.published.value,
            Post.published_at >= desde,
        )
    ).all()
    return len(filas)


@router.post("/accounts/tiktok/manual")
def add_tiktok_manual(body: TikTokManualIn, db: Session = Depends(get_db)):
    """Alta manual: útil para probar sin credenciales o para pegar un token propio."""
    credentials: dict[str, Any] = {}
    if body.access_token:
        credentials = {
            "access_token": body.access_token,
            "refresh_token": body.refresh_token,
            "expires_at": time.time() + body.expires_in,
        }
    account = Account(
        platform=Platform.tiktok.value,
        display_name=body.display_name,
        handle=body.handle.lstrip("@"),
        external_id=f"manual-{secrets.token_hex(6)}",
        status=(
            AccountStatus.connected.value if credentials else AccountStatus.needs_auth.value
        ),
        status_detail=(
            "" if credentials else "Sin token: las publicaciones se harán en modo simulación."
        ),
        credentials=credentials,
        strategy=timing.default_strategy(),
    )
    db.add(account)
    db.commit()
    return account_to_dict(account)


@router.post("/accounts/{account_id}/refresh")
def refresh_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Cuenta no encontrada")
    enqueue(db, "refresh_metrics", {"account_id": account.id}, priority=60,
            message=f"Actualizar {account.display_name}")
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Edición y estrategia
# --------------------------------------------------------------------------
@router.patch("/accounts/{account_id}")
def patch_account(account_id: int, body: AccountPatch, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Cuenta no encontrada")
    if body.display_name is not None:
        account.display_name = body.display_name
    if body.handle is not None:
        account.handle = body.handle.lstrip("@")
    if body.enabled is not None:
        account.enabled = body.enabled
    if body.strategy is not None:
        account.strategy = timing.ensure_strategy(
            {**(account.strategy or {}), **body.strategy}
        )
    db.commit()
    return account_to_dict(account)


@router.get("/accounts/{account_id}/strategy")
def get_strategy(account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Cuenta no encontrada")
    state = timing.account_state(db, account)
    return {
        "strategy": timing.ensure_strategy(account.strategy),
        "state": state,
        "health": timing.health_score(state),
        "heatmap": timing.combined_heatmap(db, account),
        "best_hours": timing.best_hours(db, account, top=6),
        "days": timing.DAYS,
    }


@router.put("/accounts/{account_id}/strategy")
def put_strategy(account_id: int, body: dict[str, Any], db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Cuenta no encontrada")
    account.strategy = timing.ensure_strategy(body)
    db.commit()
    return {"strategy": account.strategy}


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(404, "Cuenta no encontrada")
    db.delete(account)
    db.commit()
    return {"ok": True}


@router.get("/tiktok/config")
def tiktok_config():
    return {
        "configured": tiktok.is_configured(),
        "redirect_uri": tiktok.redirect_uri(),
        "scopes": tiktok.SCOPES,
        "dry_run": settings.dry_run,
    }
