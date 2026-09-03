"""Publicación en YouTube Shorts y republicación de Shorts en TikTok."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.config import settings
from app.flow_schema import FLOW_PRESETS, default_config, step_config
from app.models import Account, AccountStatus, Platform, Video
from app.services import pipeline, segmenter, youtube_api


# --------------------------------------------------------------------------
# Servidor falso que imita a la API de YouTube
# --------------------------------------------------------------------------
class _Google(BaseHTTPRequestHandler):
    recibido = bytearray()
    trozos = 0

    def _responder(self, code, payload=None, headers=None):
        datos = json.dumps(payload or {}).encode()
        self.send_response(code)
        for clave, valor in (headers or {}).items():
            self.send_header(clave, valor)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def do_GET(self):  # noqa: N802
        if "/channels" in self.path:
            self._responder(200, {"items": [{
                "id": "UC123",
                "snippet": {"title": "Mi Canal", "customUrl": "@micanal",
                            "thumbnails": {"default": {"url": "http://x/a.jpg"}}},
                "statistics": {"subscriberCount": "1234", "videoCount": "56",
                               "viewCount": "78900"},
            }]})
        elif "/videos" in self.path:
            self._responder(200, {"items": [{
                "id": "vid1",
                "snippet": {"title": "Un Short"},
                "statistics": {"viewCount": "500", "likeCount": "40", "commentCount": "3"},
            }]})
        else:
            self._responder(404, {"error": {"message": "no existe"}})

    def do_POST(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        cuerpo = self.rfile.read(largo)

        if self.path.startswith("/token"):
            self._responder(200, {"access_token": "token-nuevo", "expires_in": 3600})
            return

        if "uploadType=resumable" in self.path:
            enviado = json.loads(cuerpo)
            assert enviado["snippet"]["title"]
            assert enviado["status"]["privacyStatus"]
            type(self).recibido = bytearray()
            type(self).trozos = 0
            base = f"http://{self.headers['Host']}"
            self._responder(200, {}, {"Location": f"{base}/sesion-de-subida"})
            return

        self._responder(404, {"error": {"message": "ruta desconocida"}})

    def do_PUT(self):  # noqa: N802
        largo = int(self.headers.get("Content-Length", 0))
        datos = self.rfile.read(largo)
        rango = self.headers.get("Content-Range", "")
        total = int(rango.split("/")[-1])

        type(self).recibido.extend(datos)
        type(self).trozos += 1

        if len(type(self).recibido) >= total:
            self._responder(200, {"id": "abc123XYZ", "status": {"uploadStatus": "uploaded"}})
        else:
            # 308 = «sigue mandando», como hace Google de verdad
            self.send_response(308)
            self.send_header("Range", f"bytes=0-{len(type(self).recibido) - 1}")
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *_args):
        pass


@pytest.fixture
def google(monkeypatch):
    servidor = HTTPServer(("127.0.0.1", 0), _Google)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{servidor.server_address[1]}"

    monkeypatch.setattr(youtube_api, "API_BASE", f"{base}/youtube/v3")
    monkeypatch.setattr(youtube_api, "UPLOAD_BASE", f"{base}/upload/youtube/v3")
    monkeypatch.setattr(youtube_api, "TOKEN_URL", f"{base}/token")
    monkeypatch.setattr(youtube_api, "CHUNK", 64 * 1024)   # forzar varios trozos
    monkeypatch.setattr(settings, "youtube_client_id", "id-de-prueba")
    monkeypatch.setattr(settings, "youtube_client_secret", "secreto-de-prueba")
    monkeypatch.setattr(settings, "dry_run", False)
    try:
        yield base
    finally:
        servidor.shutdown()


CREDENCIALES = {"access_token": "abc", "refresh_token": "ref", "expires_at": 9e12}


# --------------------------------------------------------------------------
# Cliente de la API
# --------------------------------------------------------------------------
def test_url_de_autorizacion(google):
    url = youtube_api.build_auth_url("estado123")
    assert "accounts.google.com" in url
    assert "access_type=offline" in url          # hace falta para el refresh token
    assert "youtube.upload" in url
    assert "state=estado123" in url


def test_sin_credenciales_no_deja_empezar(monkeypatch):
    monkeypatch.setattr(settings, "youtube_client_id", "")
    monkeypatch.setattr(settings, "youtube_client_secret", "")
    assert youtube_api.is_configured() is False
    with pytest.raises(youtube_api.YouTubeNotConfigured):
        youtube_api.build_auth_url("x")


def test_datos_del_canal(google):
    canal = youtube_api.fetch_channel(CREDENCIALES)
    assert canal["channel_id"] == "UC123"
    assert canal["name"] == "Mi Canal"
    assert canal["handle"] == "micanal"          # sin la arroba
    assert canal["subscribers"] == 1234


def test_el_token_caducado_se_renueva(google):
    caducado = {"access_token": "viejo", "refresh_token": "ref", "expires_at": 0}
    renovado = youtube_api.valid_credentials(caducado)
    assert renovado["access_token"] == "token-nuevo"
    assert renovado["refresh_token"] == "ref"    # se conserva el de siempre


def test_subida_por_trozos(google, tmp_path):
    archivo = tmp_path / "short.mp4"
    archivo.write_bytes(b"K" * (200 * 1024))     # 200 KB -> varios trozos de 64 KB

    progreso: list[float] = []
    resultado = youtube_api.upload_short(
        CREDENCIALES,
        video_path=archivo,
        title="Mi Short de prueba",
        description="Una descripción",
        tags=["uno", "dos"],
        privacy_status="unlisted",
        on_progress=progreso.append,
    )

    assert resultado["video_id"] == "abc123XYZ"
    assert resultado["url"] == "https://www.youtube.com/shorts/abc123XYZ"
    assert resultado["quota_used"] == youtube_api.COST_UPLOAD
    assert _Google.trozos >= 3                   # se ha troceado de verdad
    assert len(_Google.recibido) == 200 * 1024   # y ha llegado entero
    assert progreso and progreso[-1] == 1.0


def test_modo_simulacion_no_sube_nada(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "dry_run", True)
    archivo = tmp_path / "short.mp4"
    archivo.write_bytes(b"x" * 1024)
    resultado = youtube_api.upload_short(CREDENCIALES, video_path=archivo, title="t")
    assert resultado["dry_run"] is True
    assert resultado["quota_used"] == 0


def test_estadisticas_de_videos(google):
    stats = youtube_api.fetch_video_stats(CREDENCIALES, ["vid1"])
    assert stats["vid1"]["views"] == 500
    assert stats["vid1"]["likes"] == 40


def test_avisos_del_formato_short():
    assert youtube_api.validate_short(1080, 1920, 45) == []
    largo = youtube_api.validate_short(1080, 1920, 400)
    assert largo and "Short" in largo[0]
    horizontal = youtube_api.validate_short(1920, 1080, 30)
    assert horizontal and "vertical" in horizontal[0]


def test_las_etiquetas_se_recortan_a_500_caracteres():
    muchas = [f"etiqueta-larguisima-numero-{i:03d}" for i in range(60)]
    salida = youtube_api._limit_tags(muchas)
    assert sum(len(t) + 1 for t in salida) <= 500
    assert len(salida) < len(muchas)


# --------------------------------------------------------------------------
# Destinos de publicación
# --------------------------------------------------------------------------
def _cuenta(session, plataforma, *, con_token=True):
    cuenta = Account(
        platform=plataforma,
        display_name=f"Cuenta {plataforma}",
        handle=plataforma,
        external_id=f"ext-{plataforma}",
        status=AccountStatus.connected.value,
        credentials={"access_token": "t"} if con_token else {},
    )
    session.add(cuenta)
    session.commit()
    return cuenta


def test_destinos_segun_el_flujo(session):
    video = Video(external_id="v1", title="Vídeo", url="x")
    session.add(video)
    _cuenta(session, Platform.tiktok.value)
    youtube = _cuenta(session, Platform.youtube.value)
    session.commit()

    config = default_config("publish")
    assert len(pipeline.destinations_for(session, video, config)) == 1     # sólo TikTok

    config["publish_youtube_shorts"] = True
    destinos = pipeline.destinations_for(session, video, config)
    assert {d.platform for d in destinos} == {"tiktok", "youtube"}

    config["publish_tiktok"] = False
    assert [d.id for d in pipeline.destinations_for(session, video, config)] == [youtube.id]

    # un canal de YouTube sin permiso de subida no cuenta como destino
    youtube.credentials = {}
    session.commit()
    assert pipeline.destinations_for(session, video, config) == []


def test_plantilla_de_republicar_shorts():
    preset = next(p for p in FLOW_PRESETS if p["name"] == "Shorts a TikTok")
    pasos = preset["steps"]
    assert step_config(pasos, "segment")["strategy"] == "completo"
    apagados = {p["type"] for p in pasos if not p["enabled"]}
    assert {"subtitles", "overlays"} <= apagados      # el Short ya viene montado

    doble = next(p for p in FLOW_PRESETS if p["name"] == "Clips a TikTok y Shorts")
    publish = step_config(doble["steps"], "publish")
    assert publish["publish_tiktok"] and publish["publish_youtube_shorts"]
    assert step_config(doble["steps"], "segment")["max_duration"] < 60


def test_el_video_entero_como_un_solo_clip():
    config = default_config("segment")
    config["strategy"] = "completo"
    trozos = segmenter.find_segments(
        media_path="x.mp4", duration=48.5, transcript={}, config=config
    )
    assert len(trozos) == 1
    assert trozos[0]["start"] == 0 and trozos[0]["end"] == 48.5

    # un vídeo sin duración conocida no genera nada
    assert segmenter.find_segments(
        media_path="x.mp4", duration=0, transcript={}, config=config
    ) == []


# --------------------------------------------------------------------------
# Cuota diaria y fallos parciales
# --------------------------------------------------------------------------
def _clip_listo(session, tmp_path, flow_steps):
    """Un clip renderizado de verdad (un archivo pequeño basta) y su flujo."""
    from app.models import Clip, ClipStatus, Flow, Video

    archivo = tmp_path / "clip.mp4"
    archivo.write_bytes(b"no es un mp4 de verdad, pero existe")

    flujo = Flow(name="De prueba", steps=flow_steps)
    session.add(flujo)
    video = Video(external_id="v-cuota", title="Vídeo", url="x")
    session.add(video)
    session.flush()
    clip = Clip(
        video_id=video.id, flow_id=flujo.id, index=1, title="Un clip",
        caption="Un clip", start_s=0, end_s=20,
        render_path=str(archivo), status=ClipStatus.rendered.value,
        render_config={"output": {"width": 1080, "height": 1920, "duration": 20}},
    )
    session.add(clip)
    session.commit()
    return clip


def _post(session, clip, cuenta, estado="scheduled"):
    from app.models import Post, utcnow

    post = Post(clip_id=clip.id, account_id=cuenta.id, caption="Un clip",
                scheduled_at=utcnow(), status=estado)
    session.add(post)
    session.commit()
    return post


def _contexto(session, post):
    from app.models import Job

    job = Job(kind="publish", payload={"post_id": post.id}, status="running")
    session.add(job)
    session.commit()
    return pipeline.JobContext(session, job)


def _pasos_publicando_en(tiktok: bool, youtube: bool):
    from app.flow_schema import normalize_steps

    pasos = normalize_steps([])
    for paso in pasos:
        if paso["type"] == "publish":
            paso["config"]["publish_tiktok"] = tiktok
            paso["config"]["publish_youtube_shorts"] = youtube
            paso["config"]["mode"] = "auto"
    return pasos


def test_la_cuota_diaria_de_youtube_se_cuenta_por_24_horas(session, tmp_path):
    from datetime import timedelta

    from app.models import PostStatus, utcnow

    cuenta = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    assert pipeline.youtube_uploads_today(session) == 0

    reciente = _post(session, clip, cuenta, PostStatus.published.value)
    reciente.published_at = utcnow() - timedelta(hours=3)
    antiguo = _post(session, clip, cuenta, PostStatus.published.value)
    antiguo.published_at = utcnow() - timedelta(hours=30)
    session.commit()

    assert pipeline.youtube_uploads_today(session) == 1     # el de ayer ya no cuenta


def test_sin_cuota_el_short_se_aplaza_en_vez_de_fallar(session, tmp_path, monkeypatch):
    from datetime import timedelta

    from app.models import ClipStatus, Notification, PostStatus, utcnow

    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(youtube_api, "is_configured", lambda: True)

    cuenta = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(False, True))
    maximo = youtube_api.DAILY_QUOTA // youtube_api.COST_UPLOAD
    for _ in range(maximo):
        gastado = _post(session, clip, cuenta, PostStatus.published.value)
        gastado.published_at = utcnow()
    session.commit()

    post = _post(session, clip, cuenta)
    pipeline.job_publish(session, _contexto(session, post))

    assert post.status == PostStatus.scheduled.value          # no ha fallado
    assert not post.error
    assert post.scheduled_at > utcnow() + timedelta(hours=23)
    assert "cuota" in post.slot_reason.lower()
    assert clip.status == ClipStatus.scheduled.value
    avisos = session.query(Notification).all()
    assert any("cuota" in (a.title or "").lower() for a in avisos)


def test_si_falla_un_destino_el_otro_sigue_en_pie(session, tmp_path, monkeypatch):
    """Con dos destinos, que TikTok falle no debe cancelar el Short."""
    from app.models import ClipStatus, PostStatus

    monkeypatch.setattr(settings, "dry_run", False)

    tiktok = _cuenta(session, Platform.tiktok.value)
    youtube = _cuenta(session, Platform.youtube.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, True))
    post_tiktok = _post(session, clip, tiktok)
    post_youtube = _post(session, clip, youtube)

    def revienta(*_args, **_kwargs):
        raise RuntimeError("TikTok ha dicho que no")

    monkeypatch.setattr(pipeline, "_publish_to_tiktok", revienta)

    with pytest.raises(RuntimeError):
        pipeline.job_publish(session, _contexto(session, post_tiktok))

    assert post_tiktok.status == PostStatus.failed.value
    assert post_youtube.status == PostStatus.scheduled.value   # intacto
    # el clip sigue programado porque le queda una publicación viva
    assert clip.status == ClipStatus.scheduled.value


def test_si_falla_el_unico_destino_el_clip_si_se_da_por_fallido(session, tmp_path, monkeypatch):
    from app.models import ClipStatus, PostStatus

    monkeypatch.setattr(settings, "dry_run", False)
    tiktok = _cuenta(session, Platform.tiktok.value)
    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    post = _post(session, clip, tiktok)

    def revienta(*_args, **_kwargs):
        raise RuntimeError("TikTok ha dicho que no")

    monkeypatch.setattr(pipeline, "_publish_to_tiktok", revienta)
    with pytest.raises(RuntimeError):
        pipeline.job_publish(session, _contexto(session, post))

    assert post.status == PostStatus.failed.value
    assert clip.status == ClipStatus.failed.value


def test_el_flujo_del_canal_manda_aunque_no_se_pida(session):
    """Si el canal tiene su propio flujo, procesar el vídeo debe usar ese."""
    from app.models import Flow, Source, Video

    por_defecto = Flow(name="El de siempre", is_default=True, steps=[])
    del_canal = Flow(name="El del canal", steps=[])
    session.add_all([por_defecto, del_canal])
    session.flush()

    canal = Source(name="Mi canal", url="https://example.invalid/c", flow_id=del_canal.id)
    session.add(canal)
    session.flush()
    video = Video(source_id=canal.id, external_id="v9", title="Vídeo", url="x")
    suelto = Video(external_id="v10", title="Sin canal", url="x")
    session.add_all([video, suelto])
    session.commit()

    assert pipeline.resolve_flow(session, None, video).id == del_canal.id
    # una orden explícita sigue mandando por encima del canal
    assert pipeline.resolve_flow(session, por_defecto.id, video).id == por_defecto.id
    # y un vídeo sin canal se queda con el predeterminado
    assert pipeline.resolve_flow(session, None, suelto).id == por_defecto.id
