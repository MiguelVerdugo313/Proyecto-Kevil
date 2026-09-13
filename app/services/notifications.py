"""Avisos del asistente.

Se guardan en la base de datos (los ves en la campana de la interfaz) y, si lo
tienes activado, también aparecen como notificación del escritorio. No hace
falta ninguna librería extra: se usa lo que ya trae cada sistema.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import threading
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Notification, utcnow

MAX_NOTIFICATIONS = 200


# --------------------------------------------------------------------------
# Notificación del escritorio (mejor esfuerzo: si falla, no pasa nada)
# --------------------------------------------------------------------------
def _desktop_command(title: str, body: str) -> list[str] | None:
    system = platform.system()
    if system == "Darwin":
        script = (
            f'display notification {_applescript(body)} '
            f'with title {_applescript("Kevil Studio")} '
            f'subtitle {_applescript(title)}'
        )
        return ["osascript", "-e", script]

    if system == "Linux":
        if shutil.which("notify-send"):
            return ["notify-send", "-a", "Kevil Studio", title, body]
        return None

    if system == "Windows":
        script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications,"
            " ContentType = WindowsRuntime] > $null;"
            "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(2);"
            f"$t.GetElementsByTagName('text')[0].AppendChild($t.CreateTextNode({_ps(title)})) > $null;"
            f"$t.GetElementsByTagName('text')[1].AppendChild($t.CreateTextNode({_ps(body)})) > $null;"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
            "'Kevil Studio').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
        )
        return ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script]

    return None


def _applescript(text: str) -> str:
    return '"' + (text or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ps(text: str) -> str:
    return "'" + (text or "").replace("'", "''") + "'"


def send_desktop(title: str, body: str) -> None:
    if not settings.notifications_desktop:
        return
    command = _desktop_command(title, body[:220])
    if not command:
        return

    def run() -> None:
        try:
            subprocess.run(command, capture_output=True, timeout=10)
        except Exception:
            pass  # nunca debe romper nada

    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------
# Registro
# --------------------------------------------------------------------------
def notify(
    session: Session,
    title: str,
    body: str = "",
    *,
    kind: str = "general",
    level: str = "info",
    action_label: str = "",
    action_url: str = "",
    data: dict[str, Any] | None = None,
    dedupe_hours: float = 12,
    desktop: bool = True,
) -> Notification | None:
    """Crea un aviso. Si ya hay uno igual reciente, no lo repite."""
    if dedupe_hours > 0:
        since = utcnow() - timedelta(hours=dedupe_hours)
        repeated = session.scalars(
            select(Notification)
            .where(
                Notification.kind == kind,
                Notification.title == title,
                Notification.created_at >= since,
            )
            .limit(1)
        ).first()
        if repeated:
            return None

    notification = Notification(
        kind=kind,
        level=level,
        title=title[:200],
        body=body,
        action_label=action_label[:80],
        action_url=action_url[:200],
        data=data or {},
    )
    session.add(notification)
    session.flush()

    old = session.scalars(
        select(Notification.id).order_by(Notification.id.desc()).offset(MAX_NOTIFICATIONS)
    ).all()
    if old:
        from sqlalchemy import delete

        session.execute(delete(Notification).where(Notification.id.in_(old)))

    if desktop:
        send_desktop(title, body)
    return notification


def unread_count(session: Session) -> int:
    return len(
        session.execute(
            select(Notification.id).where(Notification.read_at.is_(None))
        ).all()
    )


def mark_read(session: Session, notification_id: int | None = None) -> int:
    query = select(Notification).where(Notification.read_at.is_(None))
    if notification_id:
        query = query.where(Notification.id == notification_id)
    rows = session.scalars(query).all()
    for row in rows:
        row.read_at = utcnow()
    return len(rows)
