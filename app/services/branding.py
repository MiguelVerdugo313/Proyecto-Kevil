"""Los colores de tu canal.

Se saca la paleta del avatar (o del banner) de tu canal de YouTube: se
descarga la imagen, se reduce a unos pocos píxeles con ffmpeg y se agrupan los
colores para quedarse con el más característico.

Después se ajusta para que se lea bien sobre negro y sobre blanco: un color de
marca puede ser precioso en un logo y un desastre como texto.
"""

from __future__ import annotations

import colorsys
import subprocess
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

TIMEOUT = httpx.Timeout(20.0)


# --------------------------------------------------------------------------
# Color
# --------------------------------------------------------------------------
def to_hex(rgb: tuple[float, float, float]) -> str:
    return "#{:02X}{:02X}{:02X}".format(
        *(max(0, min(255, int(round(c)))) for c in rgb)
    )


def from_hex(value: str) -> tuple[int, int, int]:
    value = (value or "").strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return (52, 211, 153)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """Luminancia según la fórmula de contraste de la WCAG."""
    canales = []
    for c in rgb:
        c = c / 255
        canales.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2]


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    claro, oscuro = max(la, lb), min(la, lb)
    return (claro + 0.05) / (oscuro + 0.05)


def adjust_for_dark(hex_color: str, minimo: float = 4.5) -> str:
    """Aclara el color hasta que se lea sobre negro."""
    r, g, b = from_hex(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    s = max(s, 0.45)
    for _ in range(40):
        rgb = tuple(c * 255 for c in colorsys.hls_to_rgb(h, l, s))
        if contrast(tuple(int(c) for c in rgb), (0, 0, 0)) >= minimo:  # type: ignore[arg-type]
            return to_hex(rgb)
        l = min(0.94, l + 0.02)
    return to_hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, 0.75, s)))


def adjust_for_light(hex_color: str, minimo: float = 4.5) -> str:
    """Oscurece el color hasta que se lea sobre blanco."""
    r, g, b = from_hex(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    s = max(s, 0.45)
    for _ in range(60):
        rgb = tuple(c * 255 for c in colorsys.hls_to_rgb(h, l, s))
        if contrast(tuple(int(c) for c in rgb), (255, 255, 255)) >= minimo:  # type: ignore[arg-type]
            return to_hex(rgb)
        if l <= 0.08:
            break
        l = max(0.08, l - 0.02)
    return to_hex(tuple(c * 255 for c in colorsys.hls_to_rgb(h, 0.26, s)))


def ink_for(hex_color: str) -> str:
    """Color de texto legible encima del acento (negro o blanco).

    A igualdad de contraste se prefiere el blanco: sobre un rojo o un azul de
    marca, el texto oscuro queda raro aunque técnicamente contraste un pelo más.
    """
    rgb = from_hex(hex_color)
    sobre_negro = contrast(rgb, (0, 0, 0))
    sobre_blanco = contrast(rgb, (255, 255, 255))
    return "#08130F" if sobre_negro > sobre_blanco * 1.6 else "#FFFFFF"


# --------------------------------------------------------------------------
# Extracción de la paleta
# --------------------------------------------------------------------------
def palette_from_image(path: str | Path, *, colores: int = 6) -> list[dict[str, Any]]:
    """Colores predominantes de una imagen, del más vivo al menos."""
    comando = [
        settings.ffmpeg_path,
        "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(path),
        "-vf", "scale=48:48:force_original_aspect_ratio=increase,crop=48:48",
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    try:
        salida = subprocess.run(comando, capture_output=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):  # pragma: no cover
        return []
    datos = salida.stdout or b""
    if len(datos) < 48 * 48 * 3:
        return []

    # Se agrupan los píxeles en cubos de color y se cuenta cuántos caen en cada uno
    cubos: dict[tuple[int, int, int], list[int]] = {}
    for i in range(0, 48 * 48 * 3, 3):
        r, g, b = datos[i], datos[i + 1], datos[i + 2]
        clave = (r // 32, g // 32, b // 32)
        acumulado = cubos.setdefault(clave, [0, 0, 0, 0])
        acumulado[0] += r
        acumulado[1] += g
        acumulado[2] += b
        acumulado[3] += 1

    total = 48 * 48
    paleta: list[dict[str, Any]] = []
    for (r_sum, g_sum, b_sum, cuenta) in cubos.values():
        medio = (r_sum / cuenta, g_sum / cuenta, b_sum / cuenta)
        h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in medio))
        paleta.append(
            {
                "hex": to_hex(medio),
                "share": round(cuenta / total, 4),
                "saturation": round(s, 3),
                "lightness": round(l, 3),
                # se premia el color vivo y con presencia, no el gris de fondo
                "score": round(s * 0.65 + min(1.0, cuenta / total * 3) * 0.35, 4),
            }
        )

    # Fuera los casi negros y los casi blancos: no sirven como acento
    utiles = [c for c in paleta if 0.08 < c["lightness"] < 0.94 and c["saturation"] > 0.12]
    utiles.sort(key=lambda c: c["score"], reverse=True)
    return (utiles or sorted(paleta, key=lambda c: c["share"], reverse=True))[:colores]


def download(url: str, destino: Path) -> Path | None:
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
            respuesta = client.get(url)
        if respuesta.status_code >= 400 or not respuesta.content:
            return None
    except Exception:
        return None
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(respuesta.content)
    return destino


def extract_from_url(image_url: str) -> dict[str, Any]:
    """Paleta lista para usar a partir de la imagen de un canal."""
    if not image_url:
        raise ValueError("No hay ninguna imagen de la que sacar los colores.")

    archivo = download(image_url, settings.work_path / "marca-origen.img")
    if archivo is None:
        raise ValueError("No se ha podido descargar la imagen del canal.")

    paleta = palette_from_image(archivo)
    if not paleta:
        raise ValueError("No se han podido leer los colores de la imagen.")

    principal = paleta[0]["hex"]
    secundario = paleta[1]["hex"] if len(paleta) > 1 else principal
    return build_theme(principal, secundario, paleta)


def build_theme(
    principal: str, secundario: str = "", paleta: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Ajusta un color de marca para que funcione en los dos modos."""
    secundario = secundario or principal
    return {
        "source_accent": principal,
        "accent_dark": adjust_for_dark(principal),
        "accent_light": adjust_for_light(principal),
        "accent2_dark": adjust_for_dark(secundario, minimo=3.5),
        "accent2_light": adjust_for_light(secundario, minimo=3.5),
        "ink_dark": ink_for(adjust_for_dark(principal)),
        "ink_light": ink_for(adjust_for_light(principal)),
        "palette": paleta or [],
    }


def current_theme() -> dict[str, Any]:
    """El tema que debe aplicar la interfaz ahora mismo."""
    if not settings.brand_accent:
        return {"custom": False}
    tema = build_theme(settings.brand_accent, settings.brand_accent_2 or "")
    tema["custom"] = True
    tema["source"] = settings.brand_source
    return tema
