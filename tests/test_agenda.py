"""Lo programado sale solo: YouTube programado allí, TikTok sin madrugones."""

from datetime import timedelta

import pytest

from app.config import settings
from app.models import ClipStatus, Notification, Platform, PostStatus, utcnow
from app.services import pipeline, scheduler, segundo_plano, youtube_api
from tests.test_youtube_publish import (
    _clip_listo, _contexto, _cuenta, _pasos_publicando_en, _post,
)


@pytest.fixture
def youtube_real(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(youtube_api, "is_configured", lambda: True)
    subidas = []

    def subir(credentials, **datos):
        subidas.append(datos)
        return {"video_id": "yt123", "url": "https://youtube.com/shorts/yt123"}

    monkeypatch.setattr(youtube_api, "upload_short", subir)
    monkeypatch.setattr(youtube_api, "valid_credentials", lambda c: c)
    return subidas


@pytest.fixture
def sin_sesion_propia(monkeypatch, session):
    """El planificador abre su propia sesión: que use la de la prueba."""
    import contextlib

    @contextlib.contextmanager
    def misma():
        yield session
        session.flush()

    monkeypatch.setattr(scheduler, "session_scope", misma)


def _mas_tarde(post, horas):
    post.scheduled_at = utcnow() + timedelta(hours=horas)


def test_el_short_se_sube_ya_programado_en_youtube(session, tmp_path, youtube_real):
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    post = _post(session, clip, youtube)
    _mas_tarde(post, 6)
    session.commit()

    ctx = _contexto(session, post)
    ctx.payload = {"post_id": post.id, "programar": True}
    pipeline.job_publish(session, ctx)

    assert youtube_real[0]["publish_at"] == youtube_api.hora_para_youtube(post.scheduled_at)
    assert youtube_real[0]["publish_at"].endswith("Z")
    assert post.en_plataforma and post.external_post_id == "yt123"
    assert post.status == PostStatus.scheduled.value          # sale a su hora
    assert post.subido_at is not None
    assert pipeline.youtube_uploads_today(session) == 1       # la cuota se gasta hoy

    # a su hora no se vuelve a subir: se da por publicado
    ctx2 = _contexto(session, post)
    pipeline.job_publish(session, ctx2)
    assert len(youtube_real) == 1


def test_a_su_hora_se_da_por_publicado_sin_subir_otra_vez(
    session, tmp_path, youtube_real, sin_sesion_propia
):
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    post = _post(session, clip, youtube)
    post.en_plataforma = True
    post.external_post_id = "yt123"
    post.scheduled_at = utcnow() - timedelta(minutes=1)
    session.commit()

    scheduler.dispatch_due_posts()
    assert post.status == PostStatus.published.value
    assert clip.status == ClipStatus.published.value
    assert not youtube_real


def test_el_planificador_deja_los_shorts_programados(
    session, tmp_path, youtube_real, sin_sesion_propia
):
    from app.models import Job

    youtube = _cuenta(session, Platform.youtube.value)
    tiktok = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, True))
    corto = _post(session, clip, youtube)
    _mas_tarde(corto, 5)
    de_tiktok = _post(session, clip, tiktok)
    _mas_tarde(de_tiktok, 5)
    session.commit()

    scheduler.dispatch_due_posts()
    trabajos = session.query(Job).filter_by(kind="publish").all()
    pedidos = [j.payload for j in trabajos]
    assert {"post_id": corto.id, "programar": True} in pedidos
    assert not any(p.get("post_id") == de_tiktok.id for p in pedidos)   # TikTok, a su hora

    # no se repite en cada vuelta del planificador
    for trabajo in trabajos:
        trabajo.status = "done"
    session.commit()
    scheduler.dispatch_due_posts()
    assert session.query(Job).filter_by(kind="publish").count() == len(trabajos)


def test_en_simulacion_no_se_sube_antes(session, tmp_path, monkeypatch, youtube_real):
    monkeypatch.setattr(settings, "dry_run", True)
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    post = _post(session, clip, youtube)
    _mas_tarde(post, 6)
    assert not pipeline.puede_programar_en_youtube(youtube, post)


def test_si_el_pc_estaba_apagado_se_recoloca_en_vez_de_publicar_de_madrugada(
    session, tmp_path, sin_sesion_propia, monkeypatch
):
    from app.models import Job

    monkeypatch.setattr(settings, "dry_run", False)
    tiktok = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    post = _post(session, clip, tiktok)
    post.scheduled_at = utcnow() - timedelta(hours=7)
    reciente = _post(session, clip, tiktok)
    reciente.scheduled_at = utcnow() - timedelta(minutes=10)
    session.commit()

    scheduler.dispatch_due_posts()
    assert post.scheduled_at > utcnow()                      # movido al futuro
    assert "apagado" in post.slot_reason
    assert session.query(Notification).filter_by(kind="agenda").count() == 1
    # el de hace diez minutos sí sale ya
    assert session.query(Job).filter_by(kind="publish").count() == 1


def test_mover_un_short_programado_lo_mueve_en_youtube(session, tmp_path, monkeypatch):
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    post = _post(session, clip, youtube)
    post.en_plataforma = True
    post.external_post_id = "yt123"
    _mas_tarde(post, 10)
    llamadas = []
    monkeypatch.setattr(
        youtube_api, "cambiar_programacion",
        lambda cred, vid, cuando, ya=False: llamadas.append((vid, cuando, ya)),
    )
    assert pipeline.mover_en_plataforma(session, post) == ""
    assert llamadas[-1][0] == "yt123" and llamadas[-1][1].endswith("Z")

    # sin el permiso nuevo: aviso con el enlace a Studio, sin romper nada
    def sin_permiso(*_a, **_k):
        raise youtube_api.SinPermisoParaCambiar("vuelve a conectar YouTube")

    monkeypatch.setattr(youtube_api, "cambiar_programacion", sin_permiso)
    aviso = pipeline.mover_en_plataforma(session, post, cancelar=True)
    assert "YouTube Studio" in aviso
    avisos = session.query(Notification).filter_by(kind="youtube").all()
    assert avisos and "studio.youtube.com" in avisos[-1].action_url


def test_pendientes_que_necesitan_el_pc(session, tmp_path):
    youtube = _cuenta(session, Platform.youtube.value)
    tiktok = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, True))
    en_youtube = _post(session, clip, youtube)
    en_youtube.en_plataforma = True
    _mas_tarde(en_youtube, 3)
    de_tiktok = _post(session, clip, tiktok)
    _mas_tarde(de_tiktok, 3)
    session.commit()
    assert segundo_plano.pendientes_en_el_pc(session) == 1   # el de YouTube sale solo
    assert segundo_plano.pendientes_de_tiktok(session) == 1


def test_orden_de_arranque_con_windows():
    orden = segundo_plano.orden_de_arranque()
    assert "run.py" in orden and "--sin-ventana" in orden
