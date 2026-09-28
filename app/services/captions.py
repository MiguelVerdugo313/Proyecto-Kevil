"""Generación del archivo ASS con rótulos, gancho, marca y barra de progreso.

Todo el texto sobreimpreso se genera en un único archivo .ass que ffmpeg quema
en el vídeo. Es mucho más fiable (y más bonito) que encadenar drawtext.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

# Tipografías que viajan con el programa (en el .exe también): la de los
# rótulos virales no suele estar instalada en Windows.
TIPOGRAFIAS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FUENTE_VIRAL = "Montserrat Black"

# Medidas de cada tipografía que viaja con el programa (assets/fonts/anchos.json):
# el ancho de cada carácter, la altura de las mayúsculas y el ascendente, todo
# en proporción al tamaño de letra de ASS (libass escala la fuente para que
# ascendente + descendente = tamaño). Sirve para saber si una línea cabe sin
# abrir la fuente —en los rótulos virales no se parte la línea, se encoge, y
# salirse del vídeo es lo peor que le puede pasar a un rótulo— y para poner la
# pastilla justo detrás de la palabra que suena.
_METRICAS: dict[str, dict[str, Any]] | None = None
ANCHO_MEDIO = 0.5
# Las demás fuentes (Arial, Impact…) se miden con Montserrat Black y un
# margen, que sobra en unas y falta en ninguna.
ANCHO_OTRAS = 1.2
FUENTE_EMOJI = "Kevil Emoji"   # Noto Emoji (OFL) en negrita y sólo con los que se usan


def metricas(fuente: str) -> dict[str, Any] | None:
    global _METRICAS
    if _METRICAS is None:
        try:
            _METRICAS = {
                nombre.lower(): datos
                for nombre, datos in json.loads(
                    (TIPOGRAFIAS / "anchos.json").read_text(encoding="utf-8")
                ).items()
            }
        except (OSError, ValueError):
            _METRICAS = {}
    return _METRICAS.get((fuente or "").lower())


def asegurar_tipografias(destino: str | Path) -> None:
    """Deja las tipografías del programa en la carpeta de fuentes de los datos."""
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    for origen in TIPOGRAFIAS.glob("*.ttf"):
        copia = destino / origen.name
        if not copia.exists() or copia.stat().st_size != origen.stat().st_size:
            shutil.copyfile(origen, copia)


_EMOJIS: dict[str, str] | None = None


def glifo_emoji(emoji: str) -> str:
    """El carácter con el que la fuente de emojis del programa dibuja `emoji`.

    libass sólo busca en la tabla básica de la fuente (hasta U+FFFF): con los
    emojis de verdad (🏆 es U+1F3C6) se iba a la fuente de color del sistema y
    salían pixelados. Por eso cada emoji vive también en la zona privada
    (U+E000…) de «Kevil Emoji». Vacío si la fuente no lo tiene.
    """
    global _EMOJIS
    if _EMOJIS is None:
        try:
            _EMOJIS = json.loads((TIPOGRAFIAS / "emojis.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _EMOJIS = {}
    codigo = _EMOJIS.get(emoji)
    return chr(int(codigo, 16)) if codigo else ""


def ancho_texto(texto: str, tamano: float, fuente: str = FUENTE_VIRAL) -> float:
    """Ancho aproximado en píxeles de una línea, tal cual se va a escribir."""
    datos = metricas(fuente)
    factor = 1.0
    if datos is None:
        datos, factor = metricas(FUENTE_VIRAL) or {}, ANCHO_OTRAS
        texto = texto.upper()               # a lo ancho: mejor que sobre
    anchos = datos.get("anchos") or {}
    medio = datos.get("medio", ANCHO_MEDIO)
    return sum(anchos.get(c, medio) for c in texto) * tamano * factor


def altura_mayusculas(fuente: str) -> float:
    return float((metricas(fuente) or {}).get("mayus", 0.448))


def ascendente(fuente: str) -> float:
    return float((metricas(fuente) or {}).get("asc", 0.71))


def es_gruesa(fuente: str) -> bool:
    """Si la negrita de ASS le va bien o la engordaría de mentira.

    Las de rótulo (Anton, Bangers…) sólo tienen un grosor: pedirles negrita
    hace que libass la invente y se emborronan.
    """
    datos = metricas(fuente)
    return datos is None or int(datos.get("peso", 700)) >= 700


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
# Rótulos con plantilla
#
# Es el formato que domina en TikTok y Shorts (el de los clips de Hormozi,
# MrBeast o los que sacan Opus Clip y SupoClip): pocas palabras cada vez, letra
# muy gruesa con borde, la palabra que se está diciendo resaltada (de color, un
# poco más grande o con una pastilla detrás), las palabras fuertes de otro
# color, algún emoji y un «salto» al aparecer cada grupo. Todo lo decide la
# plantilla (ver plantillas.py); «viral» sin plantilla es la de Kevil con tus
# colores.
# --------------------------------------------------------------------------
PALABRAS_POR_LINEA = 3
POP_MS = 90                 # lo que tarda cada grupo en «saltar» al entrar
FADE_MS = 110
CRECE_ACTIVA = 1.12         # la palabra que suena, un 12 % más grande
SIN_PAUSA = 0.35            # huecos más cortos no dejan la pantalla vacía
MAYUS_REFERENCIA = 0.448    # Montserrat Black: los tamaños se pensaron con ella


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


def _rectangulo(ancho: float, alto: float, radio: float) -> str:
    """Rectángulo redondeado en el dibujo de ASS (\\p1), desde la esquina."""
    w, h = round(ancho), round(alto)
    r = max(0, min(round(radio), w // 2, h // 2))
    return (
        f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} "
        f"b {w} {h} {w} {h} {w - r} {h} l {r} {h} b 0 {h} 0 {h} 0 {h - r} "
        f"l 0 {r} b 0 0 0 0 {r} 0"
    )


def plantilla_efectiva(sub: dict[str, Any]) -> dict[str, Any] | None:
    """La plantilla que manda en estos rótulos, o None para los estilos clásicos.

    Sin plantilla, el estilo «viral» es la de Kevil con tus colores y tu letra.
    """
    from app.services import plantillas

    clave = sub.get("template")
    if plantillas.existe(clave):
        tpl = plantillas.completa(clave)
        tpl["normalizar"] = True
        return tpl
    if (sub.get("style") or "viral").lower() != "viral":
        return None
    borde = int(sub.get("outline", 8) or 0)
    return {
        **plantillas.completa(plantillas.POR_DEFECTO),
        "fuente": sub.get("font") or FUENTE_VIRAL,
        "color": sub.get("primary_color", "#FFFFFF"),
        "activo": sub.get("highlight_color", "#FFD400"),
        "borde": borde,
        "sombra": max(1, round(borde * 0.6)),
        "mayus": bool(sub.get("uppercase", True)),
        "normalizar": False,
    }


def tamano_de_letra(tpl: dict[str, Any], tamano: float) -> int:
    """El tamaño de la plantilla: todas con mayúsculas igual de altas."""
    if tpl.get("normalizar"):
        tamano *= float(tpl.get("tam", 1.0)) * MAYUS_REFERENCIA / altura_mayusculas(tpl["fuente"])
    return max(8, round(tamano))


def estilos_de_plantilla(
    tpl: dict[str, Any], *, font_size: int, scale: float, margin: int
) -> list[str]:
    fuente = tpl["fuente"]
    negrita = -1 if es_gruesa(fuente) else 0
    color = hex_to_ass(tpl["color"])
    sombra = round(float(tpl.get("sombra") or 0) * scale)
    # con caja no hay borde: la caja (un rectángulo redondeado) ya despega el texto
    borde = 0 if tpl.get("caja") else round(float(tpl.get("borde") or 0) * scale)
    if tpl.get("caja"):
        sombra = 0
    estilo_sub = (
        f"Style: Sub,{fuente},{font_size},{color},{color},"
        f"{hex_to_ass(tpl.get('color_borde') or '#000000')},&H70000000,"
        f"{negrita},0,0,0,100,100,0,0,1,{borde},{sombra},5,{margin},{margin},0,1"
    )
    emoji = round(font_size * 0.95)
    return [
        estilo_sub,
        f"Style: Emoji,{FUENTE_EMOJI},{emoji},{hex_to_ass(tpl.get('activo') or tpl['color'])},"
        f"&H00FFFFFF,&H00000000,&H70000000,0,0,0,0,100,100,0,0,1,"
        f"{max(2, round(6 * scale))},{max(1, round(4 * scale))},5,{margin},{margin},0,1",
    ]


def _con_plantilla(
    dialogue, words: list[dict[str, Any]], tpl: dict[str, Any], *, width: int,
    margin: int, font_size: int, scale: float, y: float, max_chars: int,
) -> None:
    from app.services import plantillas

    fuente = tpl["fuente"]
    mayus = bool(tpl.get("mayus", True))
    crece = float(tpl.get("crece") or 1.0)
    pastilla = tpl.get("pastilla")
    caja = tpl.get("caja")
    entrada = tpl.get("entrada") or "pop"
    por_linea = max(1, int(tpl.get("palabras") or PALABRAS_POR_LINEA))
    if por_linea > PALABRAS_POR_LINEA:
        max_chars = max(max_chars, 28)      # frases largas: que quepan

    limpias = []
    for word in words:
        texto = _limpiar(word.get("text", ""), mayus)
        if texto:
            limpias.append({**word, "text": word.get("text", ""), "clean": texto})
    groups = group_words(limpias, max_chars=max_chars, max_words=por_linea, por_frases=True)

    borde = 0 if caja else round(float(tpl.get("borde") or 0) * scale)
    sombra = 0 if caja else round(float(tpl.get("sombra") or 0) * scale)
    relleno_caja = max(4, round(font_size * 0.3)) if caja else 0
    pad_x = round(font_size * 0.16) if pastilla else 0
    disponible = width - 2 * margin
    cx = width / 2
    color_normal = override_color(tpl["color"])
    color_activo = override_color(tpl["activo"]) if tpl.get("activo") else ""
    color_enfasis = override_color(tpl["enfasis"]) if tpl.get("enfasis") else ""
    brillo = tpl.get("brillo")
    espacio = ancho_texto(" ", font_size, fuente)
    ultimo_emoji = -99.0

    for number, group in enumerate(groups):
        limpios = [w["clean"] for w in group]
        texts = [escape_text(t) for t in limpios]
        anchos = [ancho_texto(t, font_size, fuente) for t in limpios]
        linea = sum(anchos) + espacio * (len(anchos) - 1)
        extra = max(anchos) * (crece - 1) + 2 * (borde + pad_x + relleno_caja)
        k = min(1.0, disponible / max(1.0, linea + extra))

        start = group[0]["start"]
        siguiente = groups[number + 1][0]["start"] if number + 1 < len(groups) else None
        end = max(group[-1]["end"] + 0.2, start + 0.4)
        if siguiente is not None and (siguiente - end < SIN_PAUSA or end > siguiente):
            end = siguiente                       # sin parpadeos entre grupos

        # emoji encima del grupo, con mesura
        if tpl.get("emojis") and start - ultimo_emoji >= plantillas.EMOJI_CADA:
            emoji = glifo_emoji(plantillas.emoji_de([w.get("text", "") for w in group]))
            if emoji:
                ultimo_emoji = start
                alto = font_size * k
                dialogue(
                    start, end, "Emoji",
                    f"{{\\an2\\pos({cx:.0f},{y - alto * 0.62:.0f})"
                    f"\\fscx60\\fscy60\\t(0,120,\\fscx112\\fscy112)\\t(120,200,\\fscx100\\fscy100)"
                    f"\\frz-8\\t(0,200,\\frz0)}}{emoji}",
                    layer=3,
                )

        for index, word in enumerate(group):
            primero = index == 0
            pop_grupo = primero and entrada == "pop" and not pastilla
            parts = []
            for position, text in enumerate(texts):
                fuerte = bool(color_enfasis) and plantillas.es_fuerte(limpios[position])
                if position == index and (color_activo or crece != 1.0):
                    color = color_activo or (color_enfasis if fuerte else color_normal)
                    # sobre la pastilla, borde fino y sin sombra: si no, se ensucia
                    fino = f"\\bord{borde // 3}\\shad0" if pastilla else ""
                    vuelve = f"\\bord{borde}\\shad{sombra}" if pastilla else ""
                    parts.append(
                        f"{{\\1c{color}{fino}{_escala(k, pop_grupo, crece)}}}{text}"
                        f"{{\\1c{color_normal}{vuelve}{_escala(k, pop_grupo)}}}"
                    )
                elif fuerte:
                    parts.append(f"{{\\1c{color_enfasis}}}{text}{{\\1c{color_normal}}}")
                else:
                    parts.append(text)
            state_start = start if primero else word["start"]
            state_end = group[index + 1]["start"] if index + 1 < len(group) else end
            state_end = max(state_end, state_start + 0.1)
            entra = f"\\fad({FADE_MS},0)" if primero and entrada == "fade" else ""
            if primero and pastilla:
                entra = "\\fad(60,0)"
            cabeza = f"\\an5\\pos({cx:.0f},{y:.0f}){_escala(k, pop_grupo)}"
            texto = " ".join(parts)

            if brillo:
                dialogue(
                    state_start, state_end, "Sub",
                    f"{{{cabeza}{entra}\\1a&HFF&\\3c{override_color(brillo)}\\3a&H50&"
                    f"\\bord{max(6, round(font_size * 0.12))}\\blur{max(6, round(font_size * 0.1))}"
                    f"\\shad0}}" + texto,
                    layer=0,
                )
            if caja:
                # la caja, redondeada, detrás de toda la línea
                ancho_linea = (sum(anchos) + espacio * (len(anchos) - 1)) * k
                tam = font_size * k
                base = y + tam * (ascendente(fuente) - 0.5)          # línea base
                arriba = base - altura_mayusculas(fuente) * tam
                abajo = base + (0 if mayus else 0.2 * tam)            # la «p», la «g»
                alto_caja = abajo - arriba + 2 * relleno_caja * k * 0.6
                centro_y = (arriba + abajo) / 2
                dialogue(
                    state_start, state_end, "Sub",
                    f"{{\\an5\\pos({cx:.0f},{centro_y:.0f})\\p1\\bord0\\shad0{entra}"
                    f"\\1c{override_color(caja)}\\1a&H26&}}"
                    f"{_rectangulo(ancho_linea + 2 * relleno_caja * k, alto_caja, alto_caja * 0.3)}{{\\p0}}",
                    layer=1,
                )
            if pastilla:
                # la pastilla va justo detrás de la palabra que suena
                ancho_linea = (sum(anchos) + espacio * (len(anchos) - 1)) * k
                x0 = cx - ancho_linea / 2 + (sum(anchos[:index]) + espacio * index) * k
                w_p = anchos[index] * k + 2 * pad_x * k
                cap = altura_mayusculas(fuente) * font_size * k
                h_p = cap * 1.55
                centro_y = y + font_size * k * (ascendente(fuente) - 0.5) - cap / 2
                centro_x = x0 + anchos[index] * k / 2
                dialogue(
                    state_start, state_end, "Sub",
                    f"{{\\an5\\pos({centro_x:.0f},{centro_y:.0f})\\p1\\bord0\\shad0"
                    f"\\1c{override_color(pastilla)}\\1a&H00&"
                    f"\\fscx85\\fscy85\\t(0,70,\\fscx106\\fscy106)\\t(70,130,\\fscx100\\fscy100)}}"
                    f"{_rectangulo(w_p, h_p, h_p * 0.28)}{{\\p0}}",
                    layer=1,
                )
            dialogue(state_start, state_end, "Sub", f"{{{cabeza}{entra}}}" + texto, layer=2)


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
    tpl = plantilla_efectiva(sub)
    # Los tamaños se piensan para un vertical de 1920 de alto; en otras
    # resoluciones se escalan para que el rótulo ocupe lo mismo en pantalla.
    scale = height / 1920 if height > 0 else 1.0
    font = tpl["fuente"] if tpl else (sub.get("font") or FUENTE_VIRAL)
    font_size = round(int(sub.get("font_size", 125) or 125) * scale)
    if tpl:
        font_size = tamano_de_letra(tpl, int(sub.get("font_size", 125) or 125) * scale)
    primary_hex = sub.get("primary_color", "#FFFFFF")
    highlight_hex = sub.get("highlight_color", "#FFD400")
    primary = hex_to_ass(primary_hex)
    highlight = hex_to_ass(highlight_hex)
    outline = round(int(sub.get("outline", 8) or 0) * scale)
    shadow = 1
    position_y = float(sub.get("position_y", 66) or 66)
    uppercase = bool(sub.get("uppercase", True))
    max_chars = int(sub.get("max_chars", 16) or 16)

    hook_size = round(int(over.get("hook_font_size", 58) or 58) * scale)
    hook_y = float(over.get("hook_position_y", 16) or 16)
    hook_seconds = float(over.get("hook_seconds", 3) or 0)

    margin = int(width * 0.07)
    if tpl:
        # Rótulos principales: los dibuja la plantilla (borde, sombra o caja)
        styles = estilos_de_plantilla(tpl, font_size=font_size, scale=scale, margin=margin)
    else:
        styles = [
            f"Style: Sub,{font},{font_size},{primary},{primary},&H00000000,&H90000000,"
            f"-1,0,0,0,100,100,0,0,1,{outline},{shadow},5,{margin},{margin},0,1",
        ]
    hook_bold = -1 if es_gruesa(font) else 0
    styles += [
        # Gancho superior (caja opaca)
        f"Style: Hook,{font},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00101014,&HB0101014,"
        f"{hook_bold},0,0,0,100,100,0,0,3,14,0,5,{margin},{margin},0,1",
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
    if subtitles_enabled and words and tpl:
        _con_plantilla(
            dialogue, words, tpl, width=width, margin=margin, font_size=font_size,
            scale=scale, y=height * position_y / 100, max_chars=max_chars,
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
