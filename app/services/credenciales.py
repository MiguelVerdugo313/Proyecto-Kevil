"""Encontrar solo el archivo de credenciales que Google te descarga.

Google no deja saltarse el alta de la aplicación, pero sí se puede quitar el
paso de abrir el archivo, seleccionarlo entero y pegarlo: ese archivo casi
siempre acaba en Descargas con un nombre reconocible, así que lo busca Kevil.

Se mira sólo en un puñado de carpetas evidentes (Descargas, Escritorio, la
carpeta del programa) y sólo archivos pequeños que se llamen como los de
Google. Ni se recorre el disco ni se abre nada que no cuadre.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable

from app import rutas

# Google lo baja como «client_secret_<id>.apps.googleusercontent.com.json»,
# pero la gente lo renombra, así que se aceptan unas cuantas variantes.
PATRONES = (
    "client_secret*.json",
    "client-secret*.json",
    "*googleusercontent*.json",
    "credentials*.json",
    "kevil*.json",
)

# El archivo real ronda el medio KB. Cualquier cosa más grande no es eso.
TAMANO_MAXIMO = 128 * 1024

CARPETAS_DE_CASA = (
    "Downloads",
    "Descargas",
    "Desktop",
    "Escritorio",
    "Documents",
    "Documentos",
)


def buscar_par(datos: Any, claves: tuple[str, ...]) -> str:
    """Busca una clave en cualquier nivel de un JSON (Google anida en «installed»)."""
    if isinstance(datos, dict):
        for clave in claves:
            valor = datos.get(clave)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()
        for valor in datos.values():
            encontrado = buscar_par(valor, claves)
            if encontrado:
                return encontrado
    elif isinstance(datos, list):
        for elemento in datos:
            encontrado = buscar_par(elemento, claves)
            if encontrado:
                return encontrado
    return ""


def carpetas_donde_mirar() -> list[Path]:
    """Las carpetas donde puede haber caído el archivo, sin repetir."""
    vistas: set[str] = set()
    salida: list[Path] = []

    def anadir(carpeta: Path | str | None) -> None:
        if not carpeta:
            return
        ruta = Path(carpeta).expanduser()
        clave = str(ruta).lower()
        if clave in vistas:
            return
        vistas.add(clave)
        salida.append(ruta)

    # Vale con dejar el archivo al lado del programa: es lo más fácil de explicar.
    anadir(rutas.carpeta_del_programa())
    anadir(rutas.carpeta_de_datos())

    for base in (Path.home(), os.environ.get("USERPROFILE")):
        if not base:
            continue
        for nombre in CARPETAS_DE_CASA:
            anadir(Path(base).expanduser() / nombre)

    # Por si alguien tiene las carpetas en otro sitio o en otro idioma.
    anadir(os.environ.get("KEVIL_CREDENCIALES_DIR"))
    return salida


def candidatos(carpetas: Iterable[Path] | None = None) -> list[Path]:
    """Archivos que podrían ser el de Google, del más reciente al más viejo."""
    encontrados: dict[str, tuple[float, Path]] = {}
    for carpeta in carpetas if carpetas is not None else carpetas_donde_mirar():
        try:
            if not carpeta.is_dir():
                continue
        except OSError:
            continue
        for patron in PATRONES:
            try:
                archivos = list(carpeta.glob(patron))
            except OSError:
                continue
            for archivo in archivos:
                try:
                    datos = archivo.stat()
                except OSError:
                    continue
                if not archivo.is_file() or datos.st_size > TAMANO_MAXIMO:
                    continue
                encontrados[str(archivo).lower()] = (datos.st_mtime, archivo)
    return [ruta for _, ruta in sorted(encontrados.values(), key=lambda p: -p[0])]


def leer(ruta: Path) -> tuple[str, str]:
    """Saca (identificador, secreto) del archivo, o dos cadenas vacías."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return "", ""
    client_id = buscar_par(datos, ("client_id",))
    client_secret = buscar_par(datos, ("client_secret",))
    if not client_id.endswith(".apps.googleusercontent.com") or not client_secret:
        return "", ""
    return client_id, client_secret


def buscar_de_google(
    carpetas: Iterable[Path] | None = None,
) -> tuple[Path, str, str] | None:
    """El archivo de Google más reciente que sirva de verdad, si lo hay."""
    for ruta in candidatos(carpetas):
        client_id, client_secret = leer(ruta)
        if client_id:
            return ruta, client_id, client_secret
    return None
