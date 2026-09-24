"""Generación del título, la descripción y los hashtags de cada clip."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

STOPWORDS = {
    "que", "de", "la", "el", "y", "a", "en", "un", "una", "es", "por", "con", "no",
    "para", "los", "las", "se", "del", "al", "lo", "como", "más", "pero", "sus",
    "le", "ya", "o", "porque", "cuando", "muy", "sin", "sobre", "también", "me",
    "hasta", "hay", "donde", "quien", "desde", "todo", "nos", "durante", "todos",
    "uno", "les", "ni", "contra", "otros", "este", "eso", "ante", "ellos", "e",
    "esto", "mí", "antes", "algunos", "qué", "unos", "yo", "otro", "otras", "otra",
    "él", "tanto", "esa", "estos", "mucho", "quienes", "nada", "muchos", "cual",
    "sea", "poco", "ella", "estar", "haber", "estas", "estaba", "estamos", "algunas",
    "algo", "nosotros", "mi", "mis", "tú", "te", "ti", "tu", "tus", "ellas", "nosotras",
    "vosotros", "vosotras", "os", "mío", "mía", "the", "and", "for", "you", "with",
    "this", "that", "are", "was", "have", "has", "not", "but", "your", "from", "they",
    "vamos", "entonces", "bueno", "claro", "aquí", "ahora", "bien", "puede", "hacer",
    "va", "ver", "dos", "así", "cosa", "cosas", "gente", "vez", "años", "solo",
}


def slugify_tag(text: str) -> str:
    text = text.lower().strip()
    for source, target in zip("áéíóúüñ", "aeiouun"):
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def suggest_hashtags(text: str, limit: int = 4) -> list[str]:
    words = re.findall(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]{4,}", (text or "").lower())
    counter = Counter(w for w in words if w not in STOPWORDS)
    tags: list[str] = []
    for word, _count in counter.most_common(limit * 3):
        tag = slugify_tag(word)
        if len(tag) >= 4 and tag not in tags:
            tags.append(tag)
        if len(tags) >= limit:
            break
    return tags


def render_template(template: str, variables: dict[str, Any]) -> str:
    result = template or ""
    for key, value in variables.items():
        result = result.replace("{" + key + "}", str(value))
    result = re.sub(r"\{[a-z_]+\}", "", result)
    # una variable vacía no deja líneas en blanco de más ni separadores colgando
    lineas = [re.sub(r"^[\s·|\-–]+|[\s·|\-–]+$", "", linea) for linea in result.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


TITULO_MAX = 80          # que quepa «… · Parte 12 #Shorts» en los 100 de YouTube


def acortar(texto: str, largo: int = TITULO_MAX) -> str:
    texto = (texto or "").strip()
    if len(texto) <= largo:
        return texto
    return texto[: largo - 1].rsplit(" ", 1)[0].rstrip(" ,.;:·|-") + "…"


def build_metadata(
    *,
    config: dict[str, Any],
    video_title: str,
    channel: str,
    hook: str,
    text: str,
    index: int,
    total: int,
    entero: bool | None = None,
) -> dict[str, Any]:
    fixed = [slugify_tag(t) for t in (config.get("hashtags") or []) if slugify_tag(t)]
    tags = list(dict.fromkeys(fixed))

    if config.get("auto_hashtags", True):
        for tag in suggest_hashtags(f"{video_title} {text}", limit=4):
            if tag not in tags:
                tags.append(tag)

    max_tags = int(config.get("max_hashtags", 6) or 0)
    tags = tags[:max_tags] if max_tags else []
    hashtag_text = " ".join(f"#{tag}" for tag in tags)

    titulo = acortar(video_title)
    # el gancho sólo si dice algo más que el título del vídeo
    gancho = (hook or "").strip()
    if gancho.lower() == (video_title or "").strip().lower():
        gancho = ""
    variables = {
        "titulo": titulo,
        "hook": gancho,
        "n": index,
        "total": total,
        "canal": channel,
        "hashtags": hashtag_text,
    }

    plantilla_titulo = config.get("title_template", "{titulo} · Parte {n}")
    plantilla_texto = config.get("caption_template", "{titulo} · Parte {n}\n{hook}\n\n{hashtags}")
    if entero if entero is not None else total <= 1:
        # un vídeo que sale entero no es «Parte 1»
        for resto in (" · Parte {n}", " · parte {n}", "Parte {n} · ", "parte {n} · "):
            plantilla_titulo = plantilla_titulo.replace(resto, "")
            plantilla_texto = plantilla_texto.replace(resto, "")
    title = render_template(plantilla_titulo, variables)
    caption = render_template(plantilla_texto, variables)

    max_chars = int(config.get("max_caption_chars", 2100) or 2100)
    if len(caption) > max_chars:
        caption = caption[: max_chars - 1].rstrip() + "…"

    return {
        "title": title[:300] or titulo[:300],
        "caption": caption,
        "hashtags": tags,
    }
