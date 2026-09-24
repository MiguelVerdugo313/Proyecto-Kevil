"""Asistente del canal de YouTube: cada cuánto publicar y cuándo.

Todo sale de tus propios datos (los vídeos que ya has publicado, con sus
visitas y sus fechas), no de reglas inventadas:

* **Cadencia**: la mediana de días entre subidas. La constancia importa más
  que el número: el algoritmo aprende a esperar tu vídeo.
* **Regularidad**: cuánto varían esos huecos. Publicar cada 7 días exactos
  rinde más que 2 vídeos una semana y ninguno las tres siguientes.
* **Mejor día y hora**: los que mejor te han funcionado a ti, ponderando por
  visitas y descartando los vídeos con menos de una semana (aún están subiendo).
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account, Platform, Setting, Source, Video, utcnow
from app.services import notifications, youtube_api
from app.services.timing import get_zone, hora_12, to_local, zona_local

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

# Franjas recomendadas si aún no hay datos propios suficientes.
# (día de la semana, hora local) — tardes y fines de semana por la mañana.
DEFAULT_SLOTS = [(4, 17), (5, 11), (2, 18), (6, 11), (3, 17)]


# --------------------------------------------------------------------------
# De dónde salen tus subidas
#
# La lista de vídeos que baja yt-dlp de un canal no trae la fecha de cada uno,
# y por eso el coach se quedaba a cero aunque el canal estuviera conectado.
# Las fechas salen de dos sitios que sí las dan exactas:
#   * el feed público del canal (los últimos 15 vídeos, sin claves ni cuota);
#   * la API de YouTube si tienes el canal conectado (hasta 50, 2 unidades).
# Se guardan en un historial propio que se va ampliando con cada repaso.
# --------------------------------------------------------------------------
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
HISTORIAL_KEY = "historial_canal"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


@dataclass
class Subida:
    """Un vídeo publicado en tu canal (sirve igual venga de donde venga)."""

    id: str
    title: str
    published_at: datetime
    views: int = 0


def _fecha(texto: str) -> datetime | None:
    try:
        fecha = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


def leer_feed(channel_id: str, client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Los últimos vídeos del canal con su fecha exacta, del feed público."""
    propio = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True)
    try:
        respuesta = client.get(FEED.format(channel_id))
        respuesta.raise_for_status()
        raiz = ElementTree.fromstring(respuesta.text)
    finally:
        if propio:
            client.close()
    subidas: list[dict[str, Any]] = []
    for entrada in raiz.findall("atom:entry", NS):
        enlace = entrada.find("atom:link", NS)
        href = enlace.get("href", "") if enlace is not None else ""
        if "/shorts/" in href:
            continue              # los Shorts no marcan el ritmo de tus vídeos
        video_id = entrada.findtext("yt:videoId", default="", namespaces=NS)
        publicado = _fecha(entrada.findtext("atom:published", default="", namespaces=NS))
        if not video_id or not publicado:
            continue
        estadisticas = entrada.find("media:group/media:community/media:statistics", NS)
        subidas.append(
            {
                "id": video_id,
                "title": entrada.findtext("atom:title", default="", namespaces=NS),
                "published_at": publicado.isoformat(),
                "views": int((estadisticas.get("views") if estadisticas is not None else 0) or 0),
            }
        )
    return subidas


def _canales(session: Session) -> list[str]:
    """Los identificadores (UC…) de tus canales: los vigilados y el conectado."""
    ids: list[str] = []
    for source in session.scalars(select(Source)).all():
        canal = source.channel_id or ""
        if not canal:
            encontrado = re.search(r"/channel/(UC[\w-]{20,})", source.url or "")
            canal = encontrado.group(1) if encontrado else ""
        if canal.startswith("UC") and canal not in ids:
            ids.append(canal)
    for account in session.scalars(
        select(Account).where(Account.platform == Platform.youtube.value)
    ).all():
        if (account.external_id or "").startswith("UC") and account.external_id not in ids:
            ids.append(account.external_id)
    return ids


