"""Nada se publica dos veces y cada clip se llama «Vídeo · Parte N»."""

from datetime import timedelta

import pytest

from app import bootstrap
from app.config import settings
from app.flow_schema import default_config
from app.models import (
    Account, AccountStatus, Clip, ClipStatus, Platform, Post, PostStatus, Video, utcnow,
)
from app.services import metadata, partes, pipeline, repetidos, tiktok, youtube_api


@pytest.fixture(autouse=True)
def _sin_cache():
    repetidos._cache.clear()
    yield
    repetidos._cache.clear()


def _cuenta(session, plataforma):
    cuenta = Account(platform=plataforma, display_name=plataforma, handle=plataforma,
                     external_id=f"ext-{plataforma}", status=AccountStatus.connected.value,
                     credentials={"access_token": "t", "expires_at": 9e12})
    session.add(cuenta)
    session.flush()
    return cuenta


def _video(session, titulo="FNF Animania"):
    bootstrap.seed_flows(session)
    video = Video(external_id=f"v-{titulo}", title=titulo, url="https://youtu.be/x",
                  duration_s=3600)
    session.add(video)
    session.flush()
    return video


def _clip(session, video, desde, hasta, estado=ClipStatus.rendered.value, titulo="", tmp=None):
    ruta = ""
    if tmp is not None:
        archivo = tmp / f"c{desde}.mp4"
        archivo.write_bytes(b"x")
        ruta = str(archivo)
    clip = Clip(video_id=video.id, start_s=desde, end_s=hasta, status=estado,
                title=titulo or f"{video.title} · parte 9", hook=f"El susto del segundo {desde}",
                caption="", render_path=ruta)
    session.add(clip)
    session.flush()
    return clip


def _post(session, clip, cuenta, estado=PostStatus.scheduled.value, horas=5, **extra):
    post = Post(clip_id=clip.id, account_id=cuenta.id, status=estado,
                scheduled_at=utcnow() + timedelta(hours=horas), caption=clip.caption, **extra)
    session.add(post)
    session.flush()
    return post


# ------------------------------------------------------------------ títulos
def test_un_video_entero_no_es_parte_1():
    datos = metadata.build_metadata(
        config=default_config("metadata"), video_title="Mi vídeo", channel="",
        hook="", text="", index=1, total=1,
    )
    assert datos["title"] == "Mi vídeo"
    assert datos["caption"].startswith("Mi vídeo\n")


def test_las_partes_van_en_el_orden_del_video(session):
    video = _video(session)
    tarde = _clip(session, video, 900, 950)
    pronto = _clip(session, video, 100, 150)
    a_mano = _clip(session, video, 500, 550, titulo="Mi título puesto a mano")
    publicado = _clip(session, video, 50, 90, estado=ClipStatus.published.value,
                      titulo="FNF Animania · parte 4")
    tiktok_ = _cuenta(session, Platform.tiktok.value)
    programado = _post(session, pronto, tiktok_)
    session.refresh(video)

    partes.numerar(session, video)

    assert publicado.title == "FNF Animania · parte 4"         # lo publicado no se toca
    assert pronto.title == "FNF Animania · Parte 2"
    assert a_mano.title == "Mi título puesto a mano"           # lo tuyo se respeta
    assert tarde.title == "FNF Animania · Parte 4"
    assert [c.index for c in (publicado, pronto, a_mano, tarde)] == [1, 2, 3, 4]
    # se recuerda cómo se llamaba (así se reconoce si ya se subió)
    assert "FNF Animania · parte 9" in pronto.render_config["titulos_anteriores"]
    # y lo programado se sube con el título nuevo
    assert programado.caption.startswith("FNF Animania · Parte 2")


# ------------------------------------------------------------------ en Kevil
def test_mismo_trozo():
    assert repetidos.mismo_trozo(0, 40, 2, 41)
    assert repetidos.mismo_trozo(0, 90, 10, 50)          # uno dentro del otro
    assert not repetidos.mismo_trozo(0, 40, 35, 80)
    assert not repetidos.mismo_trozo(0, 40, 40, 80)


