"""El canal autorizado se vigila, el plan B al listar y dónde sale cada clip."""

import contextlib
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import bootstrap
from app.db import SessionLocal, engine, init_db
from app.models import Account, Base, Clip, Flow, Job, Platform, Source, Video
from app.services import canales, destinos, pipeline, youtube_api

CANAL = "UC" + "k" * 22


@contextlib.asynccontextmanager
async def _sin_lifespan(_app):
    yield


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as session:
        bootstrap.seed_flows(session)
        session.commit()
    from app.main import app

    app.router.lifespan_context = _sin_lifespan
    with TestClient(app) as test_client:
        yield test_client


def _cuenta_youtube(session, *, token=True):
    cuenta = Account(
        platform=Platform.youtube.value,
        display_name="Kevil",
        external_id=CANAL,
        credentials={"access_token": "x", "expires_at": 9e12} if token else {},
    )
    session.add(cuenta)
    session.flush()
    return cuenta


# ------------------------------------------------------------ vigilar
def test_el_canal_autorizado_se_vigila_al_abrir(session):
    cuenta = _cuenta_youtube(session)
    assert canales.cuentas_sin_vigilar(session) == [cuenta]

    assert canales.vigilar_los_conectados(session) == 1
    fuente = canales.fuente_de(session, cuenta)
    assert fuente.channel_id == CANAL
    assert fuente.url.endswith(f"/channel/{CANAL}")
    assert fuente.auto_ingest and fuente.include_lives
    assert session.query(Job).filter_by(kind="sync_source").count() == 1
    assert canales.cuentas_sin_vigilar(session) == []

    # la segunda vez no se duplica
    assert canales.vigilar_los_conectados(session) == 0


def test_si_lo_quitas_no_vuelve_solo(client):
    with SessionLocal() as session:
        cuenta = _cuenta_youtube(session)
        fuente = canales.vigilar(session, cuenta)
        session.commit()
        fuente_id, cuenta_id = fuente.id, cuenta.id

    assert client.delete(f"/api/sources/{fuente_id}").status_code == 200
    with SessionLocal() as session:
        assert canales.vigilar_los_conectados(session) == 0
        assert canales.cuentas_sin_vigilar(session) == []

    # pero si lo pides tú, sí
    respuesta = client.post(f"/api/accounts/{cuenta_id}/vigilar")
    assert respuesta.status_code == 200
    assert respuesta.json()["channel_id"] == CANAL


def test_conectar_la_url_de_un_canal_ya_autorizado_lo_vigila(client, monkeypatch):
    with SessionLocal() as session:
        _cuenta_youtube(session)
        session.commit()
    monkeypatch.setattr(
        "app.services.youtube.resolve_channel",
        lambda url: {"channel_id": CANAL, "name": "Kevil", "handle": "@kevil",
                     "url": f"https://www.youtube.com/channel/{CANAL}", "avatar_url": "",
                     "subscribers": 24000},
    )
    respuesta = client.post("/api/accounts/youtube", json={"url": "@kevil", "backfill_limit": 7})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["source"]["backfill_limit"] == 7

    # y ahora sí dice que ya está
    otra = client.post("/api/accounts/youtube", json={"url": "@kevil"})
    assert otra.status_code == 409


def test_el_motor_avisa_del_canal_sin_vigilar(client):
    with SessionLocal() as session:
        _cuenta_youtube(session)
        session.commit()
    motor = client.get("/api/status").json()["motor"]
    assert motor["canales"] == 0
    assert motor["sin_vigilar"][0]["nombre"] == "Kevil"


# ------------------------------------------------------------ plan B
def test_si_yt_dlp_no_puede_se_lista_por_la_api(session, monkeypatch):
    bootstrap.seed_flows(session)
    cuenta = _cuenta_youtube(session)
    fuente = canales.vigilar(session, cuenta)
    session.commit()

    def bloqueado(*_a, **_k):
        raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setattr("app.services.youtube.list_channel_videos", bloqueado)
    monkeypatch.setattr(youtube_api, "fetch_uploads", lambda c, limit=50: [
        {"id": "directo1", "title": "Directo de ayer", "published_at": "2026-09-20T20:00:00"},
        {"id": "short1", "title": "Un short", "published_at": "2026-09-19T20:00:00"},
        {"id": "ahora", "title": "En directo", "published_at": "2026-09-21T20:00:00"},
    ])
    monkeypatch.setattr(youtube_api, "fetch_video_details", lambda c, ids: {
        "directo1": {"duration_s": 7200, "was_live": True, "en_directo": False},
        "short1": {"duration_s": 40, "was_live": False, "en_directo": False},
        "ahora": {"duration_s": 0, "was_live": True, "en_directo": True},
    })
    monkeypatch.setattr(pipeline, "_es_short", lambda video_id: video_id == "short1")

    class Ctx:
        payload = {"source_id": fuente.id}

        def progress(self, *_a, **_k):
            pass

    pipeline.job_sync_source(session, Ctx())
    titulos = [v.title for v in session.query(Video).all()]
    assert titulos == ["Directo de ayer"]
    video = session.query(Video).one()
    assert video.was_live and video.duration_s == 7200
    assert video.published_at == datetime(2026, 9, 20, 20)


