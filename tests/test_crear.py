"""«Crear»: de un enlace o un archivo a clips, con lo elegido sólo para ese vídeo."""

import contextlib
import io

import pytest
from fastapi.testclient import TestClient

from app import bootstrap
from app.api.crear import limpiar_ajustes
from app.db import get_db
from app.flow_schema import normalize_steps, step_config, step_enabled
from app.models import Clip, ClipStatus, Flow, Job, Video
from app.services import pipeline
from app.services import youtube as youtube_service


@pytest.fixture
def cliente(session):
    from app.main import app

    bootstrap.seed_flows(session)
    session.commit()

    @contextlib.asynccontextmanager
    async def _nada(_app):
        yield

    app.router.lifespan_context = _nada
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


def test_solo_se_guarda_lo_permitido():
    ajustes = limpiar_ajustes({
        "subtitles": {"template": "gamer", "enabled": 0, "font": "Arial", "position_y": "70"},
        "reframe": {"mode": "split"},
        "cleanup": {"remove_fillers": "sí", "max_pause": "1.2"},
        "publish": {"publish_tiktok": True},          # no se toca desde aquí
        "segment": {"ai_pick": False, "max_clips": "x"},
    })
    assert ajustes == {
        "subtitles": {"template": "gamer", "enabled": False, "position_y": 70.0},
        "reframe": {"mode": "split"},
        "cleanup": {"remove_fillers": True, "max_pause": 1.2},
        "segment": {"ai_pick": False},
    }
    assert "reframe" not in limpiar_ajustes({"reframe": {"mode": "raro"}})
    assert limpiar_ajustes({"subtitles": {"template": "no-existe"}}) == {}


def test_los_ajustes_del_video_mandan_sin_tocar_el_flujo(session):
    pasos = normalize_steps([])
    video = Video(external_id="x", title="x", url="x", ajustes={
        "subtitles": {"template": "neon", "enabled": False},
        "segment": {"enabled": False, "ai_pick": False},     # «segment» no se puede apagar
    })
    mios = pipeline.con_ajustes(pasos, video)
    assert step_config(mios, "subtitles")["template"] == "neon"
    assert step_enabled(mios, "subtitles") is False
    assert step_enabled(mios, "segment") is True
    assert step_config(mios, "segment")["ai_pick"] is False
    # el flujo sigue igual
    assert step_config(pasos, "subtitles")["template"] == "kevil"
    assert pipeline.con_ajustes(pasos, Video(external_id="y", title="y", url="y")) is pasos


def test_opciones_de_la_pantalla(cliente):
    datos = cliente.get("/api/crear/opciones").json()
    assert datos["flujos"] and datos["flow_id"]
    assert {e["value"] for e in datos["encuadres"]} >= {"blur", "crop", "smart", "split"}
    assert datos["valores"]["subtitles"]["template"] == "kevil"
    assert datos["valores"]["cleanup"]["remove_fillers"] is False


def test_crear_desde_un_enlace(cliente, session, monkeypatch):
    monkeypatch.setattr(youtube_service, "fetch_video_info", lambda url: {
        "external_id": "abc12345678", "title": "Partida", "url": url, "duration_s": 600,
    })
    r = cliente.post("/api/crear/enlace", json={
        "url": "https://youtu.be/abc12345678", "contexto": "FNF Animania",
        "ajustes": {"subtitles": {"template": "mrbeast"}, "cleanup": {"remove_fillers": True}},
    })
    assert r.status_code == 200, r.text
    video = session.get(Video, r.json()["id"])
    assert video.ajustes["subtitles"]["template"] == "mrbeast"
    assert video.contexto == "FNF Animania"
    assert session.query(Job).filter_by(kind="ingest").count() == 1

    p = cliente.get(f"/api/crear/{video.id}/progreso").json()
    assert [paso["clave"] for paso in p["pasos"]] == ["descargar", "transcribir", "momentos", "montar", "listo"]
    assert p["pasos"][0]["estado"] == "ahora" and not p["terminado"]
    assert cliente.post("/api/crear/enlace", json={"url": " "}).status_code == 400


