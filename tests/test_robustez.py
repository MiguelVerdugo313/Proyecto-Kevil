"""Que Kevil no se rompa en el uso real: permisos, límites, archivos que faltan…"""

from datetime import timedelta

import httpx
import pytest

from app.config import settings
from app.models import (
    AccountStatus, ClipStatus, Job, Notification, Platform, PostStatus, Source, utcnow,
)
from app.services import permisos, pipeline, repetidos, scheduler, tiktok, youtube_api
from tests.test_agenda import sin_sesion_propia  # noqa: F401 - fixture
from tests.test_youtube_publish import (
    _clip_listo, _contexto, _cuenta, _pasos_publicando_en, _post,
)


@pytest.fixture
def de_verdad(monkeypatch):
    """Sin simulación, con YouTube y TikTok configurados y sin red real."""
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(youtube_api, "is_configured", lambda: True)
    monkeypatch.setattr(tiktok, "is_configured", lambda: True)
    monkeypatch.setattr(youtube_api, "valid_credentials", lambda c: c)
    monkeypatch.setattr(tiktok, "valid_credentials", lambda c: c)
    monkeypatch.setattr(youtube_api, "mis_subidas", lambda c, limit=50: [])
    monkeypatch.setattr(tiktok, "fetch_recent_videos", lambda c, limit=20: [])
    repetidos._cache.clear()
    yield
    repetidos._cache.clear()


def _respuesta(codigo, cuerpo):
    return httpx.Response(codigo, json=cuerpo, request=httpx.Request("POST", "https://x"))


# ------------------------------------------------------------ permisos
def test_google_sin_permiso_se_entiende():
    with pytest.raises(youtube_api.PermisoCaducado) as error:
        youtube_api._json(_respuesta(400, {"error": "invalid_grant",
                                           "error_description": "Token has been expired or revoked."}))
    assert "vuelve a conectar" in str(error.value)
    with pytest.raises(youtube_api.PermisoCaducado):
        youtube_api._json(_respuesta(401, {"error": {"message": "Invalid Credentials"}}))
    with pytest.raises(youtube_api.YouTubeAPIError) as error:
        youtube_api._json(_respuesta(401, {"error": "invalid_client"}))
    assert "secreto de cliente" in str(error.value)
    with pytest.raises(youtube_api.LimiteDelDia):
        youtube_api._json(_respuesta(403, {"error": {"message": "x", "errors": [{"reason": "quotaExceeded"}]}}))


def test_permiso_caducado_al_publicar_y_vuelve_al_reconectar(session, tmp_path, de_verdad, monkeypatch):
    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    post = _post(session, clip, cuenta)

    def caducado(*_a, **_k):
        raise tiktok.PermisoCaducado("TikTok ya no acepta el permiso de esta cuenta. Vuelve a conectarla.")

    monkeypatch.setattr(tiktok, "valid_credentials", caducado)
    pipeline.job_publish(session, _contexto(session, post))

    assert post.status == PostStatus.failed.value and post.error.startswith(permisos.PREFIJO)
    assert cuenta.status == AccountStatus.needs_auth.value
    assert session.query(Notification).filter(Notification.title.like("Vuelve a conectar%")).count() == 1

    # mientras no se reconecta, no se vuelve a intentar subir nada
    intentos = []
    monkeypatch.setattr(pipeline, "_publish_to_tiktok", lambda *a, **k: intentos.append(1) or {})
    post.status = PostStatus.scheduled.value
    pipeline.job_publish(session, _contexto(session, post))
    assert not intentos and post.status == PostStatus.failed.value

    # al reconectar, vuelve sola a la agenda (lo atrasado, en unos minutos)
    cuenta.status = AccountStatus.connected.value
    assert permisos.rescatar(session, cuenta) == 1
    assert post.status == PostStatus.scheduled.value and post.scheduled_at > utcnow()


