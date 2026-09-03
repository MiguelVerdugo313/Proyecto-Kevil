// Ajustes: lo justo a la vista, y todo lo demás detrás de «Editar».

import { api } from '../lib/api.js';
import { cargarColores } from '../app.js';
import {
  confirmDialog, escapeHtml, jobPill, modal, toast, toastError,
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
function editarIA(valores, ia, reload) {
  const proveedor = (clave) => {
    const meta = ia.providers[clave];
    return `
      <div class="bloque">
        <div class="bloque-head">
          <div>
            <strong style="font-size:14px">${escapeHtml(meta.label)}</strong>
            <p class="muted tiny" style="margin-top:4px">
              Clave gratuita en
              <a href="${escapeHtml(meta.keys_url)}" target="_blank" rel="noreferrer"
                 style="color:var(--accent)">${escapeHtml(meta.keys_url.replace('https://', ''))}</a>
            </p>
          </div>
          ${meta.configured ? '<span class="pill ok">lista</span>' : '<span class="pill">vacía</span>'}
        </div>
        <div class="field"><label>Clave de API</label>
          <input type="password" id="${clave}-key" value="${escapeHtml(valores[`${clave}_api_key`] || '')}"
            placeholder="${meta.configured ? '••••••••' : 'pega aquí tu clave'}"></div>
        <details style="margin-top:12px">
          <summary class="muted tiny" style="cursor:pointer">Elegir modelos</summary>
          <div class="form-grid" style="margin-top:12px">
            <div class="field"><label>Texto</label>
              <input type="text" id="${clave}-text" list="${clave}-lt"
                value="${escapeHtml(valores[`${clave}_text_model`] || '')}"
                placeholder="${escapeHtml(meta.text_models[0])}">
              <datalist id="${clave}-lt">${meta.text_models.map((m) => `<option value="${escapeHtml(m)}">`).join('')}</datalist></div>
            <div class="field"><label>Imagen</label>
              <input type="text" id="${clave}-img" list="${clave}-li"
                value="${escapeHtml(valores[`${clave}_image_model`] || '')}"
                placeholder="${escapeHtml(meta.image_models[0])}">
              <datalist id="${clave}-li">${meta.image_models.map((m) => `<option value="${escapeHtml(m)}">`).join('')}</datalist></div>
          </div>
        </details>
      </div>`;
  };

  modal({
    title: 'Inteligencia artificial',
    wide: true,
    body: `
      <p class="muted small" style="line-height:1.7">
        Sirve para los títulos, la descripción, los hashtags y las ideas.
        <b>Puedes poner las dos claves</b>: si a una se le acaban los créditos o te limita
        por peticiones, Kevil pasa a la otra automáticamente. Sin ninguna, todo se
        genera en local.
      </p>
      <div class="grid cols-2" style="gap:14px">
        ${proveedor('openrouter')}
        ${proveedor('nvidia')}
      </div>
      <div class="field">
        <label>Cuál se intenta primero</label>
        <select id="ia-primary">
          ${Object.entries(ia.providers).map(([clave, meta]) =>
            `<option value="${clave}" ${valores.ai_primary === clave ? 'selected' : ''}>${escapeHtml(meta.label)}</option>`).join('')}
        </select>
        <span class="help">El otro queda de reserva.</span>
      </div>
      <div id="ia-resultado" class="small"></div>`,
    actions: [
      { label: 'Probar las claves', onClick: async (root) => {
        const salida = root.querySelector('#ia-resultado');
        salida.innerHTML = '<span class="muted">Probando…</span>';
        try {
          await guardarIA(root);
          const resultado = await api.post('/api/ai/test');
          salida.innerHTML = resultado.results.map((r) => `
            <div style="margin-top:6px;color:${r.ok ? 'var(--green)' : 'var(--red)'}">
              ${r.ok ? '✓' : '×'} ${escapeHtml(r.label)}: ${escapeHtml(r.ok ? (r.model || 'responde') : r.detail)}
            </div>`).join('');
        } catch (error) {
          salida.innerHTML = `<span style="color:var(--red)">${escapeHtml(error.message)}</span>`;
        }
        return false;   // el diálogo se queda abierto
      } },
      { label: 'Guardar', variant: 'primary', onClick: async (root) => {
        await guardarIA(root);
        toast('Claves guardadas');
        reload();
      } },
    ],
  });
}

async function guardarIA(root) {
  const limpio = (valor) => (valor === '••••••••' ? undefined : valor);
  await api.put('/api/settings', {
    openrouter_api_key: limpio(root.querySelector('#openrouter-key').value.trim()),
    openrouter_text_model: root.querySelector('#openrouter-text').value.trim(),
    openrouter_image_model: root.querySelector('#openrouter-img').value.trim(),
    nvidia_api_key: limpio(root.querySelector('#nvidia-key').value.trim()),
    nvidia_text_model: root.querySelector('#nvidia-text').value.trim(),
    nvidia_image_model: root.querySelector('#nvidia-img').value.trim(),
    ai_primary: root.querySelector('#ia-primary').value,
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
          Si Google te enseña un aviso de «aplicación no verificada», es normal:
          la aplicación es tuya y se ejecuta en tu ordenador. Pulsa
          «Configuración avanzada» → «Ir a Kevil Studio».
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
        Google exige que cada programa se registre con ellos una vez. Son
        <b>tres pasos y cinco minutos</b>, y no hay que volver a hacerlo nunca más.
      </p>

      <div class="guia">
        ${paso(1, 'Crea el proyecto y activa la API',
          `Abre <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noreferrer">crear proyecto</a>,
           ponle el nombre que quieras y créalo. Después entra en
           <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noreferrer">YouTube Data API v3</a>
           y pulsa <b>Habilitar</b>.`)}
        ${paso(2, 'Crea las credenciales',
          `En <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer">Credenciales</a>:
           <b>Crear credenciales → ID de cliente de OAuth</b>, tipo
           <b>Aplicación web</b>. En «URI de redireccionamiento autorizados»
           pega esta dirección:`)}
        ${campoCopiable('URL de retorno', yt.redirect_uri, 'yt-redirect')}
        ${paso(3, 'Descarga el archivo y pégalo aquí',
          `Al crearla, Google te ofrece descargar un archivo
           <span class="mono">client_secret_….json</span>. Ábrelo con el Bloc de notas,
           copia <b>todo</b> y pégalo abajo. Yo saco de ahí lo que hace falta.`)}
      </div>

      <div class="field full" style="margin-top:6px">
        <label>Pega aquí el archivo de Google</label>
        <textarea id="yt-json" rows="5" class="mono"
          placeholder='{"web":{"client_id":"…","client_secret":"…"}}'></textarea>
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
        ${paso(1, 'Crea la aplicación',
          `Entra en <a href="https://developers.tiktok.com/apps" target="_blank" rel="noreferrer">developers.tiktok.com/apps</a>,
           inicia sesión con tu cuenta de TikTok y pulsa <b>Connect an app</b>.`)}
        ${paso(2, 'Pide los productos y pega la URL de retorno',
          `Añade <b>Login Kit</b> y <b>Content Posting API</b>. En «Redirect URI»
           pega esta dirección exacta:`)}
        ${campoCopiable('URL de retorno', tt.redirect_uri, 'tt-redirect')}
        ${paso(3, 'Copia las dos claves y pégalas aquí',
          `En la pantalla de tu app verás <b>Client key</b> y <b>Client secret</b>.
           Pégalas abajo, una en cada línea.`)}
      </div>

      <div class="field full" style="margin-top:6px">
        <label>Pega aquí las dos claves</label>
        <textarea id="tt-pegado" rows="3" class="mono"
          placeholder="Client key: awxxxxxxxxxxxx&#10;Client secret: xxxxxxxxxxxxxxxx"></textarea>
      </div>

      <p class="muted tiny" style="margin-top:12px">
        TikTok revisa las aplicaciones antes de dejar publicar. Mientras tanto
        Kevil sigue funcionando en simulación y no pierdes nada de lo programado.
      </p>

      <details style="margin-top:12px">
        <summary class="muted small">O ponlas a mano</summary>
        <div class="form-grid" style="margin-top:12px">
          <div class="field full"><label>Client key</label>
            <input type="text" id="tt-key" value="${escapeHtml(valores.tiktok_client_key || '')}" placeholder="aw…"></div>
          <div class="field full"><label>Client secret</label>
            <input type="password" id="tt-secret" value="${escapeHtml(valores.tiktok_client_secret || '')}" placeholder="••••••••"></div>
        </div>
      </details>`,
    wide: true,
    onOpen: activarCopiar,
    actions: [
      { label: 'Cancelar' },
      { label: 'Guardar y conectar', variant: 'primary', onClick: async (root) => {
        const pegado = root.querySelector('#tt-pegado').value.trim();
        if (pegado) {
          await api.post('/api/credentials/tiktok', { text: pegado });
        } else {
          const clave = root.querySelector('#tt-key').value.trim();
          const secreto = root.querySelector('#tt-secret').value.trim();
          if (!clave || !secreto) {
            toastError('Pega las dos claves, o rellena los campos de abajo.');
            return false;
          }
          await api.put('/api/settings', {
            tiktok_client_key: clave,
            tiktok_client_secret: secreto === '••••••••' ? undefined : secreto,
          });
        }
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
    const [config, status, jobs, ia, yt, tt, marca] = await Promise.all([
      api.settings(), api.status(), api.jobs('?limit=12'),
      api.get('/api/ai/status'), api.get('/api/youtube/config'),
      api.get('/api/tiktok/config'), api.get('/api/branding'),
    ]);
    const valores = config.settings;
    const fallidas = jobs.filter((job) => job.status === 'failed');

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
                descripcion: ia.enabled
                  ? `${ia.active.map((p) => escapeHtml(p.label)).join(' + ')}${ia.has_backup ? ' · con respaldo automático' : ''}`
                  : 'Sin clave: los textos se generan en local',
                estado: ia.enabled ? (ia.has_backup ? 'con respaldo' : 'activa') : 'sin clave',
                tono: ia.enabled ? 'ok' : '',
                accion: 'ia',
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

          ${fallidas.length ? `<div class="card">
            <div class="card-head">
              <h3>Tareas con problemas</h3>
              <button class="btn sm ghost" data-clear>Limpiar historial</button>
            </div>
            <table class="table">
              <tbody>${fallidas.map((job) => `
                <tr>
                  <td><strong class="small">${escapeHtml(job.message || job.kind)}</strong>
                    <div class="tiny" style="color:var(--red)">${escapeHtml((job.error || '').split('\n')[0].slice(0, 140))}</div></td>
                  <td style="width:110px">${jobPill(job.status)}</td>
                  <td class="right" style="width:110px">
                    <button class="btn sm" data-retry="${job.id}">Reintentar</button></td>
                </tr>`).join('')}</tbody>
            </table>
          </div>` : ''}
        </div>

        <div style="display:flex;flex-direction:column;gap:22px">
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
      ia: () => editarIA(valores, ia, ctx.reload),
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

    const limpiar = root.querySelector('[data-clear]');
    if (limpiar) {
      limpiar.onclick = async () => {
        if (!await confirmDialog('Limpiar historial',
          'Se borran las tareas terminadas, fallidas y canceladas.', 'Limpiar')) return;
        await api.del('/api/jobs/finished');
        toast('Historial limpio');
        ctx.reload();
      };
    }

    root.querySelectorAll('[data-retry]').forEach((boton) => {
      boton.onclick = async () => {
        await api.post(`/api/jobs/${boton.dataset.retry}/retry`);
        toast('Tarea reencolada');
        ctx.reload();
      };
    });
  },
};
