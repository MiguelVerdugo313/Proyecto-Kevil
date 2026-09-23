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


# --------------------------------------------------------------------------
# Encuadre que sigue a la acción
# --------------------------------------------------------------------------
def test_la_expresion_de_foco_se_mueve_con_el_tiempo():
    fija = renderer.expresion_de_foco([])
    assert fija == "0.5"
    assert renderer.expresion_de_foco([(0.0, 0.3)]) == "0.3000"

    movil = renderer.expresion_de_foco([(0.0, 0.2), (1.0, 0.8)])
    assert "t" in movil                      # depende del momento del clip
    assert "0.2000" in movil and "0.8000" in movil
    assert movil.count("gte(t,") >= 1


def test_el_recorte_usa_la_expresion_y_no_se_sale():
    cadenas, _ = renderer.build_video_filters(
        mode="smart", width=1080, height=1920, focus_x=0.5, zoom=1.0, blur=20,
        focus_track=[(0.0, 0.2), (2.0, 0.8)],
    )
    crop = cadenas[0]
    assert "crop=1080:1920" in crop
    assert "0.2000" in crop and "0.8000" in crop
    # el foco es el punto que va al centro, y se pega a los bordes sin salirse
    assert "iw*(" in crop and "-540" in crop
    assert "min(max(" in crop and "iw-1080" in crop


def test_suavizado_frena_los_saltos():
    brusco = [0.1, 0.9, 0.1, 0.9, 0.1, 0.9]
    suave = renderer._suavizar(brusco)
    saltos = [abs(b - a) for a, b in zip(suave, suave[1:])]
    assert max(saltos) <= renderer.PASO_MAXIMO + 1e-6
    assert all(0.0 <= v <= 1.0 for v in suave)


@pytest.mark.skipif(not media_service.ffmpeg_ready(), reason="ffmpeg no está instalado")
def test_el_encuadre_persigue_a_lo_que_se_mueve(tmp_path):
    """Un cuadro que cruza la pantalla: con seguimiento no se sale del clip."""
    origen = tmp_path / "movil.mp4"
    media_service.run_ffmpeg([
        "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=8:r=25",
        "-f", "lavfi", "-i", "color=c=white:s=200x200:d=8:r=25",
        "-filter_complex", "[0:v][1:v]overlay=x='120+t*110':y=260:eval=frame[v]",
        "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-an", str(origen),
    ], total_duration=8)

    puntos = renderer.seguir_accion(origen, 0.5, 7.5)
    assert len(puntos) >= 5
    assert puntos[0][1] < puntos[-1][1] - 0.2      # va de izquierda a derecha
    assert all(0.0 <= x <= 1.0 for _, x in puntos)
    assert all(b[0] > a[0] for a, b in zip(puntos, puntos[1:]))   # en orden

    salida = tmp_path / "clip.mp4"
    settings.work_path.mkdir(parents=True, exist_ok=True)
    datos = renderer.render_clip(
        source_path=origen, start=0.5, end=7.5, output_path=salida,
        reframe={**default_config("reframe"), "mode": "smart", "resolution": "360x640"},
        audio=default_config("audio"), subtitles_enabled=False,
        overlays_enabled=False, has_audio=False,
    )
    assert salida.exists()
    assert len(datos["focus_track"]) >= 5


# --------------------------------------------------------------------------
# Puesta al día de las plantillas al actualizar el programa
# --------------------------------------------------------------------------
def test_las_plantillas_se_ponen_al_dia_sin_pisar_lo_tuyo(session):
    from app import bootstrap
    from app.models import Flow, Setting

    def con_modo(nombre, modo):
        pasos = default_steps()
        for paso in pasos:
            if paso["type"] == "reframe":
                paso["config"]["mode"] = modo
        return Flow(name=nombre, description="", icon="", steps=pasos)

    de_fabrica = con_modo("Cortes virales (recomendado)", "blur")
    tocado = con_modo("Clips a TikTok y Shorts", "split")     # elegido a mano
    ajeno = con_modo("Mi flujo", "blur")                      # no es una plantilla
    session.add_all([de_fabrica, tocado, ajeno])
    session.flush()

    assert bootstrap.actualizar_plantillas(session) == 1
    session.flush()

    def modo(flow):
        return step_config(flow.steps, "reframe")["mode"]

    assert modo(de_fabrica) == "smart"      # seguía con el valor de antes
    assert step_config(de_fabrica.steps, "reframe")["follow"] is True
    assert modo(tocado) == "split"          # lo eligió el usuario: no se toca
    assert modo(ajeno) == "blur"            # no es una plantilla de las nuestras

    # y no se repite en cada arranque
    assert bootstrap.actualizar_plantillas(session) == 0
    assert session.get(Setting, bootstrap.MEJORAS_KEY).value == list(bootstrap.MEJORAS)


