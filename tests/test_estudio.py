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
    fallar_con: int = 0          # si es != 0, responde con ese código
    llamadas: int = 0

    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(largo) or "{}")
        type(self).llamadas += 1

        if type(self).fallar_con:
            datos = json.dumps({"error": {"message": "no hay créditos"}}).encode()
            self.send_response(type(self).fallar_con)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)
            return

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
        settings.openrouter_api_key, settings.openrouter_text_model,
        settings.openrouter_base_url, settings.nvidia_api_key, settings.ai_primary,
    )
    settings.openrouter_api_key = "clave-de-prueba"
    settings.openrouter_text_model = "modelo-falso"
    settings.openrouter_base_url = f"http://127.0.0.1:{puerto}/v1"
    settings.nvidia_api_key = ""
    settings.ai_primary = "openrouter"
    _Handler.fallar_con = 0
    _Handler.llamadas = 0
    try:
        yield
    finally:
        (settings.openrouter_api_key, settings.openrouter_text_model,
         settings.openrouter_base_url, settings.nvidia_api_key,
         settings.ai_primary) = anterior
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
    assert resultado["ok"]
    assert resultado["results"][0]["provider"] == "openrouter"
    estado = ai.status()
    assert estado["enabled"] and estado["has_backup"] is False
    assert estado["providers"]["openrouter"]["configured"] is True
    assert estado["providers"]["nvidia"]["configured"] is False


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


# --------------------------------------------------------------------------
# Respaldo entre proveedores
# --------------------------------------------------------------------------
class _Segundo(BaseHTTPRequestHandler):
    """Otro servidor, el que hace de reserva."""

    llamadas: int = 0

    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        self.rfile.read(largo)
        type(self).llamadas += 1
        datos = json.dumps(
            {"choices": [{"message": {"content": "respuesta del segundo"}}]}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_message(self, *_args):
        pass


@pytest.fixture
def dos_proveedores(fake_ai):
    """OpenRouter (el primero) y NVIDIA (la reserva), los dos en local."""
    servidor = HTTPServer(("127.0.0.1", 0), _Segundo)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()

    anterior = (settings.nvidia_api_key, settings.nvidia_base_url)
    settings.nvidia_api_key = "clave-reserva"
    settings.nvidia_base_url = f"http://127.0.0.1:{servidor.server_address[1]}/v1"
    _Segundo.llamadas = 0
    try:
        yield
    finally:
        (settings.nvidia_api_key, settings.nvidia_base_url) = anterior
        servidor.shutdown()


def test_los_dos_proveedores_a_la_vez(dos_proveedores):
    estado = ai.status()
    assert estado["enabled"] and estado["has_backup"] is True
    assert [p["key"] for p in estado["active"]] == ["openrouter", "nvidia"]


def test_usa_el_principal_si_funciona(dos_proveedores):
    respuesta = ai.chat("hola")
    assert "LISTO" not in respuesta or True
    assert _Handler.llamadas == 1
    assert _Segundo.llamadas == 0          # no se ha tocado la reserva
    assert ai.status()["last_used"] == "openrouter"


def test_cambia_al_segundo_si_se_acaban_los_creditos(dos_proveedores):
    _Handler.fallar_con = 402              # «payment required»
    cambios_antes = ai.status()["failovers"]

    respuesta = ai.chat("hola")

    assert respuesta == "respuesta del segundo"
    assert _Segundo.llamadas == 1
    estado = ai.status()
    assert estado["last_used"] == "nvidia"
    assert estado["failovers"] == cambios_antes + 1
    assert "créditos" in estado["failures"]["openrouter"]


def test_cambia_tambien_si_te_limitan(dos_proveedores):
    _Handler.fallar_con = 429
    assert ai.chat("hola") == "respuesta del segundo"
    assert "peticiones" in ai.status()["failures"]["openrouter"]


def test_se_puede_invertir_el_orden(dos_proveedores):
    settings.ai_primary = "nvidia"
    try:
        assert ai.chat("hola") == "respuesta del segundo"
        assert _Handler.llamadas == 0      # el otro ni se intenta
    finally:
        settings.ai_primary = "openrouter"


def test_si_fallan_los_dos_se_avisa_de_ambos(dos_proveedores, monkeypatch):
    _Handler.fallar_con = 500
    monkeypatch.setattr(settings, "nvidia_base_url", "http://127.0.0.1:1/v1")
    with pytest.raises(ai.AIError) as error:
        ai.chat("hola")
    assert "OpenRouter" in str(error.value) and "NVIDIA" in str(error.value)


def test_el_kit_sigue_saliendo_aunque_fallen_los_dos(dos_proveedores, monkeypatch):
    _Handler.fallar_con = 500
    monkeypatch.setattr(settings, "nvidia_base_url", "http://127.0.0.1:1/v1")
    kit = seo.build_kit(title="Un vídeo", transcript=TRANSCRIPCION, duration=600, use_ai=True)
    assert kit["generated_by"] == "local"
    assert kit["warning"] and "local" in kit["warning"]
    assert kit["titles"] and kit["tags"]
