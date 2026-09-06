"""Que no te llene el disco: modo ligero, limpieza automática y tope."""

import subprocess
from pathlib import Path

import pytest

from app.config import settings
from app.flow_schema import normalize_steps
from app.models import (
    Account, AccountStatus, Clip, ClipStatus, Flow, Job, Platform, Post,
    PostStatus, Video, utcnow,
)
from app.services import pipeline, storage
from app.services import media as media_service


def _cuenta(session):
    cuenta = Account(
        platform=Platform.tiktok.value, display_name="Cuenta", handle="c",
        external_id="c1", status=AccountStatus.connected.value,
    )
    session.add(cuenta)
    session.commit()
    return cuenta


def _flujo(session, estrategia="smart", nombre="De prueba"):
    pasos = normalize_steps([])
    for paso in pasos:
        if paso["type"] == "segment":
            paso["config"]["strategy"] = estrategia
    flujo = Flow(name=nombre, steps=pasos)
    session.add(flujo)
    session.commit()
    return flujo


# --------------------------------------------------------------------------
# Cuándo se activa el modo ligero
# --------------------------------------------------------------------------
def test_el_modo_ligero_se_aplica_salvo_al_republicar_entero(session, monkeypatch):
    monkeypatch.setattr(settings, "light_mode", True)

    inteligente = _flujo(session, "smart", "Cortes")
    entero = _flujo(session, "completo", "Shorts tal cual")

    assert pipeline.usa_modo_ligero(inteligente) is True
    # republicar un Short entero no ahorra nada: el tramo es el vídeo completo
    assert pipeline.usa_modo_ligero(entero) is False

    monkeypatch.setattr(settings, "light_mode", False)
    assert pipeline.usa_modo_ligero(inteligente) is False


def test_solo_se_baja_audio_si_hay_que_oir_los_silencios(session):
    assert pipeline.necesita_audio(_flujo(session, "smart", "A")) is True
    assert pipeline.necesita_audio(_flujo(session, "silence", "B")) is True
    # cortar por trozos iguales o por texto no necesita oír nada
    assert pipeline.necesita_audio(_flujo(session, "fixed", "C")) is False
    assert pipeline.necesita_audio(_flujo(session, "completo", "D")) is False


# --------------------------------------------------------------------------
# Limpieza
# --------------------------------------------------------------------------
def _clip_con_archivo(session, tmp_path, *, nombre="clip.mp4", bytes_=200_000):
    video = Video(external_id="v1", title="Vídeo", url="x",
                  local_path=str(tmp_path / "original.mp4"))
    Path(video.local_path).write_bytes(b"0" * (bytes_ * 3))
    session.add(video)
    session.flush()
    archivo = tmp_path / nombre
    archivo.write_bytes(b"0" * bytes_)
    clip = Clip(video_id=video.id, index=1, title="Un clip", start_s=0, end_s=10,
                render_path=str(archivo), status=ClipStatus.rendered.value)
    session.add(clip)
    session.commit()
    return video, clip


def test_al_publicar_se_borra_el_clip_y_el_original(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "keep_clips", False)
    monkeypatch.setattr(settings, "keep_originals", False)

    video, clip = _clip_con_archivo(session, tmp_path)
    post = Post(clip_id=clip.id, account_id=_cuenta(session).id,
                scheduled_at=utcnow(), status=PostStatus.published.value)
    session.add(post)
    clip.status = ClipStatus.published.value
    session.commit()

    liberado = storage.after_publish(session, clip)
    assert liberado > 0
    assert not Path(tmp_path / "clip.mp4").exists()
    assert not Path(tmp_path / "original.mp4").exists()
    assert clip.render_path == "" and video.local_path == ""


def test_con_dos_destinos_no_se_borra_hasta_publicar_en_los_dos(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "keep_clips", False)
    monkeypatch.setattr(settings, "keep_originals", True)   # aquí sólo miramos el clip
    video, clip = _clip_con_archivo(session, tmp_path)
    cuenta = _cuenta(session)
    session.add(Post(clip_id=clip.id, account_id=cuenta.id, scheduled_at=utcnow(),
                     status=PostStatus.published.value))
    pendiente = Post(clip_id=clip.id, account_id=cuenta.id, scheduled_at=utcnow(),
                     status=PostStatus.scheduled.value)
    session.add(pendiente)
    session.commit()

    # el clip aún tiene que salir en la otra plataforma: su archivo se queda
    storage.after_publish(session, clip)
    assert Path(clip.render_path).exists()

    pendiente.status = PostStatus.published.value
    session.commit()
    assert storage.after_publish(session, clip) > 0
    assert not (tmp_path / "clip.mp4").exists()
    assert clip.render_path == ""


