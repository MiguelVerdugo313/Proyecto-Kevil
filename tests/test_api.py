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
    try:
        client.put(
            "/api/settings",
            json={
                "openrouter_api_key": "clave-openrouter",
                "nvidia_api_key": "clave-nvidia",
                "ai_primary": "nvidia",
                "channel_topic": "Minecraft",
                "target_uploads_per_week": 3,
            },
        )
        actual = client.get("/api/settings").json()["settings"]
        assert actual["ai_primary"] == "nvidia"
        # las claves nunca se devuelven, ni la principal ni la de respaldo
        assert actual["openrouter_api_key"] == "••••••••"
        assert actual["nvidia_api_key"] == "••••••••"
        assert actual["channel_topic"] == "Minecraft"
        assert actual["target_uploads_per_week"] == 3

        # con las dos claves puestas, la IA está activa y tiene respaldo
        estado = client.get("/api/ai/status").json()
        assert estado["enabled"] is True
        assert estado["has_backup"] is True
        # el principal va primero, el otro queda de reserva
        assert [p["key"] for p in estado["active"]] == ["nvidia", "openrouter"]
        assert estado["providers"]["nvidia"]["configured"] is True
        assert estado["providers"]["openrouter"]["configured"] is True
    finally:
        client.put(
            "/api/settings",
            json={
                "openrouter_api_key": "",
                "nvidia_api_key": "",
                "ai_primary": "openrouter",
            },
        )
    assert client.get("/api/ai/status").json()["enabled"] is False


def test_migracion_de_la_ia_antigua(client):
    """Una instalación vieja (un solo proveedor) pasa sola al formato nuevo."""
    from app.bootstrap import migrate_ai_settings
    from app.db import session_scope
    from app.models import Setting

    with session_scope() as sesion:
        for clave in ("openrouter_api_key", "nvidia_api_key", "ai_primary"):
            fila = sesion.get(Setting, clave)
            if fila is not None:
                sesion.delete(fila)
        sesion.add(Setting(key="ai_provider", value="nvidia"))
        sesion.add(Setting(key="ai_api_key", value="clave-vieja"))
        sesion.add(Setting(key="ai_text_model", value="modelo/viejo"))

    with session_scope() as sesion:
        migrate_ai_settings(sesion)

    with session_scope() as sesion:
        assert sesion.get(Setting, "nvidia_api_key").value == "clave-vieja"
        assert sesion.get(Setting, "ai_primary").value == "nvidia"
        assert sesion.get(Setting, "nvidia_text_model").value == "modelo/viejo"
        # y no se vuelve a migrar por encima de lo que el usuario cambie después
        sesion.get(Setting, "nvidia_api_key").value = "clave-nueva"

    with session_scope() as sesion:
        migrate_ai_settings(sesion)
    with session_scope() as sesion:
        assert sesion.get(Setting, "nvidia_api_key").value == "clave-nueva"

    # dejar los ajustes como estaban para el resto de pruebas
    from app.config import settings

    with session_scope() as sesion:
        for clave in ("ai_provider", "ai_api_key", "ai_text_model",
                      "nvidia_api_key", "nvidia_text_model", "ai_primary"):
            fila = sesion.get(Setting, clave)
            if fila is not None:
                sesion.delete(fila)
    settings.nvidia_api_key = ""
    settings.nvidia_text_model = ""
    settings.ai_primary = "openrouter"


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