def test_los_rotos_por_el_error_viejo_se_reintentan(session, tmp_path):
    cuenta = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    roto = _post(session, clip, cuenta, PostStatus.failed.value)
    roto.error = "'str' object has no attribute 'get'"
    otro = _post(session, clip, cuenta, PostStatus.failed.value)
    otro.error = "TikTok rechazó el vídeo"
    session.commit()
    assert permisos.reintentar_los_rotos(session) == 1
    assert roto.status == PostStatus.scheduled.value and otro.status == PostStatus.failed.value


# ------------------------------------------------------------ límites
def test_tiktok_pide_calma_se_aplaza_no_falla(session, tmp_path, de_verdad, monkeypatch):
    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    post = _post(session, clip, cuenta)

    def calma(*_a, **_k):
        raise tiktok.TikTokRechazo("spam_risk_too_many_posts", "too many")

    monkeypatch.setattr(pipeline, "_publish_to_tiktok", calma)
    pipeline.job_publish(session, _contexto(session, post))
    assert post.status == PostStatus.scheduled.value
    assert post.scheduled_at > utcnow() + timedelta(hours=2)
    assert "Aplazado" in post.slot_reason


def test_cuota_de_youtube_de_la_api_tambien_se_aplaza(session, tmp_path, de_verdad, monkeypatch):
    cuenta = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    post = _post(session, clip, cuenta)

    def sin_cuota(*_a, **_k):
        raise youtube_api.LimiteDelDia("cuota agotada")

    monkeypatch.setattr(youtube_api, "upload_short", sin_cuota)
    pipeline.job_publish(session, _contexto(session, post))
    assert post.status == PostStatus.scheduled.value
    assert post.scheduled_at > utcnow() + timedelta(hours=23)


def test_sin_el_video_del_clip_se_vuelve_a_montar(session, tmp_path, de_verdad):
    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    clip.video.url = "https://youtu.be/x"
    post = _post(session, clip, cuenta)
    clip.render_path = str(tmp_path / "ya-no-esta.mp4")
    session.commit()

    pipeline.job_publish(session, _contexto(session, post))
    assert post.status == PostStatus.scheduled.value and post.scheduled_at > utcnow()
    assert session.query(Job).filter_by(kind="render").count() == 1


# ------------------------------------------------------------ nada falso
def test_un_canal_sin_permiso_no_finge_que_publica(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(youtube_api, "is_configured", lambda: True)
    cuenta = _cuenta(session, Platform.youtube.value, con_token=False)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    post = _post(session, clip, cuenta)
    with pytest.raises(RuntimeError):
        pipeline.job_publish(session, _contexto(session, post))
    assert post.status == PostStatus.failed.value and "permiso" in post.error


def test_tiktok_sin_clave_de_app_no_finge_que_publica(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(tiktok, "is_configured", lambda: False)
    monkeypatch.setattr(tiktok, "fetch_recent_videos", lambda c, limit=20: [])
    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    post = _post(session, clip, cuenta)
    with pytest.raises(RuntimeError):
        pipeline.job_publish(session, _contexto(session, post))
    assert post.status == PostStatus.failed.value and "clave" in post.error


def test_una_cuenta_de_prueba_si_simula_y_se_ve(session, tmp_path, monkeypatch):
    from app.api.common import post_to_dict

    monkeypatch.setattr(settings, "dry_run", False)
    cuenta = _cuenta(session, Platform.tiktok.value, con_token=False)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    post = _post(session, clip, cuenta)
    pipeline.job_publish(session, _contexto(session, post))
    assert post.status == PostStatus.published.value
    assert post_to_dict(post)["simulado"] is True


# ------------------------------------------------------------ estados
def test_con_tiktok_pendiente_el_clip_no_esta_publicado(session, tmp_path, de_verdad, monkeypatch):
    youtube = _cuenta(session, Platform.youtube.value)
    tik = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, True))
    _post(session, clip, tik).scheduled_at = utcnow() + timedelta(hours=3)
    post = _post(session, clip, youtube)
    session.commit()
    monkeypatch.setattr(youtube_api, "upload_short", lambda *a, **k: {"video_id": "v1", "url": ""})
    pipeline.job_publish(session, _contexto(session, post))
    assert post.status == PostStatus.published.value
    assert clip.status == ClipStatus.scheduled.value
    assert clip.render_path                         # su vídeo sigue para TikTok


