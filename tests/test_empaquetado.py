"""Que el .exe encuentre sus cosas y no te guarde los datos donde no debe."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import rutas  # noqa: E402


def test_con_el_codigo_suelto_todo_esta_en_el_proyecto():
    assert rutas.empaquetado() is False
    raiz = Path(__file__).resolve().parent.parent
    assert rutas.raiz_recursos() == raiz
    assert rutas.carpeta_del_programa() == raiz


def test_empaquetado_los_recursos_salen_del_paquete(monkeypatch, tmp_path):
    """Dentro del .exe, la interfaz vive donde PyInstaller la descomprime."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "descomprimido"), raising=False)

    assert rutas.empaquetado() is True
    assert rutas.raiz_recursos() == tmp_path / "descomprimido"


def test_los_datos_nunca_van_dentro_del_paquete(monkeypatch, tmp_path):
    """Si fuesen al paquete, se borrarían cada vez que cierras el programa."""
    temporal = tmp_path / "descomprimido"
    junto = tmp_path / "junto-al-exe"
    junto.mkdir()
    (junto / "Kevil Studio.exe").write_text("x")

    monkeypatch.delenv("KEVIL_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(temporal), raising=False)
    monkeypatch.setattr(sys, "executable", str(junto / "Kevil Studio.exe"))

    datos = rutas.carpeta_de_datos()
    assert datos == junto / "data"
    assert temporal not in datos.parents and datos != temporal


def test_si_no_se_puede_escribir_al_lado_se_usa_tu_carpeta(monkeypatch, tmp_path):
    """Como cuando lo dejas en Archivos de programa."""
    monkeypatch.delenv("KEVIL_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "x"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "solo-lectura" / "Kevil.exe"))
    monkeypatch.setattr(rutas, "_se_puede_escribir", lambda carpeta: False)

    casa = tmp_path / "casa"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: casa))
    # cada sistema guarda los datos de usuario en un sitio distinto
    monkeypatch.setenv("XDG_DATA_HOME", str(casa / "datos"))     # Linux
    monkeypatch.setenv("LOCALAPPDATA", str(casa / "AppData"))    # Windows

    datos = rutas.carpeta_de_datos()
    assert str(casa) in str(datos)
    assert "KevilStudio" in str(datos)


def test_la_variable_de_entorno_manda(monkeypatch, tmp_path):
    monkeypatch.setenv("KEVIL_DATA_DIR", str(tmp_path / "donde-yo-diga"))
    assert rutas.carpeta_de_datos() == tmp_path / "donde-yo-diga"


def test_se_usa_el_ffmpeg_incluido_si_viene_con_el_paquete(monkeypatch, tmp_path):
    """Un .exe puede traer su propio ffmpeg para no tener que instalar nada."""
    paquete = tmp_path / "paquete"
    (paquete / "bin").mkdir(parents=True)
    sufijo = ".exe" if sys.platform == "win32" else ""
    incluido = paquete / "bin" / f"ffmpeg{sufijo}"
    incluido.write_text("soy ffmpeg")

    monkeypatch.setattr(rutas, "raiz_recursos", lambda: paquete)
    monkeypatch.setattr(rutas, "carpeta_del_programa", lambda: tmp_path / "otro")
    assert rutas.ffmpeg_incluido("ffmpeg") == str(incluido)

    # si no viene, se devuelve vacío y se usa el del sistema
    assert rutas.ffmpeg_incluido("ffprobe") == ""


# --------------------------------------------------------------------------
# El flujo que construye el .exe
# --------------------------------------------------------------------------
def test_el_arranque_del_exe_no_monta_entornos_virtuales():
    """arranque.py es para el .exe: ahí ya va todo dentro."""
    codigo = (Path(__file__).resolve().parent.parent / "arranque.py").read_text(encoding="utf-8")
    assert "venv" not in codigo and "pip install" not in codigo
    # y sí tiene lo que hace falta en Windows para no abrir ventanas infinitas
    assert "freeze_support" in codigo


def test_el_constructor_incluye_lo_que_se_carga_por_su_nombre():
    import construir

    # uvicorn y apscheduler cargan estos módulos por cadena de texto: si no se
    # declaran, el .exe se construye pero peta al arrancar
    assert "uvicorn.protocols.http.auto" in construir.IMPORTS_OCULTOS
    assert "uvicorn.lifespan.on" in construir.IMPORTS_OCULTOS
    assert "sqlalchemy.dialects.sqlite" in construir.IMPORTS_OCULTOS
    assert any(m.startswith("apscheduler") for m in construir.IMPORTS_OCULTOS)


def test_el_flujo_de_github_construye_en_windows():
    # pyyaml no es una dependencia de Kevil: si no está, esta comprobación sobra
    yaml = pytest.importorskip("yaml")

    ruta = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "exe.yml"
    flujo = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    trabajo = flujo["jobs"]["windows"]

    # un .exe de Windows sólo se puede construir en Windows
    assert trabajo["runs-on"] == "windows-latest"
    nombres = [p.get("name", "") for p in trabajo["steps"]]
    assert any("Construir" in n for n in nombres)
    # y no se publica sin comprobar que arranca
    assert any("arranca" in n for n in nombres)


def test_no_se_empaqueta_un_ffmpeg_de_mentira(tmp_path, monkeypatch):
    """Chocolatey instala un lanzador de pocos KB que apunta al binario real.

    Metido en el .exe no sirve de nada: hay que quedarse con el de verdad o con
    ninguno, pero no con el atajo.
    """
    import construir

    falso = tmp_path / "atajo"
    falso.mkdir()
    sufijo = ".exe" if sys.platform == "win32" else ""
    lanzador = falso / f"ffmpeg{sufijo}"
    lanzador.write_bytes(b"0" * 60_000)                 # un atajo, 60 KB

    monkeypatch.delenv("KEVIL_FFMPEG_DIR", raising=False)
    monkeypatch.setattr(construir.shutil, "which", lambda n: str(lanzador))
    assert construir._buscar_binario("ffmpeg") == ""     # se descarta

    # el de verdad sí vale
    bueno = tmp_path / "bueno"
    bueno.mkdir()
    real = bueno / f"ffmpeg{sufijo}"
    real.write_bytes(b"0" * (construir.MINIMO_FFMPEG + 1))
    monkeypatch.setattr(construir.shutil, "which", lambda n: str(real))
    assert construir._buscar_binario("ffmpeg") == str(real)

    # y se puede decir dónde está a mano
    monkeypatch.setenv("KEVIL_FFMPEG_DIR", str(bueno))
    monkeypatch.setattr(construir.shutil, "which", lambda n: None)
    assert construir._buscar_binario("ffmpeg") == str(real)


def test_avisa_si_el_puerto_esta_ocupado():
    """El puerto va escrito en la dirección de retorno de Google y de TikTok:
    arrancar en otro rompería las conexiones sin decir por qué."""
    import socket

    import arranque

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        puerto = servidor.getsockname()[1]
        assert arranque._puerto_ocupado("127.0.0.1", puerto) is True

    # ya cerrado: libre otra vez
    assert arranque._puerto_ocupado("127.0.0.1", puerto) is False