def _resolver_canales_sin_id(session: Session) -> None:
    """Los canales añadidos por @usuario no guardaban su id: se averigua una vez."""
    from app.services import youtube as youtube_service

    for source in session.scalars(select(Source).where(Source.channel_id == "")).all():
        try:
            info = youtube_service.resolve_channel(source.url)
        except Exception:  # noqa: BLE001 - sin red o sin yt-dlp: ya se hará
            continue
        if (info.get("channel_id") or "").startswith("UC"):
            source.channel_id = info["channel_id"]


def historial(session: Session) -> list[dict[str, Any]]:
    fila = session.get(Setting, HISTORIAL_KEY)
    return list((fila.value if fila else None) or [])


def actualizar_historial(session: Session) -> int:
    """Junta en el historial lo que digan el feed y la API. Devuelve cuántos hay."""
    _resolver_canales_sin_id(session)
    por_id = {item["id"]: item for item in historial(session)}

    for canal in _canales(session):
        try:
            for item in leer_feed(canal):
                por_id[item["id"]] = {**por_id.get(item["id"], {}), **item}
        except Exception:  # noqa: BLE001 - un canal sin feed no rompe el resto
            continue

    for account in session.scalars(
        select(Account).where(Account.platform == Platform.youtube.value)
    ).all():
        credenciales = account.credentials or {}
        if not credenciales.get("access_token"):
            continue
        try:
            credenciales = youtube_api.valid_credentials(credenciales)
            account.credentials = credenciales
            for item in youtube_api.fetch_uploads(credenciales, limit=50):
                por_id[item["id"]] = {**por_id.get(item["id"], {}), **item}
        except Exception:  # noqa: BLE001
            continue

    lista = sorted(por_id.values(), key=lambda i: i.get("published_at") or "", reverse=True)[:300]
    fila = session.get(Setting, HISTORIAL_KEY)
    if fila is None:
        session.add(Setting(key=HISTORIAL_KEY, value=lista))
    else:
        fila.value = lista
    session.flush()
    return len(lista)


def _uploads(session: Session, limit: int = 60) -> list[Subida]:
    """Tus subidas conocidas, sin repetir, de la más nueva a la más vieja."""
    por_id: dict[str, Subida] = {}
    for video in session.scalars(
        select(Video)
        .where(Video.origin == "youtube", Video.published_at.is_not(None))
        .order_by(Video.published_at.desc())
        .limit(limit * 2)
    ).all():
        por_id[video.external_id] = Subida(
            video.external_id, video.title, video.published_at, int(video.views or 0)
        )
    for item in historial(session):
        fecha = _fecha(item.get("published_at") or "")
        if not fecha:
            continue
        anterior = por_id.get(item["id"])
        por_id[item["id"]] = Subida(
            item["id"],
            item.get("title") or (anterior.title if anterior else ""),
            fecha,
            max(int(item.get("views") or 0), anterior.views if anterior else 0),
        )
    subidas = sorted(por_id.values(), key=lambda s: s.published_at, reverse=True)
    return subidas[:limit]


def tiene_canal(session: Session) -> bool:
    return bool(
        session.scalars(select(Source.id).limit(1)).first()
        or session.scalars(
            select(Account.id).where(Account.platform == Platform.youtube.value).limit(1)
        ).first()
    )


