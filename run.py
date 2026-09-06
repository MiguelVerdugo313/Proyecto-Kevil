#!/usr/bin/env python3
"""Arrancador de Kevil Studio.

Se encarga de todo:
  1. Crea un entorno virtual (.venv) la primera vez.
  2. Instala las dependencias que falten.
  3. Comprueba que ffmpeg está disponible.
  4. Levanta el servidor local y abre el navegador.

Kevil se abre en su **propia ventana**, como cualquier otro programa. Si en
este equipo no se puede, cae al navegador sin que se rompa nada.

Uso:
    python run.py                # arranque normal, en su ventana
    python run.py --navegador    # abrirlo en el navegador
    python run.py --sin-ventana  # sólo el servidor, no abrir nada
    python run.py --puerto 9000  # otro puerto
    python run.py --reinstalar   # rehace el entorno virtual
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import venv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / ".venv"
REQUIREMENTS = BASE_DIR / "requirements.txt"
WINDOW_REQS = BASE_DIR / "requirements-ventana.txt"
STAMP = VENV_DIR / ".dependencias-instaladas"
WINDOW_STAMP = VENV_DIR / ".ventana-comprobada"

AZUL = "\033[38;5;81m"
VERDE = "\033[38;5;79m"
ROJO = "\033[38;5;203m"
GRIS = "\033[38;5;245m"
FIN = "\033[0m"


def color(text: str, tone: str) -> str:
    if os.name == "nt" and not os.environ.get("WT_SESSION"):
        return text
    return f"{tone}{text}{FIN}"


def banner() -> None:
    print()
    print(color("  ██   KEVIL STUDIO", AZUL))
    print(color("       De YouTube a TikTok, en tu ordenador", GRIS))
    print()


def venv_python() -> Path:
    if platform.system() == "Windows":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def in_target_venv() -> bool:
    try:
        return Path(sys.executable).resolve() == venv_python().resolve()
    except OSError:
        return False


def create_venv(force: bool = False) -> None:
    if force and VENV_DIR.exists():
        print(color("· Rehaciendo el entorno virtual…", GRIS))
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    if not venv_python().exists():
        print(color("· Creando el entorno virtual (.venv)…", GRIS))
        venv.EnvBuilder(with_pip=True, upgrade_deps=False).create(VENV_DIR)


def requirements_changed() -> bool:
    if not STAMP.exists():
        return True
    try:
        return STAMP.read_text(encoding="utf-8").strip() != REQUIREMENTS.read_text(
            encoding="utf-8"
        ).strip()
    except OSError:
        return True


def install_requirements() -> None:
    if not requirements_changed():
        return
    print(color("· Instalando dependencias (sólo la primera vez)…", GRIS))
    result = subprocess.run(
        [
            str(venv_python()), "-m", "pip", "install", "--upgrade", "--quiet",
            "pip", "-r", str(REQUIREMENTS),
        ]
    )
    if result.returncode != 0:
        print(color("  No se han podido instalar las dependencias.", ROJO))
        print(color("  Prueba a ejecutarlo a mano:", GRIS))
        print(f"    {venv_python()} -m pip install -r {REQUIREMENTS}")
        sys.exit(1)
    STAMP.write_text(REQUIREMENTS.read_text(encoding="utf-8"), encoding="utf-8")
    print(color("  Dependencias listas.", VERDE))


def install_window_support() -> None:
    """Intenta instalar la ventana de escritorio, sin dramas si no puede.

    Va aparte de las dependencias normales a propósito: que la ventana no se
    pueda instalar en un equipo concreto no puede impedir que Kevil arranque.
    """
    if WINDOW_STAMP.exists():
        return
    ya_esta = subprocess.run(
        [str(venv_python()), "-c", "import webview"], capture_output=True
    )
    if ya_esta.returncode == 0:
        WINDOW_STAMP.write_text("ok", encoding="utf-8")
        return

    print(color("· Preparando la ventana de la aplicación…", GRIS))
    resultado = subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--quiet", "-r", str(WINDOW_REQS)],
        capture_output=True,
    )
    # Se marca en cualquier caso: si no se pudo, no hay que reintentarlo cada vez.
    WINDOW_STAMP.write_text("ok" if resultado.returncode == 0 else "no", encoding="utf-8")
    if resultado.returncode != 0:
        print(color("  Sin ventana propia en este equipo: se usará el navegador.", GRIS))


def check_ffmpeg() -> bool:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    print()
    print(color("  ⚠  No se encuentra ffmpeg (hace falta para cortar y montar vídeo).", ROJO))
    system = platform.system()
    if system == "Darwin":
        print(color("     macOS:    brew install ffmpeg", GRIS))
    elif system == "Windows":
        print(color("     Windows:  winget install Gyan.FFmpeg", GRIS))
        print(color("               (o descárgalo de https://ffmpeg.org/download.html)", GRIS))
    else:
        print(color("     Linux:    sudo apt install ffmpeg", GRIS))
    print(color("     La aplicación arrancará igualmente, pero no podrá renderizar.", GRIS))
    print()
    return False


def open_browser_later(url: str, delay: float = 2.0) -> None:
    def worker() -> None:
        time.sleep(delay)
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:
            pass

    threading.Thread(target=worker, daemon=True).start()


def esperar_al_servidor(url: str, intentos: int = 100) -> bool:
    """Espera a que el servidor conteste antes de enseñar la ventana."""
    import urllib.error
    import urllib.request

    for _ in range(intentos):
        try:
            with urllib.request.urlopen(f"{url}/api/status", timeout=1):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    return False


def abrir_ventana(url: str) -> bool:
    """Abre Kevil en su propia ventana, como cualquier otro programa.

    Usa el motor web que ya trae el sistema (WebView2 en Windows, WebKit en
    macOS, GTK en Linux): no instala ningún navegador ni pesa cientos de megas.
    Si en este equipo no hay forma de abrirla, se avisa y se sigue con el
    navegador de siempre, que funciona igual.
    """
    try:
        import logging

        # pywebview escupe un traceback enorme si el equipo no tiene con qué
        # dibujar la ventana. No es un fallo que el usuario deba leer: abajo se
        # cae al navegador y se sigue.
        logging.getLogger("pywebview").setLevel(logging.CRITICAL)
        import webview
    except Exception:
        print(color("  · Sin ventana propia (falta pywebview): abro el navegador.", GRIS))
        return False

    if not esperar_al_servidor(url):
        print(color("  · El servidor ha tardado demasiado en arrancar.", ROJO))
        return False

    try:
        webview.create_window(
            "Kevil Studio",
            url,
            width=1380,
            height=920,
            min_size=(1024, 680),
            background_color="#000000",
            text_select=True,
        )
        webview.start()          # bloquea hasta que cierras la ventana
        return True
    except Exception as exc:
        print(color(f"  · No se ha podido abrir la ventana ({exc}).", GRIS))
        print(color("    Abro el navegador en su lugar.", GRIS))
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Arranca Kevil Studio")
    parser.add_argument("--puerto", type=int, default=None, help="Puerto del servidor")
    parser.add_argument("--host", default=None, help="Dirección de escucha")
    parser.add_argument("--navegador", action="store_true",
                        help="Abrir en el navegador en vez de en su propia ventana")
    parser.add_argument("--sin-ventana", action="store_true",
                        help="No abrir nada: sólo dejar el servidor en marcha")
    parser.add_argument("--sin-navegador", action="store_true",
                        help=argparse.SUPPRESS)          # nombre antiguo
    parser.add_argument("--reinstalar", action="store_true", help="Rehacer el entorno virtual")
    parser.add_argument("--recargar", action="store_true", help="Recarga automática (desarrollo)")
    args = parser.parse_args()

    banner()

    if not in_target_venv():
        create_venv(force=args.reinstalar)
        install_requirements()
        if not (args.sin_ventana or args.sin_navegador or args.navegador):
            install_window_support()
        # se relanza a sí mismo dentro del entorno virtual
        os.execv(str(venv_python()), [str(venv_python()), str(Path(__file__).resolve()), *sys.argv[1:]])

    check_ffmpeg()

    if args.puerto:
        os.environ["KEVIL_PORT"] = str(args.puerto)
    if args.host:
        os.environ["KEVIL_HOST"] = args.host

    sys.path.insert(0, str(BASE_DIR))
    from app.config import settings  # noqa: E402

    url = f"http://{settings.host}:{settings.port}"
    silencioso = args.sin_ventana or args.sin_navegador
    en_navegador = args.navegador or settings.window_mode == "navegador"

    import uvicorn  # noqa: E402

    config = uvicorn.Config(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=args.recargar,
        log_level="info",
        access_log=False,
    )
    servidor = uvicorn.Server(config)

    # Sin ventana (o con recarga automática, que necesita el hilo principal)
    # se hace lo de siempre: servidor en primer plano.
    if silencioso or args.recargar:
        if not silencioso:
            print(color(f"  Abriendo {url}", VERDE))
            open_browser_later(url)
        else:
            print(color(f"  Servidor en {url}", VERDE))
        print(color("  (Ctrl+C para parar)", GRIS))
        print()
        servidor.run()
        return

    # Ventana propia: el servidor se va a un hilo de fondo y la ventana manda.
    print(color("  Abriendo Kevil Studio…", VERDE))
    print(color("  (cierra la ventana para salir)", GRIS))
    print()

    hilo = threading.Thread(target=servidor.run, name="kevil-server", daemon=True)
    hilo.start()

    if not en_navegador and abrir_ventana(url):
        pass                                  # se ha cerrado la ventana: salimos
    else:
        open_browser_later(url, delay=0.5)
        print(color(f"  Kevil está en {url} · Ctrl+C para parar", GRIS))
        try:
            while hilo.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    servidor.should_exit = True
    hilo.join(timeout=8)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print(color("  Hasta luego.", GRIS))
