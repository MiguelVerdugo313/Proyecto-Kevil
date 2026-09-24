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


def _frase_principal(contexto: str, largo: int = 60) -> str:
    """La primera idea de lo que cuentas, lista para servir de título."""
    frase = re.split(r"[.\n!?]", (contexto or "").strip(), maxsplit=1)[0].strip(" ,;:")
    frase = re.sub(r"^(?:b[aá]sicamente|pues|bueno|es un|es una|este v[ií]deo es)\s+", "",
                   frase, flags=re.IGNORECASE)
    if len(frase) > largo:
        frase = frase[:largo].rsplit(" ", 1)[0].rstrip(" ,;:")
    return frase[:1].upper() + frase[1:] if frase else ""


def build_basic_kit(
    *,
    title: str,
    transcript: dict[str, Any],
    duration: float,
    topic: str = "",
    contexto: str = "",
    terminos: list[str] | None = None,
) -> dict[str, Any]:
    """Kit sin IA: sólo con lo que se sabe del vídeo, sin adornos inventados.

    Nada de «guía completa» ni «lo que nadie te cuenta»: si es un gameplay, el
    título dice qué juego es y ya.
    """
    from app.services import fidelidad

    texto = transcript_text(transcript, 6000)
    terminos = list(terminos or [])
    nombres = fidelidad.nombres_propios(f"{contexto} {title}")
    principal = _frase_principal(contexto)
    base = title.strip()
    es_gameplay = "gameplay" in fidelidad.sin_tildes(contexto)
    extra = " (Gameplay)" if es_gameplay else ""

    titulos: list[str] = []
    if len(nombres) >= 2:
        titulos.append(f"{nombres[0]} | {nombres[1]}{extra}")
        titulos.append(f"{nombres[1]} en {nombres[0]}")
    elif nombres:
        titulos.append(f"{nombres[0]}{extra}")
    if principal:
        # la frase entera sólo si cabe sin cortarse a media idea
        corta = principal if len(principal) <= 55 else principal.split(",")[0]
        titulos.append(corta)
    if base:
        titulos.append(base)
    if not titulos:
        palabras_titulo = keywords(texto, limit=1)
        titulos = [palabras_titulo[0].capitalize() if palabras_titulo else "Vídeo nuevo"]

    gancho = (contexto or "").strip()
    if not gancho:
        for segment in transcript.get("segments") or []:
            if len(segment.get("text", "")) > 40:
                gancho = segment["text"].strip()
                break
    gancho = gancho or base

    capitulos = _basic_chapters(transcript, duration) if texto else []
    bloque_capitulos = ""
    if capitulos:
        bloque_capitulos = "\n\n⏱️ Capítulos\n" + "\n".join(
            f"{timestamp(c['time'])} {c['title']}" for c in capitulos
        )

    # etiquetas: los nombres enteros primero, sin repetirlos palabra a palabra
    compuestos = " ".join(fidelidad.sin_tildes(n) for n in terminos + nombres)
    palabras = [
        w for w in keywords(f"{contexto} {title} {texto}", limit=20)
        if len(w) >= 4
        and fidelidad.sin_tildes(w) not in fidelidad.MULETILLAS
        and fidelidad.sin_tildes(w) not in compuestos
    ]
    etiquetas = list(dict.fromkeys(
        [t.lower() for t in nombres] + [t.lower() for t in terminos
                                        if fidelidad.sin_tildes(t) not in fidelidad.MULETILLAS]
        + palabras
        + (["gameplay"] if es_gameplay else [])
    ))[:15]
    hashtags = [slugify_tag(t) for t in (nombres or terminos or palabras)[:3] if slugify_tag(t)]
    if es_gameplay and len(hashtags) < 3:
        hashtags.append("gameplay")

    linea_juego = f"\n\n🎮 {' · '.join(nombres[:3])}" if nombres else ""
    descripcion = (
        f"{gancho[:400]}{linea_juego}"
        f"{bloque_capitulos}\n\n"
        f"👉 Suscríbete para no perderte los próximos.\n\n"
        + " ".join(f"#{tag}" for tag in dict.fromkeys(hashtags))
    ).strip()

    textos_miniatura = [n.upper()[:26] for n in nombres[:2]] or (
        [" ".join((principal or base).split()[:3]).upper()[:26]] if (principal or base) else []
    )
    texto_miniatura = textos_miniatura[0] if textos_miniatura else ""
    return {
        "titles": [t[:MAX_TITLE] for t in dict.fromkeys(titulos) if t],
        "description": descripcion,
        "tags": etiquetas,
        "hashtags": hashtags,
        "chapters": capitulos,
        "thumbnail_texts": textos_miniatura,
        "thumbnail_prompt": prompt_de_miniatura(contexto or base, texto_miniatura, topic),
        "generated_by": "local",
    }


