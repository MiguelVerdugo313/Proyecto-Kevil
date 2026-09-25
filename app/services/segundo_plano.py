"""Seguir publicando con la ventana cerrada (y arrancar con Windows).

TikTok no deja que ninguna aplicación externa programe publicaciones: sólo se
puede publicar «ahora». Así que para que un clip salga a las 8:25 p. m. alguien
tiene que mandarlo a esa hora, y ese alguien es Kevil. Para no tener que estar
pendiente:

* al cerrar la ventana, Kevil **se queda en segundo plano** si tiene cosas por
  publicar (sin ventana ni consola; se vuelve a abrir pulsando su icono);
* con «Arrancar con Windows», al encender el PC se pone en marcha solo, en
  segundo plano.

YouTube es distinto: allí el Short se sube antes, ya programado dentro de
YouTube, y sale solo aunque el ordenador esté apagado.
"""

from __future__ import annotations

import platform
import sys
import threading
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Platform, Post, PostStatus, utcnow

# Se activa desde «Cerrar Kevil del todo»: el arranque lo espera para salir
salir = threading.Event()
# True cuando Kevil lo ha arrancado el .exe (arranque.py), que es quien escucha
# `salir`. Si no (por ejemplo con run.py), cerrar del todo cierra el proceso.
gestionado = False


def cerrar_del_todo() -> None:
    salir.set()
    if not gestionado:
        import os

        # un momento para que la respuesta llegue a la ventana
        threading.Timer(1.0, os._exit, (0,)).start()

CLAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOMBRE = "Kevil Studio"
ARGUMENTO = "--segundo-plano"


def pendientes_en_el_pc(session: Session, dias: int = 14) -> int:
    """Publicaciones que sólo pueden salir si Kevil está encendido a su hora.

    Las de YouTube ya subidas y programadas allí no cuentan: salen solas.
    """
    return len(session.execute(
        select(Post.id)
        .join(Account, Post.account_id == Account.id)
        .where(
            Post.status == PostStatus.scheduled.value,
            Post.en_plataforma.is_(False),
            Post.scheduled_at <= utcnow() + timedelta(days=dias),
        )
    ).all())


def pendientes_de_tiktok(session: Session) -> int:
    return len(session.execute(
        select(Post.id)
        .join(Account, Post.account_id == Account.id)
        .where(
            Post.status == PostStatus.scheduled.value,
            Account.platform == Platform.tiktok.value,
        )
    ).all())


# --------------------------------------------------------------------------
# Arrancar con Windows
# --------------------------------------------------------------------------
def orden_de_arranque() -> str:
    """Lo que Windows ejecuta al encender: el .exe (o run.py) en segundo plano."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" {ARGUMENTO}'
    lanzador = Path(sys.executable).with_name("pythonw.exe")
    if not lanzador.exists():
        lanzador = Path(sys.executable)
    raiz = Path(__file__).resolve().parents[2]
    return f'"{lanzador}" "{raiz / "run.py"}" --sin-ventana'


def arranque_disponible() -> bool:
    return platform.system() == "Windows"


def arranca_con_windows() -> bool:
    if not arranque_disponible():
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CLAVE_RUN) as clave:
            valor, _tipo = winreg.QueryValueEx(clave, NOMBRE)
        return bool(valor)
    except OSError:
        return False


def arrancar_con_windows(activar: bool) -> bool:
    """Pone o quita Kevil del arranque de Windows. Devuelve si ha podido."""
    if not arranque_disponible():
        return False
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, CLAVE_RUN, 0, winreg.KEY_SET_VALUE
        ) as clave:
            if activar:
                winreg.SetValueEx(clave, NOMBRE, 0, winreg.REG_SZ, orden_de_arranque())
            else:
                try:
                    winreg.DeleteValue(clave, NOMBRE)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