def test_pegar_el_json_de_google(client):
    """El archivo que descarga Google se pega tal cual y se saca lo necesario."""
    archivo = {
        "web": {
            "client_id": "123-abc.apps.googleusercontent.com",
            "project_id": "kevil-studio",
            "client_secret": "GOCSPX-secreto",
            "redirect_uris": ["http://127.0.0.1:8756/api/oauth/youtube/callback"],
        }
    }
    import json as _json

    respuesta = client.post("/api/credentials/youtube", json={"text": _json.dumps(archivo)})
    assert respuesta.status_code == 200
    assert respuesta.json()["ready"] is True

    guardado = client.get("/api/settings").json()["settings"]
    assert guardado["youtube_client_id"] == "123-abc.apps.googleusercontent.com"
    assert guardado["youtube_client_secret"] == "••••••••"      # nunca se devuelve

    # también vale el formato «installed» (app de escritorio)
    escritorio = {"installed": dict(archivo["web"])}
    assert client.post(
        "/api/credentials/youtube", json={"text": _json.dumps(escritorio)}
    ).status_code == 200

    # y lo que no es el archivo se rechaza con un mensaje que se entiende
    malo = client.post("/api/credentials/youtube", json={"text": "hola"})
    assert malo.status_code == 400
    assert "archivo de Google" in malo.json()["detail"]

    sin_secreto = client.post(
        "/api/credentials/youtube", json={"text": '{"web":{"client_id":"x.apps.googleusercontent.com"}}'}
    )
    assert sin_secreto.status_code == 400

    otro_sitio = client.post(
        "/api/credentials/youtube",
        json={"text": '{"client_id":"123.example.com","client_secret":"x"}'},
    )
    assert otro_sitio.status_code == 400

    client.put("/api/settings", json={"youtube_client_id": "", "youtube_client_secret": ""})


def test_pegar_las_claves_de_tiktok(client):
    """Se acepta el pegado tal cual salga de la pantalla de TikTok."""
    con_etiquetas = "Client key: awabcdefghij\nClient secret: secretoxxxxxxxx"
    respuesta = client.post("/api/credentials/tiktok", json={"text": con_etiquetas})
    assert respuesta.status_code == 200
    assert respuesta.json()["client_key"] == "awabcdefghij"
    assert respuesta.json()["ready"] is True

    guardado = client.get("/api/settings").json()["settings"]
    assert guardado["tiktok_client_key"] == "awabcdefghij"
    assert guardado["tiktok_client_secret"] == "••••••••"

    # sin etiquetas, dos valores sueltos: el primero es la clave
    suelto = client.post(
        "/api/credentials/tiktok", json={"text": "awzzzzzzzzzz\notrosecreto123"}
    )
    assert suelto.status_code == 200
    assert suelto.json()["client_key"] == "awzzzzzzzzzz"

    assert client.post("/api/credentials/tiktok", json={"text": ""}).status_code == 400
    # un solo valor no se puede repartir
    assert client.post(
        "/api/credentials/tiktok", json={"text": "solounacosa123"}
    ).status_code == 400

    client.put("/api/settings", json={"tiktok_client_key": "", "tiktok_client_secret": ""})


def test_el_piloto_automatico_no_se_enciende_a_medias(client):
    """Sin canal ni destino no se puede publicar solo: hay que decirlo."""
    estado = client.get("/api/autopilot").json()
    assert estado["enabled"] is False
    assert estado["missing"]

    fallo = client.post("/api/autopilot", json={"enabled": True})
    assert fallo.status_code == 400
    assert "le falta" in fallo.json()["detail"]

    # y sigue apagado, no a medio encender
    assert client.get("/api/autopilot").json()["enabled"] is False


def test_pegar_una_direccion_donde_van_las_claves_avisa(client):
    """Es fácil confundir la URL de retorno con las claves: hay que decirlo."""
    confusion = client.post(
        "/api/credentials/tiktok",
        json={"text": "http://127.0.0.1:8756/api/oauth/tiktok/callback\nwn1p6HPIKykY1IgN"},
    )
    assert confusion.status_code == 400
    detalle = confusion.json()["detail"]
    assert "una dirección web" in detalle
    assert "Redirect URI" in detalle          # y dice dónde va de verdad

    # y también si la dirección viene en la casilla de la clave
    en_la_casilla = client.post(
        "/api/credentials/tiktok",
        json={"client_key": "http://127.0.0.1:8756/api/oauth/tiktok/callback",
              "client_secret": "wn1p6HPIKykY1IgN"},
    )
    assert en_la_casilla.status_code == 400


