"""Preparación inicial: flujos de ejemplo y ajustes guardados."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.flow_schema import FLOW_PRESETS, normalize_steps
from app.models import Flow, Setting
from app.services import canales, diagnostico, timing

# Ajustes que se pueden cambiar desde la interfaz y se guardan en la base de datos
EDITABLE_SETTINGS = {
    "tiktok_client_key": str,
    "tiktok_client_secret": str,
    "youtube_api_key": str,
    "youtube_client_id": str,
    "youtube_client_secret": str,
    "dry_run": bool,
    "workers": int,
    "watch_interval_minutes": int,
    "ffmpeg_path": str,
    "ffprobe_path": str,
    # Inteligencia artificial (los dos proveedores a la vez)
    "ai_primary": str,
    "openrouter_api_key": str,
    "openrouter_text_model": str,
    "openrouter_image_model": str,
    "nvidia_api_key": str,
    "nvidia_text_model": str,
    "nvidia_image_model": str,
    # Canal
    "channel_topic": str,
    "channel_language": str,
    "target_uploads_per_week": float,
    "notifications_desktop": bool,
    # Colores
    "brand_accent": str,
    "brand_accent_2": str,
    "brand_source": str,
    # Espacio en disco
    "light_mode": bool,
    "keep_originals": bool,
    "keep_clips": bool,
    "disk_budget_gb": float,
    # Ventana de la aplicación
    "window_mode": str,
    "segundo_plano": bool,
    # YouTube: de dónde sacar tu sesión cuando pide «no soy un robot»
    "youtube_cookies": str,
    # Más proveedores de IA (se editan desde su propia pantalla)
    "ia_proveedores": list,
}

# Se guardan como los demás, pero no salen en la lista general de ajustes:
# llevan claves dentro y tienen su propia pantalla, que las enseña tapadas.
AJUSTES_APARTE = {"ia_proveedores"}

SECRET_SETTINGS = {
    "tiktok_client_secret", "youtube_api_key", "youtube_client_secret",
    "openrouter_api_key", "nvidia_api_key",
}


SEEDED_KEY = "seeded_presets"

# Mejoras que se aplican a las plantillas que vienen de serie cuando el
# programa se actualiza.
MEJORAS_KEY = "mejoras_de_plantilla"

# Cada cambio dice de qué valor viene y a cuál va: así sólo se tocan las
# plantillas que siguen con el valor de antes. Si tú elegiste otra cosa, se
# respeta. Y cada mejora se aplica una sola vez, aunque luego vuelvas atrás.
MEJORAS: dict[str, dict[str, dict[str, dict[str, tuple[Any, Any]]]]] = {
    # El recorte vertical que va siguiendo a la acción es lo que hace que el
    # clip no corte a quien habla. Antes el flujo recomendado salía con el
    # vídeo centrado sobre fondo desenfocado.
    "seguir-la-accion-1": {
        "Cortes virales (recomendado)": {"reframe": {"mode": ("blur", "smart")}},
        "Clips a TikTok y Shorts": {"reframe": {"mode": ("blur", "smart")}},
        "Podcast / entrevistas": {"reframe": {"mode": ("crop", "smart")}},
    },
    # Rótulos al estilo de los clips virales y varios clips por vídeo: con los
    # valores de antes un vídeo de siete minutos daba un solo clip. «*» vale
    # para todos los flujos, también los tuyos, pero sólo donde siga el valor
    # de fábrica de antes.
    "rotulos-virales-y-mas-clips-1": {
        "*": {
            "segment": {"clips_per_hour": (8, 20), "max_clips": (12, 20)},
            "subtitles": {
                "style": ("karaoke", "viral"),
                "font": ("DejaVu Sans", "Montserrat Black"),
                "font_size": (64, 125),
                "highlight_color": (["#E8D5B7", "#28E7C5"], "#FFD400"),
                "outline": (4, 8),
                "position_y": (72, 66),
                "max_chars": (22, 16),
            },
        },
        "Directos largos": {"segment": {"clips_per_hour": (6, 15), "max_clips": (25, 30)}},
        "Podcast / entrevistas": {
            "segment": {"clips_per_hour": (6, 12)},
            "subtitles": {
                "style": ("blocks", "viral"),
                "font_size": (58, 125),
                "position_y": (76, 70),
            },
        },
    },
    # Clips con contexto: de 30 a 90 s en vez de 21 a 59. Los cortos se
    # quedaban a media idea.
    "clips-con-contexto-1": {
        "*": {"segment": {"min_duration": (21, 30), "max_duration": (59, 90)}},
        "Directos largos": {"segment": {"min_duration": (25, 30), "max_duration": (75, 90)}},
        "Clips a TikTok y Shorts": {"segment": {"max_duration": (58, 90)}},
        "Tutoriales y gameplay": {
            "segment": {"min_duration": (20, 30), "max_duration": (55, 90)},
        },
    },
    # Vuelta al fondo borroso: el vídeo entero centrado y, detrás, él mismo
    # desenfocado. No corta nada de la pantalla y es el que más te gusta.
    "fondo-borroso-1": {
        "Cortes virales (recomendado)": {"reframe": {"mode": ("smart", "blur")}},
        "Clips a TikTok y Shorts": {"reframe": {"mode": ("smart", "blur")}},
        "Podcast / entrevistas": {"reframe": {"mode": ("smart", "blur")}},
    },
}


def _cambios_para(por_nombre: dict[str, Any], nombre: str) -> dict[str, dict[str, Any]]:
    """Lo que toca a un flujo: lo común («*») y encima lo suyo."""
    cambios: dict[str, dict[str, Any]] = {}
    for clave in ("*", nombre):
        for paso, campos in (por_nombre.get(clave) or {}).items():
            cambios.setdefault(paso, {}).update(campos)
    return cambios


def _coincide(actual: Any, antes: Any) -> bool:
    """`antes` puede ser un valor o una lista de valores de fábrica de antes."""
    return actual in antes if isinstance(antes, list) else actual == antes


def _clips_sin_montar_a_fondo_borroso(session: Session) -> int:
    """Los clips que aún no se han montado cogen también el fondo borroso."""
    from app.models import Clip, ClipStatus

    cambiados = 0
    pendientes = {ClipStatus.draft.value, ClipStatus.failed.value}
    for clip in session.scalars(select(Clip).where(Clip.status.in_(pendientes))).all():
        config = dict(clip.render_config or {})
        encuadre = dict(config.get("reframe") or {})
        if encuadre.get("mode") == "smart":
            encuadre["mode"] = "blur"
            config["reframe"] = encuadre
            clip.render_config = config
            cambiados += 1
    return cambiados


def _canales_sin_saltar_cortos(session: Session) -> int:
    """Los canales que se saltaban los vídeos de menos de 2 minutos ya no.

    Ahora un vídeo corto se publica entero en vez de trocearlo, así que no hay
    motivo para dejarlo fuera.
    """
    from app.models import Source

    cambiados = 0
    for source in session.scalars(select(Source).where(Source.min_duration_s == 120)).all():
        source.min_duration_s = 20
        cambiados += 1
    return cambiados


def actualizar_plantillas(session: Session) -> int:
    """Pone al día las plantillas que siguen con los valores de fábrica."""
    registro = session.get(Setting, MEJORAS_KEY)
    aplicadas: list[str] = list((registro.value if registro else None) or [])
    cambiados = 0

    for clave, por_nombre in MEJORAS.items():
        if clave in aplicadas:
            continue
        aplicadas.append(clave)
        if clave == "fondo-borroso-1":
            _clips_sin_montar_a_fondo_borroso(session)
        if clave == "clips-con-contexto-1":
            _canales_sin_saltar_cortos(session)
        for flow in session.scalars(select(Flow)).all():
            cambios = _cambios_para(por_nombre, flow.name)
            if not cambios:
                continue
            pasos = [dict(paso) for paso in (flow.steps or [])]
            tocado = False
            for paso in pasos:
                campos = cambios.get(paso.get("type", ""))
                if not campos:
                    continue
                config = dict(paso.get("config") or {})
                for campo, (antes, despues) in campos.items():
                    if _coincide(config.get(campo), antes):
                        config[campo] = despues
                        tocado = True
                paso["config"] = config
            if tocado:
                flow.steps = normalize_steps(pasos)
                cambiados += 1

    if registro is None:
        session.add(Setting(key=MEJORAS_KEY, value=aplicadas))
    else:
        registro.value = aplicadas
    return cambiados


def seed_flows(session: Session) -> None:
    """Crea las plantillas de flujo que aún no se hayan creado nunca.

    Se recuerda cuáles se han sembrado ya, así que al actualizar la aplicación
    aparecen las plantillas nuevas sin resucitar las que hayas borrado.
    """
    primera_vez = session.scalars(select(Flow).limit(1)).first() is None

    registro = session.get(Setting, SEEDED_KEY)
    ya_sembradas: list[str] = list((registro.value if registro else None) or [])

    # Al actualizar desde una versión anterior no existe el registro: se da por
    # sembrado todo lo que ya esté en la base de datos para no duplicarlo.
    if registro is None:
        ya_sembradas += [
            nombre for (nombre,) in session.execute(select(Flow.name)).all()
        ]

    creadas = 0
    for preset in FLOW_PRESETS:
        if preset["name"] in ya_sembradas:
            continue
        session.add(
            Flow(
                name=preset["name"],
                description=preset["description"],
                icon=preset["icon"],
                steps=normalize_steps(preset["steps"]),
                is_default=primera_vez and creadas == 0,
            )
        )
        ya_sembradas.append(preset["name"])
        creadas += 1

    if creadas:
        if registro is None:
            session.add(Setting(key=SEEDED_KEY, value=ya_sembradas))
        else:
            registro.value = ya_sembradas


def load_setting_overrides(session: Session) -> None:
    """Aplica los ajustes guardados sobre la configuración en memoria."""
    rows = session.scalars(select(Setting)).all()
    for row in rows:
        if row.key not in EDITABLE_SETTINGS or row.value in (None, ""):
            continue
        caster = EDITABLE_SETTINGS[row.key]
        try:
            setattr(settings, row.key, caster(row.value))
        except (TypeError, ValueError):
            continue


def save_settings(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    applied: dict[str, Any] = {}
    for key, value in values.items():
        if key not in EDITABLE_SETTINGS:
            continue
        caster = EDITABLE_SETTINGS[key]
        try:
            value = caster(value)
        except (TypeError, ValueError):
            continue
        row = session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=value)
            session.add(row)
        else:
            row.value = value
        setattr(settings, key, value)
        applied[key] = value
    return applied


def current_settings(session: Session) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in EDITABLE_SETTINGS:
        if key in AJUSTES_APARTE:
            continue
        value = getattr(settings, key, None)
        if key in SECRET_SETTINGS and value:
            value = "••••••••"
        result[key] = value
    return result


def migrate_ai_settings(session: Session) -> None:
    """De la configuración antigua (un proveedor) a la nueva (los dos)."""
    antiguo_proveedor = session.get(Setting, "ai_provider")
    antigua_clave = session.get(Setting, "ai_api_key")
    if not antiguo_proveedor or not antigua_clave or not antigua_clave.value:
        return

    proveedor = str(antiguo_proveedor.value or "").strip().lower()
    if proveedor not in {"openrouter", "nvidia"}:
        return
    if session.get(Setting, f"{proveedor}_api_key"):
        return                                    # ya migrado

    save_settings(
        session,
        {
            f"{proveedor}_api_key": antigua_clave.value,
            "ai_primary": proveedor,
            **{
                f"{proveedor}_{campo}": (session.get(Setting, f"ai_{campo}").value or "")
                for campo in ("text_model", "image_model")
                if session.get(Setting, f"ai_{campo}")
            },
        },
    )


def olvidar_modelos_retirados(session: Session) -> None:
    """El modelo de NVIDIA que ya no existe se olvida: se usa el recomendado."""
    from app.services import ai

    for proveedor in ai.PROVIDERS:
        clave = f"{proveedor}_text_model"
        if (getattr(settings, clave, "") or "") in ai.RETIRADOS:
            save_settings(session, {clave: ""})


def run() -> None:
    with session_scope() as session:
        load_setting_overrides(session)
        migrate_ai_settings(session)
        olvidar_modelos_retirados(session)
        seed_flows(session)
        actualizar_plantillas(session)
        # las cuentas que seguían con la hora de Madrid pasan a la del equipo
        timing.poner_zona_del_equipo(session)
        # lo que falló por algo pasajero se vuelve a intentar al abrir
        diagnostico.reintentar_pasajeros_al_arrancar(session)
        # el canal autorizado para publicar también se vigila para sacar clips
        canales.vigilar_los_conectados(session)
