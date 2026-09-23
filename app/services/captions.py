"""Generación del archivo ASS con rótulos, gancho, marca y barra de progreso.

Todo el texto sobreimpreso se genera en un único archivo .ass que ffmpeg quema
en el vídeo. Es mucho más fiable (y más bonito) que encadenar drawtext.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

# Tipografías que viajan con el programa (en el .exe también): la de los
# rótulos virales no suele estar instalada en Windows.
TIPOGRAFIAS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FUENTE_VIRAL = "Montserrat Black"

# Ancho de cada carácter de Montserrat Black, en proporción al tamaño de letra
# de ASS (libass escala la fuente para que ascendente + descendente = tamaño).
# Sirve para saber si una línea cabe sin tener que abrir la fuente: en el
# estilo viral no se parte la línea, se encoge, y salirse del vídeo es lo peor
# que le puede pasar a un rótulo.
ANCHOS = {
    "A": 0.516, "B": 0.495, "C": 0.472, "D": 0.529, "E": 0.431, "F": 0.412,
    "G": 0.492, "H": 0.515, "I": 0.224, "J": 0.367, "K": 0.49, "L": 0.395,
    "M": 0.611, "N": 0.515, "O": 0.543, "P": 0.476, "Q": 0.543, "R": 0.477,
    "S": 0.421, "T": 0.419, "U": 0.502, "V": 0.503, "W": 0.772, "X": 0.488,
    "Y": 0.455, "Z": 0.44, "Á": 0.516, "É": 0.431, "Í": 0.224, "Ó": 0.543,
    "Ú": 0.502, "Ñ": 0.515, "Ü": 0.502, "0": 0.443, "1": 0.268, "2": 0.389,
    "3": 0.393, "4": 0.456, "5": 0.396, "6": 0.423, "7": 0.413, "8": 0.434,
    "9": 0.423, " ": 0.192, ".": 0.195, ",": 0.195, "!": 0.201, "¡": 0.201,
    "?": 0.388, "¿": 0.388, "'": 0.163, "-": 0.25, "%": 0.587, "$": 0.421,
    "#": 0.474, "@": 0.664, "&": 0.497,
}
ANCHO_MEDIO = 0.5
# Las demás fuentes (Arial, DejaVu, Impact…) se miden con la misma tabla y un
# margen, que sobra en unas y falta en ninguna.
ANCHO_OTRAS = 1.2


def asegurar_tipografias(destino: str | Path) -> None:
    """Deja las tipografías del programa en la carpeta de fuentes de los datos."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    for origen in TIPOGRAFIAS.glob("*.ttf"):
        copia = destino / origen.name
        if not copia.exists() or copia.stat().st_size != origen.stat().st_size:
            shutil.copyfile(origen, copia)


def ancho_texto(texto: str, tamano: float, fuente: str = FUENTE_VIRAL) -> float:
    """Ancho aproximado en píxeles de una línea en mayúsculas."""
    factor = 1.0 if fuente.lower() == FUENTE_VIRAL.lower() else ANCHO_OTRAS
    return sum(ANCHOS.get(c, ANCHO_MEDIO) for c in texto.upper()) * tamano * factor

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
FIN_DE_FRASE = tuple(".,;:!?…")


def group_words(
    words: list[dict[str, Any]], max_chars: int = 22, max_words: int = 7,
    *, por_frases: bool = False,
) -> list[list[dict[str, Any]]]:
    """Reparte las palabras en líneas.

    Con `por_frases` una línea nunca cruza un punto o una coma: «VAMOS. ESTO»
    en la misma pantalla se lee peor que dos golpes seguidos.
    """
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
        sentence = por_frases and bool(current) and (
            (current[-1].get("text") or "").strip().endswith(FIN_DE_FRASE)
        )
        if current and (too_long or too_many or big_pause or sentence):
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
# Estilo viral
#
# Es el formato que domina en TikTok y Shorts (el de los clips de Hormozi,
# MrBeast o los que saca Opus Clip): dos o tres palabras cada vez, letra muy
# gruesa en mayúsculas con borde negro grueso y sombra, la palabra que se está
# diciendo en amarillo y un poco más grande, y un «salto» al aparecer cada
# grupo. Va en el tercio de abajo pero por encima de los textos de la app.
# --------------------------------------------------------------------------
PALABRAS_POR_LINEA = 3
POP_MS = 90                 # lo que tarda cada grupo en «saltar» al entrar
CRECE_ACTIVA = 1.12         # la palabra que suena, un 12 % más grande
SIN_PAUSA = 0.35            # huecos más cortos no dejan la pantalla vacía


def _limpiar(texto: str, uppercase: bool) -> str:
    """Sin puntos ni comas colgando: en pantalla sólo estorban."""
    texto = (texto or "").strip().rstrip(".,;:…").lstrip("-—")
    return texto.upper() if uppercase else texto


