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

En **Login Kit / Redirect URI**, añade exactamente:

```
http://127.0.0.1:8756/api/oauth/tiktok/callback
```

Si arrancas en otro puerto (`python run.py --puerto 9000`), la URL cambia.
La correcta siempre aparece en **Ajustes** dentro de la aplicación: cópiala de ahí.

## 4. Copia las credenciales

En la ficha de la app tienes **Client key** y **Client secret**.
Pégalas en Kevil Studio, en **Ajustes → TikTok**, y guarda.

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
