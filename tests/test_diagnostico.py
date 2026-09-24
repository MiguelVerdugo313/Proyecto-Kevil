"""Tareas con problemas y la sesión de YouTube: que se entiendan y se arreglen."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import settings
from app.models import Clip, ClipStatus, Job, JobStatus, Video, utcnow
from app.services import diagnostico
from app.services import youtube as yt

# Los errores tal cual salían en las capturas de la 1.4
OCUPADO = (
    "Unable to download video: [WinError 32] El proceso no tiene acceso al archivo porque "
    "está siendo utilizado por otro proceso: 'C:\\\\Users\\\\migue\\\\Desktop\\\\Kevil "
    "Studio\\\\data\\\\temp\\\\tramo--o_nGIBxNl8.mp4'"
)
RENOMBRAR = (
    "ERROR: Unable to rename file: [WinError 32] El proceso no tiene acceso al archivo "
    "porque está siendo utilizado por otro proceso. Giving up after 3 retries"
)
ROBOT = "ERROR: [youtube] abc: Sign in to confirm you're not a bot. Use --cookies-from-browser"


def test_cada_error_se_explica_y_dice_que_hacer():
    ocupado = diagnostico.diagnosticar(OCUPADO)
    assert ocupado["tipo"] == "ocupado" and ocupado["pasajero"]
    assert diagnostico.diagnosticar(RENOMBRAR)["tipo"] == "ocupado"

    robot = diagnostico.diagnosticar(ROBOT)
    assert robot["tipo"] == "robot"
    assert len(robot["pasos"]) >= 3                          # pasos concretos, no «activa X»
    assert any(a["id"] == "sesion_youtube" for a in robot["acciones"])

    assert diagnostico.diagnosticar("HTTP Error 429: Too Many Requests")["tipo"] == "limite"
    assert diagnostico.diagnosticar("Read timed out")["tipo"] == "red"
    # «image» o «page» no son «age»: no se confunde con la restricción de edad
    assert diagnostico.diagnosticar("bad image page usage")["tipo"] == "otro"


def _clip(session, titulo="C"):
    video = Video(external_id=f"v-{titulo}", title="V", url="https://example.invalid/v")
    session.add(video)
    session.flush()
    clip = Clip(video_id=video.id, index=1, title=titulo, start_s=0, end_s=30,
                status=ClipStatus.failed.value, error=OCUPADO)
    session.add(clip)
    session.flush()
    return clip


def _fallido(session, clip, error, hace_min=0):
    job = Job(kind="render", payload={"clip_id": clip.id}, status=JobStatus.failed.value,
              error=error, message=error[:200],
              finished_at=utcnow() - timedelta(minutes=hace_min))
    session.add(job)
    session.flush()
    return job


def test_los_fallos_repetidos_del_mismo_clip_cuentan_una_vez(session):
    clip = _clip(session)
    for minuto in range(4):                      # como en la captura: cuatro veces lo mismo
        _fallido(session, clip, OCUPADO if minuto % 2 else RENOMBRAR, minuto)
    otro = _clip(session, "D")
    _fallido(session, otro, ROBOT)
    session.commit()

    datos = diagnostico.problemas(session)
    assert datos["total"] == 2
    assert datos["duplicados"] == 3
    tipos = {g["tipo"]: g["total"] for g in datos["grupos"]}
    assert tipos == {"ocupado": 1, "robot": 1}
    assert datos["grupos"][0]["trabajos"][0]["titulo"]      # se ve de qué clip es


def test_al_abrir_se_reintenta_solo_lo_pasajero(session):
    clip = _clip(session)
    for minuto in range(3):
        _fallido(session, clip, OCUPADO, minuto)
    robot = _fallido(session, _clip(session, "R"), ROBOT)
    session.commit()

    assert diagnostico.reintentar_pasajeros_al_arrancar(session) == 1
    session.commit()

    pendientes = session.query(Job).filter(Job.status == JobStatus.pending.value).all()
    assert len(pendientes) == 1 and pendientes[0].payload["clip_id"] == clip.id
    assert clip.status == ClipStatus.draft.value and clip.error == ""
    # los duplicados se quitan de la lista y lo del robot espera a que lo arregles
    assert session.query(Job).filter(Job.status == JobStatus.cancelled.value).count() == 2
    assert robot.status == JobStatus.failed.value

    # y no se repite en cada arranque
    pendientes[0].status = JobStatus.failed.value
    session.commit()
    assert diagnostico.reintentar_pasajeros_al_arrancar(session) == 0


def test_un_fallo_pasajero_vuelve_a_la_cola_con_espera(session):
    job = _fallido(session, _clip(session), "Read timed out")
    assert diagnostico.reintentar_solo_si_toca(job)
    assert job.status == JobStatus.pending.value
    assert job.run_at > utcnow() + timedelta(minutes=1)
    assert "se reintenta solo" in job.message

    # a la cuarta ya no: se deja para que lo mires
    job.payload = {**job.payload, "reintentos_auto": len(diagnostico.ESPERAS_MIN)}
    job.status = JobStatus.failed.value
    assert not diagnostico.reintentar_solo_si_toca(job)

    # lo que necesita que hagas algo no se reintenta a lo tonto
    assert not diagnostico.reintentar_solo_si_toca(_fallido(session, _clip(session, "Z"), ROBOT))


def test_reintentar_todo_de_una_causa(session):
    uno, dos = _clip(session, "1"), _clip(session, "2")
    _fallido(session, uno, OCUPADO)
    _fallido(session, dos, ROBOT)
    session.commit()
    assert diagnostico.reintentar_grupo(session, "robot") == 1
    assert diagnostico.problemas(session)["total"] == 1


# --------------------------------------------------------------------------
# La sesión de YouTube
# --------------------------------------------------------------------------
class _YDL:
    """yt-dlp de mentira: sólo deja pasar con las cookies de Firefox."""

    llamadas: list[dict] = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        _YDL.llamadas.append(self.opts)
        cookies = self.opts.get("cookiesfrombrowser")
        if cookies == ("chrome",):
            raise RuntimeError("Could not copy Chrome cookie database")
        if cookies != ("firefox",) and "cookiefile" not in self.opts:
            raise RuntimeError(ROBOT)
        return {"id": "abc", "title": "Vídeo", "duration": 60}


@pytest.fixture
def youtube_falso(monkeypatch, tmp_path):
    class Modulo:
        YoutubeDL = _YDL

    _YDL.llamadas = []
    monkeypatch.setattr(yt, "yt_dlp", Modulo)
    monkeypatch.setattr(yt, "PAUSA_ENTRE_LLAMADAS", 0)
    monkeypatch.setattr(yt, "navegadores_instalados", lambda: ["chrome", "firefox"])
    monkeypatch.setattr(yt, "guardar_modo_cookies",
                        lambda modo: setattr(settings, "youtube_cookies", modo))
    monkeypatch.setattr(yt, "ruta_cookies_txt", lambda: tmp_path / "cookies.txt")
    monkeypatch.setattr(settings, "youtube_cookies", "auto")
    return _YDL


def test_si_youtube_pide_la_comprobacion_prueba_tus_navegadores_solo(youtube_falso):
    video = yt.fetch_video_info("https://www.youtube.com/watch?v=abc")
    assert video["external_id"] == "abc"
    assert settings.youtube_cookies == "firefox"          # se queda con el que funcionó

    # la siguiente vez ya va directa con Firefox, sin volver a probar
    youtube_falso.llamadas = []
    yt.fetch_video_info("https://www.youtube.com/watch?v=abc")
    assert len(youtube_falso.llamadas) == 1
    assert youtube_falso.llamadas[0]["cookiesfrombrowser"] == ("firefox",)


def test_explica_por_que_no_sirve_cada_navegador(youtube_falso):
    resultado = yt.probar_navegadores("u", ["chrome"])
    assert not resultado["ok"]
    assert "ciérralo" in resultado["intentos"][0]["resultado"]


def test_sin_sesion_que_valga_el_error_lo_explica(youtube_falso, monkeypatch):
    monkeypatch.setattr(yt, "navegadores_instalados", lambda: ["chrome"])
    with pytest.raises(yt.RobotCheck) as error:
        yt.fetch_video_info("https://www.youtube.com/watch?v=abc")
    assert "Qué hago" in str(error.value)


def test_un_cookies_txt_se_usa_antes_que_nada(youtube_falso, tmp_path):
    (tmp_path / "cookies.txt").write_text(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n",
        encoding="utf-8",
    )
    assert yt.cookies_txt_valido((tmp_path / "cookies.txt").read_text())
    assert yt.opciones_de_cookies() == {"cookiefile": str(tmp_path / "cookies.txt")}
    assert not yt.cookies_txt_valido("hola\nadiós")