def test_volver_a_cortar_no_repite_lo_que_ya_existe(session, monkeypatch):
    from app.models import Job

    video = _video(session)
    ya = _clip(session, video, 0, 40, estado=ClipStatus.scheduled.value)
    descartado = _clip(session, video, 300, 340, estado=ClipStatus.rejected.value)
    session.commit()
    monkeypatch.setattr(pipeline.segmenter, "find_segments", lambda **_k: [
        {"start": 1, "end": 41, "score": 0.9, "hook": "otra vez"},          # ya existe
        {"start": 301, "end": 339, "score": 0.8, "hook": "lo descartaste"},  # no lo quieres
        {"start": 100, "end": 140, "score": 0.7, "hook": "nuevo"},
    ])
    job = Job(kind="process", payload={"video_id": video.id}, status="running")
    session.add(job)
    session.commit()
    video.local_path = ""
    video.transcript = {"words": [{"text": "hola", "start": 0, "end": 1}]}
    session.commit()

    pipeline.job_process(session, pipeline.JobContext(session, job))
    session.refresh(video)
    nuevos = [c for c in video.clips if c.id not in {ya.id, descartado.id}]
    assert [(c.start_s, c.end_s) for c in nuevos] == [(100, 140)]
    assert nuevos[0].title == "FNF Animania · Parte 2"          # va después del 0-40


def test_limpiar_repetidos_en_kevil(session):
    video = _video(session)
    tiktok_ = _cuenta(session, Platform.tiktok.value)
    youtube = _cuenta(session, Platform.youtube.value)

    original = _clip(session, video, 0, 40, estado=ClipStatus.scheduled.value)
    en_youtube = _post(session, original, youtube, en_plataforma=True)
    copia = _clip(session, video, 1, 42, estado=ClipStatus.scheduled.value)
    copia_youtube = _post(session, copia, youtube)                # repetido en YouTube
    copia_tiktok = _post(session, copia, tiktok_)                 # en TikTok no estaba
    sin_publicar = _clip(session, video, 2, 40)                   # otro igual, sin más
    doble = _clip(session, video, 600, 640, estado=ClipStatus.scheduled.value)
    primero = _post(session, doble, tiktok_)
    segundo = _post(session, doble, tiktok_)
    session.commit()

    resumen = repetidos.limpiar_locales(session)

    assert en_youtube.status == PostStatus.scheduled.value        # lo de YouTube manda
    assert copia_youtube.status == PostStatus.cancelled.value
    assert copia_tiktok.status == PostStatus.scheduled.value
    assert copia.status == ClipStatus.scheduled.value
    assert sin_publicar.status == ClipStatus.rejected.value
    assert "Repetido" in sin_publicar.reason
    assert primero.status == PostStatus.scheduled.value
    assert segundo.status == PostStatus.cancelled.value
    assert resumen == {"descartados": 1, "cancelados": 2}


def test_aprobar_no_repite_el_mismo_momento(client_con_sesion):
    client, session = client_con_sesion
    video = _video(session)
    tiktok_ = _cuenta(session, Platform.tiktok.value)
    ya = _clip(session, video, 0, 40, estado=ClipStatus.published.value)
    _post(session, ya, tiktok_, estado=PostStatus.published.value)
    otro = _clip(session, video, 1, 41)
    session.commit()

    respuesta = client.post(f"/api/clips/{otro.id}/approve", json={"account_id": tiktok_.id})
    datos = respuesta.json()
    assert datos["post_ids"] == []
    assert "ya está" in datos["avisos"][0]


@pytest.fixture
def client_con_sesion(session):
    import contextlib

    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    @contextlib.asynccontextmanager
    async def _nada(_app):
        yield

    app.router.lifespan_context = _nada
    app.dependency_overrides[get_db] = lambda: session
    with TestClient(app) as cliente:
        yield cliente, session
    app.dependency_overrides.clear()


# ------------------------------------------------------------------ en las plataformas
@pytest.fixture
def de_verdad(monkeypatch):
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(youtube_api, "is_configured", lambda: True)
    monkeypatch.setattr(tiktok, "is_configured", lambda: True)
    monkeypatch.setattr(youtube_api, "valid_credentials", lambda c: c)
    monkeypatch.setattr(tiktok, "valid_credentials", lambda c: c)
    subidas = []
    monkeypatch.setattr(youtube_api, "upload_short", lambda *a, **k: subidas.append(k) or {
        "video_id": "nuevo", "url": ""})
    monkeypatch.setattr(pipeline, "_publish_to_tiktok",
                        lambda *a, **k: subidas.append("tiktok") or {"publish_id": "p"})
    return subidas


def _ctx(session, post, **payload):
    from app.models import Job

    job = Job(kind="publish", payload={"post_id": post.id, **payload}, status="running")
    session.add(job)
    session.commit()
    return pipeline.JobContext(session, job)


