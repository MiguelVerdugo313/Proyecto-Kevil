"""Kevil busca él solo el archivo que Google te descarga."""

from __future__ import annotations

import contextlib
import json
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import bootstrap
from app.db import SessionLocal, engine, init_db
from app.models import Base
from app.services import credenciales

BUENO = {
    "installed": {
        "client_id": "123-abc.apps.googleusercontent.com",
        "project_id": "kevil-studio",
        "client_secret": "GOCSPX-secreto",
    }
}


def _escribir(carpeta, nombre, contenido, *, antiguedad=0.0):
    ruta = carpeta / nombre
    if isinstance(contenido, (dict, list)):
        contenido = json.dumps(contenido)
    ruta.write_text(contenido, encoding="utf-8")
    if antiguedad:
        viejo = time.time() - antiguedad
        os.utime(ruta, (viejo, viejo))
    return ruta


# --------------------------------------------------------------------------
# Leer el archivo
# --------------------------------------------------------------------------
def test_buscar_par_entra_en_cualquier_nivel():
    assert credenciales.buscar_par(BUENO, ("client_id",)).startswith("123-abc")
    assert credenciales.buscar_par([{"a": {"client_secret": "x"}}], ("client_secret",)) == "x"
    assert credenciales.buscar_par({"otra": 3}, ("client_id",)) == ""


def test_leer_solo_acepta_un_archivo_de_google(tmp_path):
    bueno = _escribir(tmp_path, "client_secret_1.json", BUENO)
    assert credenciales.leer(bueno) == (
        "123-abc.apps.googleusercontent.com",
        "GOCSPX-secreto",
    )

    # de otro sitio: no vale
    ajeno = _escribir(tmp_path, "client_secret_2.json", {"client_id": "x.example.com", "client_secret": "y"})
    assert credenciales.leer(ajeno) == ("", "")

    # sin secreto tampoco
    medio = _escribir(tmp_path, "client_secret_3.json", {"client_id": "a.apps.googleusercontent.com"})
    assert credenciales.leer(medio) == ("", "")

    # y lo que no es un JSON no revienta
    roto = _escribir(tmp_path, "client_secret_4.json", "esto no es json")
    assert credenciales.leer(roto) == ("", "")
    assert credenciales.leer(tmp_path / "no-existe.json") == ("", "")


# --------------------------------------------------------------------------
# Encontrar el archivo
# --------------------------------------------------------------------------
def test_candidatos_del_mas_nuevo_al_mas_viejo(tmp_path):
    _escribir(tmp_path, "client_secret_viejo.json", BUENO, antiguedad=9000)
    _escribir(tmp_path, "client_secret_nuevo.json", BUENO)
    _escribir(tmp_path, "vacaciones.json", BUENO)  # nombre que no cuadra

    nombres = [ruta.name for ruta in credenciales.candidatos([tmp_path])]
    assert nombres == ["client_secret_nuevo.json", "client_secret_viejo.json"]


def test_candidatos_ignora_lo_que_no_puede_ser(tmp_path):
    grande = tmp_path / "client_secret_grande.json"
    grande.write_text("x" * (credenciales.TAMANO_MAXIMO + 10), encoding="utf-8")
    (tmp_path / "client_secret_carpeta.json").mkdir()

    assert credenciales.candidatos([tmp_path]) == []
    # una carpeta que no existe no molesta
    assert credenciales.candidatos([tmp_path / "ni-idea"]) == []


def test_buscar_de_google_salta_los_que_no_sirven(tmp_path):
    _escribir(tmp_path, "client_secret_malo.json", {"client_id": "x.example.com", "client_secret": "y"})
    _escribir(tmp_path, "client_secret_bueno.json", BUENO, antiguedad=600)

    hallazgo = credenciales.buscar_de_google([tmp_path])
    assert hallazgo is not None
    ruta, client_id, secreto = hallazgo
    assert ruta.name == "client_secret_bueno.json"
    assert client_id == "123-abc.apps.googleusercontent.com"
    assert secreto == "GOCSPX-secreto"

    assert credenciales.buscar_de_google([tmp_path / "vacia"]) is None


def test_donde_mira_incluye_descargas_y_no_repite(tmp_path, monkeypatch):
    casa = tmp_path / "casa"
    (casa / "Downloads").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("USERPROFILE", str(casa))  # en Windows manda esta
    monkeypatch.setenv("KEVIL_CREDENCIALES_DIR", str(tmp_path / "otro-sitio"))

    carpetas = credenciales.carpetas_donde_mirar()
    nombres = {str(c) for c in carpetas}
    assert str(casa / "Downloads") in nombres
    assert str(casa / "Descargas") in nombres      # y en español
    assert str(tmp_path / "otro-sitio") in nombres
    assert len(nombres) == len(carpetas)           # sin duplicados


# --------------------------------------------------------------------------
# El botón de «buscar el archivo»
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as session:
        bootstrap.seed_flows(session)
        session.commit()

    from app.main import app

    @contextlib.asynccontextmanager
    async def _sin_lifespan(_app):
        yield

    app.router.lifespan_context = _sin_lifespan
    with TestClient(app) as test_client:
        yield test_client


def test_boton_de_buscar_el_archivo(client, tmp_path, monkeypatch):
    monkeypatch.setenv("KEVIL_CREDENCIALES_DIR", str(tmp_path))

    # sin nada que encontrar, un mensaje que dice dónde mirar
    vacio = client.post("/api/credentials/youtube/buscar")
    assert vacio.status_code == 404
    assert "Descargas" in vacio.json()["detail"]

    _escribir(tmp_path, "client_secret_9.json", BUENO)
    try:
        respuesta = client.post("/api/credentials/youtube/buscar")
        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["file"] == "client_secret_9.json"
        assert cuerpo["client_id"] == "123-abc.apps.googleusercontent.com"
        assert cuerpo["ready"] is True

        guardado = client.get("/api/settings").json()["settings"]
        assert guardado["youtube_client_id"] == "123-abc.apps.googleusercontent.com"
        assert guardado["youtube_client_secret"] == "••••••••"
    finally:
        client.put(
            "/api/settings",
            json={"youtube_client_id": "", "youtube_client_secret": ""},
        )
