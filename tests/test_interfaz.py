"""La interfaz: que se sirva fresca, con sus tipografías y sin trampas visuales."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.version import VERSION

WEB = Path(__file__).resolve().parent.parent / "app" / "web"


@pytest.fixture(scope="module")
def client():
    from app.main import app

    @contextlib.asynccontextmanager
    async def _sin_lifespan(_app):
        yield

    app.router.lifespan_context = _sin_lifespan
    with TestClient(app) as test_client:
        yield test_client


# --------------------------------------------------------------------------
# Que al actualizar se vea lo nuevo
# --------------------------------------------------------------------------
def test_la_pagina_va_sin_cache_y_con_la_version(client):
    respuesta = client.get("/")
    assert respuesta.status_code == 200
    assert "no-store" in respuesta.headers.get("cache-control", "")
    assert f"style.css?v={VERSION}" in respuesta.text
    assert "__V__" not in respuesta.text


def test_los_archivos_de_la_interfaz_tampoco_se_guardan(client):
    for ruta in ("/static/css/style.css", "/static/js/app.js"):
        respuesta = client.get(ruta)
        assert respuesta.status_code == 200
        assert "no-store" in respuesta.headers.get("cache-control", "")


def test_al_codigo_no_se_le_cuelga_la_version():
    """Con «?v=» el navegador carga dos copias del módulo y la interfaz revienta.

    Los módulos se importan entre ellos por su ruta pelada («../app.js»), así que
    app.js?v=1.2.3 y app.js serían dos módulos distintos: el segundo entra en el
    ciclo a medio inicializar y salta «Cannot access 'ajustes' before
    initialization». Basta con servirlo sin caché.
    """
    html = (WEB / "index.html").read_text(encoding="utf-8")
    script = re.search(r'<script type="module" src="([^"]+)"', html)
    assert script, "no se encuentra el script de arranque"
    assert "?" not in script.group(1)


# --------------------------------------------------------------------------
# Tipografías incluidas
# --------------------------------------------------------------------------
def test_las_tipografias_van_dentro_y_no_de_internet():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert "fonts.googleapis.com" not in html
    assert "/static/css/fuentes.css" in html

    css = (WEB / "css" / "fuentes.css").read_text(encoding="utf-8")
    archivos = set(re.findall(r"/static/fonts/([\w.-]+\.woff2)", css))
    assert archivos, "fuentes.css no apunta a ningún archivo"
    for nombre in archivos:
        assert (WEB / "fonts" / nombre).is_file(), f"falta la tipografía {nombre}"
    assert any("Playfair" in n for n in archivos)
    assert any("Inter" in n for n in archivos)


# --------------------------------------------------------------------------
# El fallo de los desplegables
# --------------------------------------------------------------------------
def test_los_desplegables_no_quedan_blanco_sobre_blanco():
    """Windows pinta la lista con el color del select: si es translúcido, se ve
    blanco sobre blanco y no se lee nada."""
    css = (WEB / "css" / "style.css").read_text(encoding="utf-8")

    assert "color-scheme: dark" in css
    bloque = css[css.index("select {") : css.index("input[type=\"range\"]")]
    assert "background-color: var(--solid)" in bloque
    assert "select option" in bloque

    # y ese color tiene que ser opaco de verdad, no un rgba
    solido = re.search(r"--solid:\s*(#[0-9A-Fa-f]{6})", css)
    assert solido, "--solid tiene que ser un color sólido"


def test_el_estilo_es_el_del_canal():
    css = (WEB / "css" / "style.css").read_text(encoding="utf-8")
    assert "--bg: #0A0A0A" in css
    assert "--accent: #A78B71" in css          # oro base
    assert "--accent-2: #C9B8A0" in css        # oro claro
    assert "--accent-hover: #E8D5B7" in css    # oro al pasar por encima
    assert "cubic-bezier(.4, 0, .2, 1)" in css
    assert "rgba(167, 139, 113, .2)" in css    # el resplandor
    assert "Playfair Display" in css
    assert "background-size: 32px 32px" in css  # la rejilla de puntos


def test_el_estilo_nuevo_mezcla_el_del_canal_con_la_aurora():
    """1.5: lo del canal (negro, puntos, oro, Playfair de acento) + aurora cálida,
    grano, Outfit, teclas y aparición al hacer scroll."""
    css = (WEB / "css" / "style.css").read_text(encoding="utf-8")
    html = (WEB / "index.html").read_text(encoding="utf-8")
    fuentes = (WEB / "css" / "fuentes.css").read_text(encoding="utf-8")

    for familia in ("Outfit", "Reenie Beanie", "Geist Mono"):
        assert f"font-family: '{familia}'" in fuentes
    assert "'Outfit'" in css and "var(--font-hand)" in css
    # aurora sólo cálida: carmesí, coral, ámbar (nada de violetas)
    assert "--aurora-1: #FF2F3A" in css and "--aurora-3: #FFB347" in css
    assert 'class="aurora"' in html and 'class="grano"' in html
    assert "prefers-reduced-motion" in css          # respeta a quien no quiere movimiento
    assert "body.quieto .aurora" in css             # y se para con la ventana oculta
    assert ".btn.primary" in css and "inset 0 -2px 0" in css   # la tecla en relieve
    assert ".reveal.visible" in css
    assert 'id="cmdk"' in html                       # la paleta de comandos


def test_las_graficas_usan_el_color_validado():
    css = (WEB / "css" / "style.css").read_text(encoding="utf-8")
    assert "--chart: #EC5A3E" in css                 # oscuro: contraste ≥ 3:1
    assert "--chart: #E0492E" in css                 # claro