def test_si_pides_guardarlo_no_se_borra_nada(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "keep_clips", True)
    monkeypatch.setattr(settings, "keep_originals", True)

    _video, clip = _clip_con_archivo(session, tmp_path)
    session.add(Post(clip_id=clip.id, account_id=_cuenta(session).id,
                     scheduled_at=utcnow(), status=PostStatus.published.value))
    session.commit()

    assert storage.after_publish(session, clip) == 0
    assert Path(clip.render_path).exists()


def test_el_original_espera_a_que_no_queden_clips_por_montar(session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "keep_originals", False)
    video, clip = _clip_con_archivo(session, tmp_path)
    original = Path(video.local_path)
    pendiente = Clip(video_id=video.id, index=2, title="Otro", start_s=10, end_s=20,
                     status=ClipStatus.draft.value)
    session.add(pendiente)
    session.commit()

    assert storage.cleanup_video(session, video) == 0    # el otro clip aún no está
    assert original.exists()

    pendiente.status = ClipStatus.rendered.value
    session.commit()
    assert storage.cleanup_video(session, video) > 0
    assert not original.exists()
    assert video.local_path == ""


def test_el_tope_de_disco_borra_lo_mas_viejo_ya_publicado(session, monkeypatch):
    monkeypatch.setattr(settings, "keep_clips", False)
    monkeypatch.setattr(settings, "keep_originals", False)
    monkeypatch.setattr(settings, "disk_budget_gb", 0.0001)     # ~100 KB

    video = Video(external_id="v9", title="Vídeo", url="x")
    session.add(video)
    cuenta = _cuenta(session)
    session.flush()
    for i in range(3):
        archivo = settings.clips_path / f"tope-{i}.mp4"
        archivo.write_bytes(b"0" * 90_000)
        clip = Clip(video_id=video.id, index=i, title=f"Clip {i}", start_s=0, end_s=5,
                    render_path=str(archivo), status=ClipStatus.published.value)
        session.add(clip)
        session.flush()
        session.add(Post(clip_id=clip.id, account_id=cuenta.id,
                         scheduled_at=utcnow(), status=PostStatus.published.value))
    session.commit()

    resultado = storage.enforce_budget(session)
    assert resultado["freed_mb"] > 0
    restantes = list(settings.clips_path.glob("tope-*.mp4"))
    assert len(restantes) < 3         # ha borrado por lo menos uno


def test_el_resumen_de_espacio_cuadra(session):
    (settings.clips_path / "medida.mp4").write_bytes(b"0" * 1024 * 512)
    datos = storage.usage()
    assert datos["parts"]["clips"] >= 0.5
    assert datos["total_mb"] >= 0.5
    assert "budget_gb" in datos and "light_mode" in datos
    (settings.clips_path / "medida.mp4").unlink()


# --------------------------------------------------------------------------
# Renderizar bajando sólo el tramo
# --------------------------------------------------------------------------
@pytest.mark.skipif(not media_service.ffmpeg_ready(), reason="hace falta ffmpeg")
def test_renderiza_bajando_solo_el_tramo(session, tmp_path, monkeypatch):
    """Sin original en el disco, el render se baja sus segundos y los borra."""
    largo = tmp_path / "largo.mp4"
    subprocess.run(
        [settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=15:duration=60",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=60",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(largo)],
        check=True, capture_output=True,
    )

    flujo = _flujo(session, "smart", "Ligero")
    video = Video(external_id="lig1", title="Vídeo largo",
                  url="https://example.invalid/v", duration_s=60.0,
                  local_path="")                       # <- no hay original
    session.add(video)
    session.flush()
    clip = Clip(video_id=video.id, flow_id=flujo.id, index=1, title="Un clip",
                start_s=20.0, end_s=28.0, status=ClipStatus.draft.value,
                render_config={"reframe": {"mode": "blur"}})
    session.add(clip)
    session.commit()

    bajados: list[tuple] = []

    def falso_download_sections(url, ranges, **kwargs):
        """Imita a yt-dlp: recorta el tramo pedido de un archivo local."""
        bajados.append((url, tuple(ranges)))
        desde, hasta = ranges[0]
        destino = Path(kwargs.get("destination") or settings.work_path) / "tramo-lig1.mp4"
        subprocess.run(
            [settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
             "-ss", str(desde), "-to", str(hasta), "-i", str(largo),
             "-c", "copy", str(destino)],
            check=True, capture_output=True,
        )
        return str(destino)

    monkeypatch.setattr(
        pipeline.youtube_service, "download_sections", falso_download_sections
    )

    job = Job(kind="render", payload={"clip_id": clip.id}, status="running")
    session.add(job)
    session.commit()
    pipeline.job_render(session, pipeline.JobContext(session, job))

    # se pidió sólo el tramo del clip, con un poco de margen
    assert len(bajados) == 1
    (desde, hasta) = bajados[0][1][0]
    assert 18.0 <= desde <= 20.0 and 28.0 <= hasta <= 30.0

    assert clip.status == ClipStatus.rendered.value
    salida = Path(clip.render_path)
    assert salida.exists()

    # el clip dura lo que tenía que durar, no lo que duraba el tramo descargado
    duracion = media_service.probe(str(salida)).get("duration") or 0
    assert 7.0 <= duracion <= 9.5

    # y el tramo temporal ya no está en el disco
    assert not list(settings.work_path.glob("tramo-lig1.*"))


