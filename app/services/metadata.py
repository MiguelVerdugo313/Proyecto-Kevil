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
    return re.sub(r"\{[a-z_]+\}", "", result).strip()


def build_metadata(
    *,
    config: dict[str, Any],
    video_title: str,
    channel: str,
    hook: str,
    text: str,
    index: int,
    total: int,
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

    variables = {
        "titulo": video_title,
        "hook": hook or video_title,
        "n": index,
        "total": total,
        "canal": channel,
        "hashtags": hashtag_text,
    }

    title = render_template(config.get("title_template", "{titulo} · parte {n}"), variables)
    caption = render_template(config.get("caption_template", "{hook}\n\n{hashtags}"), variables)

    max_chars = int(config.get("max_caption_chars", 2100) or 2100)
    if len(caption) > max_chars:
        caption = caption[: max_chars - 1].rstrip() + "…"

    return {
        "title": title[:300] or video_title[:300],
        "caption": caption,
        "hashtags": tags,
    }
