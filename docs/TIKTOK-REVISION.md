# Los seis requisitos de TikTok, resueltos

Cuando le das a **Save** en la pestaña *Production*, TikTok valida el formulario
entero y pide seis cosas. Ninguna hace falta para **Sandbox**, que es donde vas
a trabajar desde el primer día; esto es para cuando quieras publicar en público.

| Requisito | Estado |
|---|---|
| 1. Icono 1024×1024 | ✅ [`icono-1024.png`](icono-1024.png) |
| 2. Terms of Service URL | ✅ `https://miguelverdugo313.github.io/Proyecto-Kevil/terminos.html` |
| 3. Privacy Policy URL | ✅ `https://miguelverdugo313.github.io/Proyecto-Kevil/privacidad.html` |
| 4. URL verificada | ⚙️ hay que subir el archivo que te dé TikTok (abajo) |
| 5. Texto de productos y permisos | ✅ listo para pegar (abajo) |
| 6. Vídeo demo | 🎬 lo grabas tú en Sandbox (guion abajo) |

Las URLs salen de la web del proyecto, que vive en este mismo repositorio.
Para que estén en línea hay que encenderla una vez:

> **GitHub → Settings → Pages → Build and deployment → Source: «Deploy from a
> branch» → Branch: `main`, carpeta `/docs` → Save.**
> En un par de minutos responde `https://miguelverdugo313.github.io/Proyecto-Kevil/`.

---

## 4. Verificar la URL

TikTok no se fía de una dirección que no hayas demostrado que es tuya. Como la
web está en tu repositorio, se puede demostrar en dos minutos:

1. En el portal, arriba a la derecha: **URL properties**.
2. Elige verificar por **URL prefix** (no por dominio: `github.io` no es tuyo,
   pero esa carpeta sí).
3. Pega:

   ```
   https://miguelverdugo313.github.io/Proyecto-Kevil/
   ```

4. TikTok te da un archivo `tiktok-developers-site-verification.txt` con una
   cadena dentro. **Mándame esa cadena** y la subo al repositorio, o súbela tú:
   tiene que quedar en `docs/tiktok-developers-site-verification.txt`.
5. Espera a que GitHub publique (un par de minutos) y pulsa **Verify**.

> No borres ese archivo nunca: TikTok lo vuelve a comprobar cada cierto tiempo y
> si desaparece te quita la verificación.

---

## 5. Texto de productos y permisos

TikTok lo revisa en inglés. Pégalo tal cual en «Explain how each product and
scope works within your app».

```
Kevil Studio is a desktop application that a creator installs on their own
computer. It turns their own long-form YouTube videos and livestreams into
vertical short-form clips and publishes them to their own TikTok account.
There is no hosted service: everything runs locally and all credentials stay
on the creator's machine.

LOGIN KIT
Used only so the creator can connect their own TikTok account. The app opens
TikTok's official authorization screen in the user's browser (PKCE, desktop
flow, loopback redirect to 127.0.0.1). The returned access token is stored
locally and used only to act on that same account.

CONTENT POSTING API
Used to upload the clips the app produces. The flow is:
1. The creator adds a YouTube channel they own, or drops a video file.
2. The app downloads/reads the video on the creator's computer.
3. It transcribes it, scores the moments and picks the best ones.
4. It renders a 9:16 clip with subtitles and a hook, tracking the speaker.
5. The creator reviews the clip and its caption inside the app.
6. The app uploads it to the creator's own TikTok account.
Before posting, the app calls /post/publish/creator_info/query/ and only uses
a privacy level that the account actually allows. While the app is unaudited
it sends the clip to the creator's TikTok inbox as a draft instead.

SCOPES
- user.info.basic: show the connected account's display name and avatar in the
  app, so the creator can see which account they are publishing to.
- user.info.profile: show the account's username next to the avatar.
- user.info.stats: follower and like counts, used locally to decide how many
  clips per day that account should receive.
- video.upload: send a clip to the creator's TikTok inbox as a draft.
- video.publish: publish the clip directly to the creator's own account when
  they choose to.
- video.list: read the performance of the app's own posts (views, likes) so the
  app can learn which times of day work best for that account.

The app never posts to accounts other than the ones the user has explicitly
connected, never posts without the user's action or schedule, and does not
share any data with third parties.
```

---

## 6. El vídeo demo

Una grabación de pantalla de dos o tres minutos enseñando el flujo entero.
Grábala **en Sandbox**: los revisores lo esperan y no necesitas estar aprobado.

Guion:

1. Abres Kevil Studio.
2. **Ajustes → TikTok**: se ve la pantalla de conexión. Pulsas «Conectar».
3. Sale la **pantalla oficial de TikTok** pidiendo permiso. La lees en voz alta
   o la dejas unos segundos a la vista, y autorizas. *(Esto es lo que más
   miran: que el consentimiento sea el real y se vea entero.)*
4. Vuelves a la aplicación: la cuenta aparece conectada con su avatar.
5. Subes un vídeo o conectas un canal de YouTube.
6. Se ven los clips generados en la pantalla **Clips**.
7. Abres uno: se ve el vídeo vertical, el texto de la descripción y la
   privacidad elegida.
8. Le das a publicar y se ve el resultado en TikTok (en sandbox llega a la
   bandeja o queda privado: es lo normal y conviene que se vea).
9. Terminas enseñando cómo se retira el acceso: en TikTok, Ajustes y
   privacidad → Seguridad y permisos → Aplicaciones conectadas.

Sin música, sin cortes raros y con el ratón despacio. Súbelo a YouTube como
**no listado** y pega el enlace en el formulario.

---

## Y mientras tanto: Sandbox

Para **probar y usar el programa no necesitas nada de lo anterior**.

1. En tu app, pestaña **Sandbox** → crear uno.
2. **Target users**: añade tu propia cuenta de TikTok.
3. Configura ahí los mismos permisos y la misma **Redirect URI**
   (`http://127.0.0.1:8756/api/oauth/tiktok/callback`).
4. El sandbox tiene **su propia Client key y Client secret**: ésas son las que
   van en Kevil, no las de producción.

Límites del sandbox: hasta 5 sandboxes por app y 10 cuentas en cada uno.

Y el que de verdad importa: mientras la app no esté revisada, **la API no puede
publicar en público**. Kevil lo pregunta antes de subir nada y, si TikTok sólo
admite «sólo para mí», deja el clip **en tu bandeja de TikTok** en vez de
publicarlo en privado. Así te llega al móvil, le das a publicar y **ahí sí sale
en público para tu gente**. El trabajo entero lo hace el programa; lo único
manual es ese toque por clip.

Cuando pases la revisión, ese toque desaparece: publica solo y en público.
