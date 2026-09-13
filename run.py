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
SHORTCUT_STAMP = VENV_DIR / ".acceso-directo-creado"

AZUL = "\033[38;5;81m"
VERDE = "\033[38;5;79m"
ROJO = "\033[38;5;203m"
GRIS = "\033[38;5;245m"
FIN = "\033[0m"


def preparar_salida() -> None:
    """Que escribir en pantalla no reviente en Windows.

    Cuando la salida no va a una consola sino a un archivo o a otro programa,
    Windows usa cp1252, donde no caben ni los bloques del banner ni el signo de
    aviso. Sin esto, Kevil se cae con un UnicodeEncodeError antes de arrancar.
    """
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def escribir(texto: str = "") -> None:
    """print(), pero si la consola no sabe pintar algún carácter no se muere."""
    try:
        print(texto)
    except UnicodeEncodeError:
        codificacion = getattr(sys.stdout, "encoding", None) or "ascii"
        print(texto.encode(codificacion, errors="replace").decode(codificacion))
    except (AttributeError, ValueError):
        pass                     # sin consola (pythonw): no hay nada que decir


def color(text: str, tone: str) -> str:
    if os.name == "nt" and not os.environ.get("WT_SESSION"):
        return text
    return f"{tone}{text}{FIN}"


def banner() -> None:
    escribir()
    escribir(color("  ##   KEVIL STUDIO", AZUL))
    escribir(color("       De YouTube a TikTok, en tu ordenador", GRIS))
    escribir()


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
        escribir(color("· Rehaciendo el entorno virtual…", GRIS))
        shutil.rmtree(VENV_DIR, ignore_errors=True)
    if not venv_python().exists():
        escribir(color("· Creando el entorno virtual (.venv)…", GRIS))
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
    escribir(color("· Instalando dependencias (sólo la primera vez)…", GRIS))
    result = subprocess.run(
        [
            str(venv_python()), "-m", "pip", "install", "--upgrade", "--quiet",
            "pip", "-r", str(REQUIREMENTS),
        ]
    )
    if result.returncode != 0:
        escribir(color("  No se han podido instalar las dependencias.", ROJO))
        escribir(color("  Prueba a ejecutarlo a mano:", GRIS))
        escribir(f"    {venv_python()} -m pip install -r {REQUIREMENTS}")
        sys.exit(1)
    STAMP.write_text(REQUIREMENTS.read_text(encoding="utf-8"), encoding="utf-8")
    escribir(color("  Dependencias listas.", VERDE))


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

    escribir(color("· Preparando la ventana de la aplicación…", GRIS))
    resultado = subprocess.run(
        [str(venv_python()), "-m", "pip", "install", "--quiet", "-r", str(WINDOW_REQS)],
        capture_output=True,
    )
    # Se marca en cualquier caso: si no se pudo, no hay que reintentarlo cada vez.
    WINDOW_STAMP.write_text("ok" if resultado.returncode == 0 else "no", encoding="utf-8")
    if resultado.returncode != 0:
        escribir(color("  Sin ventana propia en este equipo: se usará el navegador.", GRIS))


def crear_acceso_directo() -> None:
    """La primera vez, deja Kevil en el escritorio y en el menú Inicio.

    Se hace una sola vez: si luego lo borras, no vuelve a aparecer solo.
    """
    if SHORTCUT_STAMP.exists():
        return
    SHORTCUT_STAMP.write_text("hecho", encoding="utf-8")
    try:
        sys.path.insert(0, str(BASE_DIR))
        import acceso_directo

        creados = acceso_directo.crear()
    except Exception:
        return
    for ruta in creados:
        escribir(color(f"· Acceso directo creado: {ruta.name}", GRIS))


def check_ffmpeg() -> bool:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    escribir()
    escribir(color("  ⚠  No se encuentra ffmpeg (hace falta para cortar y montar vídeo).", ROJO))
    system = platform.system()
    if system == "Darwin":
        escribir(color("     macOS:    brew install ffmpeg", GRIS))
    elif system == "Windows":
        escribir(color("     Windows:  winget install Gyan.FFmpeg", GRIS))
        escribir(color("               (o descárgalo de https://ffmpeg.org/download.html)", GRIS))
    else:
        escribir(color("     Linux:    sudo apt install ffmpeg", GRIS))
    escribir(color("     La aplicación arrancará igualmente, pero no podrá renderizar.", GRIS))
    escribir()
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
    parser.add_argument("--diagnostico", action="store_true",
                        help="Decir qué se puede usar para abrir la ventana y salir")
    args = parser.parse_args()
    preparar_salida()

    if args.diagnostico:
        sys.path.insert(0, str(BASE_DIR))
        import ventana as ventana_mod

        banner()
        escribir(color(f"  Sistema:  {platform.system()} · Python {sys.version.split()[0]}", GRIS))
        navegador = ventana_mod.buscar_navegador()
        escribir(color(f"  Modo app: {navegador or 'no encontrado (ni Edge ni Chrome)'}", GRIS))
        try:
            import importlib

            importlib.import_module("webview")
            nativa = "disponible"
        except Exception as exc:
            nativa = f"no disponible ({type(exc).__name__})"
        escribir(color(f"  Nativa:   {nativa}", GRIS))
        escribir(color(f"  ffmpeg:   {shutil.which('ffmpeg') or 'no encontrado'}", GRIS))
        escribir()
        return

    banner()

    if not in_target_venv():
        create_venv(force=args.reinstalar)
        install_requirements()
        if not (args.sin_ventana or args.sin_navegador or args.navegador):
            install_window_support()
            crear_acceso_directo()
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
            escribir(color(f"  Abriendo {url}", VERDE))
            open_browser_later(url)
        else:
            escribir(color(f"  Servidor en {url}", VERDE))
        escribir(color("  (Ctrl+C para parar)", GRIS))
        escribir()
        servidor.run()
        return

    # Ventana propia: el servidor se va a un hilo de fondo y la ventana manda.
    import ventana as ventana_mod  # noqa: E402

    escribir(color("  Abriendo Kevil Studio…", VERDE))
    escribir(color("  (cierra la ventana para salir)", GRIS))
    escribir()

    hilo = threading.Thread(target=servidor.run, name="kevil-server", daemon=True)
    hilo.start()

    consola_oculta = False

    def al_abrir(modo: str, detalle: str) -> None:
        nonlocal consola_oculta
        if modo == "app":
            escribir(color(f"  Ventana de aplicación ({Path(detalle).name})", GRIS))
        elif modo == "navegador":
            escribir(color(f"  Kevil está en {url} · Ctrl+C para parar", GRIS))
        if modo != "navegador":
            # un programa no enseña una consola negra
            consola_oculta = ventana_mod.ocultar_consola()

    modo = ventana_mod.abrir(
        url,
        perfil=settings.data_path / "ventana",
        preferencia="navegador" if en_navegador else "auto",
        al_abrir=al_abrir,
    )

    if modo == "sin-servidor":
        escribir(color("  El servidor no ha llegado a arrancar. Mira el error de arriba.", ROJO))
    elif modo == "navegador":
        # no hay ventana que esperar: nos quedamos hasta que pares tú
        try:
            while hilo.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass

    if consola_oculta:
        ventana_mod.mostrar_consola()
    servidor.should_exit = True
    hilo.join(timeout=8)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        escribir()
        escribir(color("  Hasta luego.", GRIS))
