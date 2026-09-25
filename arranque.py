"""Punto de entrada del ejecutable de Kevil Studio.

``run.py`` está pensado para el código suelto: crea el entorno virtual e
instala las dependencias. Dentro del ``.exe`` nada de eso hace falta —ya va
todo dentro—, así que este arranque es directo: levanta el servidor y abre la
ventana.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
import threading
import traceback
from pathlib import Path


def preparar_salida() -> None:
    """Darle una salida de verdad al programa cuando no hay consola.

    El ejecutable se construye sin consola (es una aplicación, no un script), y
    entonces Windows deja ``sys.stdout`` y ``sys.stderr`` en ``None``. En cuanto
    algo intenta escribir —uvicorn lo hace nada más arrancar— el hilo del
    servidor se muere **en silencio**: el programa sigue abierto pero no
    responde a nada. Se les da un archivo de registro, que además sirve para
    saber qué ha pasado si algo falla.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return

    try:
        from app.config import settings

        carpeta = settings.logs_path
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = open(
            carpeta / "kevil.log", "a", encoding="utf-8", errors="replace", buffering=1
        )
    except Exception:
        destino = open(os.devnull, "w", encoding="utf-8")

    if sys.stdout is None:
        sys.stdout = destino
    if sys.stderr is None:
        sys.stderr = destino


def main() -> None:
    # Sin esto, en Windows cada hilo que arranca un proceso vuelve a lanzar el
    # ejecutable entero y salen ventanas infinitas.
    multiprocessing.freeze_support()

    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))

    from app.config import settings

    settings.ensure_dirs()
    preparar_salida()          # antes de uvicorn: es el primero que escribe

    import uvicorn

    from app.main import app as aplicacion

    # El puerto no es un detalle: es el que va escrito en la dirección de
    # retorno que registras en Google y en TikTok. Si está ocupado, más vale
    # decirlo claro que arrancar en otro y que fallen las conexiones.
    solo_fondo = "--segundo-plano" in sys.argv      # al encender Windows: sin ventana
    url = f"http://{settings.host}:{settings.port}"

    if _puerto_ocupado(settings.host, settings.port):
        if _es_kevil(url):
            # Ya está en marcha (en segundo plano): sólo hace falta la ventana
            if not solo_fondo:
                import ventana

                ventana.abrir(
                    url,
                    perfil=settings.data_path / "ventana",
                    preferencia="navegador" if settings.window_mode == "navegador" else "auto",
                )
            return
        _avisar(
            f"El puerto {settings.port} está ocupado.\n\n"
            "Seguramente ya tienes Kevil Studio abierto: mira en la barra de "
            "tareas. Si no, cierra el programa que lo esté usando y vuelve a "
            "abrir Kevil."
        )
        return

    configuracion = uvicorn.Config(
        aplicacion,                 # el objeto, no la ruta: dentro del .exe no
        host=settings.host,         # se puede importar por su nombre
        port=settings.port,
        log_level="warning",
        access_log=False,
    )
    servidor = uvicorn.Server(configuracion)

    fallo: list[BaseException] = []

    def arrancar_servidor() -> None:
        """El servidor va en un hilo; si revienta ahí, nadie se entera.

        Sin esto, un error al arrancar deja el programa abierto pero sin
        responder a nada, que es lo peor que puede pasar: ni funciona ni dice
        por qué.
        """
        try:
            servidor.run()
        except BaseException as exc:          # noqa: BLE001
            fallo.append(exc)
            _anotar_error(exc, "el servidor no ha podido arrancar")

    hilo = threading.Thread(target=arrancar_servidor, name="kevil-server", daemon=True)
    hilo.start()

    import ventana
    from app.services import segundo_plano

    segundo_plano.gestionado = True       # «Cerrar del todo» lo atiende este bucle
    if solo_fondo:
        modo = "fondo"
    else:
        modo = ventana.abrir(
            url,
            perfil=settings.data_path / "ventana",
            preferencia="navegador" if settings.window_mode == "navegador" else "auto",
        )

    if fallo:
        raise fallo[0]

    # Al cerrar la ventana: si hay cosas que sólo puede publicar Kevil a su
    # hora (TikTok no deja programar), se queda en segundo plano.
    if (modo not in {"navegador", "fondo"} and not segundo_plano.salir.is_set()
            and _seguir_en_segundo_plano()):
        modo = "fondo"
        _avisar_en_segundo_plano()

    if modo in {"navegador", "fondo"}:
        # Nos quedamos mientras el servidor viva o hasta «Cerrar Kevil del todo»
        try:
            while hilo.is_alive() and not segundo_plano.salir.is_set():
                hilo.join(timeout=0.5)
        except KeyboardInterrupt:
            pass

    servidor.should_exit = True
    hilo.join(timeout=8)


def _es_kevil(url: str) -> bool:
    """¿Lo que ocupa el puerto es Kevil en segundo plano?"""
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(f"{url}/api/status", timeout=3) as respuesta:
            return "version" in json.loads(respuesta.read().decode("utf-8"))
    except Exception:
        return False


def _seguir_en_segundo_plano() -> bool:
    try:
        from app.config import settings
        from app.db import session_scope
        from app.services import segundo_plano

        if not settings.segundo_plano:
            return False
        with session_scope() as session:
            return segundo_plano.pendientes_en_el_pc(session) > 0
    except Exception:
        return False


def _avisar_en_segundo_plano() -> None:
    try:
        from app.services import notifications

        notifications.send_desktop(
            "Kevil sigue en segundo plano",
            "Publicará lo programado a su hora. Pulsa su icono para abrirlo "
            "o ciérralo del todo desde Ajustes.",
        )
    except Exception:
        pass


def _anotar_error(exc: BaseException, que: str) -> str:
    """Deja el error por escrito y devuelve dónde lo ha dejado."""
    detalle = f"=== {que} ===\n" + "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    try:
        from app.rutas import carpeta_de_datos

        registro = carpeta_de_datos() / "error-al-arrancar.txt"
        registro.parent.mkdir(parents=True, exist_ok=True)
        with registro.open("a", encoding="utf-8") as archivo:
            archivo.write(detalle + "\n")
        donde = str(registro)
    except Exception:
        donde = ""
    try:
        print(detalle, file=sys.stderr)
    except Exception:
        pass
    return donde


def _puerto_ocupado(host: str, puerto: int) -> bool:
    """¿Hay ya algo escuchando ahí?"""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sonda:
        sonda.settimeout(0.6)
        return sonda.connect_ex((host or "127.0.0.1", int(puerto))) == 0


def _avisar(mensaje: str) -> None:
    """Un aviso a secas, sin traza: el .exe no tiene consola donde leerlo."""
    print(mensaje, file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, mensaje, "Kevil Studio", 0x30)
        except Exception:
            pass


def _avisar_del_error(exc: BaseException) -> None:
    """Un .exe sin consola que peta no dice nada: mejor dejarlo por escrito."""
    detalle = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    donde = _anotar_error(exc, "Kevil no ha podido arrancar")

    mensaje = "Kevil Studio no ha podido arrancar.\n\n" + detalle[-1200:]
    if donde:
        mensaje += f"\n\nGuardado en:\n{donde}"

    print(mensaje, file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, mensaje, "Kevil Studio", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except BaseException as exc:      # noqa: BLE001 - hay que contarlo sí o sí
        _avisar_del_error(exc)
        sys.exit(1)