def test_crear_desde_un_archivo_y_ver_el_progreso(cliente, session, tmp_path):
    r = cliente.post(
        "/api/crear/archivo",
        files={"file": ("Mi partida.mp4", io.BytesIO(b"0" * 4096), "video/mp4")},
        data={"ajustes": '{"reframe": {"mode": "crop"}}', "contexto": ""},
    )
    assert r.status_code == 200, r.text
    video = session.get(Video, r.json()["id"])
    assert video.origin == "local" and video.title == "Mi partida"
    assert video.ajustes == {"reframe": {"mode": "crop"}}
    trabajo = session.query(Job).filter_by(kind="analyze_local").one()
    assert trabajo.payload["make_clips"] is True and trabajo.payload["kit"] is False

    # ya cortado y montado: todo en verde
    video.status = "done"
    video.transcript = {"words": [{"start": 0, "end": 1, "text": "hola"}], "segments": []}
    session.add(Clip(video_id=video.id, index=1, title="Mi partida", start_s=0, end_s=30,
                     status=ClipStatus.rendered.value))
    session.commit()
    p = cliente.get(f"/api/crear/{video.id}/progreso").json()
    assert all(paso["estado"] == "hecho" for paso in p["pasos"])
    assert p["terminado"] and p["porcentaje"] == 1.0
    assert p["pasos"][0]["nombre"] == "Analizar el archivo"

    assert cliente.post("/api/crear/archivo", files={"file": ("x.txt", io.BytesIO(b"hola"), "text/plain")}
                        ).status_code == 400


def test_el_render_usa_lo_elegido_para_el_video(session, tmp_path, monkeypatch):
    from app.services import renderer

    flujo = Flow(name="F", steps=normalize_steps([]))
    video = Video(external_id="v", title="V", url="x", local_path=str(tmp_path / "o.mp4"),
                  ajustes={"subtitles": {"template": "gamer"}, "cleanup": {"remove_fillers": True},
                           "reframe": {"mode": "crop"}})
    (tmp_path / "o.mp4").write_bytes(b"0")
    session.add_all([flujo, video])
    session.flush()
    clip = Clip(video_id=video.id, flow_id=flujo.id, index=1, title="c", start_s=0, end_s=10)
    session.add(clip)
    session.commit()
    visto = {}

    def falso(**k):
        visto.update(k)
        salida = tmp_path / "c.mp4"
        salida.write_bytes(b"0")
        return {"path": str(salida), "thumb": "", "focus_x": 0.5}

    monkeypatch.setattr(renderer, "render_clip", falso)
    job = Job(kind="render", payload={"clip_id": clip.id}, status="running")
    session.add(job)
    session.commit()
    pipeline.job_render(session, pipeline.JobContext(session, job))
    assert visto["subtitles"]["template"] == "gamer"
    assert visto["limpieza"]["remove_fillers"] is True
    assert visto["reframe"]["mode"] == "crop"


def test_whisper_en_la_nube_con_groq(tmp_path, monkeypatch):
    """Un vídeo sin subtítulos se transcribe con Groq, por trozos y con tiempos."""
    import httpx

    from app.services import ai, transcript
    from app.services import media as media_service

    if not media_service.ffmpeg_ready():
        pytest.skip("ffmpeg no está instalado")
    origen = tmp_path / "voz.mp4"
    media_service.make_test_video(origen, seconds=6)
    monkeypatch.setattr(transcript, "NUBE_TROZO_S", 4)          # dos trozos
    pedidos = []

    def responder(peticion: httpx.Request) -> httpx.Response:
        pedidos.append(peticion)
        assert peticion.url.path.endswith("/audio/transcriptions")
        assert peticion.headers["authorization"] == "Bearer clave"
        return httpx.Response(200, json={"words": [
            {"word": " hola", "start": 0.5, "end": 0.9}, {"word": "mundo", "start": 1.0, "end": 1.4},
        ]})

    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **k: real(transport=httpx.MockTransport(responder), **k))
    groq = ai.Provider(key="groq", api_key="clave", text_model="", image_model="",
                       base_url="https://api.groq.com/openai/v1", tipo="groq")
    datos = transcript.transcribe_in_cloud(origen, language="es", provider=groq)
    assert len(pedidos) == 2
    assert datos["source"] == "whisper-nube"
    textos = [w["text"] for w in datos["words"]]
    assert textos == ["hola", "mundo", "hola", "mundo"]
    # el segundo trozo va detrás del primero
    assert datos["words"][2]["start"] >= 4.0
    assert datos["segments"]