def _escala(k: float, pop: bool, final: float = 1.0) -> str:
    """Etiquetas de tamaño: fijo, o con el salto de entrada.

    El salto arranca pequeño, se pasa un poco y vuelve a su sitio; `final` es
    el tamaño en el que acaba (la palabra activa acaba algo más grande).
    """
    base = round(100 * k * final)
    if not pop:
        if final == 1.0:
            return f"\\fscx{base}\\fscy{base}"
        # sin salto de grupo: sólo la palabra activa crece al llegar
        return f"\\fscx{round(100 * k)}\\fscy{round(100 * k)}\\t(0,{POP_MS},\\fscx{base}\\fscy{base})"
    small, big = round(base * 0.8), round(base * 1.06)
    return (
        f"\\fscx{small}\\fscy{small}"
        f"\\t(0,{POP_MS},\\fscx{big}\\fscy{big})"
        f"\\t({POP_MS},{POP_MS + 60},\\fscx{base}\\fscy{base})"
    )


def _viral(
    dialogue, words: list[dict[str, Any]], *, width: int, margin: int,
    font: str, font_size: int, outline: int, primary: str, highlight: str,
    y: float, uppercase: bool, max_chars: int,
) -> None:
    limpias = []
    for word in words:
        texto = _limpiar(word.get("text", ""), uppercase)
        if texto:
            limpias.append({**word, "text": word.get("text", ""), "clean": texto})
    groups = group_words(
        limpias, max_chars=max_chars, max_words=PALABRAS_POR_LINEA, por_frases=True
    )
    disponible = width - 2 * margin
    color_normal = override_color(primary)
    color_activo = override_color(highlight)

    for number, group in enumerate(groups):
        texts = [escape_text(w["clean"]) for w in group]
        # lo que ocupa la línea con la palabra más larga ya agrandada
        linea = " ".join(w["clean"] for w in group)
        mayor = max(ancho_texto(w["clean"], font_size, font) for w in group)
        necesario = ancho_texto(linea, font_size, font) + mayor * (CRECE_ACTIVA - 1) + 2 * outline
        k = min(1.0, disponible / max(1.0, necesario))

        start = group[0]["start"]
        siguiente = groups[number + 1][0]["start"] if number + 1 < len(groups) else None
        end = max(group[-1]["end"] + 0.2, start + 0.4)
        if siguiente is not None and (siguiente - end < SIN_PAUSA or end > siguiente):
            end = siguiente                       # sin parpadeos entre grupos

        for index, word in enumerate(group):
            pop = index == 0
            parts = []
            for position, text in enumerate(texts):
                if position == index:
                    parts.append(
                        f"{{\\1c{color_activo}{_escala(k, pop, CRECE_ACTIVA)}}}{text}"
                        f"{{\\1c{color_normal}{_escala(k, pop)}}}"
                    )
                else:
                    parts.append(text)
            state_start = start if index == 0 else word["start"]
            state_end = group[index + 1]["start"] if index + 1 < len(group) else end
            dialogue(
                state_start,
                max(state_end, state_start + 0.1),
                "Sub",
                f"{{\\an5\\pos({width / 2:.0f},{y:.0f}){_escala(k, pop)}}}" + " ".join(parts),
            )


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

    style_name = (sub.get("style") or "viral").lower()
    viral = style_name == "viral"
    # Los tamaños se piensan para un vertical de 1920 de alto; en otras
    # resoluciones se escalan para que el rótulo ocupe lo mismo en pantalla.
    scale = height / 1920 if height > 0 else 1.0
    font = sub.get("font") or FUENTE_VIRAL
    font_size = round(int(sub.get("font_size", 125) or 125) * scale)
    primary_hex = sub.get("primary_color", "#FFFFFF")
    highlight_hex = sub.get("highlight_color", "#FFD400")
    primary = hex_to_ass(primary_hex)
    highlight = hex_to_ass(highlight_hex)
    outline = round(int(sub.get("outline", 8) or 0) * scale)
    shadow = max(1, round(outline * 0.6)) if viral else 1
    position_y = float(sub.get("position_y", 66) or 66)
    uppercase = bool(sub.get("uppercase", True))
    max_chars = int(sub.get("max_chars", 16) or 16)

    hook_size = round(int(over.get("hook_font_size", 58) or 58) * scale)
    hook_y = float(over.get("hook_position_y", 16) or 16)
    hook_seconds = float(over.get("hook_seconds", 3) or 0)

    margin = int(width * 0.07)
    styles = [
        # Rótulos principales (en el viral, sombra negra para despegarlos del fondo)
        f"Style: Sub,{font},{font_size},{primary},{primary},&H00000000,"
        f"{'&H70000000' if viral else '&H90000000'},"
        f"-1,0,0,0,100,100,0,0,1,{outline},{shadow},5,{margin},{margin},0,1",
        # Gancho superior (caja opaca)
        f"Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00101014,&HB0101014,"
        f"-1,0,0,0,100,100,0,0,3,14,0,5,{margin},{margin},0,1",
        # Marca de agua
        f"Style: Mark,{font},{int(width * 0.032)},&H30FFFFFF,&H30FFFFFF,&H50000000,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,2,0,5,{margin},{margin},0,1",
        # Barra de progreso (dibujo)
        "Style: Bar,Arial,20,&H00B7D5E8,&H00B7D5E8,&H00000000,&H00000000,"
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
    if subtitles_enabled and words and viral:
        _viral(
            dialogue, words, width=width, margin=margin,
            font=font, font_size=font_size, outline=outline,
            primary=primary_hex, highlight=highlight_hex,
            y=height * position_y / 100, uppercase=uppercase, max_chars=max_chars,
        )
    elif subtitles_enabled and words:
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
