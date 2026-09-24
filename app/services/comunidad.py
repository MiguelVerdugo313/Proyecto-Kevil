"""Contenido de comunidad: encuestas, avisos, preguntas y carruseles.

Además de los clips, un canal vive de lo que pasa entre vídeo y vídeo: la
pestaña «Comunidad» (Publicaciones) de YouTube y los carruseles de fotos de
TikTok. YouTube no deja que ninguna aplicación lea ni publique esas entradas,
así que Kevil hace lo que sí puede: te las **propone** ya escritas, a partir de
tus vídeos, tus directos y tus mejores clips, con la hora a la que conviene
sacarlas; te **avisa** cuando toca; y tú las pegas con un clic. Al marcarlas
como hechas, el coach las cuenta.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Clip, ClipStatus, Platform, Setting, Video, utcnow
from app.services import notifications
from app.services.timing import DAYS, get_zone, hora_12, to_local, to_utc_naive, zona_local

log = logging.getLogger(__name__)

CLAVE = "comunidad_ideas"
HISTORIAL_MAX = 80
POR_SEMANA = 3                  # lo que YouTube recomienda: 2 o 3 entre vídeo y vídeo

TIPOS: dict[str, dict[str, str]] = {
    "encuesta": {"nombre": "Encuesta", "plataforma": "youtube", "icono": "📊"},
    "quiz": {"nombre": "Cuestionario", "plataforma": "youtube", "icono": "🧠"},
    "adelanto": {"nombre": "Aviso de lo próximo", "plataforma": "youtube", "icono": "🔴"},
    "imagen": {"nombre": "Imagen con pregunta", "plataforma": "youtube", "icono": "🖼️"},
    "texto": {"nombre": "Pregunta a la comunidad", "plataforma": "youtube", "icono": "💬"},
    "tiktok_fotos": {"nombre": "Carrusel de fotos", "plataforma": "tiktok", "icono": "🎞️"},
}

OPCIONES_MAX = 5                 # una encuesta de YouTube admite hasta 5


# --------------------------------------------------------------- guardado
def _leer(session: Session) -> list[dict[str, Any]]:
    fila = session.get(Setting, CLAVE)
    return [dict(i) for i in ((fila.value if fila else None) or [])]


def _guardar(session: Session, ideas: list[dict[str, Any]]) -> None:
    vivas = [i for i in ideas if i.get("estado") in ("propuesta", "programada")]
    pasadas = [i for i in ideas if i.get("estado") not in ("propuesta", "programada")]
    pasadas.sort(key=lambda i: i.get("hecha_at") or i.get("creada") or "", reverse=True)
    lista = vivas + pasadas[:HISTORIAL_MAX]
    fila = session.get(Setting, CLAVE)
    if fila is None:
        session.add(Setting(key=CLAVE, value=lista))
    else:
        fila.value = lista
    session.flush()


def _iso(fecha: datetime | None) -> str | None:
    return fecha.isoformat() + "Z" if fecha else None


def _fecha(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.fromisoformat(str(texto).rstrip("Z"))
    except ValueError:
        return None


# --------------------------------------------------------------- contexto
def _canal(session: Session) -> Account | None:
    return session.scalars(
        select(Account)
        .where(Account.platform == Platform.youtube.value, Account.enabled.is_(True))
        .order_by(Account.id)
        .limit(1)
    ).first()


def _juego(titulo: str) -> str:
    """«MINECRAFT HARDCORE | Día 5» → «Minecraft Hardcore»."""
    trozo = re.split(r"\s[|\-–—:]\s|[|#]", titulo or "", maxsplit=1)[0].strip(" .!¡¿?")
    trozo = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", trozo).strip()
    if not trozo or len(trozo) > 32:
        return ""
    # «MINECRAFT HARDCORE» se suaviza; «FNAF 2 PLUS» (siglas) se deja como está
    return trozo.title() if trozo.isupper() and len(trozo) > 12 else trozo


def _corto(titulo: str, largo: int = 55) -> str:
    """Un título que quepa en una opción de encuesta."""
    base = re.split(r"\s[|–—]\s|\|", titulo or "", maxsplit=1)[0].strip()
    base = re.sub(r"([!?¡¿])\1+", r"\1", base)
    return base if len(base) <= largo else base[: largo - 1].rstrip() + "…"


def contexto(session: Session) -> dict[str, Any]:
    """Lo que Kevil sabe de tu canal para escribir las propuestas."""
    from app.services import coach

    videos = session.scalars(
        select(Video).order_by(Video.published_at.desc().nullslast(), Video.id.desc()).limit(20)
    ).all()
    historial = coach.historial(session)[:20]
    titulos = [v.title for v in videos] + [h.get("title", "") for h in historial]
    juegos = [j for j, _ in Counter(filter(None, map(_juego, titulos))).most_common(6)]

    clips = session.scalars(
        select(Clip)
        .where(Clip.status.in_([
            ClipStatus.rendered.value, ClipStatus.approved.value, ClipStatus.scheduled.value,
            ClipStatus.published.value,
        ]))
        .order_by(Clip.score.desc())
        .limit(8)
    ).all()

    try:
        consejo = coach.recommendation(session)
    except Exception:  # noqa: BLE001 - sin datos del canal todavía
        consejo = {"stats": {}}
    stats = consejo.get("stats") or {}
    cuenta = _canal(session)

    ultimo = videos[0] if videos else None
    return {
        "canal": cuenta.display_name if cuenta else "",
        "canal_id": cuenta.external_id if cuenta else "",
        "juegos": juegos,
        "ultimo": {
            "titulo": ultimo.title,
            "url": ultimo.url,
            "directo": bool(ultimo.was_live),
            "duracion_s": ultimo.duration_s or 0,
            "miniatura": ultimo.thumbnail_url,
        } if ultimo else None,
        "hace_directos": any(v.was_live for v in videos),
        "top": [
            {"titulo": t.get("title", ""), "visitas": t.get("views", 0)}
            for t in (stats.get("top_videos") or [])
        ],
        "clips": [
            {
                "id": c.id, "titulo": c.title, "gancho": c.hook,
                "video": c.video.title if c.video else "",
                "url": c.video.url if c.video else "",
                "video_id": c.video_id,
                # sin miniatura aún: se usa la del vídeo (o ninguna)
                "imagen": f"/api/clips/{c.id}/thumb" if _existe(c.thumb_path)
                else (c.video.thumbnail_url if c.video else ""),
            }
            for c in clips
        ],
        "franjas": [(s["day"], s["hour"]) for s in (stats.get("best_slots") or [])],
        "proxima_subida": consejo.get("next_upload_at"),
        "dias_desde": stats.get("days_since_last"),
    }


def _existe(ruta: str | None) -> bool:
    from pathlib import Path

    return bool(ruta) and Path(ruta).exists()


# --------------------------------------------------------------- horas
def _horas(ctx: dict[str, Any], cuantas: int) -> list[datetime]:
    """Una hora buena por día, empezando mañana (o hoy si aún da tiempo).

    Las publicaciones de comunidad funcionan a la hora a la que tu gente está
    mirando: se usan tus mejores franjas; si aún no las hay, las 7 de la tarde.
    """
    zona = get_zone(zona_local())
    ahora = to_local(utcnow(), zona)
    horas_por_dia = {dia: hora for dia, hora in reversed(ctx.get("franjas") or [])}
    comun = Counter(h for _, h in ctx.get("franjas") or []).most_common(1)
    por_defecto = comun[0][0] if comun else 19

    resultado: list[datetime] = []
    dia = 0
    while len(resultado) < cuantas and dia < 30:
        fecha = (ahora + timedelta(days=dia)).date()
        hora = horas_por_dia.get(fecha.weekday(), por_defecto)
        momento = datetime(fecha.year, fecha.month, fecha.day, hora, 0, tzinfo=zona)
        if momento > ahora + timedelta(hours=1):
            resultado.append(to_utc_naive(momento))
        # un día sí y otro no: 3 o 4 por semana, sin agobiar
        dia += 2 if resultado else 1
    return resultado


def _a_buena_hora(fecha: datetime | None, ctx: dict[str, Any]) -> datetime | None:
    """La próxima subida que calcula el coach es «a los N días»: aquí se pone
    ese día (o mañana, si ya es casi ahora) a tu hora de siempre."""
    if not fecha:
        return None
    zona = get_zone(zona_local())
    ahora = to_local(utcnow(), zona)
    dia = max(to_local(fecha, zona).date(), (ahora + timedelta(hours=8)).date())
    horas_por_dia = {d: h for d, h in reversed(ctx.get("franjas") or [])}
    comun = Counter(h for _, h in ctx.get("franjas") or []).most_common(1)
    hora = horas_por_dia.get(dia.weekday(), comun[0][0] if comun else 19)
    return to_utc_naive(datetime(dia.year, dia.month, dia.day, hora, 0, tzinfo=zona))


def _cuando_texto(fecha: datetime) -> str:
    local = to_local(fecha, get_zone(zona_local()))
    return f"{DAYS[local.weekday()].lower()} a las {hora_12(local.hour, local.minute)}"


# --------------------------------------------------------------- plantillas
def _semilla(*partes: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, partes)).encode()).hexdigest()[:8], 16)


def _plantillas(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Propuestas sin IA: salen de tus datos y siempre funcionan."""
    ideas: list[dict[str, Any]] = []
    ultimo = ctx.get("ultimo")
    juegos = ctx.get("juegos") or []
    clips = ctx.get("clips") or []
    semana = utcnow().isocalendar()[1]

    # 1. Encuesta: qué jugar / qué ver
    if len(juegos) >= 2:
        opciones = juegos[:OPCIONES_MAX - 1] + ["Algo nuevo (decidme en comentarios)"]
        ideas.append({
            "tipo": "encuesta",
            "titulo": "¿Qué jugamos en el próximo directo?",
            "texto": "Vosotros decidís 👇 ¿Qué queréis ver en el próximo directo?",
            "opciones": opciones,
            "por_que": "Las encuestas son lo que más interacción da en Comunidad y te "
                       "dicen qué directo va a funcionar antes de hacerlo.",
        })
    else:
        ideas.append({
            "tipo": "encuesta",
            "titulo": "¿Qué queréis ver ahora?",
            "texto": "Estoy preparando lo próximo del canal. ¿Qué os apetece más? 👇",
            "opciones": ["Directo largo", "Retos", "Vídeo editado", "Jugar con suscriptores"],
            "por_que": "Una encuesta cuesta un segundo contestarla: sube la interacción "
                       "y te da ideas de lo que pide tu gente.",
        })

    # 2. Aviso de lo próximo (o encuesta de horario si no hay fecha)
    proxima = _a_buena_hora(_fecha(ctx.get("proxima_subida")), ctx)
    if proxima and proxima > utcnow():
        que = "directo" if ctx.get("hace_directos") else "vídeo"
        ideas.append({
            "tipo": "adelanto",
            "titulo": f"Aviso: próximo {que}",
            "texto": f"🔴 El {_cuando_texto(proxima)} hay {que} nuevo. "
                     f"Activad la campanita 🔔 para no perdéroslo. ¿Qué esperáis ver?",
            "opciones": [],
            "por_que": "Avisar unas horas antes llena los primeros minutos, que es "
                       "cuando YouTube decide a cuánta gente enseñarlo.",
            "_cuando": proxima - timedelta(hours=3),
        })
    elif ctx.get("franjas"):
        opciones = [f"{DAYS[d]} · {hora_12(h)}" for d, h in ctx["franjas"][:4]]
        ideas.append({
            "tipo": "encuesta",
            "titulo": "¿A qué hora os viene mejor el directo?",
            "texto": "Quiero poner un horario fijo para los directos. ¿Cuándo podéis? ⏰",
            "opciones": opciones,
            "por_que": "Un horario fijo que elige tu gente hace que vuelvan solos.",
        })

    # 3. Imagen de un buen momento (miniatura del mejor clip)
    con_imagen = [c for c in clips if c.get("imagen")]
    if con_imagen:
        clip = con_imagen[_semilla(semana, "imagen") % min(3, len(con_imagen))]
        gancho = clip.get("gancho") or clip.get("titulo") or "este momento"
        ideas.append({
            "tipo": "imagen",
            "titulo": "¿Os acordáis de esto?",
            "texto": f"😂 {gancho}\n\n¿Quién estaba en el directo cuando pasó? "
                     f"Momento completo aquí: {clip.get('url') or ''}".strip(),
            "opciones": [],
            "imagenes": [clip["imagen"]],
            "por_que": "Una imagen con pregunta recupera un vídeo antiguo y manda "
                       "visitas al directo completo.",
        })

    # 4. Pregunta sobre el último vídeo
    if ultimo:
        que = "el directo" if ultimo.get("directo") else "el último vídeo"
        ideas.append({
            "tipo": "texto",
            "titulo": f"¿Qué os pareció {que}?",
            "texto": f"¿Qué os pareció {que}, «{_corto(ultimo['titulo'], 80)}»? "
                     f"Os leo todos en comentarios 👇\n{ultimo.get('url') or ''}".strip(),
            "opciones": [],
            "imagen": ultimo.get("miniatura") or "",
            "por_que": "Preguntar por el último vídeo le da una segunda vida y los "
                       "comentarios cuentan para el algoritmo.",
        })

    # 5. Cuestionario con tus propios números
    top = [t for t in ctx.get("top") or [] if t.get("titulo")]
    if len(top) >= 3:
        opciones = [_corto(t["titulo"]) for t in top[:4]]
        ideas.append({
            "tipo": "quiz",
            "titulo": "¿Cuál es el vídeo más visto del canal?",
            "texto": "🧠 A ver quién conoce el canal: ¿cuál es el vídeo con más visitas?",
            "opciones": opciones,
            "correcta": 0,
            "por_que": "Los cuestionarios enganchan y llevan a la gente a ver tus "
                       "mejores vídeos otra vez.",
        })

    # 6. Carrusel de TikTok con los mejores momentos
    del_mismo: dict[int, list[dict[str, Any]]] = {}
    for clip in clips:
        del_mismo.setdefault(clip["video_id"], []).append(clip)
    grupo = max(del_mismo.values(), key=len, default=[])
    if len(grupo) >= 2:
        n = min(4, len(grupo))
        ideas.append({
            "tipo": "tiktok_fotos",
            "titulo": f"Top {n} momentos",
            "texto": f"Top {n} momentos de «{_corto(grupo[0]['video'], 45)}» 🔥 "
                     f"¿Cuál es el mejor? 👇 #gaming #directo",
            "opciones": [],
            "imagenes": [c["imagen"] for c in grupo[:4] if c.get("imagen")],
            "por_que": "En TikTok los carruseles de fotos se reparten aparte de los "
                       "vídeos: más alcance con lo que ya tienes.",
        })
    return ideas


