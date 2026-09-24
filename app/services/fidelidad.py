"""Que el kit hable del vídeo de verdad, no de lo que se imagine la IA.

El caso que lo motiva: un gameplay de Friday Night Funkin' sin voz, con el
título «Animania», acabó con títulos de «aprende a editar vídeo». La IA no
tenía nada del vídeo (sin transcripción útil, sin tema del canal) y rellenó
con lo primero que se le ocurrió. Aquí se decide:

* qué sirve de verdad para describir el vídeo (lo que tú cuentas, el título si
  no es el nombre de un archivo, la transcripción sólo si hay voz de verdad);
* si hay que **preguntarte** de qué va antes de escribir nada;
* y si lo que ha escrito la IA se ha salido del tema (para repetirlo o
  descartarlo).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from app.services.metadata import STOPWORDS

# Frases que Whisper se inventa cuando sólo hay música o ruido
ALUCINACIONES = (
    "amara.org", "subtítulos realizados", "subtitulos realizados", "subtítulos por",
    "gracias por ver", "suscríbete", "suscribete", "¡suscríbete", "música", "musica",
    "[música]", "(música)", "thanks for watching", "thank you for watching", "please subscribe",
    "sous-titres", "untertitel",
)

# Palabras que convierten un gameplay en un «tutorial» inventado
TEMAS_DE_RELLENO = (
    "tutorial", "aprende", "aprender", "guía", "guia", "curso", "edición", "edicion",
    "editar", "edita", "trucos", "consejos", "paso a paso", "principiantes", "profesional",
)

# Lo que se dice al hablar y no describe nada
MULETILLAS = {
    "basicamente", "literal", "literalmente", "bueno", "pues", "entonces", "digamos",
    "osea", "tipo", "cosa", "cosas", "algo", "este", "esta", "esto", "eso", "hoy", "video",
    "jugue", "jugando", "juego", "hice", "hago", "subi", "grabe", "tengo", "quiero",
    "comentarios", "solo", "jugar", "vez", "rato", "nada",
}

GENERICO = re.compile(
    r"^(?:vid|video|vídeo|img|mov|dsc|obs|replay|grabaci[oó]n|captura|recording|clip|"
    r"untitled|sin t[ií]tulo|nuevo|final|export|render)?[\s_\-.]*"
    r"[\d\s_\-.:()]*(?:final|editado|edit|v\d+)?[\s_\-.\d]*$",
    re.IGNORECASE,
)


def sin_tildes(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in normal if not unicodedata.combining(c)).lower()


def titulo_generico(titulo: str) -> bool:
    """«2026-09-24 20-30-11», «VID_0001», «grabación final»: no dicen nada."""
    limpio = (titulo or "").strip()
    return not limpio or bool(GENERICO.fullmatch(limpio)) or len(re.findall(r"[a-zA-Z]", limpio)) < 3


def _frases(transcript: dict[str, Any]) -> list[str]:
    segmentos = transcript.get("segments") or []
    if segmentos:
        return [str(s.get("text", "")).strip() for s in segmentos if s.get("text")]
    palabras = " ".join(str(w.get("text", "")) for w in transcript.get("words") or [])
    return [palabras] if palabras.strip() else []


def limpiar_transcripcion(transcript: dict[str, Any]) -> dict[str, Any]:
    """Quita las frases que Whisper se inventa sobre la música."""
    segmentos = [
        s for s in (transcript.get("segments") or [])
        if s.get("text") and not any(a in str(s["text"]).lower() for a in ALUCINACIONES)
    ]
    return {**transcript, "segments": segmentos}


def transcripcion_util(transcript: dict[str, Any], duracion: float) -> tuple[bool, str]:
    """¿Hay voz de verdad en el vídeo? Devuelve (sirve, por qué no)."""
    frases = _frases(limpiar_transcripcion(transcript or {}))
    texto = " ".join(frases)
    palabras = re.findall(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]{2,}", texto)
    if not palabras:
        return False, "el vídeo no tiene voz que transcribir (o no se ha transcrito)"
    minutos = max(1.0, (duracion or 60) / 60)
    if len(palabras) < max(30, 6 * minutos):
        return False, "casi no hay voz: la transcripción no dice de qué va"
    # Whisper repitiendo la misma frase una y otra vez sobre la música
    if frases and len(set(f.lower() for f in frases)) / len(frases) < 0.35:
        return False, "la transcripción se repite: parece música, no voz"
    return True, ""


def terminos(texto: str, limite: int = 8) -> list[str]:
    """Lo que tiene que salir sí o sí: nombres propios y palabras con peso.

    «Gameplay de Friday Night Funkin', el mod Animania» →
    ["Friday Night Funkin'", "Animania", "gameplay", "mod"].
    """
    texto = texto or ""
    nombres: list[str] = []
    for grupo in re.findall(
        r"(?:[A-ZÁÉÍÓÚÑ0-9][\w'’:\-]*(?:\s+(?:of|the|&)?\s*[A-ZÁÉÍÓÚÑ0-9][\w'’:\-]*)*)",
        texto,
    ):
        grupo = grupo.strip(" -:")
        if (len(grupo) >= 3 and sin_tildes(grupo) not in STOPWORDS | MULETILLAS
                and grupo not in nombres):
            nombres.append(grupo)
    # las palabras sueltas que no son relleno
    palabras = [
        p for p in re.findall(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ0-9']{3,}", texto.lower())
        if p not in STOPWORDS and sin_tildes(p) not in STOPWORDS | MULETILLAS
    ]
    sueltas = [p for p, _ in Counter(palabras).most_common(limite)]
    vistos = {sin_tildes(n) for n in nombres}
    resultado = nombres + [p for p in sueltas if not any(p in v for v in vistos)]
    return resultado[:limite]


GENERICAS = {
    "gameplay", "directo", "video", "vídeo", "hoy", "sin", "con", "live", "stream", "parte",
    "actualizacion", "mod", "update", "nivel", "capitulo", "episodio",
}


def nombres_propios(texto: str) -> list[str]:
    """Los nombres (juego, mod, personaje) de lo que cuentas, sin «Gameplay».

    Si lo escribiste todo en minúsculas («jugué fnf animania») no hay
    mayúsculas que los delaten: se toman las palabras con peso que no son
    genéricas («FNF», «Animania»).
    """
    todos = terminos(texto, limite=10)
    nombres = [t for t in todos if t[:1].isupper() and sin_tildes(t) not in GENERICAS]
    if nombres:
        return nombres
    return [
        t.upper() if len(t) <= 4 else t.capitalize()
        for t in todos
        if sin_tildes(t) not in GENERICAS and sin_tildes(t) not in MULETILLAS
    ][:3]


def fuentes(
    *, titulo: str, contexto: str, transcript: dict[str, Any], duracion: float
) -> dict[str, Any]:
    """Lo que de verdad se sabe del vídeo, y si hay que preguntarte."""
    util, motivo = transcripcion_util(transcript, duracion)
    generico = titulo_generico(titulo)
    contexto = (contexto or "").strip()
    return {
        "contexto": contexto,
        "titulo": "" if generico else (titulo or "").strip(),
        "transcripcion_util": util,
        "motivo_transcripcion": motivo,
        "transcript": limpiar_transcripcion(transcript or {}) if util else {},
        # sin lo que tú cuentas y sin voz, la IA sólo tendría el título:
        # eso es justo lo que la hace inventar
        "falta_contexto": not contexto and not util,
        "terminos": terminos(f"{contexto} {'' if generico else titulo}"),
    }


def se_sale_del_tema(kit: dict[str, Any], datos: dict[str, Any]) -> str:
    """Si el kit habla de otra cosa, dice por qué; si está bien, cadena vacía."""
    base = sin_tildes(f"{datos.get('contexto', '')} {datos.get('titulo', '')}")
    if (datos.get("transcript") or {}).get("segments"):
        base += " " + sin_tildes(" ".join(
            str(s.get("text", "")) for s in datos["transcript"]["segments"][:200]
        ))
    escrito = sin_tildes(" ".join(
        list(kit.get("titles") or []) + [kit.get("description", "")] + list(kit.get("tags") or [])
    ))

    inventados = [t for t in TEMAS_DE_RELLENO if sin_tildes(t) in escrito and sin_tildes(t) not in base]
    if inventados:
        return f"habla de «{inventados[0]}», que no aparece en lo que sabemos del vídeo"

    claves = [sin_tildes(t) for t in datos.get("terminos") or [] if len(t) >= 4][:4]
    titulos = [sin_tildes(t) for t in kit.get("titles") or []]
    if claves and titulos:
        con_clave = [t for t in titulos if any(c in t for c in claves)]
        if len(con_clave) * 2 < len(titulos):
            return "los títulos no nombran lo que dijiste del vídeo"
    return ""
