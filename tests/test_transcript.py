"""Lectura de subtítulos de YouTube (json3 y vtt)."""

import json

from app.services import transcript


def test_parse_json3_con_tiempos_por_palabra(tmp_path):
    data = {
        "events": [
            {
                "tStartMs": 1000,
                "dDurationMs": 1600,
                "segs": [
                    {"utf8": "hola", "tOffsetMs": 0},
                    {"utf8": " "},
                    {"utf8": "mundo", "tOffsetMs": 600},
                ],
            },
            {"tStartMs": 3000, "dDurationMs": 900, "segs": [{"utf8": "[Música]"}]},
            {"tStartMs": 4000, "dDurationMs": 800, "segs": [{"utf8": "adiós", "tOffsetMs": 0}]},
        ]
    }
    path = tmp_path / "sub.es.json3"
    path.write_text(json.dumps(data), encoding="utf-8")

    words = transcript.parse_json3(path)
    assert [w["text"] for w in words] == ["hola", "mundo", "adiós"]
    assert words[0]["start"] == 1.0
    assert words[1]["start"] == 1.6
    # el final de cada palabra nunca invade el inicio de la siguiente
    assert words[0]["end"] <= words[1]["start"]


def test_parse_vtt_con_marcas_en_linea(tmp_path):
    contenido = """WEBVTT

00:00:01.000 --> 00:00:03.000
esto es <00:00:01.500><c>una </c><00:00:02.100><c>prueba</c>

00:00:03.000 --> 00:00:05.000
segunda linea de texto
"""
    path = tmp_path / "sub.es.vtt"
    path.write_text(contenido, encoding="utf-8")

    words = transcript.parse_vtt(path)
    textos = [w["text"] for w in words]
    assert "prueba" in textos
    assert "segunda" in textos
    assert all(w["end"] >= w["start"] for w in words)


def test_agrupacion_en_frases():
    words = [
        {"start": 0.0, "end": 0.3, "text": "hola"},
        {"start": 0.3, "end": 0.7, "text": "mundo."},
        {"start": 4.0, "end": 4.4, "text": "otra"},   # pausa larga: nueva frase
        {"start": 4.4, "end": 4.9, "text": "frase"},
    ]
    segments = transcript.words_to_segments(words)
    assert len(segments) == 2
    assert segments[0]["text"] == "hola mundo."
    assert segments[1]["start"] == 4.0


def test_elegir_archivo_por_idioma_y_formato():
    archivos = ["/x/v.en.vtt", "/x/v.es.vtt", "/x/v.es.json3"]
    assert transcript.pick_subtitle_file(archivos, ["es", "en"]) == "/x/v.es.json3"
    assert transcript.pick_subtitle_file(archivos, ["en"]) == "/x/v.en.vtt"
    assert transcript.pick_subtitle_file([], ["es"]) is None


def test_recorte_de_palabras_relativo_al_clip():
    words = [
        {"start": 10.0, "end": 10.5, "text": "uno"},
        {"start": 11.0, "end": 11.5, "text": "dos"},
        {"start": 30.0, "end": 30.5, "text": "fuera"},
    ]
    trozo = transcript.slice_words(words, 9.5, 12.0)
    assert [w["text"] for w in trozo] == ["uno", "dos"]
    assert trozo[0]["start"] == 0.5


def test_motor_sin_transcripcion():
    resultado = transcript.build_transcript(
        engine="none", media_path="x.mp4", subtitle_files=[], language="es"
    )
    assert resultado["words"] == []
    assert resultado["source"] == "none"
