"""Transcripción con marcas de tiempo.

Fuentes admitidas:
  * Subtítulos descargados de YouTube (json3 con tiempo por palabra, vtt o srt).
  * Whisper local (opcional, si el usuario instala faster-whisper).

Formato interno unificado:
    {"words": [{"start": 1.2, "end": 1.6, "text": "hola"}, ...],
     "segments": [{"start": .., "end": .., "text": ".."}],
     "language": "es", "source": "youtube"}
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

MAX_WORD_GAP = 1.2  # segundos: por encima de esto se corta la frase


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _clean(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\[[^\]]{0,30}\]", " ", text)  # [Música], [Aplausos]
    return re.sub(r"\s+", " ", text).strip()


def _timestamp_to_seconds(value: str) -> float:
    value = value.replace(",", ".").strip()
    parts = value.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except ValueError:
        return 0.0


def words_to_segments(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Agrupa palabras en frases usando pausas y signos de puntuación."""
    segments: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        segments.append(
            {
                "start": current[0]["start"],
                "end": current[-1]["end"],
                "text": " ".join(w["text"] for w in current).strip(),
            }
        )
        current.clear()

    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            long_enough = len(current) >= 6
            if gap > MAX_WORD_GAP or (
                long_enough and current[-1]["text"].endswith((".", "?", "!", "…"))
            ):
                flush()
        current.append(word)
        if len(current) >= 40:
            flush()
    flush()
    return segments


