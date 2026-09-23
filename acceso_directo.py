"""Deja Kevil Studio en el escritorio y en el menú Inicio, como un programa.

No hay que ejecutarlo a mano: ``run.py`` lo hace solo la primera vez. También
puedes lanzarlo aparte:

    python acceso_directo.py          # crear
    python acceso_directo.py --quitar # borrar
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
NOMBRE = "Kevil Studio"
ICONO = BASE_DIR / "app" / "web" / "img" / "kevil.ico"
ICONO_PNG = BASE_DIR / "app" / "web" / "img" / "icono-256.png"


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------
def _escritorio_windows() -> Path:
    perfil = os.environ.get("USERPROFILE", "")
    for nombre in ("Desktop", "Escritorio"):
        ruta = Path(perfil) / nombre
        if ruta.is_dir():
            return ruta
    return Path(perfil) / "Desktop"


def _crear_windows() -> list[Path]:
    """Crea los accesos directos con un VBScript: no hace falta instalar nada.

    El acceso directo apunta a ``pythonw.exe`` (sin consola) y arranca
    ``run.py``, así que al pulsarlo sale la ventana de Kevil y nada más.
    """
    lanzador = BASE_DIR / ".venv" / "Scripts" / "pythonw.exe"
    if not lanzador.exists():
        lanzador = Path(sys.executable).with_name("pythonw.exe")
    if not lanzador.exists():
        lanzador = Path(sys.executable)

    destinos = [_escritorio_windows()]
    inicio = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"
    if inicio.is_dir():
        destinos.append(inicio)

    creados: list[Path] = []
    for carpeta in destinos:
        atajo = carpeta / f"{NOMBRE}.lnk"
        script = f'''
Set ws = CreateObject("WScript.Shell")
Set s = ws.CreateShortcut("{atajo}")
s.TargetPath = "{lanzador}"
s.Arguments = """{BASE_DIR / 'run.py'}"""
s.WorkingDirectory = "{BASE_DIR}"
s.IconLocation = "{ICONO}"
s.Description = "Tu estudio de YouTube y TikTok"
s.Save
'''
        temporal = BASE_DIR / ".acceso-directo.vbs"
        try:
            temporal.write_text(script.strip(), encoding="utf-8")
            # cscript es de consola: sin esto parpadea una terminal
            from app import procesos

            procesos.run(
                ["cscript", "//nologo", str(temporal)],
                capture_output=True, timeout=30, check=False,
            )
            if atajo.exists():
                creados.append(atajo)
        except (OSError, subprocess.TimeoutExpired):
            continue
        finally:
            temporal.unlink(missing_ok=True)
    return creados


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------
def _crear_linux() -> list[Path]:
    carpeta = Path.home() / ".local/share/applications"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / "kevil-studio.desktop"
    destino.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NOMBRE}\n"
        "Comment=Tu estudio de YouTube y TikTok\n"
        f"Exec={sys.executable} {BASE_DIR / 'run.py'}\n"
        f"Path={BASE_DIR}\n"
        f"Icon={ICONO_PNG}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Video;\n",
        encoding="utf-8",
    )
    destino.chmod(0o755)
    return [destino]


# --------------------------------------------------------------------------
# macOS
# --------------------------------------------------------------------------
def _crear_mac() -> list[Path]:
    """Un .app de verdad: una carpeta con un script dentro, que es lo que es."""
    destino = Path.home() / "Applications" / f"{NOMBRE}.app"
    macos = destino / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)

    (destino / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        "  <key>CFBundleName</key><string>Kevil Studio</string>\n"
        "  <key>CFBundleExecutable</key><string>kevil</string>\n"
        "  <key>CFBundleIdentifier</key><string>studio.kevil.app</string>\n"
        "  <key>CFBundlePackageType</key><string>APPL</string>\n"
        "  <key>LSUIElement</key><false/>\n"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    arranque = macos / "kevil"
    arranque.write_text(
        f'#!/bin/bash\ncd "{BASE_DIR}"\nexec "{sys.executable}" run.py\n', encoding="utf-8"
    )
    arranque.chmod(0o755)
    return [destino]


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
def crear() -> list[Path]:
    sistema = platform.system()
    try:
        if sistema == "Windows":
            return _crear_windows()
        if sistema == "Darwin":
            return _crear_mac()
        return _crear_linux()
    except Exception:
        return []


def quitar() -> int:
    sistema = platform.system()
    borrados = 0
    candidatos: list[Path] = []
    if sistema == "Windows":
        candidatos = [_escritorio_windows() / f"{NOMBRE}.lnk"]
        inicio = Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs"
        candidatos.append(inicio / f"{NOMBRE}.lnk")
    elif sistema == "Darwin":
        candidatos = [Path.home() / "Applications" / f"{NOMBRE}.app"]
    else:
        candidatos = [Path.home() / ".local/share/applications/kevil-studio.desktop"]

    for candidato in candidatos:
        try:
            if candidato.is_dir():
                import shutil

                shutil.rmtree(candidato)
                borrados += 1
            elif candidato.exists():
                candidato.unlink()
                borrados += 1
        except OSError:
            continue
    return borrados


if __name__ == "__main__":       # pragma: no cover
    if "--quitar" in sys.argv:
        print(f"Accesos directos borrados: {quitar()}")
    else:
        creados = crear()
        if creados:
            for ruta in creados:
                print(f"Creado: {ruta}")
        else:
            print("No se ha podido crear el acceso directo en este sistema.")
