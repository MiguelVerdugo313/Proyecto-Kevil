"""Empaqueta Kevil Studio en un ejecutable.

    python construir.py              # un solo archivo (Kevil Studio.exe)
    python construir.py --carpeta    # una carpeta (arranca más rápido)
    python construir.py --con-ffmpeg # meter ffmpeg dentro: no instalas nada

El resultado queda en ``dist/``.

**Importante**: PyInstaller no sabe hacer un ``.exe`` de Windows desde Linux ni
desde macOS. El ejecutable hay que construirlo en el mismo sistema en el que se
va a usar. Si no quieres montar nada en tu equipo, el repositorio trae un
flujo de GitHub Actions que lo construye solo en una máquina con Windows y te
deja el ``.exe`` para descargar (ver ``.github/workflows/exe.yml``).
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
NOMBRE = "Kevil Studio"
ICONO_WIN = BASE_DIR / "app" / "web" / "img" / "kevil.ico"
ICONO_PNG = BASE_DIR / "app" / "web" / "img" / "icono-256.png"

# Módulos que PyInstaller no encuentra solo porque se cargan por su nombre en
# tiempo de ejecución, no con un «import» normal.
IMPORTS_OCULTOS = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "apscheduler.triggers.cron",
    "apscheduler.triggers.interval",
    "apscheduler.triggers.date",
    "apscheduler.executors.pool",
    "apscheduler.jobstores.memory",
    "sqlalchemy.dialects.sqlite",
    "app.main",
    "app.services.pipeline",
    "app.services.scheduler",
    "app.services.studio",
]


def separador() -> str:
    """PyInstaller usa «;» en Windows y «:» en el resto para --add-data."""
    return ";" if platform.system() == "Windows" else ":"


def comprobar_pyinstaller() -> bool:
    try:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True, check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    print("· Instalando PyInstaller…")
    resultado = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "pyinstaller>=6.3"]
    )
    return resultado.returncode == 0


def copiar_ffmpeg(destino: Path) -> list[Path]:
    """Copia el ffmpeg del sistema para meterlo dentro del paquete."""
    destino.mkdir(parents=True, exist_ok=True)
    copiados: list[Path] = []
    for nombre in ("ffmpeg", "ffprobe"):
        origen = shutil.which(nombre)
        if not origen:
            print(f"  ⚠  No se encuentra {nombre} en el PATH: no se incluirá.")
            continue
        final = destino / Path(origen).name
        shutil.copy2(origen, final)
        copiados.append(final)
        print(f"  · {nombre} incluido ({final.stat().st_size / 1024 / 1024:.0f} MB)")
    return copiados


def construir(un_archivo: bool = True, con_ffmpeg: bool = False) -> Path | None:
    if not comprobar_pyinstaller():
        print("No se ha podido instalar PyInstaller.")
        return None

    sep = separador()
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name", NOMBRE,
        # sin consola: es una aplicación, no un script
        "--windowed" if platform.system() != "Linux" else "--console",
        "--onefile" if un_archivo else "--onedir",
        # la interfaz (HTML, CSS, JS e iconos) va dentro del ejecutable
        "--add-data", f"{BASE_DIR / 'app' / 'web'}{sep}app/web",
    ]

    icono = ICONO_WIN if platform.system() == "Windows" else ICONO_PNG
    if icono.exists() and platform.system() != "Linux":
        args += ["--icon", str(icono)]

    for modulo in IMPORTS_OCULTOS:
        args += ["--hidden-import", modulo]

    # yt-dlp trae cientos de extractores que se cargan por su nombre
    args += ["--collect-submodules", "yt_dlp"]

    temporales: list[Path] = []
    if con_ffmpeg:
        carpeta = BASE_DIR / "build" / "bin"
        temporales = copiar_ffmpeg(carpeta)
        if temporales:
            args += ["--add-binary", f"{carpeta}{sep}bin"]

    args.append(str(BASE_DIR / "arranque.py"))

    print(f"· Construyendo {NOMBRE}… (esto tarda un par de minutos)")
    resultado = subprocess.run(args, cwd=str(BASE_DIR))

    for archivo in temporales:
        archivo.unlink(missing_ok=True)

    if resultado.returncode != 0:
        print("La construcción ha fallado. El error está arriba.")
        return None

    if un_archivo:
        sufijo = ".exe" if platform.system() == "Windows" else ""
        final = BASE_DIR / "dist" / f"{NOMBRE}{sufijo}"
    else:
        final = BASE_DIR / "dist" / NOMBRE

    if not final.exists():
        print(f"Se ha construido, pero no encuentro {final}.")
        return None

    if final.is_file():
        print(f"\n  Listo: {final}  ({final.stat().st_size / 1024 / 1024:.0f} MB)")
    else:
        print(f"\n  Listo: {final}")
    return final


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Empaqueta {NOMBRE}")
    parser.add_argument("--carpeta", action="store_true",
                        help="Una carpeta en vez de un solo archivo (arranca más rápido)")
    parser.add_argument("--con-ffmpeg", action="store_true",
                        help="Incluir ffmpeg dentro: el resultado no necesita instalar nada")
    args = parser.parse_args()

    final = construir(un_archivo=not args.carpeta, con_ffmpeg=args.con_ffmpeg)
    sys.exit(0 if final else 1)


if __name__ == "__main__":
    main()
