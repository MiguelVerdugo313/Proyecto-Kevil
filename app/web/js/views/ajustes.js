// Ajustes: lo justo a la vista, y todo lo demás detrás de «Editar».

import { api } from '../lib/api.js';
import { cargarColores } from '../app.js';
import { subirCookies, usarSesionYouTube } from '../lib/ayuda.js';
import { activarProblemas, problemasHtml } from '../lib/problemas.js';
import { activarSegundoPlano, estadoSegundoPlano } from '../lib/segundoPlano.js';
import {
  confirmDialog, escapeHtml, modal, toast, toastError,
} from '../lib/ui.js';

/* ------------------------------------------------------------ una conexión */
function fila({ nombre, descripcion, estado, tono, accion, boton = 'Editar' }) {
  return `<div class="conexion">
    <div class="grow" style="min-width:0">
      <div style="display:flex;gap:9px;align-items:center;flex-wrap:wrap">
        <strong>${escapeHtml(nombre)}</strong>
        <span class="pill ${tono}">${escapeHtml(estado)}</span>
      </div>
      <p class="muted small" style="margin-top:5px">${descripcion}</p>
    </div>
    <button class="btn sm" data-abrir="${accion}">${escapeHtml(boton)}</button>
  </div>`;
}

/* --------------------------------------------------------------- diálogos */
/* Inteligencia artificial: una lista de claves de varios sitios. La primera
   manda; si falla (sin créditos, límite, modelo retirado…), pasa a la
   siguiente. Los modelos se piden a cada proveedor: la lista es la de verdad. */
