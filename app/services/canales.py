"""El canal que conectas es también el que se vigila.

Hay dos maneras de «conectar» YouTube: pegar la URL del canal (para que Kevil
busque vídeos y saque clips) y autorizarlo con Google (para publicar Shorts).
Antes eran dos cosas separadas y, si sólo hacías la segunda, la aplicación
decía «cuenta conectada» pero no buscaba nada. Ahora autorizar el canal lo deja
también vigilado, salvo que tú lo hayas quitado a propósito.
"""

from __future__ import annotations

import logging

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Account, Platform, Setting, Source
from app.services import events
from app.services.queue import enqueue

log = logging.getLogger(__name__)

# Canales que quitaste de «Canales vigilados»: no se vuelven a añadir solos.
NO_VIGILAR_KEY = "canales_sin_vigilar"


def url_del_canal(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}"


def fuente_de(session: Session, account: Account) -> Source | None:
    """La fuente que vigila el canal de esta cuenta, si la hay."""
    canal = account.external_id or ""
    condiciones = [Source.account_id == account.id]
    if canal.startswith("UC"):
        condiciones += [Source.channel_id == canal, Source.url.like(f"%/channel/{canal}%")]
    return session.scalars(
        select(Source)
        .where(Source.kind == "channel", or_(*condiciones))
        .order_by(Source.id)
        .limit(1)
    ).first()


def _no_vigilar(session: Session) -> list[str]:
    registro = session.get(Setting, NO_VIGILAR_KEY)
    return list((registro.value if registro else None) or [])


def recordar_que_no(session: Session, channel_id: str) -> None:
    """Quitaste el canal de los vigilados: se respeta."""
    if not channel_id:
        return
    lista = _no_vigilar(session)
    if channel_id in lista:
        return
    lista.append(channel_id)
    registro = session.get(Setting, NO_VIGILAR_KEY)
    if registro is None:
        session.add(Setting(key=NO_VIGILAR_KEY, value=lista))
    else:
        registro.value = lista


def lo_quitaste(session: Session, account: Account) -> bool:
    return (account.external_id or "") in _no_vigilar(session)


def olvidar_que_no(session: Session, channel_id: str) -> None:
    lista = [c for c in _no_vigilar(session) if c != channel_id]
    registro = session.get(Setting, NO_VIGILAR_KEY)
    if registro is not None:
        registro.value = lista


def vigilar(
    session: Session, account: Account, *, aunque_lo_quitaras: bool = False
) -> Source | None:
    """Deja vigilado el canal de una cuenta de YouTube. Devuelve la fuente.

    Si ya lo estaba se devuelve la que hay (y se reactiva si pediste vigilarlo
    a mano). Si lo quitaste tú, sólo se vuelve a vigilar cuando lo pides.
    """
    if account.platform != Platform.youtube.value:
        return None
    canal = account.external_id or ""
    existente = fuente_de(session, account)
    if existente is not None:
        if aunque_lo_quitaras and not (existente.enabled and existente.auto_ingest):
            existente.enabled = True
            existente.auto_ingest = True
            _revisar(session, existente)
        if existente.account_id is None:
            existente.account_id = account.id
        return existente

    if not canal.startswith("UC"):
        return None               # sin el ID del canal no hay nada que vigilar
    if canal in _no_vigilar(session) and not aunque_lo_quitaras:
        return None
    olvidar_que_no(session, canal)

    fuente = Source(
        account_id=account.id,
        name=account.display_name or "Mi canal",
        url=url_del_canal(canal),
        channel_id=canal,
        kind="channel",
        auto_ingest=True,
        include_lives=True,
        include_shorts=False,
        backfill_limit=20,
        min_duration_s=20,
    )
    session.add(fuente)
    session.flush()
    _revisar(session, fuente)
    events.log(
        session,
        f"Vigilando «{fuente.name}»: se buscan vídeos y directos para sacar clips",
        level="success",
        scope="canal",
    )
    return fuente


def _revisar(session: Session, fuente: Source) -> None:
    enqueue(
        session,
        "sync_source",
        {"source_id": fuente.id},
        priority=80,
        message=f"Revisar «{fuente.name}»",
    )


def cuentas_sin_vigilar(session: Session) -> list[Account]:
    """Canales conectados que nadie vigila (y que no quitaste tú)."""
    quitados = set(_no_vigilar(session))
    sueltas = []
    for account in session.scalars(
        select(Account).where(
            Account.platform == Platform.youtube.value, Account.enabled.is_(True)
        )
    ).all():
        if (account.external_id or "") in quitados:
            continue
        fuente = fuente_de(session, account)
        if fuente is None or not (fuente.enabled and fuente.auto_ingest):
            sueltas.append(account)
    return sueltas


def vigilar_los_conectados(session: Session) -> int:
    """Al abrir: el canal autorizado que no se vigilaba pasa a vigilarse."""
    creadas = 0
    for account in session.scalars(
        select(Account).where(
            Account.platform == Platform.youtube.value, Account.enabled.is_(True)
        )
    ).all():
        if fuente_de(session, account) is None and vigilar(session, account):
            creadas += 1
    return creadas