def test_las_claves_de_tiktok_en_sus_dos_casillas(client):
    """Lo normal ahora: cada clave en su campo, sin adivinar nada."""
    try:
        bien = client.post(
            "/api/credentials/tiktok",
            json={"client_key": "awabcdefghij", "client_secret": "secretolargo12345"},
        )
        assert bien.status_code == 200
        assert bien.json()["client_key"] == "awabcdefghij"
        assert bien.json()["ready"] is True

        # las dos iguales es casi siempre un copiar y pegar mal hecho
        repetida = client.post(
            "/api/credentials/tiktok",
            json={"client_key": "awabcdefghij", "client_secret": "awabcdefghij"},
        )
        assert repetida.status_code == 400
        assert "lo mismo" in repetida.json()["detail"]

        # y media clave tampoco vale
        corta = client.post(
            "/api/credentials/tiktok", json={"client_key": "aw", "client_secret": "x"}
        )
        assert corta.status_code == 400

        falta = client.post("/api/credentials/tiktok", json={"client_key": "awabcdefghij"})
        assert falta.status_code == 400
    finally:
        client.put(
            "/api/settings", json={"tiktok_client_key": "", "tiktok_client_secret": ""}
        )


def test_el_motor_propone_la_hora_del_clip_y_se_respeta(client):
    """En la ficha del clip la fecha viene ya puesta con la hora que elige el motor."""
    from app.models import Account, AccountStatus, Clip, Platform, Post, Video

    with SessionLocal() as db:
        cuenta = Account(platform=Platform.tiktok.value, display_name="K", handle="k",
                         external_id="prop-1", status=AccountStatus.connected.value,
                         strategy={"timezone": "America/Bogota"})
        video = Video(external_id="prop-v", title="V", url="x")
        db.add_all([cuenta, video])
        db.flush()
        clip = Clip(video_id=video.id, index=1, title="C", start_s=0, end_s=30,
                    status="rendered")
        db.add(clip)
        db.commit()
        clip_id, cuenta_id = clip.id, cuenta.id

    datos = client.get(f"/api/clips/{clip_id}/propuesta?account_id={cuenta_id}").json()
    assert datos["scheduled_at"].endswith("Z")
    assert "m." in datos["reason"]                  # «8:30 p. m.», en formato de 12 h

    r = client.post(f"/api/clips/{clip_id}/approve", json={
        "account_id": cuenta_id, "scheduled_at": datos["scheduled_at"],
        "slot_reason": datos["reason"],
    })
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        post = db.query(Post).filter(Post.clip_id == clip_id).one()
        assert post.slot_reason == datos["reason"]   # sigue siendo del motor, no «a mano»
        assert post.scheduled_at.isoformat()[:16] == datos["scheduled_at"][:16]


def test_el_motor_dice_que_toca_despues(client):
    """«Sin tareas activas» no puede parecer que está parado: dice qué viene."""
    from datetime import timedelta

    from app.models import Account, AccountStatus, Clip, Platform, Post, Source, Video, utcnow

    with SessionLocal() as db:
        db.add(Source(name="Kevil", url="https://www.youtube.com/@kevil",
                      last_checked_at=utcnow() - timedelta(minutes=5)))
        cuenta = Account(platform=Platform.tiktok.value, display_name="K", handle="k2",
                         external_id="motor-1", status=AccountStatus.connected.value)
        video = Video(external_id="motor-v", title="V", url="x")
        db.add_all([cuenta, video])
        db.flush()
        clip = Clip(video_id=video.id, index=1, title="El clip que sale luego",
                    start_s=0, end_s=30)
        db.add(clip)
        db.flush()
        db.add(Post(clip_id=clip.id, account_id=cuenta.id,
                    scheduled_at=utcnow() + timedelta(hours=3)))
        db.commit()

    motor = client.get("/api/status").json()["motor"]
    assert motor["canales"] >= 1
    assert motor["proxima_revision"]                    # cuándo vuelve a mirar el canal
    assert motor["proxima_publicacion"]
    assert motor["proxima_publicacion_titulo"]
