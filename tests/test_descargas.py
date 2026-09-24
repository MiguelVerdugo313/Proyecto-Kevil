"""Descargas de tramos: nombres propios y reintento si Windows bloquea el archivo."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.models import Clip, ClipStatus, Flow, Job, JobStatus, Video
from app.flow_schema import default_steps
from app.services import pipeline
from app.services import youtube as yt


class _FalsoYDL:
    """Imita lo justo de yt_dlp.YoutubeDL para `download_sections`."""

    fallos_pendientes = 0          # cuántas veces contestar con WinError 32
    nombres: list[str] = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        plantilla = self.opts["outtmpl"]
        ruta = Path(plantilla.replace("%(id)s", "abc").replace("%(ext)s", "mp4"))
        _FalsoYDL.nombres.append(ruta.name)
        # deja un .part a medias, como hace yt-dlp antes de renombrar
        ruta.with_name(ruta.name + ".part").write_bytes(b"x")
        if _FalsoYDL.fallos_pendientes > 0:
            _FalsoYDL.fallos_pendientes -= 1
            raise RuntimeError(
                f"ERROR: Unable to rename file: [WinError 32] El proceso no tiene acceso al "
                f"archivo porque está siendo utilizado por otro proceso: '{ruta}.part'"
            )
        ruta.with_name(ruta.name + ".part").rename(ruta)
        return {"id": "abc", "requested_downloads": [{"filepath": str(ruta)}]}


@pytest.fixture
def falso_ytdlp(monkeypatch):
    class Utils:
        @staticmethod
        def download_range_func(_chapters, rangos):
            return rangos

    class Modulo:
        YoutubeDL = _FalsoYDL
        utils = Utils

    _FalsoYDL.fallos_pendientes = 0
    _FalsoYDL.nombres = []
    monkeypatch.setattr(yt, "yt_dlp", Modulo)
    monkeypatch.setattr(yt, "PAUSA_ENTRE_LLAMADAS", 0)
    monkeypatch.setattr(yt.time, "sleep", lambda _s: None)
    return _FalsoYDL


def test_dos_clips_del_mismo_video_no_comparten_archivo(falso_ytdlp, tmp_path):
    """Era el WinError 32: dos renders bajaban a la vez a «tramo-<id>.mp4»."""
    rutas: list[str] = []

    def bajar(desde):
        rutas.append(yt.download_sections("u", [(desde, desde + 30)], destination=tmp_path))

    hilos = [threading.Thread(target=bajar, args=(i * 40,)) for i in range(4)]
    for hilo in hilos:
        hilo.start()
    for hilo in hilos:
        hilo.join()

    assert len(rutas) == 4
    assert len(set(rutas)) == 4, "cada descarga tiene que ir a su propio archivo"
    assert all(Path(r).exists() for r in rutas)


def test_si_windows_bloquea_el_archivo_se_reintenta_con_otro_nombre(falso_ytdlp, tmp_path):
    falso_ytdlp.fallos_pendientes = 2
    ruta = yt.download_sections("u", [(0, 10)], destination=tmp_path)

    assert Path(ruta).exists()
    assert len(falso_ytdlp.nombres) == 3
    assert len(set(falso_ytdlp.nombres)) == 3          # un nombre nuevo cada vez
    # y no quedan restos de los intentos fallidos
    assert sorted(p.name for p in tmp_path.iterdir()) == [Path(ruta).name]


def test_si_no_hay_manera_el_error_se_entiende(falso_ytdlp, tmp_path):
    falso_ytdlp.fallos_pendientes = 99
    with pytest.raises(yt.YouTubeError) as error:
        yt.download_sections("u", [(0, 10)], destination=tmp_path, intentos=2)
    assert "otro programa" in str(error.value)
    assert "WinError" not in str(error.value)


def test_el_render_se_reprograma_solo_si_el_archivo_sigue_ocupado(session, monkeypatch):
    flujo = Flow(name="F", description="", icon="", steps=default_steps())
    video = Video(external_id="v1", title="V", url="https://example.invalid/v",
                  duration_s=120, local_path="")
    session.add_all([flujo, video])
    session.flush()
    clip = Clip(video_id=video.id, flow_id=flujo.id, index=1, title="C",
                start_s=10, end_s=40, status=ClipStatus.draft.value)
    session.add(clip)
    job = Job(kind="render", payload={"clip_id": 0}, status=JobStatus.running.value)
    session.add(job)
    session.flush()
    job.payload = {"clip_id": clip.id}
    session.commit()

    def ocupado(*_a, **_k):
        raise RuntimeError("[WinError 32] being used by another process")

    monkeypatch.setattr(pipeline.youtube_service, "download_sections", ocupado)
    pipeline.job_render(session, pipeline.JobContext(session, job))
    session.commit()

    assert clip.status == ClipStatus.draft.value and clip.error == ""
    # hay un trabajo NUEVO esperando (antes se tomaba por duplicado de sí mismo)
    pendientes = session.query(Job).filter(
        Job.kind == "render", Job.status == JobStatus.pending.value
    ).all()
    assert len(pendientes) == 1 and pendientes[0].id != job.id
    assert pendientes[0].payload == {"clip_id": clip.id}
