"""Que Kevil se abra como programa, no como pestaña del navegador."""

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ventana  # noqa: E402


# --------------------------------------------------------------------------
# Encontrar con qué abrir la ventana
# --------------------------------------------------------------------------
def test_se_puede_decir_donde_esta_el_navegador(tmp_path, monkeypatch):
    """KEVIL_BROWSER manda: por si lo tienes instalado en un sitio raro."""
    falso = tmp_path / "msedge.exe"
    falso.write_text("no soy un navegador de verdad")
    monkeypatch.setenv("KEVIL_BROWSER", str(falso))
    assert ventana.buscar_navegador() == str(falso)

    # una ruta que no existe se ignora y se sigue buscando por los sitios de siempre
    monkeypatch.setenv("KEVIL_BROWSER", str(tmp_path / "no-existe.exe"))
    assert ventana.buscar_navegador() != str(tmp_path / "no-existe.exe")


def test_se_busca_en_los_sitios_de_cada_sistema(tmp_path, monkeypatch):
    monkeypatch.delenv("KEVIL_BROWSER", raising=False)
    edge = tmp_path / "msedge.exe"
    edge.write_text("x")

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    monkeypatch.setattr(ventana, "CANDIDATOS_WINDOWS", [str(edge)])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert ventana.buscar_navegador() == str(edge)

    # si no está ninguno, se dice que no, no se inventa una ruta
    monkeypatch.setattr(ventana, "CANDIDATOS_WINDOWS", [str(tmp_path / "nada.exe")])
    assert ventana.buscar_navegador() == ""


# --------------------------------------------------------------------------
# La ventana sin barra de direcciones
# --------------------------------------------------------------------------
def _navegador_falso(tmp_path: Path, segundos: float, registro: Path) -> Path:
    """Un «navegador» de mentira que apunta sus argumentos y vive un rato."""
    guion = tmp_path / "navegador_falso.py"
    guion.write_text(
        "import sys, time\n"
        f"open({str(registro)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
        f"time.sleep({segundos})\n",
        encoding="utf-8",
    )
    lanzador = tmp_path / "navegador.sh"
    lanzador.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{guion}" "$@"\n', encoding="utf-8")
    lanzador.chmod(0o755)
    return lanzador


@pytest.mark.skipif(os.name == "nt", reason="el guion de prueba es de shell")
def test_se_abre_en_modo_aplicacion_con_su_propio_perfil(tmp_path):
    """Las opciones son las que quitan la barra de direcciones y las pestañas."""
    registro = tmp_path / "argumentos.txt"
    falso = _navegador_falso(tmp_path, 6.0, registro)
    perfil = tmp_path / "perfil"

    os.environ["KEVIL_BROWSER"] = str(falso)
    try:
        assert ventana.abrir_modo_app("http://127.0.0.1:9999", perfil) is True
    finally:
        os.environ.pop("KEVIL_BROWSER", None)

    argumentos = registro.read_text(encoding="utf-8").splitlines()
    # --app es lo que hace que no haya barra de direcciones ni pestañas
    assert "--app=http://127.0.0.1:9999" in argumentos
    # el perfil aparte es lo que la separa de tus pestañas y permite esperarla
    assert f"--user-data-dir={perfil}" in argumentos
    assert perfil.is_dir()


@pytest.mark.skipif(os.name == "nt", reason="el guion de prueba es de shell")
def test_una_ventana_que_se_muere_al_instante_no_cuenta(tmp_path):
    """Si el navegador se cierra solo, hay que probar lo siguiente, no salir."""
    registro = tmp_path / "argumentos.txt"
    falso = _navegador_falso(tmp_path, 0.1, registro)

    os.environ["KEVIL_BROWSER"] = str(falso)
    try:
        assert ventana.abrir_modo_app("http://127.0.0.1:9999", tmp_path / "p") is False
    finally:
        os.environ.pop("KEVIL_BROWSER", None)


def test_sin_navegador_no_se_intenta_el_modo_aplicacion(tmp_path, monkeypatch):
    monkeypatch.setattr(ventana, "buscar_navegador", lambda: "")
    assert ventana.abrir_modo_app("http://127.0.0.1:9999", tmp_path / "p") is False