def test_lo_que_ya_esta_programado_en_youtube_no_se_sube_otra_vez(session, tmp_path, de_verdad,
                                                                   monkeypatch):
    video = _video(session)
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip(session, video, 0, 40, tmp=tmp_path)
    session.refresh(video)
    partes.numerar(session, video)                    # «… · parte 9» → «… · Parte 1»
    post = _post(session, clip, youtube, horas=10)
    session.commit()
    en_youtube = (utcnow() + timedelta(hours=30)).replace(microsecond=0)
    monkeypatch.setattr(youtube_api, "mis_subidas", lambda c, limit=50: [{
        "id": "viejo", "title": "FNF Animania · parte 9 #Shorts",     # subido con el título de antes
        "privacy": "private", "publish_at": en_youtube.isoformat(),
        "published_at": utcnow().isoformat(),
    }])

    pipeline.job_publish(session, _ctx(session, post, programar=True))

    assert not de_verdad                                   # no se ha subido nada
    assert post.en_plataforma and post.external_post_id == "viejo"
    assert post.scheduled_at == en_youtube                 # manda la hora de YouTube


def test_lo_ya_publicado_en_youtube_se_da_por_publicado(session, tmp_path, de_verdad, monkeypatch):
    video = _video(session)
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip(session, video, 0, 40, titulo="FNF Animania · Parte 1", tmp=tmp_path)
    post = _post(session, clip, youtube, horas=-1)
    session.commit()
    monkeypatch.setattr(youtube_api, "mis_subidas", lambda c, limit=50: [{
        "id": "ya", "title": "FNF Animania · Parte 1 #Shorts", "privacy": "public",
        "publish_at": "", "published_at": "2026-09-20T20:25:00",
    }])
    pipeline.job_publish(session, _ctx(session, post))
    assert not de_verdad
    assert post.status == PostStatus.published.value
    assert clip.status == ClipStatus.published.value


def test_lo_ya_publicado_en_tiktok_no_se_repite(session, tmp_path, de_verdad, monkeypatch):
    video = _video(session)
    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip(session, video, 0, 40, titulo="FNF Animania · Parte 1", tmp=tmp_path)
    post = _post(session, clip, cuenta, horas=-1)
    session.commit()
    monkeypatch.setattr(tiktok, "fetch_recent_videos", lambda c, limit=20: [{
        "id": "7", "title": "", "create_time": 1_790_000_000,
        "video_description": "El susto del segundo 0 #fyp #parati",   # subido con el gancho
        "share_url": "https://tiktok.com/@kevil/video/7",
    }])
    pipeline.job_publish(session, _ctx(session, post))
    assert de_verdad == []
    assert post.status == PostStatus.published.value
    assert post.share_url.endswith("/7")


def test_si_no_esta_se_sube_normal(session, tmp_path, de_verdad, monkeypatch):
    video = _video(session)
    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip(session, video, 0, 40, titulo="FNF Animania · Parte 1", tmp=tmp_path)
    post = _post(session, clip, cuenta, horas=-1)
    session.commit()
    monkeypatch.setattr(tiktok, "fetch_recent_videos", lambda c, limit=20: [{
        "id": "8", "video_description": "Otra cosa distinta del todo", "create_time": 1,
    }])
    pipeline.job_publish(session, _ctx(session, post))
    assert de_verdad == ["tiktok"]


def test_sin_red_se_sube_igual(session, tmp_path, de_verdad, monkeypatch):
    video = _video(session)
    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip(session, video, 0, 40, titulo="FNF Animania · Parte 1", tmp=tmp_path)
    post = _post(session, clip, cuenta, horas=-1)
    session.commit()

    def sin_red(*_a, **_k):
        raise RuntimeError("sin conexión")

    monkeypatch.setattr(tiktok, "fetch_recent_videos", sin_red)
    pipeline.job_publish(session, _ctx(session, post))
    assert de_verdad == ["tiktok"]


def test_parte_1_no_es_parte_12():
    clip = Clip(title="Friday Night Funkin Animania · Parte 1", hook="", start_s=0, end_s=1)
    assert repetidos._coincide("Friday Night Funkin Animania · Parte 1 #Shorts", clip)
    assert not repetidos._coincide("Friday Night Funkin Animania · Parte 12 #Shorts", clip)


def test_al_actualizar_los_clips_pasan_a_partes(session):
    from app.models import Setting

    video = _video(session)
    solo = _clip(session, video, 600, 650, titulo="FNF Animania · parte 3")
    session.add(Setting(key=bootstrap.MEJORAS_KEY, value=[
        k for k in bootstrap.MEJORAS if k != "titulos-por-partes-1"
    ]))
    session.commit()
    bootstrap.actualizar_plantillas(session)
    # uno solo de un directo de una hora sigue siendo «Parte 1»
    assert solo.title == "FNF Animania · Parte 1"


