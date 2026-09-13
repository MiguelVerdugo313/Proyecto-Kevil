"""Motor de render: convierte un tramo del vídeo original en un clip vertical."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Callable

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
# Encuadre automático (hacia dónde mirar)
# --------------------------------------------------------------------------
def estimate_focus_x(
    source: str | Path, start: float, end: float, *, samples: int = 24
) -> float:
    """Estima el centro horizontal de la acción midiendo el movimiento.

    Extrae unos fotogramas diminutos en gris, calcula cuánto cambia cada
    columna y devuelve el centro de masa (0 = izquierda, 1 = derecha).
    Si algo falla, devuelve 0.5 (centro).
    """
    duration = max(0.5, end - start)
    columns, rows = 48, 27
    fps = max(0.5, min(4.0, samples / duration))
    cmd = [
        settings.ffmpeg_path,
        "-hide_banner", "-nostdin", "-loglevel", "error",
        "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(source),
        "-vf", f"fps={fps:.3f},scale={columns}:{rows},format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=180)
    except (FileNotFoundError, subprocess.TimeoutExpired):  # pragma: no cover
        return 0.5
    raw = out.stdout or b""
    frame_size = columns * rows
    frames = [raw[i : i + frame_size] for i in range(0, len(raw) - frame_size + 1, frame_size)]
    if len(frames) < 3:
        return 0.5

    energy = [0.0] * columns
    for index in range(1, len(frames)):
        previous, current = frames[index - 1], frames[index]
        for row in range(rows):
            offset = row * columns
            for column in range(columns):
                energy[column] += abs(current[offset + column] - previous[offset + column])

    total = sum(energy)
    if total <= 0:
        return 0.5

    # centro de masa, suavizado hacia el centro para evitar encuadres raros
    centroid = sum((c + 0.5) / columns * e for c, e in enumerate(energy)) / total
    return round(0.5 + (centroid - 0.5) * 0.75, 4)


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
) -> tuple[list[str], str]:
    """Devuelve (cadena de filtros, etiqueta final)."""
    zoom = max(1.0, min(2.0, float(zoom or 1.0)))
    focus_x = max(0.0, min(1.0, float(focus_x if focus_x is not None else 0.5)))
    chains: list[str] = []

    if mode == "crop" or mode == "smart":
        scale_w = int(width * zoom)
        chains.append(
            f"[0:v]scale={scale_w}:{int(height * zoom)}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='min(max((iw-{width})*{focus_x:.4f},0),iw-{width})'"
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
            f":x='min(max((iw-min(iw,ih*{bottom_ar:.4f}))*{focus_x:.4f},0),"
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
    if mode == "smart":
        focus_x = estimate_focus_x(source_path, float(start), float(end))

    chains, label = build_video_filters(
        mode=mode,
        width=width,
        height=height,
        focus_x=focus_x,
        zoom=float(reframe.get("zoom", 1.0) or 1.0),
        blur=float(reframe.get("background_blur", 22) or 22),
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
        "focus_x": focus_x,
        "duration": info.get("duration", duration),
        "size": info.get("size", 0),
        "width": info.get("width", width),
        "height": info.get("height", height),
    }
