"""Lanzar programas externos sin que Windows abra una ventana negra.

El ejecutable se construye **sin consola**, que es lo suyo para una
aplicación. El problema es que, sin consola propia, cada programa de consola
que se lanza desde ella —ffmpeg, ffprobe, powershell…— se crea la suya, y
Windows se la pone delante al usuario: parpadea una ventana de terminal y te
saca del juego o de lo que estuvieras haciendo.

Kevil llama a ffmpeg y a ffprobe muchas veces por clip, así que eso convertía
el ordenador en algo inusable mientras trabajaba. La solución es decirle a
Windows, en cada llamada, que no cree ventana.

Además se lleva la cuenta de los procesos vivos, para poder cortarlos todos
de golpe cuando se pone el motor en pausa: si no, un render de cinco minutos
seguiría comiéndose el ordenador aunque le hayas dado a pausar.

En Linux y macOS no hay ventanas que esconder: `opciones()` devuelve un
diccionario vacío y la llamada queda igual que antes.
"""

from __future__ import annotations

import subprocess
import sys
import threading
import weakref
from functools import lru_cache
from typing import Any

_vivos: "weakref.WeakSet[subprocess.Popen]" = weakref.WeakSet()
_candado = threading.Lock()


@lru_cache(maxsize=1)
def opciones() -> dict[str, Any]:
    """Lo que hay que pasarle a subprocess para que no abra ventana."""
    if sys.platform != "win32":
        return {}

    # Dos cinturones: la bandera vale para los programas de consola y la
    # estructura de arranque para los que miran cómo se les pide que salgan.
    arranque = subprocess.STARTUPINFO()                       # type: ignore[attr-defined]
    arranque.dwFlags |= subprocess.STARTF_USESHOWWINDOW       # type: ignore[attr-defined]
    arranque.wShowWindow = subprocess.SW_HIDE                 # type: ignore[attr-defined]
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,         # type: ignore[attr-defined]
        "startupinfo": arranque,
    }


def popen(*args: Any, **kwargs: Any) -> subprocess.Popen:
    """`subprocess.Popen` sin ventana, y apuntado para poder pararlo."""
    proceso = subprocess.Popen(*args, **{**opciones(), **kwargs})
    with _candado:
        _vivos.add(proceso)
    return proceso


def run(
    args: Any,
    *,
    input: Any = None,
    capture_output: bool = False,
    timeout: float | None = None,
    check: bool = False,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Lo mismo que `subprocess.run`, sin terminal y con posibilidad de pararlo."""
    if capture_output:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    if input is not None:
        kwargs["stdin"] = subprocess.PIPE

    with popen(args, **kwargs) as proceso:
        try:
            salida, errores = proceso.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            proceso.kill()
            proceso.communicate()
            raise
        except BaseException:
            proceso.kill()
            raise
        codigo = proceso.poll()

    if check and codigo:
        raise subprocess.CalledProcessError(codigo, args, output=salida, stderr=errores)
    return subprocess.CompletedProcess(args, codigo, salida, errores)


def vivos() -> int:
    """Cuántos programas externos siguen trabajando ahora mismo."""
    with _candado:
        return sum(1 for proceso in list(_vivos) if proceso.poll() is None)


def terminar_todos() -> int:
    """Corta en seco todo lo que esté en marcha. Devuelve cuántos ha parado."""
    parados = 0
    with _candado:
        pendientes = [proceso for proceso in list(_vivos) if proceso.poll() is None]
    for proceso in pendientes:
        try:
            proceso.kill()
            parados += 1
        except OSError:
            pass
    return parados
