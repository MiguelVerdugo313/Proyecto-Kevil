"""Nota de viralidad de cada momento: gancho, enganche, valor y compartible.

Cada criterio vale de 0 a 25 y la suma es la nota (0-100). Con IA configurada
la pone el modelo leyendo lo que se dice en el trozo, y además explica por qué
y propone un gancho corto para arriba del clip, sacado de lo que se dice (no
inventado). Sin IA, o si falla, se calcula con reglas sobre el texto: la nota
siempre está, y siempre se ve de dónde sale.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Callable

log = logging.getLogger("kevil.viralidad")

CRITERIOS = ("gancho", "enganche", "valor", "compartible")
TIPOS_DE_GANCHO = {
    "pregunta": "Pregunta",
    "dato": "Dato o cifra",
    "reaccion": "Reacción",
    "conflicto": "Conflicto",
    "historia": "Historia",
    "humor": "Humor",
    "reto": "Reto",
    "sorpresa": "Sorpresa",
    "ninguno": "Sin gancho claro",
}
POR_LOTE = 8                   # momentos por consulta: los modelos pequeños no dan para más
TEXTO_MAXIMO = 900             # caracteres de cada momento que se le enseñan

SISTEMA = (
    "Eres editor de clips virales para TikTok y YouTube Shorts de un canal de "
    "gaming en español. Puntúas momentos de un vídeo por lo que se DICE en ellos."
)

REGLAS = """REGLAS DE VERDAD:
- Juzga sólo lo que dice la transcripción de cada momento. No supongas lo que se ve.
- «gancho_titulo» sale de lo que se dice en ese momento: puedes resumirlo o
  reformularlo, pero no añadas hechos, juegos, nombres ni cifras que no estén.
- Si un momento no tiene nada, ponle notas bajas: no pasa nada.

Criterios (0 a 25 cada uno):
- gancho: ¿los primeros segundos atrapan? (pregunta, reacción fuerte, dato, conflicto)
- enganche: ¿mantiene la atención hasta el final? (ritmo, tensión, emoción)
- valor: ¿se entiende solo y aporta algo? (risa, info, momento épico, historia completa)
- compartible: ¿alguien lo mandaría a un amigo o lo comentaría?