def _dedupe_words(words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los subtítulos automáticos repiten líneas al hacer scroll: se limpian."""
    result: list[dict[str, Any]] = []
    for word in words:
        if not word["text"]:
            continue
        if result and word["start"] < result[-1]["end"] - 0.05 and word["text"] == result[-1]["text"]:
            continue
        if result and word["start"] < result[-1]["start"]:
            continue
        word["end"] = max(word["end"], word["start"] + 0.08)
        result.append(word)
    return result


# --------------------------------------------------------------------------
# Analizadores de formato
# --------------------------------------------------------------------------
def parse_json3(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8", errors="ignore") or "{}")
    words: list[dict[str, Any]] = []
    for event in data.get("events") or []:
        start_ms = event.get("tStartMs")
        if start_ms is None or not event.get("segs"):
            continue
        duration_ms = event.get("dDurationMs") or 0
        for seg in event["segs"]:
            text = _clean(seg.get("utf8", ""))
            if not text:
                continue
            offset = seg.get("tOffsetMs") or 0
            start = (start_ms + offset) / 1000
            words.append({"start": start, "end": start + 0.4, "text": text})
        # ajustamos el final de cada palabra al inicio de la siguiente
        if duration_ms and words:
            words[-1]["end"] = (start_ms + duration_ms) / 1000
    for index in range(len(words) - 1):
        words[index]["end"] = min(
            max(words[index]["end"], words[index]["start"] + 0.1), words[index + 1]["start"]
        )
    return _dedupe_words(words)


def parse_vtt(path: str | Path) -> list[dict[str, Any]]:
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    words: list[dict[str, Any]] = []
    cue_re = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})\s*-->\s*"
        r"(\d{1,2}:\d{2}:\d{2}[.,]\d{3}|\d{1,2}:\d{2}[.,]\d{3})"
    )
    inline_re = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})>")

    blocks = re.split(r"\n\s*\n", raw)
    for block in blocks:
        match = cue_re.search(block)
        if not match:
            continue
        cue_start = _timestamp_to_seconds(match.group(1))
        cue_end = _timestamp_to_seconds(match.group(2))
        body = block[match.end():].strip("\n")
        if not body.strip():
            continue

        if inline_re.search(body):
            # subtítulos automáticos con tiempo por palabra
            pieces = inline_re.split(body)
            cursor = cue_start
            head = _clean(pieces[0])
            if head:
                for token in head.split():
                    words.append({"start": cursor, "end": cursor + 0.3, "text": token})
            for index in range(1, len(pieces), 2):
                stamp = _timestamp_to_seconds(pieces[index])
                text = _clean(pieces[index + 1] if index + 1 < len(pieces) else "")
                cursor = stamp
                for token in text.split():
                    words.append({"start": cursor, "end": cursor + 0.3, "text": token})
        else:
            text = _clean(body)
            tokens = text.split()
            if not tokens:
                continue
            span = max(0.2, cue_end - cue_start)
            step = span / len(tokens)
            for position, token in enumerate(tokens):
                start = cue_start + position * step
                words.append({"start": start, "end": start + step, "text": token})

    for index in range(len(words) - 1):
        words[index]["end"] = min(
            max(words[index]["end"], words[index]["start"] + 0.1), words[index + 1]["start"]
        )
    return _dedupe_words(words)


def parse_subtitle_file(path: str | Path) -> list[dict[str, Any]]:
    suffix = Path(path).suffix.lower()
    if suffix == ".json3":
        return parse_json3(path)
    if suffix in {".vtt", ".srt"}:
        return parse_vtt(path)
    return []


def pick_subtitle_file(paths: list[str], languages: list[str]) -> str | None:
    """Elige el mejor archivo: idioma preferido y formato con más información."""
    if not paths:
        return None
    ranked: list[tuple[int, int, str]] = []
    for path in paths:
        name = Path(path).name.lower()
        lang_rank = len(languages) + 1
        for index, lang in enumerate(languages):
            if f".{lang}." in name or f".{lang}-" in name:
                lang_rank = index
                break
        format_rank = {".json3": 0, ".vtt": 1, ".srt": 2}.get(Path(path).suffix.lower(), 3)
        ranked.append((lang_rank, format_rank, path))
    ranked.sort()
    return ranked[0][2]


# --------------------------------------------------------------------------
# Whisper local (opcional)
# --------------------------------------------------------------------------
def transcribe_with_whisper(
    media_path: str | Path, *, model: str = "small", language: str = "es"
) -> dict[str, Any]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except Exception as exc:  # pragma: no cover - dependencia opcional
        raise RuntimeError(
            "Whisper no está instalado. Ejecuta: pip install faster-whisper"
        ) from exc

    whisper = WhisperModel(model, device="auto", compute_type="int8")
    segments, info = whisper.transcribe(
        str(media_path),
        language=None if language == "auto" else language,
        word_timestamps=True,
        vad_filter=True,
    )
    words: list[dict[str, Any]] = []
    for segment in segments:
        for word in segment.words or []:
            text = _clean(word.word)
            if text:
                words.append({"start": float(word.start), "end": float(word.end), "text": text})
    return {
        "words": words,
        "segments": words_to_segments(words),
        "language": getattr(info, "language", language),
        "source": "whisper",
    }


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Whisper en la nube (Groq): para vídeos sin subtítulos de YouTube
# --------------------------------------------------------------------------
NUBE_MODELO = "whisper-large-v3-turbo"
NUBE_TROZO_S = 1200          # 20 min de audio a 32 kb/s ≈ 4,8 MB: cabe de sobra
NUBE_TIPOS = {"groq"}        # gratis; los de pago no se usan sin pedirlo


def proveedor_en_la_nube():
    """El proveedor con Whisper que tengas configurado (hoy, Groq), o None."""
    from app.services import ai

    for provider in ai.configured_providers():
        if provider.tipo in NUBE_TIPOS or provider.key in NUBE_TIPOS:
            return provider
    return None


def _trozos_de_audio(media_path: str | Path, destino: Path) -> list[Path]:
    from app import procesos
    from app.config import settings

    destino.mkdir(parents=True, exist_ok=True)
    patron = destino / "trozo-%03d.mp3"
    procesos.run(
        [
            settings.ffmpeg_path, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
            "-i", str(media_path), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k",
            "-f", "segment", "-segment_time", str(NUBE_TROZO_S), "-reset_timestamps", "1",
            str(patron),
        ],
        capture_output=True, timeout=3600, check=True,
    )
    return sorted(destino.glob("trozo-*.mp3"))


def transcribe_in_cloud(
    media_path: str | Path, *, language: str = "es", provider=None,
    on_progress=None,
) -> dict[str, Any]:
    """Transcribe con Whisper de Groq, con el tiempo de cada palabra."""
    import shutil
    import tempfile

    import httpx

    from app.services import media as media_service

    provider = provider or proveedor_en_la_nube()
    if provider is None:
        raise RuntimeError("No hay ningún servicio con Whisper configurado (añade Groq en IA).")
    carpeta = Path(tempfile.mkdtemp(prefix="kevil-voz-"))
    words: list[dict[str, Any]] = []
    try:
        trozos = _trozos_de_audio(media_path, carpeta)
        desplazamiento = 0.0
        with httpx.Client(timeout=httpx.Timeout(30.0, read=600.0)) as cliente:
            for numero, trozo in enumerate(trozos):
                if on_progress:
                    on_progress(numero / max(1, len(trozos)))
                datos = {
                    "model": NUBE_MODELO,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": ["word", "segment"],
                }
                if language and language != "auto":
                    datos["language"] = language
                with trozo.open("rb") as audio:
                    respuesta = cliente.post(
                        f"{provider.base_url.rstrip('/')}/audio/transcriptions",
                        headers={"Authorization": f"Bearer {provider.api_key}"},
                        data=datos,
                        files={"file": (trozo.name, audio, "audio/mpeg")},
                    )
                if respuesta.status_code >= 400:
                    raise RuntimeError(
                        f"{provider.label or 'Groq'} no ha podido transcribir "
                        f"({respuesta.status_code}): {respuesta.text[:200]}"
                    )
                cuerpo = respuesta.json()
                sueltas = cuerpo.get("words") or []
                if not sueltas:
                    # sin tiempos por palabra: se reparten dentro de cada frase
                    for segmento in cuerpo.get("segments") or []:
                        trozos_texto = str(segmento.get("text", "")).split()
                        ini, fin = float(segmento["start"]), float(segmento["end"])
                        paso = (fin - ini) / max(1, len(trozos_texto))
                        for n, texto in enumerate(trozos_texto):
                            sueltas.append({"word": texto, "start": ini + n * paso,
                                            "end": ini + (n + 1) * paso})
                for palabra in sueltas:
                    texto = _clean(str(palabra.get("word", "")))
                    if texto:
                        words.append({
                            "start": round(float(palabra["start"]) + desplazamiento, 3),
                            "end": round(float(palabra["end"]) + desplazamiento, 3),
                            "text": texto,
                        })
                duracion = float(media_service.probe(trozo).get("duration") or NUBE_TROZO_S)
                desplazamiento += duracion
    finally:
        shutil.rmtree(carpeta, ignore_errors=True)
    return {
        "words": words,
        "segments": words_to_segments(words),
        "language": language,
        "source": "whisper-nube",
    }


def _whisper_local_disponible() -> bool:
    try:
        import faster_whisper  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def transcribir_archivo(
    media_path: str | Path, *, language: str = "es", whisper_model: str = "small"
) -> dict[str, Any]:
    """Un archivo sin subtítulos: Whisper en tu PC si está, si no, en la nube."""
    if _whisper_local_disponible():
        return transcribe_with_whisper(media_path, model=whisper_model, language=language)
    if proveedor_en_la_nube() is not None:
        return transcribe_in_cloud(media_path, language=language)
    return {"words": [], "segments": [], "language": language, "source": "unavailable"}


def build_transcript(
    *,
    engine: str,
    media_path: str | Path,
    subtitle_files: list[str],
    language: str = "es",
    whisper_model: str = "small",
) -> dict[str, Any]:
    languages = [language] if language != "auto" else ["es", "en"]

    def from_youtube() -> dict[str, Any] | None:
        chosen = pick_subtitle_file(subtitle_files, languages)
        if not chosen:
            return None
        words = parse_subtitle_file(chosen)
        if len(words) < 5:
            return None
        return {
            "words": words,
            "segments": words_to_segments(words),
            "language": language,
            "source": "youtube",
            "file": chosen,
        }

    if engine == "none":
        return {"words": [], "segments": [], "language": language, "source": "none"}
    if engine == "youtube":
        resultado = from_youtube()
        if resultado:
            return resultado
        # sin subtítulos (vídeo del PC, o YouTube no los tiene): Whisper en la
        # nube si tienes Groq, que es gratis
        if media_path and Path(media_path).exists() and proveedor_en_la_nube() is not None:
            try:
                return transcribe_in_cloud(media_path, language=language)
            except Exception:
                pass
        return {"words": [], "segments": [], "language": language, "source": "unavailable"}
    if engine == "whisper":
        return transcribe_with_whisper(media_path, model=whisper_model, language=language)
    if engine == "youtube_then_whisper":
        result = from_youtube()
        if result:
            return result
        try:
            return transcribe_with_whisper(media_path, model=whisper_model, language=language)
        except Exception:
            return {
                "words": [], "segments": [], "language": language, "source": "unavailable"
            }
    return {"words": [], "segments": [], "language": language, "source": "none"}


def slice_words(
    words: list[dict[str, Any]], start: float, end: float
) -> list[dict[str, Any]]:
    """Palabras dentro de un tramo, con los tiempos ya relativos al clip."""
    result = []
    for word in words:
        if word["end"] <= start or word["start"] >= end:
            continue
        result.append(
            {
                "start": round(max(0.0, word["start"] - start), 3),
                "end": round(min(end - start, word["end"] - start), 3),
                "text": word["text"],
            }
        )
    return result
