# Conectar tu cuenta de TikTok

Kevil Studio publica con la **Content Posting API v2**, la vía oficial de TikTok.
Para usarla hace falta una app propia (gratuita) en el portal de desarrolladores.

Si sólo quieres probar el programa, sáltate todo esto: crea una **cuenta de prueba**
desde *Cuentas → Conectar TikTok*. Se generan los clips y se programan igual,
pero la subida se simula.

---

## 1. Crea la app

1. Entra en <https://developers.tiktok.com> y accede con tu cuenta de TikTok.
2. **Manage apps → Connect an app**. Ponle un nombre (por ejemplo, «Kevil Studio»).
3. Rellena los datos que pida (categoría, descripción, política de privacidad).
4. En **Platforms**, marca **Desktop**. No marques *Web*: como aplicación web,
   TikTok exige que la dirección de retorno empiece por `https` y no acepta la de
   tu propio ordenador.
5. Al marcar Desktop aparece **Configure for Web/Desktop → Web/Desktop URL**. Ese
   campo es **la web de tu aplicación**, no la dirección de retorno, y tiene que
   empezar por `https`. Si no tienes una, vale la del repositorio. Si pones ahí la
   dirección de retorno, TikTok contesta *«Enter a valid URL beginning with
   https://»*.

> Las aplicaciones de escritorio **tienen que usar PKCE**: Kevil lo hace solo, con
> el detalle particular de TikTok de enviar el reto en hexadecimal en vez de en
> base64url. Sin eso la autorización falla aunque todo lo demás esté bien.

## 2. Añade los productos y permisos

En la app, añade el producto **Content Posting API** y activa estos permisos (*scopes*):

| Permiso | Para qué |
|---|---|
| `user.info.basic` | nombre y avatar de la cuenta |
| `user.info.profile` | usuario público |
| `user.info.stats` | seguidores y likes (alimenta el motor de horarios) |
| `video.publish` | publicar directamente |
| `video.upload` | enviar a borradores |
| `video.list` | leer las métricas de tus publicaciones |

> **Direct Post**: para publicar sin pasar por la app de TikTok hay que activar
> «Direct Post» dentro de Content Posting API. Mientras la app esté en modo
> *sandbox* o sin auditar, TikTok obliga a que los vídeos se publiquen como
> privados (`SELF_ONLY`). Es normal: cámbialo en el flujo, paso «Publicación en
> TikTok → Privacidad», mientras haces pruebas.

## 3. Configura la URL de retorno

Va **dentro de Login Kit**, en el campo **Redirect URI** —que es otro distinto del
*Web/Desktop URL* del paso 1—. Ahí sí se admite `http` y tu propio ordenador, y
añade exactamente:

```
http://127.0.0.1:8756/api/oauth/tiktok/callback
```

Si arrancas en otro puerto (`python run.py --puerto 9000`), la URL cambia.
La correcta siempre aparece en **Ajustes** dentro de la aplicación: cópiala de ahí.

## 4. Copia las credenciales

En la ficha de la app tienes **Client key** y **Client secret**. Cada una va en su
casilla de Kevil Studio, en **Ajustes → TikTok**. Son cadenas de letras y números:
ahí no va ninguna dirección web.

## 4 bis. Si TikTok aún no ha revisado tu app

Sin revisar, la API no deja publicar directamente. Kevil se da cuenta y **deja el
clip en la bandeja de tu TikTok** en vez de perderlo: te llega igual al móvil y
sólo tienes que darle a publicar. Lo verás anotado en los avisos.

## 5. Autoriza la cuenta

**Cuentas → Conectar TikTok → Autorizar en TikTok**. Se abre TikTok, aceptas los
permisos y vuelves a la aplicación con la cuenta ya conectada.

Puedes repetirlo con tantas cuentas como quieras: cada una tendrá su propia
estrategia de horarios y sus propios canales de origen.

---

## Cosas que conviene saber

* **El token caduca.** Kevil Studio lo renueva solo con el *refresh token*. Si la
  cuenta aparece como «Falta autorizar», vuelve a pasar por el botón de autorizar.
* **Límites de TikTok.** La API limita cuántos vídeos se pueden subir al día por
  cuenta. Si te acercas al límite, baja el «Máximo por día» en la estrategia.
* **Vídeos que rechaza.** TikTok verifica el archivo después de subirlo. Si lo
  rechaza, verás el motivo en la publicación, dentro de Agenda.
* **Borradores.** Con el modo «Enviar al borrador de TikTok», el clip aparece en la
  bandeja de la app móvil y lo publicas tú desde el teléfono. Es la opción más
  conservadora si la app aún no está auditada.
* **Tus credenciales no salen de tu equipo**: se guardan en `data/kevil.db`, en tu disco.