tipo_gancho: uno de pregunta, dato, reaccion, conflicto, historia, humor, reto, sorpresa, ninguno."""


# --------------------------------------------------------------------------
# Reglas (sin IA)
# --------------------------------------------------------------------------
def _sin_tildes(texto: str) -> str:
    normal = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in normal if not unicodedata.combining(c))


REACCIONES = re.compile(
    r"\b(no+ ?puede ser|que (?:locura|fuerte|dices)|madre mia|dios mio|increible|"
    r"brutal|wow+|o+mg|jaja+|ja ja|nooo+|siii+|vamo+s|toma+|que risa|me muero|"
    r"no me lo creo|flipa|what|insane)\b"
)
CONFLICTO = re.compile(r"\b(pero|sin embargo|problema|error|fallo|perdi|muer[eto]|odio|nunca)\b")
HISTORIA = re.compile(r"\b(una vez|resulta que|entonces|al final|cuando|primero|despues)\b")
RETO = re.compile(r"\b(reto|challenge|intentar|consegui|lograr|record|sin morir|primera vez)\b")


def _tipo(texto: str) -> str:
    t = _sin_tildes(texto[:220])
    if "?" in texto[:220] or "¿" in texto[:220]:
        return "pregunta"
    if REACCIONES.search(t):
        return "reaccion"
    if re.search(r"\b\d{1,6}\b", t):
        return "dato"
    if RETO.search(t):
        return "reto"
    if CONFLICTO.search(t):
        return "conflicto"
    if HISTORIA.search(t):
        return "historia"
    return "ninguno"


def por_reglas(candidato: dict[str, Any]) -> dict[str, Any]:
    """La nota calculada con reglas sobre el texto y los datos del corte."""
    texto = str(candidato.get("text") or "")
    t = _sin_tildes(texto)
    duracion = max(1.0, float(candidato.get("end", 0)) - float(candidato.get("start", 0)))
    palabras = len(texto.split())
    ritmo = palabras / duracion
    tipo = _tipo(texto)

    gancho = 6 + (9 if tipo != "ninguno" else 0)
    gancho += 5 if REACCIONES.search(_sin_tildes(texto[:120])) else 0
    gancho += 3 if "idea completa" in str(candidato.get("reason", "")).lower() else 0

    enganche = 5 + min(12, ritmo * 4)
    enganche += min(6, len(re.findall(r"[!¡]", texto)) * 2)

    valor = 6 + min(8, palabras / 12)
    valor += 5 if HISTORIA.search(t) else 0
    valor += 4 if re.search(r"\b\d{1,6}\b", t) else 0

    compartible = 4 + min(12, len(REACCIONES.findall(t)) * 4)
    compartible += 5 if tipo in {"reaccion", "reto", "conflicto"} else 0

    notas = {
        "gancho": gancho, "enganche": enganche, "valor": valor, "compartible": compartible,
    }
    motivo = ""
    if not palabras:
        notas = dict.fromkeys(CRITERIOS, 3)
        motivo = "Sin voz que analizar: la nota no dice mucho de este momento"
    return _cerrar(notas, tipo=tipo, motivo=motivo, gancho_titulo="", fuente="reglas")


def _cerrar(
    notas: dict[str, Any], *, tipo: str, motivo: str, gancho_titulo: str, fuente: str
) -> dict[str, Any]:
    limpias = {}
    for criterio in CRITERIOS:
        try:
            valor = float(notas.get(criterio, 0) or 0)
        except (TypeError, ValueError):
            valor = 0.0
        limpias[criterio] = int(round(max(0.0, min(25.0, valor))))
    tipo = tipo if tipo in TIPOS_DE_GANCHO else "ninguno"
    return {
        **limpias,
        "total": sum(limpias.values()),
        "tipo_gancho": tipo,
        "motivo": (motivo or "").strip()[:280],
        "gancho_titulo": (gancho_titulo or "").strip().strip("«»\"'")[:90],
        "fuente": fuente,
    }


# --------------------------------------------------------------------------
# Con IA
# --------------------------------------------------------------------------
def _prompt(lote: list[dict[str, Any]], *, titulo: str, contexto: str) -> str:
    momentos = []
    for numero, candidato in enumerate(lote):
        texto = re.sub(r"\s+", " ", str(candidato.get("text") or "")).strip()[:TEXTO_MAXIMO]
        duracion = float(candidato.get("end", 0)) - float(candidato.get("start", 0))
        momentos.append(f'[{numero}] ({duracion:.0f} s) "{texto or "(sin voz)"}"')
    cabecera = f"Vídeo: {titulo}" + (f"\nDe qué va (lo cuenta el creador): {contexto}" if contexto else "")
    return (
        f"{cabecera}\n\n{REGLAS}\n\nMomentos:\n" + "\n".join(momentos) + "\n\n"
        'Devuelve {"momentos": [{"i": 0, "gancho": 0-25, "enganche": 0-25, "valor": 0-25, '
        '"compartible": 0-25, "tipo_gancho": "...", "motivo": "una frase de por qué", '
        '"gancho_titulo": "máx. 8 palabras, para arriba del clip"}]} con un elemento por momento.'
    )


def _palabras_clave(texto: str) -> set[str]:
    return {p for p in re.findall(r"[a-z0-9ñ]{4,}", _sin_tildes(texto))}


def gancho_fiel(gancho: str, texto: str, contexto: str = "") -> bool:
    """El gancho de la IA sólo vale si sus palabras con peso salen en el trozo.

    Se permite reformular («¡No me lo puedo creer!» -> «No se lo cree»), pero
    si trae nombres o cifras que no se dicen, se descarta.
    """
    propias = _palabras_clave(gancho)
    if not propias:
        return bool(gancho.strip())
    base = _palabras_clave(f"{texto} {contexto}")
    raices = {p[:5] for p in base}
    ajenas = [p for p in propias if p not in base and p[:5] not in raices]
    cifras = set(re.findall(r"\d+", gancho)) - set(re.findall(r"\d+", f"{texto} {contexto}"))
    return not cifras and len(ajenas) <= max(1, len(propias) // 3)


def con_ia(
    candidatos: list[dict[str, Any]], *, titulo: str, contexto: str = ""
) -> list[dict[str, Any] | None]:
    """Una nota por candidato (None donde la IA no respondió bien)."""
    from app.services import ai

    notas: list[dict[str, Any] | None] = [None] * len(candidatos)
    for inicio in range(0, len(candidatos), POR_LOTE):
        lote = candidatos[inicio : inicio + POR_LOTE]
        try:
            respuesta = ai.chat_json(
                _prompt(lote, titulo=titulo, contexto=contexto),
                system=SISTEMA, temperature=0.3, max_tokens=250 * len(lote) + 200,
            )
        except Exception as exc:          # la IA es un extra: nunca rompe el proceso
            log.info("Viralidad con IA no disponible: %s", exc)
            if inicio == 0:
                return notas              # si falla la primera, no se insiste
            continue
        elementos = respuesta.get("momentos") if isinstance(respuesta, dict) else respuesta
        for elemento in elementos or []:
            if not isinstance(elemento, dict):
                continue
            try:
                numero = int(elemento.get("i", -1))
            except (TypeError, ValueError):
                continue
            if not 0 <= numero < len(lote):
                continue
            candidato = lote[numero]
            gancho = str(elemento.get("gancho_titulo") or "")
            if gancho and not gancho_fiel(gancho, str(candidato.get("text") or ""), contexto):
                gancho = ""               # se inventaba algo: mejor el de siempre
            notas[inicio + numero] = _cerrar(
                elemento,
                tipo=str(elemento.get("tipo_gancho") or "ninguno").lower().strip(),
                motivo=str(elemento.get("motivo") or ""),
                gancho_titulo=gancho,
                fuente="ia",
            )
    return notas


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------
def puntuar(
    candidatos: list[dict[str, Any]], *, usar_ia: bool, titulo: str, contexto: str = "",
    avisar: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Pone la nota a cada candidato (y, con IA, su motivo y su gancho).

    La nota final mezcla la de la IA (o las reglas) con la del corte (si la
    frase empieza y acaba limpia, el ritmo…), que la IA no ve.
    """
    from app.services import ai

    notas_ia: list[dict[str, Any] | None] = [None] * len(candidatos)
    if usar_ia and candidatos and ai.is_enabled():
        notas_ia = con_ia(candidatos, titulo=titulo, contexto=contexto)
        buenas = sum(1 for n in notas_ia if n)
        if avisar:
            avisar(
                f"La IA ha puntuado {buenas} de {len(candidatos)} momentos"
                if buenas else "La IA no ha respondido: nota calculada con reglas"
            )

    salida = []
    for candidato, nota in zip(candidatos, notas_ia):
        nota = nota or por_reglas(candidato)
        corte = float(candidato.get("score", 0) or 0)
        nuevo = dict(candidato)
        nuevo["viralidad"] = nota
        nuevo["score"] = round(0.75 * nota["total"] / 100 + 0.25 * corte, 3)
        if nota["fuente"] == "ia":
            if nota["motivo"]:
                nuevo["reason"] = nota["motivo"]
            if nota["gancho_titulo"]:
                nuevo["hook"] = nota["gancho_titulo"]
        salida.append(nuevo)
    return salida


def elegir(candidatos: list[dict[str, Any]], cuantos: int) -> list[dict[str, Any]]:
    """Los `cuantos` mejores por nota, devueltos en el orden del vídeo."""
    mejores = sorted(candidatos, key=lambda c: c.get("score", 0), reverse=True)[: max(1, cuantos)]
    return sorted(mejores, key=lambda c: c["start"])