def prompt_de_miniatura(de_que_va: str, texto: str = "", topic: str = "") -> str:
    """Un prompt para crear la miniatura en cualquier IA de imágenes.

    Sirve cuando no hay generador de imágenes configurado o cuando las
    miniaturas de fotograma no convencen: se copia y se pega en ChatGPT,
    Gemini, Ideogram, Leonardo…
    """
    de_que_va = (de_que_va or "").strip().rstrip(".") or "a gaming video"
    extra = f" Channel style: {topic}." if topic else ""
    rotulo = (
        f' Leave clear space on the left third for the big bold title text "{texto.upper()}".'
        if texto else " Leave clear space on the left third for a big bold title."
    )
    return (
        "YouTube thumbnail, 16:9, 1280x720. Subject: "
        f"{de_que_va}.{extra} Use the real characters and art style of that game, "
        "one clear focal point, expressive reaction, high contrast, saturated colors, "
        f"dramatic rim lighting, clean background, no watermark.{rotulo}"
    )


# --------------------------------------------------------------------------
# Generación con IA
# --------------------------------------------------------------------------
SYSTEM = (
    "Eres un estratega de YouTube con años de experiencia optimizando vídeos para "
    "búsqueda y recomendación. Escribes en español neutro, natural y directo. "
    "No exageras ni usas clickbait falso: el título siempre refleja el contenido real. "
    "Nunca inventas de qué va un vídeo: si un dato no está en lo que te pasan, no lo pones."
)

