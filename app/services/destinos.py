"""Dónde sale cada clip: TikTok, YouTube Shorts o los dos.

Lo decide el paso «Publicación» de cada flujo. Aquí se junta todo lo que hace
falta para verlo de un vistazo y cambiarlo sin entrar en el editor de flujos.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_schema import normalize_steps, step_config
from app.models import Account, Clip, Flow, Platform, Source
from app.services import pipeline

SHORT_MAX = 180          # YouTube trata como Short hasta 3 minutos


def _flujo_por_defecto(session: Session) -> Flow | None:
    return session.scalars(
        select(Flow).where(Flow.is_default.is_(True)).limit(1)
    ).first() or session.scalars(select(Flow).order_by(Flow.id).limit(1)).first()


def de_flujo(flow: Flow) -> dict[str, bool]:
    config = step_config(flow.steps, "publish")
    return {
        "tiktok": bool(config.get("publish_tiktok", True)),
        "shorts": bool(config.get("publish_youtube_shorts", False)),
    }


def cambiar(flow: Flow, *, tiktok: bool | None = None, shorts: bool | None = None) -> None:
    pasos = [dict(paso) for paso in (flow.steps or [])]
    encontrado = False
    for paso in pasos:
        if paso.get("type") != "publish":
            continue
        encontrado = True
        config = dict(paso.get("config") or {})
        if tiktok is not None:
            config["publish_tiktok"] = bool(tiktok)
        if shorts is not None:
            config["publish_youtube_shorts"] = bool(shorts)
        paso["config"] = config
    if not encontrado:
        pasos.append({
            "type": "publish", "enabled": True,
            "config": {
                **({"publish_tiktok": bool(tiktok)} if tiktok is not None else {}),
                **({"publish_youtube_shorts": bool(shorts)} if shorts is not None else {}),
            },
        })
    flow.steps = normalize_steps(pasos)


def _youtube(session: Session) -> tuple[Account | None, Account | None]:
    """(el canal con permiso para subir, el primero conectado aunque no lo tenga)."""
    publica = pipeline.publishable_youtube_account(session)
    cualquiera = session.scalars(
        select(Account)
        .where(Account.platform == Platform.youtube.value, Account.enabled.is_(True))
        .order_by(Account.id)
        .limit(1)
    ).first()
    return publica, cualquiera


def resumen(session: Session) -> dict[str, Any]:
    """Cada flujo en uso, a dónde manda los clips y qué falta para que salgan."""
    tiktok = session.scalars(
        select(Account)
        .where(Account.platform == Platform.tiktok.value, Account.enabled.is_(True))
        .order_by(Account.id)
    ).all()
    publica, cualquiera = _youtube(session)
    defecto = _flujo_por_defecto(session)

    uso: dict[int, list[str]] = {}
    for fuente in session.scalars(select(Source).where(Source.enabled.is_(True))).all():
        flujo_id = fuente.flow_id or (defecto.id if defecto else None)
        if flujo_id:
            uso.setdefault(flujo_id, []).append(fuente.name)

    flujos = []
    for flow in session.scalars(select(Flow).order_by(Flow.id)).all():
        en_uso = flow.id in uso or flow.is_default
        flujos.append({
            "id": flow.id,
            "name": flow.name,
            "icon": flow.icon,
            "is_default": bool(flow.is_default),
            "en_uso": en_uso,
            "canales": uso.get(flow.id, []),
            **de_flujo(flow),
        })
    flujos.sort(key=lambda f: (not f["en_uso"], not f["is_default"], f["id"]))

    return {
        "tiktok": [
            {"id": c.id, "nombre": f"@{c.handle}" if c.handle else c.display_name,
             "prueba": not (c.credentials or {}).get("access_token")}
            for c in tiktok
        ],
        "youtube": (
            {"id": publica.id, "nombre": publica.display_name} if publica else None
        ),
        # conectado para leer, pero sin el permiso de subir
        "youtube_sin_permiso": (
            {"id": cualquiera.id, "nombre": cualquiera.display_name}
            if cualquiera and not publica else None
        ),
        "flujos": flujos,
    }


def para_clip(session: Session, clip: Clip) -> dict[str, Any]:
    """Las casillas «Publicar en» de un clip, marcadas según su flujo."""
    flow = pipeline.resolve_flow(session, clip.flow_id, clip.video)
    marcas = de_flujo(flow)
    objetivo = pipeline.target_account_for(session, clip.video) if clip.video else None
    objetivo = objetivo or pipeline.default_tiktok_account(session)

    cuentas: list[dict[str, Any]] = []
    for cuenta in session.scalars(
        select(Account)
        .where(Account.platform == Platform.tiktok.value, Account.enabled.is_(True))
        .order_by(Account.id)
    ).all():
        cuentas.append({
            "account_id": cuenta.id,
            "plataforma": "tiktok",
            "nombre": f"@{cuenta.handle}" if cuenta.handle else cuenta.display_name,
            "marcada": marcas["tiktok"] and objetivo is not None and cuenta.id == objetivo.id,
            "puede": True,
            "aviso": "" if (cuenta.credentials or {}).get("access_token")
            else "Cuenta de prueba: la publicación se simula.",
        })

    publica, cualquiera = _youtube(session)
    largo = (clip.end_s - clip.start_s) > SHORT_MAX
    if publica:
        cuentas.append({
            "account_id": publica.id,
            "plataforma": "youtube",
            "nombre": publica.display_name,
            "marcada": marcas["shorts"] and not largo,
            "puede": True,
            "aviso": "Dura más de 3 minutos: YouTube no lo mostraría como Short."
            if largo else "",
        })
    elif cualquiera:
        cuentas.append({
            "account_id": cualquiera.id,
            "plataforma": "youtube",
            "nombre": cualquiera.display_name,
            "marcada": False,
            "puede": False,
            "aviso": "Para publicar Shorts, autoriza el canal en Cuentas → «Autorizar para publicar».",
        })
    return {
        "flujo": {"id": flow.id, "name": flow.name, **marcas},
        "cuentas": cuentas,
    }
