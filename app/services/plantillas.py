"""Plantillas de rótulos: el aspecto completo de los subtítulos en un clic.

Cada plantilla decide la tipografía, los colores, el borde, si la palabra que
suena lleva una pastilla detrás, si las palabras fuertes cambian de color, si
salen emojis y cómo entran en pantalla. Tú sigues decidiendo el tamaño, la
altura y cuánto texto cabe en una línea.

«Personalizado» (plantilla vacía) usa los campos del paso tal cual, como antes.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# --------------------------------------------------------------------------
# Plantillas
#
# Campos:
#   fuente        familia (viene con el programa, ver assets/fonts)
#   color         texto normal
#   activo        la palabra que suena (None = no cambia de color)
#   enfasis       palabras fuertes y números (None = sin énfasis)
#   pastilla      color de la pastilla detrás de la palabra que suena
#   caja          color de la caja detrás de toda la línea
#   borde         grosor del borde (en un vertical de 1920 de alto)
#   color_borde   color del borde
#   sombra        distancia de la sombra (0 = sin sombra)
#   brillo        color del resplandor (None = sin brillo)
#   entrada       «pop» (salta), «fade» (aparece) o «nada»
#   crece         cuánto crece la palabra que suena (1.0 = nada)
#   mayus         todo en mayúsculas
#   palabras      palabras por línea como mucho
#   emojis        pone un emoji encima cuando se dice algo que lo pide
#   tam           tamaño respecto a lo normal (1.0 = el tamaño del paso)
# --------------------------------------------------------------------------
BASE: dict[str, Any] = {
    "fuente": "Montserrat Black",
    "color": "#FFFFFF",
    "activo": "#FFD400",
    "enfasis": None,
    "pastilla": None,
    "caja": None,
    "borde": 8,
    "color_borde": "#000000",
    "sombra": 5,
    "brillo": None,
    "entrada": "pop",
    "crece": 1.12,
    "mayus": True,
    "palabras": 3,
    "emojis": False,
    "tam": 1.0,
}

PLANTILLAS: dict[str, dict[str, Any]] = {
    "kevil": {
        "nombre": "Kevil",
        "descripcion": "La de siempre: gruesa, en mayúsculas y la palabra que suena en amarillo.",
    },
    "hormozi": {
        "nombre": "Hormozi",
        "descripcion": "Pastilla verde detrás de la palabra que suena y números en amarillo.",
        "fuente": "Montserrat Black",
        "activo": "#FFFFFF",
        "pastilla": "#00BF49",
        "enfasis": "#FFD400",
        "crece": 1.0,
        "sombra": 4,
    },
    "mrbeast": {
        "nombre": "MrBeast",
        "descripcion": "Letra de cómic, amarilla con borde grueso y las palabras fuertes en rojo.",
        "fuente": "Luckiest Guy",
        "color": "#FFFFFF",
        "activo": "#FFE11A",
        "enfasis": "#FF3B3B",
        "borde": 10,
        "sombra": 7,
        "crece": 1.15,
        "emojis": True,
    },
    "tiktok": {
        "nombre": "TikTok",
        "descripcion": "La letra de TikTok con la palabra que suena en rosa.",
        "fuente": "TikTok Sans",
        "activo": "#FE2C55",
        "enfasis": "#25F4EE",
        "borde": 7,
        "sombra": 3,
        "mayus": False,
        "emojis": True,
    },
    "gamer": {
        "nombre": "Gamer",
        "descripcion": "Bangers en verde lima, emojis y las jugadas fuertes en naranja.",
        "fuente": "Bangers",
        "activo": "#B6FF3B",
        "enfasis": "#FF8A00",
        "borde": 9,
        "sombra": 6,
        "crece": 1.18,
        "emojis": True,
    },
    "neon": {
        "nombre": "Neón",
        "descripcion": "Letra alta con resplandor cian y la palabra que suena en magenta.",
        "fuente": "Bebas Neue",
        "color": "#E9FDFF",
        "activo": "#FF2BD6",
        "enfasis": "#FFE600",
        "borde": 4,
        "color_borde": "#0A1A2F",
        "sombra": 0,
        "brillo": "#18E0FF",
        "entrada": "fade",
        "tam": 1.05,
    },
    "minimal": {
        "nombre": "Minimal",
        "descripcion": "Frase limpia sobre una caja oscura, sin saltos. Para charlas y podcasts.",
        "fuente": "TikTok Sans",
        "activo": None,
        "caja": "#101014",
        "borde": 0,
        "sombra": 0,
        "entrada": "fade",
        "crece": 1.0,
        "mayus": False,
        "palabras": 5,
        "tam": 0.8,
    },
    "podcast": {
        "nombre": "Podcast",
        "descripcion": "Poppins sobre caja, la palabra que suena en dorado.",
        "fuente": "Poppins ExtraBold",
        "activo": "#FFC83D",
        "caja": "#000000",
        "borde": 0,
        "sombra": 0,
        "entrada": "fade",
        "crece": 1.0,
        "mayus": False,
        "palabras": 4,
        "tam": 0.85,
    },
    "impacto": {
        "nombre": "Impacto",
        "descripcion": "Anton enorme, una palabra cada vez. Golpe a golpe.",
        "fuente": "Anton",
        "activo": "#FFFFFF",
        "enfasis": "#FFD400",
        "borde": 9,
        "sombra": 6,
        "crece": 1.0,
        "palabras": 1,
        "tam": 1.5,
    },
    "clasico": {
        "nombre": "Clásico",
        "descripcion": "Archivo Black blanca con borde, sin colores. Nunca falla.",
        "fuente": "Archivo Black",
        "activo": None,
        "borde": 7,
        "sombra": 4,
        "crece": 1.0,
        "palabras": 4,
        "tam": 0.9,
    },
}

POR_DEFECTO = "kevil"


def lista() -> list[dict[str, Any]]:
    """Las plantillas con todos sus campos, para la interfaz y la vista previa."""
    return [{"id": clave, **completa(clave)} for clave in PLANTILLAS]


def completa(clave: str | None) -> dict[str, Any]:
    """La plantilla con los huecos rellenos con los valores base."""
    return {**BASE, **PLANTILLAS.get(clave or "", PLANTILLAS[POR_DEFECTO])}


def existe(clave: str | None) -> bool:
    return bool(clave) and clave in PLANTILLAS


# --------------------------------------------------------------------------
# Palabras fuertes y emojis
# --------------------------------------------------------------------------
def normalizar(palabra: str) -> str:
    """minúsculas, sin tildes y sin signos: «¡Increíble!» -> «increible»."""
    texto = unicodedata.normalize("NFKD", (palabra or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9ñ]", "", texto)


# Las que merecen otro color: lo que haría subrayar a un editor.
FUERTES = {
    # español
    "increible", "brutal", "brutalisimo", "locura", "loco", "locos", "epico",
    "epica", "nunca", "jamas", "siempre", "nadie", "imposible",
    "gratis", "secreto", "secretos", "dinero", "millon", "millones", "mil",
    "mejor", "peor", "primero", "primera", "ultimo", "ultima", "record",
    "gane", "ganamos", "ganar", "gano", "victoria", "perdi", "perdimos",
    "muerto", "muerte", "mori", "morimos", "jefe", "final", "cuidado", "ojo",
    "rapido", "enorme", "gigante", "top", "viral", "legendario", "legendaria",
    "hack", "truco", "trucos", "error", "fallo", "bug", "mentira", "verdad",
    "odio", "amo", "wow", "ala", "hostia", "madre", "dios", "tremendo",
    "tremenda", "insano", "insana", "roto", "rota", "facil", "dificil",
    "clave", "basta", "stop", "atencion", "urgente", "nuevo",
    "nueva", "exclusivo", "prohibido", "peligro", "boss",
    # inglés
    "insane", "crazy", "never", "always", "everything", "nothing", "free",
    "secret", "money", "best", "worst", "first", "last", "win", "won",
    "lose", "lost", "dead", "died", "clutch", "epic", "legendary", "omg",
    "wtf", "huge", "impossible", "broken", "new",
}

# palabra (normalizada) -> emoji. Pocas y claras: un emoji que no pega distrae.
EMOJIS: dict[str, str] = {
    # emociones
    "jaja": "😂", "jajaja": "😂", "jajajaja": "😂", "risa": "😂", "gracioso": "😂",
    "lol": "😂", "lmao": "😂", "xd": "😂",
    "triste": "😢", "llorar": "😭", "lloro": "😭", "llorando": "😭", "cry": "😭",
    "miedo": "😱", "susto": "😱", "terror": "😱", "scary": "😱", "grito": "😱",
    "enfadado": "😡", "rabia": "😡", "odio": "😡", "angry": "😡",
    "amor": "❤", "amo": "❤", "love": "❤", "corazon": "❤",
    "wow": "🤯", "increible": "🤯", "locura": "🤯", "insane": "🤯",
    "brutal": "🤯", "mindblowing": "🤯", "alucinante": "🤯",
    "pensar": "🤔", "pienso": "🤔", "idea": "💡", "duda": "🤔", "why": "🤔",
    "raro": "🤨", "sospechoso": "🤨", "sus": "🤨",
    "cool": "😎", "facil": "😎", "ez": "😎", "easy": "😎",
    "asco": "🤢", "cringe": "😬", "incomodo": "😬", "nervios": "😬",
    "sueno": "😴", "aburrido": "😴", "boring": "😴",
    "hola": "👋", "adios": "👋", "hello": "👋", "bye": "👋",
    "gracias": "🙏", "porfavor": "🙏", "thanks": "🙏",
    "ok": "👌", "perfecto": "👌", "perfect": "👌",
    "genial": "👍", "good": "👍", "mal": "👎", "bad": "👎",
    "aplauso": "👏", "bravo": "👏",
    "fuerte": "💪", "fuerza": "💪", "strong": "💪",
    "ojo": "👀", "mira": "👀", "mirad": "👀", "look": "👀", "atencion": "👀",
    "silencio": "🤫", "secreto": "🤫", "secret": "🤫",
    # juego
    "gane": "🏆", "ganamos": "🏆", "ganar": "🏆", "victoria": "🏆", "win": "🏆",
    "won": "🏆", "campeon": "🏆", "record": "🏆", "top": "🏆", "primero": "🥇",
    "perdi": "💀", "perdimos": "💀", "muerto": "💀", "mori": "💀", "morimos": "💀",
    "muerte": "💀", "dead": "💀", "died": "💀", "rip": "💀", "gg": "🎮",
    "fuego": "🔥", "fire": "🔥", "caliente": "🔥", "epico": "🔥", "epica": "🔥",
    "epic": "🔥", "legendario": "🔥", "clutch": "🔥",
    "boss": "👑", "jefe": "👑", "rey": "👑", "king": "👑", "reina": "👑",
    "juego": "🎮", "jugar": "🎮", "game": "🎮", "gaming": "🎮", "partida": "🎮",
    "nivel": "⭐", "level": "⭐", "estrella": "⭐", "star": "⭐",
    "bomba": "💣", "explota": "💥", "explosion": "💥", "boom": "💥", "pum": "💥",
    "golpe": "💥", "disparo": "🔫", "pistola": "🔫", "arma": "🔫",
    "espada": "⚔", "pelea": "⚔", "batalla": "⚔", "fight": "⚔",
    "rapido": "⚡", "fast": "⚡", "velocidad": "⚡", "speed": "⚡", "rayo": "⚡",
    "bug": "🐛", "error": "❌", "fallo": "❌",
    "correcto": "✅", "yes": "✅", "listo": "✅",
    "musica": "🎵", "cancion": "🎵", "ritmo": "🎵", "song": "🎵", "baile": "💃",
    "bailar": "💃", "dance": "💃", "micro": "🎤", "cantar": "🎤", "rap": "🎤",
    "flecha": "🏹", "diana": "🎯", "objetivo": "🎯", "punteria": "🎯",
    "escudo": "🛡", "vida": "❤", "cofre": "📦", "caja": "📦", "llave": "🔑",
    "mapa": "🗺", "tesoro": "💎", "diamante": "💎", "diamantes": "💎",
    "monstruo": "👾", "alien": "👽", "robot": "🤖", "fantasma": "👻", "ghost": "👻",
    "zombie": "🧟", "zombi": "🧟", "dragon": "🐉", "payaso": "🤡", "clown": "🤡",
    # cosas
    "dinero": "💰", "money": "💰", "pasta": "💰", "millones": "💰", "euros": "💶",
    "dolares": "💵", "gratis": "🆓", "free": "🆓", "regalo": "🎁", "gift": "🎁",
    "tiempo": "⏰", "hora": "⏰", "reloj": "⏰", "time": "⏰",
    "cohete": "🚀", "subir": "🚀", "sube": "🚀", "rocket": "🚀",
    "arriba": "⬆", "abajo": "⬇", "cerebro": "🧠", "smart": "🧠",
    "telefono": "📱", "movil": "📱", "phone": "📱", "video": "🎬", "canal": "📺",
    "youtube": "▶", "suscribete": "🔔", "subscribe": "🔔", "campana": "🔔",
    "comida": "🍔", "hambre": "🍔", "pizza": "🍕", "cafe": "☕", "agua": "💧",
    "casa": "🏠", "coche": "🚗", "car": "🚗", "mundo": "🌍", "world": "🌍",
    "noche": "🌙", "sol": "☀", "frio": "🥶", "calor": "🥵",
    "cien": "💯", "100": "💯", "numero1": "🥇", "fiesta": "🎉", "party": "🎉",
    "cumple": "🎂", "feliz": "😄", "happy": "😄", "sorpresa": "😮", "what": "😮",
    "cuidado": "⚠", "peligro": "⚠", "warning": "⚠", "prohibido": "🚫",
}

# Un emoji como mucho cada tantos segundos: más, y el clip parece un anuncio.
EMOJI_CADA = 2.5


def es_fuerte(palabra: str) -> bool:
    limpia = normalizar(palabra)
    if not limpia:
        return False
    if any(c.isdigit() for c in limpia):
        return True                     # los números siempre llaman la atención
    return limpia in FUERTES


def emoji_de(palabras: list[str]) -> str:
    """El emoji que pide una línea (el de la primera palabra que lo tenga)."""
    for palabra in palabras:
        emoji = EMOJIS.get(normalizar(palabra))
        if emoji:
            return emoji
    return ""


def todos_los_emojis() -> set[str]:
    return set(EMOJIS.values())
