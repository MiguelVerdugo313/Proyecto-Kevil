"""Generación del archivo ASS con rótulos, gancho, marca y barra de progreso.

Todo el texto sobreimpreso se genera en un único archivo .ass que ffmpeg quema
en el vídeo. Es mucho más fiable (y más bonito) que encadenar drawtext.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def hex_to_ass(color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (el formato de ASS invierte los canales)."""
    color = (color or "#FFFFFF").strip().lstrip("#")
    if len(color) == 3:
        color = "".join(char * 2 for char in color)
    if len(color) != 6:
        color = "FFFFFF"
    red, green, blue = color[0:2], color[2:4], color[4:6]
    return f"&H{alpha:02X}{blue}{green}{red}".upper()


def override_color(color: str) -> str:
    """Color para usarlo dentro de una etiqueta: {\\1c&HBBGGRR&}.

    Ojo: en las etiquetas de anulación el color va SIN el byte de alfa y con
    la almohadilla de cierre; el alfa se pone aparte con \\1a.
    """
    return "&H" + hex_to_ass(color)[4:] + "&"


def override_alpha(alpha: int) -> str:
    """Alfa para una etiqueta: 00 = opaco, FF = transparente."""
    return f"&H{max(0, min(255, int(alpha))):02X}&"


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rest = seconds % 60
    return f"{hours}:{minutes:02d}:{rest:05.2f}"


def escape_text(text: str) -> str:
    return (
        (text or "")
        .replace("\\", "\\\\")
        .replace("{", "(")
        .replace("}", ")")
        .replace("\n", "\\N")
    )


