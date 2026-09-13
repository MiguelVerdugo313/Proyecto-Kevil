"""Los colores del canal: extracción, ajuste de contraste y endpoints."""

import contextlib
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import bootstrap
from app.config import settings
from app.db import SessionLocal, engine, init_db
from app.models import Account, Base, Platform
from app.services import branding


@contextlib.asynccontextmanager
async def _sin_lifespan(_app):
    yield


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    init_db()
    with SessionLocal() as session:
        bootstrap.seed_flows(session)
        session.commit()

    from app.main import app

    app.router.lifespan_context = _sin_lifespan
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------------------
# Color
# --------------------------------------------------------------------------
def test_lee_el_color_venga_como_venga():
    assert branding.from_hex("#FF0033") == (255, 0, 51)
    assert branding.from_hex("ff0033") == (255, 0, 51)
    assert branding.from_hex("#f03") == (255, 0, 51)      # atajo de tres cifras
    assert branding.from_hex("no es un color") == (52, 211, 153)   # el de siempre
    assert branding.to_hex((255.4, -3, 300)) == "#FF00FF"          # se recorta


def test_el_contraste_es_el_de_la_wcag():
    blanco_sobre_negro = branding.contrast((255, 255, 255), (0, 0, 0))
    assert round(blanco_sobre_negro, 1) == 21.0
    assert branding.contrast((120, 120, 120), (120, 120, 120)) == 1.0


@pytest.mark.parametrize(
    "color",
    ["#FF0033", "#34D399", "#1D4ED8", "#111111", "#7C3AED", "#F59E0B", "#FFFFFF"],
)
def test_cualquier_color_de_marca_acaba_legible(color):
    """Sea cual sea el logo, el acento tiene que leerse en los dos modos."""
    oscuro = branding.adjust_for_dark(color)
    claro = branding.adjust_for_light(color)
    assert branding.contrast(branding.from_hex(oscuro), (0, 0, 0)) >= 4.4
    assert branding.contrast(branding.from_hex(claro), (255, 255, 255)) >= 4.4


def test_un_color_ya_legible_no_se_toca_en_modo_oscuro():
    # el rojo puro ya contrasta de sobra sobre negro
    assert branding.adjust_for_dark("#FF0033") == "#FF0033"


def test_el_texto_de_encima_se_elige_por_contraste():
    assert branding.ink_for("#FDE047") == "#08130F"     # amarillo claro -> texto oscuro
    assert branding.ink_for("#1D4ED8") == "#FFFFFF"     # azul oscuro -> texto blanco


def test_el_tema_trae_las_dos_variantes():
    tema = branding.build_theme("#FF0033", "#00A3FF")
    assert set(tema) >= {
        "source_accent", "accent_dark", "accent_light",
        "accent2_dark", "accent2_light", "ink_dark", "ink_light",
    }
    assert tema["source_accent"] == "#FF0033"
    assert tema["ink_dark"] in {"#08130F", "#FFFFFF"}


def test_sin_color_guardado_el_tema_es_el_de_casa():
    anterior = settings.brand_accent
    settings.brand_accent = ""
    try:
        assert branding.current_theme() == {"custom": False}
    finally:
        settings.brand_accent = anterior


# --------------------------------------------------------------------------
# Paleta a partir de una imagen
# --------------------------------------------------------------------------
def _hay_ffmpeg() -> bool:
    try:
        subprocess.run(
            [settings.ffmpeg_path, "-version"], capture_output=True, timeout=20
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):  # pragma: no cover
        return False


@pytest.mark.skipif(not _hay_ffmpeg(), reason="hace falta ffmpeg")
def test_saca_el_color_vivo_de_un_logo(tmp_path):
    """Un logo casi todo gris con una franja de color: gana el color."""
    logo = tmp_path / "logo.png"
    subprocess.run(
        [
            settings.ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=0x232323:s=256x256",
            "-f", "lavfi", "-i", "color=c=0xFF0033:s=256x80",
            "-filter_complex", "[0][1]overlay=0:88",
            "-frames:v", "1", str(logo),
        ],
        check=True,
        capture_output=True,
    )

    paleta = branding.palette_from_image(logo)
    assert paleta, "no se ha leído ningún color"
    r, g, b = branding.from_hex(paleta[0]["hex"])
    assert r > 180 and g < 80 and b < 110      # el rojo, no el gris de fondo
    assert 0 < paleta[0]["share"] <= 1


@pytest.mark.skipif(not _hay_ffmpeg(), reason="hace falta ffmpeg")
def test_una_imagen_que_no_lo_es_no_revienta(tmp_path):
    roto = tmp_path / "esto-no-es-una-imagen.png"
    roto.write_bytes(b"hola")
    assert branding.palette_from_image(roto) == []


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
def test_branding_por_defecto(client):
    datos = client.get("/api/branding").json()
    assert datos["theme"] == {"custom": False}
    assert datos["default_accent"] == "#34D399"
    assert datos["channels"] == []


def test_poner_y_quitar_un_color_a_mano(client):
    respuesta = client.post("/api/branding", json={"accent": "#FF0033"})
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["accent"] == "#FF0033"
    assert datos["source"] == "manual"
    assert datos["theme"]["custom"] is True

    guardado = client.get("/api/branding").json()
    assert guardado["accent"] == "#FF0033"
    assert guardado["theme"]["accent_dark"]
    assert guardado["theme"]["accent_light"]

    assert client.delete("/api/branding").json()["theme"] == {"custom": False}
    assert client.get("/api/branding").json()["theme"] == {"custom": False}


def test_hace_falta_decir_algo(client):
    assert client.post("/api/branding", json={}).status_code == 400


def test_el_canal_sin_imagen_avisa(client):
    with SessionLocal() as session:
        cuenta = Account(
            platform=Platform.youtube.value,
            display_name="Canal sin foto",
            handle="@sinfoto",
            external_id="UC-sin-foto",
        )
        session.add(cuenta)
        session.commit()
        sin_imagen = cuenta.id

    respuesta = client.post("/api/branding", json={"account_id": sin_imagen})
    assert respuesta.status_code == 404

    # y un canal que ni existe
    assert client.post("/api/branding", json={"account_id": 9999}).status_code == 404


def test_los_canales_con_foto_salen_como_opcion(client):
    with SessionLocal() as session:
        cuenta = Account(
            platform=Platform.youtube.value,
            display_name="Canal con foto",
            handle="@confoto",
            external_id="UC-con-foto",
            avatar_url="https://example.invalid/avatar.jpg",
        )
        session.add(cuenta)
        session.commit()

    canales = client.get("/api/branding").json()["channels"]
    assert [c["name"] for c in canales] == ["Canal con foto"]
    assert canales[0]["platform"] == "youtube"
