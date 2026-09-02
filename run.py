#!/usr/bin/env python3
"""Arrancador de Kevil Studio.

Se encarga de todo:
  1. Crea un entorno virtual (.venv) la primera vez.
  2. Instala las dependencias que falten.
  3. Comprueba que ffmpeg está disponible.
  4. Levanta el servidor local y abre el navegador.

Uso:
    python run.py                # arranque normal
    python run.py --puerto 9000  # otro puerto
    python run.py --sin-navegador
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
STAMP = VENV_DIR / ".dependencias-instaladas"

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Arranca Kevil Studio")
    parser.add_argument("--puerto", type=int, default=None, help="Puerto del servidor")
    parser.add_argument("--host", default=None, help="Dirección de escucha")
    parser.add_argument("--sin-navegador", action="store_true", help="No abrir el navegador")
    parser.add_argument("--reinstalar", action="store_true", help="Rehacer el entorno virtual")
    parser.add_argument("--recargar", action="store_true", help="Recarga automática (desarrollo)")
    args = parser.parse_args()

    banner()

    if not in_target_venv():
        create_venv(force=args.reinstalar)
        install_requirements()
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
    print(color(f"  Abriendo {url}", VERDE))
    print(color("  (Ctrl+C para parar)", GRIS))
    print()

    if not args.sin_navegador:
        open_browser_later(url)

    import uvicorn  # noqa: E402

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=args.recargar,
        log_level="info",
        access_log=False,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print(color("  Hasta luego.", GRIS))
