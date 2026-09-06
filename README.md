# Kevil Studio

**Tu estudio de YouTube y TikTok, funcionando en tu propio ordenador.**

Kevil Studio se descarga y se abre **en su propia ventana**, como cualquier otro
programa. Hace tres cosas:

1. **Reaprovecha tu contenido en las dos direcciones**: corta tus vídeos y directos de
   YouTube en clips verticales y los publica en **TikTok y en YouTube Shorts**; y trae
   los **Shorts que ya tienes** para republicarlos en TikTok tal cual.
2. **Prepara tus subidas a YouTube**: subes el vídeo y te devuelve títulos, descripción
   con capítulos, etiquetas, hashtags y varias miniaturas, siguiendo las buenas prácticas
   de la plataforma. Con IA si le das una clave; si no, generado en local.
3. **Te hace de asistente**: te dice cada cuánto publicar para que el algoritmo no te
   olvide, te avisa cuando te retrasas y te propone sobre qué grabar el próximo vídeo,
   comprobando en YouTube si el tema tiene público de verdad.

No hay servidor en la nube ni suscripción, y tus vídeos no salen de tu equipo: las únicas
conexiones son con YouTube (descargar y consultar), TikTok (publicar) y, si la activas,
tu proveedor de IA.

**Y no te llena el disco.** De cada vídeo largo se bajan *sólo los segundos que van a
salir en un clip*, y en cuanto algo se publica su archivo se borra. Un directo de dos
horas deja unos pocos MB de paso, no varios GB para siempre.

---

## Qué hace, paso a paso

```
                       ┌──────────── Coach del canal ────────────┐
                       │  cadencia · avisos · ideas validadas    │
                       └────────────────────────────────────────┘
                                       ▲
Vídeos y directos ──► Descarga ──► Transcripción ──► Cortes ──► Vertical + rótulos
                                                                        │
                                                            ┌───────────┴───────────┐
                                                            ▼                       ▼
                                                         TikTok            YouTube Shorts
Tus Shorts de YouTube ────────────────────────────────────► TikTok (tal cual)

Vídeo que subes tú ──► Kit de publicación: títulos · descripción · etiquetas · miniaturas
```

### Camino 1 — de tus vídeos largos a TikTok y Shorts

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
7. **Programa** cada clip en la mejor franja de cada cuenta (ver más abajo).
8. **Publica** en TikTok, en YouTube Shorts o en ambos a la vez; lo deja en borradores,
   o espera tu visto bueno. Cada destino recibe su propio horario.

### Camino 2 — tus Shorts de YouTube a TikTok

En **Cuentas → ↻ Shorts a TikTok** pegas la URL de tu canal. Kevil mira la pestaña de
Shorts, se los baja y los publica en TikTok **tal cual** (ya son verticales: no se
recortan ni se les añade nada encima). Los Shorts nuevos que subas se republican solos.

La plantilla de flujo **🔁 Shorts a TikTok** ya viene preparada: estrategia «vídeo
entero» y los pasos de rótulos y gancho apagados, porque el Short ya viene montado.

### Camino 3 — preparar una subida a YouTube

En **Estudio** arrastras el vídeo y obtienes, en un par de minutos:

* **5 títulos** de 45-60 caracteres, con el número de caracteres a la vista.
* **Descripción** con el gancho en las dos primeras líneas (lo único que se ve antes
  del «...más»), el cuerpo y los **capítulos** listos para pegar.
* **12 etiquetas** y como mucho **3 hashtags** (más de tres y YouTube los ignora).
* **Tres miniaturas 1280×720** en estilos distintos, con el texto en grande.
* Una **revisión** que te dice qué falla antes de publicar: título largo, pocas
  etiquetas, capítulos que YouTube no va a activar…

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

En Windows es más cómodo hacer **doble clic en `run.bat`**; en macOS y Linux, `./run.sh`.

La primera vez crea un entorno virtual (`.venv`), instala las dependencias, comprueba
ffmpeg y abre **la ventana de Kevil**. Las siguientes veces arranca en unos segundos.

