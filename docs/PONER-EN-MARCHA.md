# Dejar Kevil Studio conectado, paso a paso

Todo lo que hay que hacer una vez para que el programa quede publicando solo.
Está pensado para seguirlo con una pestaña abierta en el portal que toque.

---

## Antes de empezar: qué puede hacer cada uno

**Lo que sólo puedes hacer tú**, en tu ordenador:

- Entrar en tu cuenta de Google y en la de TikTok.
- El botón final de «Conectar»: la autorización vuelve a `127.0.0.1`, que es
  **tu propio ordenador**. Ni yo aquí ni Claude en el navegador podemos
  recibir esa vuelta, así que ese clic es tuyo por narices.

**Lo que sí te puede hacer Claude en el navegador:**

- Llevarte de la mano por cada pantalla de los portales y decirte qué campo es
  cuál a partir de tus capturas.
- Escribirte los textos que piden (descripción de la app, para qué usas cada
  permiso, la política de privacidad si te la exigen).
- Leer el error que te salga y decirte qué falta.

**Lo que no hay que mandar por ningún chat**: el *Client secret* de TikTok, el
`client_secret_….json` de Google y los tokens. No hacen falta para que te
ayuden: van directos del portal a Kevil, sin pasar por ninguna conversación.
Si alguno se te escapa en un chat, bórralo y genera otro en el portal.

---

## 0. Instalar (5 minutos)

