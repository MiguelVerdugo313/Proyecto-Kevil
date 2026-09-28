"""Limpieza del clip: silencios largos y muletillas fuera, rótulos en su sitio."""

import pytest

from app.config import settings
from app.flow_schema import default_config
from app.services import limpieza, renderer
from app.services import media as media_service

PALABRAS = [
    {"start": 0.2, "end": 0.6, "text": "vamos"},
    {"start": 0.7, "end": 1.0, "text": "eh"},
    {"start": 1.1, "end": 1.5, "text": "a"},
    {"start": 1.5, "end": 2.0, "text": "ganar"},
    # tres segundos sin hablar
    {"start": 5.0, "end": 5.4, "text": "¡Mmm!"},
    {"start": 5.5, "end": 6.0, "text": "increíble"},
]


def test_que_es_una_muletilla():
    for si in ("eh", "Ehh", "em", "mmm", "¡Mmm!", "hmm", "um", "uh", "eee"):
        assert limpieza.es_muletilla(si), si
    for no in ("e", "este", "pues", "me", "mi", "ahí", "hum…no", "ah", "y"):
        assert not limpieza.es_muletilla(no), no


def test_sin_nada_encendido_no_se_toca():
    assert limpieza.cortes(PALABRAS, 7.0) == []
    assert limpieza.recolocar(PALABRAS, [], muletillas=False) == PALABRAS


def test_quita_los_silencios_y_deja_aire():
    cortes = limpieza.cortes(PALABRAS, 7.0, silencios=True, pausa_max=0.8)
    assert len(cortes) == 1
    a, b = cortes[0]
    assert a == pytest.approx(2.0 + limpieza.AIRE_DESPUES)
    assert b == pytest.approx(5.0 - limpieza.AIRE_ANTES)
    quedan = limpieza.tramos(7.0, cortes)
    assert quedan[0][0] == 0 and quedan[-1][1] == 7.0
    # las palabras de después llegan antes, las de antes no se mueven
    nuevas = limpieza.recolocar(PALABRAS, cortes, muletillas=False)
    assert nuevas[0] == PALABRAS[0]
    assert nuevas[-1]["start"] == pytest.approx(5.5 - (b - a), abs=0.01)


def test_quita_las_muletillas_y_sus_rotulos():
    cortes = limpieza.cortes(PALABRAS, 7.0, muletillas=True)
    assert len(cortes) == 2                       # el «eh» y el «mmm»
    nuevas = limpieza.recolocar(PALABRAS, cortes, muletillas=True)
    textos = [w["text"] for w in nuevas]
    assert "eh" not in textos and "¡Mmm!" not in textos
    assert textos == ["vamos", "a", "ganar", "increíble"]
    # nunca se solapan ni van hacia atrás
    for antes, despues in zip(nuevas, nuevas[1:]):
        assert antes["end"] <= despues["start"] + 1e-6


def test_los_dos_a_la_vez_no_se_pisan():
    cortes = limpieza.cortes(PALABRAS, 7.0, silencios=True, muletillas=True)
    for (a1, b1), (a2, b2) in zip(cortes, cortes[1:]):
        assert b1 < a2
    total = sum(b - a for a, b in cortes)
    assert 2.5 < total < 4.0
    assert "cortes" in limpieza.resumen(7.0, cortes)


@pytest.mark.skipif(not media_service.ffmpeg_ready(), reason="ffmpeg no está instalado")
def test_render_real_con_limpieza(tmp_path):
    origen = tmp_path / "origen.mp4"
    media_service.make_test_video(origen, seconds=10)
    salida = tmp_path / "limpio.mp4"
    settings.work_path.mkdir(parents=True, exist_ok=True)
    resultado = renderer.render_clip(
        source_path=origen,
        start=1,
        end=8,
        output_path=salida,
        reframe={**default_config("reframe"), "resolution": "540x960"},
        audio=default_config("audio"),
        subtitles={**default_config("subtitles"), "template": "hormozi"},
        overlays=default_config("overlays"),
        words=PALABRAS,
        hook_text="gancho",
        limpieza={"remove_silences": True, "remove_fillers": True, "max_pause": 0.8},
    )
    assert salida.exists()
    # 7 s de clip menos lo quitado, con audio y vídeo del mismo largo
    esperado = 7.0 - resultado["quitado_s"]
    assert resultado["quitado_s"] > 2.5
    assert abs(resultado["duration"] - esperado) < 0.35
    assert resultado["limpieza"].startswith("Limpieza:")


def test_editar_el_clip_recoloca_rotulos_y_guarda_lo_suyo(session, tmp_path):
    import contextlib

    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app
    from app.models import ClipStatus
    from tests.test_youtube_publish import _clip_listo, _pasos_publicando_en

    clip = _clip_listo(session, tmp_path, _pasos_publicando_en(True, False))
    clip.video.transcript = {"words": [
        {"start": 3.0, "end": 3.5, "text": "hola"},
        {"start": 12.0, "end": 12.5, "text": "adiós"},
    ]}
    session.commit()

    @contextlib.asynccontextmanager
    async def _nada(_app):
        yield

    app.router.lifespan_context = _nada
    app.dependency_overrides[get_db] = lambda: session
    try:
        with TestClient(app) as cliente:
            r = cliente.patch(f"/api/clips/{clip.id}", json={"start_s": 10, "end_s": 20})
            assert r.status_code == 200, r.text
            # el rótulo de «adiós» cae a los 2 s del nuevo inicio
            assert clip.words == [{"start": 2.0, "end": 2.5, "text": "adiós"}]
            assert clip.status == ClipStatus.draft.value          # hay que volver a montarlo

            r = cliente.patch(f"/api/clips/{clip.id}", json={
                "subtitles": {"template": "gamer", "font": "Arial"},
                "cleanup": {"remove_fillers": True, "otra": 1},
            })
            assert r.status_code == 200
            assert clip.render_config["subtitles"] == {"template": "gamer"}   # sólo lo permitido
            assert clip.render_config["cleanup"] == {"remove_fillers": True}
            assert cliente.patch(f"/api/clips/{clip.id}",
                                 json={"subtitles": {"template": "no-existe"}}).status_code == 400

            lista = cliente.get("/api/flows/plantillas-rotulos").json()
            assert {p["id"] for p in lista} >= {"kevil", "hormozi", "gamer"}
            archivo = next(p["archivo"] for p in lista if p["id"] == "gamer")
            assert cliente.get(f"/api/flows/plantillas-rotulos/fuente/{archivo}").status_code == 200
            assert cliente.get("/api/flows/plantillas-rotulos/fuente/..%2F..%2Fconfig.py").status_code == 404
    finally:
        app.dependency_overrides.clear()
