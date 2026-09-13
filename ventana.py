"""La ventana de Kevil: que sea un programa, no una pestaña del navegador.

Se intentan tres cosas por orden, y la segunda funciona en cualquier Windows
sin instalar nada:

1. **Ventana nativa** (pywebview sobre el WebView2 de Windows, WebKit en macOS
   o GTK en Linux). Es lo ideal, pero depende de que se pueda instalar.
2. **Modo aplicación de Edge o Chrome** (``--app=``). Abre una ventana **sin
   barra de direcciones, sin pestañas y sin marcadores**, con su propio icono
   en la barra de tareas. Por dentro es el motor del navegador, pero para ti es
   un programa aparte: no puedes escribir una URL ni se mezcla con tus pestañas.
   Edge viene con Windows, así que esto está siempre disponible.
3. **Navegador normal**, sólo si no hay ninguna de las dos anteriores.

En los dos primeros casos el programa se queda esperando a que cierres la
ventana, y al cerrarla se para todo, como cualquier aplicación.
"""

from __future__ import annotations

import contextlib
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Una ventana que se cierra sola antes de esto no llegó a abrirse de verdad
VIVA_MINIMO = 4.0

# Dónde suelen estar Edge y Chrome en cada sistema
CANDIDATOS_WINDOWS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]
CANDIDATOS_MAC = [
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]
CANDIDATOS_LINUX = [
    "microsoft-edge", "microsoft-edge-stable",
    "google-chrome", "google-chrome-stable",
    "chromium", "chromium-browser", "brave-browser",
]


# --------------------------------------------------------------------------
# Esperar a que el servidor esté listo
# --------------------------------------------------------------------------
def esperar_al_servidor(url: str, segundos: float = 25.0) -> bool:
    import urllib.error
    import urllib.request

    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        try:
            with urllib.request.urlopen(f"{url}/api/status", timeout=1):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    return False


# --------------------------------------------------------------------------
# 1. Ventana nativa
# --------------------------------------------------------------------------
@contextlib.contextmanager
def _sin_ruido():
    """Se traga lo que se escriba en stderr.

    pywebview suelta un par de tracebacks enteros cuando el equipo no tiene con
    qué dibujar la ventana. No es un fallo que el usuario deba leer: hay plan B
    justo debajo y lo único que consigue es asustar.
    """
    import logging

    logging.getLogger("pywebview").setLevel(logging.CRITICAL)
    original = sys.stderr
    try:
        with open(os.devnull, "w", encoding="utf-8") as vacio:
            sys.stderr = vacio
            yield
    finally:
        sys.stderr = original


def abrir_nativa(url: str, titulo: str = "Kevil Studio") -> bool:
    """Ventana de verdad del sistema. Bloquea hasta que se cierra."""
    try:
        with _sin_ruido():
            import webview
    except Exception:
        return False

    try:
        with _sin_ruido():
            webview.create_window(
                titulo, url,
                width=1380, height=920, min_size=(1024, 680),
                background_color="#000000", text_select=True,
            )
            webview.start()
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# 2. Modo aplicación de Edge / Chrome
# --------------------------------------------------------------------------
def buscar_navegador() -> str:
    """Ruta a Edge o Chrome, que son los que saben abrir en modo aplicación."""
    # Por si lo tienes en un sitio raro: KEVIL_BROWSER=C:\ruta\a\msedge.exe
    propio = (os.environ.get("KEVIL_BROWSER") or "").strip().strip('"')
    if propio and Path(propio).is_file():
        return propio

    sistema = platform.system()
    if sistema == "Windows":
        candidatos = CANDIDATOS_WINDOWS
        # también en la carpeta del usuario, donde Chrome se instala a veces
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidatos = candidatos + [
                str(Path(local) / "Google/Chrome/Application/chrome.exe"),
                str(Path(local) / "Microsoft/Edge/Application/msedge.exe"),
            ]
    elif sistema == "Darwin":
        candidatos = CANDIDATOS_MAC
    else:
        candidatos = CANDIDATOS_LINUX

    for candidato in candidatos:
        if os.path.sep in candidato or (len(candidato) > 2 and candidato[1] == ":"):
            if Path(candidato).is_file():
                return candidato
        else:
            encontrado = shutil.which(candidato)
            if encontrado:
                return encontrado
    return ""