async function editarIA(reload) {
  let datos = await api.get('/api/ia');
  let elegido = '';

  const filaProveedor = (p, i) => `
    <div class="proveedor ${p.principal && p.tiene_clave ? 'principal' : ''}" data-prov="${escapeHtml(p.id)}">
      <div class="proveedor-head">
        <span class="orden">${i + 1}</span>
        <strong>${escapeHtml(p.nombre)}</strong>
        ${!p.tiene_clave ? '<span class="pill">sin clave</span>'
          : !p.activo ? '<span class="pill">apagado</span>'
          : p.principal ? '<span class="pill ok">principal</span>' : '<span class="pill violet">reserva</span>'}
        ${p.keys_url ? `<a class="muted tiny" href="${escapeHtml(p.keys_url)}" target="_blank" rel="noreferrer"
          style="text-decoration:underline">conseguir clave</a>` : ''}
        <span class="grow"></span>
        ${p.tiene_clave && !p.principal ? '<button class="btn sm ghost" data-principal>Usar primero</button>' : ''}
        ${p.tiene_clave ? `<button class="btn sm ghost" data-quitar>${p.fijo ? 'Quitar clave' : 'Quitar'}</button>` : ''}
      </div>
      ${p.aviso ? `<div class="small" style="color:var(--amber)">↻ ${escapeHtml(p.aviso)}</div>` : ''}
      ${p.fallo ? `<div class="small" style="color:var(--red)">× Último fallo: ${escapeHtml(p.fallo)}</div>` : ''}
      <div class="proveedor-fila">
        <div class="field"><label>Clave</label>
          <input type="password" data-clave placeholder="${escapeHtml(p.clave || 'pega aquí tu clave')}"
            autocomplete="off"></div>
        <div class="field"><label>Modelo</label>
          <div style="display:flex;gap:6px">
            <select data-modelo><option value="${escapeHtml(p.modelo)}">${escapeHtml(p.modelo || 'el recomendado')}</option></select>
            <button class="btn sm" data-ver-modelos title="Pedir a ${escapeHtml(p.nombre)} la lista de sus modelos">Ver todos</button>
          </div></div>
        <div style="display:flex;gap:6px">
          <button class="btn sm" data-probar>Probar</button>
          <button class="btn sm primary" data-guardar>Guardar</button>
        </div>
      </div>
      <div class="tiny muted" data-salida></div>
    </div>`;

  const catalogoHtml = () => `
    <div class="bloque">
      <div class="bloque-head"><div>
        <strong style="font-size:14px">Añadir otra clave</strong>
        <p class="muted tiny" style="margin-top:4px">Puedes poner varias, incluso dos del mismo sitio: se usan en orden y se pasa sola a la siguiente.</p>
      </div></div>
      <div class="catalogo">${datos.catalogo.map((c) => `
        <button type="button" data-tipo="${escapeHtml(c.tipo)}" class="${elegido === c.tipo ? 'sel' : ''}">
          <strong>${escapeHtml(c.nombre)}</strong><span>${escapeHtml(c.nota)}</span></button>`).join('')}
      </div>
      ${elegido ? (() => {
        const c = datos.catalogo.find((x) => x.tipo === elegido);
        return `<div class="form-grid" style="margin-top:14px">
          ${c.sin_clave ? '' : `<div class="field"><label>Clave de ${escapeHtml(c.nombre)}</label>
            <input type="password" id="nueva-clave" placeholder="pega aquí tu clave" autocomplete="off">
            ${c.keys_url ? `<span class="help">Se consigue en <a href="${escapeHtml(c.keys_url)}" target="_blank" rel="noreferrer" style="text-decoration:underline">${escapeHtml(c.keys_url.replace('https://', ''))}</a></span>` : ''}</div>`}
          <div class="field"><label>Dirección del servicio</label>
            <input type="text" id="nueva-url" value="${escapeHtml(c.base_url)}" placeholder="https://…/v1">
            <span class="help">${c.tipo === 'ollama' ? 'Ollama tiene que estar abierto en tu PC.' : 'Normalmente no hay que tocarla.'}</span></div>
          <div class="full" style="display:flex;justify-content:flex-end">
            <button class="btn primary" data-anadir>Añadir ${escapeHtml(c.nombre)}</button></div>
        </div>`;
      })() : ''}
    </div>`;

  const cuerpo = () => `
    <p class="muted small" style="line-height:1.7">
      Sirve para los títulos, la descripción, los hashtags y las ideas. Pon las claves que quieras:
      <b>la primera manda</b> y si falla (sin créditos, límite de peticiones o un modelo retirado)
      Kevil pasa sola a la siguiente. Sin ninguna, los textos se generan en local.
    </p>
    <div class="proveedores">${datos.proveedores.map(filaProveedor).join('')}</div>
    ${catalogoHtml()}
    <div id="ia-resultado" class="small"></div>`;

  const { root } = modal({
    title: 'Inteligencia artificial',
    wide: true,
    body: '<div id="ia-cuerpo"></div>',
    actions: [
      { label: 'Probar todas', onClick: async (raiz) => {
        const salida = raiz.querySelector('#ia-resultado');
        salida.innerHTML = '<span class="muted">Probando…</span>';
        try {
          const r = await api.post('/api/ia/probar', {});
          datos = r;
          pintar();
          raiz.querySelector('#ia-resultado').innerHTML = r.results.map((x) => `
            <div style="margin-top:6px;color:${x.ok ? 'var(--green)' : 'var(--red)'}">
              ${x.ok ? '✓' : '×'} ${escapeHtml(x.label)}: ${escapeHtml(x.ok ? `${x.model || ''} ${x.detail && x.detail.includes('retiró') ? `(${x.detail})` : ''}` : x.detail)}
            </div>`).join('');
        } catch (error) {
          salida.innerHTML = `<span style="color:var(--red)">${escapeHtml(error.message)}</span>`;
        }
        return false;
      } },
      { label: 'Listo', variant: 'primary', onClick: () => { reload(); } },
    ],
  });

  function pintar() {
    const caja = root.querySelector('#ia-cuerpo');
    caja.innerHTML = cuerpo();
    caja.querySelectorAll('[data-prov]').forEach(conectarFila);
    caja.querySelectorAll('[data-tipo]').forEach((b) => {
      b.onclick = () => { elegido = elegido === b.dataset.tipo ? '' : b.dataset.tipo; pintar(); };
    });
    const anadir = caja.querySelector('[data-anadir]');
    if (anadir) {
      anadir.onclick = async () => {
        try {
          datos = await api.post('/api/ia/proveedores', {
            tipo: elegido,
            api_key: caja.querySelector('#nueva-clave')?.value.trim() || '',
            base_url: caja.querySelector('#nueva-url')?.value.trim() || '',
          });
          toast('Añadido. Pulsa «Probar» para comprobar la clave.');
          elegido = '';
          pintar();
        } catch (error) { toastError(error); }
      };
    }
  }

  function conectarFila(fila) {
    const id = fila.dataset.prov;
    const salida = fila.querySelector('[data-salida]');
    const selector = fila.querySelector('[data-modelo]');
    fila.querySelector('[data-ver-modelos]').onclick = async (e) => {
      const boton = e.currentTarget;
      boton.disabled = true;
      salida.textContent = 'Pidiendo la lista de modelos…';
      try {
        const r = await api.get(`/api/ia/modelos?id=${encodeURIComponent(id)}&refrescar=true`);
        if (r.error) { salida.textContent = r.error; return; }
        selector.innerHTML = r.modelos.map((m) => `<option value="${escapeHtml(m.id)}" ${m.id === r.actual ? 'selected' : ''}>
          ${escapeHtml(m.id)}${m.gratis ? '  · gratis' : ''}${m.id === r.recomendado ? '  ★ recomendado' : ''}</option>`).join('');
        salida.textContent = `${r.modelos.length} modelos disponibles ahora mismo.`;
      } catch (error) {
        salida.textContent = error.message;
      } finally { boton.disabled = false; }
    };
    fila.querySelector('[data-guardar]').onclick = async () => {
      try {
        datos = await api.patch(`/api/ia/proveedores/${encodeURIComponent(id)}`, {
          api_key: fila.querySelector('[data-clave]').value.trim() || null,
          modelo: selector.value,
        });
        toast('Guardado');
        pintar();
      } catch (error) { toastError(error); }
    };
    fila.querySelector('[data-probar]').onclick = async () => {
      salida.textContent = 'Probando…';
      try {
        const clave = fila.querySelector('[data-clave]').value.trim();
        if (clave || selector.value) {
          await api.patch(`/api/ia/proveedores/${encodeURIComponent(id)}`, { api_key: clave || null, modelo: selector.value });
        }
        const r = await api.post('/api/ia/probar', { id });
        datos = r;
        const x = r.results[0];
        pintar();
        const nueva = root.querySelector(`[data-prov="${CSS.escape(id)}"] [data-salida]`);
        if (nueva) {
          nueva.innerHTML = x && x.ok
            ? `<span style="color:var(--green)">✓ Responde con ${escapeHtml(x.model || '')}</span>`
            : `<span style="color:var(--red)">× ${escapeHtml(x ? x.detail : 'sin respuesta')}</span>`;
        }
      } catch (error) { salida.innerHTML = `<span style="color:var(--red)">× ${escapeHtml(error.message)}</span>`; }
    };
    const principal = fila.querySelector('[data-principal]');
    if (principal) {
      principal.onclick = async () => { datos = await api.post('/api/ia/principal', { id }); pintar(); };
    }
    const quitar = fila.querySelector('[data-quitar]');
    if (quitar) {
      quitar.onclick = async () => {
        if (!await confirmDialog('Quitar la clave', 'Kevil dejará de usar este proveedor.', 'Quitar')) return;
        datos = await api.del(`/api/ia/proveedores/${encodeURIComponent(id)}`);
        editarIA(reload);
      };
    }
  }

  pintar();
}

