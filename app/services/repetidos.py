"""Que nada se publique dos veces.

Dos fuentes de repetidos:

* **En Kevil**: el mismo momento del vídeo cortado dos veces (al volver a
  cortar, o en versiones anteriores), o el mismo clip aprobado dos veces para
  la misma cuenta.
* **Fuera de Kevil**: lo que ya subió una versión anterior (con su propia
  carpeta de datos, que no sabe nada de esta) y ya está en tu canal o en tu
  TikTok, publicado o programado.

Antes de subir algo se mira si ya existe de verdad en la plataforma; si está,
se enlaza en vez de subirlo otra vez. Y al abrir Kevil (o con «Buscar
repetidos») se repasa todo lo programado.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account, Clip, ClipStatus, Platform, Post, PostStatus, utcnow
from app.services import events, notifications
from app.services.queue import JobContext, register

log = logging.getLogger(__name__)

SOLAPE_MINIMO = 0.6        # 60 % del clip más corto en común = mismo momento
CACHE_SEGUNDOS = 600
_cache: dict[tuple[str, int], tuple[float, list[dict[str, Any]]]] = {}

VIVOS = {PostStatus.scheduled.value, PostStatus.publishing.value, PostStatus.published.value}


# --------------------------------------------------------------------------
# Comparar
# --------------------------------------------------------------------------
def mismo_trozo(a0: float, a1: float, b0: float, b1: float, umbral: float = SOLAPE_MINIMO) -> bool:
    """¿Son el mismo momento del vídeo? (se solapan en la mayor parte)."""
    comun = min(a1, b1) - max(a0, b0)
    if comun <= 0:
        return False
    corto = max(0.1, min(a1 - a0, b1 - b0))
    return comun / corto >= umbral


def normalizar(texto: str) -> str:
    from app.services.fidelidad import sin_tildes

    texto = sin_tildes(texto or "")
    texto = re.sub(r"#shorts?\b", " ", texto)
    texto = re.sub(r"[^a-z0-9ñ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def titulos_de(clip: Clip) -> list[str]:
    """El título de ahora y los que tuvo antes (con ellos se subió en su día)."""
    anteriores = list((clip.render_config or {}).get("titulos_anteriores") or [])
    return [t for t in [clip.title, *anteriores] if t and len(normalizar(t)) >= 6]


def _titulo_coincide(subido: str, clip: Clip) -> bool:
    subido = normalizar(subido)
    if not subido:
        return False
    for titulo in titulos_de(clip):
        propio = normalizar(titulo)
        if subido == propio:
            return True
        # YouTube corta a 100 caracteres: sólo entonces vale que uno empiece
        # por el otro (si no, «Parte 1» se confundiría con «Parte 12»)
        if len(subido) >= 90 and propio.startswith(subido):
            return True
    return False


def _gancho(clip: Clip) -> str:
    """El texto propio de ese momento (el título del vídeo lo comparten todos)."""
    gancho = normalizar(clip.hook or "")
    video = normalizar(clip.video.title if clip.video else "")
    return gancho if len(gancho) >= 8 and gancho != video else ""


def _contiene(texto: str, frase: str) -> bool:
    """Palabras enteras: «parte 1» no está dentro de «parte 12»."""
    return bool(frase) and f" {frase} " in f" {texto} "


def _no_es_anterior(fecha_subida: str | None, clip: Clip) -> bool:
    """Lo subido antes de que existiera el vídeo no puede ser un clip suyo.

    Con directos que se titulan igual («FNF Animania»), la «Parte 1» de hoy no
    es la del directo de la semana pasada.
    """
    subido = _fecha(fecha_subida)
    publicado = clip.video.published_at if clip.video else None
    if not subido or not publicado:
        return True
    return subido >= publicado - timedelta(days=1)


def _coincide(subido: str, clip: Clip, *, texto: str = "", fecha: str | None = None) -> bool:
    """¿Es este clip lo que ya está subido?

    El título solo no basta: dos directos con el mismo nombre dan «Parte 1»
    iguales. Si el clip tiene su gancho, tiene que estar en el texto subido.
    """
    if not _titulo_coincide(subido, clip) or not _no_es_anterior(fecha, clip):
        return False
    gancho = _gancho(clip)
    if gancho and texto:
        return _contiene(normalizar(f"{subido} {texto}"), gancho)
    return True


def _fecha(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        fecha = datetime.fromisoformat(str(texto).replace("Z", ""))
    except ValueError:
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.astimezone(timezone.utc).replace(tzinfo=None)
    return fecha


# --------------------------------------------------------------------------
# Lo que ya hay en las plataformas
# --------------------------------------------------------------------------
def _con_cache(clave: tuple[str, int], leer) -> list[dict[str, Any]]:
    guardado = _cache.get(clave)
    if guardado and time.monotonic() - guardado[0] < CACHE_SEGUNDOS:
        return guardado[1]
    lista = leer()
    _cache[clave] = (time.monotonic(), lista)
    return lista


def olvidar(account: Account) -> None:
    """Tras subir algo, la próxima consulta vuelve a preguntar a la plataforma."""
    for plataforma in ("youtube", "tiktok"):
        _cache.pop((plataforma, account.id), None)


def _puede_mirar(account: Account) -> bool:
    if settings.dry_run or not (account.credentials or {}).get("access_token"):
        return False
    if account.platform == Platform.youtube.value:
        from app.services import youtube_api

        return youtube_api.is_configured()
    from app.services import tiktok

    return tiktok.is_configured()


def ya_en_youtube(account: Account, clip: Clip) -> dict[str, Any] | None:
    from app.services import youtube_api

    def leer():
        credenciales = youtube_api.valid_credentials(account.credentials or {})
        account.credentials = credenciales
        return youtube_api.mis_subidas(credenciales, limit=50)

    for subida in _con_cache(("youtube", account.id), leer):
        if _coincide(subida.get("title", ""), clip,
                     texto=subida.get("description", ""), fecha=subida.get("published_at")):
            return subida
    return None


def ya_en_tiktok(account: Account, clip: Clip, post: Post | None = None) -> dict[str, Any] | None:
    from app.services import tiktok

    def leer():
        credenciales = tiktok.valid_credentials(account.credentials or {})
        account.credentials = credenciales
        return tiktok.fetch_recent_videos(credenciales, limit=20)

    for video in _con_cache(("tiktok", account.id), leer):
        if coincide_en_tiktok(video, clip):
            return video
    return None


def coincide_en_tiktok(video: dict[str, Any], clip: Clip) -> bool:
    """¿Este vídeo de TikTok es este clip? Por su gancho o, si no tiene, su título."""
    titulos = [t for t in (normalizar(t) for t in titulos_de(clip)) if len(t) >= 12]
    gancho = _gancho(clip)
    if not titulos and not gancho:
        return False
    creado = video.get("create_time")
    cuando = (
        datetime.fromtimestamp(int(creado), tz=timezone.utc).replace(tzinfo=None).isoformat()
        if creado else None
    )
    if not _no_es_anterior(cuando, clip):
        return False
    texto = normalizar(f"{video.get('title', '')} {video.get('video_description', '')}")
    if gancho:
        # el gancho es lo propio de ese momento: con él basta (las versiones
        # de antes subían sólo el gancho) y sin él no vale
        return _contiene(texto, gancho)
    return any(_contiene(texto, titulo) for titulo in titulos)


def ya_existe(account: Account, clip: Clip, post: Post | None = None) -> dict[str, Any] | None:
    """Lo que ya hay en la plataforma para este clip, o None. Nunca revienta."""
    if not _puede_mirar(account):
        return None
    try:
        if account.platform == Platform.youtube.value:
            encontrado = ya_en_youtube(account, clip)
            return {**encontrado, "plataforma": "youtube"} if encontrado else None
        encontrado = ya_en_tiktok(account, clip, post)
        return {**encontrado, "plataforma": "tiktok"} if encontrado else None
    except Exception as exc:  # noqa: BLE001 - sin red se sigue como siempre
        log.info("No se ha podido mirar si ya existe en %s: %s", account.platform, exc)
        return None


def enlazar(session: Session, post: Post, encontrado: dict[str, Any]) -> str:
    """El post pasa a apuntar a lo que ya existe. Devuelve qué se ha hecho."""
    from app.services import storage, youtube_api

    clip = post.clip
    if encontrado.get("plataforma") == "youtube":
        video_id = encontrado["id"]
        post.external_post_id = post.publish_id = video_id
        post.share_url = f"https://www.youtube.com/shorts/{video_id}"
        cuando = _fecha(encontrado.get("publish_at"))
        subido = _fecha(encontrado.get("published_at"))
        if encontrado.get("privacy") == "private" and cuando and cuando > utcnow():
            # ya estaba programado en YouTube: manda su hora
            post.en_plataforma = True
            post.scheduled_at = cuando
            post.subido_at = post.subido_at or subido
            post.status = PostStatus.scheduled.value
            post.error = ""
            return "ya estaba programado en YouTube"
        if encontrado.get("privacy") in {"public", "unlisted"}:
            post.status = PostStatus.published.value
            post.published_at = subido or utcnow()
            post.error = ""
            if clip:
                clip.status = ClipStatus.published.value
                session.flush()
                storage.after_publish(session, clip)
            return "ya estaba publicado en YouTube"
        # subido pero privado y sin fecha: se le pone la de la agenda
        post.en_plataforma = True
        try:
            youtube_api.cambiar_programacion(
                post.account.credentials or {}, video_id,
                youtube_api.hora_para_youtube(post.scheduled_at),
            )
            return "estaba subido en privado: se ha programado en YouTube"
        except Exception:  # noqa: BLE001
            post.status = PostStatus.cancelled.value
            post.en_plataforma = False
            post.error = "Ya estaba subido en privado en YouTube: publícalo desde YouTube Studio."
            notifications.notify(
                session,
                "Ese Short ya estaba subido (privado)",
                f"«{(clip.title if clip else '')[:60]}» ya está en tu canal como privado. "
                "No se ha vuelto a subir: publícalo o prográmalo desde YouTube Studio.",
                kind="youtube", level="warn",
                action_label="Abrir YouTube Studio",
                action_url=youtube_api.enlace_studio(video_id),
                dedupe_hours=0,
            )
            return "estaba subido en privado"

    # TikTok: si se ve, es que ya está publicado
    post.status = PostStatus.published.value
    post.share_url = str(encontrado.get("share_url") or post.share_url or "")
    post.external_post_id = str(encontrado.get("id") or post.external_post_id or "")
    creado = encontrado.get("create_time")
    post.published_at = (
        datetime.fromtimestamp(int(creado), tz=timezone.utc).replace(tzinfo=None)
        if creado else utcnow()
    )
    post.error = ""
    if clip:
        clip.status = ClipStatus.published.value
        session.flush()
        storage.after_publish(session, clip)
    return "ya estaba publicado en TikTok"


# --------------------------------------------------------------------------
# Repetidos dentro de Kevil
# --------------------------------------------------------------------------
def _rango(clip: Clip) -> int:
    """Cuánto «existe» un clip: lo publicado manda sobre lo que sólo está hecho."""
    posts = [p for p in clip.posts if p.status in VIVOS]
    if any(p.status == PostStatus.published.value for p in posts):
        return 0
    if any(p.en_plataforma for p in posts):
        return 1
    if posts:
        return 2
    orden = {
        ClipStatus.approved.value: 3, ClipStatus.rendered.value: 4,
        ClipStatus.rendering.value: 5, ClipStatus.draft.value: 6,
        ClipStatus.failed.value: 7, ClipStatus.rejected.value: 8,
    }
    return orden.get(clip.status, 6)


def cuentas_con_ese_momento(clip: Clip, excluir_clip: bool = False) -> dict[int, str]:
    """Cuentas en las que ese momento del vídeo ya está programado o publicado."""
    cuentas: dict[int, str] = {}
    video = clip.video
    otros = video.clips if video else [clip]
    for otro in otros:
        if excluir_clip and otro.id == clip.id:
            continue
        if otro.id != clip.id and not mismo_trozo(clip.start_s, clip.end_s, otro.start_s, otro.end_s):
            continue
        for post in otro.posts:
            if post.status in VIVOS:
                cuentas.setdefault(post.account_id, otro.title)
    return cuentas


def _minuto(segundos: float) -> str:
    total = int(segundos)
    horas, resto = divmod(total, 3600)
    minutos, seg = divmod(resto, 60)
    return f"{horas}:{minutos:02d}:{seg:02d}" if horas else f"{minutos}:{seg:02d}"


def limpiar_locales(session: Session) -> dict[str, int]:
    """Quita lo repetido en Kevil. Nunca toca lo que ya está en una plataforma."""
    from app.models import Video

    descartados = cancelados = 0
    for video in session.scalars(select(Video).where(Video.clips.any())).all():
        clips = sorted(video.clips, key=lambda c: (_rango(c), c.id))
        buenos: list[Clip] = []
        for clip in clips:
            original = next(
                (b for b in buenos
                 if mismo_trozo(clip.start_s, clip.end_s, b.start_s, b.end_s)), None,
            )
            if original is None:
                buenos.append(clip)
                continue
            # las cuentas donde el original ya está
            ocupadas = {p.account_id for p in original.posts if p.status in VIVOS}
            vivos = 0
            for post in clip.posts:
                if post.status not in VIVOS:
                    continue
                if (post.status == PostStatus.scheduled.value and not post.en_plataforma
                        and post.account_id in ocupadas):
                    post.status = PostStatus.cancelled.value
                    post.error = f"Repetido: el momento del {_minuto(clip.start_s)} ya estaba en esa cuenta"
                    cancelados += 1
                else:
                    vivos += 1
            if not vivos and clip.status != ClipStatus.rejected.value:
                clip.status = ClipStatus.rejected.value
                # por el minuto, que no cambia al renumerar las partes
                clip.reason = f"Repetido: el momento del {_minuto(clip.start_s)} ya es otro clip"
                descartados += 1
            elif vivos:
                buenos.append(clip)

        # el mismo clip dos veces en la misma cuenta
        for clip in video.clips:
            por_cuenta: dict[int, list[Post]] = {}
            for post in clip.posts:
                if post.status in VIVOS:
                    por_cuenta.setdefault(post.account_id, []).append(post)
            for lista in por_cuenta.values():
                lista.sort(key=lambda p: (
                    p.status != PostStatus.published.value, not p.en_plataforma, p.id,
                ))
                for sobra in lista[1:]:
                    if sobra.status == PostStatus.scheduled.value and not sobra.en_plataforma:
                        sobra.status = PostStatus.cancelled.value
                        sobra.error = "Repetido: este clip ya estaba en esa cuenta"
                        cancelados += 1
    session.flush()
    return {"descartados": descartados, "cancelados": cancelados}


def revisar(session: Session, *, remoto: bool = True) -> dict[str, int]:
    """Repaso completo: repetidos en Kevil y lo que ya existe en las plataformas."""
    resumen = limpiar_locales(session)
    if resumen["descartados"]:
        # sin los repetidos, las partes se vuelven a numerar sin huecos
        from app.services import partes

        partes.numerar_todo(session)
    resumen["enlazados"] = 0
    if remoto:
        pendientes = session.scalars(
            select(Post).where(
                Post.status == PostStatus.scheduled.value, Post.en_plataforma.is_(False)
            )
        ).all()
        for post in pendientes:
            if not post.clip or not post.account:
                continue
            encontrado = ya_existe(post.account, post.clip, post)
            if encontrado:
                que = enlazar(session, post, encontrado)
                resumen["enlazados"] += 1
                events.log(
                    session, f"«{post.clip.title[:50]}» {que}: no se sube otra vez",
                    level="info", scope="agenda", data={"post_id": post.id},
                )
    session.flush()
    return resumen


def texto_del_resumen(resumen: dict[str, int]) -> str:
    partes = []
    if resumen.get("enlazados"):
        partes.append(f"{resumen['enlazados']} ya estaban en YouTube o TikTok (no se suben otra vez)")
    if resumen.get("cancelados"):
        partes.append(f"{resumen['cancelados']} publicación(es) repetida(s) cancelada(s)")
    if resumen.get("descartados"):
        partes.append(f"{resumen['descartados']} clip(s) repetido(s) descartado(s)")
    return "; ".join(partes)


@register("revisar_repetidos")
def job_revisar_repetidos(session: Session, ctx: JobContext) -> None:
    ctx.progress(0.1, "Buscando repetidos…")
    resumen = revisar(session, remoto=bool(ctx.payload.get("remoto", True)))
    texto = texto_del_resumen(resumen)
    if texto:
        notifications.notify(
            session,
            "Repetidos resueltos",
            texto[0].upper() + texto[1:] + ".",
            kind="agenda",
            level="info",
            action_label="Ver la agenda",
            action_url="#agenda",
            dedupe_hours=0,
        )
        events.log(session, f"Repetidos: {texto}", level="success", scope="agenda")
    ctx.progress(1.0, texto or "Sin repetidos")