def channel_stats(session: Session) -> dict[str, Any]:
    """Radiografía del canal a partir de los vídeos conocidos."""
    videos = _uploads(session)
    now = utcnow()

    if not videos:
        return {
            "known_uploads": 0,
            "cadence_days": None,
            "regularity": None,
            "last_upload_at": None,
            "days_since_last": None,
            "uploads_30d": 0,
            "uploads_90d": 0,
            "median_views": 0,
            "best_slots": [],
            "top_videos": [],
            "has_data": False,
        }

    fechas = sorted((v.published_at for v in videos if v.published_at), reverse=True)
    huecos = [
        (fechas[i] - fechas[i + 1]).total_seconds() / 86400 for i in range(len(fechas) - 1)
    ]
    huecos = [h for h in huecos if 0 < h < 120]  # se ignoran pausas larguísimas

    cadencia = round(statistics.median(huecos), 1) if huecos else None
    regularidad = None
    if len(huecos) >= 3 and cadencia:
        desviacion = statistics.pstdev(huecos)
        # 1 = como un reloj, 0 = totalmente irregular
        regularidad = round(max(0.0, min(1.0, 1 - desviacion / max(cadencia, 1))), 2)

    ultimo = fechas[0]
    dias_desde = round((now - ultimo).total_seconds() / 86400, 1)

    visitas = [v.views for v in videos if v.views]
    mediana_visitas = int(statistics.median(visitas)) if visitas else 0

    # Mejores franjas según TUS resultados (sólo vídeos con más de 7 días)
    maduros = [
        v for v in videos
        if v.views and v.published_at and (now - v.published_at).days >= 7
    ]
    zona = get_zone(zona_local())
    franjas: dict[tuple[int, int], list[int]] = {}
    for video in maduros:
        local = to_local(video.published_at, zona)       # tu hora, no la de Londres
        clave = (local.weekday(), local.hour)
        franjas.setdefault(clave, []).append(video.views)

    mejores: list[dict[str, Any]] = []
    if len(maduros) >= 6:
        referencia = statistics.median([v.views for v in maduros]) or 1
        for (dia, hora), lista in franjas.items():
            media = sum(lista) / len(lista)
            mejores.append(
                {
                    "day": dia,
                    "hour": hora,
                    "label": f"{DAYS[dia]} · {hora_12(hora)}",
                    "videos": len(lista),
                    "avg_views": int(media),
                    "index": round(media / referencia, 2),
                }
            )
        mejores.sort(key=lambda s: (s["index"], s["videos"]), reverse=True)
        mejores = mejores[:5]
        fuente = "tu historial"
    else:
        mejores = [
            {
                "day": dia,
                "hour": hora,
                "label": f"{DAYS[dia]} · {hora_12(hora)}",
                "videos": 0,
                "avg_views": 0,
                "index": 1.0,
            }
            for dia, hora in DEFAULT_SLOTS
        ]
        fuente = "franjas de referencia"

    top = sorted(videos, key=lambda v: v.views or 0, reverse=True)[:5]

    return {
        "known_uploads": len(videos),
        "cadence_days": cadencia,
        "regularity": regularidad,
        "last_upload_at": ultimo.isoformat() + "Z",
        "days_since_last": dias_desde,
        "uploads_30d": len([f for f in fechas if (now - f).days <= 30]),
        "uploads_90d": len([f for f in fechas if (now - f).days <= 90]),
        "median_views": mediana_visitas,
        "best_slots": mejores,
        "slots_source": fuente,
        "timeline": [
            {"published_at": f.isoformat() + "Z"} for f in sorted(fechas)[-24:]
        ],
        "top_videos": [
            {
                "id": v.id,
                "title": v.title,
                "views": v.views,
                "published_at": v.published_at.isoformat() + "Z" if v.published_at else None,
            }
            for v in top
        ],
        "has_data": True,
    }


