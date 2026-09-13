"""Rótulos, filtros de vídeo y render real con ffmpeg."""

import pytest

from app.config import settings
from app.flow_schema import default_config, default_steps, normalize_steps, step_config
from app.services import captions, renderer
from app.services import media as media_service

PALABRAS = [
    {"start": 0.0, "end": 0.4, "text": "hola"},
    {"start": 0.4, "end": 0.9, "text": "qué"},
    {"start": 0.9, "end": 1.5, "text": "tal"},
    {"start": 2.0, "end": 2.6, "text": "todo"},
    {"start": 2.6, "end": 3.2, "text": "bien"},
]


def test_colores_ass():
    assert captions.hex_to_ass("#FFFFFF") == "&H00FFFFFF"
    assert captions.hex_to_ass("#28E7C5") == "&H00C5E728"
    assert captions.hex_to_ass("nada") == "&H00FFFFFF"


def test_el_texto_se_escapa_sin_romper_los_saltos():
    escapado = captions.escape_text("llaves {raras} y \\barra")
    assert "{" not in escapado and "}" not in escapado
    # el salto de ASS se añade después de escapar, así que sobrevive
    linea = captions._wrap(escapado, 12)
    assert "\\N" in linea


def test_archivo_ass_completo(tmp_path):
    destino = tmp_path / "sub.ass"
    captions.build_ass(
        path=destino,
        width=1080,
        height=1920,
        duration=4.0,
        words=PALABRAS,
        subtitles_config=default_config("subtitles"),
        overlays_config={**default_config("overlays"), "watermark": "@kevil", "progress_bar": True},
        hook_text="un gancho de prueba bastante largo para que se parta",
    )
    contenido = destino.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in contenido
    assert "Style: Sub," in contenido and "Style: Hook," in contenido
    assert contenido.count("Dialogue:") > len(PALABRAS)   # karaoke + gancho + marca + barra
    assert "@kevil" in contenido
    assert "HOLA" in contenido    # mayúsculas activadas por defecto


def test_agrupacion_de_palabras_por_ancho():
    grupos = captions.group_words(PALABRAS, max_chars=10, max_words=7)
    assert len(grupos) >= 2
    assert sum(len(grupo) for grupo in grupos) == len(PALABRAS)


@pytest.mark.parametrize("modo", ["blur", "crop", "smart", "split"])
def test_los_filtros_producen_una_salida(modo):
    cadenas, etiqueta = renderer.build_video_filters(
        mode=modo, width=1080, height=1920, focus_x=0.5, zoom=1.1, blur=20
    )
    assert cadenas
    assert etiqueta == "[v]"
    assert cadenas[-1].endswith("[v]")


def test_resolucion():
    assert renderer.parse_resolution("720x1280") == (720, 1280)
    assert renderer.parse_resolution("mal") == (1080, 1920)


def test_filtros_de_audio():
    cadena = renderer.build_audio_filters(default_config("audio"), duration=20)
    assert "loudnorm" in cadena and "afade=t=out" in cadena
    assert "aresample=44100" in cadena


def test_pasos_por_defecto_y_normalizacion():
    pasos = default_steps()
    assert [p["type"] for p in pasos][0] == "ingest"

    # un flujo guardado al que le faltan opciones se completa solo
    guardado = [{"type": "segment", "enabled": True, "config": {"max_clips": 3}}]
    normalizado = normalize_steps(guardado)
    tipos = [p["type"] for p in normalizado]
    assert len(tipos) == len(set(tipos)) == len(pasos)
    config = step_config(normalizado, "segment")
    assert config["max_clips"] == 3
    assert "min_duration" in config          # rellenado con el valor por defecto
    assert step_config(normalizado, "reframe")["mode"] == "blur"


@pytest.mark.skipif(not media_service.ffmpeg_ready(), reason="ffmpeg no está instalado")
def test_render_real_vertical(tmp_path):
    origen = tmp_path / "origen.mp4"
    media_service.make_test_video(origen, seconds=12)
    datos = media_service.probe(origen)
    assert datos["width"] == 1280 and datos["has_audio"]

    salida = tmp_path / "clip.mp4"
    settings.work_path.mkdir(parents=True, exist_ok=True)
    resultado = renderer.render_clip(
        source_path=origen,
        start=2,
        end=8,
        output_path=salida,
        reframe={**default_config("reframe"), "resolution": "720x1280"},
        audio=default_config("audio"),
        subtitles=default_config("subtitles"),
        overlays={**default_config("overlays"), "watermark": "@kevil"},
        words=PALABRAS,
        hook_text="gancho de prueba",
    )
    assert salida.exists()
    assert resultado["width"] == 720 and resultado["height"] == 1280
    assert 5.5 <= resultado["duration"] <= 6.5


@pytest.mark.skipif(not media_service.ffmpeg_ready(), reason="ffmpeg no está instalado")
def test_deteccion_del_centro_de_accion(tmp_path):
    origen = tmp_path / "origen.mp4"
    media_service.make_test_video(origen, seconds=8)
    foco = renderer.estimate_focus_x(origen, 1, 6)
    assert 0.0 <= foco <= 1.0
