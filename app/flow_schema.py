"""Esquema declarativo de los flujos editables.

La interfaz web construye los formularios automáticamente a partir de esta
definición, así que añadir una opción nueva aquí la hace editable en la
pantalla «Flujos» sin tocar el front-end.

Cada paso es:
    {"type": "segment", "enabled": true, "config": {...}}
"""

from __future__ import annotations

import copy
from typing import Any

# --------------------------------------------------------------------------
# Definición de los pasos disponibles
# --------------------------------------------------------------------------
STEP_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "ingest",
        "label": "Descarga del original",
        "icon": "⬇️",
        "description": "Baja el vídeo o el directo de YouTube a tu disco.",
        "locked": True,  # no se puede desactivar
        "fields": [
            {
                "key": "quality",
                "label": "Calidad máxima",
                "type": "select",
                "default": "1080",
                "options": [
                    {"value": "2160", "label": "4K (2160p)"},
                    {"value": "1440", "label": "2K (1440p)"},
                    {"value": "1080", "label": "Full HD (1080p)"},
                    {"value": "720", "label": "HD (720p)"},
                ],
                "help": "1080p es suficiente para TikTok y ocupa mucho menos.",
            },
            {
                "key": "download_subtitles",
                "label": "Bajar subtítulos de YouTube",
                "type": "bool",
                "default": True,
                "help": "Se usan para elegir los mejores momentos y para los rótulos.",
            },
            {
                "key": "subtitle_langs",
                "label": "Idiomas de subtítulos",
                "type": "tags",
                "default": ["es", "en"],
            },
            {
                "key": "keep_source",
                "label": "Conservar el original tras cortar",
                "type": "bool",
                "default": True,
                "help": "Desactívalo si andas justo de espacio en disco.",
            },
            {
                "key": "cookies_from_browser",
                "label": "Cookies del navegador",
                "type": "select",
                "default": "",
                "options": [
                    {"value": "", "label": "No usar"},
                    {"value": "chrome", "label": "Chrome"},
                    {"value": "edge", "label": "Edge"},
                    {"value": "firefox", "label": "Firefox"},
                    {"value": "brave", "label": "Brave"},
                    {"value": "safari", "label": "Safari"},
                ],
                "help": "Necesario sólo para vídeos privados o no listados.",
            },
        ],
    },
    {
        "type": "transcribe",
        "label": "Transcripción",
        "icon": "📝",
        "description": "Obtiene el texto con tiempos para cortar con criterio y poner rótulos.",
        "fields": [
            {
                "key": "engine",
                "label": "Motor",
                "type": "select",
                "default": "youtube",
                "options": [
                    {"value": "youtube", "label": "Subtítulos de YouTube (rápido)"},
                    {"value": "whisper", "label": "Whisper local (más preciso)"},
                    {"value": "youtube_then_whisper", "label": "YouTube y si falla, Whisper"},
                    {"value": "none", "label": "Sin transcripción"},
                ],
            },
            {
                "key": "language",
                "label": "Idioma",
                "type": "select",
                "default": "es",
                "options": [
                    {"value": "es", "label": "Español"},
                    {"value": "en", "label": "Inglés"},
                    {"value": "pt", "label": "Portugués"},
                    {"value": "auto", "label": "Detectar"},
                ],
            },
            {
                "key": "whisper_model",
                "label": "Modelo de Whisper",
                "type": "select",
                "default": "small",
                "options": [
                    {"value": "tiny", "label": "tiny (muy rápido)"},
                    {"value": "base", "label": "base"},
                    {"value": "small", "label": "small (recomendado)"},
                    {"value": "medium", "label": "medium (lento)"},
                ],
                "help": "Requiere instalar faster-whisper: pip install faster-whisper",
            },
        ],
    },
    {
        "type": "segment",
        "label": "Selección de momentos",
        "icon": "✂️",
        "description": "Decide por dónde cortar el vídeo largo o el directo.",
        "locked": True,
        "fields": [
            {
                "key": "strategy",
                "label": "Estrategia",
                "type": "select",
                "default": "smart",
                "options": [
                    {"value": "smart", "label": "Inteligente (texto + silencios)"},
                    {"value": "uniform", "label": "Trozos iguales"},
                    {"value": "silence", "label": "Por pausas del audio"},
                    {"value": "manual", "label": "Manual (los marco yo)"},
                    {
                        "value": "completo",
                        "label": "El vídeo entero (para Shorts que ya tienes)",
                    },
                ],
            },
            {
                "key": "min_duration",
                "label": "Duración mínima (s)",
                "type": "number",
                "default": 21,
                "min": 5,
                "max": 180,
            },
            {
                "key": "max_duration",
                "label": "Duración máxima (s)",
                "type": "number",
                "default": 59,
                "min": 10,
                "max": 600,
                "help": "Por debajo de 60 s el clip entra en el formato corto clásico.",
            },
            {
                "key": "clips_per_hour",
                "label": "Clips por hora de vídeo",
                "type": "number",
                "default": 8,
                "min": 1,
                "max": 60,
            },
            {
                "key": "max_clips",
                "label": "Máximo de clips por vídeo",
                "type": "number",
                "default": 12,
                "min": 1,
                "max": 100,
            },
            {
                "key": "min_gap",
                "label": "Separación mínima entre clips (s)",
                "type": "number",
                "default": 30,
                "min": 0,
                "max": 600,
            },
            {
                "key": "skip_intro",
                "label": "Saltar el principio (s)",
                "type": "number",
                "default": 30,
                "min": 0,
                "max": 1800,
                "help": "Muy útil en directos: se salta la espera inicial.",
            },
            {
                "key": "skip_outro",
                "label": "Saltar el final (s)",
                "type": "number",
                "default": 15,
                "min": 0,
                "max": 1800,
            },
            {
                "key": "pad_start",
                "label": "Margen antes (s)",
                "type": "number",
                "default": 0.4,
                "min": 0,
                "max": 5,
                "step": 0.1,
            },
            {
                "key": "pad_end",
                "label": "Margen después (s)",
                "type": "number",
                "default": 0.8,
                "min": 0,
                "max": 5,
                "step": 0.1,
            },
            {
                "key": "boost_keywords",
                "label": "Palabras que suman",
                "type": "tags",
                "default": [
                    "secreto", "error", "truco", "nunca", "siempre", "gratis",
                    "increíble", "cuidado", "consejo", "importante", "mira",
                ],
                "help": "Los momentos donde se dicen estas palabras puntúan más alto.",
            },
            {
                "key": "avoid_keywords",
                "label": "Palabras que restan",
                "type": "tags",
                "default": ["suscríbete", "patrocinado", "publicidad", "en un momento"],
            },
            {
                "key": "prefer_questions",
                "label": "Priorizar preguntas y ganchos",
                "type": "bool",
                "default": True,
            },
        ],
    },
    {
        "type": "reframe",
        "label": "Formato vertical",
        "icon": "📱",
        "description": "Convierte el 16:9 en 9:16 listo para TikTok.",
        "locked": True,
        "fields": [
            {
                "key": "mode",
                "label": "Modo de encuadre",
                "type": "select",
                "default": "blur",
                "options": [
                    {"value": "blur", "label": "Vídeo centrado con fondo desenfocado"},
                    {"value": "crop", "label": "Recorte a pantalla completa"},
                    {"value": "smart", "label": "Recorte con seguimiento de la acción"},
                    {"value": "split", "label": "Vídeo arriba + zoom abajo"},
                ],
            },
            {
                "key": "focus_x",
                "label": "Centro horizontal del recorte",
                "type": "slider",
                "default": 0.5,
                "min": 0,
                "max": 1,
                "step": 0.01,
                "help": "0 = izquierda, 1 = derecha. Sólo para modos de recorte.",
            },
            {
                "key": "zoom",
                "label": "Zoom",
                "type": "slider",
                "default": 1.0,
                "min": 1.0,
                "max": 1.8,
                "step": 0.05,
            },
            {
                "key": "resolution",
                "label": "Resolución",
                "type": "select",
                "default": "1080x1920",
                "options": [
                    {"value": "1080x1920", "label": "1080 x 1920 (recomendado)"},
                    {"value": "720x1280", "label": "720 x 1280 (más ligero)"},
                ],
            },
            {
                "key": "fps",
                "label": "Fotogramas por segundo",
                "type": "select",
                "default": "30",
                "options": [
                    {"value": "24", "label": "24"},
                    {"value": "30", "label": "30"},
                    {"value": "60", "label": "60"},
                ],
            },
            {
                "key": "background_blur",
                "label": "Intensidad del desenfoque",
                "type": "slider",
                "default": 22,
                "min": 0,
                "max": 50,
                "step": 1,
            },
        ],
    },
    {
        "type": "subtitles",
        "label": "Rótulos automáticos",
        "icon": "🔠",
        "description": "Subtítulos quemados en el vídeo, estilo TikTok.",
        "fields": [
            {
                "key": "style",
                "label": "Estilo",
                "type": "select",
                "default": "karaoke",
                "options": [
                    {"value": "karaoke", "label": "Karaoke (resalta la palabra)"},
                    {"value": "blocks", "label": "Bloques de frase"},
                    {"value": "word", "label": "Palabra a palabra"},
                ],
            },
            {
                "key": "font",
                "label": "Tipografía",
                "type": "select",
                "default": "DejaVu Sans",
                "options": [
                    {"value": "DejaVu Sans", "label": "DejaVu Sans"},
                    {"value": "Arial", "label": "Arial"},
                    {"value": "Impact", "label": "Impact"},
                    {"value": "Verdana", "label": "Verdana"},
                    {"value": "Montserrat", "label": "Montserrat"},
                ],
            },
            {
                "key": "font_size",
                "label": "Tamaño",
                "type": "number",
                "default": 64,
                "min": 24,
                "max": 140,
            },
            {
                "key": "primary_color",
                "label": "Color del texto",
                "type": "color",
                "default": "#FFFFFF",
            },
            {
                "key": "highlight_color",
                "label": "Color de la palabra activa",
                "type": "color",
                "default": "#28E7C5",
            },
            {
                "key": "outline",
                "label": "Grosor del borde",
                "type": "number",
                "default": 4,
                "min": 0,
                "max": 12,
            },
            {
                "key": "position_y",
                "label": "Altura en pantalla (%)",
                "type": "slider",
                "default": 72,
                "min": 20,
                "max": 92,
                "step": 1,
            },
            {
                "key": "uppercase",
                "label": "TODO EN MAYÚSCULAS",
                "type": "bool",
                "default": True,
            },
            {
                "key": "max_chars",
                "label": "Caracteres por línea",
                "type": "number",
                "default": 22,
                "min": 8,
                "max": 60,
            },
        ],
    },
    {
        "type": "overlays",
        "label": "Gancho y marca",
        "icon": "✨",
        "description": "Texto de gancho arriba, tu @ de marca y barra de progreso.",
        "fields": [
            {
                "key": "hook_enabled",
                "label": "Mostrar gancho",
                "type": "bool",
                "default": True,
            },
            {
                "key": "hook_template",
                "label": "Texto del gancho",
                "type": "text",
                "default": "{hook}",
                "help": "Variables: {hook} {titulo} {n} {total}",
            },
            {
                "key": "hook_seconds",
                "label": "Segundos visible",
                "type": "number",
                "default": 3,
                "min": 0,
                "max": 60,
            },
            {
                "key": "hook_font_size",
                "label": "Tamaño del gancho",
                "type": "number",
                "default": 58,
                "min": 20,
                "max": 140,
            },
            {
                "key": "hook_position_y",
                "label": "Altura del gancho (%)",
                "type": "slider",
                "default": 16,
                "min": 4,
                "max": 60,
                "step": 1,
            },
            {
                "key": "watermark",
                "label": "Marca de agua (@usuario)",
                "type": "text",
                "default": "",
            },
            {
                "key": "watermark_position",
                "label": "Posición de la marca",
                "type": "select",
                "default": "bottom",
                "options": [
                    {"value": "top", "label": "Arriba"},
                    {"value": "bottom", "label": "Abajo"},
                ],
            },
            {
                "key": "progress_bar",
                "label": "Barra de progreso",
                "type": "bool",
                "default": False,
            },
        ],
    },
    {
        "type": "audio",
        "label": "Audio",
        "icon": "🔊",
        "description": "Nivela el volumen para que suene igual que el resto de TikTok.",
        "fields": [
            {
                "key": "normalize",
                "label": "Normalizar volumen",
                "type": "bool",
                "default": True,
            },
            {
                "key": "target_lufs",
                "label": "Volumen objetivo (LUFS)",
                "type": "number",
                "default": -14,
                "min": -24,
                "max": -8,
            },
            {
                "key": "fade_in",
                "label": "Entrada suave (s)",
                "type": "number",
                "default": 0.15,
                "min": 0,
                "max": 3,
                "step": 0.05,
            },
            {
                "key": "fade_out",
                "label": "Salida suave (s)",
                "type": "number",
                "default": 0.3,
                "min": 0,
                "max": 3,
                "step": 0.05,
            },
        ],
    },
    {
        "type": "metadata",
        "label": "Título y descripción",
        "icon": "🏷️",
        "description": "Genera el texto de la publicación y los hashtags.",
        "fields": [
            {
                "key": "title_template",
                "label": "Título interno",
                "type": "text",
                "default": "{titulo} · parte {n}",
                "help": "Variables: {titulo} {hook} {n} {total} {canal}",
            },
            {
                "key": "caption_template",
                "label": "Descripción de TikTok",
                "type": "textarea",
                "default": "{hook}\n\n{hashtags}",
                "help": "Variables: {hook} {titulo} {n} {total} {canal} {hashtags}",
            },
            {
                "key": "hashtags",
                "label": "Hashtags fijos",
                "type": "tags",
                "default": ["fyp", "parati", "viral"],
            },
            {
                "key": "auto_hashtags",
                "label": "Añadir hashtags según el contenido",
                "type": "bool",
                "default": True,
            },
            {
                "key": "max_hashtags",
                "label": "Máximo de hashtags",
                "type": "number",
                "default": 6,
                "min": 0,
                "max": 20,
            },
            {
                "key": "max_caption_chars",
                "label": "Máximo de caracteres",
                "type": "number",
                "default": 2100,
                "min": 100,
                "max": 2200,
            },
        ],
    },
    {
        "type": "schedule",
        "label": "Programación",
        "icon": "🗓️",
        "description": "Reparte los clips en las mejores horas de cada cuenta.",
        "fields": [
            {
                "key": "auto_schedule",
                "label": "Programar automáticamente",
                "type": "bool",
                "default": True,
            },
            {
                "key": "max_per_day",
                "label": "Publicaciones por día",
                "type": "number",
                "default": 3,
                "min": 1,
                "max": 12,
            },
            {
                "key": "min_gap_hours",
                "label": "Horas mínimas entre publicaciones",
                "type": "number",
                "default": 3,
                "min": 0.5,
                "max": 48,
                "step": 0.5,
            },
            {
                "key": "spread_days",
                "label": "Repartir en (días)",
                "type": "number",
                "default": 7,
                "min": 1,
                "max": 60,
            },
            {
                "key": "start_delay_hours",
                "label": "Empezar dentro de (horas)",
                "type": "number",
                "default": 2,
                "min": 0,
                "max": 168,
                "step": 0.5,
            },
            {
                "key": "order",
                "label": "Orden de publicación",
                "type": "select",
                "default": "score",
                "options": [
                    {"value": "score", "label": "Mejores primero"},
                    {"value": "chronological", "label": "Orden del vídeo"},
                    {"value": "random", "label": "Aleatorio"},
                ],
            },
        ],
    },
    {
        "type": "publish",
        "label": "Publicación",
        "icon": "🚀",
        "description": "Dónde y cómo sale cada clip.",
        "fields": [
            {
                "key": "publish_tiktok",
                "label": "Publicar en TikTok",
                "type": "bool",
                "default": True,
            },
            {
                "key": "publish_youtube_shorts",
                "label": "Publicar en YouTube Shorts",
                "type": "bool",
                "default": False,
                "help": "Requiere conectar tu canal con permiso de subida "
                        "(Ajustes → YouTube). Google permite unas 6 subidas al día.",
            },
            {
                "key": "mode",
                "label": "Modo",
                "type": "select",
                "default": "review",
                "options": [
                    {"value": "auto", "label": "Automático (publica solo)"},
                    {"value": "review", "label": "Revisar antes de publicar"},
                    {"value": "draft", "label": "Enviar al borrador de TikTok"},
                    {"value": "manual", "label": "Sólo exportar el archivo"},
                ],
            },
            {
                "key": "privacy_level",
                "label": "Privacidad",
                "type": "select",
                "default": "PUBLIC_TO_EVERYONE",
                "options": [
                    {"value": "PUBLIC_TO_EVERYONE", "label": "Público"},
                    {"value": "MUTUAL_FOLLOW_FRIENDS", "label": "Amigos"},
                    {"value": "SELF_ONLY", "label": "Sólo yo (pruebas)"},
                ],
            },
            {"key": "allow_comments", "label": "Permitir comentarios", "type": "bool", "default": True},
            {"key": "allow_duet", "label": "Permitir dúos", "type": "bool", "default": True},
            {"key": "allow_stitch", "label": "Permitir stitch", "type": "bool", "default": True},
            {
                "key": "commercial_content",
                "label": "Contenido comercial (TikTok)",
                "type": "bool",
                "default": False,
            },
            {
                "key": "youtube_privacy",
                "label": "Privacidad en YouTube",
                "type": "select",
                "default": "public",
                "options": [
                    {"value": "public", "label": "Público"},
                    {"value": "unlisted", "label": "Oculto (con enlace)"},
                    {"value": "private", "label": "Privado (pruebas)"},
                ],
            },
            {
                "key": "youtube_title_suffix",
                "label": "Añadir al título en YouTube",
                "type": "text",
                "default": " #Shorts",
                "help": "Ayuda a que YouTube lo clasifique como Short.",
            },
            {
                "key": "youtube_made_for_kids",
                "label": "Contenido para niños (YouTube)",
                "type": "bool",
                "default": False,
            },
        ],
    },
]

