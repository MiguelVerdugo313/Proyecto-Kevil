"""Selección de los momentos que se convertirán en clips.

Cada estrategia devuelve una lista de candidatos:
    {"start": s, "end": s, "score": 0..1, "reason": "...", "hook": "...", "text": "..."}
"""

from __future__ import annotations

import bisect
import itertools
import math
import random
import re
from typing import Any

from app.services import media as media_service

QUESTION_RE = re.compile(r"[¿?]")
HOOK_STARTERS = (
    "por qué", "cómo", "qué pasa", "lo que", "nadie", "esto es", "el error",
    "el truco", "te voy a", "mira", "imagina", "la clave", "si tú", "nunca",
    "siempre", "atención", "escucha",
)


# --------------------------------------------------------------------------
# Ayudas
# --------------------------------------------------------------------------
def _normalize(text: str) -> str:
    text = text.lower()
    for source, target in zip("áéíóúü", "aeiouu"):
        text = text.replace(source, target)
    return text


# Lo que se salta al principio y al final es para la espera de los directos.
# En un vídeo corto no puede comerse más que este trozo de cada punta: los
# primeros segundos de un vídeo normal suelen ser justo lo mejor.
MAX_SALTO = 0.15

# Por poco que dure el vídeo, se buscan al menos estos clips (si caben).
CLIPS_MINIMOS = 8


def _usable_range(duration: float, config: dict[str, Any]) -> tuple[float, float]:
    intro = min(float(config.get("skip_intro", 0) or 0), duration * MAX_SALTO)
    outro = min(float(config.get("skip_outro", 0) or 0), duration * MAX_SALTO)
    start = max(0.0, intro)
    end = max(start, duration - max(0.0, outro))
    if end - start < 5:  # el vídeo es demasiado corto para recortar tanto
        return 0.0, duration
    return start, end


def _lengths(config: dict[str, Any]) -> tuple[float, float]:
    min_len = float(config.get("min_duration", 21) or 21)
    max_len = max(min_len, float(config.get("max_duration", 59) or 59))
    return min_len, max_len


def _gap(duration: float, config: dict[str, Any]) -> float:
    """Separación entre clips, proporcional a lo que dura el vídeo.

    Treinta segundos entre clips tienen sentido en un directo de dos horas; en
    un vídeo de cinco minutos se comen la mitad de los momentos buenos.
    """
    start, end = _usable_range(duration, config)
    wanted = float(config.get("min_gap", 0) or 0)
    # nunca por debajo de los márgenes, para que al añadirlos no se pisen
    pads = float(config.get("pad_start", 0) or 0) + float(config.get("pad_end", 0) or 0)
    return max(pads, min(wanted, (end - start) / 50))


def _target_count(duration: float, config: dict[str, Any]) -> int:
    """Cuántos clips se buscan en este vídeo.

    Antes salían «clips por hora» a secas, y un vídeo de siete minutos daba
    uno solo. Ahora se buscan al menos CLIPS_MINIMOS (o los que quepan, en un
    vídeo muy corto), más en los largos, sin pasar del máximo del flujo.
    """
    start, end = _usable_range(duration, config)
    usable = max(0.0, end - start)
    min_len, max_len = _lengths(config)
    gap = _gap(duration, config)
    ideal = (min_len + max_len) / 2

    fit = max(1, round((usable + gap) / (ideal + gap)))          # los que caben
    per_hour = float(config.get("clips_per_hour", 20) or 20)
    wanted = max(CLIPS_MINIMOS, math.ceil(usable / 3600 * per_hour))
    max_clips = int(config.get("max_clips", 20) or 20)
    return int(max(1, min(max_clips, fit, wanted)))


