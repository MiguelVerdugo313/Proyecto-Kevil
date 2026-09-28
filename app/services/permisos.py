"""Cuando YouTube o TikTok retiran el permiso de una cuenta.

Pasa más de lo que parece: Google caduca los permisos cada 7 días si tu app
está en modo «Prueba», y TikTok los retira si cambias la contraseña o quitas
la app. Antes eso acababa en errores raros publicación tras publicación. Ahora:

* la cuenta queda como «Falta autorizar», con el motivo y un aviso;
* lo que no pudo salir queda anotado, y al volver a conectar la cuenta vuelve
  solo a la agenda.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, AccountStatus, Platform, Post, PostStatus, utcnow
from app.services import events, notifications

# Lo que llevan delante los errores de las publicaciones que no salieron por
# esto: así se encuentran al reconectar.
PREFIJO = "Hay que volver a conectar la cuenta · "
CODIGOS_TIKTOK = {"access_token_invalid", "refresh_token_invalid"}


def es_permiso_caducado(exc: BaseException) -> bool:
    from app.services import tiktok, youtube_api

    if isinstance(exc, (youtube_api.PermisoCaducado, tiktok.PermisoCaducado)):
        return True
    return isinstance(exc, tiktok.TikTokRechazo) and exc.codigo in CODIGOS_TIKTOK


def marcar_para_reconectar(session: Session, account: Account, exc: BaseException) -> None:
    """La cuenta pasa a «Falta autorizar» y se avisa (una vez cada 12 h)."""
    donde = "YouTube" if account.platform == Platform.youtube.value else "TikTok"
    account.status = AccountStatus.needs_auth.value
    account.status_detail = str(exc)[:500]
    notifications.notify(
        session,
        f"Vuelve a conectar {donde}",
        f"«{account.display_name}» ya no deja publicar: {exc} "
        "Lo que tenía que salir se publicará en cuanto la vuelvas a conectar.",
        kind="cuentas",
        level="error",
        action_label="Ir a Cuentas",
        action_url="#cuentas",
        dedupe_hours=12,
    )
    events.log(session, f"{donde}: hay que volver a conectar «{account.display_name}»",
               level="error", scope=account.platform)


def puede_usarse(account: Account | None) -> bool:
    return account is not None and account.status != AccountStatus.needs_auth.value


def rescatar(session: Session, account: Account) -> int:
    """Al volver a conectar: lo que no salió por el permiso vuelve a la agenda."""
    ahora = utcnow()
    vueltas = 0
    for post in session.scalars(
        select(Post).where(
            Post.account_id == account.id,
            Post.status == PostStatus.failed.value,
            Post.error.like(f"{PREFIJO}%"),
        )
    ).all():
        post.status = PostStatus.scheduled.value
        post.error = ""
        if post.scheduled_at < ahora:
            # lo atrasado sale en unos minutos, no de golpe todo a la vez
            post.scheduled_at = ahora + timedelta(minutes=5 + 10 * vueltas)
            post.slot_reason = "Vuelve tras reconectar la cuenta"
        if post.clip is not None and post.clip.status in {"failed", "rendered"}:
            post.clip.status = "scheduled"
        vueltas += 1
    if vueltas:
        events.log(session, f"{vueltas} publicación(es) de «{account.display_name}» vuelven "
                   "a la agenda tras reconectar", level="success", scope="agenda")
    return vueltas


# Lo que dejaban las versiones anteriores cuando Google retiraba el permiso: un
# error interno de Python en vez del motivo.
ERRORES_VIEJOS = ("has no attribute 'get'", "No se ha podido renovar el acceso")


def reintentar_los_rotos(session: Session) -> int:
    """Al arrancar: lo que falló por ese error viejo vuelve a la agenda.

    Si el permiso sigue caducado, esta vez se dirá bien y la cuenta quedará
    marcada para reconectar.
    """
    ahora = utcnow()
    vueltas = 0
    for post in session.scalars(
        select(Post).where(Post.status == PostStatus.failed.value)
    ).all():
        if not any(marca in (post.error or "") for marca in ERRORES_VIEJOS):
            continue
        post.status = PostStatus.scheduled.value
        post.error = ""
        if post.scheduled_at < ahora:
            post.scheduled_at = ahora + timedelta(minutes=5 + 10 * vueltas)
            post.slot_reason = "Reintento tras actualizar Kevil"
        if post.clip is not None and post.clip.status == "failed":
            post.clip.status = "scheduled"
        vueltas += 1
    return vueltas
