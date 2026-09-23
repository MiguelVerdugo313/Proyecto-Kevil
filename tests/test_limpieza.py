"""«Liberar espacio» y borrar clips: se va lo que sobra, se queda lo que hace falta."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.config import settings
from app.models import (
    Account, AccountStatus, Clip, ClipStatus, Platform, Post, PostStatus, Video, utcnow,
)
from app.services import storage


@pytest.fixture
def carpetas(tmp_path, monkeypatch):
    """Carpetas de medios propias para no pisar las de otras pruebas."""
    rutas = {
        "sources_path": tmp_path / "originales",
        "clips_path": tmp_path / "clips",
        "thumbs_path": tmp_path / "miniaturas",
        "work_path": tmp_path / "trabajo",
    }
    for nombre, ruta in rutas.items():
        ruta.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(type(settings), nombre, property(lambda _s, r=ruta: r))
    return rutas


def _archivo(carpeta: Path, nombre: str, kb: int = 100, *, viejo: bool = True) -> Path:
    ruta = carpeta / nombre
    ruta.write_bytes(b"0" * kb * 1024)
    if viejo:  # los sueltos recientes no se tocan: se envejecen para la prueba
        hace = time.time() - 2 * storage.MARGEN_HUERFANOS_S
        os.utime(ruta, (hace, hace))
    return ruta


def _cuenta(session) -> Account:
    cuenta = Account(platform=Platform.tiktok.value, display_name="C", handle="c",
                     external_id="c1", status=AccountStatus.connected.value)
    session.add(cuenta)
    session.flush()
    return cuenta


def _clip(session, video, carpetas, nombre, estado, publicaciones=()):
    archivo = _archivo(carpetas["clips_path"], nombre)
    clip = Clip(video_id=video.id, index=1, title=nombre, start_s=0, end_s=10,
                render_path=str(archivo), status=estado)
    session.add(clip)
    session.flush()
    cuenta = _cuenta(session) if publicaciones else None
    for estado_post in publicaciones:
        session.add(Post(clip_id=clip.id, account_id=cuenta.id,
                         scheduled_at=utcnow(), status=estado_post))
    session.flush()
    return clip


def test_liberar_espacio_se_lleva_solo_lo_que_sobra(session, carpetas):
    hecho = Video(external_id="v1", title="Ya cortado", url="x",
                  local_path=str(_archivo(carpetas["sources_path"], "hecho.mp4", 300)))
    nuevo = Video(external_id="v2", title="Recién bajado", url="x",
                  local_path=str(_archivo(carpetas["sources_path"], "nuevo.mp4", 300)))
    session.add_all([hecho, nuevo])
    session.flush()

    descartado = _clip(session, hecho, carpetas, "descartado.mp4", ClipStatus.rejected.value)
    publicado = _clip(session, hecho, carpetas, "publicado.mp4", ClipStatus.published.value,
                      [PostStatus.published.value])
    por_revisar = _clip(session, hecho, carpetas, "revisar.mp4", ClipStatus.rendered.value)
    programado = _clip(session, hecho, carpetas, "programado.mp4", ClipStatus.scheduled.value,
                       [PostStatus.scheduled.value])
    fallido = _clip(session, hecho, carpetas, "fallido.mp4", ClipStatus.failed.value,
                    [PostStatus.failed.value])
    session.commit()

    temporal = _archivo(carpetas["work_path"], "resto.ass", 50)
    suelto_viejo = _archivo(carpetas["clips_path"], "de-nadie.mp4", 200)
    suelto_nuevo = _archivo(carpetas["clips_path"], "escribiendose.mp4", 200, viejo=False)

    plan = storage.plan_de_limpieza(session)
    assert plan["parts"]["descartados"] > 0
    assert plan["parts"]["publicados"] > 0
    assert plan["parts"]["originales"] > 0
    assert plan["parts"]["huerfanos"] > 0
    assert plan["total_mb"] > 0

    resultado = storage.liberar_espacio(session)
    session.commit()
    assert resultado["freed_mb"] > 0

    # se va
    assert not Path(descartado.render_path or "x").exists()
    assert not Path(publicado.render_path or "x").exists()
    assert hecho.local_path == ""
    assert not temporal.exists()
    assert not suelto_viejo.exists()

    # se queda
    assert Path(por_revisar.render_path).exists(), "lo que está por revisar no se toca"
    assert Path(programado.render_path).exists(), "lo programado no se toca"
    assert Path(fallido.render_path).exists(), "lo que falló puede querer reintentarse"
    assert Path(nuevo.local_path).exists(), "un vídeo aún sin cortar se necesita"
    assert suelto_nuevo.exists(), "un archivo recién escrito puede ser de un trabajo en marcha"

    # y una segunda pasada no encuentra nada más que llevarse
    assert storage.liberar_espacio(session)["freed_mb"] == 0


def test_borrar_clips_elegidos(session, carpetas):
    video = Video(external_id="v3", title="V", url="x")
    session.add(video)
    session.flush()
    uno = _clip(session, video, carpetas, "uno.mp4", ClipStatus.rendered.value)
    programado = _clip(session, video, carpetas, "prog.mp4", ClipStatus.scheduled.value,
                       [PostStatus.scheduled.value])
    subiendo = _clip(session, video, carpetas, "sube.mp4", ClipStatus.publishing.value,
                     [PostStatus.publishing.value])
    session.commit()
    rutas = {c.id: Path(c.render_path) for c in (uno, programado, subiendo)}

    resultado = storage.borrar_clips(session, [uno.id, programado.id, subiendo.id])
    session.commit()

    assert resultado["deleted"] == 2
    assert resultado["skipped"] == 1          # el que se está subiendo, no
    assert resultado["freed_mb"] > 0
    assert not rutas[uno.id].exists() and not rutas[programado.id].exists()
    assert rutas[subiendo.id].exists()
    assert session.get(Clip, uno.id) is None
    # la publicación programada se va con su clip
    assert session.query(Post).filter(Post.clip_id == programado.id).count() == 0


def test_borrar_todo_cancela_lo_programado(session, carpetas):
    """Sin archivo no se puede publicar: mejor cancelarlo que verlo fallar después."""
    video = Video(external_id="v4", title="V", url="x")
    session.add(video)
    session.flush()
    programado = _clip(session, video, carpetas, "p.mp4", ClipStatus.scheduled.value,
                       [PostStatus.scheduled.value])
    session.commit()

    storage.purge_everything(session)
    session.commit()
    assert programado.posts[0].status == PostStatus.cancelled.value
    assert programado.render_path == ""
