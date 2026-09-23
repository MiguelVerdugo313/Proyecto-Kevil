"""Motor de render: convierte un tramo del vídeo original en un clip vertical."""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from app import procesos
from app.config import settings
from app.services import captions
from app.services import media as media_service


def parse_resolution(value: str) -> tuple[int, int]:
    try:
        width, _, height = str(value or "1080x1920").lower().partition("x")
        return max(2, int(width)), max(2, int(height))
    except ValueError:
        return 1080, 1920


# --------------------------------------------------------------------------
# Encuadre automático (hacia dónde mirar, y cuándo)
# --------------------------------------------------------------------------
COLUMNAS, FILAS = 48, 27
MUESTRAS_POR_SEGUNDO = 6.0
PUNTOS_MAXIMOS = 36        # cuántos puntos de giro caben en el encuadre
VENTANA_SUAVIZADO = 5      # media móvil: sin esto el encuadre tiembla
PASO_MAXIMO = 0.05         # cuánto puede desplazarse el encuadre de un punto a otro
HACIA_EL_CENTRO = 0.9      # se tira un poco hacia el medio: queda más natural
HACIA_EL_CENTRO_FIJO = 0.75   # con un encuadre fijo conviene ser más prudente


def _fotogramas(source: str | Path, start: float, end: float, fps: float) -> list[bytes]:
    """Fotogramas diminutos en gris del tramo pedido."""
    duration = max(0.5, end - start)
    cmd = [
        settings.ffmpeg_path,
        "-hide_banner", "-nostdin", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(source),
        "-vf", f"fps={fps:.3f},scale={COLUMNAS}:{FILAS},format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    try:
        out = procesos.run(cmd, capture_output=True, timeout=240)
    except (FileNotFoundError, subprocess.TimeoutExpired):  # pragma: no cover
        return []
    raw = out.stdout or b""
    tamano = COLUMNAS * FILAS
    return [raw[i : i + tamano] for i in range(0, len(raw) - tamano + 1, tamano)]


def _centros(frames: list[bytes]) -> list[float]:
    """Centro de masa del movimiento en cada fotograma (0 izquierda, 1 derecha)."""
    centros: list[float] = []
    ultimo = 0.5
    for index in range(1, len(frames)):
        anterior, actual = frames[index - 1], frames[index]
        energia = [0.0] * COLUMNAS
        for fila in range(FILAS):
            base = fila * COLUMNAS
            for columna in range(COLUMNAS):
                energia[columna] += abs(actual[base + columna] - anterior[base + columna])
        total = sum(energia)
        if total > 0:
            ultimo = sum((c + 0.5) / COLUMNAS * e for c, e in enumerate(energia)) / total
        centros.append(ultimo)
    return centros


def _suavizar(centros: list[float]) -> list[float]:
    """Media móvil y freno: el encuadre acompaña a la acción, no la persigue."""
    if not centros:
        return []
    suaves: list[float] = []
    for index in range(len(centros)):
        desde = max(0, index - VENTANA_SUAVIZADO // 2)
        hasta = min(len(centros), index + VENTANA_SUAVIZADO // 2 + 1)
        trozo = centros[desde:hasta]
        suaves.append(sum(trozo) / len(trozo))

    frenados = [suaves[0]]
    for valor in suaves[1:]:
        previo = frenados[-1]
        salto = max(-PASO_MAXIMO, min(PASO_MAXIMO, valor - previo))
        frenados.append(previo + salto)

    return [
        round(max(0.0, min(1.0, 0.5 + (v - 0.5) * HACIA_EL_CENTRO)), 4) for v in frenados
    ]


def seguir_accion(
    source: str | Path, start: float, end: float, *, fps: float = MUESTRAS_POR_SEGUNDO
) -> list[tuple[float, float]]:
    """Por dónde anda la acción a lo largo del clip: [(segundo, foco), …].

    Es lo que hace que el recorte vertical vaya detrás de quien habla en vez de
    quedarse clavado en un sitio. Si no se puede medir, se devuelve vacío y el
    encuadre se queda fijo en el centro.
    """
    duracion = max(0.5, end - start)
    frames = _fotogramas(source, start, end, fps)
    if len(frames) < 4:
        return []

    suaves = _suavizar(_centros(frames))
    if not suaves:
        return []

    # se reduce a unos pocos puntos de giro: ni el encuadre necesita más ni la
    # expresión de ffmpeg conviene que crezca sin medida
    grupo = max(1, math.ceil(len(suaves) / PUNTOS_MAXIMOS))
    puntos: list[tuple[float, float]] = []
    for inicio in range(0, len(suaves), grupo):
        trozo = suaves[inicio : inicio + grupo]
        momento = (inicio + len(trozo) / 2) / fps
        puntos.append((round(min(duracion, momento), 3), round(sum(trozo) / len(trozo), 4)))
    return puntos


def expresion_de_foco(puntos: list[tuple[float, float]]) -> str:
    """Convierte los puntos de giro en una expresión que ffmpeg evalúa por fotograma."""
    if not puntos:
        return "0.5"
    if len(puntos) == 1:
        return f"{puntos[0][1]:.4f}"

    trozos = [f"lt(t,{puntos[0][0]:.3f})*{puntos[0][1]:.4f}"]
    for (t0, x0), (t1, x1) in zip(puntos, puntos[1:]):
        if t1 - t0 < 1e-3:
            continue
        trozos.append(
            f"gte(t,{t0:.3f})*lt(t,{t1:.3f})*"
            f"({x0:.4f}+({x1 - x0:.4f})*(t-{t0:.3f})/{t1 - t0:.3f})"
        )
    trozos.append(f"gte(t,{puntos[-1][0]:.3f})*{puntos[-1][1]:.4f}")
    return "(" + "+".join(trozos) + ")"


def estimate_focus_x(
    source: str | Path, start: float, end: float, *, samples: int = 24
) -> float:
    """Un único centro para todo el tramo (encuadre fijo)."""
    duration = max(0.5, end - start)
    fps = max(0.5, min(4.0, samples / duration))
    frames = _fotogramas(source, start, end, fps)
    if len(frames) < 3:
        return 0.5
    centros = _centros(frames)
    if not centros:
        return 0.5
    medio = sum(centros) / len(centros)
    return round(max(0.0, min(1.0, 0.5 + (medio - 0.5) * HACIA_EL_CENTRO_FIJO)), 4)


# --------------------------------------------------------------------------
# Construcción del grafo de filtros
# --------------------------------------------------------------------------
def build_video_filters(
    *,
    mode: str,
    width: int,
    height: int,
    focus_x: float,
    zoom: float,
    blur: float,
    focus_track: list[tuple[float, float]] | None = None,
) -> tuple[list[str], str]:
    """Devuelve (cadena de filtros, etiqueta final).

    Con `focus_track` el recorte va siguiendo a la acción a lo largo del clip;
    sin él se queda fijo en `focus_x`.
    """
    zoom = max(1.0, min(2.0, float(zoom or 1.0)))
    focus_x = max(0.0, min(1.0, float(focus_x if focus_x is not None else 0.5)))
    # `crop` reevalúa x en cada fotograma, así que basta con darle una
    # expresión que dependa de «t» para que el encuadre se mueva.
    foco = expresion_de_foco(focus_track) if focus_track else f"{focus_x:.4f}"
    chains: list[str] = []

    if mode == "crop" or mode == "smart":
        scale_w = int(width * zoom)
        chains.append(
            f"[0:v]scale={scale_w}:{int(height * zoom)}:force_original_aspect_ratio=increase,"
            # el foco es el punto del original que queremos en el centro del
            # recorte, así que se resta media ventana y se pega a los bordes
            f"crop={width}:{height}:x='min(max(iw*{foco}-{width // 2},0),iw-{width})'"
            f":y='(ih-{height})/2',setsar=1[v]"
        )
        return chains, "[v]"

    if mode == "split":
        top_h = int(width * 9 / 16 / 2) * 2
        bottom_h = int(height * 0.40 / 2) * 2
        top_y = int(height * 0.12)
        bottom_y = min(height - bottom_h - 40, top_y + top_h + int(height * 0.03))
        bottom_ar = width / bottom_h
        chains.append("[0:v]split=3[bg][top][bot]")
        chains.append(
            f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},gblur=sigma={max(1, int(blur or 20))},"
            f"eq=brightness=-0.10:saturation=1.1,setsar=1[bgv]"
        )
        chains.append(f"[top]scale={width}:{top_h},setsar=1[topv]")
        chains.append(
            f"[bot]crop='min(iw,ih*{bottom_ar:.4f})':ih"
            f":x='min(max(iw*{foco}-min(iw,ih*{bottom_ar:.4f})/2,0),"
            f"iw-min(iw,ih*{bottom_ar:.4f}))':y=0,"
            f"scale={width}:{bottom_h},setsar=1[botv]"
        )
        chains.append(f"[bgv][topv]overlay=0:{top_y}[stage1]")
        chains.append(f"[stage1][botv]overlay=0:{bottom_y}[v]")
        return chains, "[v]"

    # modo por defecto: vídeo centrado sobre fondo desenfocado
    inner_w = int(width * zoom / 2) * 2
    chains.append("[0:v]split=2[bg][fg]")
    chains.append(
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={max(1, int(blur or 20))},"
        f"eq=brightness=-0.08:saturation=1.15,setsar=1[bgv]"
    )
    chains.append(
        f"[fg]scale={inner_w}:-2,crop='min(iw,{width})':'min(ih,{height})'"
        f":x='(iw-min(iw,{width}))/2':y='(ih-min(ih,{height}))/2',setsar=1[fgv]"
    )
    chains.append("[bgv][fgv]overlay=(W-w)/2:(H-h)/2[v]")
    return chains, "[v]"


def build_audio_filters(config: dict[str, Any], duration: float) -> str:
    filters: list[str] = []
    if config.get("normalize", True):
        target = float(config.get("target_lufs", -14) or -14)
        filters.append(f"loudnorm=I={target}:TP=-1.5:LRA=11")
    fade_in = float(config.get("fade_in", 0) or 0)
    fade_out = float(config.get("fade_out", 0) or 0)
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={fade_in:.2f}")
    if fade_out > 0 and duration > fade_out:
        filters.append(f"afade=t=out:st={duration - fade_out:.2f}:d={fade_out:.2f}")
    filters.append("aresample=44100")
    return ",".join(filters)


# --------------------------------------------------------------------------
# Render de un clip
# --------------------------------------------------------------------------
def render_clip(
    *,
    source_path: str | Path,
    start: float,
    end: float,
    output_path: str | Path,
    reframe: dict[str, Any],
    audio: dict[str, Any] | None = None,
    subtitles: dict[str, Any] | None = None,
    subtitles_enabled: bool = True,
    overlays: dict[str, Any] | None = None,
    overlays_enabled: bool = True,
    words: list[dict[str, Any]] | None = None,
    hook_text: str = "",
    has_audio: bool = True,
    on_progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    source_path = str(source_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    duration = max(0.5, float(end) - float(start))
    width, height = parse_resolution(reframe.get("resolution", "1080x1920"))
    fps = int(str(reframe.get("fps", 30)) or 30)
    mode = (reframe.get("mode") or "blur").lower()

    focus_x = float(reframe.get("focus_x", 0.5) or 0.5)
    recorrido: list[tuple[float, float]] = []
    if mode == "smart":
        # «Seguir a la acción» es lo que hace que el vertical no corte a quien
        # habla cuando se mueve. Se puede apagar y quedarse con un encuadre fijo.
        if bool(reframe.get("follow", True)):
            recorrido = seguir_accion(source_path, float(start), float(end))
        if recorrido:
            focus_x = sum(x for _, x in recorrido) / len(recorrido)
        else:
            focus_x = estimate_focus_x(source_path, float(start), float(end))

    chains, label = build_video_filters(
        mode=mode,
        width=width,
        height=height,
        focus_x=focus_x,
        zoom=float(reframe.get("zoom", 1.0) or 1.0),
        blur=float(reframe.get("background_blur", 22) or 22),
        focus_track=recorrido,
    )

    # Rótulos y sobreimpresos en un único archivo ASS.
    # Se genera en la carpeta de trabajo y ffmpeg se ejecuta desde ahí, así el
    # filtro `subtitles=` sólo recibe un nombre de archivo simple: nos ahorramos
    # los quebraderos de cabeza al escapar rutas con espacios, comas o «C:\».
    safe_stem = re.sub(r"[^A-Za-z0-9_-]", "_", output_path.stem)[:80] or "clip"
    settings.work_path.mkdir(parents=True, exist_ok=True)
    ass_path = settings.work_path / f"{safe_stem}.ass"
    needs_ass = (subtitles_enabled and words) or (
        overlays_enabled
        and (
            (overlays or {}).get("hook_enabled", True) and hook_text
            or (overlays or {}).get("watermark")
            or (overlays or {}).get("progress_bar")
        )
    )
    if needs_ass:
        captions.build_ass(
            path=ass_path,
            width=width,
            height=height,
            duration=duration,
            words=words or [],
            subtitles_config=subtitles or {},
            subtitles_enabled=subtitles_enabled,
            overlays_config=overlays or {},
            overlays_enabled=overlays_enabled,
            hook_text=hook_text,
        )
        # `../fonts` (relativo a la carpeta de trabajo) permite al usuario dejar
        # sus propias tipografías en data/fonts sin instalarlas en el sistema.
        chains.append(f"{label}subtitles={ass_path.name}:fontsdir=../fonts[vout]")
        label = "[vout]"

    chains.append(f"{label}fps={fps},format=yuv420p[vfinal]")
    filter_complex = ";".join(chains)

    args = [
        "-ss", f"{float(start):.3f}",
        "-t", f"{duration:.3f}",
        "-i", source_path,
        "-filter_complex", filter_complex,
        "-map", "[vfinal]",
    ]

    if has_audio:
        audio_chain = build_audio_filters(audio or {}, duration)
        args += ["-map", "0:a:0?", "-af", audio_chain, "-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    else:
        args += ["-an"]

    args += [
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-profile:v", "high",
        "-level", "4.1",
        "-maxrate", "8M",
        "-bufsize", "12M",
        "-g", str(fps * 2),
        "-movflags", "+faststart",
        "-shortest",
        str(output_path),
    ]

    media_service.run_ffmpeg(
        args,
        total_duration=duration,
        on_progress=on_progress,
        cwd=settings.work_path,
    )

    thumb_path = settings.thumbs_path / f"{output_path.stem}.jpg"
    try:
        media_service.extract_thumbnail(output_path, min(1.5, duration / 3), thumb_path, width=360)
    except Exception:
        thumb_path = Path("")

    info = media_service.probe(output_path)
    return {
        "path": str(output_path),
        "thumb": str(thumb_path) if thumb_path else "",
        "focus_x": round(focus_x, 4),
        "focus_track": recorrido,
        "duration": info.get("duration", duration),
        "size": info.get("size", 0),
        "width": info.get("width", width),
        "height": info.get("height", height),
    }
