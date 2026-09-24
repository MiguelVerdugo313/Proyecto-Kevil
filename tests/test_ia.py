"""Proveedores de IA: modelos retirados, la lista real de modelos y varias claves."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import ai

RETIRADO = "meta/llama-3.1-8b-instruct"


class _NIM(BaseHTTPRequestHandler):
    """Imita a NVIDIA NIM: el modelo viejo contesta 410 como en tu captura."""

    pedidos: list[str] = []

    def _json(self, codigo, datos):
        cuerpo = json.dumps(datos).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):  # noqa: N802
        if self.path.endswith("/models"):
            self._json(200, {"data": [
                {"id": "nvidia/nv-embedqa-e5-v5"},          # no es de chat: fuera
                {"id": "meta/llama-3.3-70b-instruct"},
                {"id": "qwen/qwen3-235b-a22b"},
                {"id": "gratis/modelo:free", "pricing": {"prompt": "0", "completion": "0"}},
            ]})
        else:
            self._json(404, {})

    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(largo) or "{}")
        type(self).pedidos.append(cuerpo["model"])
        if cuerpo["model"] == RETIRADO:
            self._json(410, {"type": "about:blank", "title": "Gone", "status": 410,
                             "detail": f"The model '{RETIRADO}' has reached its end of life"})
            return
        self._json(200, {"choices": [{"message": {"content": f"hola desde {cuerpo['model']}"}}]})

    def log_message(self, *_a):
        pass


@pytest.fixture
def nim(monkeypatch):
    servidor = HTTPServer(("127.0.0.1", 0), _NIM)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}/v1"
    _NIM.pedidos = []
    ai._cache_modelos.clear()
    guardados: dict[str, str] = {}
    monkeypatch.setattr(ai, "guardar_modelo", lambda key, modelo: (
        guardados.__setitem__(key, modelo), setattr(settings, f"{key}_text_model", modelo)))
    for campo, valor in {
        "openrouter_api_key": "", "nvidia_api_key": "clave-nim", "nvidia_base_url": base,
        "nvidia_text_model": "otro/que-tambien-se-retiro", "ai_primary": "nvidia",
        "ia_proveedores": [],
    }.items():
        monkeypatch.setattr(settings, campo, valor)
    yield {"base": base, "guardados": guardados}
    servidor.shutdown()


def test_si_el_modelo_se_retiro_se_cambia_solo_y_se_guarda(nim, monkeypatch):
    monkeypatch.setattr(settings, "nvidia_text_model", "otro/retirado-hoy")
    _NIM_retirados = {"otro/retirado-hoy"}

    original = _NIM.do_POST

    def post(self):
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = json.loads(self.rfile.read(largo) or "{}")
        type(self).pedidos.append(cuerpo["model"])
        if cuerpo["model"] in _NIM_retirados:
            self._json(410, {"title": "Gone", "detail": "has reached its end of life"})
            return
        self._json(200, {"choices": [{"message": {"content": f"hola desde {cuerpo['model']}"}}]})

    monkeypatch.setattr(_NIM, "do_POST", post)
    respuesta = ai.chat("hola")
    assert respuesta == "hola desde meta/llama-3.3-70b-instruct"
    assert nim["guardados"]["nvidia"] == "meta/llama-3.3-70b-instruct"   # para la próxima
    assert "se retiró" in ai.status()["model_changes"]["nvidia"]     # y se avisa
    monkeypatch.setattr(_NIM, "do_POST", original)


def test_el_modelo_retirado_de_tu_captura_ni_se_intenta(nim, monkeypatch):
    monkeypatch.setattr(settings, "nvidia_text_model", RETIRADO)
    assert ai.chat("hola").startswith("hola desde meta/llama-3.3-70b-instruct")
    assert RETIRADO not in _NIM.pedidos


def test_la_lista_de_modelos_es_la_real_y_marca_los_gratis(nim):
    proveedor = ai._provider("nvidia")
    modelos = ai.listar_modelos(proveedor)
    ids = [m["id"] for m in modelos]
    assert "nvidia/nv-embedqa-e5-v5" not in ids               # los de embeddings no
    assert ids[0] == "meta/llama-3.3-70b-instruct"            # los recomendados, arriba
    assert len(ids) == 3
    assert next(m for m in modelos if m["id"] == "gratis/modelo:free")["gratis"]


def test_el_error_410_se_explica():
    import httpx

    respuesta = httpx.Response(410, text='{"detail": "has reached its end of life"}')
    assert "retirado" in ai._describe_error(respuesta, RETIRADO)


# --------------------------------------------------------------------------
# Muchas claves de muchos sitios
# --------------------------------------------------------------------------
@pytest.fixture
def cliente(nim):
    from app.main import app
    from tests.test_api import _sin_lifespan

    app.router.lifespan_context = _sin_lifespan
    with TestClient(app) as test_client:
        yield test_client


def test_anadir_proveedores_de_la_lista_y_usarlos_de_reserva(cliente, nim):
    datos = cliente.get("/api/ia").json()
    tipos = {c["tipo"] for c in datos["catalogo"]}
    assert {"groq", "gemini", "mistral", "cerebras", "ollama", "personalizado"} <= tipos

    # una clave de Groq (apunta al servidor falso) y Ollama sin clave
    r = cliente.post("/api/ia/proveedores", json={
        "tipo": "groq", "api_key": "gsk_abcdefghijklmnop1234", "base_url": nim["base"],
        "modelo": "qwen/qwen3-235b-a22b"})
    assert r.status_code == 200, r.text
    groq_id = r.json()["id"]
    r = cliente.post("/api/ia/proveedores", json={"tipo": "ollama", "base_url": nim["base"]})
    assert r.status_code == 200, r.text

    filas = {f["id"]: f for f in cliente.get("/api/ia").json()["proveedores"]}
    assert filas[groq_id]["clave"] == "••••1234"               # nunca la clave entera
    assert "abcdefgh" not in json.dumps(filas)
    assert len(ai.configured_providers()) == 3                  # NVIDIA + Groq + Ollama

    # los modelos de Groq se piden a Groq
    lista = cliente.get(f"/api/ia/modelos?id={groq_id}").json()
    assert lista["modelos"] and not lista["error"]

    # Groq primero
    cliente.post("/api/ia/principal", json={"id": groq_id})
    assert ai.chat("hola") == "hola desde qwen/qwen3-235b-a22b"

    # la clave tapada no pisa la de verdad al guardar
    cliente.patch(f"/api/ia/proveedores/{groq_id}", json={"api_key": "••••1234", "modelo": "x"})
    assert next(i for i in settings.ia_proveedores if i["id"] == groq_id)["api_key"].startswith("gsk_")

    # y se puede quitar
    cliente.delete(f"/api/ia/proveedores/{groq_id}")
    assert groq_id not in {f["id"] for f in cliente.get("/api/ia").json()["proveedores"]}


def test_una_clave_sin_direccion_se_rechaza(cliente):
    r = cliente.post("/api/ia/proveedores", json={"tipo": "personalizado", "api_key": "k"})
    assert r.status_code == 400
    r = cliente.post("/api/ia/proveedores", json={"tipo": "groq"})
    assert r.status_code == 400 and "clave" in r.json()["detail"]
