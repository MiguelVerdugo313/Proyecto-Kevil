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


# --------------------------------------------------------------------------
# Estudio y coach
# --------------------------------------------------------------------------
def test_subir_video_y_generar_kit(client, tmp_path):
    import pytest

    from app.services import media as media_service

    if not media_service.ffmpeg_ready():
        pytest.skip("ffmpeg no está instalado")

    origen = tmp_path / "corto.mp4"
    media_service.make_test_video(origen, seconds=6)

    with origen.open("rb") as archivo:
        respuesta = client.post(
            "/api/videos/upload",
            files={"file": ("mi vídeo.mp4", archivo, "video/mp4")},
            data={"title": "Mi vídeo de prueba", "use_ai": "false"},
        )
    assert respuesta.status_code == 200
    video = respuesta.json()
    assert video["title"] == "Mi vídeo de prueba"
    assert video["downloaded"] is True

    # formato no admitido
    malo = client.post(
        "/api/videos/upload",
        files={"file": ("documento.txt", b"hola", "text/plain")},
    )
    assert malo.status_code == 400

    # el kit todavía no existe, pero el endpoint responde
    kit = client.get(f"/api/videos/{video['id']}/kit").json()
    assert kit["kit"] == {}
    assert "ai" in kit

    # se puede editar a mano
    guardado = client.patch(
        f"/api/videos/{video['id']}/kit",
        json={"description": "Una descripción escrita a mano", "tags": ["uno", "dos"]},
    ).json()
    assert guardado["kit"]["description"].startswith("Una descripción")
    assert guardado["kit"]["review"]


def test_endpoints_del_coach(client):
    coach = client.get("/api/coach").json()
    assert "state" in coach and "stats" in coach and len(coach["days"]) == 7

    avisos = client.get("/api/notifications").json()
    assert "unread" in avisos and "items" in avisos

    assert client.get("/api/ideas").json() == []
    assert client.get("/api/ai/status").json()["enabled"] is False
    # sin clave configurada, probar la conexión debe fallar con un mensaje claro
    assert client.post("/api/ai/test").status_code == 400


def test_ajustes_de_ia_y_canal(client):
    client.put(
        "/api/settings",
        json={
            "ai_provider": "nvidia",
            "ai_api_key": "clave-secreta",
            "channel_topic": "Minecraft",
            "target_uploads_per_week": 3,
        },
    )
    actual = client.get("/api/settings").json()["settings"]
    assert actual["ai_provider"] == "nvidia"
    assert actual["ai_api_key"] == "••••••••"        # la clave nunca se devuelve
    assert actual["channel_topic"] == "Minecraft"
    assert actual["target_uploads_per_week"] == 3
    client.put("/api/settings", json={"ai_provider": "", "ai_api_key": ""})


def test_migracion_anade_columnas_que_faltan(client):
    """Una base de datos de una versión anterior debe seguir funcionando."""
    from sqlalchemy import text

    from app.db import _add_missing_columns, engine

    with engine.begin() as conexion:
        conexion.execute(text("ALTER TABLE videos DROP COLUMN kit"))
        columnas = {r[1] for r in conexion.execute(text("PRAGMA table_info('videos')"))}
        assert "kit" not in columnas

    _add_missing_columns()

    with engine.begin() as conexion:
        columnas = {r[1] for r in conexion.execute(text("PRAGMA table_info('videos')"))}
    assert {"kit", "origin", "views", "likes"} <= columnas
    assert client.get("/api/status").status_code == 200