/* Tu sesión de YouTube: lo que evita el «demuestra que no eres un robot» */
async function editarSesion(reload) {
  const estado = await api.get('/api/youtube/sesion');
  modal({
    title: 'Tu sesión de YouTube',
    wide: true,
    body: `
      <p class="muted small" style="line-height:1.7">
        Cuando se bajan muchos vídeos seguidos, YouTube pide «demuestra que no eres un robot».
        Con tu sesión (las cookies de tu navegador) Kevil baja como si fueras tú y deja de pedirlo.
        <b>Kevil ya lo intenta solo</b> la primera vez que pasa; aquí puedes hacerlo a mano.
      </p>
      <div class="bloque">
        <div class="list">
          <div class="list-row"><span class="grow">Ahora mismo usa</span><b>${escapeHtml(estado.usando)}</b></div>
          <div class="list-row"><span class="grow">Navegadores encontrados</span>
            <b>${estado.navegadores.map((n) => escapeHtml(n.nombre)).join(', ') || 'ninguno'}</b></div>
          <div class="list-row"><span class="grow">Motor de JavaScript para YouTube</span>
            ${estado.motor_js ? '<span class="pill ok">incluido</span>' : '<span class="pill warn">no encontrado</span>'}</div>
        </div>
      </div>
      <div class="guia">
        ${paso(1, 'Abre YouTube en tu navegador y entra con tu cuenta', 'Mejor en <b>Firefox</b>: es el único cuya sesión se lee siempre bien. Con Edge o Chrome también suele valer.')}
        ${paso(2, 'Cierra ese navegador del todo', 'Chrome y Edge no dejan leer su sesión mientras están abiertos (mira también el icono junto al reloj).')}
        ${paso(3, 'Pulsa «Usar mi sesión de YouTube»', 'Kevil prueba tus navegadores, se queda con el que funcione y vuelve a poner en marcha lo que falló.')}
        ${paso(4, 'Si ninguno vale: sube un cookies.txt', 'En Chrome instala la extensión «Get cookies.txt LOCALLY», entra en youtube.com, pulsa «Export» y sube aquí el archivo.')}
      </div>
      <div class="field">
        <label>Qué sesión usar</label>
        <select id="sesion-modo">
          <option value="auto" ${estado.modo === 'auto' ? 'selected' : ''}>Automático: cookies.txt si hay; si no, probar navegadores cuando haga falta</option>
          ${estado.navegadores.map((n) => `<option value="${escapeHtml(n.id)}" ${estado.modo === n.id ? 'selected' : ''}>Siempre la de ${escapeHtml(n.nombre)}</option>`).join('')}
          ${estado.archivo ? `<option value="archivo" ${estado.modo === 'archivo' ? 'selected' : ''}>Siempre mi cookies.txt</option>` : ''}
          <option value="no" ${estado.modo === 'no' ? 'selected' : ''}>No usar ninguna</option>
        </select>
      </div>`,
    actions: [
      ...(estado.archivo ? [{ label: 'Borrar cookies.txt', variant: 'danger', onClick: async () => {
        await api.del('/api/youtube/sesion/archivo'); toast('Borrado'); reload();
      } }] : []),
      { label: 'Subir cookies.txt', onClick: async () => { if (await subirCookies()) reload(); return false; } },
      { label: 'Guardar', onClick: async (raiz) => {
        await api.post('/api/youtube/sesion/modo', { modo: raiz.querySelector('#sesion-modo').value });
        toast('Guardado'); reload();
      } },
      { label: 'Usar mi sesión de YouTube', variant: 'primary', onClick: async () => { await usarSesionYouTube(); } },
    ],
  });
}

/* Campo de sólo lectura con botón de copiar: la URL de retorno hay que pegarla
   tal cual en Google y en TikTok, y equivocarse en una letra rompe el enlace. */
function campoCopiable(etiqueta, valor, id) {
  return `<div class="field full"><label>${escapeHtml(etiqueta)}</label>
    <div style="display:flex;gap:8px;align-items:center">
      <input type="text" id="${id}" value="${escapeHtml(valor)}" readonly class="mono grow">
      <button class="btn sm" data-copiar="${id}">Copiar</button>
    </div></div>`;
}

function activarCopiar(root) {
  root.querySelectorAll('[data-copiar]').forEach((boton) => {
    boton.addEventListener('click', async () => {
      const campo = root.querySelector(`#${boton.dataset.copiar}`);
      try {
        await navigator.clipboard.writeText(campo.value);
      } catch {
        campo.select();
        document.execCommand('copy');
      }
      boton.textContent = 'Copiado';
      setTimeout(() => { boton.textContent = 'Copiar'; }, 1600);
    });
  });
}

function paso(numero, titulo, cuerpo) {
  return `<div class="paso-guia">
    <span class="paso-num">${numero}</span>
    <div class="grow" style="min-width:0">
      <strong>${titulo}</strong>
      <div class="muted small" style="margin-top:4px;line-height:1.65">${cuerpo}</div>
    </div>
  </div>`;
}