def recommendation(session: Session) -> dict[str, Any]:
    """Qué deberías hacer ahora mismo con tu canal."""
    stats = channel_stats(session)
    objetivo_semanal = max(0.25, float(settings.target_uploads_per_week or 2))
    objetivo_dias = round(7 / objetivo_semanal, 1)

    if not stats["has_data"]:
        conectado = tiene_canal(session)
        return {
            "stats": stats,
            "target_days": objetivo_dias,
            "target_per_week": objetivo_semanal,
            "state": "leyendo" if conectado else "sin_datos",
            "headline": "Leyendo tu canal…" if conectado else "Conecta tu canal para empezar",
            "detail": (
                "Kevil está mirando las fechas de tus vídeos publicados. En un momento "
                "verás tu ritmo real, tu último vídeo y cuándo te toca el siguiente."
                if conectado else
                "En cuanto Kevil vea tus vídeos publicados podrá calcular tu ritmo real, "
                "tu regularidad y las mejores franjas para subir."
            ),
            "next_upload_at": None,
            "overdue_days": 0,
            "actions": [] if conectado else ["Conecta tu canal de YouTube en «Cuentas»."],
        }

    cadencia = stats["cadence_days"] or objetivo_dias
    dias_desde = stats["days_since_last"] or 0

    # Fecha ideal de la próxima subida. Si ya se ha pasado, toca «ya».
    proxima = None
    retraso = 0.0
    if stats["last_upload_at"]:
        ultimo = datetime.fromisoformat(stats["last_upload_at"].rstrip("Z"))
        ideal = ultimo + timedelta(days=objetivo_dias)
        ahora = utcnow()
        if ideal < ahora:
            retraso = round((ahora - ideal).total_seconds() / 86400, 1)
            proxima = ahora
        else:
            proxima = ideal

    acciones: list[str] = []
    if dias_desde > objetivo_dias * 2:
        estado = "parado"
        titular = f"Llevas {int(dias_desde)} días sin publicar"
        detalle = (
            f"Tu ritmo era de un vídeo cada {cadencia} días. Cuando el canal se para, "
            f"YouTube deja de mostrar tus vídeos a los suscriptores menos activos. "
            f"Publica algo esta semana, aunque sea más corto de lo normal."
        )
        acciones.append("Sube un vídeo cuanto antes para retomar el ritmo.")
    elif dias_desde > objetivo_dias:
        estado = "retrasado"
        titular = f"Te toca publicar: van {int(dias_desde)} días"
        detalle = (
            f"Tu objetivo es un vídeo cada {objetivo_dias} días. "
            f"Mantener el hueco constante es lo que más ayuda a que te recomienden."
        )
        acciones.append("Prepara el próximo vídeo hoy o mañana.")
    else:
        estado = "al_dia"
        restantes = max(0, round(objetivo_dias - dias_desde, 1))
        titular = "Vas al día" if restantes else "Justo a tiempo"
        detalle = (
            f"Te quedan {restantes} días hasta tu próxima subida según tu objetivo "
            f"de {objetivo_semanal} vídeos por semana."
        )

    regularidad = stats["regularity"]
    if regularidad is not None and regularidad < 0.5:
        acciones.append(
            "Tus huecos entre vídeos varían mucho: fija un día concreto y respétalo."
        )
    if stats["best_slots"]:
        mejor = stats["best_slots"][0]
        acciones.append(f"Tu mejor franja: {mejor['label']} ({stats['slots_source']}).")
    if stats["uploads_30d"] == 0 and stats["known_uploads"]:
        acciones.append("Ningún vídeo en los últimos 30 días: recupera la constancia.")

    return {
        "stats": stats,
        "target_days": objetivo_dias,
        "target_per_week": objetivo_semanal,
        "state": estado,
        "headline": titular,
        "detail": detalle,
        "next_upload_at": proxima.isoformat() + "Z" if proxima else None,
        "overdue_days": retraso,
        "actions": acciones,
    }


def daily_check(session: Session) -> list[str]:
    """Repaso diario: pone al día tus subidas y genera los avisos que hagan falta."""
    creados: list[str] = []
    try:
        actualizar_historial(session)
    except Exception:  # noqa: BLE001 - sin red: se avisa con lo que ya se sabía
        pass
    data = recommendation(session)
    estado = data["state"]

    if estado == "parado":
        notifications.notify(
            session,
            data["headline"],
            data["detail"],
            kind="cadencia",
            level="warn",
            action_label="Ver el coach",
            action_url="#coach",
            dedupe_hours=48,
        )
        creados.append("cadencia")
    elif estado == "retrasado":
        notifications.notify(
            session,
            data["headline"],
            data["detail"],
            kind="cadencia",
            level="info",
            action_label="Ver el coach",
            action_url="#coach",
            dedupe_hours=24,
        )
        creados.append("cadencia")

    stats = data["stats"]
    if stats["has_data"] and stats["regularity"] is not None and stats["regularity"] < 0.4:
        notifications.notify(
            session,
            "Tu ritmo de publicación es irregular",
            "Los huecos entre tus vídeos varían mucho. Elige un día fijo de la semana: "
            "la constancia pesa más que la cantidad.",
            kind="regularidad",
            level="info",
            action_label="Ver el coach",
            action_url="#coach",
            dedupe_hours=24 * 7,
        )
        creados.append("regularidad")

    return creados
