# Publicar Shorts en YouTube

Kevil sube Shorts con la **YouTube Data API v3**, la vía oficial. Hace falta un
proyecto propio en Google Cloud (gratuito).

> **Ojo, esto sólo es para publicar.** Para vigilar canales, descargar vídeos y
> traerte tus Shorts a TikTok no hace falta nada de esto: eso funciona sin claves.

---

## El límite de cuota (léelo antes de empezar)

Google reparte **10.000 unidades de cuota al día** por proyecto y cada subida de
vídeo cuesta **1.600**. Es decir: **unas 6 publicaciones diarias**.

No es un límite de Kevil, es de Google, y afecta igual a cualquier programa que
publique con la API. Con eso en mente:

* En la estrategia de tu canal, deja el máximo diario en 5 o menos.
* Kevil lleva la cuenta y te la enseña en **Ajustes → YouTube**.
* Si necesitas más, se puede pedir ampliación de cuota en la consola de Google
  (rellenando un formulario de auditoría; tardan semanas y no siempre la dan).

---

## 1. Crea el proyecto

1. Entra en <https://console.cloud.google.com> y crea un proyecto nuevo.
2. Ve a **APIs y servicios → Biblioteca**, busca **YouTube Data API v3** y pulsa
   **Habilitar**.

## 2. Configura la pantalla de consentimiento

En **APIs y servicios → Pantalla de consentimiento de OAuth**:

1. Tipo de usuario: **Externo**.
2. Rellena el nombre de la aplicación y tu correo.
3. En **Permisos**, añade estos dos:
   * `.../auth/youtube.upload` — subir vídeos.
   * `.../auth/youtube.readonly` — leer los datos del canal y las estadísticas.
4. En **Usuarios de prueba**, añade tu propia cuenta de Google.

> Mientras la app esté «en pruebas», sólo funcionará con los usuarios de prueba que
> añadas, y el permiso caduca cada 7 días (tendrás que volver a autorizar). Para uso
> personal es perfectamente válido; si te molesta reautorizar, publica la app
> (Google pedirá verificación).

## 3. Crea las credenciales

En **APIs y servicios → Credenciales → Crear credenciales → ID de cliente de OAuth**:

1. Tipo: **Aplicación web**.
2. En **URIs de redireccionamiento autorizados**, añade exactamente:

   ```
   http://127.0.0.1:8756/api/oauth/youtube/callback
   ```

   Si arrancas Kevil en otro puerto, la URL cambia. La correcta siempre aparece en
   **Ajustes → YouTube**: cópiala de ahí.
3. Copia el **ID de cliente** y el **secreto de cliente**.

## 4. Conéctalo en Kevil

1. **Ajustes → YouTube**: pega el ID y el secreto, y guarda.
2. Pulsa **Autorizar mi canal**. Se abre Google, aceptas y vuelves.
3. Listo: en Ajustes verás el canal conectado y la cuota que te queda hoy.

## 5. Activa la publicación en tus flujos

En **Flujos**, paso **Publicación**, enciende *«Publicar en YouTube Shorts»*.
También tienes la plantilla **🚀 Clips a TikTok y Shorts**, que ya viene con los
dos destinos activados y los clips limitados a 58 segundos.

Cada clip generará entonces **dos publicaciones**: una para TikTok y otra para
YouTube, cada una con su propio horario (cada cuenta tiene su estrategia).

---

## Cosas que conviene saber

* **Qué cuenta como Short.** Vertical (más alto que ancho) y máximo 3 minutos.
  Kevil lo comprueba antes de subir y te avisa en el registro de la tarea si algo
  no cuadra. Al título se le añade ` #Shorts` (editable en el flujo) para ayudar a
  que YouTube lo clasifique bien.
* **La miniatura.** Se intenta poner la del clip, pero YouTube sólo admite
  miniaturas personalizadas en canales verificados; si el tuyo no lo está, se
  ignora sin dar error. En Shorts, además, casi siempre se usa un fotograma.
* **Privacidad.** En el flujo puedes elegir público, oculto o privado. Para las
  primeras pruebas, «privado» es lo más seguro.
* **El permiso caduca.** Kevil renueva el acceso solo mientras tenga el permiso de
  larga duración. Si la cuenta aparece como «falta autorizar», vuelve a pasar por
  el botón de autorizar.
* **Tus credenciales no salen de tu equipo**: se guardan en `data/kevil.db`.
