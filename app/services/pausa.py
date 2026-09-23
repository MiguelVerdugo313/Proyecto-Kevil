"""Pausar y reanudar el motor.

Para cuando quieres el ordenador para otra cosa —jugar, grabar, editar— y no
quieres que Kevil se lo coma bajando vídeos y montando clips.

Al pausar:

* no se empieza ningún trabajo pesado nuevo;
* lo que estuviera a medias **se corta en seco** —el ffmpeg que esté
  renderizando se para, la descarga se interrumpe— y vuelve a la cola, así que
  al reanudar se retoma sin perder nada;
* el estado se guarda: si cierras Kevil en pausa, se abre en pausa.

Lo que **sigue funcionando** en pausa son las publicaciones programadas y el
repaso de métricas: son ligeras y tienen hora. Si se pararan, al volver se te
habrían acumulado todas las de la tarde.
"""

from __future__ import annotations

import threading

from sqlalchemy.orm import Session

from app import procesos
from app.models import Setting

CLAVE = "motor_en_pausa"

# Los trabajos que tiran del procesador, del disco o de la conexión a lo bestia.
PESADOS = frozenset({
    "ingest",          # bajar el vídeo
    "process",         # transcribir y elegir los momentos
    "render",          # montar cada clip
    "analyze_local",   # analizar un vídeo subido
    "build_kit",       # títulos y miniaturas
    "upload_youtube",  # subir un vídeo largo entero
})

_en_pausa = threading.Event()


class Pausado(RuntimeError):
    """El trabajo se ha cortado porque el motor se ha puesto en pausa."""

    def __init__(self) -> None:
        super().__init__("En pausa: se retomará al reanudar")


def activa() -> bool:
    return _en_pausa.is_set()


def afecta(tipo: str) -> bool:
    """¿Este tipo de trabajo se detiene cuando el motor está en pausa?"""
    return tipo in PESADOS


def comprobar() -> None:
    """Para el trabajo en curso si el motor está en pausa.

    Se llama desde los puntos donde el trabajo informa de su avance: así hasta
    las fases que no lanzan ningún programa externo se paran enseguida.
    """
    if _en_pausa.is_set():
        raise Pausado()


def cargar(session: Session) -> bool:
    """Al arrancar se recupera el estado en que se dejó."""
    fila = session.get(Setting, CLAVE)
    if fila is not None and bool(fila.value):
        _en_pausa.set()
    else:
        _en_pausa.clear()
    return activa()


def _guardar(session: Session, valor: bool) -> None:
    fila = session.get(Setting, CLAVE)
    if fila is None:
        session.add(Setting(key=CLAVE, value=valor))
    else:
        fila.value = valor


def pausar(session: Session) -> int:
    """Pone el motor en pausa. Devuelve cuántos procesos ha tenido que cortar."""
    _en_pausa.set()
    _guardar(session, True)
    return procesos.terminar_todos()


def reanudar(session: Session) -> None:
    _en_pausa.clear()
    _guardar(session, False)