def test_los_flujos_viejos_pasan_a_rotulos_virales_y_mas_clips(session):
    """Con los valores de antes un vídeo corto daba un clip y rótulos sosos."""
    from app import bootstrap
    from app.models import Flow

    antes = {
        "segment": {"clips_per_hour": 8, "max_clips": 12},
        "subtitles": {"style": "karaoke", "font": "DejaVu Sans", "font_size": 64,
                      "highlight_color": "#28E7C5", "outline": 4, "position_y": 72,
                      "max_chars": 22},
    }

    def flujo(nombre, **cambios):
        pasos = default_steps()
        for paso in pasos:
            paso["config"].update(antes.get(paso["type"], {}))
            paso["config"].update(cambios.get(paso["type"], {}))
        return Flow(name=nombre, description="", icon="", steps=pasos)

    viejo = flujo("Mi flujo")
    elegido = flujo("Otro mío", subtitles={"style": "blocks", "font_size": 80},
                    segment={"max_clips": 3})
    session.add_all([viejo, elegido])
    session.flush()

    bootstrap.actualizar_plantillas(session)
    session.flush()

    rotulos, corte = step_config(viejo.steps, "subtitles"), step_config(viejo.steps, "segment")
    assert rotulos["style"] == "viral" and rotulos["font"] == "Montserrat Black"
    assert rotulos["highlight_color"] == "#FFD400" and rotulos["font_size"] == 125
    assert corte["clips_per_hour"] == 20 and corte["max_clips"] == 20

    # lo que se eligió a mano se respeta; lo que seguía de fábrica, se mejora
    rotulos = step_config(elegido.steps, "subtitles")
    assert rotulos["style"] == "blocks" and rotulos["font_size"] == 80
    assert rotulos["highlight_color"] == "#FFD400"
    assert step_config(elegido.steps, "segment")["max_clips"] == 3


# --------------------------------------------------------------------------
# Rótulos virales
# --------------------------------------------------------------------------
def _dialogos(ruta):
    return [l for l in ruta.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue:")]


def test_rotulos_virales_por_defecto(tmp_path):
    config = default_config("subtitles")
    assert config["style"] == "viral" and config["font"] == captions.FUENTE_VIRAL
    frase = ("¿Sabes qué? Los zombis vienen, corre corre, "
             "extraordinariamente incomprensiblemente rápido.")
    palabras, t = [], 0.0
    for texto in frase.split():
        palabras.append({"start": t, "end": t + 0.3, "text": texto})
        t += 0.32
    destino = tmp_path / "viral.ass"
    captions.build_ass(path=destino, width=1080, height=1920, duration=t + 1,
                       words=palabras, subtitles_config=config, overlays_enabled=False)
    contenido = destino.read_text(encoding="utf-8")
    assert "Style: Sub,Montserrat Black,125," in contenido
    dialogos = _dialogos(destino)
    assert len(dialogos) == len(palabras)          # un estado por palabra que suena

    import re
    for linea in dialogos:
        texto = linea.split(",,", 1)[1].split(",", 4)[-1]
        visible = re.sub(r"\{[^}]*\}", "", texto)
        assert len(visible.split()) <= 3, visible            # dos o tres palabras
        assert "," not in visible and "." not in visible     # sin puntuación colgando
        assert "&H00D4FF&" in texto                          # la que suena, en amarillo
        # y nunca se sale del vídeo: las palabras largas encogen la línea
        escala = int(re.search(r"\\fscx(\d+)", texto).group(1))
        ancho = captions.ancho_texto(visible, 125) * escala / 100
        assert ancho <= 1080 - 2 * int(1080 * 0.07), visible
    # «¿SABES QUÉ?» no se junta con la frase siguiente
    assert not any("QUÉ? LOS" in d or "QUÉ LOS" in d for d in dialogos)
    # el salto de entrada al aparecer cada grupo
    assert "\\t(0,90," in contenido


def test_rotulos_escalan_con_la_resolucion(tmp_path):
    destino = tmp_path / "720.ass"
    captions.build_ass(path=destino, width=720, height=1280, duration=2,
                       words=PALABRAS, subtitles_config=default_config("subtitles"))
    assert "Style: Sub,Montserrat Black,83," in destino.read_text(encoding="utf-8")


def test_la_tipografia_viaja_con_el_programa(tmp_path):
    captions.asegurar_tipografias(tmp_path)
    assert (tmp_path / "Montserrat-Black.ttf").stat().st_size > 100_000
    from pathlib import Path
    construir = (Path(__file__).parent.parent / "construir.py").read_text(encoding="utf-8")
    assert "app/assets" in construir      # y entra en el .exe
