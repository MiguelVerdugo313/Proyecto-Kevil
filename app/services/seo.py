"""Kit de publicación para YouTube: títulos, descripción, etiquetas y capítulos.

Sigue las buenas prácticas habituales del formato largo:

* **Título**: 50-60 caracteres, la idea fuerte al principio, sin engañar.
* **Descripción**: gancho en las dos primeras líneas (es lo único que se ve
  antes de «...más»), luego el desarrollo, capítulos y enlaces.
* **Capítulos**: el primero SIEMPRE en 00:00 y mínimo tres, o YouTube no los
  activa; separación mínima de 10 segundos.
* **Etiquetas**: unas 10-15, de lo concreto a lo general, sin repetir relleno.
* **Hashtags**: 3 como mucho en la descripción (los tres primeros son los que
  se muestran encima del título).

Con IA salen mejor redactados; sin IA se generan a partir de la transcripción,
que ya es bastante mejor que dejarlo en blanco.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.services import ai
from app.services.metadata import STOPWORDS, slugify_tag

MAX_TITLE = 70
IDEAL_TITLE = 60


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _sin_tildes(word: str) -> str:
    for origen, destino in zip("áéíóúü", "aeiouu"):
        word = word.replace(origen, destino)
    return word


def keywords(text: str, limit: int = 20) -> list[str]:
    words = re.findall(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ0-9]{4,}", (text or "").lower())
    # «cómo» y «como» son la misma palabra vacía: se comparan sin tildes
    counter = Counter(
        word for word in words
        if word not in STOPWORDS and _sin_tildes(word) not in STOPWORDS
    )
    return [word for word, _ in counter.most_common(limit)]


def transcript_text(transcript: dict[str, Any], limit: int = 9000) -> str:
    segments = transcript.get("segments") or []
    if segments:
        text = " ".join(segment.get("text", "") for segment in segments)
    else:
        text = " ".join(word.get("text", "") for word in transcript.get("words") or [])
    return text[:limit].strip()


def sample_for_chapters(transcript: dict[str, Any], target: int = 40) -> list[dict[str, Any]]:
    """Muestra repartida de la transcripción con sus tiempos, para los capítulos."""
    segments = [s for s in (transcript.get("segments") or []) if s.get("text")]
    if not segments:
        return []
    step = max(1, len(segments) // target)
    return [
        {"t": round(segment["start"], 1), "texto": segment["text"][:160]}
        for segment in segments[::step]
    ][:target]


# --------------------------------------------------------------------------
# Generación sin IA
# --------------------------------------------------------------------------
def _basic_chapters(transcript: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    """Capítulos por bloques regulares, titulados con las palabras del tramo."""
    if duration < 120:
        return []
    segments = [s for s in (transcript.get("segments") or []) if s.get("text")]
    count = max(3, min(10, int(duration // 180) + 2))
    block = duration / count

    chapters: list[dict[str, Any]] = []
    for index in range(count):
        start = index * block
        end = start + block
        texto = " ".join(
            s["text"] for s in segments if start <= s["start"] < end
        )
        palabras = keywords(texto, limit=3)
        titulo = ", ".join(word.capitalize() for word in palabras) or f"Parte {index + 1}"
        chapters.append({"time": 0 if index == 0 else round(start), "title": titulo[:80]})

    # YouTube exige que el primero sea 00:00 y 10 s de separación mínima
    chapters[0]["time"] = 0
    limpio = [chapters[0]]
    for chapter in chapters[1:]:
        if chapter["time"] - limpio[-1]["time"] >= 10:
            limpio.append(chapter)
    return limpio if len(limpio) >= 3 else []


def build_basic_kit(
    *,
    title: str,
    transcript: dict[str, Any],
    duration: float,
    topic: str = "",
) -> dict[str, Any]:
    """Kit razonable sin usar IA: se apoya en la transcripción."""
    texto = transcript_text(transcript, 6000)
    palabras = keywords(f"{title} {texto}", limit=15)

    base = title.strip() or (palabras[0].capitalize() if palabras else "Vídeo nuevo")
    titulos = [
        base[:MAX_TITLE],
        f"{base} | Guía completa"[:MAX_TITLE],
        f"Lo que nadie te cuenta sobre {palabras[0]}"[:MAX_TITLE] if palabras else base[:MAX_TITLE],
    ]

    gancho = ""
    for segment in transcript.get("segments") or []:
        if len(segment.get("text", "")) > 40:
            gancho = segment["text"].strip()
            break
    gancho = gancho or f"Todo sobre {base}."

    capitulos = _basic_chapters(transcript, duration)
    bloque_capitulos = ""
    if capitulos:
        bloque_capitulos = "\n\n⏱️ Capítulos\n" + "\n".join(
            f"{timestamp(c['time'])} {c['title']}" for c in capitulos
        )

    etiquetas = [word for word in palabras if len(word) >= 4][:15]
    hashtags = [slugify_tag(word) for word in palabras[:3] if slugify_tag(word)]

    descripcion = (
        f"{gancho[:180]}\n\n"
        f"En este vídeo{f' sobre {topic}' if topic else ''} repasamos "
        f"{', '.join(palabras[:5]) or 'el tema de hoy'}."
        f"{bloque_capitulos}\n\n"
        f"👉 Suscríbete para no perderte los próximos.\n\n"
        + " ".join(f"#{tag}" for tag in hashtags)
    ).strip()

    return {
        "titles": [t for t in dict.fromkeys(titulos) if t],
        "description": descripcion,
        "tags": etiquetas,
        "hashtags": hashtags,
        "chapters": capitulos,
        "thumbnail_texts": [
            " ".join(word.upper() for word in palabras[:2]) or base.upper()[:22]
        ],
        "generated_by": "local",
    }


# --------------------------------------------------------------------------
# Generación con IA
# --------------------------------------------------------------------------
SYSTEM = (
    "Eres un estratega de YouTube con años de experiencia optimizando vídeos para "
    "búsqueda y recomendación. Escribes en español neutro, natural y directo. "
    "No exageras ni usas clickbait falso: el título siempre refleja el contenido real."
)

PROMPT = """Prepara la publicación de este vídeo de YouTube.

