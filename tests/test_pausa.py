"""Pausar y reanudar el motor."""

from __future__ import annotations

import contextlib
import sys
import threading

import pytest
from fastapi.testclient import TestClient

from app import procesos
from app.models import Job, JobStatus, Setting
from app.services import media as media_service
from app.services import pausa, queue


@pytest.fixture(autouse=True)
def _sin_pausa_al_acabar():
    yield
    pausa._en_pausa.clear()


# --------------------------------------------------------------------------
# El estado
# --------------------------------------------------------------------------
def test_pausar_y_reanudar_se_guarda(session):
    assert pausa.activa() is False

    pausa.pausar(session)
    session.flush()
    assert pausa.activa() is True
    assert session.get(Setting, pausa.CLAVE).value is True

    # al volver a abrir el programa se acuerda
    pausa._en_pausa.clear()
    assert pausa.cargar(session) is True

    pausa.reanudar(session)
    session.flush()
    assert pausa.activa() is False
    assert pausa.cargar(session) is False


def test_pausar_corta_lo_que_esta_en_marcha(session):
    lento = procesos.popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert pausa.pausar(session) >= 1
        lento.wait(timeout=5)
    finally:
        if lento.poll() is None:
            lento.kill()


def test_que_se_para_y_que_no():
    assert pausa.afecta("render") and pausa.afecta("ingest") and pausa.afecta("process")
    # publicar a su hora y leer métricas siguen: son ligeras y tienen hora
    assert not pausa.afecta("publish")
    assert not pausa.afecta("refresh_metrics")


# --------------------------------------------------------------------------
# La cola
# --------------------------------------------------------------------------
def _trabajo(session, kind: str) -> Job:
    job = Job(kind=kind, payload={}, status=JobStatus.pending.value)
    session.add(job)
    session.commit()
    return job


def test_en_pausa_solo_sale_lo_ligero(session):
    pesado = _trabajo(session, "render")
    ligero = _trabajo(session, "publish")
    trabajador = queue.Worker(99, threading.Event())

    pausa._en_pausa.set()
    elegido = trabajador._claim()
    assert elegido == ligero.id              # el render se queda esperando
    assert trabajador._claim() is None       # y no hay más que coger

    pausa._en_pausa.clear()
    assert trabajador._claim() == pesado.id  # al reanudar, sale


def test_el_avance_de_un_trabajo_pesado_lo_corta(session):
    pesado = _trabajo(session, "render")
    contexto = queue.JobContext(session, pesado)
    contexto.progress(0.2)                   # sin pausa, nada

    pausa._en_pausa.set()
    with pytest.raises(pausa.Pausado):
        contexto.progress(0.4)

    # uno ligero sigue a lo suyo aunque haya pausa
    ligero = _trabajo(session, "publish")
    queue.JobContext(session, ligero).progress(0.5)


def test_lo_cortado_vuelve_a_la_cola_sin_contar_como_intento(session):
    job = _trabajo(session, "render")
    job.status = JobStatus.running.value
    job.attempts = 1
    job.progress = 0.6
    session.commit()

    queue._devolver_a_la_cola(session, job.id)
    session.refresh(job)
    assert job.status == JobStatus.pending.value
    assert job.attempts == 0
    assert job.progress == 0.0
    assert "pausa" in job.message.lower()


def test_ffmpeg_no_se_queda_vivo_si_se_corta_a_medias(tmp_path):
    """Si el que escucha el avance lanza (la pausa), ffmpeg se para también."""
    if not media_service.ffmpeg_ready():
        pytest.skip("ffmpeg no está instalado")

    def cortar(_ratio):
        raise pausa.Pausado()

    with pytest.raises(pausa.Pausado):
        media_service.run_ffmpeg(
            ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=30",
             "-c:v", "libx264", "-preset", "ultrafast", str(tmp_path / "x.mp4")],
            total_duration=30,
            on_progress=cortar,
        )
    assert procesos.vivos() == 0


# --------------------------------------------------------------------------
# El botón
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    from app.main import app

    @contextlib.asynccontextmanager
    async def _sin_lifespan(_app):
        yield

    app.router.lifespan_context = _sin_lifespan
    with TestClient(app) as test_client:
        yield test_client


def test_el_boton_de_pausa(client):
    assert client.get("/api/status").json()["paused"] is False

    pausado = client.post("/api/motor/pausa").json()
    assert pausado["paused"] is True
    assert client.get("/api/status").json()["paused"] is True
    assert client.get("/api/motor").json()["paused"] is True

    reanudado = client.post("/api/motor/reanudar").json()
    assert reanudado["paused"] is False
    assert client.get("/api/status").json()["paused"] is False