# ------------------------------------------------ lo programado en YouTube
def _en_youtube(session, tmp_path, minutos_pasados=1):
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    post = _post(session, clip, youtube)
    post.en_plataforma = True
    post.external_post_id = "yt9"
    post.scheduled_at = utcnow() - timedelta(minutes=minutos_pasados)
    session.commit()
    return post


@pytest.mark.parametrize("estado,minutos,esperado", [
    ({"privacy": "public", "publish_at": "", "upload_status": "processed", "motivo": ""}, 1, "published"),
    (None, 1, "failed"),
    ({"privacy": "private", "publish_at": "", "upload_status": "rejected", "motivo": "copyright"}, 1, "failed"),
    ({"privacy": "private", "publish_at": "", "upload_status": "processed", "motivo": ""}, 5, "scheduled"),
    ({"privacy": "private", "publish_at": "", "upload_status": "processed", "motivo": ""}, 45, "failed"),
])
def test_a_su_hora_se_comprueba_que_salio_en_youtube(session, tmp_path, de_verdad, monkeypatch,
                                                    estado, minutos, esperado):
    post = _en_youtube(session, tmp_path, minutos)
    monkeypatch.setattr(youtube_api, "estado_del_video", lambda c, v: estado)
    pipeline.comprobar_salido_en_youtube(session, post)
    assert post.status == esperado
    if esperado == "failed":
        assert session.query(Notification).filter(Notification.title.like("Un Short no salió%")).count() == 1


def test_si_cambias_la_hora_en_studio_manda_la_de_alli(session, tmp_path, de_verdad, monkeypatch):
    post = _en_youtube(session, tmp_path)
    luego = (utcnow() + timedelta(hours=5)).replace(microsecond=0)
    monkeypatch.setattr(youtube_api, "estado_del_video", lambda c, v: {
        "privacy": "private", "publish_at": luego.isoformat(), "upload_status": "processed", "motivo": ""})
    pipeline.comprobar_salido_en_youtube(session, post)
    assert post.status == PostStatus.scheduled.value and post.scheduled_at == luego


def test_el_planificador_comprueba_en_vez_de_suponer(session, tmp_path, de_verdad, monkeypatch,
                                                     sin_sesion_propia):  # noqa: F811
    post = _en_youtube(session, tmp_path)
    monkeypatch.setattr(youtube_api, "estado_del_video", lambda c, v: None)
    scheduler.dispatch_due_posts()
    assert post.status == PostStatus.failed.value and "ya no está" in post.error


def test_volver_a_montar_sustituye_la_version_ya_subida(session, tmp_path, de_verdad, monkeypatch):
    post = _en_youtube(session, tmp_path)
    post.scheduled_at = utcnow() + timedelta(hours=3)
    session.commit()
    borrados = []
    monkeypatch.setattr(youtube_api, "borrar_video", lambda c, v: borrados.append(v))
    pipeline._reemplazar_en_youtube(session, post.clip)
    assert borrados == ["yt9"]
    assert not post.en_plataforma and not post.external_post_id
    assert post.status == PostStatus.scheduled.value


# ------------------------------------------------------------ medir
def test_un_fallo_de_red_al_medir_no_deja_la_cuenta_en_error(session):
    cuenta = _cuenta(session, Platform.tiktok.value)
    pipeline._fallo_al_medir(session, cuenta, httpx.ConnectError("sin red"))
    assert cuenta.status == AccountStatus.connected.value
    cuenta.status = AccountStatus.needs_auth.value
    pipeline._cuenta_funciona(cuenta)
    assert cuenta.status == AccountStatus.connected.value