def test_un_video_corto_entero_no_lleva_parte(session):
    video = _video(session)
    video.duration_s = 50
    entero = _clip(session, video, 0, 50, titulo="FNF Animania · parte 1")
    session.refresh(video)
    partes.numerar(session, video)
    assert entero.title == "FNF Animania"


def test_directos_con_el_mismo_titulo_no_se_confunden(session, tmp_path, de_verdad, monkeypatch):
    """«FNF Animania · Parte 1» de hoy no es la del directo de la semana pasada."""
    video = _video(session)
    video.published_at = utcnow() - timedelta(days=1)
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip(session, video, 0, 40, titulo="FNF Animania · Parte 1", tmp=tmp_path)
    post = _post(session, clip, youtube, horas=-1)
    session.commit()
    monkeypatch.setattr(youtube_api, "mis_subidas", lambda c, limit=50: [
        # mismo título, otro momento (otro gancho) y de antes de este directo
        {"id": "semana-pasada", "title": "FNF Animania · Parte 1 #Shorts", "privacy": "public",
         "description": "FNF Animania · Parte 1\nEl jefe final me destroza\n\n#fyp",
         "publish_at": "", "published_at": (utcnow() - timedelta(days=8)).isoformat()},
    ])
    pipeline.job_publish(session, _ctx(session, post))
    assert de_verdad and de_verdad[0]["title"].startswith("FNF Animania · Parte 1")


def test_mismo_titulo_y_mismo_momento_si_es_repetido(session, tmp_path, de_verdad, monkeypatch):
    video = _video(session)
    video.published_at = utcnow() - timedelta(days=1)
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip(session, video, 0, 40, titulo="FNF Animania · Parte 1", tmp=tmp_path)
    post = _post(session, clip, youtube, horas=-1)
    session.commit()
    monkeypatch.setattr(youtube_api, "mis_subidas", lambda c, limit=50: [
        {"id": "este", "title": "FNF Animania · Parte 1 #Shorts", "privacy": "public",
         "description": "El susto del segundo 0\n\n#fyp #parati",
         "publish_at": "", "published_at": utcnow().isoformat()},
    ])
    pipeline.job_publish(session, _ctx(session, post))
    assert not de_verdad
    assert post.external_post_id == "este"


def test_en_tiktok_otro_momento_del_mismo_juego_no_cuenta(session, tmp_path, de_verdad, monkeypatch):
    video = _video(session)
    cuenta = _cuenta(session, Platform.tiktok.value)
    clip = _clip(session, video, 0, 40, titulo="FNF Animania · Parte 1", tmp=tmp_path)
    post = _post(session, clip, cuenta, horas=-1)
    session.commit()
    monkeypatch.setattr(tiktok, "fetch_recent_videos", lambda c, limit=20: [{
        "id": "9", "create_time": 1_790_000_000,
        "video_description": "FNF Animania · Parte 1\nOtro momento distinto\n\n#fyp",
    }])
    pipeline.job_publish(session, _ctx(session, post))
    assert de_verdad == ["tiktok"]


def test_las_visitas_de_tiktok_llegan_a_su_publicacion(session, tmp_path, monkeypatch):
    """Antes nunca casaban: se guardaba el id de la subida, no el del vídeo."""
    from app.models import Job

    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(tiktok, "valid_credentials", lambda c: c)
    monkeypatch.setattr(tiktok, "fetch_user_info", lambda c: {"follower_count": 10})
    video = _video(session)
    cuenta = _cuenta(session, Platform.tiktok.value)
    con_id = _clip(session, video, 0, 40, titulo="FNF Animania · Parte 1")
    viejo = _clip(session, video, 100, 140, titulo="FNF Animania · Parte 2")
    publicado = _post(session, con_id, cuenta, estado=PostStatus.published.value,
                      external_post_id="111")
    de_antes = _post(session, viejo, cuenta, estado=PostStatus.published.value)
    session.commit()
    monkeypatch.setattr(tiktok, "fetch_recent_videos", lambda c, limit=20: [
        {"id": "111", "view_count": 500, "create_time": 1_790_000_000},
        {"id": "222", "view_count": 90, "create_time": 1_790_000_000,
         "video_description": "El susto del segundo 100 #fyp"},
    ])
    job = Job(kind="refresh_metrics", payload={"account_id": cuenta.id}, status="running")
    session.add(job)
    session.commit()
    pipeline.job_refresh_metrics(session, pipeline.JobContext(session, job))
    assert publicado.metrics["views"] == 500
    assert de_antes.external_post_id == "222" and de_antes.metrics["views"] == 90