function editarDisco(valores, disco, reload) {
  const barra = (etiqueta, mb) => `
    <div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--line)">
      <span class="muted small">${escapeHtml(etiqueta)}</span>
      <b class="small">${mb} MB</b>
    </div>`;

  modal({
    title: 'Espacio en disco',
    body: `
      <p class="muted small" style="line-height:1.7">
        Kevil no está pensado para dejarte el disco lleno de vídeos. De cada
        vídeo largo se bajan <b>sólo los segundos que van a salir en un clip</b>,
        y en cuanto algo se publica, su archivo se borra.
      </p>

      <div class="bloque" style="margin-top:16px">
        ${barra('Vídeos originales', disco.parts.originales ?? 0)}
        ${barra('Clips montados', disco.parts.clips ?? 0)}
        ${barra('Miniaturas', disco.parts.miniaturas ?? 0)}
        ${barra('Temporales', disco.parts.temporales ?? 0)}
        <div style="display:flex;justify-content:space-between;padding:11px 0 2px">
          <b>Total ahora mismo</b>
          <b style="color:var(--accent)">${disco.total_mb} MB</b>
        </div>
      </div>

      <div class="form-grid" style="margin-top:18px">
        <div class="field full">
          <label class="switch">
            <input type="checkbox" id="disco-ligero" ${valores.light_mode ? 'checked' : ''}>
            <span class="track"></span>
            <span class="switch-label">Bajar sólo los trozos que se usan</span>
          </label>
          <span class="help">Un directo de dos horas pasa de varios GB a unos pocos MB.</span>
        </div>
        <div class="field full">
          <label class="switch">
            <input type="checkbox" id="disco-clips" ${valores.keep_clips ? 'checked' : ''}>
            <span class="track"></span>
            <span class="switch-label">Guardar los clips después de publicarlos</span>
          </label>
        </div>
        <div class="field full">
          <label class="switch">
            <input type="checkbox" id="disco-originales" ${valores.keep_originals ? 'checked' : ''}>
            <span class="track"></span>
            <span class="switch-label">Guardar los vídeos originales</span>
          </label>
        </div>
        <div class="field">
          <label>Tope de la carpeta (GB)</label>
          <input type="number" id="disco-tope" min="0" max="500" step="0.5"
            value="${valores.disk_budget_gb}">
          <span class="help">Al pasarse, se borra lo más antiguo ya publicado. 0 = sin tope.</span>
        </div>
      </div>`,
    actions: [
      { label: 'Cerrar' },
      { label: 'Borrarlo todo ahora', variant: 'danger', onClick: async () => {
        const seguro = await confirmDialog(
          'Borrar todos los vídeos',
          'Se borran los originales y los clips del disco. El historial de lo que '
          + 'has publicado se conserva; lo que desaparece son los archivos.',
          'Sí, liberar espacio',
        );
        if (!seguro) return false;
        const resultado = await api.post('/api/storage/purge');
        toast(`Liberados ${resultado.freed_mb} MB`);
        reload();
      } },
      { label: 'Limpiar lo publicado', onClick: async () => {
        const resultado = await api.post('/api/storage/clean');
        toast(resultado.freed_mb ? `Liberados ${resultado.freed_mb} MB` : 'Ya estaba limpio');
        reload();
      } },
      { label: 'Guardar', variant: 'primary', onClick: async (root) => {
        await api.put('/api/settings', {
          light_mode: root.querySelector('#disco-ligero').checked,
          keep_clips: root.querySelector('#disco-clips').checked,
          keep_originals: root.querySelector('#disco-originales').checked,
          disk_budget_gb: Number(root.querySelector('#disco-tope').value) || 0,
        });
        toast('Guardado');
        reload();
      } },
    ],
  });
}

function editarYouTube(valores, yt, reload) {
  // Ya conectado: nada que configurar, sólo el estado y el botón de rehacerlo.
  if (yt.connected) {
    const porDia = Math.floor(yt.quota.daily_units / yt.quota.cost_per_upload);
    modal({
      title: 'YouTube',
      body: `<p class="muted small" style="line-height:1.7">
          Tu canal está conectado y Kevil puede publicar Shorts en él.
          Hoy te quedan <b style="color:var(--text)">${yt.quota.uploads_left}</b>
          de ${porDia} subidas (es el límite de cuota que pone Google, no Kevil).
        </p>`,
      actions: [
        { label: 'Cerrar' },
        { label: 'Conectar otra cuenta', variant: 'primary',
          onClick: () => { window.location.href = '/api/oauth/youtube/start'; return false; } },
      ],
    });
    return;
  }

  // Ya hay credenciales: un solo botón.
  if (yt.configured) {
    modal({
      title: 'Conectar con Google',
      body: `<p class="muted small" style="line-height:1.7">
          Todo listo. Pulsa el botón, elige tu cuenta de Google y acepta los permisos:
          vuelves aquí solo y el canal queda conectado.
        </p>
        <p class="muted tiny" style="margin-top:14px">
          Google te enseñará un aviso de «aplicación no verificada». Es normal y no es
          un fallo: ese aviso sale en toda aplicación que no ha pasado la revisión de
          Google, y una que corre en tu ordenador y sólo la usas tú no la necesita.
          Pulsa «Configuración avanzada» → «Ir a Kevil Studio».
        </p>`,
      actions: [
        { label: 'Cancelar' },
        { label: 'Rehacer la configuración', onClick: () => { yt.configured = false; editarYouTube(valores, yt, reload); return false; } },
        { label: 'Conectar con Google', variant: 'primary',
          onClick: () => { window.location.href = '/api/oauth/youtube/start'; return false; } },
      ],
    });
    return;
  }

  // Primera vez: la guía.
  modal({
    title: 'Conectar con Google',
    body: `
      <p class="muted small" style="line-height:1.7">
        Sólo hace falta para <b>publicar Shorts</b>. Vigilar tus canales, bajar vídeos y
        pasar tus Shorts a TikTok ya funciona sin esto.
      </p>
      <p class="muted small" style="line-height:1.7;margin-top:10px">
        El botón de conectar es <b>el inicio de sesión de Google de verdad</b>: se abre
        <span class="mono">accounts.google.com</span>, eliges tu cuenta y ya. Lo único
        es que Google pide que cada programa se dé de alta con ellos una vez, y como
        Kevil corre en tu ordenador, ese programa es el tuyo. <b>Dos pasos.</b>
      </p>

      <div class="guia">
        ${paso(1, 'Activa la API de YouTube',
          `Abre <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noreferrer">crear proyecto</a>,
           ponle el nombre que quieras y créalo. Después entra en
           <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noreferrer">YouTube Data API v3</a>
           y pulsa <b>Habilitar</b>.`)}
        ${paso(2, 'Crea la credencial y pega el archivo',
          `En <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer">Credenciales</a>:
           <b>Crear credenciales → ID de cliente de OAuth</b> y elige el tipo
           <b>Aplicación de escritorio</b>.
           <br><br>Con ese tipo <b>no hay que copiar ninguna dirección</b>: Google acepta
           el retorno a tu propio ordenador sin registrarlo. Al crearla te ofrece
           descargar un <span class="mono">client_secret_….json</span>:
           <b>descárgalo y ya está</b>, no hace falta ni abrirlo. Pulsa abajo
           «Buscar el archivo» y Kevil lo coge de tu carpeta de Descargas.`)}
      </div>

      <div class="field full" style="margin-top:6px">
        <label>O pega aquí el archivo de Google</label>
        <textarea id="yt-json" rows="5" class="mono"
          placeholder='{"installed":{"client_id":"…","client_secret":"…"}}'></textarea>
      </div>

      <details style="margin-top:12px">
        <summary class="muted small">O ponlo a mano</summary>
        <div class="form-grid" style="margin-top:12px">
          <div class="field full"><label>ID de cliente</label>
            <input type="text" id="yt-id" value="${escapeHtml(valores.youtube_client_id || '')}"
              placeholder="123456789-abc.apps.googleusercontent.com"></div>
          <div class="field full"><label>Secreto de cliente</label>
            <input type="password" id="yt-secret" value="${escapeHtml(valores.youtube_client_secret || '')}"
              placeholder="••••••••"></div>
        </div>
      </details>`,
    wide: true,
    onOpen: activarCopiar,
    actions: [
      { label: 'Cancelar' },
      { label: 'Buscar el archivo', onClick: async () => {
        // Lo normal es que siga en Descargas tal cual lo dejó Google.
        const r = await api.post('/api/credentials/youtube/buscar', {});
        toast(`Encontrado: ${r.file} · abriendo Google…`);
        setTimeout(() => { window.location.href = '/api/oauth/youtube/start'; }, 900);
        return true;
      } },
      { label: 'Guardar y conectar', variant: 'primary', onClick: async (root) => {
        const pegado = root.querySelector('#yt-json').value.trim();
        if (pegado) {
          await api.post('/api/credentials/youtube', { text: pegado });
        } else {
          const id = root.querySelector('#yt-id').value.trim();
          const secreto = root.querySelector('#yt-secret').value.trim();
          if (!id || !secreto) {
            toastError('Pega el archivo de Google, o rellena los dos campos de abajo.');
            return false;
          }
          await api.put('/api/settings', {
            youtube_client_id: id,
            youtube_client_secret: secreto === '••••••••' ? undefined : secreto,
          });
        }
        toast('Credenciales guardadas · abriendo Google…');
        setTimeout(() => { window.location.href = '/api/oauth/youtube/start'; }, 700);
        return true;
      } },
    ],
  });
}

