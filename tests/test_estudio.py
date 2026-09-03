"""Kit de publicación, miniaturas y conector de inteligencia artificial."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.config import settings
from app.services import ai, seo, thumbnails
from app.services import media as media_service


# --------------------------------------------------------------------------
# Un servidor falso compatible con OpenAI, para probar el cliente de verdad
# --------------------------------------------------------------------------
RESPUESTA_KIT = {
    "titles": ["Un título de prueba bastante razonable", "Otro título distinto"],
    "description": "Gancho de dos líneas.\nSegunda línea.\n\nCuerpo de la descripción con "
                   "bastante texto para que pase la revisión de longitud mínima sin problema "
                   "ninguno, porque si no salta el aviso correspondiente.",
    "chapters": [
        {"time": 0, "title": "Intro"},
        {"time": 3, "title": "Demasiado pegado al anterior"},
        {"time": "0:40", "title": "Desarrollo"},
        {"time": 70, "title": "Cierre"},
        {"time": 9999, "title": "Fuera del vídeo"},
    ],
    "tags": ["etiqueta uno", "etiqueta dos", "etiqueta tres"],
    "hashtags": ["Uno", "#dos", "tres", "cuatro"],
    "thumbnail_texts": ["texto miniatura"],
    "thumbnail_prompt": "a cinematic shot",
    "notes": "Un consejo",
}


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(largo) or "{}")
        prompt = cuerpo["messages"][-1]["content"]

        if "LISTO" in prompt:
            contenido = "LISTO"
        elif "ideas de vídeo" in prompt:
            contenido = json.dumps({"ideas": [{"topic": "tema uno", "title": "Título uno"}]})
        else:
            # a propósito envuelto en un bloque de código y con texto alrededor
            contenido = "Aquí tienes:\n```json\n" + json.dumps(RESPUESTA_KIT) + "\n```\nUn saludo."

        datos = json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": contenido}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, *_args):  # silencio en las pruebas
        pass


@pytest.fixture
def fake_ai():
    servidor = HTTPServer(("127.0.0.1", 0), _Handler)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    puerto = servidor.server_address[1]

    anterior = (
        settings.ai_provider, settings.ai_api_key,
        settings.ai_text_model, settings.ai_base_url,
    )
    settings.ai_provider = "openrouter"
    settings.ai_api_key = "clave-de-prueba"
    settings.ai_text_model = "modelo-falso"
    settings.ai_base_url = f"http://127.0.0.1:{puerto}/v1"
    try:
        yield
    finally:
        (settings.ai_provider, settings.ai_api_key,
         settings.ai_text_model, settings.ai_base_url) = anterior
        servidor.shutdown()


TRANSCRIPCION = {
    "segments": [
        {"start": i * 10, "end": i * 10 + 8, "text": f"Frase número {i} sobre el tema del vídeo."}
        for i in range(12)
    ],
    "words": [{"start": i, "end": i + 0.4, "text": "palabra"} for i in range(60)],
    "source": "test",
}


# --------------------------------------------------------------------------
# Conector de IA
# --------------------------------------------------------------------------
def test_sin_configurar_no_esta_activa():
    assert ai.is_enabled() is False
    with pytest.raises(ai.AINotConfigured):
        ai.chat("hola")


def test_conexion_y_estado(fake_ai):
    assert ai.is_enabled() is True
    resultado = ai.test_connection()
    assert resultado["ok"] and resultado["answer"] == "LISTO"
    estado = ai.status()
    assert estado["enabled"] and estado["provider"] == "openrouter"
    assert "openrouter" in estado["providers"] and "nvidia" in estado["providers"]


def test_extraer_json_entre_texto():
    assert ai.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai.extract_json('Claro: {"a": 2} ¿algo más?') == {"a": 2}
    assert ai.extract_json('[1, 2, 3]') == [1, 2, 3]
    with pytest.raises(ai.AIError):
        ai.extract_json("no hay json por aquí")


# --------------------------------------------------------------------------
# Kit de publicación
# --------------------------------------------------------------------------
def test_kit_local_sin_ia():
    kit = seo.build_kit(
        title="Cómo montar una granja en Minecraft",
        transcript=TRANSCRIPCION,
        duration=600,
        use_ai=False,
    )
    assert kit["generated_by"] == "local"
    assert kit["titles"]
    assert kit["description"]
    assert kit["tags"]
    # «cómo» es palabra vacía aunque lleve tilde
    assert "cómo" not in kit["tags"] and "como" not in kit["tags"]
    assert len(kit["chapters"]) >= 3
    assert kit["chapters"][0]["time"] == 0


def test_kit_con_ia_limpia_la_respuesta(fake_ai):
    kit = seo.build_kit(
        title="Título original", transcript=TRANSCRIPCION, duration=120, use_ai=True
    )
    assert kit["generated_by"].startswith("ia:")
    assert kit["warning"] == ""

    tiempos = [c["time"] for c in kit["chapters"]]
    assert tiempos[0] == 0                 # el primero siempre en 00:00
    assert 3 not in tiempos                # descartado: muy pegado al anterior
    assert 40 in tiempos                   # "0:40" convertido a segundos
    assert all(t <= 120 for t in tiempos)  # nada más allá del final del vídeo

    assert len(kit["hashtags"]) <= 3
    assert all(h == h.lower() and "#" not in h for h in kit["hashtags"])
    assert "⏱️ Capítulos" in kit["description"]
    assert kit["description"].rstrip().endswith("#tres") or "#" in kit["description"]


def test_la_revision_detecta_problemas():
    flojo = {
        "titles": ["Un título larguísimo que se pasa de la raya y se va a cortar seguro en el móvil"],
        "description": "corta",
        "tags": ["una"],
        "hashtags": ["a", "b", "c", "d"],
        "chapters": [],
    }
    avisos = seo.review_kit(flojo, duration=600)
    textos = " ".join(a["text"] for a in avisos)
    assert any(a["level"] == "warn" for a in avisos)
    assert "caracteres" in textos and "etiquetas" in textos
    assert "hashtags" in textos and "capítulos" in textos.lower() or "Capítulos" in textos


def test_marcas_de_tiempo():
    assert seo.timestamp(0) == "0:00"
    assert seo.timestamp(75) == "1:15"
    assert seo.timestamp(3725) == "1:02:05"


# --------------------------------------------------------------------------
# Miniaturas
# --------------------------------------------------------------------------
@pytest.mark.skipif(not media_service.ffmpeg_ready(), reason="ffmpeg no está instalado")
def test_miniaturas_reales(tmp_path):
    origen = tmp_path / "origen.mp4"
    media_service.make_test_video(origen, seconds=20)

    puntuados = thumbnails.score_frames(origen, duration=20, samples=10)
    assert puntuados
    assert all(0 <= f["score"] <= 1 for f in puntuados)

    elegidos = thumbnails.pick_frames(puntuados, count=2, min_gap=3)
    assert 1 <= len(elegidos) <= 2

    resultados = thumbnails.generate(
        video_path=origen,
        duration=20,
        texts=["PRUEBA UNO", "PRUEBA DOS"],
        out_dir=tmp_path / "salida",
        prefix="test",
        count=2,
    )
    assert resultados
    for resultado in resultados:
        assert resultado["path"]
        info = media_service.probe(resultado["path"])
        assert info["width"] == 1280 and info["height"] == 720


def test_colores_y_alfa_de_las_bandas():
    from app.services import captions

    assert captions.override_color("#28E7C5") == "&HC5E728&"
    assert captions.override_alpha(0) == "&H00&"
    assert captions.override_alpha(255) == "&HFF&"
    assert captions.override_alpha(999) == "&HFF&"
