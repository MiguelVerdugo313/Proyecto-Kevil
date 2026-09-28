"""Limpieza del clip: fuera los silencios largos y los «eh», «em», «mmm».

Se decide con la transcripción (cuándo se habla y qué se dice), así que sólo
se corta donde nadie habla. Ojo en los gameplays: si en ese silencio pasa algo
en pantalla, también se va; por eso viene apagado y se enciende a propósito.

Todo trabaja en segundos relativos al clip: 0 es el inicio del corte.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Sonidos de relleno, no palabras: «este», «pues» o «o sea» a veces significan
# algo y cortarlos cambiaría la frase.
MULETILLA = re.compile(r"^(?:e+h+|e{2,}|e+m+|m{2,}|h+m+|u+m+|u+h+m*|a+h+m+|mm+h+)$")

PAUSA_POR_DEFECTO = 0.8     # silencios más largos se acortan
AIRE_ANTES = 0.12           # lo que se deja antes de volver a hablar
AIRE_DESPUES = 0.18         # y después de la última palabra
CORTE_MINIMO = 0.25         # cortes más pequeños no merecen el salto


def _normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", (texto or "").lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", texto)


def es_muletilla(texto: str) -> bool:
    limpia = _normalizar(texto)
    return bool(limpia) and bool(MULETILLA.match(limpia))


def _unir(huecos: list[tuple[float, float]]) -> list[tuple[float, float]]:
    unidos: list[tuple[float, float]] = []
    for a, b in sorted(huecos):
        if unidos and a <= unidos[-1][1] + 0.01:
            unidos[-1] = (unidos[-1][0], max(unidos[-1][1], b))
        else:
            unidos.append((a, b))
    return unidos


def cortes(
    words: list[dict[str, Any]],
    duracion: float,
    *,
    silencios: bool = False,
    muletillas: bool = False,
    pausa_max: float = PAUSA_POR_DEFECTO,
) -> list[tuple[float, float]]:
    """Los trozos que se quitan del clip, de menor a mayor y sin solaparse."""
    if not words or duracion <= 0 or not (silencios or muletillas):
        return []
    habladas = sorted(
        (w for w in words if (w.get("text") or "").strip()), key=lambda w: w["start"]
    )
    huecos: list[tuple[float, float]] = []

    if muletillas:
        for index, word in enumerate(habladas):
            if not es_muletilla(word["text"]):
                continue
            # la muletilla y el aire que la rodea, hasta las palabras vecinas
            antes = habladas[index - 1]["end"] if index else 0.0
            despues = habladas[index + 1]["start"] if index + 1 < len(habladas) else duracion
            a = max(antes + 0.04, word["start"] - 0.05)
            b = min(despues - 0.04, word["end"] + 0.05)
            if b > a:
                huecos.append((a, b))

    if silencios:
        pausa_max = max(0.3, float(pausa_max or PAUSA_POR_DEFECTO))
        reales = [w for w in habladas if not (muletillas and es_muletilla(w["text"]))]
        for anterior, siguiente in zip(reales, reales[1:]):
            hueco = siguiente["start"] - anterior["end"]
            if hueco > pausa_max:
                huecos.append((anterior["end"] + AIRE_DESPUES, siguiente["start"] - AIRE_ANTES))

    limpios = [
        (round(max(0.0, a), 3), round(min(duracion, b), 3))
        for a, b in _unir(huecos)
        if min(duracion, b) - max(0.0, a) >= CORTE_MINIMO
    ]
    return limpios


def tramos(duracion: float, quitados: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Lo que se queda: el complemento de los cortes dentro de [0, duración]."""
    quedan: list[tuple[float, float]] = []
    cursor = 0.0
    for a, b in quitados:
        if a > cursor:
            quedan.append((round(cursor, 3), round(a, 3)))
        cursor = max(cursor, b)
    if cursor < duracion:
        quedan.append((round(cursor, 3), round(duracion, 3)))
    return [(a, b) for a, b in quedan if b - a > 0.04]


def nuevo_tiempo(t: float, quitados: list[tuple[float, float]]) -> float:
    """Dónde cae el instante `t` del clip original una vez hechos los cortes."""
    menos = 0.0
    for a, b in quitados:
        if t >= b:
            menos += b - a
        elif t > a:
            menos += t - a          # dentro de un corte: se pega a donde empieza
    return max(0.0, t - menos)


def recolocar(
    words: list[dict[str, Any]], quitados: list[tuple[float, float]], *, muletillas: bool
) -> list[dict[str, Any]]:
    """Las palabras con sus tiempos nuevos, sin las muletillas quitadas."""
    if not quitados:
        return list(words)
    salida = []
    for word in words:
        if muletillas and es_muletilla(word.get("text", "")):
            continue
        inicio = nuevo_tiempo(float(word["start"]), quitados)
        fin = nuevo_tiempo(float(word["end"]), quitados)
        if fin - inicio < 0.05:
            continue                     # se la comió un corte
        salida.append({**word, "start": round(inicio, 3), "end": round(fin, 3)})
    return salida


def resumen(duracion: float, quitados: list[tuple[float, float]]) -> str:
    total = sum(b - a for a, b in quitados)
    if not quitados:
        return ""
    return f"Limpieza: {len(quitados)} cortes, {total:.1f} s menos ({duracion - total:.1f} s)"