# --------------------------------------------------------------------------
# Agrupación de palabras en líneas
# --------------------------------------------------------------------------
def group_words(
    words: list[dict[str, Any]], max_chars: int = 22, max_words: int = 7
) -> list[list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    length = 0

    for word in words:
        text = (word.get("text") or "").strip()
        if not text:
            continue
        gap = word["start"] - current[-1]["end"] if current else 0
        too_long = length + len(text) + 1 > max_chars
        too_many = len(current) >= max_words
        big_pause = gap > 0.6
        if current and (too_long or too_many or big_pause):
            groups.append(current)
            current, length = [], 0
        current.append(word)
        length += len(text) + 1

    if current:
        groups.append(current)
    return groups


def _wrap(text: str, max_chars: int) -> str:
    """Parte una línea larga con saltos de ASS (\\N).

    Ojo: se aplica SIEMPRE después de `escape_text`, para que el escapado no
    convierta el salto en una barra invertida literal.
    """
    if len(text) <= max_chars:
        return text
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > max_chars:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return "\\N".join(lines[:3])


# --------------------------------------------------------------------------
# Construcción del archivo
# --------------------------------------------------------------------------
def build_ass(
    *,
    path: str | Path,
    width: int,
    height: int,
    duration: float,
    words: list[dict[str, Any]] | None = None,
    subtitles_config: dict[str, Any] | None = None,
    subtitles_enabled: bool = True,
    overlays_config: dict[str, Any] | None = None,
    overlays_enabled: bool = True,
    hook_text: str = "",
) -> Path:
    words = words or []
    sub = subtitles_config or {}
    over = overlays_config or {}

    font = sub.get("font") or "DejaVu Sans"
    font_size = int(sub.get("font_size", 64) or 64)
    primary = hex_to_ass(sub.get("primary_color", "#FFFFFF"))
    highlight = hex_to_ass(sub.get("highlight_color", "#28E7C5"))
    outline = int(sub.get("outline", 4) or 0)
    position_y = float(sub.get("position_y", 72) or 72)
    uppercase = bool(sub.get("uppercase", True))
    max_chars = int(sub.get("max_chars", 22) or 22)
    style_name = (sub.get("style") or "karaoke").lower()

    hook_size = int(over.get("hook_font_size", 58) or 58)
    hook_y = float(over.get("hook_position_y", 16) or 16)
    hook_seconds = float(over.get("hook_seconds", 3) or 0)

    margin = int(width * 0.07)
    styles = [
        # Rótulos principales
        f"Style: Sub,{font},{font_size},{primary},{primary},&H00000000,&H90000000,"
        f"-1,0,0,0,100,100,0,0,1,{outline},1,5,{margin},{margin},0,1",
        # Gancho superior (caja opaca)
        f"Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00101014,&HB0101014,"
        f"-1,0,0,0,100,100,0,0,3,14,0,5,{margin},{margin},0,1",
        # Marca de agua
        f"Style: Mark,{font},{int(width * 0.032)},&H30FFFFFF,&H30FFFFFF,&H50000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,0,5,{margin},{margin},0,1",
        # Barra de progreso (dibujo)
        "Style: Bar,Arial,20,&H0028E7C5,&H0028E7C5,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
    ]

    events: list[str] = []

    def dialogue(start: float, end: float, style: str, text: str, layer: int = 0) -> None:
        if end <= start:
            return
        events.append(
            f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}"
        )

    # --- Rótulos --------------------------------------------------------
    if subtitles_enabled and words:
        y = height * position_y / 100
        groups = group_words(words, max_chars=max_chars)
        for group in groups:
            group_start = group[0]["start"]
            group_end = max(group[-1]["end"], group_start + 0.35)

            if style_name == "word":
                for word in group:
                    text = word["text"].upper() if uppercase else word["text"]
                    dialogue(
                        word["start"],
                        max(word["end"], word["start"] + 0.25),
                        "Sub",
                        f"{{\\pos({width / 2:.0f},{y:.0f})\\fad(60,60)}}{escape_text(text)}",
                    )
                continue

            full = " ".join(w["text"] for w in group)
            full = full.upper() if uppercase else full

            if style_name == "blocks":
                dialogue(
                    group_start,
                    group_end,
                    "Sub",
                    f"{{\\pos({width / 2:.0f},{y:.0f})\\fad(80,80)}}"
                    f"{_wrap(escape_text(full), max_chars)}",
                )
                continue

            # karaoke: la palabra activa cambia de color
            for index, word in enumerate(group):
                parts = []
                for position, other in enumerate(group):
                    text = other["text"].upper() if uppercase else other["text"]
                    text = escape_text(text)
                    if position == index:
                        parts.append(f"{{\\c{highlight}\\fscx108\\fscy108}}{text}{{\\r}}")
                    else:
                        parts.append(text)
                line = " ".join(parts)
                start = word["start"] if index else group_start
                end = (
                    group[index + 1]["start"] if index + 1 < len(group) else group_end
                )
                dialogue(
                    start,
                    max(end, start + 0.12),
                    "Sub",
                    f"{{\\pos({width / 2:.0f},{y:.0f})}}{line}",
                )

    # --- Gancho, marca y barra -----------------------------------------
    if overlays_enabled:
        if over.get("hook_enabled", True) and hook_text and hook_seconds > 0:
            text = _wrap(escape_text(hook_text.strip()), 26)
            dialogue(
                0.15,
                min(duration, hook_seconds),
                "Hook",
                f"{{\\pos({width / 2:.0f},{height * hook_y / 100:.0f})\\fad(180,220)}}{text}",
                layer=2,
            )

        watermark = (over.get("watermark") or "").strip()
        if watermark:
            mark_y = height * (0.94 if over.get("watermark_position", "bottom") == "bottom" else 0.06)
            dialogue(
                0,
                duration,
                "Mark",
                f"{{\\pos({width / 2:.0f},{mark_y:.0f})}}{escape_text(watermark)}",
                layer=2,
            )

        if over.get("progress_bar"):
            bar_height = max(6, int(height * 0.005))
            step = 0.4
            elapsed = 0.0
            while elapsed < duration:
                ratio = min(1.0, (elapsed + step) / duration)
                filled = max(2, int(width * ratio))
                drawing = f"m 0 0 l {filled} 0 l {filled} {bar_height} l 0 {bar_height}"
                dialogue(
                    elapsed,
                    min(duration, elapsed + step),
                    "Bar",
                    f"{{\\pos(0,{height - bar_height})\\p1\\bord0\\shad0}}{drawing}{{\\p0}}",
                    layer=3,
                )
                elapsed += step

    content = ASS_HEADER.format(width=width, height=height, styles="\n".join(styles))
    content += "\n".join(events) + "\n"

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