def _make_hook(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    hook = sentences[0] if sentences else text
    if len(hook) < 25 and len(sentences) > 1:
        hook = f"{hook} {sentences[1]}"
    hook = hook.strip(" ,;:-—")
    if len(hook) > limit:
        hook = hook[:limit].rsplit(" ", 1)[0] + "…"
    return hook


def _best_set(
    candidates: list[dict[str, Any]], *, min_gap: float, max_clips: int
) -> list[dict[str, Any]]:
    """El mejor juego de clips que no se pisan, hasta `max_clips`.

    Quedarse con el mejor y descartar todo lo que lo toca (lo de antes) deja
    huecos: un clip largo en mitad de un vídeo corto bloquea dos buenos. Aquí
    se elige el conjunto entero que más puntúa sumando, con programación
    dinámica sobre los candidatos ordenados por su final.
    """
    items = sorted((c for c in candidates if c["score"] > 0), key=lambda c: c["end"])
    if not items or max_clips <= 0:
        return []
    ends = [c["end"] for c in items]
    # cuántos candidatos terminan a tiempo para poder ir antes de cada uno
    previous = [bisect.bisect_right(ends, c["start"] - min_gap) for c in items]
    n = len(items)

    # best[j][i]: la mejor suma con los i primeros candidatos y j clips como mucho
    best = [[0.0] * (n + 1) for _ in range(max_clips + 1)]
    for j in range(1, max_clips + 1):
        row, fewer = best[j], best[j - 1]
        for i in range(1, n + 1):
            take = fewer[previous[i - 1]] + items[i - 1]["score"]
            row[i] = take if take > row[i - 1] else row[i - 1]

    chosen: list[dict[str, Any]] = []
    j, i = max_clips, n
    while j > 0 and i > 0:
        if best[j][i] == best[j][i - 1]:
            i -= 1
        else:
            chosen.append(items[i - 1])
            i = previous[i - 1]
            j -= 1
    chosen.sort(key=lambda c: c["start"])
    return chosen


def _conflicts(start: float, end: float, chosen: list[dict[str, Any]], gap: float) -> bool:
    return any(start < o["end"] + gap and o["start"] < end + gap for o in chosen)


def _fill(
    chosen: list[dict[str, Any]], duration: float, config: dict[str, Any], target: int
) -> list[dict[str, Any]]:
    """Completa con tramos seguidos si la estrategia se ha quedado corta.

    Pasa en partidas con poca charla: la transcripción da para pocos momentos
    y el vídeo acababa en un solo clip. Los tramos de relleno puntúan bajo,
    así que en la lista salen detrás de los elegidos por su contenido.
    """
    start, end = _usable_range(duration, config)
    min_len, max_len = _lengths(config)
    gap = _gap(duration, config)
    length = (min_len + max_len) / 2
    result = list(chosen)
    cursor = start
    while len(result) < target and cursor + min_len <= end:
        clip_end = min(cursor + length, end)
        if clip_end - cursor >= min_len and not _conflicts(cursor, clip_end, result, gap):
            result.append(
                {
                    "start": round(cursor, 2),
                    "end": round(clip_end, 2),
                    "score": 0.2,
                    "reason": "Tramo del vídeo",
                    "hook": "",
                    "text": "",
                }
            )
            cursor = clip_end + gap
        else:
            cursor += 2.0
    result.sort(key=lambda c: c["start"])
    return result


# --------------------------------------------------------------------------
# Estrategias
# --------------------------------------------------------------------------
def segment_uniform(duration: float, config: dict[str, Any]) -> list[dict[str, Any]]:
    start, end = _usable_range(duration, config)
    min_len, max_len = _lengths(config)
    gap = _gap(duration, config)
    count = _target_count(duration, config)
    # trozos iguales que llenen el vídeo con los clips que tocan
    clip_len = min(max_len, max(min_len, (end - start - gap * (count - 1)) / count))

    candidates: list[dict[str, Any]] = []
    cursor = start
    index = 0
    while cursor + min_len <= end and len(candidates) < count:
        clip_end = min(cursor + clip_len, end)
        candidates.append(
            {
                "start": round(cursor, 2),
                "end": round(clip_end, 2),
                "score": round(max(0.15, 0.9 - index * 0.04), 3),
                "reason": "Corte por tiempo",
                "hook": "",
                "text": "",
            }
        )
        cursor = clip_end + gap
        index += 1
    return candidates


def segment_whole(duration: float, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Un único «clip» con el vídeo entero.

    Es lo que se usa para republicar Shorts que ya están hechos: no hay nada
    que recortar, sólo reencuadrar (si hiciera falta) y publicar.
    """
    if duration <= 0:
        return []
    return [
        {
            "start": 0.0,
            "end": round(duration, 2),
            "score": 0.9,
            "reason": "Vídeo completo",
            "hook": "",
            "text": "",
        }
    ]


def segment_by_silence(
    media_path: str, duration: float, config: dict[str, Any]
) -> list[dict[str, Any]]:
    start, end = _usable_range(duration, config)
    min_len, max_len = _lengths(config)

    silences = media_service.detect_silences(media_path, start=start, duration=end - start)
    if not silences:
        return segment_uniform(duration, config)

    boundaries = [start] + [ (a + b) / 2 for a, b in silences ] + [end]
    boundaries = sorted({round(b, 2) for b in boundaries if start <= b <= end})

    candidates: list[dict[str, Any]] = []
    cursor = boundaries[0]
    for boundary in boundaries[1:]:
        length = boundary - cursor
        if length < min_len:
            continue
        clip_end = min(boundary, cursor + max_len)
        candidates.append(
            {
                "start": round(cursor, 2),
                "end": round(clip_end, 2),
                "score": round(min(1.0, 0.4 + (clip_end - cursor) / max_len * 0.4), 3),
                "reason": "Bloque entre pausas",
                "hook": "",
                "text": "",
            }
        )
        cursor = clip_end
    return _best_set(
        candidates,
        min_gap=_gap(duration, config),
        max_clips=_target_count(duration, config),
    )


def _window_ends(
    usable: list[dict[str, Any]], index: int, window_start: float,
    end_limit: float, min_len: float, max_len: float,
) -> list[float]:
    """Dónde puede terminar una ventana que empieza en la frase `index`.

    Se ofrecen tres largos (el más corto, el más cercano al ideal y el más
    largo) para que en un vídeo corto quepan varios clips en vez de uno largo.
    """
    ends: list[float] = []
    cursor = index
    while cursor < len(usable) and usable[cursor]["end"] - window_start <= max_len:
        ends.append(min(end_limit, usable[cursor]["end"]))
        cursor += 1
    valid = sorted({e for e in ends if e - window_start >= min_len})
    if len(valid) <= 3:
        return valid
    ideal = window_start + (min_len + max_len) / 2
    middle = min(valid, key=lambda e: abs(e - ideal))
    return sorted({valid[0], middle, valid[-1]})


def segment_smart(
    transcript: dict[str, Any], duration: float, config: dict[str, Any]
) -> list[dict[str, Any]]:
    """Puntúa ventanas que empiezan en frase completa y contienen ganchos."""
    segments = [
        s for s in (transcript.get("segments") or []) if s.get("text")
    ]
    if len(segments) < 3:
        return []

    start_limit, end_limit = _usable_range(duration, config)
    min_len, max_len = _lengths(config)
    boost = [_normalize(k) for k in (config.get("boost_keywords") or []) if k]
    avoid = [_normalize(k) for k in (config.get("avoid_keywords") or []) if k]
    prefer_questions = bool(config.get("prefer_questions", True))

    usable = [s for s in segments if s["end"] > start_limit and s["start"] < end_limit]
    candidates: list[dict[str, Any]] = []

    for index, segment in enumerate(usable):
        window_start = max(start_limit, segment["start"])
        for window_end in _window_ends(usable, index, window_start, end_limit, min_len, max_len):
            pieces = list(
                itertools.takewhile(lambda p: p["start"] < window_end - 0.01, usable[index:])
            )
            candidates.append(
                _score_window(
                    pieces, window_start, window_end,
                    start_limit=start_limit, min_len=min_len, max_len=max_len,
                    boost=boost, avoid=avoid, prefer_questions=prefer_questions,
                )
            )

    return _best_set(
        candidates,
        min_gap=_gap(duration, config),
        max_clips=_target_count(duration, config),
    )


def _score_window(
    pieces: list[dict[str, Any]], window_start: float, window_end: float, *,
    start_limit: float, min_len: float, max_len: float,
    boost: list[str], avoid: list[str], prefer_questions: bool,
) -> dict[str, Any]:
    text = " ".join(p["text"] for p in pieces)
    normalized = _normalize(text)
    words_count = len(text.split())
    length = window_end - window_start

    # --- puntuación -------------------------------------------------
    density = words_count / max(1.0, length)          # palabras por segundo
    score = min(1.0, density / 3.2) * 0.35            # ritmo del discurso

    boost_hits = sum(1 for keyword in boost if keyword in normalized)
    score += min(0.30, boost_hits * 0.10)

    if prefer_questions and QUESTION_RE.search(text):
        score += 0.10

    opening = _normalize(text[:60])
    if any(opening.startswith(starter) or starter in opening for starter in HOOK_STARTERS):
        score += 0.12

    if re.search(r"\b\d{1,4}\b", text):               # cifras y datos concretos
        score += 0.05

    ideal = (min_len + max_len) / 2
    score += 0.10 * (1 - min(1.0, abs(length - ideal) / ideal))

    avoid_hits = sum(1 for keyword in avoid if keyword in normalized)
    score -= avoid_hits * 0.25

    if window_start < start_limit + 20:
        score -= 0.05

    score = max(0.0, min(1.0, score))
    reasons = []
    if boost_hits:
        reasons.append(f"{boost_hits} palabra(s) gancho")
    if prefer_questions and QUESTION_RE.search(text):
        reasons.append("pregunta directa")
    if density > 2.6:
        reasons.append("ritmo alto")
    if not reasons:
        reasons.append("frase completa")

    return {
        "start": round(window_start, 2),
        "end": round(window_end, 2),
        "score": round(score, 3),
        "reason": ", ".join(reasons).capitalize(),
        "hook": _make_hook(text),
        "text": text[:1200],
    }


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------
def find_segments(
    *,
    media_path: str,
    duration: float,
    transcript: dict[str, Any] | None,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    strategy = (config.get("strategy") or "smart").lower()
    transcript = transcript or {}

    if strategy == "manual":
        return []

    # El vídeo entero se devuelve tal cual, sin márgenes ni recortes por duración
    if strategy == "completo":
        return segment_whole(duration, config)

    candidates: list[dict[str, Any]] = []
    if strategy == "smart":
        candidates = segment_smart(transcript, duration, config)
        if not candidates:
            candidates = segment_by_silence(media_path, duration, config)
    elif strategy == "silence":
        candidates = segment_by_silence(media_path, duration, config)
    else:
        candidates = segment_uniform(duration, config)

    if not candidates:
        candidates = segment_uniform(duration, config)
    elif strategy in {"smart", "silence"}:
        candidates = _fill(candidates, duration, config, _target_count(duration, config))

    # márgenes de cortesía y ajuste final
    pad_start = float(config.get("pad_start", 0) or 0)
    pad_end = float(config.get("pad_end", 0) or 0)
    min_len, max_len = _lengths(config)

    final: list[dict[str, Any]] = []
    for candidate in candidates:
        start = max(0.0, candidate["start"] - pad_start)
        end = min(duration, candidate["end"] + pad_end)
        if end - start < min(min_len, duration):
            continue
        if end - start > max_len:
            end = start + max_len
        candidate = dict(candidate)
        candidate["start"] = round(start, 2)
        candidate["end"] = round(end, 2)
        final.append(candidate)

    # completa el texto y el gancho a partir de la transcripción si faltan
    words = transcript.get("words") or []
    if words:
        for candidate in final:
            if candidate.get("hook"):
                continue
            text = " ".join(
                w["text"] for w in words
                if w["start"] >= candidate["start"] and w["end"] <= candidate["end"]
            )
            candidate["text"] = text[:1200]
            candidate["hook"] = _make_hook(text)

    return final


def shuffle_order(items: list[Any], order: str) -> list[Any]:
    if order == "random":
        items = list(items)
        random.shuffle(items)
        return items
    return items