PROMPT = """Prepara la publicación de este vídeo de YouTube.

DE QUÉ VA EL VÍDEO, CONTADO POR EL CREADOR (es la fuente principal: manda sobre todo lo demás)
{contexto}

DATOS DEL VÍDEO
- Título provisional: {title}
- Duración: {duration}
- Tema del canal: {topic}
- Idioma: {language}
- Otros vídeos del canal (sólo para imitar el estilo; NO son este vídeo): {canal}

TRANSCRIPCIÓN (recortada)
{transcript}

MUESTRA CON TIEMPOS (para los capítulos)
{samples}

REGLAS DE VERDAD (las más importantes)
- Escribe SOLO sobre lo que dicen el creador, el título y la transcripción. No
  inventes el tema, el juego, el formato ni lo que pasa en el vídeo.
- Si es un gameplay o un directo jugando, es eso: no lo conviertas en tutorial,
  guía, curso, consejos ni «aprende a…» salvo que el creador lo diga.
- Nombra el juego, el mod o la actualización tal y como los escribe el creador.
- Si falta información, sé breve y concreto con lo que sí se sabe; nunca rellenes
  con suposiciones.{obligatorio}

REGLAS DE FORMATO
- 5 títulos distintos, de 45 a 60 caracteres, la palabra clave al principio,
  sin mayúsculas gritadas ni clickbait que el vídeo no cumpla.
- Descripción: las dos primeras líneas son el gancho (máx. 150 caracteres),
  luego 2-3 párrafos cortos y una llamada a la acción. Sin los capítulos: van aparte.
- Capítulos: entre 4 y 10, el primero SIEMPRE en 0 segundos, separados 30 s como
  mínimo, títulos de 2 a 5 palabras. Usa los tiempos de la muestra.
- 12 etiquetas, de lo más concreto a lo más general, en minúsculas.
- 3 hashtags como máximo, sin la almohadilla, en minúsculas y sin espacios.
- 3 textos de miniatura de 2 a 4 palabras, en MAYÚSCULAS, muy legibles.
- Un prompt en inglés para generar la imagen de una miniatura llamativa del
  juego o de lo que pasa en el vídeo (alto contraste, sin texto en la imagen).
- Capítulos: si no hay transcripción, devuelve una lista vacía.

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
    contexto: str = "",
    canal: list[str] | None = None,
    obligatorio: list[str] | None = None,
) -> dict[str, Any]:
    """Kit generado con el proveedor de IA configurado."""
    samples = sample_for_chapters(transcript)
    prompt = PROMPT.format(
        contexto=contexto or "(no lo ha contado: usa sólo el título y la transcripción)",
        title=title or "(sin título: es el nombre de un archivo)",
        duration=timestamp(duration),
        topic=topic or "(sin especificar)",
        language=language,
        canal="; ".join(canal or []) or "(no hay)",
        transcript=transcript_text(transcript, 7000)
        or "(el vídeo no tiene voz útil: no hay transcripción; no supongas lo que se dice)",
        samples="\n".join(f"[{timestamp(s['t'])}] {s['texto']}" for s in samples) or "(no hay)",
        obligatorio=(
            "\n- La vez anterior te saliste del tema. Cada título DEBE nombrar al menos "
            f"uno de estos: {', '.join(obligatorio)}."
            if obligatorio else ""
        ),
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
    contexto: str = "",
    canal: list[str] | None = None,
    forzar: bool = False,
) -> dict[str, Any]:
    """Punto de entrada: decide con qué se escribe y comprueba que no se invente.

    * Si no sabe de qué va el vídeo (no lo has contado y no hay voz), no
      escribe nada: devuelve `falta_contexto` para que la app te pregunte.
      Con `forzar` se escribe igual, sólo con el título.
    * Con IA, si el resultado se sale del tema se repite una vez exigiendo
      que nombre lo que dijiste; si vuelve a salirse, se usa el kit local.
    """
    from app.services import fidelidad

    datos = fidelidad.fuentes(
        titulo=title, contexto=contexto, transcript=transcript, duracion=duration
    )
    if datos["falta_contexto"] and not forzar:
        return {
            "falta_contexto": True,
            "motivo": datos["motivo_transcripcion"],
            "titles": [],
            "generated_by": "pendiente",
            "warning": "",
        }

    texto_util = datos["transcript"]
    aviso_voz = (
        f"Sin transcripción útil ({datos['motivo_transcripcion']}): se ha usado lo que contaste."
        if not datos["transcripcion_util"] and contexto else ""
    )

    def local(motivo: str) -> dict[str, Any]:
        kit = build_basic_kit(
            title=datos["titulo"], transcript=texto_util, duration=duration,
            topic=topic, contexto=contexto, terminos=datos["terminos"],
        )
        kit["warning"] = " ".join(p for p in (motivo, aviso_voz) if p)
        return kit

    if not (use_ai and ai.is_enabled()):
        return local("" if not use_ai else "Sin IA configurada: kit generado en local.")

    obligatorio: list[str] | None = None
    for _intento in range(2):
        try:
            kit = build_ai_kit(
                title=datos["titulo"], transcript=texto_util, duration=duration,
                topic=topic, language=language, contexto=contexto, canal=canal,
                obligatorio=obligatorio,
            )
        except Exception as exc:  # la IA nunca debe dejarte sin kit
            return local(f"La IA no ha respondido ({exc}). Kit generado en local.")
        fuera = fidelidad.se_sale_del_tema(kit, datos)
        if not fuera:
            kit["warning"] = aviso_voz
            if not kit.get("thumbnail_prompt"):
                kit["thumbnail_prompt"] = prompt_de_miniatura(
                    contexto or title, (kit.get("thumbnail_texts") or [""])[0], topic
                )
            return kit
        obligatorio = [t for t in datos["terminos"] if len(t) >= 3][:4] or None
    return local(f"La IA se salía del tema ({fuera}); se ha hecho con lo que contaste.")


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
