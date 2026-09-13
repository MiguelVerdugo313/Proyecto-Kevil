"""Recomendaciones de contenido: sobre qué juego o tema grabar el próximo vídeo.

La IA propone; los datos deciden. Cada propuesta se busca en YouTube y se mide:

* **Demanda**: la mediana de visitas de los vídeos que salen al buscar el tema.
  Si nadie los ve, da igual lo bien que suene la idea.
* **Competencia**: cuánta gente grande lo está cubriendo ya.
* **Encaje**: cuánto se parece a lo que tú ya haces (tu canal ya tiene una
  audiencia; irse muy lejos suele salir mal).

La nota final combina las tres. Sin clave de IA el motor sigue funcionando:
propone a partir de tus propios vídeos que mejor han rendido.
"""

from __future__ import annotations

import re
import statistics
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Idea, Video
from app.services import ai
from app.services import youtube as youtube_service
from app.services.seo import keywords

SYSTEM = (
    "Eres un asesor de creadores de YouTube. Conoces el mercado de contenido de "
    "videojuegos y entretenimiento, y propones ideas concretas y grabables, "
    "nunca genéricas. Escribes en español neutro."
)

PROMPT = """Propón {count} ideas de vídeo para este canal de YouTube.

SOBRE EL CANAL
- Tema declarado: {topic}
- Vídeos recientes:
{recent}
- Los que mejor han funcionado:
{best}
- Palabras que más aparecen en su contenido: {keywords}

REGLAS
- Cada idea debe ser un vídeo concreto y grabable, no una categoría.
- Si el canal es de videojuegos, propón juegos concretos (mezcla: alguno que ya
  toca, alguno cercano en auge y como mucho uno arriesgado).
- El campo "topic" es lo que se buscaría en YouTube para ver si hay demanda:
  2 a 5 palabras, sin adornos (por ejemplo "minecraft granja automatica").
- El título debe tener entre 45 y 60 caracteres, sin clickbait falso.
- Explica en "reason" por qué encaja con ESTE canal en una frase.

Devuelve este JSON:
{{"ideas": [
  {{"topic": "...", "title": "...", "hook": "...", "angle": "...",
    "reason": "...", "tags": ["..."]}}
]}}"""


# --------------------------------------------------------------------------
# Contexto del canal
# --------------------------------------------------------------------------
def channel_context(session: Session, limit: int = 25) -> dict[str, Any]:
    videos = list(
        session.scalars(
            select(Video)
            .where(Video.origin == "youtube")
            .order_by(Video.published_at.desc().nullslast())
            .limit(limit)
        ).all()
    )
    mejores = sorted(videos, key=lambda v: v.views or 0, reverse=True)[:8]
    texto = " ".join(v.title for v in videos)
    return {
        "recent": [v.title for v in videos[:12]],
        "best": [{"title": v.title, "views": v.views} for v in mejores if v.views],
        "keywords": keywords(texto, limit=15),
        "count": len(videos),
    }


# --------------------------------------------------------------------------
# Medición con datos reales
# --------------------------------------------------------------------------
def measure_topic(topic: str, *, limit: int = 12) -> dict[str, Any]:
    """Busca el tema en YouTube y estima demanda y competencia."""
    try:
        resultados = youtube_service.search_videos(topic, limit=limit)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "results": 0}

    visitas = [r["views"] for r in resultados if r["views"] > 0]
    if not visitas:
        return {"ok": False, "error": "sin resultados con visitas", "results": len(resultados)}

    mediana = statistics.median(visitas)
    maximo = max(visitas)
    # Demanda: escala logarítmica, 100.000 visitas de mediana ya es mucho
    demanda = min(1.0, (len(str(int(mediana))) - 2) / 5) if mediana > 100 else 0.05
    # Competencia: cuántos superan holgadamente a la mediana (canales grandes)
    grandes = len([v for v in visitas if v > mediana * 6])
    competencia = min(1.0, grandes / max(1, len(visitas)) * 2)

    return {
        "ok": True,
        "results": len(resultados),
        "median_views": int(mediana),
        "max_views": int(maximo),
        "demand": round(demanda, 3),
        "competition": round(competencia, 3),
        "examples": [
            {"title": r["title"][:110], "channel": r["channel"], "views": r["views"]}
            for r in sorted(resultados, key=lambda r: r["views"], reverse=True)[:3]
        ],
    }


def _fit(topic: str, palabras: list[str]) -> float:
    """Cuánto se parece el tema a lo que ya hace el canal (0..1)."""
    if not palabras:
        return 0.5
    tokens = set(re.findall(r"[a-záéíóúñ]{4,}", topic.lower()))
    comunes = tokens & set(palabras)
    return min(1.0, 0.35 + len(comunes) * 0.25)


