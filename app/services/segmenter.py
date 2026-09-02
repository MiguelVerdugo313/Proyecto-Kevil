"""Selección de los momentos que se convertirán en clips.

Cada estrategia devuelve una lista de candidatos:
    {"start": s, "end": s, "score": 0..1, "reason": "...", "hook": "...", "text": "..."}
"""

from __future__ import annotations

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


def _usable_range(duration: float, config: dict[str, Any]) -> tuple[float, float]:
    start = max(0.0, float(config.get("skip_intro", 0) or 0))
    end = max(start, duration - float(config.get("skip_outro", 0) or 0))
    if end - start < 5:  # el vídeo es demasiado corto para recortar tanto
        return 0.0, duration
    return start, end


def _target_count(duration: float, config: dict[str, Any]) -> int:
    per_hour = float(config.get("clips_per_hour", 8) or 8)
    max_clips = int(config.get("max_clips", 12) or 12)
    estimated = max(1, round(duration / 3600 * per_hour))
    return int(max(1, min(max_clips, estimated)))


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


def _dedupe_and_limit(
    candidates: list[dict[str, Any]], *, min_gap: float, max_clips: int
) -> list[dict[str, Any]]:
    """Se queda con los mejores sin solaparse y respetando la separación."""
    chosen: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda c: c["score"], reverse=True):
        if len(chosen) >= max_clips:
            break
        conflict = any(
            candidate["start"] < other["end"] + min_gap
            and other["start"] < candidate["end"] + min_gap
            for other in chosen
        )
        if not conflict:
            chosen.append(candidate)
    chosen.sort(key=lambda c: c["start"])
    return chosen


# --------------------------------------------------------------------------
# Estrategias
# --------------------------------------------------------------------------
def segment_uniform(duration: float, config: dict[str, Any]) -> list[dict[str, Any]]:
    start, end = _usable_range(duration, config)
    clip_len = float(config.get("max_duration", 59) or 59)
    min_len = float(config.get("min_duration", 21) or 21)
    gap = float(config.get("min_gap", 0) or 0)
    max_clips = _target_count(duration, config)

    candidates: list[dict[str, Any]] = []
    cursor = start
    index = 0
    while cursor + min_len <= end and len(candidates) < max_clips:
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


def segment_by_silence(
    media_path: str, duration: float, config: dict[str, Any]
) -> list[dict[str, Any]]:
    start, end = _usable_range(duration, config)
    min_len = float(config.get("min_duration", 21) or 21)
    max_len = float(config.get("max_duration", 59) or 59)

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
    return _dedupe_and_limit(
        candidates,
        min_gap=float(config.get("min_gap", 0) or 0),
        max_clips=_target_count(duration, config),
    )


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
    min_len = float(config.get("min_duration", 21) or 21)
    max_len = float(config.get("max_duration", 59) or 59)
    boost = [_normalize(k) for k in (config.get("boost_keywords") or []) if k]
    avoid = [_normalize(k) for k in (config.get("avoid_keywords") or []) if k]
    prefer_questions = bool(config.get("prefer_questions", True))

    usable = [s for s in segments if s["end"] > start_limit and s["start"] < end_limit]
    candidates: list[dict[str, Any]] = []

    for index, segment in enumerate(usable):
        window_start = max(start_limit, segment["start"])
        pieces = [segment]
        cursor = index + 1
        while cursor < len(usable) and usable[cursor]["end"] - window_start <= max_len:
            pieces.append(usable[cursor])
            cursor += 1
        window_end = min(end_limit, pieces[-1]["end"])
        if window_end - window_start < min_len:
            continue

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

        candidates.append(
            {
                "start": round(window_start, 2),
                "end": round(window_end, 2),
                "score": round(score, 3),
                "reason": ", ".join(reasons).capitalize(),
                "hook": _make_hook(text),
                "text": text[:1200],
            }
        )

    return _dedupe_and_limit(
        candidates,
        min_gap=float(config.get("min_gap", 30) or 0),
        max_clips=_target_count(duration, config),
    )


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

    # márgenes de cortesía y ajuste final
    pad_start = float(config.get("pad_start", 0) or 0)
    pad_end = float(config.get("pad_end", 0) or 0)
    min_len = float(config.get("min_duration", 21) or 21)
    max_len = float(config.get("max_duration", 59) or 59)

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