# --------------------------------------------------------------------------
# Tu carpeta de marca
# --------------------------------------------------------------------------
@pytest.mark.skipif(not media_service.ffmpeg_ready(), reason="hace falta ffmpeg")
def test_la_carpeta_de_marca_se_entiende_sola(session, monkeypatch):
    """Metes archivos sin ordenar y Kevil deduce qué es cada uno."""
    from app.services import brandkit

    raiz = settings.branding_path
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "zombis").mkdir(exist_ok=True)

    def imagen(destino, ancho, alto, color="0x224466", alfa=False):
        formato = "rgba" if alfa else "rgb24"
        subprocess.run(
            [settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", f"color=c={color}:s={ancho}x{alto}",
             "-pix_fmt", formato, "-frames:v", "1", str(destino)],
            check=True, capture_output=True,
        )

    imagen(raiz / "el-logo.png", 400, 400, "0xFF0033", alfa=True)
    imagen(raiz / "portada.jpg", 1920, 1080)
    imagen(raiz / "zombis" / "fondo-zombis.jpg", 1920, 1080, "0x1A3A1A")
    imagen(raiz / "para-shorts.jpg", 1080, 1920, "0x552211")
    (raiz / "sobre-mi.txt").write_text("Canal de gameplays. Tono gamberro.", encoding="utf-8")

    datos = brandkit.scan()
    tipos = {p["name"]: p["kind"] for lista in datos["pieces"].values() for p in lista}
    assert tipos["el-logo.png"] == "logo"            # PNG con alfa y cuadrado
    assert tipos["portada.jpg"] == "fondo"           # apaisada
    assert tipos["para-shorts.jpg"] == "vertical"    # más alta que ancha
    assert tipos["sobre-mi.txt"] == "notas"
    assert "gamberro" in datos["notes"]
    assert datos["accent"].startswith("#")

    # y al pedir fondo para un directo de zombis, gana el de la carpeta «zombis»
    elegido = brandkit.pick_background("zombis a las siete")
    assert Path(elegido).name == "fondo-zombis.jpg"

    # sin pistas, cualquier fondo vale, pero sigue siendo un fondo
    assert Path(brandkit.pick_background("")).suffix in {".jpg", ".png"}

    contexto = brandkit.context_for_ai()
    assert "gamberro" in contexto and "Color principal" in contexto

    for archivo in list(raiz.rglob("*")):
        if archivo.is_file():
            archivo.unlink()


def test_sin_carpeta_de_marca_no_pasa_nada(session):
    from app.services import brandkit

    for archivo in list(settings.branding_path.rglob("*")):
        if archivo.is_file():
            archivo.unlink()
    datos = brandkit.scan()
    assert datos["total"] == 0
    assert brandkit.pick_background("lo que sea") == ""
    assert brandkit.pick_logo() == ""
    assert brandkit.context_for_ai() == ""


# --------------------------------------------------------------------------
# Reintentar más tarde cuando YouTube nos frena
# --------------------------------------------------------------------------
def test_un_trabajo_puede_pedir_esperar(session):
    """Es como se reintenta un «too many requests» sin machacar a YouTube."""
    from datetime import timedelta

    from app.services.queue import enqueue

    ahora = enqueue(session, "ingest", {"video_id": 1}, message="ya")
    luego = enqueue(
        session, "ingest", {"video_id": 2}, message="dentro de un rato",
        run_at=utcnow() + timedelta(minutes=45),
    )
    session.commit()

    assert ahora.run_at <= utcnow()
    assert luego.run_at > utcnow() + timedelta(minutes=40)


def test_el_error_de_youtube_se_explica_en_cristiano():
    from app.services import youtube

    limite = youtube.traducir_error(RuntimeError("HTTP Error 429: Too Many Requests"))
    assert "too many requests" in limite.lower()
    assert "reintentará" in limite            # dice qué va a pasar, no sólo el fallo

    privado = youtube.traducir_error(RuntimeError("ERROR: Private video"))
    assert "privado" in privado.lower() and "cookies" in privado.lower()

    robot = youtube.traducir_error(RuntimeError("Sign in to confirm you're not a bot"))
    assert "robot" in robot.lower()

    # lo que no se reconoce se deja tal cual, no se inventa nada
    raro = youtube.traducir_error(RuntimeError("algo rarísimo pasó"))
    assert raro == "algo rarísimo pasó"
