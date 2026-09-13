"""Punto de entrada del ejecutable de Kevil Studio.

``run.py`` está pensado para el código suelto: crea el entorno virtual e
instala las dependencias. Dentro del ``.exe`` nada de eso hace falta —ya va
todo dentro—, así que este arranque es directo: levanta el servidor y abre la
ventana.
"""

from __future__ import annotations

import multiprocessing
import sys
import threading
import traceback
from pathlib import Path


def main() -> None:
    # Sin esto, en Windows cada hilo que arranca un proceso vuelve a lanzar el
    # ejecutable entero y salen ventanas infinitas.
    multiprocessing.freeze_support()

    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))

    from app.config import settings

    settings.ensure_dirs()

    import uvicorn

    from app.main import app as aplicacion

    configuracion = uvicorn.Config(
        aplicacion,                 # el objeto, no la ruta: dentro del .exe no
        host=settings.host,         # se puede importar por su nombre
        port=settings.port,
        log_level="warning",
        access_log=False,
    )
    servidor = uvicorn.Server(configuracion)
    hilo = threading.Thread(target=servidor.run, name="kevil-server", daemon=True)
    hilo.start()

    import ventana

    url = f"http://{settings.host}:{settings.port}"
    modo = ventana.abrir(
        url,
        perfil=settings.data_path / "ventana",
        preferencia="navegador" if settings.window_mode == "navegador" else "auto",
    )

    if modo == "navegador":
        # No hay ventana que esperar: nos quedamos mientras el servidor viva.
        try:
            while hilo.is_alive():
                hilo.join(timeout=0.5)
        except KeyboardInterrupt:
            pass

    servidor.should_exit = True
    hilo.join(timeout=8)


def _avisar_del_error(exc: BaseException) -> None:
    """Un .exe sin consola que peta no dice nada: mejor dejarlo por escrito."""
    detalle = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        from app.rutas import carpeta_de_datos

        registro = carpeta_de_datos() / "error-al-arrancar.txt"
        registro.parent.mkdir(parents=True, exist_ok=True)
        registro.write_text(detalle, encoding="utf-8")
        donde = str(registro)
    except Exception:
        donde = ""

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
