"""Dónde está cada cosa, tanto si corres el código como si usas el .exe.

Cuando Kevil va empaquetado con PyInstaller pasan dos cosas que hay que tener
en cuenta, y las dos rompen el programa si se ignoran:

* el código y la interfaz viven **dentro** del ejecutable (en una carpeta
  temporal que el sistema descomprime al arrancar y borra al salir), así que
  los archivos de la web hay que buscarlos ahí;
* y por lo mismo, **tus datos no pueden ir ahí**: se borrarían cada vez. Van
  junto al ejecutable si se puede escribir, y si no, a tu carpeta de usuario.

Con el código suelto (``python run.py``) todo sigue como siempre.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def empaquetado() -> bool:
    """¿Estamos dentro de un ejecutable de PyInstaller?"""
    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def raiz_recursos() -> Path:
    """Dónde están el código y los archivos de la interfaz."""
    if empaquetado():
        return Path(sys._MEIPASS)                       # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def carpeta_del_programa() -> Path:
    """La carpeta donde está el ejecutable (o el proyecto, si es código)."""
    if empaquetado():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _se_puede_escribir(carpeta: Path) -> bool:
    try:
        carpeta.mkdir(parents=True, exist_ok=True)
        prueba = carpeta / ".kevil-escritura"
        prueba.write_text("ok", encoding="utf-8")
        prueba.unlink()
        return True
    except OSError:
        return False


def carpeta_de_datos() -> Path:
    """Dónde guardar la base de datos, los vídeos y tus ajustes.

    Junto al programa, que es lo cómodo (se lleva todo copiando la carpeta).
    Si ahí no se puede escribir —por ejemplo si lo has dejado en
    ``C:\\Program Files``—, se usa la carpeta de datos de tu usuario.
    """
    propio = (os.environ.get("KEVIL_DATA_DIR") or "").strip()
    if propio:
        return Path(propio).expanduser()

    junto = carpeta_del_programa() / "data"
    if _se_puede_escribir(junto):
        return junto

    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "KevilStudio"


def ffmpeg_incluido(nombre: str) -> str:
    """Busca ffmpeg/ffprobe dentro del paquete o al lado del ejecutable.

    Así se puede repartir un .exe que no obliga a instalar nada aparte. Si no
    viene incluido se devuelve "" y se usa el del sistema, como siempre.
    """
    sufijo = ".exe" if sys.platform == "win32" else ""
    for carpeta in (raiz_recursos() / "bin", carpeta_del_programa() / "bin",
                    carpeta_del_programa()):
        candidato = carpeta / f"{nombre}{sufijo}"
        if candidato.is_file():
            return str(candidato)
    return ""