def test_sin_plan_b_el_error_se_ve(session, monkeypatch):
    bootstrap.seed_flows(session)
    fuente = Source(name="Otro", url="https://www.youtube.com/@otro", kind="channel")
    session.add(fuente)
    session.commit()

    def bloqueado(*_a, **_k):
        raise RuntimeError("Sign in to confirm you're not a bot")

    monkeypatch.setattr("app.services.youtube.list_channel_videos", bloqueado)

    class Ctx:
        payload = {"source_id": fuente.id}

        def progress(self, *_a, **_k):
            pass

    with pytest.raises(RuntimeError):
        pipeline.job_sync_source(session, Ctx())
    assert "bot" in fuente.last_error


def test_duracion_iso():
    assert youtube_api.duracion_iso("PT1H2M3S") == 3723
    assert youtube_api.duracion_iso("PT45S") == 45
    assert youtube_api.duracion_iso("P0D") == 0
    assert youtube_api.duracion_iso("raro") == 0


# ------------------------------------------------------------ destinos
def test_destinos_se_ven_y_se_cambian(client):
    with SessionLocal() as session:
        _cuenta_youtube(session)
        session.add(Account(platform=Platform.tiktok.value, display_name="Kevil",
                            handle="the_kevil", external_id="tt"))
        session.commit()
        defecto = session.query(Flow).filter_by(is_default=True).one()

    datos = client.get("/api/destinos").json()
    assert datos["youtube"]["nombre"] == "Kevil"
    assert datos["tiktok"][0]["nombre"] == "@the_kevil"
    fila = next(f for f in datos["flujos"] if f["id"] == defecto.id)
    assert fila["en_uso"] and fila["tiktok"] and not fila["shorts"]

    datos = client.put(f"/api/destinos/{defecto.id}", json={"shorts": True}).json()
    fila = next(f for f in datos["flujos"] if f["id"] == defecto.id)
    assert fila["shorts"] and fila["tiktok"]


def test_el_clip_marca_tiktok_y_shorts_segun_su_flujo(session):
    tiktok = Account(platform=Platform.tiktok.value, display_name="Kevil",
                     handle="the_kevil", external_id="tt")
    session.add(tiktok)
    youtube = _cuenta_youtube(session)
    bootstrap.seed_flows(session)
    session.flush()
    flujo = session.query(Flow).filter_by(name="Clips a TikTok y Shorts").one()
    video = Video(external_id="v1", title="V", url="u")
    session.add(video)
    session.flush()
    corto = Clip(video_id=video.id, flow_id=flujo.id, start_s=0, end_s=60)
    largo = Clip(video_id=video.id, flow_id=flujo.id, start_s=0, end_s=240)
    session.add_all([corto, largo])
    session.flush()

    datos = destinos.para_clip(session, corto)
    marcadas = {c["plataforma"]: c["marcada"] for c in datos["cuentas"]}
    assert marcadas == {"tiktok": True, "youtube": True}

    # más de 3 minutos no sería un Short: no se marca y se explica
    datos = destinos.para_clip(session, largo)
    shorts = next(c for c in datos["cuentas"] if c["plataforma"] == "youtube")
    assert not shorts["marcada"] and "3 minutos" in shorts["aviso"]

    # sin permiso de subida se ve, pero no se puede marcar
    youtube.credentials = {}
    datos = destinos.para_clip(session, corto)
    shorts = next(c for c in datos["cuentas"] if c["plataforma"] == "youtube")
    assert not shorts["puede"] and "Autoriza" in shorts["aviso"]


def test_aprobar_con_una_hora_por_sitio(client):
    with SessionLocal() as session:
        tiktok = Account(platform=Platform.tiktok.value, display_name="Kevil",
                         handle="the_kevil", external_id="tt")
        session.add(tiktok)
        youtube = _cuenta_youtube(session)
        video = Video(external_id="v2", title="V", url="u")
        session.add(video)
        session.flush()
        clip = Clip(video_id=video.id, start_s=0, end_s=45, status="rendered")
        session.add(clip)
        session.commit()
        ids = (clip.id, tiktok.id, youtube.id)

    clip_id, tiktok_id, youtube_id = ids
    respuesta = client.post(f"/api/clips/{clip_id}/approve", json={"destinos": [
        {"account_id": tiktok_id, "scheduled_at": "2026-10-01T01:00:00Z"},
        {"account_id": youtube_id, "scheduled_at": "2026-10-01T03:30:00Z"},
    ]})
    assert respuesta.status_code == 200, respuesta.text
    posts = respuesta.json()["clip"]["posts"]
    horas = {p["platform"]: p["scheduled_at"] for p in posts}
    assert horas["tiktok"].startswith("2026-10-01T01:00")
    assert horas["youtube"].startswith("2026-10-01T03:30")
