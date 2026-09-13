"""Piloto automático: conectar las cuentas y no volver a tocar nada.

Kevil ya sabía publicar solo, pero venía apagado y el interruptor estaba
escondido en las opciones del paso «Publicación» de cada flujo. Aquí se junta
todo lo que hace falta en un único sitio:

* cada flujo publica sin pedir permiso, en vez de esperar tu visto bueno;
* los clips se programan solos en la mejor hora de cada cuenta;
* los canales se vigilan y lo que subas entra en el proceso sin que hagas nada.

Al apagarlo, cada flujo vuelve al modo que tenía antes, no a uno inventado.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_schema import normalize_steps, step_config
from app.models import Account, Flow, Platform, Setting, Source

CLAVE = "autopilot"
CLAVE_PREVIO = "autopilot_modo_previo"


# --------------------------------------------------------------------------
# Leer y escribir el estado
# --------------------------------------------------------------------------
def _ajuste(session: Session, clave: str, por_defecto: Any = None) -> Any:
    fila = session.get(Setting, clave)
    return fila.value if fila is not None else por_defecto


def _guardar(session: Session, clave: str, valor: Any) -> None:
    fila = session.get(Setting, clave)
    if fila is None:
        session.add(Setting(key=clave, value=valor))
    else:
        fila.value = valor


def esta_activo(session: Session) -> bool:
    return bool(_ajuste(session, CLAVE, False))


# --------------------------------------------------------------------------
# Qué falta para que funcione solo
# --------------------------------------------------------------------------
def _cuentas_para_publicar(session: Session) -> list[Account]:
    """Cuentas a las que se puede publicar de verdad."""
    cuentas = []
    for cuenta in session.scalars(select(Account).where(Account.enabled.is_(True))).all():
        tiene_permiso = bool((cuenta.credentials or {}).get("access_token"))
        if cuenta.platform == Platform.tiktok.value or tiene_permiso:
            cuentas.append(cuenta)
    return cuentas


def requisitos(session: Session) -> list[dict[str, Any]]:
    """Lo que hace falta para que Kevil pueda trabajar sin ti.

    Se devuelven todos, cumplidos y no cumplidos, para poder enseñar una lista
    con lo que ya está y lo que falta en vez de un simple «no se puede».
    """
    canales = session.scalars(select(Source).where(Source.enabled.is_(True))).all()
    cuentas = _cuentas_para_publicar(session)
    tiktok = [c for c in cuentas if c.platform == Platform.tiktok.value]
    youtube = [c for c in cuentas if c.platform == Platform.youtube.value]

    return [
        {
            "clave": "canal",
            "titulo": "Un canal de YouTube del que sacar vídeos",
            "cumplido": bool(canales),
            "detalle": (
                f"{len(canales)} canal(es) vigilado(s)" if canales
                else "Añádelo en Cuentas → Conectar canal"
            ),
            "accion": "#cuentas",
        },
        {
            "clave": "destino",
            "titulo": "Al menos una cuenta donde publicar",
            "cumplido": bool(cuentas),
            "detalle": (
                " · ".join(
                    filter(None, [
                        f"{len(tiktok)} TikTok" if tiktok else "",
                        f"{len(youtube)} YouTube" if youtube else "",
                    ])
                )
                or "Conecta TikTok o tu canal de YouTube"
            ),
            "accion": "#cuentas",
        },
    ]


def falta_algo(session: Session) -> list[str]:
    return [r["titulo"] for r in requisitos(session) if not r["cumplido"]]


# --------------------------------------------------------------------------
# Encender y apagar
# --------------------------------------------------------------------------
def _con_publicacion_automatica(pasos: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Deja los pasos listos para publicar solo. Devuelve el modo anterior."""
    pasos = normalize_steps(pasos)
    anterior = str(step_config(pasos, "publish").get("mode", "review"))
    for paso in pasos:
        if paso["type"] == "publish":
            paso["enabled"] = True
            paso["config"]["mode"] = "auto"
        elif paso["type"] == "schedule":
            paso["enabled"] = True
            paso["config"]["auto_schedule"] = True
    return pasos, anterior


def activar(session: Session) -> dict[str, Any]:
    """Todo en automático: cortar, programar y publicar sin preguntar."""
    previos: dict[str, str] = dict(_ajuste(session, CLAVE_PREVIO, {}) or {})

    flujos = session.scalars(select(Flow).where(Flow.enabled.is_(True))).all()
    for flujo in flujos:
        pasos, anterior = _con_publicacion_automatica(flujo.steps or [])
        # sólo se apunta el modo original la primera vez, para no guardar
        # «auto» encima de sí mismo si se enciende dos veces seguidas
        previos.setdefault(str(flujo.id), anterior)
        flujo.steps = pasos

    canales = session.scalars(select(Source)).all()
    for canal in canales:
        canal.auto_ingest = True
        canal.enabled = True

    _guardar(session, CLAVE_PREVIO, previos)
    _guardar(session, CLAVE, True)
    # sin esto lo recién escrito aún no se ve y se devolvería el estado viejo
    session.flush()
    return estado(session) | {"flows": len(flujos), "sources": len(canales)}


def desactivar(session: Session) -> dict[str, Any]:
    """Vuelve a pedirte el visto bueno antes de publicar."""
    previos: dict[str, str] = dict(_ajuste(session, CLAVE_PREVIO, {}) or {})

    for flujo in session.scalars(select(Flow)).all():
        pasos = normalize_steps(flujo.steps or [])
        # se devuelve el modo que tenía cada flujo, no uno inventado
        anterior = previos.get(str(flujo.id), "review")
        for paso in pasos:
            if paso["type"] == "publish":
                paso["config"]["mode"] = anterior
        flujo.steps = pasos

    _guardar(session, CLAVE_PREVIO, {})
    _guardar(session, CLAVE, False)
    session.flush()
    return estado(session)


def estado(session: Session) -> dict[str, Any]:
    """Cómo está ahora mismo y qué le falta."""
    lista = requisitos(session)
    flujos = session.scalars(select(Flow).where(Flow.enabled.is_(True))).all()
    automaticos = [
        flujo for flujo in flujos
        if step_config(normalize_steps(flujo.steps or []), "publish").get("mode") == "auto"
    ]
    canales = session.scalars(
        select(Source).where(Source.enabled.is_(True), Source.auto_ingest.is_(True))
    ).all()

    return {
        "enabled": esta_activo(session),
        "ready": all(r["cumplido"] for r in lista),
        "requirements": lista,
        "missing": [r["titulo"] for r in lista if not r["cumplido"]],
        "flows_total": len(flujos),
        "flows_auto": len(automaticos),
        "sources_watched": len(canales),
    }
