"""Miniaturas de YouTube (1280x720).

Cómo se hace una miniatura aquí:

1. Se analizan fotogramas repartidos por todo el vídeo y se puntúan por
   contraste, nitidez y colorido, descartando los oscuros o planos.
2. Se eligen los mejores, bien separados en el tiempo.
3. Sobre cada uno se compone el texto (2-4 palabras en grande) con ffmpeg,
   en tres estilos distintos para que puedas comparar.
4. Si hay un modelo de imagen configurado, se genera además una variante con
   fondo creado por IA.

El paso 4 es el único que necesita clave: sin ella siguen saliendo miniaturas
buenas a partir de tus propios fotogramas.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.config import settings
from app.services import ai, captions
from app.services import media as media_service

WIDTH, HEIGHT = 1280, 720

# Paleta de acentos para las bandas y los bordes
ACCENTS = ["#28E7C5", "#FFB545", "#FF4D8D", "#7C5CFF"]


# --------------------------------------------------------------------------
# Elección de fotogramas
# --------------------------------------------------------------------------
def score_frames(
    video_path: str | Path, *, duration: float, samples: int = 30
) -> list[dict[str, float]]:
    """Puntúa fotogramas repartidos por el vídeo. Devuelve [{t, score, ...}]."""
    duration = max(1.0, float(duration))
    columns, rows = 48, 27
    fps = max(0.02, min(2.0, samples / duration))

    command = [
        settings.ffmpeg_path,
        "-hide_banner", "-nostdin", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", f"fps={fps:.5f},scale={columns}:{rows}",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
    ]
    try:
        result = subprocess.run(command, capture_output=True, timeout=600)
    except (FileNotFoundError, subprocess.TimeoutExpired):  # pragma: no cover
        return []

    raw = result.stdout or b""
    frame_size = columns * rows * 3
    total = len(raw) // frame_size
    if total == 0:
        return []

    scored: list[dict[str, float]] = []
    for index in range(total):
        frame = raw[index * frame_size : (index + 1) * frame_size]
        grays: list[float] = []
        rg: list[float] = []
        yb: list[float] = []
        for pixel in range(0, frame_size, 3):
            red, green, blue = frame[pixel], frame[pixel + 1], frame[pixel + 2]
            grays.append(0.299 * red + 0.587 * green + 0.114 * blue)
            rg.append(red - green)
            yb.append(0.5 * (red + green) - blue)

        media = sum(grays) / len(grays)
        varianza = sum((g - media) ** 2 for g in grays) / len(grays)
        contraste = varianza ** 0.5

        # nitidez aproximada: cuánto cambia el brillo entre píxeles vecinos
        bordes = 0.0
        for row in range(rows):
            base = row * columns
            for column in range(columns - 1):
                bordes += abs(grays[base + column] - grays[base + column + 1])
        bordes /= rows * (columns - 1)

        media_rg = sum(rg) / len(rg)
        media_yb = sum(yb) / len(yb)
        desv_rg = (sum((v - media_rg) ** 2 for v in rg) / len(rg)) ** 0.5
        desv_yb = (sum((v - media_yb) ** 2 for v in yb) / len(yb)) ** 0.5
        colorido = (desv_rg**2 + desv_yb**2) ** 0.5

        if media < 24 or media > 240:      # negro o quemado
            score = 0.0
        else:
            score = (
                min(1.0, contraste / 70) * 0.45
                + min(1.0, bordes / 26) * 0.35
                + min(1.0, colorido / 70) * 0.20
            )

        scored.append(
            {
                "t": round(index / fps, 2),
                "score": round(score, 4),
                "brillo": round(media, 1),
                "contraste": round(contraste, 1),
                "detalle": round(bordes, 1),
                "colorido": round(colorido, 1),
            }
        )
    return scored


def pick_frames(
    scored: list[dict[str, float]], *, count: int = 3, min_gap: float = 8.0
) -> list[dict[str, float]]:
    """Los mejores fotogramas, separados entre sí para que no se parezcan."""
    elegidos: list[dict[str, float]] = []
    for frame in sorted(scored, key=lambda f: f["score"], reverse=True):
        if frame["score"] <= 0:
            continue
        if all(abs(frame["t"] - otro["t"]) >= min_gap for otro in elegidos):
            elegidos.append(frame)
        if len(elegidos) >= count:
            break
    if not elegidos and scored:
        elegidos = [max(scored, key=lambda f: f["score"])]
    return elegidos


# --------------------------------------------------------------------------
# Composición
# --------------------------------------------------------------------------
def _ass_for_style(
    path: Path, *, text: str, style: str, accent: str
) -> Path:
    """Archivo ASS con el texto de la miniatura en el estilo elegido."""
    acento = captions.hex_to_ass(accent)
    blanco = "&H00FFFFFF"
    negro_80 = "&HB4101014"

    texto = captions.escape_text((text or "").strip().upper())
    lineas = _wrap_words(texto, 14)

    if style == "bloque":
        # Texto grande abajo a la izquierda, sobre caja opaca, con barra de color
        estilos = [
            f"Style: Big,DejaVu Sans,104,{blanco},{blanco},&H00101014,{negro_80},"
            f"-1,0,0,0,100,100,0,0,3,20,0,1,60,60,70,1",
        ]
        eventos = [
            _dibujo(0, 0, 18, HEIGHT, acento),                       # barra lateral
            f"Dialogue: 1,0:00:00.00,0:00:10.00,Big,,0,0,0,,"
            f"{{\\an1\\pos(64,{HEIGHT - 70})}}{lineas}",
        ]
    elif style == "banda":
        # Banda superior con el color de acento y el texto encima
        estilos = [
            f"Style: Big,DejaVu Sans,92,&H00101014,&H00101014,{acento},&H00000000,"
            f"-1,0,0,0,100,100,0,0,1,0,0,5,50,50,0,1",
        ]
        eventos = [
            _dibujo(0, 0, WIDTH, 168, acento),
            f"Dialogue: 1,0:00:00.00,0:00:10.00,Big,,0,0,0,,"
            f"{{\\an5\\pos({WIDTH // 2},84)}}{lineas}",
        ]
    else:  # "centro": degradado inferior y texto centrado con borde de color
        estilos = [
            f"Style: Big,DejaVu Sans,112,{blanco},{blanco},{acento},&H00000000,"
            f"-1,0,0,0,100,100,0,0,1,9,3,5,60,60,0,1",
        ]
        eventos = [
            _dibujo(0, HEIGHT - 330, WIDTH, 330, "#05070C", alpha=0xB0),
            _dibujo(0, HEIGHT - 250, WIDTH, 250, "#05070C", alpha=0x90),
            _dibujo(0, HEIGHT - 170, WIDTH, 170, "#05070C", alpha=0x70),
            f"Dialogue: 1,0:00:00.00,0:00:10.00,Big,,0,0,0,,"
            f"{{\\an5\\pos({WIDTH // 2},{HEIGHT - 150})}}{lineas}",
        ]

    # El estilo «Box» lo usan los rectángulos de fondo de todos los diseños
    estilos.append(
        "Style: Box,Arial,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"
    )

    contenido = captions.ASS_HEADER.format(
        width=WIDTH, height=HEIGHT, styles="\n".join(estilos)
    )
    contenido += "\n".join(eventos) + "\n"
    path.write_text(contenido, encoding="utf-8")
    return path


def _dibujo(x: int, y: int, width: int, height: int, color: str, alpha: int = 0) -> str:
    """Rectángulo dibujado con ASS. `alpha`: 0 = opaco, 255 = invisible."""
    return (
        f"Dialogue: 0,0:00:00.00,0:00:10.00,Box,,0,0,0,,"
        f"{{\\an7\\pos({x},{y})\\p1\\bord0\\shad0"
        f"\\1c{captions.override_color(color)}\\1a{captions.override_alpha(alpha)}}}"
        f"m 0 0 l {width} 0 l {width} {height} l 0 {height}{{\\p0}}"
    )


def _wrap_words(text: str, max_chars: int) -> str:
    palabras = text.split()
    lineas: list[str] = []
    actual = ""
    for palabra in palabras:
        if actual and len(actual) + len(palabra) + 1 > max_chars:
            lineas.append(actual)
            actual = palabra
        else:
            actual = f"{actual} {palabra}".strip()
    if actual:
        lineas.append(actual)
    return "\\N".join(lineas[:3])


def compose(
    *,
    background: str | Path,
    text: str,
    output: str | Path,
    style: str = "centro",
    accent: str = "#28E7C5",
    from_video: bool = True,
    timestamp: float = 0.0,
) -> Path:
    """Monta una miniatura: fondo (fotograma o imagen) + texto."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    settings.work_path.mkdir(parents=True, exist_ok=True)

    ass_path = settings.work_path / f"{output.stem}.ass"
    _ass_for_style(ass_path, text=text, style=style, accent=accent)

    filtros = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},eq=contrast=1.12:saturation=1.25:brightness=0.02,"
        f"unsharp=5:5:0.8,subtitles={ass_path.name}"
    )

    args: list[str] = []
    if from_video:
        args += ["-ss", f"{max(0.0, timestamp):.3f}"]
    args += ["-i", str(Path(background).resolve()), "-vf", filtros, "-frames:v", "1", "-q:v", "2"]
    args += [str(output.resolve())]

    media_service.run_ffmpeg(args, cwd=settings.work_path)
    return output


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------
def generate(
    *,
    video_path: str | Path,
    duration: float,
    texts: list[str],
    out_dir: str | Path,
    prefix: str,
    count: int = 3,
    ai_prompt: str = "",
    use_ai_image: bool = False,
    on_progress: Any = None,
) -> list[dict[str, Any]]:
    """Genera varias miniaturas y devuelve su descripción."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    textos = [t for t in (texts or []) if t.strip()] or ["MÍRALO"]

    scored = score_frames(video_path, duration=duration)
    frames = pick_frames(scored, count=count)
    estilos = ["centro", "bloque", "banda"]
    resultados: list[dict[str, Any]] = []

    for index, frame in enumerate(frames):
        texto = textos[index % len(textos)]
        estilo = estilos[index % len(estilos)]
        acento = ACCENTS[index % len(ACCENTS)]
        destino = out_dir / f"{prefix}-{index + 1}.jpg"
        try:
            compose(
                background=video_path,
                text=texto,
                output=destino,
                style=estilo,
                accent=acento,
                from_video=True,
                timestamp=frame["t"],
            )
        except Exception:
            continue
        resultados.append(
            {
                "path": str(destino),
                "text": texto,
                "style": estilo,
                "accent": acento,
                "source": "fotograma",
                "timestamp": frame["t"],
                "score": frame["score"],
            }
        )
        if on_progress:
            on_progress(0.4 + 0.4 * (index + 1) / max(1, len(frames)))

    # Variante con fondo generado por IA
    if use_ai_image and ai_prompt and ai.is_enabled():
        try:
            imagen = ai.generate_image(ai_prompt, width=WIDTH, height=HEIGHT)
            fondo = settings.work_path / f"{prefix}-ia.png"
            fondo.write_bytes(imagen)
            destino = out_dir / f"{prefix}-ia.jpg"
            compose(
                background=fondo,
                text=textos[0],
                output=destino,
                style="centro",
                accent=ACCENTS[0],
                from_video=False,
            )
            resultados.append(
                {
                    "path": str(destino),
                    "text": textos[0],
                    "style": "centro",
                    "accent": ACCENTS[0],
                    "source": "ia",
                    "prompt": ai_prompt[:300],
                    "score": 1.0,
                }
            )
        except Exception as exc:
            resultados.append({"error": f"No se ha podido generar la imagen con IA: {exc}"})

    return resultados