def abrir_modo_app(url: str, perfil: Path, *, esperar: bool = True) -> bool:
    """Ventana sin barra de direcciones ni pestañas, con su icono propio.

    El perfil aparte es lo que hace que sea **su** ventana: no se mete entre
    tus pestañas, no hereda tus extensiones y, al cerrarla, el proceso termina
    de verdad (si reutilizásemos tu navegador, se lo pasaría a la ventana que
    ya tienes abierta y no habría forma de saber cuándo se cierra).
    """
    navegador = buscar_navegador()
    if not navegador:
        return False

    perfil.mkdir(parents=True, exist_ok=True)
    args = [
        navegador,
        f"--app={url}",
        f"--user-data-dir={perfil}",
        "--window-size=1380,920",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-infobars",
        "--disable-features=Translate,MediaRouter,OptimizationHints",
        "--disable-background-networking",
        "--disable-component-update",
    ]
    # Por si tu equipo necesita algo más: KEVIL_BROWSER_ARGS="--flag --otro"
    extra = (os.environ.get("KEVIL_BROWSER_ARGS") or "").split()
    args.extend(extra)

    try:
        proceso = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return False

    if not esperar:
        return True

    # Si la ventana se muere nada más abrirla es que no ha podido: no vale
    # darla por buena y cerrar el programa, hay que probar lo siguiente.
    arranque = time.monotonic()
    try:
        proceso.wait()
    except KeyboardInterrupt:
        proceso.terminate()
        return True
    return time.monotonic() - arranque >= VIVA_MINIMO


# --------------------------------------------------------------------------
# 3. Navegador de siempre
# --------------------------------------------------------------------------
def abrir_navegador(url: str) -> bool:
    try:
        import webbrowser

        return bool(webbrowser.open(url))
    except Exception:
        return False


# --------------------------------------------------------------------------
# Ocultar la consola en Windows
# --------------------------------------------------------------------------
def ocultar_consola() -> bool:
    """Esconde la ventana negra una vez la aplicación está en pantalla.

    Un programa no enseña una consola. Si algo falla, se vuelve a mostrar
    (ver ``mostrar_consola``) para que se pueda leer el error.
    """
    if platform.system() != "Windows":
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetConsoleWindow()
        if not handle:
            return False
        ctypes.windll.user32.ShowWindow(handle, 0)      # SW_HIDE
        return True
    except Exception:
        return False


def mostrar_consola() -> None:
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetConsoleWindow()
        if handle:
            ctypes.windll.user32.ShowWindow(handle, 5)  # SW_SHOW
    except Exception:
        pass


# --------------------------------------------------------------------------
# Punto de entrada
# --------------------------------------------------------------------------
def abrir(
    url: str,
    *,
    perfil: Path,
    preferencia: str = "auto",
    al_abrir=None,
) -> str:
    """Abre Kevil como aplicación. Devuelve cómo se ha conseguido.

    ``preferencia``: "auto" (nativa, luego modo app), "nativa", "app"
    (Edge/Chrome sin barra) o "navegador".
    """
    if not esperar_al_servidor(url):
        return "sin-servidor"

    if preferencia in {"auto", "nativa"} and abrir_nativa(url):
        return "nativa"

    if preferencia in {"auto", "nativa", "app"}:
        navegador = buscar_navegador()
        if navegador:
            if al_abrir:
                al_abrir("app", navegador)
            if abrir_modo_app(url, perfil):
                return "app"

    if al_abrir:
        al_abrir("navegador", "")
    abrir_navegador(url)
    return "navegador"


if __name__ == "__main__":       # pragma: no cover - utilidad de diagnóstico
    print("Sistema:", platform.system())
    print("Navegador para modo aplicación:", buscar_navegador() or "(ninguno)")
    try:
        import importlib

        importlib.import_module("webview")
        print("Ventana nativa (pywebview): disponible")
    except Exception as exc:
        print(f"Ventana nativa (pywebview): no disponible ({exc})")
    print("Python:", sys.version.split()[0])
