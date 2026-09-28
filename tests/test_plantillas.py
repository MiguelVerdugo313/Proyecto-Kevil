"""Plantillas de rótulos: pastilla, énfasis, emojis, brillo, caja y tipografías."""

import json
import re

import pytest

from app.flow_schema import default_config, default_steps, step_config
from app.services import captions, plantillas

FRASE = "Gané la partida con 100 puntos increíble jaja mira esto".split()


def _palabras():
    palabras, t = [], 0.0
    for texto in FRASE:
        palabras.append({"start": t, "end": t + 0.4, "text": texto})
        t += 0.45
    return palabras, t


def _ass(tmp_path, plantilla, **extra):
    palabras, t = _palabras()
    destino = tmp_path / f"{plantilla or 'propio'}.ass"
    config = {**default_config("subtitles"), "template": plantilla, **extra}
    captions.build_ass(path=destino, width=1080, height=1920, duration=t + 1,
                       words=palabras, subtitles_config=config, overlays_enabled=False)
    return destino.read_text(encoding="utf-8")


def _dialogos(contenido, capa=None):
    lineas = [ln for ln in contenido.splitlines() if ln.startswith("Dialogue:")]
    if capa is not None:
        lineas = [ln for ln in lineas if ln.startswith(f"Dialogue: {capa},")]
    return lineas


def test_cada_plantilla_tiene_su_tipografia_en_el_programa():
    medidas = json.loads((captions.TIPOGRAFIAS / "anchos.json").read_text(encoding="utf-8"))
    for clave in plantillas.PLANTILLAS:
        fuente = plantillas.completa(clave)["fuente"]
        assert fuente in medidas, fuente
        assert (captions.TIPOGRAFIAS / medidas[fuente]["archivo"]).is_file()
        # y su licencia viaja con ella
    licencias = {p.name for p in captions.TIPOGRAFIAS.glob("*.txt")}
    assert {"OFL-Anton.txt", "OFL-Bangers.txt", "OFL-NotoEmoji.txt",
            "LICENSE-LuckiestGuy.txt"} <= licencias


def test_todos_los_emojis_se_pueden_dibujar():
    for emoji in plantillas.todos_los_emojis():
        glifo = captions.glifo_emoji(emoji)
        # en la zona privada: libass no mira más allá de U+FFFF
        assert glifo and 0xE000 <= ord(glifo) <= 0xF8FF, emoji


@pytest.mark.parametrize("clave", list(plantillas.PLANTILLAS))
def test_ninguna_plantilla_se_sale_del_video(tmp_path, clave):
    contenido = _ass(tmp_path, clave)
    fuente = plantillas.completa(clave)["fuente"]
    assert f"Style: Sub,{fuente}," in contenido
    tamano = int(re.search(r"Style: Sub,[^,]+,(\d+),", contenido).group(1))
    disponible = 1080 - 2 * int(1080 * 0.07)
    for linea in _dialogos(contenido, capa=2):
        texto = linea.split(",,", 1)[1].split(",", 4)[-1]
        visible = re.sub(r"\{[^}]*\}", "", texto)
        escala = int(re.search(r"\\fscx(\d+)", texto).group(1))
        assert captions.ancho_texto(visible, tamano, fuente) * escala / 100 <= disponible, visible


def test_las_mayusculas_miden_lo_mismo_en_todas():
    """Cambiar de plantilla no hace el rótulo enano ni gigante (salvo que lo pida)."""
    alturas = []
    for clave in plantillas.PLANTILLAS:
        tpl = plantillas.completa(clave)
        tpl["normalizar"] = True
        tamano = captions.tamano_de_letra(tpl, 125)
        alturas.append(tamano * captions.altura_mayusculas(tpl["fuente"]) / tpl["tam"])
    assert max(alturas) - min(alturas) < 2


def test_kevil_es_el_viral_de_siempre(tmp_path):
    contenido = _ass(tmp_path, "kevil")
    assert "Style: Sub,Montserrat Black,125," in contenido
    assert "&H00D4FF&" in contenido                  # la que suena, en amarillo
    assert "\\t(0,90," in contenido                  # el salto al entrar
    assert "\\p1" not in contenido                   # sin pastilla ni caja