# --------------------------------------------------------------------------
# Qué se ve de entrada y qué queda para quien quiera afinar
#
# La interfaz muestra sólo estos campos; el resto aparece al activar «todas las
# opciones». Así el flujo se entiende de un vistazo sin perder nada.
# --------------------------------------------------------------------------
ESSENTIAL_FIELDS: dict[str, set[str]] = {
    "ingest": {"quality"},
    "transcribe": {"engine"},
    "segment": {"strategy", "min_duration", "max_duration", "max_clips"},
    "reframe": {"mode"},
    "subtitles": {"style", "font_size", "highlight_color"},
    "overlays": {"hook_enabled", "watermark"},
    "audio": {"normalize"},
    "metadata": {"hashtags"},
    "schedule": {"max_per_day", "spread_days"},
    "publish": {"publish_tiktok", "publish_youtube_shorts", "mode"},
}

for _step in STEP_DEFINITIONS:
    _esenciales = ESSENTIAL_FIELDS.get(_step["type"], set())
    for _field in _step["fields"]:
        _field["advanced"] = _field["key"] not in _esenciales

STEP_INDEX = {step["type"]: step for step in STEP_DEFINITIONS}
STEP_ORDER = [step["type"] for step in STEP_DEFINITIONS]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def default_config(step_type: str) -> dict[str, Any]:
    definition = STEP_INDEX.get(step_type)
    if not definition:
        return {}
    return {field["key"]: copy.deepcopy(field["default"]) for field in definition["fields"]}