function editarTikTok(valores, tt, reload) {
  if (tt.configured) {
    modal({
      title: 'Conectar con TikTok',
      body: `<p class="muted small" style="line-height:1.7">
          Todo listo. Pulsa el botón, entra en tu cuenta de TikTok y acepta los
          permisos: vuelves aquí solo y la cuenta queda conectada.
        </p>
        <p class="muted tiny" style="margin-top:14px">
          Puedes conectar varias cuentas: cada canal de YouTube publica en la que
          le asignes.
        </p>`,
      actions: [
        { label: 'Cancelar' },
        { label: 'Rehacer la configuración', onClick: () => { tt.configured = false; editarTikTok(valores, tt, reload); return false; } },
        { label: 'Conectar con TikTok', variant: 'primary',
          onClick: () => { window.location.href = '/api/oauth/tiktok/start'; return false; } },
      ],
    });
    return;
  }

  modal({
    title: 'Conectar con TikTok',
    body: `
      <p class="muted small" style="line-height:1.7">
        Sin esto Kevil funciona en <b>simulación</b>: corta, monta y programa todo,
        pero no sube nada. Para publicar de verdad, TikTok exige registrar la
        aplicación una vez.
      </p>

      <div class="guia">
        ${paso(1, 'Crea la aplicación y márcala como <b>Desktop</b>',
          `Entra en <a href="https://developers.tiktok.com/apps" target="_blank" rel="noreferrer">developers.tiktok.com/apps</a>,
           inicia sesión y pulsa <b>Connect an app</b>.
           <br><br>Baja hasta <b>Platforms</b> y marca <b>Desktop</b>. Deja
           <b>Web</b> sin marcar: como «Web», TikTok exige que la dirección de
           retorno empiece por <span class="mono">https</span> y no acepta la de
           tu ordenador.`)}
        ${paso(2, 'Web/Desktop URL: la web de tu app, <u>no</u> la de retorno',
          `Al marcar Desktop sale un recuadro <b>Configure for Web/Desktop</b>
           con el campo <b>Web/Desktop URL</b>. Ahí va la web de tu aplicación y
           tiene que empezar por <span class="mono">https</span> —si pones otra
           cosa te saldrá «Enter a valid URL beginning with https://»—. Si no
           tienes web, vale ésta:`)}
        ${campoCopiable('Web/Desktop URL', 'https://github.com/MiguelVerdugo313/Proyecto-Kevil', 'tt-web')}
        ${paso(3, 'Añade los dos productos y sus permisos',
          `En <b>Products</b> añade <b>Login Kit</b> y <b>Content Posting API</b>.
           Después, en <b>Scopes</b>, marca estos cuatro:
           <span class="mono">user.info.basic</span>,
           <span class="mono">video.publish</span>,
           <span class="mono">video.upload</span> y
           <span class="mono">video.list</span>.
           Sin ellos TikTok corta la conexión nada más empezar.`)}
        ${paso(4, 'La dirección de retorno, dentro de Login Kit',
          `Dentro de <b>Login Kit</b> hay un campo <b>Redirect URI</b> —es otro,
           no el del paso 2— y ahí sí va esto tal cual:`)}
        ${campoCopiable('Redirect URI', tt.redirect_uri, 'tt-redirect')}
        ${paso(5, 'Copia las dos claves en sus casillas',
          `Arriba en la pantalla de tu app están <b>Client key</b> y
           <b>Client secret</b>. Cada una en su casilla de aquí abajo; no son
           direcciones web.`)}
      </div>

      <div class="form-grid" style="margin-top:6px">
        <div class="field full">
          <label>Client key</label>
          <input type="text" id="tt-key" class="mono" autocomplete="off" spellcheck="false"
            value="${escapeHtml(valores.tiktok_client_key || '')}" placeholder="aw…">
          <span class="help">Empieza por «aw» y es la más corta de las dos.</span>
        </div>
        <div class="field full">
          <label>Client secret</label>
          <input type="text" id="tt-secret" class="mono" autocomplete="off" spellcheck="false"
            placeholder="la cadena larga que sale debajo de la client key">
        </div>
      </div>
      <p class="tiny" id="tt-aviso" style="margin-top:8px;color:var(--red)" hidden></p>

      <p class="muted tiny" style="margin-top:12px">
        Hasta que TikTok revise tu app sólo deja dejar el vídeo en tu bandeja de
        TikTok en vez de publicarlo directamente. Kevil lo detecta y lo hace así
        solo: el clip te llega igual y sólo tienes que darle a publicar.
      </p>`,
    wide: true,
    onOpen: (root) => {
      activarCopiar(root);
      // Si pega de golpe las dos claves en una casilla, se reparten solas.
      root.querySelector('#tt-key').addEventListener('paste', (evento) => {
        const pegado = (evento.clipboardData || window.clipboardData).getData('text') || '';
        const piezas = pegado.split(/[\s,;:=]+/).filter((p) => p.length >= 8);
        if (piezas.length === 2) {
          evento.preventDefault();
          root.querySelector('#tt-key').value = piezas[0];
          root.querySelector('#tt-secret').value = piezas[1];
        }
      });
    },
    actions: [
      { label: 'Cancelar' },
      { label: 'Guardar y conectar', variant: 'primary', onClick: async (root) => {
        const aviso = root.querySelector('#tt-aviso');
        const fallo = (texto) => {
          aviso.textContent = texto;
          aviso.hidden = false;
          return false;
        };
        const clave = root.querySelector('#tt-key').value.trim();
        const secreto = root.querySelector('#tt-secret').value.trim();

        if (!clave || !secreto) return fallo('Faltan las dos claves: la key y el secret.');
        if (/https?:\/\//.test(clave) || /https?:\/\//.test(secreto)) {
          return fallo('Eso es una dirección web. La de retorno va en TikTok, en «Redirect URI» de Login Kit.');
        }
        if (clave === secreto) return fallo('Has puesto lo mismo en las dos casillas: son valores distintos.');

        await api.post('/api/credentials/tiktok', { client_key: clave, client_secret: secreto });
        toast('Credenciales guardadas · abriendo TikTok…');
        setTimeout(() => { window.location.href = '/api/oauth/tiktok/start'; }, 700);
        return true;
      } },
    ],
  });
}