def test_hormozi_pone_la_pastilla_detras_de_la_palabra(tmp_path):
    contenido = _ass(tmp_path, "hormozi")
    pastillas = [ln for ln in _dialogos(contenido, capa=1) if "\\p1" in ln]
    textos = _dialogos(contenido, capa=2)
    assert len(pastillas) == len(textos) == len(FRASE)
    assert "&H49BF00&" in pastillas[0]               # verde
    # cada pastilla va más a la derecha que la anterior dentro de la línea
    xs = [float(re.search(r"\\pos\(([\d.]+),", ln).group(1)) for ln in pastillas[:3]]
    assert xs == sorted(xs)
    # los números y las palabras fuertes, en amarillo
    assert any("&H00D4FF&}100" in ln for ln in textos)


def test_gamer_pone_emojis_con_mesura(tmp_path):
    contenido = _ass(tmp_path, "gamer")
    emojis = [ln for ln in _dialogos(contenido) if ",Emoji," in ln]
    assert emojis
    assert chr(int(json.loads((captions.TIPOGRAFIAS / "emojis.json").read_text(
        encoding="utf-8"))["🏆"], 16)) in emojis[0]      # «gané» -> 🏆
    assert "Style: Emoji,Kevil Emoji," in contenido
    # nunca dos emojis en menos de EMOJI_CADA segundos
    inicios = [captions_time(ln.split(",")[1]) for ln in emojis]
    assert all(b - a >= plantillas.EMOJI_CADA for a, b in zip(inicios, inicios[1:]))


def captions_time(texto):
    h, m, s = texto.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def test_neon_brilla_y_podcast_va_sobre_caja(tmp_path):
    neon = _ass(tmp_path, "neon")
    assert "\\blur" in neon and "\\1a&HFF&" in neon
    assert "Style: Sub,Bebas Neue," in neon and ",0,0,0,0,100,100," in neon   # sin negrita falsa
    podcast = _ass(tmp_path, "podcast")
    cajas = [ln for ln in _dialogos(podcast, capa=1) if "\\p1" in ln]
    assert cajas and "\\fad(" in podcast
    # el texto va con mayúsculas y minúsculas
    assert "Gané" in podcast


def test_personalizado_usa_lo_tuyo(tmp_path):
    contenido = _ass(tmp_path, "", font="Arial", highlight_color="#FF0000", uppercase=False)
    assert "Style: Sub,Arial," in contenido
    assert "&H0000FF&" in contenido                  # tu rojo
    assert "Gané" in contenido
    # y los estilos clásicos siguen ahí
    karaoke = _ass(tmp_path, "", style="karaoke")
    assert "\\fscx108" in karaoke


def test_los_flujos_de_antes_cogen_plantilla_sin_perder_lo_suyo(session):
    from app import bootstrap
    from app.models import Flow, Setting

    def sin_plantilla(nombre, **cambios):
        pasos = default_steps()
        for paso in pasos:
            if paso["type"] == "subtitles":
                paso["config"].pop("template")
                paso["config"].update(cambios)
        return Flow(name=nombre, description="", icon="", steps=pasos)

    de_fabrica = sin_plantilla("Uno")
    tuyo = sin_plantilla("Dos", highlight_color="#00FF00")
    session.add_all([de_fabrica, tuyo])
    session.add(Setting(key=bootstrap.MEJORAS_KEY,
                        value=[k for k in bootstrap.MEJORAS if k != "plantillas-de-rotulos-1"]))
    session.flush()
    bootstrap.actualizar_plantillas(session)
    session.flush()
    assert step_config(de_fabrica.steps, "subtitles")["template"] == "kevil"
    assert step_config(tuyo.steps, "subtitles")["template"] == ""
    assert step_config(tuyo.steps, "subtitles")["highlight_color"] == "#00FF00"


def test_el_esquema_ofrece_las_plantillas():
    campos = {c["key"]: c for c in _paso("subtitles")["fields"]}
    valores = [o["value"] for o in campos["template"]["options"]]
    assert valores[0] == "" and set(plantillas.PLANTILLAS) <= set(valores)
    assert campos["template"]["advanced"] is False


def _paso(tipo):
    from app.flow_schema import STEP_INDEX

    return STEP_INDEX[tipo]


def test_palabras_fuertes_y_emojis():
    assert plantillas.es_fuerte("¡Increíble!") and plantillas.es_fuerte("100")
    assert not plantillas.es_fuerte("partida")
    assert plantillas.emoji_de(["jajaja", "gané"]) == "😂"
    assert plantillas.emoji_de(["nada", "que", "ver"]) == ""