# ------------------------------------------------------------ textos
def test_youtube_no_rechaza_por_signos_ni_por_largo():
    texto = youtube_api.limpiar_para_youtube("te quiero <3 -> 🎮 " * 600, 5000, en_bytes=True)
    assert "<" not in texto and ">" not in texto
    assert len(texto.encode("utf-8")) <= 5000
    assert youtube_api.limpiar_para_youtube("  Hola <b>  ", 100) == "Hola ‹b›"


def test_la_pagina_de_vuelta_escapa_y_se_entiende():
    from app.api.accounts import _result_page

    pagina = _result_page("Error <script>", "@<img src=x>", False, "access_denied")
    assert "<script>" not in pagina.replace("<script>setTimeout", "") and "&lt;img" in pagina
    assert "Geist" in pagina and "prefers-color-scheme" in pagina
    ok = _result_page("¡Canal conectado!", "Listo", True)
    assert "setTimeout" in ok


# ------------------------------------------------------------ vídeos
def test_borrar_un_video_vigilado_no_lo_trae_de_vuelta(session, tmp_path, de_verdad, monkeypatch):
    import contextlib

    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app
    from app.models import Clip, Video

    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    fuente = Source(account_id=youtube.id, name="Kevil", url="x", channel_id="UCx")
    session.add(fuente)
    session.flush()
    video = clip.video
    video.source_id = fuente.id
    post = _post(session, clip, youtube)
    post.en_plataforma, post.external_post_id = True, "yt5"
    post.scheduled_at = utcnow() + timedelta(hours=4)
    session.add(Job(kind="render", payload={"clip_id": clip.id}, status="pending"))
    session.commit()
    cancelados = []
    monkeypatch.setattr(youtube_api, "cambiar_programacion",
                        lambda c, v, cuando, ya=False: cancelados.append((v, cuando)))

    @contextlib.asynccontextmanager
    async def _nada(_app):
        yield

    app.router.lifespan_context = _nada
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as cliente:
            assert cliente.delete(f"/api/videos/{video.id}").status_code == 200
    finally:
        app.dependency_overrides.clear()

    assert cancelados == [("yt5", None)]                       # no sale en YouTube
    assert session.query(Clip).count() == 0
    assert session.get(Video, video.id).status == "ignored"    # la vigilancia no lo trae
    assert session.query(Job).filter_by(kind="render").one().status == "cancelled"


def test_la_agenda_no_repite_ni_cancela_lo_publicado(session, tmp_path):
    import contextlib

    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    publicado = _post(session, clip, cuenta, PostStatus.published.value)
    pendiente = _post(session, clip, cuenta)

    @contextlib.asynccontextmanager
    async def _nada(_app):
        yield

    app.router.lifespan_context = _nada
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as cliente:
            assert cliente.post(f"/api/posts/{publicado.id}/publish-now").status_code == 400
            assert cliente.delete(f"/api/posts/{publicado.id}").status_code == 400
            pasado = (utcnow() - timedelta(hours=3)).isoformat() + "Z"
            assert cliente.patch(f"/api/posts/{pendiente.id}", json={"scheduled_at": pasado}).status_code == 400
            assert cliente.delete(f"/api/posts/{pendiente.id}").status_code == 200
    finally:
        app.dependency_overrides.clear()
    assert publicado.status == PostStatus.published.value
    assert clip.status == ClipStatus.published.value            # le queda lo publicado


def test_al_reintentar_solo_la_publicacion_vuelve_a_programada(session, tmp_path):
    from app.services import diagnostico

    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    post = _post(session, clip, cuenta, PostStatus.failed.value)
    job = Job(kind="publish", payload={"post_id": post.id}, status="failed",
              error="httpx.ConnectTimeout: timed out")
    session.add(job)
    session.commit()
    assert diagnostico.reintentar_solo_si_toca(job) is True
    assert post.status == PostStatus.scheduled.value
