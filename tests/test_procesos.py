"""Que los programas que lanza Kevil no abran ventanas de terminal en Windows.

El .exe no tiene consola: cada ffmpeg que se lanzaba se creaba una propia y
Windows la ponía delante, sacando al usuario del juego o de lo que estuviera
haciendo. Estas pruebas vigilan que no vuelva a pasar.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from app import procesos

RAIZ = Path(__file__).resolve().parent.parent


def test_fuera_de_windows_no_se_toca_nada(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    procesos.opciones.cache_clear()
    try:
        assert procesos.opciones() == {}
    finally:
        procesos.opciones.cache_clear()


def test_en_windows_se_pide_que_no_haya_ventana(monkeypatch):
    """Se simula Windows: en Linux estas constantes no existen."""

    class Arranque:
        def __init__(self):
            self.dwFlags = 0
            self.wShowWindow = None

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(subprocess, "STARTUPINFO", Arranque, raising=False)
    monkeypatch.setattr(subprocess, "STARTF_USESHOWWINDOW", 1, raising=False)
    monkeypatch.setattr(subprocess, "SW_HIDE", 0, raising=False)
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    procesos.opciones.cache_clear()
    try:
        opciones = procesos.opciones()
        assert opciones["creationflags"] == 0x08000000
        assert opciones["startupinfo"].dwFlags & 1
        assert opciones["startupinfo"].wShowWindow == 0
    finally:
        procesos.opciones.cache_clear()


def test_run_se_comporta_como_el_de_siempre():
    """Captura la salida, respeta check= y deja el código de salida."""
    bien = procesos.run([sys.executable, "-c", "print('hola')"], capture_output=True, text=True)
    assert bien.returncode == 0 and bien.stdout.strip() == "hola"

    mal = procesos.run([sys.executable, "-c", "import sys; sys.exit(3)"], capture_output=True)
    assert mal.returncode == 3

    import pytest

    with pytest.raises(subprocess.CalledProcessError):
        procesos.run([sys.executable, "-c", "import sys; sys.exit(1)"], check=True)

    with pytest.raises(subprocess.TimeoutExpired):
        procesos.run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.3)
    assert procesos.vivos() == 0          # y el que se pasó de tiempo no queda vivo


def test_terminar_todos_corta_lo_que_haya_en_marcha():
    """Es lo que usa la pausa: un render a medias tiene que morir al momento."""
    import time

    lento = procesos.popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert procesos.vivos() >= 1
        assert procesos.terminar_todos() >= 1
        lento.wait(timeout=5)
        assert lento.returncode is not None
    finally:
        if lento.poll() is None:
            lento.kill()
    time.sleep(0.05)
    assert procesos.vivos() == 0


def test_nadie_lanza_procesos_por_su_cuenta():
    """Toda llamada a un programa externo tiene que pasar por app/procesos.py.

    Si alguien vuelve a escribir `subprocess.run(` a pelo dentro de la
    aplicación, en Windows vuelven a salir las terminales. Esta prueba lo
    pilla antes de que llegue al .exe.
    """
    patron = re.compile(r"\bsubprocess\.(run|Popen|call|check_output|check_call)\(")
    culpables = []
    for archivo in (RAIZ / "app").rglob("*.py"):
        if archivo.name == "procesos.py":
            continue
        for numero, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            if patron.search(linea) and not linea.lstrip().startswith("#"):
                culpables.append(f"{archivo.relative_to(RAIZ)}:{numero}")
    assert not culpables, "Usa app.procesos en vez de subprocess: " + ", ".join(culpables)