def default_steps() -> list[dict[str, Any]]:
    return [
        {"type": step["type"], "enabled": True, "config": default_config(step["type"])}
        for step in STEP_DEFINITIONS
    ]


def normalize_steps(steps: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Completa los pasos guardados con los valores por defecto que falten.

    Así, si en una versión futura se añade una opción nueva, los flujos que ya
    existen siguen funcionando.
    """
    steps = steps or []
    by_type = {s.get("type"): s for s in steps if isinstance(s, dict) and s.get("type")}
    result: list[dict[str, Any]] = []

    # 1) respetamos el orden guardado por el usuario
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_type = step.get("type")
        if step_type not in STEP_INDEX:
            continue
        config = default_config(step_type)
        config.update(step.get("config") or {})
        locked = bool(STEP_INDEX[step_type].get("locked"))
        result.append(
            {
                "type": step_type,
                "enabled": True if locked else bool(step.get("enabled", True)),
                "config": config,
            }
        )

    # 2) añadimos los pasos nuevos que aún no estuvieran
    for step_type in STEP_ORDER:
        if step_type not in by_type:
            locked = bool(STEP_INDEX[step_type].get("locked"))
            result.append(
                {
                    "type": step_type,
                    "enabled": True if locked else step_type != "manual",
                    "config": default_config(step_type),
                }
            )
    return result


def get_step(steps: list[dict[str, Any]], step_type: str) -> dict[str, Any]:
    for step in steps:
        if step.get("type") == step_type:
            return step
    return {"type": step_type, "enabled": False, "config": default_config(step_type)}


def step_config(steps: list[dict[str, Any]], step_type: str) -> dict[str, Any]:
    step = get_step(steps, step_type)
    config = default_config(step_type)
    config.update(step.get("config") or {})
    return config


def step_enabled(steps: list[dict[str, Any]], step_type: str) -> bool:
    return bool(get_step(steps, step_type).get("enabled"))


# --------------------------------------------------------------------------
# Plantillas de flujo listas para usar
# --------------------------------------------------------------------------
def _preset(
    overrides: dict[str, dict[str, Any]], disabled: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    steps = default_steps()
    for step in steps:
        if step["type"] in overrides:
            step["config"].update(overrides[step["type"]])
        if step["type"] in disabled and not STEP_INDEX[step["type"]].get("locked"):
            step["enabled"] = False
    return steps


FLOW_PRESETS: list[dict[str, Any]] = [
    {
        "name": "Cortes virales (recomendado)",
        "icon": "⚡",
        "description": "Momentos con más gancho, rótulos en karaoke y publicación repartida.",
        "steps": _preset({}),
    },
    {
        "name": "Directos largos",
        "icon": "🔴",
        "description": "Pensado para retransmisiones: salta la espera inicial y saca más clips.",
        "steps": _preset(
            {
                "segment": {
                    "skip_intro": 300,
                    "skip_outro": 60,
                    "clips_per_hour": 6,
                    "max_clips": 25,
                    "min_gap": 120,
                    "min_duration": 25,
                    "max_duration": 75,
                },
                "schedule": {"max_per_day": 4, "spread_days": 14},
            }
        ),
    },
    {
        "name": "Podcast / entrevistas",
        "icon": "🎙️",
        "description": "Encuadre a la cara, rótulos grandes y clips algo más largos.",
        "steps": _preset(
            {
                "reframe": {"mode": "crop", "zoom": 1.1},
                "subtitles": {"style": "blocks", "font_size": 58, "position_y": 76},
                "segment": {"min_duration": 30, "max_duration": 90, "clips_per_hour": 6},
            }
        ),
    },
    {
        "name": "Shorts a TikTok",
        "icon": "🔁",
        "description": "Republica tal cual los Shorts que ya tienes en YouTube.",
        "steps": _preset(
            {
                # El Short ya está montado: ni se corta ni se le añade nada encima
                "segment": {"strategy": "completo", "skip_intro": 0, "skip_outro": 0,
                            "pad_start": 0, "pad_end": 0, "max_clips": 1},
                "reframe": {"mode": "crop", "zoom": 1.0},
                "metadata": {"title_template": "{titulo}",
                             "caption_template": "{titulo}\n\n{hashtags}"},
                "schedule": {"max_per_day": 2, "spread_days": 10},
                "publish": {"publish_tiktok": True, "publish_youtube_shorts": False},
            },
            # el Short ya lleva sus propios rótulos y su gancho
            disabled=("transcribe", "subtitles", "overlays"),
        ),
    },
    {
        "name": "Clips a TikTok y Shorts",
        "icon": "🚀",
        "description": "Cada corte sale a la vez en TikTok y en YouTube Shorts.",
        "steps": _preset(
            {
                "segment": {"max_duration": 58},   # por debajo de 60 s en ambas
                "publish": {"publish_tiktok": True, "publish_youtube_shorts": True},
                "schedule": {"max_per_day": 2},
            }
        ),
    },
    {
        "name": "Tutoriales y gameplay",
        "icon": "🎮",
        "description": "Pantalla completa arriba y zoom abajo, sin perder detalle.",
        "steps": _preset(
            {
                "reframe": {"mode": "split"},
                "overlays": {"progress_bar": True},
                "segment": {"strategy": "smart", "min_duration": 20, "max_duration": 55},
            }
        ),
    },
]