La ventana usa el motor web que ya trae tu sistema (WebView2 en Windows, WebKit en
macOS, GTK en Linux): no descarga ningún navegador ni pesa cientos de megas. Si en tu
equipo no se pudiera abrir, Kevil te lo dice y sigue funcionando en el navegador.

Opciones útiles:

```bash
python run.py --navegador       # abrirlo en el navegador en vez de en su ventana
python run.py --sin-ventana     # sólo el servidor, no abrir nada
python run.py --puerto 9000     # otro puerto
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

En **Ajustes → TikTok → Conectar**. La primera vez sale una guía de tres pasos con los
enlaces directos y un botón para copiar la URL de retorno; al final pegas de golpe la
*client key* y el *client secret* que te enseña TikTok y Kevil las separa solo. A partir
de ahí es **un botón**: «Conectar con TikTok» → entras en tu cuenta → vuelves conectado.
Los detalles largos están en [`docs/CONECTAR-TIKTOK.md`](docs/CONECTAR-TIKTOK.md).

Si prefieres probar antes, crea una **cuenta de prueba**: se hace en un clic y simula las
publicaciones. Todo lo demás (cortes, render, programación) funciona igual.

### 2 bis. (Opcional) Conecta YouTube para publicar Shorts

Sólo si quieres que Kevil **suba** los clips a tu canal. En **Ajustes → YouTube →
Conectar** tienes la misma guía de tres pasos; en el último pegas entero el archivo
`client_secret_….json` que descargas de Google y Kevil saca de ahí lo que necesita.
Después es **un botón**: «Conectar con Google» → eliges tu cuenta → vuelves conectado.
Más detalle en [`docs/CONECTAR-YOUTUBE.md`](docs/CONECTAR-YOUTUBE.md).

> Google y TikTok obligan a que **cada programa** se registre con ellos una vez; no es
> algo que Kevil pueda saltarse, le pasa a cualquier aplicación que publique en tu
> nombre. Son cinco minutos y no hay que repetirlo nunca más.

> **Importante**: Google da 10.000 unidades de cuota al día y cada subida cuesta 1.600,
> así que salen **unas 6 publicaciones diarias**. Kevil lleva la cuenta y te la muestra
> en Ajustes. Es un límite de Google, igual para cualquier programa que use su API.

### 3. Ajusta el flujo y deja que trabaje

En **Flujos** tienes seis plantillas listas: cortes virales, directos largos, podcast,
tutoriales/gameplay, **🔁 Shorts a TikTok** y **🚀 Clips a TikTok y Shorts**. Duplica la
que más se acerque, toca lo que quieras y márcala como predeterminada.

Los clips terminados aparecen en **Clips**. Ahí los ves, ajustas el corte,
el encuadre y el texto, y los apruebas. En **Agenda** ves cuándo sale cada uno.

### 4. (Opcional) Activa la IA y cuéntale de qué va tu canal

En **Ajustes → Inteligencia artificial → Editar** pegas tu clave de OpenRouter, la de
NVIDIA o **las dos** (si a una se le acaban los créditos, Kevil sigue con la otra sin
avisarte de nada raro); el botón «Probar las claves» te dice cuál responde. Arriba, en
**Tu canal**, escribe de qué va tu canal y cuántos vídeos por semana quieres publicar:
con eso el asistente afina las ideas y sabe cuándo avisarte.

Y en **Ajustes → Colores** puedes ponerle a la aplicación los colores de tu canal de
YouTube, sacados de su propio avatar.

### 5. Sube un vídeo y publica mejor

En **Estudio** arrastras el vídeo y sales con el título, la descripción y las miniaturas.
En **Coach** ves si vas al día, cuál es tu mejor franja y qué grabar después.

---

## Los flujos: todo es editable

Un flujo son **10 pasos en orden**. Cada uno se despliega y tiene sus opciones;
los que no son imprescindibles se pueden desactivar con su interruptor.

De cada paso se enseña **sólo lo esencial**: 19 campos en total en lugar de 71. Con eso
funciona. Si algo no te gusta, el interruptor **«Todas las opciones»**, arriba a la
derecha del flujo, saca el resto —los 71— y cada paso te dice cuántos extras esconde.
Tu elección se recuerda, así que si eres de tocarlo todo lo tienes siempre abierto.

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
| 10 | Publicación | **destinos (TikTok y/o YouTube Shorts)**, automático / revisar / borrador / solo exportar, privacidad de cada plataforma, comentarios, dúos, stitch |

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

## Las miniaturas: cómo se hacen

Sin IA, y aun así decentes:

1. Se analizan ~30 fotogramas repartidos por todo el vídeo y se puntúa cada uno por
   **contraste**, **nitidez** y **colorido**, descartando los oscuros o planos.
2. Se eligen los mejores, separados en el tiempo para que no se parezcan.
3. Sobre cada uno se compone el texto (2-4 palabras, mayúsculas, muy legible) en tres
   diseños: degradado inferior, bloque lateral y banda superior.

Si configuras un modelo de imagen, se añade además una cuarta variante con el fondo
generado por IA a partir del contenido del vídeo. El texto de la miniatura también lo
propone la IA (tres opciones), porque acertar con esas 3 palabras es la mitad del trabajo.

---

## La IA es opcional (y de quien tú elijas)

| | Con clave de IA | Sin clave |
|---|---|---|
| Títulos | 5 propuestas redactadas | a partir del título y la transcripción |
| Descripción | gancho + cuerpo + CTA | plantilla con las palabras clave |
| Capítulos | por temas reales del vídeo | por bloques de tiempo |
| Etiquetas | 12, de concreto a general | las palabras más frecuentes |
| Miniaturas | textos propuestos + fondo generado | tus mejores fotogramas |
| Ideas | temas concretos según tu canal | variantes de lo que ya te funciona |

Proveedores admitidos, los dos con API compatible con OpenAI:

* **OpenRouter** ([openrouter.ai/keys](https://openrouter.ai/keys)) — una clave, cientos
  de modelos, incluidos los de imagen. Hay modelos gratuitos.
* **NVIDIA NIM** ([build.nvidia.com](https://build.nvidia.com)) — créditos gratuitos,
  texto e imagen.

**Puedes poner las dos claves a la vez.** Kevil intenta primero la que marques como
principal y, si esa falla —se acabaron los créditos, te limita por peticiones, la clave
ha caducado o el servicio no responde—, repite la misma petición con la otra sin que
tengas que hacer nada. Si fallan las dos, se genera todo en local y el aviso te dice qué
ha pasado con cada una. En **Ajustes → Estado** ves cuál se está usando y cuántas veces
ha habido que cambiar.

Se configura en **Ajustes → Inteligencia artificial → Editar**, con un botón para probar
las dos claves antes de guardar. Las claves se quedan en tu disco y nunca se muestran de
vuelta.

---

## El coach: cada cuánto publicar

Todo sale de **tus** vídeos, no de reglas genéricas:

* **Tu ritmo real**: la mediana de días entre subidas.
* **Tu regularidad**: cuánto varían esos huecos. Publicar cada 7 días exactos rinde más
  que dos vídeos una semana y ninguno las tres siguientes; el coach te lo dice cuando
  tu constancia baja.
* **Tus mejores franjas**: el día y la hora que mejor te han funcionado, ponderando por
  visitas y descartando los vídeos de menos de una semana (todavía están subiendo).
  Hasta tener 6 vídeos con datos, se usan franjas de referencia.
* **Avisos**: cuando te pasas de tu objetivo aparece un aviso en la campana y, si lo
  dejas activado, una notificación del escritorio (macOS, Windows y Linux, sin instalar nada).

### Ideas de contenido

La IA propone temas concretos («minecraft granja automática», no «vídeos de gaming»)
partiendo de tus títulos recientes y de los que mejor te han ido. Después **cada idea se
busca en YouTube** y se mide:

* **Demanda** — las visitas típicas de lo que ya existe sobre ese tema.
* **Competencia** — cuántos canales grandes lo están cubriendo.
* **Encaje** — cuánto se parece a lo que tú ya haces.

La nota final combina las tres, y puedes ver los vídeos concretos en los que se basa.
Las ideas se guardan o se descartan, así no te repite siempre lo mismo.

---

## El aspecto

Interfaz en **modo oscuro** (negro puro con capas de cristal esmerilado y una textura
de grano finísima) o **claro** (grises suaves), con el botón ◐ de la barra superior para
cambiar; tu elección se recuerda. Tipografía Inter, esquinas muy redondeadas y
animaciones de entrada suaves. Si te quedas sin conexión, Inter cae en la tipografía del
sistema y todo sigue viéndose bien.

### Con los colores de tu canal

En **Ajustes → Colores → Cambiar** puedes pulsar el nombre de tu canal y Kevil se viste
con **sus** colores: descarga el avatar, saca la paleta y se queda con el color más
característico (descartando grises y fondos). Si prefieres elegirlo tú, hay un selector
manual con vista previa en directo.

El color no se aplica tal cual: se ajusta para cada modo hasta que **contrasta al menos
4.5:1** con el fondo (la referencia de la WCAG para texto legible), así que un rojo casi
negro se aclara en oscuro y se oscurece en claro, y el texto que va encima del acento se
elige blanco o negro según contraste mejor. Un logo feo nunca deja la aplicación
ilegible. «Color por defecto» vuelve al esmeralda de casa.

### Ajustes: lo esencial a la vista

La pantalla de Ajustes son **dos tarjetas**: *Tu canal* (tres campos) y *Conexiones*,
con una línea por cada cosa —IA, YouTube, TikTok, colores y motor— que te dice en qué
estado está en una frase. Todo lo demás vive detrás del botón **Editar** de cada línea,
en una ventana que sólo abres si quieres cambiar algo.

---

## Dónde queda todo (y por qué ocupa tan poco)

```
data/
├── kevil.db              base de datos SQLite (cuentas, flujos, clips, agenda)
├── branding/             ← TUS COSAS: logos, fondos, fotos, tipografías
├── media/
│   ├── originales/       normalmente vacía (ver abajo)
│   ├── clips/            clips a la espera de publicarse
│   └── miniaturas/
├── temp/                 archivos de un solo uso
└── logs/
```

Puedes cambiar la carpeta con la variable de entorno `KEVIL_DATA_DIR`.
Para llevártelo a otro equipo, copia esa carpeta entera.

### No dejar rastro

Kevil no está pensado para dejarte el ordenador lleno de vídeos:

1. **No baja el vídeo entero.** Primero lee los subtítulos (unos kilobytes), decide con
   ellos dónde están los mejores momentos, y sólo entonces baja **esos segundos**. Para
   sacar tres clips de treinta segundos de un directo de dos horas se bajan noventa
   segundos, no dos horas.
2. **Borra al publicar.** En cuanto un clip sale en TikTok y en Shorts, su `.mp4` se va.
   Si le queda algún destino pendiente, espera a que salgan todos.
3. **Tiene un tope.** Si la carpeta de medios se pasa de lo que le digas (3 GB por
   defecto), se borra lo más antiguo que ya esté publicado.

Todo esto se ve y se cambia en **Ajustes → Espacio en disco**, donde también tienes
«Limpiar lo publicado» y «Borrarlo todo ahora». Si prefieres guardarlo todo, hay un
interruptor para cada cosa.

> Para las estrategias que eligen los cortes escuchando los silencios se baja la pista
> de **audio** (unos 100 MB en un directo de dos horas, frente a varios GB de vídeo) y
> se borra en cuanto se han elegido los momentos.

### Tu carpeta de marca

En `data/branding` puedes dejar tus cosas **sin ordenarlas ni renombrarlas**: tu logo,
capturas del juego, fondos, una foto tuya, tipografías, y un `.txt` contando de qué va
tu canal. Kevil deduce qué es cada archivo por lo que es:

| Lo que metes | Cómo lo entiende |
|---|---|
| PNG con transparencia, más o menos cuadrado | logo |
| imagen apaisada | fondo de miniatura |
| imagen vertical | fondo de Short |
| `.ttf` / `.otf` | tipografía |
| `.txt` / `.md` | notas de marca (contexto para la IA) |

Si además creas subcarpetas con nombre (`zombis/`, `logos/`, `fondos/`), mandas tú.
Cuando pidas una miniatura para un directo de zombis, ganará lo que tengas en `zombis/`.

### Una sola miniatura, para un directo

En **Estudio → 🎥 Miniatura de directo**. Para un directo que aún no has hecho no hay
fotogramas de los que tirar, así que el fondo sale, por este orden: de **tu carpeta de
marca** (eligiendo lo que mejor pegue con el tema), de la **IA** si tienes clave, o de un
fondo montado con **tu color**. Escribes «ZOMBIS A LAS 7», dices que va de zombis, y
sale una. Una, no tres.

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
| `KEVIL_OPENROUTER_API_KEY` / `KEVIL_NVIDIA_API_KEY` | claves de IA; puedes poner las dos |
| `KEVIL_AI_PRIMARY` | cuál se intenta primero (`openrouter` o `nvidia`); la otra queda de reserva |
| `KEVIL_OPENROUTER_TEXT_MODEL` / `..._IMAGE_MODEL` | modelos de OpenRouter |
| `KEVIL_NVIDIA_TEXT_MODEL` / `..._IMAGE_MODEL` | modelos de NVIDIA |
| `KEVIL_YOUTUBE_CLIENT_ID` / `..._SECRET` | sólo para publicar Shorts desde Kevil |
| `KEVIL_BRAND_ACCENT` / `KEVIL_BRAND_ACCENT_2` | colores de tu marca para la interfaz |
| `KEVIL_CHANNEL_TOPIC` | de qué va tu canal (contexto para la IA) |
| `KEVIL_TARGET_UPLOADS_PER_WEEK` | tu objetivo de vídeos por semana |
| `KEVIL_FFMPEG_PATH` / `KEVIL_FFPROBE_PATH` | rutas si ffmpeg no está en el PATH |

> Si vienes de una versión anterior con `KEVIL_AI_PROVIDER` / `KEVIL_AI_API_KEY`
> guardados desde Ajustes, Kevil los pasa solo al formato nuevo la primera vez que
> arranca; no tienes que volver a escribir nada.

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

**¿Tengo que pagar por la IA?** No es obligatoria: sin clave todo se genera en local.
Si la quieres, tanto OpenRouter como NVIDIA tienen opciones gratuitas para empezar.

**¿Y si se me acaban los créditos a mitad?** Pon las dos claves. Kevil detecta que una
se ha quedado sin créditos (o que te está limitando por peticiones) y repite la misma
petición con la otra. Si las dos fallan, no se para nada: se genera en local y el aviso
te dice qué pasó con cada una.

**¿Puedo simplificar la pantalla de flujos?** Ya viene simplificada: se enseñan sólo los
19 campos que de verdad usas y el resto está detrás de «Todas las opciones».

**¿Sube el vídeo a YouTube por mí?** Los **Shorts sí**, si conectas tu canal
(ver arriba); recuerda el límite de ~6 subidas al día que impone Google. Los **vídeos
largos no**: para esos Kevil te prepara el kit (título, descripción, etiquetas y
miniatura) y los subes tú, que además así eliges la miniatura con calma.

**¿De dónde saca las mejores horas de YouTube?** De tus propios vídeos: cruza la hora de
publicación con las visitas que consiguieron. Hasta tener seis vídeos con datos usa unas
franjas de referencia y te lo indica.

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
│   ├── timing.py      motor de horarios (por cuenta y plataforma)
│   ├── youtube_api.py publicación de Shorts (API oficial, subida reanudable)
│   ├── ai.py          conector de IA (OpenRouter y NVIDIA, con relevo automático)
│   ├── branding.py    colores del canal y ajuste de contraste
│   ├── seo.py         kit de publicación de YouTube
│   ├── thumbnails.py  análisis de fotogramas y montaje de miniaturas
│   ├── coach.py       cadencia y mejores franjas del canal
│   ├── ideas.py       propuestas de contenido validadas con datos
│   ├── notifications.py  avisos en la app y en el escritorio
│   ├── tiktok.py      API de publicación
│   ├── pipeline.py    orquestación de todo el proceso
│   ├── queue.py       cola de trabajos en segundo plano
│   ├── scheduler.py   vigilancia, publicación a su hora y repaso del canal
│   └── studio.py      trabajos del estudio (kit, miniaturas, ideas)
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