# --------------------------------------------------------------------------
# El orden en que se intenta cada cosa
# --------------------------------------------------------------------------
def test_primero_la_nativa_y_si_no_el_modo_aplicacion(tmp_path, monkeypatch):
    pasos: list[str] = []
    monkeypatch.setattr(ventana, "esperar_al_servidor", lambda *a, **k: True)
    monkeypatch.setattr(ventana, "abrir_nativa", lambda *a, **k: pasos.append("nativa") or True)

    assert ventana.abrir("http://x", perfil=tmp_path / "p") == "nativa"
    assert pasos == ["nativa"]

    # sin ventana nativa se cae al modo aplicación, que es una ventana igual
    pasos.clear()
    monkeypatch.setattr(ventana, "abrir_nativa", lambda *a, **k: pasos.append("nativa") or False)
    monkeypatch.setattr(ventana, "buscar_navegador", lambda: "/usr/bin/msedge")
    monkeypatch.setattr(
        ventana, "abrir_modo_app", lambda *a, **k: pasos.append("app") or True
    )
    assert ventana.abrir("http://x", perfil=tmp_path / "p") == "app"
    assert pasos == ["nativa", "app"]


def test_el_navegador_normal_es_el_ultimo_recurso(tmp_path, monkeypatch):
    monkeypatch.setattr(ventana, "esperar_al_servidor", lambda *a, **k: True)
    monkeypatch.setattr(ventana, "abrir_nativa", lambda *a, **k: False)
    monkeypatch.setattr(ventana, "buscar_navegador", lambda: "")
    abiertos: list[str] = []
    monkeypatch.setattr(ventana, "abrir_navegador", lambda url: abiertos.append(url) or True)

    assert ventana.abrir("http://x", perfil=tmp_path / "p") == "navegador"
    assert abiertos == ["http://x"]


def test_si_se_pide_navegador_no_se_abre_ninguna_ventana(tmp_path, monkeypatch):
    monkeypatch.setattr(ventana, "esperar_al_servidor", lambda *a, **k: True)
    monkeypatch.setattr(ventana, "abrir_nativa", lambda *a, **k: pytest.fail("no tocaba"))
    monkeypatch.setattr(ventana, "abrir_navegador", lambda url: True)
    assert ventana.abrir("http://x", perfil=tmp_path / "p", preferencia="navegador") == "navegador"


def test_si_el_servidor_no_arranca_se_dice(tmp_path, monkeypatch):
    monkeypatch.setattr(ventana, "esperar_al_servidor", lambda *a, **k: False)
    assert ventana.abrir("http://x", perfil=tmp_path / "p") == "sin-servidor"


def test_esperar_al_servidor_se_rinde(monkeypatch):
    inicio = time.monotonic()
    assert ventana.esperar_al_servidor("http://127.0.0.1:9", segundos=1.0) is False
    assert time.monotonic() - inicio < 6


# --------------------------------------------------------------------------
# El icono y el acceso directo
# --------------------------------------------------------------------------
def test_el_icono_existe_y_es_un_ico_de_verdad():
    raiz = Path(__file__).resolve().parent.parent
    ico = raiz / "app" / "web" / "img" / "kevil.ico"
    png = raiz / "app" / "web" / "favicon.png"
    assert ico.is_file() and png.is_file()

    cabecera = ico.read_bytes()[:6]
    assert cabecera[:4] == b"\x00\x00\x01\x00"          # es un .ico
    assert int.from_bytes(cabecera[4:6], "little") >= 5  # con varios tamaños
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(platform.system() != "Linux", reason="cada sistema, lo suyo")
def test_el_acceso_directo_apunta_a_kevil(monkeypatch, tmp_path):
    import acceso_directo

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    creados = acceso_directo.crear()
    assert creados, "no se ha creado nada"
    contenido = creados[0].read_text(encoding="utf-8")
    assert "Kevil Studio" in contenido
    assert "run.py" in contenido
    assert "Terminal=false" in contenido      # sin consola: es un programa

    assert acceso_directo.quitar() == 1
    assert not creados[0].exists()


def test_el_diagnostico_dice_con_que_se_puede_abrir():
    raiz = Path(__file__).resolve().parent.parent
    salida = subprocess.run(
        [sys.executable, str(raiz / "run.py"), "--diagnostico"],
        capture_output=True, text=True, timeout=90, cwd=str(raiz),
    )
    assert salida.returncode == 0
    texto = salida.stdout
    assert "Modo app:" in texto and "Nativa:" in texto and "ffmpeg:" in texto


def test_la_consola_de_windows_no_tumba_el_arranque():
    """En Windows la salida es cp1252 cuando no va a una consola de verdad.

    Ahí no caben los bloques del banner ni el signo de aviso, y sin protección
    Kevil se caía con UnicodeEncodeError antes siquiera de arrancar.
    """
    raiz = Path(__file__).resolve().parent.parent
    entorno = dict(os.environ, PYTHONIOENCODING="cp1252")
    salida = subprocess.run(
        [sys.executable, str(raiz / "run.py"), "--diagnostico"],
        capture_output=True, text=True, timeout=90, cwd=str(raiz), env=entorno,
    )
    assert salida.returncode == 0, salida.stderr[-800:]
    assert "UnicodeEncodeError" not in salida.stderr
    assert "KEVIL STUDIO" in salida.stdout
