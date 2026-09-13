"""Capa fina sobre ffmpeg / ffprobe."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Callable, Iterable

from app.config import settings


class MediaError(RuntimeError):
    pass


def ffmpeg_ready() -> bool:
    return settings.ffmpeg_available() and settings.ffprobe_available()


def _fraction(value: str | None) -> float:
    if not value:
        return 0.0
    if "/" in value:
        num, _, den = value.partition("/")
        try:
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def probe(path: str | Path) -> dict:
    """Datos técnicos del archivo (duración, tamaño, fps, audio)."""
    path = str(path)
    cmd = [
        settings.ffprobe_path,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError as exc:  # pragma: no cover - entorno sin ffprobe
        raise MediaError("No se encuentra ffprobe. Instala ffmpeg.") from exc
    if out.returncode != 0:
        raise MediaError(f"ffprobe falló: {out.stderr.strip()[:400]}")

    data = json.loads(out.stdout or "{}")
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None
    )
    fmt = data.get("format", {})

    duration = 0.0
    for candidate in (fmt.get("duration"), (video_stream or {}).get("duration")):
        try:
            duration = float(candidate)
            break
        except (TypeError, ValueError):
            continue

    return {
        "duration": duration,
        "size": int(fmt.get("size") or 0),
        "width": int((video_stream or {}).get("width") or 0),
        "height": int((video_stream or {}).get("height") or 0),
        "fps": round(_fraction((video_stream or {}).get("r_frame_rate")), 3),
        "video_codec": (video_stream or {}).get("codec_name", ""),
        "audio_codec": (audio_stream or {}).get("codec_name", ""),
        "has_audio": audio_stream is not None,
    }


def run_ffmpeg(
    args: Iterable[str],
    *,
    total_duration: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
    timeout: int = 60 * 60 * 6,
    cwd: str | Path | None = None,
) -> str:
    """Ejecuta ffmpeg informando del progreso (0..1). Devuelve el log."""
    cmd = [settings.ffmpeg_path, "-hide_banner", "-nostdin", "-y"]
    # Las opciones globales van delante: si se ponen tras la salida, ffmpeg
    # puede ignorarlas según la versión.
    if on_progress and total_duration > 0:
        cmd += ["-progress", "pipe:2", "-nostats"]
    cmd += list(args)

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(cwd) if cwd else None,
        )
    except FileNotFoundError as exc:  # pragma: no cover
        raise MediaError("No se encuentra ffmpeg. Instálalo y vuelve a intentarlo.") from exc

    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        tail.append(line)
        if len(tail) > 400:
            del tail[:200]
        if on_progress and total_duration > 0:
            match = re.match(r"out_time_ms=(\d+)", line.strip())
            if match:
                seconds = int(match.group(1)) / 1_000_000
                on_progress(max(0.0, min(1.0, seconds / total_duration)))

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:  # pragma: no cover
        proc.kill()
        raise MediaError("ffmpeg tardó demasiado y se ha cancelado.")

    log = "".join(tail)
    if proc.returncode != 0:
        raise MediaError(
            f"ffmpeg terminó con error ({proc.returncode}).\n"
            f"Comando: {shlex.join(cmd[:12])} ...\n{log[-1500:]}"
        )
    return log


def detect_silences(
    path: str | Path,
    *,
    noise_db: int = -32,
    min_silence: float = 0.45,
    start: float = 0.0,
    duration: float | None = None,
) -> list[tuple[float, float]]:
    """Devuelve los tramos de silencio [(inicio, fin)] del audio."""
    args = ["-hide_banner", "-nostdin"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += [
        "-i", str(path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-",
    ]
    try:
        out = subprocess.run(
            [settings.ffmpeg_path, *args], capture_output=True, text=True, timeout=60 * 30
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):  # pragma: no cover
        return []

    silences: list[tuple[float, float]] = []
    pending: float | None = None
    for line in out.stderr.splitlines():
        begin = re.search(r"silence_start:\s*(-?[\d.]+)", line)
        if begin:
            pending = float(begin.group(1)) + start
            continue
        finish = re.search(r"silence_end:\s*(-?[\d.]+)", line)
        if finish and pending is not None:
            silences.append((pending, float(finish.group(1)) + start))
            pending = None
    return silences


def extract_thumbnail(
    video_path: str | Path, timestamp: float, out_path: str | Path, width: int = 360
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-ss", f"{max(0.0, timestamp):.3f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-vf", f"scale={width}:-2",
            "-q:v", "4",
            str(out_path),
        ]
    )
    return out_path


def make_test_video(out_path: str | Path, seconds: int = 60) -> Path:
    """Genera un vídeo de prueba 16:9 con voz sintética de tono. Útil para probar
    la aplicación sin descargar nada de YouTube."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f", "lavfi", "-i", f"testsrc=size=1280x720:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=320:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path),
        ]
    )
    return out_path