def score_idea(measure: dict[str, Any], fit: float) -> float:
    if not measure.get("ok"):
        return round(0.35 * fit, 3)
    demanda = measure["demand"]
    competencia = measure["competition"]
    return round(
        max(0.0, min(1.0, demanda * 0.5 + (1 - competencia) * 0.25 + fit * 0.25)), 3
    )


# --------------------------------------------------------------------------
# Generación
# --------------------------------------------------------------------------
def _ai_candidates(context: dict[str, Any], count: int) -> list[dict[str, Any]]:
    prompt = PROMPT.format(
        count=count,
        topic=settings.channel_topic or "(no especificado)",
        recent="\n".join(f"  - {t}" for t in context["recent"]) or "  (ninguno)",
        best="\n".join(
            f"  - {b['title']} ({b['views']} visitas)" for b in context["best"]
        )
        or "  (sin datos de visitas)",
        keywords=", ".join(context["keywords"]) or "(sin datos)",
    )
    data = ai.chat_json(prompt, system=SYSTEM, temperature=0.9, max_tokens=2600)
    ideas = data.get("ideas") if isinstance(data, dict) else data
    return [idea for idea in (ideas or []) if isinstance(idea, dict)]


def _local_candidates(context: dict[str, Any], count: int) -> list[dict[str, Any]]:
    """Sin IA: se parte de lo que ya te funciona y se buscan variantes."""
    candidatos: list[dict[str, Any]] = []
    base = [b["title"] for b in context["best"]] or context["recent"]
    palabras = context["keywords"][:6]

    plantillas = [
        ("{k} trucos", "Trucos de {k} que casi nadie usa", "Recopila los que tú ya dominas."),
        ("{k} guia", "Guía de {k} para empezar de cero", "Contenido evergreen: se ve durante meses."),
        ("{k} errores", "5 errores con {k} que te frenan", "El formato de errores retiene muy bien."),
        ("{k} novedades", "Todo lo nuevo de {k}", "Aprovecha el pico de búsquedas de cada novedad."),
    ]
    for palabra in palabras:
        for topic_tpl, title_tpl, angle in plantillas:
            if len(candidatos) >= count:
                break
            candidatos.append(
                {
                    "topic": topic_tpl.format(k=palabra),
                    "title": title_tpl.format(k=palabra.capitalize())[:60],
                    "hook": f"Lo que deberías saber sobre {palabra}.",
                    "angle": angle,
                    "reason": "Sale de las palabras que más aparecen en tus propios vídeos.",
                    "tags": [palabra],
                }
            )
    if not candidatos and base:
        candidatos.append(
            {
                "topic": base[0][:60],
                "title": f"{base[0][:50]} (parte 2)",
                "hook": "Segunda parte de lo que mejor te ha funcionado.",
                "angle": "Repetir el formato que ya te dio resultado.",
                "reason": "Tu vídeo con más visitas hasta ahora.",
                "tags": [],
            }
        )
    return candidatos[:count]


def generate(
    session: Session, *, count: int = 6, validate: bool = True, on_progress=None
) -> list[Idea]:
    """Genera ideas, las valida con datos de YouTube y las guarda."""
    context = channel_context(session)
    usando_ia = ai.is_enabled()

    if usando_ia:
        try:
            candidatos = _ai_candidates(context, count)
            origen = "ia"
        except Exception:
            candidatos = _local_candidates(context, count)
            origen = "canal"
    else:
        candidatos = _local_candidates(context, count)
        origen = "canal"

    creadas: list[Idea] = []
    for index, candidato in enumerate(candidatos[:count]):
        topic = str(candidato.get("topic") or "").strip()[:200]
        if not topic:
            continue

        medida: dict[str, Any] = {"ok": False}
        if validate:
            medida = measure_topic(topic)

        encaje = _fit(topic, context["keywords"])
        nota = score_idea(medida, encaje)

        idea = Idea(
            topic=topic,
            title=str(candidato.get("title") or topic)[:300],
            hook=str(candidato.get("hook") or "")[:600],
            angle=str(candidato.get("angle") or "")[:600],
            reason=str(candidato.get("reason") or "")[:600],
            tags=[str(t)[:40] for t in (candidato.get("tags") or [])][:8],
            score=nota,
            demand=float(medida.get("demand") or 0),
            competition=float(medida.get("competition") or 0),
            evidence={**medida, "fit": round(encaje, 3)},
            source=origen,
        )
        session.add(idea)
        creadas.append(idea)
        if on_progress:
            on_progress(0.2 + 0.8 * (index + 1) / max(1, len(candidatos)))

    session.flush()
    creadas.sort(key=lambda i: i.score, reverse=True)
    return creadas