function editarColores(marca, reload) {
  const actual = marca.accent || marca.default_accent;
  modal({
    title: 'Los colores de la aplicación',
    body: `
      <p class="muted small" style="line-height:1.7">
        Kevil puede vestirse con los colores de tu canal: se sacan del avatar y se
        ajustan solos para que se lean bien en oscuro y en claro.
      </p>
      ${marca.channels.length ? `
        <div class="field">
          <label>Sacarlos de un canal</label>
          <div class="canales">
            ${marca.channels.map((canal) => `
              <button class="canal" data-canal="${canal.id}">
                <img src="${escapeHtml(canal.avatar_url)}" alt="" onerror="this.style.visibility='hidden'">
                <span>${escapeHtml(canal.name)}</span>
              </button>`).join('')}
          </div>
        </div>` : `<p class="muted small">
          Conecta un canal en «Cuentas» y podrás sacar los colores de su avatar.</p>`}

      <div class="field">
        <label>O elígelo a mano</label>
        <div style="display:flex;gap:12px;align-items:center">
          <input type="color" id="c-acento" value="${escapeHtml(actual)}" style="width:84px">
          <input type="text" id="c-hex" value="${escapeHtml(actual)}" class="mono" style="flex:1">
        </div>
      </div>
      <div id="c-aviso" class="muted tiny"></div>`,
    actions: [
      { label: 'Color por defecto', onClick: async () => {
        await api.del('/api/branding');
        await cargarColores();
        toast('Colores restablecidos');
        reload();
      } },
      { label: 'Aplicar', variant: 'primary', onClick: async (root) => {
        await api.post('/api/branding', { accent: root.querySelector('#c-hex').value.trim() });
        await cargarColores();
        toast('Colores aplicados');
        reload();
      } },
    ],
    onOpen(root) {
      const color = root.querySelector('#c-acento');
      const hex = root.querySelector('#c-hex');
      const vistaPrevia = (valor) => document.documentElement.style.setProperty('--accent', valor);

      color.oninput = () => { hex.value = color.value.toUpperCase(); vistaPrevia(color.value); };
      hex.oninput = () => {
        if (/^#[0-9a-f]{6}$/i.test(hex.value)) { color.value = hex.value; vistaPrevia(hex.value); }
      };

      root.querySelectorAll('[data-canal]').forEach((boton) => {
        boton.onclick = async () => {
          const aviso = root.querySelector('#c-aviso');
          aviso.textContent = 'Leyendo los colores del avatar…';
          try {
            const resultado = await api.post('/api/branding', {
              account_id: Number(boton.dataset.canal),
            });
            hex.value = resultado.accent;
            color.value = resultado.accent;
            await cargarColores();
            aviso.innerHTML = `Color detectado: <b class="mono">${escapeHtml(resultado.accent)}</b>. Ya está aplicado.`;
            root.querySelectorAll('[data-canal]').forEach((b) => b.classList.remove('sel'));
            boton.classList.add('sel');
          } catch (error) {
            aviso.innerHTML = `<span style="color:var(--red)">${escapeHtml(error.message)}</span>`;
          }
        };
      });
    },
  });
}

function editarMotor(valores, reload) {
  modal({
    title: 'Motor y rendimiento',
    body: `
      <div class="form-grid">
        <div class="field"><label>Tareas en paralelo</label>
          <input type="number" id="m-workers" min="1" max="8" value="${valores.workers}">
          <span class="help">Más rápido, pero más carga en el equipo.</span></div>
        <div class="field"><label>Revisar canales cada (min)</label>
          <input type="number" id="m-watch" min="1" max="1440" value="${valores.watch_interval_minutes}"></div>
        <div class="field"><label>Ruta de ffmpeg</label>
          <input type="text" id="m-ffmpeg" value="${escapeHtml(valores.ffmpeg_path)}"></div>
        <div class="field"><label>Ruta de ffprobe</label>
          <input type="text" id="m-ffprobe" value="${escapeHtml(valores.ffprobe_path)}"></div>
        <div class="field full"><label class="switch">
          <input type="checkbox" id="m-dry" ${valores.dry_run ? 'checked' : ''}>
          <span class="track"></span>
          <span class="switch-label">Modo simulación: procesa y programa, pero no publica</span></label></div>
        <div class="field full"><label class="switch">
          <input type="checkbox" id="m-desktop" ${valores.notifications_desktop ? 'checked' : ''}>
          <span class="track"></span>
          <span class="switch-label">Avisos en el escritorio</span></label></div>
      </div>`,
    actions: [
      { label: 'Cancelar' },
      { label: 'Guardar', variant: 'primary', onClick: async (root) => {
        await api.put('/api/settings', {
          workers: Number(root.querySelector('#m-workers').value),
          watch_interval_minutes: Number(root.querySelector('#m-watch').value),
          ffmpeg_path: root.querySelector('#m-ffmpeg').value.trim(),
          ffprobe_path: root.querySelector('#m-ffprobe').value.trim(),
          dry_run: root.querySelector('#m-dry').checked,
          notifications_desktop: root.querySelector('#m-desktop').checked,
        });
        toast('Ajustes guardados');
        reload();
      } },
    ],
  });
}

/* ------------------------------------------------------------------ vista */
export default {
  title: 'Ajustes',
  subtitle: 'Lo esencial a la vista; el resto, cuando lo necesites',

  async render(root, ctx) {
    const [config, status, ia, yt, tt, marca, disco, sesion, problemas, segundoPlano] = await Promise.all([
      api.settings(), api.status(),
      api.get('/api/ia'), api.get('/api/youtube/config'),
      api.get('/api/tiktok/config'), api.get('/api/branding'),
      api.get('/api/storage'), api.get('/api/youtube/sesion'), problemasHtml(),
      estadoSegundoPlano(),
    ]);
    const valores = config.settings;
    const iaActivos = ia.proveedores.filter((p) => p.tiene_clave && p.activo);

    root.innerHTML = `
      <div class="grid side">
        <div style="display:flex;flex-direction:column;gap:22px">
          <div class="card">
            <div class="card-head">
              <div>
                <h3>Tu canal</h3>
                <p class="muted small" style="margin-top:4px">
                  Con esto el asistente afina las ideas y sabe cuándo avisarte.</p>
              </div>
              <button class="btn sm primary" data-guardar-canal>Guardar</button>
            </div>
            <div class="form-grid">
              <div class="field full"><label>¿De qué va tu canal?</label>
                <input type="text" id="ch-topic" value="${escapeHtml(valores.channel_topic || '')}"
                  placeholder="Gameplays de Minecraft y juegos de supervivencia"></div>
              <div class="field"><label>Vídeos por semana</label>
                <input type="number" id="ch-week" min="0.25" max="14" step="0.25"
                  value="${valores.target_uploads_per_week}"></div>
              <div class="field"><label>Idioma</label>
                <select id="ch-lang">
                  ${[['es', 'Español'], ['en', 'Inglés'], ['pt', 'Portugués']].map(([v, l]) =>
                    `<option value="${v}" ${valores.channel_language === v ? 'selected' : ''}>${l}</option>`).join('')}
                </select></div>
            </div>
          </div>

          <div class="card">
            <div class="card-head">
              <div>
                <h3>Conexiones</h3>
                <p class="muted small" style="margin-top:4px">
                  Todas opcionales: sin ellas Kevil funciona en local y en simulación.</p>
              </div>
            </div>
            <div class="conexiones">
              ${fila({
                nombre: 'Inteligencia artificial',
                descripcion: iaActivos.length
                  ? `${iaActivos.map((p) => escapeHtml(p.nombre)).join(' → ')}${iaActivos.length > 1 ? ' · se pasa sola a la siguiente si una falla' : ''}`
                  : 'Sin clave: los textos se generan en local',
                estado: iaActivos.length ? `${iaActivos.length} clave(s)` : 'sin clave',
                tono: iaActivos.some((p) => p.fallo) ? 'warn' : (iaActivos.length ? 'ok' : ''),
                accion: 'ia',
                boton: iaActivos.length ? 'Editar' : 'Añadir clave',
              })}
              ${fila({
                nombre: 'Descargas de YouTube',
                descripcion: `Sesión: ${escapeHtml(sesion.usando)}${sesion.motor_js ? '' : ' · falta el motor de JavaScript'}`,
                estado: sesion.modo === 'auto' && !sesion.archivo ? 'automático' : 'con tu sesión',
                tono: 'ok',
                accion: 'sesion',
                boton: 'Revisar',
              })}
              ${fila({
                nombre: 'YouTube',
                descripcion: yt.connected
                  ? `Publica Shorts · ${yt.quota.uploads_left} subidas disponibles hoy`
                  : 'Necesario sólo para publicar Shorts',
                estado: yt.connected ? 'conectado' : (yt.configured ? 'falta autorizar' : 'sin configurar'),
                tono: yt.connected ? 'ok' : (yt.configured ? 'warn' : ''),
                accion: 'youtube',
                boton: yt.connected ? 'Editar' : 'Conectar',
              })}
              ${fila({
                nombre: 'TikTok',
                descripcion: tt.connected
                  ? `${tt.accounts} cuenta(s) conectada(s) · publica de verdad`
                  : (tt.configured
                    ? 'App configurada: ya puedes autorizar tu cuenta'
                    : 'Sin credenciales: las publicaciones se simulan'),
                estado: tt.connected ? 'conectado' : (tt.configured ? 'falta autorizar' : 'simulación'),
                tono: tt.connected ? 'ok' : 'warn',
                accion: 'tiktok',
                boton: tt.connected ? 'Editar' : 'Conectar',
              })}
              ${fila({
                nombre: 'Espacio en disco',
                descripcion: disco.light_mode
                  ? `Ocupa ${disco.total_mb} MB · se baja sólo lo que se usa y se borra al publicar`
                  : `Ocupa ${disco.total_mb} MB · guardando los vídeos completos`,
                estado: disco.over_budget
                  ? 'pasado de tope'
                  : (disco.light_mode ? 'sin rastro' : 'guardando'),
                tono: disco.over_budget ? 'warn' : (disco.light_mode ? 'ok' : ''),
                accion: 'disco',
              })}
              ${fila({
                nombre: 'Colores',
                descripcion: marca.theme.custom
                  ? `Usando <b class="mono" style="color:var(--accent)">${escapeHtml(marca.accent)}</b> · ${escapeHtml(marca.source || 'manual')}`
                  : 'Color por defecto de Kevil',
                estado: marca.theme.custom ? 'personalizado' : 'por defecto',
                tono: marca.theme.custom ? 'ok' : '',
                accion: 'colores',
                boton: 'Cambiar',
              })}
              ${fila({
                nombre: 'Motor',
                descripcion: `${valores.workers} tarea(s) a la vez · revisa cada ${valores.watch_interval_minutes} min`
                  + (valores.dry_run ? ' · <b style="color:var(--amber)">simulación activada</b>' : ''),
                estado: valores.dry_run ? 'simulación' : 'normal',
                tono: valores.dry_run ? 'warn' : '',
                accion: 'motor',
              })}
            </div>
          </div>

          ${problemas.html}
        </div>

        <div style="display:flex;flex-direction:column;gap:22px">
          ${segundoPlano ? `<div class="card">
            <div class="card-head"><h3>Publicar sin estar pendiente</h3></div>
            <p class="muted small" style="line-height:1.6;margin-bottom:12px">
              Los Shorts quedan programados dentro de YouTube. TikTok no deja programar a otras apps: Kevil los
              publica a su hora, así que conviene que siga en marcha aunque cierres la ventana.</p>
            <div style="display:flex;flex-direction:column;gap:12px">
              <label class="switch"><input type="checkbox" data-sp="segundo_plano" ${segundoPlano.segundo_plano ? 'checked' : ''}>
                <span class="track"></span><span class="switch-label">Seguir en segundo plano al cerrar la ventana</span></label>
              <label class="switch ${segundoPlano.arranque_disponible ? '' : 'apagado'}"><input type="checkbox" data-sp="arrancar_con_windows"
                ${segundoPlano.arranca_con_windows ? 'checked' : ''} ${segundoPlano.arranque_disponible ? '' : 'disabled'}>
                <span class="track"></span><span class="switch-label">Arrancar con Windows (en segundo plano)</span></label>
            </div>
            <button class="btn sm danger" style="margin-top:14px" data-salir-del-todo>Cerrar Kevil del todo</button>
          </div>` : ''}
          <div class="card">
            <div class="card-head"><h3>Estado</h3></div>
            <div class="list">
              <div class="list-row"><span class="grow">Versión</span><b>${escapeHtml(config.version)}</b></div>
              <div class="list-row"><span class="grow">ffmpeg</span>
                ${status.ffmpeg ? '<span class="pill ok">disponible</span>' : '<span class="pill bad">no encontrado</span>'}</div>
              <div class="list-row"><span class="grow">Espacio libre</span><b>${status.disk_free_gb} GB</b></div>
              <div class="list-row"><span class="grow">Cuentas</span>
                <b>${status.accounts.youtube} YT · ${status.accounts.tiktok} TT</b></div>
              <div class="list-row"><span class="grow">Tareas</span>
                <b>${status.jobs_running} en marcha · ${status.jobs_pending} en espera</b></div>
            </div>
            <p class="muted tiny" style="margin-top:16px;line-height:1.6">
              Tus datos:<br><span class="mono">${escapeHtml(config.data_dir)}</span>
            </p>
          </div>

          <div class="card">
            <div class="card-head"><h3>Qué hace Kevil</h3></div>
            <ul class="muted small" style="margin:0;padding-left:18px;line-height:1.9">
              <li><b style="color:var(--text)">Clips:</b> corta tus vídeos y directos y los
                publica en TikTok y YouTube Shorts a tu mejor hora.</li>
              <li><b style="color:var(--text)">Estudio:</b> subes un vídeo y te devuelve
                títulos, descripción, etiquetas y miniaturas.</li>
              <li><b style="color:var(--text)">Coach:</b> tu ritmo real, avisos si te
                retrasas e ideas comprobadas en YouTube.</li>
            </ul>
          </div>
        </div>
      </div>`;

    const abrir = {
      ia: () => editarIA(ctx.reload),
      sesion: () => editarSesion(ctx.reload),
      disco: () => editarDisco(valores, disco, ctx.reload),
      youtube: () => editarYouTube(valores, yt, ctx.reload),
      tiktok: () => editarTikTok(valores, tt, ctx.reload),
      colores: () => editarColores(marca, ctx.reload),
      motor: () => editarMotor(valores, ctx.reload),
    };
    root.querySelectorAll('[data-abrir]').forEach((boton) => {
      boton.onclick = () => abrir[boton.dataset.abrir]();
    });

    root.querySelector('[data-guardar-canal]').onclick = async () => {
      try {
        await api.put('/api/settings', {
          channel_topic: root.querySelector('#ch-topic').value.trim(),
          channel_language: root.querySelector('#ch-lang').value,
          target_uploads_per_week: Number(root.querySelector('#ch-week').value),
        });
        toast('Guardado');
      } catch (error) { toastError(error); }
    };

    activarProblemas(root, ctx.reload);
    activarSegundoPlano(root, ctx.reload);

    // #ajustes?seccion=ia o =youtube abre directamente esa parte
    const seccion = new URLSearchParams(location.hash.split('?')[1] || '').get('seccion');
    if (seccion === 'ia') abrir.ia();
    else if (seccion === 'youtube') abrir.sesion();
  },
};
