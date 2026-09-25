"""La versión del programa, en un sitio y sólo en uno.

Además de salir en la interfaz, se usa para colgarla de las direcciones de los
archivos de estilo y de código (`style.css?v=…`). Sin eso, la ventana —que es
un Chromium con su propio perfil— se queda con la versión vieja en la caché y
uno actualiza el programa sin ver ningún cambio.
"""

from __future__ import annotations

VERSION = "1.8.1"
