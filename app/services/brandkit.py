"""Tu carpeta de marca: metes tus cosas y Kevil las reconoce.

En ``data/branding`` puedes dejar lo que quieras —tu logo, fondos, capturas del
juego, una foto tuya, tipografías— **sin ordenarlo ni renombrarlo**. Aquí se
mira cada archivo y se deduce qué es por lo que es, no por cómo se llame:

* un PNG con transparencia y más o menos cuadrado → **logo**
* una imagen apaisada y grande → **fondo**
* una imagen vertical → **fondo de Short**
* una foto con cara → **retrato** (se prioriza para las miniaturas)
* un ``.ttf`` o ``.otf`` → **tipografía**
* un ``.txt`` o ``.md`` → **notas de marca** (lo que le cuentas a la IA)

Si además hay subcarpetas con nombre (``logos/``, ``fondos/``, ``juegos/lol/``)
se respeta lo que digas tú: mandas por encima de lo que se deduzca.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from app.config import settings
from app.services import branding

IMAGENES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
TIPOGRAFIAS = {".ttf", ".otf"}
TEXTOS = {".txt", ".md"}

# Carpetas cuyo nombre ya dice qué hay dentro
CARPETAS = {
    "logo": "logo", "logos": "logo", "marca": "logo",
    "fondo": "fondo", "fondos": "fondo", "backgrounds": "fondo",
    "retrato": "retrato", "retratos": "retrato", "fotos": "retrato", "caras": "retrato",
    "vertical": "vertical", "verticales": "vertical", "shorts": "vertical",
    "tipografia": "tipografia", "tipografias": "tipografia", "fuentes": "tipografia",
}


# --------------------------------------------------------------------------
# Lectura de los archivos
# --------------------------------------------------------------------------
def _sonda(path: Path) -> dict[str, Any]:
    """Ancho, alto y si tiene canal alfa. Se pregunta a ffprobe."""
    comando = [
        settings.ffprobe_path, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,pix_fmt",
        "-of", "json", str(path),
    ]
    try:
        salida = subprocess.run(comando, capture_output=True, timeout=30)
        datos = json.loads(salida.stdout or b"{}")
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return {}
    flujos = datos.get("streams") or []
    if not flujos:
        return {}
    flujo = flujos[0]
    pix = str(flujo.get("pix_fmt") or "")
    return {
        "width": int(flujo.get("width") or 0),
        "height": int(flujo.get("height") or 0),
        # los formatos con transparencia llevan «a» en el nombre (rgba, yuva…)
        "alpha": "a" in pix.replace("yuv", "").replace("gbr", ""),
    }


def _clasificar(path: Path, sonda: dict[str, Any]) -> str:
    """Qué es este archivo, a ojo."""
    # Lo que digas tú con el nombre de la carpeta manda
    for parte in path.parts:
        etiqueta = CARPETAS.get(parte.strip().lower())
        if etiqueta:
            return etiqueta

    sufijo = path.suffix.lower()
    if sufijo in TIPOGRAFIAS:
        return "tipografia"
    if sufijo in TEXTOS:
        return "notas"
    if sufijo not in IMAGENES:
        return "otro"

    ancho = int(sonda.get("width") or 0)
    alto = int(sonda.get("height") or 0)
    if not ancho or not alto:
        return "fondo"

    proporcion = ancho / alto
    if sonda.get("alpha") and 0.6 <= proporcion <= 1.7 and max(ancho, alto) <= 1200:
        return "logo"                      # un PNG recortado y más o menos cuadrado
    if proporcion < 0.85:
        return "vertical"                  # más alto que ancho: sirve de fondo de Short
    if proporcion > 1.4:
        return "fondo"                     # apaisado: fondo de miniatura
    return "retrato"                       # cuadrado o casi: suele ser una foto


def scan() -> dict[str, Any]:
    """Lee la carpeta de marca entera y devuelve qué hay de cada cosa."""
    raiz = settings.branding_path
    raiz.mkdir(parents=True, exist_ok=True)

    piezas: dict[str, list[dict[str, Any]]] = {
        "logo": [], "fondo": [], "vertical": [], "retrato": [],
        "tipografia": [], "notas": [], "otro": [],
    }
    notas: list[str] = []

    for archivo in sorted(raiz.rglob("*")):
        if not archivo.is_file() or archivo.name.startswith("."):
            continue
        relativa = archivo.relative_to(raiz)
        sufijo = archivo.suffix.lower()
        sonda = _sonda(archivo) if sufijo in IMAGENES else {}
        clase = _clasificar(relativa, sonda)

        pieza = {
            "path": str(archivo),
            "name": archivo.name,
            "folder": str(relativa.parent) if str(relativa.parent) != "." else "",
            "kind": clase,
            "width": sonda.get("width", 0),
            "height": sonda.get("height", 0),
            "size_kb": round(archivo.stat().st_size / 1024, 1),
        }
        piezas.setdefault(clase, []).append(pieza)

        if clase == "notas":
            try:
                notas.append(archivo.read_text(encoding="utf-8", errors="ignore")[:4000])
            except OSError:
                pass

    # El color de marca sale del logo, si lo hay
    paleta: list[dict[str, Any]] = []
    if piezas["logo"]:
        paleta = branding.palette_from_image(piezas["logo"][0]["path"])
    elif piezas["fondo"]:
        paleta = branding.palette_from_image(piezas["fondo"][0]["path"])

    return {
        "path": str(raiz),
        "pieces": piezas,
        "counts": {k: len(v) for k, v in piezas.items() if v},
        "total": sum(len(v) for v in piezas.values()),
        "notes": "\n\n".join(notas).strip(),
        "palette": paleta,
        "accent": paleta[0]["hex"] if paleta else "",
    }


# --------------------------------------------------------------------------
# Elegir la pieza que toca
# --------------------------------------------------------------------------
def _coincide(pieza: dict[str, Any], pistas: list[str]) -> int:
    """Cuánto pega este archivo con lo que se va a hacer.

    Si el vídeo es de zombis y tienes una carpeta «zombis» o un archivo
    «zombis-fondo.png», gana ese.
    """
    texto = f"{pieza['folder']} {pieza['name']}".lower()
    return sum(1 for pista in pistas if pista and pista in texto)


def pick_background(tema: str = "", *, vertical: bool = False) -> str:
    """El mejor fondo de tu carpeta para lo que vas a publicar.

    Devuelve "" si no has metido nada: entonces se usan los fotogramas del
    vídeo, como siempre.
    """
    datos = scan()
    prefiere = "vertical" if vertical else "fondo"
    candidatos = list(datos["pieces"].get(prefiere) or [])
    candidatos += list(datos["pieces"].get("retrato") or [])
    if not vertical:
        candidatos += list(datos["pieces"].get("vertical") or [])
    if not candidatos:
        return ""

    pistas = [p for p in (tema or "").lower().split() if len(p) > 3]
    candidatos.sort(key=lambda pieza: _coincide(pieza, pistas), reverse=True)
    return candidatos[0]["path"]


def pick_logo() -> str:
    datos = scan()
    logos = datos["pieces"].get("logo") or []
    return logos[0]["path"] if logos else ""


def context_for_ai() -> str:
    """Lo que le contamos a la IA sobre tu marca, sacado de tu carpeta."""
    datos = scan()
    trozos: list[str] = []
    if datos["notes"]:
        trozos.append(datos["notes"])
    if datos["accent"]:
        trozos.append(f"Color principal de la marca: {datos['accent']}.")
    nombres = [
        pieza["name"]
        for clase in ("logo", "fondo", "vertical", "retrato")
        for pieza in (datos["pieces"].get(clase) or [])
    ][:12]
    if nombres:
        trozos.append("Material de marca disponible: " + ", ".join(nombres) + ".")
    return "\n".join(trozos).strip()
