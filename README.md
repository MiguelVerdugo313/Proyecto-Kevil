# Kevil Studio

**De tus vídeos y directos de YouTube a TikTok, en automático y en tu propio ordenador.**

Kevil Studio se descarga, se ejecuta en local y abre una interfaz en el navegador.
Vigila tus canales de YouTube, corta los vídeos largos y los directos en trozos con
gancho, los convierte a vertical (9:16) con rótulos, y los reparte en tu cuenta de
TikTok a las horas que mejor funcionan para esa cuenta. Todos los pasos son editables.

No hay servidor en la nube, ni suscripción, ni tus vídeos salen de tu equipo:
la única conexión a internet es con YouTube (para descargar) y con TikTok (para publicar).

---

## Qué hace, paso a paso

```
Canal de YouTube ──► Descarga ──► Transcripción ──► Selección de momentos
                                                            │
                                                            ▼
   Publicación en TikTok ◄── Programación ◄── Vertical + rótulos + gancho
```

1. **Vigila** tus canales: subidas normales y directos ya emitidos. Los vídeos nuevos
   entran solos en el proceso.
2. **Descarga** el original a tu disco (con `yt-dlp`, sin claves de API).
3. **Transcribe** con los subtítulos de YouTube (palabra a palabra) o con Whisper local.
4. **Elige los momentos**: puntúa cada tramo por ritmo del habla, palabras gancho,
   preguntas, datos concretos y pausas del audio. También puedes cortar por trozos
   iguales, por silencios o a mano.
5. **Monta el vertical**: recorte inteligente que sigue la acción, fondo desenfocado,
   split o recorte fijo; rótulos estilo karaoke; gancho arriba; marca de agua;
   barra de progreso; audio nivelado a −14 LUFS.
6. **Escribe** título, descripción y hashtags con tus plantillas.
7. **Programa** cada clip en la mejor franja de esa cuenta (ver más abajo).
8. **Publica** solo, lo deja en tus borradores de TikTok, o espera tu visto bueno.

---

## Instalación

Necesitas dos cosas: **Python 3.10 o superior** y **ffmpeg**.

| Sistema | Instalar ffmpeg |
|---|---|
| Windows | `winget install Gyan.FFmpeg` |
| macOS | `brew install ffmpeg` |
| Linux (Debian/Ubuntu) | `sudo apt install ffmpeg` |

Después, desde la carpeta del proyecto:

```bash
python run.py
```

La primera vez crea un entorno virtual (`.venv`), instala las dependencias, comprueba
ffmpeg, levanta el servidor y abre el navegador en <http://127.0.0.1:8756>.
Las siguientes veces arranca en unos segundos.

En Windows también puedes hacer doble clic en `run.bat`; en macOS y Linux, `./run.sh`.

Opciones útiles:

```bash
python run.py --puerto 9000     # otro puerto
python run.py --sin-navegador   # no abrir el navegador
python run.py --reinstalar      # rehacer el entorno virtual
```

---

## Primeros pasos en la aplicación

### 1. Conecta tu canal de YouTube

En **Cuentas → Conectar canal**, pega la URL o el `@usuario`. No hace falta clave de API.
Ahí eliges:

* qué flujo se le aplica,
* a qué cuenta de TikTok van sus clips,
* cuántos vídeos antiguos traer (0 = solo los nuevos),
* si se incluyen los directos ya emitidos,
* si el canal se vigila automáticamente.

> Para vídeos privados o no listados, en el paso «Descarga del original» del flujo puedes
> indicar que se reutilicen las cookies de tu navegador.

### 2. Conecta TikTok

Dos opciones:

* **Cuenta real**: crea una app en [developers.tiktok.com](https://developers.tiktok.com),
  copia la clave y el secreto en **Ajustes** y autoriza la cuenta.
  Los detalles están en [`docs/CONECTAR-TIKTOK.md`](docs/CONECTAR-TIKTOK.md).
* **Cuenta de prueba**: se crea en un clic y simula las publicaciones. Todo el proceso
  funciona igual (cortes, render, programación) pero no sube nada. Ideal para probar.

### 3. Ajusta el flujo y deja que trabaje

En **Flujos** tienes cuatro plantillas listas (cortes virales, directos largos,
podcast, tutoriales/gameplay). Duplica la que más se acerque, toca lo que quieras
y márcala como predeterminada.

Los clips terminados aparecen en **Clips**. Ahí los ves, ajustas el corte,
el encuadre y el texto, y los apruebas. En **Agenda** ves cuándo sale cada uno.

---

## Los flujos: todo es editable

Un flujo son **10 pasos en orden**. Cada uno se despliega y tiene sus opciones;
los que no son imprescindibles se pueden desactivar con su interruptor.

| # | Paso | Qué controlas |
|---|---|---|
| 1 | Descarga del original | calidad, subtítulos, idiomas, cookies del navegador |
| 2 | Transcripción | subtítulos de YouTube, Whisper local, idioma |
| 3 | Selección de momentos | estrategia, duraciones, nº de clips, saltar intro/outro, palabras que suman y que restan |
| 4 | Formato vertical | encuadre (desenfocado / recorte / seguimiento / split), zoom, centro, resolución, fps |
| 5 | Rótulos automáticos | estilo (karaoke, bloques, palabra), tipografía, tamaño, colores, altura, mayúsculas |
| 6 | Gancho y marca | texto del gancho y duración, marca de agua, barra de progreso |
| 7 | Audio | normalización, volumen objetivo, entradas y salidas suaves |
| 8 | Título y descripción | plantillas con variables, hashtags fijos y automáticos |
| 9 | Programación | publicaciones por día, separación mínima, días de reparto, orden |
| 10 | Publicación en TikTok | automático / revisar / borrador / solo exportar, privacidad, comentarios, dúos, stitch |

Variables disponibles en las plantillas de texto:
`{titulo}` `{hook}` `{n}` `{total}` `{canal}` `{hashtags}`.

Los flujos se guardan por canal, así que puedes tener uno para tus directos y otro
para los vídeos de siempre.

---

## Cuándo se publica cada clip

El motor de horarios combina tres señales, y las tres se pueden editar
(**Cuentas → Estrategia**):

1. **Tu historial**: a qué horas han funcionado mejor tus propias publicaciones.
   Se aprende automáticamente en cuanto hay suficientes datos (6 publicaciones con
   métricas por defecto); las vistas se normalizan con la mediana para que un vídeo
   viral no distorsione el mapa.
2. **Patrón base**: un mapa de 7 días × 24 horas con las franjas de más actividad.
   Es un punto de partida editable: pulsa cualquier casilla para subirla, clic derecho
   para bajarla.
3. **Estado de la cuenta**: seguidores, cadencia reciente y tendencia. Una cuenta nueva
   empieza con menos publicaciones al día y va subiendo (modo «calentamiento»).

Además se respetan: máximo por día, horas mínimas entre publicaciones, días permitidos,
franja de silencio nocturno y una variación aleatoria de minutos para no publicar
siempre a la misma hora clavada. Cada publicación programada te dice **por qué**
se ha elegido ese hueco.

---

## Dónde queda todo

```
data/
├── kevil.db              base de datos SQLite (cuentas, flujos, clips, agenda)
├── media/
│   ├── originales/       vídeos descargados de YouTube
│   ├── clips/            clips verticales listos (.mp4)
│   └── miniaturas/
├── temp/                 archivos de trabajo
└── logs/
```

Puedes cambiar la carpeta con la variable de entorno `KEVIL_DATA_DIR`.
Para llevártelo a otro equipo, copia esa carpeta entera.

---

## Configuración avanzada

Copia `.env.example` a `.env` para fijar valores por defecto:

| Variable | Para qué sirve |
|---|---|
| `KEVIL_PORT` | puerto del servidor (8756) |
| `KEVIL_DATA_DIR` | carpeta de datos |
| `KEVIL_WORKERS` | tareas pesadas en paralelo (2) |
| `KEVIL_WATCH_INTERVAL_MINUTES` | cada cuánto se revisan los canales (15) |
| `KEVIL_TIKTOK_CLIENT_KEY` / `..._SECRET` | credenciales de tu app de TikTok |
| `KEVIL_DRY_RUN` | `true` para no publicar de verdad |
| `KEVIL_FFMPEG_PATH` / `KEVIL_FFPROBE_PATH` | rutas si ffmpeg no está en el PATH |

Casi todo esto también se cambia desde **Ajustes**, sin tocar archivos.

**Transcripción con Whisper** (opcional, más preciso que los subtítulos de YouTube):

```bash
.venv/bin/pip install faster-whisper       # Windows: .venv\Scripts\pip install faster-whisper
```

y en el flujo, paso «Transcripción», elige *Whisper local*.

---

## Preguntas rápidas

**¿Funciona con directos?** Sí, con los que ya han terminado. En «Selección de momentos»
puedes saltarte los primeros minutos (la típica espera inicial) y sacar más clips por hora.
Los directos en curso se ignoran hasta que acaban.

**¿Y con los vídeos que suba mañana?** Sí: el canal se revisa cada 15 minutos (editable)
y los vídeos nuevos entran solos en el flujo.

**¿Puedo revisar antes de publicar?** Sí, es el modo por defecto («Revisar antes de
publicar»). También puedes dejar que publique solo o que envíe los clips a tus borradores
de TikTok.

**¿Se puede usar varias cuentas de TikTok?** Sí. Cada canal de YouTube apunta a la cuenta
que elijas, y cada cuenta tiene su propia estrategia de horarios.

**¿Cuánto tarda?** La descarga depende de tu conexión; el render, de tu procesador.
Como referencia, un clip de 30 segundos en 1080×1920 tarda entre 10 y 40 segundos.
Sube `Tareas en paralelo` en Ajustes si tu equipo lo aguanta.

**¿Necesito la API de YouTube?** No. Se usa `yt-dlp`, que sólo necesita la URL del canal.

---

## Desarrollo

```bash
python run.py --recargar          # recarga automática al cambiar el código
.venv/bin/python -m pytest tests -q
```

Estructura:

```
app/
├── main.py            servidor FastAPI y montaje de la interfaz
├── config.py          configuración y rutas
├── models.py          modelo de datos
├── flow_schema.py     definición de los pasos editables (la interfaz se genera de aquí)
├── api/               endpoints REST
├── services/
│   ├── youtube.py     listado y descarga (yt-dlp)
│   ├── transcript.py  subtítulos json3/vtt y Whisper
│   ├── segmenter.py   elección de los mejores momentos
│   ├── captions.py    generación del ASS (rótulos, gancho, barra)
│   ├── renderer.py    grafo de filtros de ffmpeg
│   ├── timing.py      motor de horarios
│   ├── tiktok.py      API de publicación
│   ├── pipeline.py    orquestación de todo el proceso
│   ├── queue.py       cola de trabajos en segundo plano
│   └── scheduler.py   vigilancia y publicación a su hora
└── web/               interfaz (HTML, CSS y JavaScript sin compilar)
```

Para añadir una opción nueva a un flujo basta con declararla en `app/flow_schema.py`:
el formulario de la interfaz se construye solo a partir de ese esquema, y los flujos
ya guardados se completan con el valor por defecto.

---

## Aviso

Publica sólo contenido del que tengas derechos. Kevil Studio usa la API oficial de
TikTok para publicar; respeta sus condiciones de uso y los límites de publicación de
tu cuenta.