DATOS DEL VÍDEO
- Título provisional: {title}
- Duración: {duration}
- Tema del canal: {topic}
- Idioma: {language}

TRANSCRIPCIÓN (recortada)
{transcript}

MUESTRA CON TIEMPOS (para los capítulos)
{samples}

REGLAS
- 5 títulos distintos, de 45 a 60 caracteres, la palabra clave al principio,
  sin mayúsculas gritadas ni clickbait que el vídeo no cumpla.
- Descripción: las dos primeras líneas son el gancho (máx. 150 caracteres),
  luego 2-3 párrafos cortos y una llamada a la acción. Sin los capítulos: van aparte.
- Capítulos: entre 4 y 10, el primero SIEMPRE en 0 segundos, separados 30 s como
  mínimo, títulos de 2 a 5 palabras. Usa los tiempos de la muestra.
- 12 etiquetas, de lo más concreto a lo más general, en minúsculas.
- 3 hashtags como máximo, sin la almohadilla, en minúsculas y sin espacios.
- 3 textos de miniatura de 2 a 4 palabras, en MAYÚSCULAS, muy legibles.
- Un prompt en inglés para generar la imagen de una miniatura llamativa
  (estilo fotográfico, alto contraste, sin texto en la imagen).

Devuelve este JSON exacto:
{{
  "titles": ["..."],
  "description": "...",
  "chapters": [{{"time": 0, "title": "..."}}],
  "tags": ["..."],
  "hashtags": ["..."],
  "thumbnail_texts": ["..."],
  "thumbnail_prompt": "...",
  "notes": "un consejo breve para este vídeo"
}}"""


def _clean_chapters(raw: Any, duration: float) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        time_value = item.get("time", item.get("start", 0))
        if isinstance(time_value, str):  # a veces devuelven "1:23"
            parts = [int(p) for p in re.findall(r"\d+", time_value)] or [0]
            seconds = 0
            for part in parts:
                seconds = seconds * 60 + part
            time_value = seconds
        try:
            time_value = int(float(time_value))
        except (TypeError, ValueError):
            continue
        title = str(item.get("title") or item.get("titulo") or "").strip()
        if not title or time_value < 0 or (duration and time_value > duration):
            continue
        chapters.append({"time": time_value, "title": title[:90]})

    chapters.sort(key=lambda c: c["time"])
    if not chapters:
        return []
    chapters[0]["time"] = 0
    limpio = [chapters[0]]
    for chapter in chapters[1:]:
        if chapter["time"] - limpio[-1]["time"] >= 10:
            limpio.append(chapter)
    return limpio if len(limpio) >= 3 else []


def build_ai_kit(
    *,
    title: str,
    transcript: dict[str, Any],
    duration: float,
    topic: str = "",
    language: str = "es",
) -> dict[str, Any]:
    """Kit generado con el proveedor de IA configurado."""
    samples = sample_for_chapters(transcript)
    prompt = PROMPT.format(
        title=title or "(sin título)",
        duration=timestamp(duration),
        topic=topic or "(sin especificar)",
        language=language,
        transcript=transcript_text(transcript, 7000) or "(sin transcripción disponible)",
        samples="\n".join(f"[{timestamp(s['t'])}] {s['texto']}" for s in samples) or "(no hay)",
    )

    data = ai.chat_json(prompt, system=SYSTEM, temperature=0.75, max_tokens=2400)
    if not isinstance(data, dict):
        raise ai.AIError("La respuesta no tiene el formato esperado.")

    titles = [str(t).strip()[:MAX_TITLE] for t in (data.get("titles") or []) if str(t).strip()]
    tags = [str(t).strip().lower()[:40] for t in (data.get("tags") or []) if str(t).strip()][:15]
    hashtags = [
        slugify_tag(str(h)) for h in (data.get("hashtags") or []) if slugify_tag(str(h))
    ][:3]
    chapters = _clean_chapters(data.get("chapters"), duration)

    description = str(data.get("description") or "").strip()
    if chapters:
        description += "\n\n⏱️ Capítulos\n" + "\n".join(
            f"{timestamp(c['time'])} {c['title']}" for c in chapters
        )
    if hashtags:
        description += "\n\n" + " ".join(f"#{tag}" for tag in hashtags)

    return {
        "titles": titles or [title[:MAX_TITLE]],
        "description": description.strip(),
        "tags": tags,
        "hashtags": hashtags,
        "chapters": chapters,
        "thumbnail_texts": [
            str(t).strip().upper()[:26]
            for t in (data.get("thumbnail_texts") or [])
            if str(t).strip()
        ][:3],
        "thumbnail_prompt": str(data.get("thumbnail_prompt") or "").strip()[:600],
        "notes": str(data.get("notes") or "").strip()[:400],
        "generated_by": f"ia:{ai.last_used()}",
    }


def build_kit(
    *,
    title: str,
    transcript: dict[str, Any],
    duration: float,
    topic: str = "",
    language: str = "es",
    use_ai: bool = True,
) -> dict[str, Any]:
    """Punto de entrada: intenta con IA y, si no puede, genera en local."""
    if use_ai and ai.is_enabled():
        try:
            kit = build_ai_kit(
                title=title,
                transcript=transcript,
                duration=duration,
                topic=topic,
                language=language,
            )
            kit["warning"] = ""
            return kit
        except Exception as exc:  # la IA nunca debe dejarte sin kit
            fallback = build_basic_kit(
                title=title, transcript=transcript, duration=duration, topic=topic
            )
            fallback["warning"] = f"La IA no ha respondido ({exc}). Kit generado en local."
            return fallback

    kit = build_basic_kit(title=title, transcript=transcript, duration=duration, topic=topic)
    kit["warning"] = "" if not use_ai else "Sin IA configurada: kit generado en local."
    return kit


# --------------------------------------------------------------------------
# Revisión de calidad (buenas prácticas)
# --------------------------------------------------------------------------
def review_kit(kit: dict[str, Any], duration: float = 0) -> list[dict[str, str]]:
    """Lista de avisos sobre lo que se puede mejorar antes de publicar."""
    checks: list[dict[str, str]] = []

    titles = kit.get("titles") or []
    if titles:
        length = len(titles[0])
        if length > IDEAL_TITLE:
            checks.append({
                "level": "warn",
                "text": f"El título elegido tiene {length} caracteres; por encima de "
                        f"{IDEAL_TITLE} se corta en el móvil.",
            })
        else:
            checks.append({"level": "ok", "text": f"Título de {length} caracteres: buena longitud."})
    else:
        checks.append({"level": "bad", "text": "No hay ningún título."})

    description = kit.get("description") or ""
    primeras = description[:150]
    if len(description) < 200:
        checks.append({
            "level": "warn",
            "text": "La descripción es muy corta; ayuda a posicionar tener 300 caracteres o más.",
        })
    elif primeras.strip():
        checks.append({"level": "ok", "text": "Las dos primeras líneas hacen de gancho."})

    chapters = kit.get("chapters") or []
    if duration >= 180:
        if len(chapters) >= 3 and chapters[0].get("time") == 0:
            checks.append({"level": "ok", "text": f"{len(chapters)} capítulos válidos."})
        else:
            checks.append({
                "level": "warn",
                "text": "Faltan capítulos: YouTube los activa con 3 o más empezando en 00:00.",
            })

    tags = kit.get("tags") or []
    if len(tags) < 8:
        checks.append({"level": "warn", "text": f"Sólo {len(tags)} etiquetas; apunta a 10-15."})
    else:
        checks.append({"level": "ok", "text": f"{len(tags)} etiquetas."})

    hashtags = kit.get("hashtags") or []
    if len(hashtags) > 3:
        checks.append({"level": "warn", "text": "Más de 3 hashtags: YouTube los ignora todos."})
    elif hashtags:
        checks.append({"level": "ok", "text": f"{len(hashtags)} hashtags."})

    if not kit.get("thumbnails"):
        checks.append({"level": "warn", "text": "Todavía no hay miniaturas generadas."})
    else:
        checks.append({
            "level": "ok",
            "text": f"{len(kit['thumbnails'])} miniaturas listas para elegir.",
        })

    return checks