# --------------------------------------------------------------- con IA
SISTEMA = (
    "Eres el community manager de un creador de contenido de videojuegos que hace "
    "directos en YouTube y sube clips a TikTok. Escribes en español, cercano, con "
    "algún emoji, frases cortas. Nada de hashtags en YouTube; en TikTok 2 o 3."
)


def _con_ia(ctx: dict[str, Any], base: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """La IA reescribe las propuestas con más gracia; si falla, se quedan las de base."""
    from app.services import ai

    if not ai.is_enabled():
        return base
    resumen = {
        "canal": ctx.get("canal"),
        "juegos_recientes": ctx.get("juegos"),
        "ultimo_video": (ctx.get("ultimo") or {}).get("titulo"),
        "hace_directos": ctx.get("hace_directos"),
        "mejores_clips": [c.get("gancho") or c.get("titulo") for c in ctx.get("clips", [])[:5]],
        "videos_mas_vistos": [t["titulo"] for t in ctx.get("top", [])[:4]],
    }
    borrador = [
        {"n": i, "tipo": idea["tipo"], "titulo": idea["titulo"], "texto": idea["texto"],
         "opciones": idea.get("opciones", [])}
        for i, idea in enumerate(base)
    ]
    prompt = (
        "Datos del canal:\n"
        f"{resumen}\n\n"
        "Estas son publicaciones de comunidad propuestas (YouTube Comunidad y un carrusel "
        "de TikTok). Mejora el título y el texto para que den ganas de contestar, "
        "usando los datos reales del canal. Mantén el mismo tipo y el mismo número. "
        "En encuestas deja entre 2 y 5 opciones de menos de 60 caracteres; en el "
        "cuestionario («quiz») NO cambies las opciones.\n\n"
        f"{borrador}\n\n"
        'Devuelve una lista JSON: [{"n": 0, "titulo": "...", "texto": "...", "opciones": ["..."]}]'
    )
    try:
        respuesta = ai.chat_json(prompt, system=SISTEMA, temperature=0.8, max_tokens=1800)
    except Exception as exc:  # noqa: BLE001 - sin IA se usan las de base
        log.info("Comunidad sin IA: %s", exc)
        return base
    if not isinstance(respuesta, list):
        return base

    mejoradas = [dict(i) for i in base]
    for item in respuesta:
        if not isinstance(item, dict):
            continue
        try:
            n = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        if not 0 <= n < len(mejoradas):
            continue
        idea = mejoradas[n]
        titulo = str(item.get("titulo") or "").strip()
        texto = str(item.get("texto") or "").strip()
        if titulo:
            idea["titulo"] = titulo[:120]
        if texto:
            # los enlaces de la propuesta de base no se pierden
            enlaces = re.findall(r"https?://\S+", base[n]["texto"])
            idea["texto"] = texto[:1200] + "".join(
                f"\n{e}" for e in enlaces if e not in texto
            )
        opciones = item.get("opciones")
        if (idea["tipo"] == "encuesta" and isinstance(opciones, list)
                and 2 <= len(opciones) <= OPCIONES_MAX):
            idea["opciones"] = [str(o).strip()[:65] for o in opciones if str(o).strip()]
        idea["origen"] = "ia"
    return mejoradas


# --------------------------------------------------------------- API del servicio
def _enlace(tipo: str, canal_id: str) -> str:
    if TIPOS.get(tipo, {}).get("plataforma") == "tiktok":
        return "https://www.tiktok.com/upload"
    if canal_id.startswith("UC"):
        return f"https://www.youtube.com/channel/{canal_id}/community"
    return "https://studio.youtube.com"


def _completar(idea: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    tipo = TIPOS.get(idea["tipo"], TIPOS["texto"])
    imagenes = [i for i in (idea.get("imagenes") or []) if i]
    if idea.get("imagen"):
        imagenes.append(idea["imagen"])
    return {
        "id": uuid.uuid4().hex[:10],
        "tipo": idea["tipo"],
        "tipo_nombre": tipo["nombre"],
        "icono": tipo["icono"],
        "plataforma": tipo["plataforma"],
        "titulo": idea["titulo"],
        "texto": idea["texto"],
        "opciones": idea.get("opciones") or [],
        "correcta": idea.get("correcta"),
        "imagenes": imagenes,
        "por_que": idea.get("por_que", ""),
        "enlace": _enlace(idea["tipo"], ctx.get("canal_id") or ""),
        "origen": idea.get("origen", "plantilla"),
        "estado": "propuesta",
        "cuando": None,
        "creada": _iso(utcnow()),
    }


def proponer(session: Session, *, usar_ia: bool = True) -> list[dict[str, Any]]:
    """Genera propuestas nuevas y sustituye las que seguían sin usar.

    Las que programaste o ya hiciste se quedan como están.
    """
    ctx = contexto(session)
    base = _plantillas(ctx)
    if usar_ia:
        base = _con_ia(ctx, base)

    nuevas = [_completar(idea, ctx) for idea in base]
    # las que tienen su hora (el aviso del próximo directo) mandan; las demás
    # van en días distintos, sin pisarse con ellas
    zona = get_zone(zona_local())
    fijas = {
        i: original["_cuando"] for i, original in enumerate(base)
        if original.get("_cuando") and original["_cuando"] > utcnow()
    }
    ocupados = {to_local(f, zona).date() for f in fijas.values()}
    libres = iter([
        h for h in _horas(ctx, len(nuevas) + len(fijas))
        if to_local(h, zona).date() not in ocupados
    ])
    for i, nueva in enumerate(nuevas):
        nueva["cuando"] = _iso(fijas.get(i) or next(libres, None))
    nuevas.sort(key=lambda i: i["cuando"] or "9")

    conservadas = [i for i in _leer(session) if i.get("estado") != "propuesta"]
    _guardar(session, nuevas + conservadas)
    return listar(session)


def listar(session: Session) -> list[dict[str, Any]]:
    ideas = _leer(session)
    orden = {"programada": 0, "propuesta": 1, "hecha": 2, "descartada": 3}
    ideas.sort(key=lambda i: (orden.get(i.get("estado"), 9), i.get("cuando") or "9"))
    return ideas


def resumen(session: Session) -> dict[str, Any]:
    """Lo que pinta el coach y el panel: la siguiente y cuántas llevas."""
    ideas = _leer(session)
    hace_una_semana = utcnow() - timedelta(days=7)
    hechas = [
        i for i in ideas
        if i.get("estado") == "hecha" and (_fecha(i.get("hecha_at")) or datetime.min) >= hace_una_semana
    ]
    pendientes = [i for i in ideas if i.get("estado") in ("propuesta", "programada")]
    pendientes.sort(key=lambda i: i.get("cuando") or "9")
    return {
        "hechas_semana": len(hechas),
        "objetivo_semana": POR_SEMANA,
        "siguiente": pendientes[0] if pendientes else None,
        "pendientes": len(pendientes),
    }


def cambiar(session: Session, idea_id: str, **cambios: Any) -> dict[str, Any] | None:
    ideas = _leer(session)
    for idea in ideas:
        if idea.get("id") != idea_id:
            continue
        estado = cambios.get("estado")
        if estado in ("propuesta", "programada", "hecha", "descartada"):
            idea["estado"] = estado
            if estado == "hecha":
                idea["hecha_at"] = _iso(utcnow())
        if "cuando" in cambios:
            fecha = _fecha(cambios["cuando"])
            idea["cuando"] = _iso(fecha)
            idea["avisada"] = False
        for campo in ("titulo", "texto"):
            if isinstance(cambios.get(campo), str) and cambios[campo].strip():
                idea[campo] = cambios[campo].strip()[:1500]
        if isinstance(cambios.get("opciones"), list):
            idea["opciones"] = [str(o).strip()[:65] for o in cambios["opciones"] if str(o).strip()][
                :OPCIONES_MAX
            ]
        _guardar(session, ideas)
        return idea
    return None


def tocan(session: Session) -> int:
    """Cuántas programadas han llegado a su hora y siguen sin publicar."""
    ahora = utcnow()
    return sum(
        1 for i in _leer(session)
        if i.get("estado") == "programada" and (_fecha(i.get("cuando")) or ahora) <= ahora
    )


def avisar_las_que_tocan(session: Session) -> int:
    """Las programadas cuya hora ha llegado: un aviso para que las publiques."""
    ideas = _leer(session)
    avisadas = 0
    ahora = utcnow()
    for idea in ideas:
        if idea.get("estado") != "programada" or idea.get("avisada"):
            continue
        cuando = _fecha(idea.get("cuando"))
        if not cuando or cuando > ahora:
            continue
        donde = "TikTok" if idea.get("plataforma") == "tiktok" else "la Comunidad de YouTube"
        notifications.notify(
            session,
            f"Toca publicar en {donde}: {idea.get('titulo', '')[:80]}",
            "El texto ya está escrito: ábrelo, cópialo y pégalo.",
            kind="comunidad",
            level="info",
            action_label="Abrir",
            action_url="#comunidad",
            dedupe_hours=0,
        )
        idea["avisada"] = True
        avisadas += 1
    if avisadas:
        _guardar(session, ideas)
    return avisadas


def asegurar(session: Session) -> list[dict[str, Any]]:
    """Si no queda ninguna propuesta pendiente, se hacen unas (sin IA: al momento)."""
    ideas = _leer(session)
    if not any(i.get("estado") in ("propuesta", "programada") for i in ideas):
        return proponer(session, usar_ia=False)
    return listar(session)
