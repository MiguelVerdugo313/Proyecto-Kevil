"""Pruebas de la API (con el cliente de FastAPI, sin levantar el servidor)."""

import pytest
from fastapi.testclient import TestClient

from app import bootstrap
from app.db import SessionLocal, engine, init_db
from app.models import Base


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as session:
        bootstrap.seed_flows(session)
        session.commit()

    from app.main import app

    # Sin lifespan: no arrancamos hilos ni tareas programadas en las pruebas.
    app.router.lifespan_context = _sin_lifespan
    with TestClient(app) as test_client:
        yield test_client


import contextlib  # noqa: E402


@contextlib.asynccontextmanager
async def _sin_lifespan(_app):
    yield


def test_estado(client):
    datos = client.get("/api/status").json()
    assert datos["version"]
    assert "accounts" in datos


def test_panel(client):
    datos = client.get("/api/dashboard").json()
    assert "counters" in datos and "upcoming" in datos


def test_esquema_de_flujos(client):
    datos = client.get("/api/flows/schema").json()
    tipos = [paso["type"] for paso in datos["steps"]]
    assert {"ingest", "segment", "reframe", "subtitles", "schedule", "publish"} <= set(tipos)
    assert datos["presets"]


def test_ciclo_completo_de_un_flujo(client):
    flujos = client.get("/api/flows").json()
    assert flujos and any(f["is_default"] for f in flujos)

    creado = client.post("/api/flows", json={"name": "Mi flujo", "preset": 1}).json()
    assert creado["name"] == "Mi flujo"
    assert len(creado["steps"]) == len(flujos[0]["steps"])

    pasos = creado["steps"]
    for paso in pasos:
        if paso["type"] == "segment":
            paso["config"]["max_clips"] = 9
        if paso["type"] == "subtitles":
            paso["enabled"] = False

    actualizado = client.put(f"/api/flows/{creado['id']}", json={"steps": pasos}).json()
    segment = next(p for p in actualizado["steps"] if p["type"] == "segment")
    subtitles = next(p for p in actualizado["steps"] if p["type"] == "subtitles")
    assert segment["config"]["max_clips"] == 9
    assert subtitles["enabled"] is False

    duplicado = client.post(f"/api/flows/{creado['id']}/duplicate").json()
    assert duplicado["name"].endswith("(copia)")

    assert client.delete(f"/api/flows/{duplicado['id']}").status_code == 200
    assert client.delete(f"/api/flows/{creado['id']}").status_code == 200


def test_cuenta_manual_y_estrategia(client):
    cuenta = client.post(
        "/api/accounts/tiktok/manual", json={"display_name": "Cuenta test", "handle": "@test"}
    ).json()
    assert cuenta["handle"] == "test"
    assert cuenta["status"] == "needs_auth"

    estrategia = client.get(f"/api/accounts/{cuenta['id']}/strategy").json()
    assert len(estrategia["heatmap"]["matrix"]) == 7
    assert estrategia["state"]["recommended_per_day"] >= 1

    nueva = dict(estrategia["strategy"])
    nueva["max_per_day"] = 5
    nueva["timezone"] = "America/Mexico_City"
    guardada = client.put(f"/api/accounts/{cuenta['id']}/strategy", json=nueva).json()
    assert guardada["strategy"]["max_per_day"] == 5
    assert guardada["strategy"]["timezone"] == "America/Mexico_City"

    huecos = client.post(
        "/api/schedule/plan", json={"account_id": cuenta["id"], "count": 3}
    ).json()
    assert len(huecos) == 3
    assert all(0 <= hueco["score"] <= 1 for hueco in huecos)

    mapa = client.get(f"/api/schedule/heatmap?account_id={cuenta['id']}").json()
    assert len(mapa["days"]) == 7


def test_ajustes(client):
    respuesta = client.put("/api/settings", json={"dry_run": True, "workers": 3}).json()
    assert "dry_run" in respuesta["applied"]
    actual = client.get("/api/settings").json()["settings"]
    assert actual["dry_run"] is True and actual["workers"] == 3
    # el marcador de secreto no debe sobrescribir nada
    client.put("/api/settings", json={"tiktok_client_secret": "••••••••"})
    client.put("/api/settings", json={"dry_run": False})


def test_errores_bien_formados(client):
    assert client.get("/api/clips/999999").status_code == 404
    assert client.get("/api/accounts/999999").status_code == 404
    assert client.post("/api/videos/import", json={"url": "no-es-una-url"}).status_code == 400