1. Descarga
   [`Kevil-Studio-Windows.zip`](https://github.com/MiguelVerdugo313/Proyecto-Kevil/releases/latest).
2. Descomprímelo **encima de la carpeta que ya tengas**, para no perder tus
   datos. Si es la primera vez, ponlo en una carpeta suya (no en Descargas).
3. Doble clic en `Kevil Studio.exe`. Se abre la aplicación en negro y oro.

> Tus datos viven en la carpeta `data`, al lado del ejecutable. Esa carpeta es
> la que hay que conservar al actualizar y la que hay que copiar si cambias de
> ordenador.

---

## 1. Tu canal de YouTube (2 minutos, sin claves)

Es lo único imprescindible: de aquí saca los vídeos.

1. **Cuentas → Conectar canal**.
2. Pega la URL de tu canal (`https://www.youtube.com/@tucanal`).
3. Elige el flujo y guarda.

No hace falta ninguna API para esto. Vigilar el canal y bajar los vídeos
funciona sin registrar nada.

---

## 2. TikTok (15 minutos, una vez)

### 2.1 Crea la app

1. Entra en <https://developers.tiktok.com/apps> con tu cuenta de TikTok.
2. **Connect an app**. Nombre: `Kevil Studio` (o el que quieras).
3. Rellena descripción y categoría.

### 2.2 Plataforma

4. En **Platforms**, marca **Desktop**. Deja **Web** sin marcar.
   Como «Web», TikTok exige que la dirección de retorno empiece por `https` y
   no acepta la de tu ordenador: ahí es donde se atasca todo el mundo.
5. Aparece **Configure for Web/Desktop → Web/Desktop URL**. Ese campo es **la
   web de tu aplicación**, no la de retorno, y tiene que empezar por `https`:

   ```
   https://github.com/MiguelVerdugo313/Proyecto-Kevil
   ```

### 2.3 Productos y permisos

6. En **Products**, añade **Login Kit** y **Content Posting API**.
7. En **Scopes**, marca:

   | Permiso | Para qué |
   |---|---|
   | `user.info.basic` | nombre y avatar de la cuenta |
   | `video.publish` | publicar |
   | `video.upload` | dejarlo en tu bandeja |
   | `video.list` | leer las métricas de lo publicado |

   Opcionales, mejoran el motor de horarios: `user.info.profile`,
   `user.info.stats`.

### 2.4 La dirección de retorno

8. Dentro de **Login Kit** hay un campo **Redirect URI** —otro distinto del
   del paso 5—. Ahí va tal cual:

   ```
   http://127.0.0.1:8756/api/oauth/tiktok/callback
   ```

   Kevil te la da con un botón de copiar en **Ajustes → TikTok**, por si
   algún día cambias el puerto.

### 2.5 Sandbox, para poder probar ya

9. TikTok revisa las apps antes de dejarlas publicar de verdad. Mientras
   tanto, en la pestaña **Sandbox**, añade tu propia cuenta de TikTok como
   usuario de pruebas. Así puedes conectarte y subir sin esperar.

### 2.6 Las claves, en Kevil

10. En la ficha de tu app, arriba: **Client key** (empieza por `aw`) y
    **Client secret**.
11. En Kevil: **Ajustes → TikTok → Conectar**. Cada una en su casilla.
12. **Guardar y conectar** → se abre TikTok → **Autorizar** → vuelves solo.

> Hasta que TikTok revise tu app, el clip se queda en la **bandeja** de la
> aplicación de TikTok en vez de publicarse directamente. Kevil lo detecta,
> lo hace así solo y te lo anota en los avisos: sólo tienes que darle a
> publicar en el móvil.

---

## 3. Google, para publicar Shorts (10 minutos, opcional)

Sólo hace falta si quieres que Kevil **suba** los clips a tu canal de YouTube.
Pasar tus Shorts a TikTok y todo lo demás funciona sin esto.

1. Crea un proyecto en
   [Google Cloud](https://console.cloud.google.com/projectcreate).
2. Habilita la
   [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com)
   → **Habilitar**.
3. **Pantalla de consentimiento de OAuth**: tipo **Externo**, pon un nombre y
   tu correo. En **Usuarios de prueba**, **añádete a ti mismo**: sin eso
   Google no deja entrar mientras la app esté en modo de prueba.
4. [Credenciales](https://console.cloud.google.com/apis/credentials) →
   **Crear credenciales → ID de cliente de OAuth** → tipo **Aplicación de
   escritorio**. Con ese tipo **no hay que registrar ninguna dirección**.
5. Descarga el `client_secret_….json` que te ofrece. **No hace falta abrirlo.**
6. En Kevil: **Ajustes → YouTube → Conectar → «Buscar el archivo»**. Lo
   encuentra él solo en Descargas.
7. **Conectar con Google** → elige tu cuenta → Google avisa de «aplicación no
   verificada» (es normal: sale en cualquier programa sin revisar, y el tuyo
   sólo lo usas tú) → **Configuración avanzada → Ir a Kevil Studio** →
   aceptar los permisos.

> Google da 10.000 unidades de cuota al día y cada subida cuesta 1.600: salen
> **unas 6 publicaciones diarias**. Es límite suyo, no de Kevil, y lo verás
> contado en Ajustes.

---

## 4. Lo que queda, todo dentro de la aplicación

Nada de esto necesita portales ni claves de nadie.

| Qué | Dónde | Para qué |
|---|---|---|
| **Tema del canal** | Ajustes → Canal | que los títulos y hashtags vayan de lo tuyo |
| **Colores** | Ajustes → Colores | vestir la aplicación con los de tu canal |
| **Carpeta de marca** | `data/branding` | tus logos y fondos, para miniaturas y rótulos |
| **IA (opcional)** | Ajustes → IA | títulos y ganchos mejores; con OpenRouter o NVIDIA NIM |
| **Espacio en disco** | Ajustes → Disco | cuánto puede ocupar antes de limpiar solo |
| **Flujo** | Flujos | cómo se corta, se monta y se publica cada vídeo |

Para gameplay, usa la plantilla **«Tutoriales y gameplay»** (pantalla partida):
el recorte a pantalla completa te comería el HUD.

---

## 5. El interruptor final

**Panel → Piloto automático**. Se enciende sólo si ya hay un canal vigilado y
al menos una cuenta donde publicar; si falta algo, te dice cuál y te lleva.

A partir de ahí Kevil corta, monta, programa y publica sin preguntarte.

---

## Comprobación: ¿está todo?

- [ ] La aplicación abre en negro y oro, y pone `v1.1.0` abajo a la izquierda.
- [ ] **Cuentas** enseña tu canal de YouTube.
- [ ] **Cuentas** enseña tu TikTok con el nombre y el avatar de verdad.
- [ ] (Si quieres Shorts) **Ajustes → YouTube** dice que está conectado.
- [ ] **Panel → Piloto automático** se puede encender, sin avisos rojos.
- [ ] Subes un vídeo en **Estudio** y en un par de minutos hay un clip en
      **Clips**, vertical y con rótulos.

---

## Si algo falla

La pantalla de error nueva dice el motivo en cristiano y trae debajo, plegado,
el código original de TikTok o de Google. Hazle una foto: con eso se sabe
exactamente qué falta.

Los más habituales:

| Lo que ves | Lo que pasa |
|---|---|
| «Enter a valid URL beginning with https://» | Has puesto la dirección de retorno en **Web/Desktop URL**. Va en **Redirect URI**, dentro de Login Kit. |
| `invalid_client` | La *client key* o el *secret* están mal copiados. |
| `invalid_scope` | Faltan permisos en **Scopes**. |
| `invalid_request` | La **Redirect URI** no coincide exactamente con la que da Kevil. |
| «El puerto 8756 está ocupado» | Ya tienes Kevil abierto: míralo en la barra de tareas. |
| Google: «aplicación no verificada» | Normal. **Configuración avanzada → Ir a Kevil Studio**. |
| Google: «acceso bloqueado» | Te falta añadirte como **usuario de prueba** en la pantalla de consentimiento. |
