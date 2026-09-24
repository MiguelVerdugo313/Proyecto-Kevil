// Arranque, navegación y latido de la interfaz.

import { api } from './lib/api.js';
import { usarSesionYouTube } from './lib/ayuda.js';
import { activarVentanitas } from './lib/graficas.js';
import { escapeHtml, fmt, toast, toastError } from './lib/ui.js';

import panel from './views/panel.js';
import estudio from './views/estudio.js';
import coach from './views/coach.js';
import comunidad from './views/comunidad.js';
import cuentas from './views/cuentas.js';
import videos from './views/videos.js';
import clips from './views/clips.js';
import flujos from './views/flujos.js';
import agenda from './views/agenda.js';
import analitica from './views/analitica.js';
import ajustes from './views/ajustes.js';

const VIEWS = { panel, estudio, coach, comunidad, cuentas, videos, clips, flujos, agenda, analitica, ajustes };

const viewRoot = document.getElementById('view');
const titleNode = document.getElementById('page-title');
const subtitleNode = document.getElementById('page-subtitle');
const actionsNode = document.getElementById('page-actions');

let current = null;
let refreshTimer = null;

/* ------------------------------------------------------------------- rutas */
function currentRoute() {
  const name = (location.hash || '#panel').slice(1).split('?')[0];
  return VIEWS[name] ? name : 'panel';
}

async function navigate() {
  // una ventana abierta no se queda encima al cambiar de pantalla
  const ventana = document.getElementById('modal-root');
  if (!ventana.hidden) { ventana.hidden = true; ventana.innerHTML = ''; }
  const name = currentRoute();
  const view = VIEWS[name];
  current = { name, view };

  document.querySelectorAll('.nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.view === name);
  });

  titleNode.textContent = view.title;
  subtitleNode.textContent = view.subtitle || '';
  actionsNode.innerHTML = '';

  const actions = typeof view.actions === 'function' ? view.actions() : (view.actions || []);
  actions.forEach((action, index) => {
    const button = document.createElement('button');
    button.className = `btn ${action.variant || ''}`;
    button.textContent = action.label;
    button.dataset.index = index;
    button.onclick = async () => {
      try { await action.onClick(); } catch (error) { toastError(error); }
    };
    actionsNode.appendChild(button);
  });

  viewRoot.innerHTML = '<div class="grid cols-3"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>';
  try {
    await view.render(viewRoot, { reload: navigate });
    revelar(viewRoot);
  } catch (error) {
    viewRoot.innerHTML = `<div class="card"><h3 style="color:var(--red)">Algo ha fallado</h3>
      <p class="muted small" style="margin-top:8px">${escapeHtml(error.message || error)}</p></div>`;
  }

  clearInterval(refreshTimer);
  if (view.refreshMs && view.onRefresh) {
    refreshTimer = setInterval(() => {
      if (document.getElementById('modal-root').hidden) {
        view.onRefresh(viewRoot).catch(() => {});
      }
    }, view.refreshMs);
  }
}

/* -------------------------------------------------------- latido del motor */
async function heartbeat() {
  try {
    const [status, jobs] = await Promise.all([
      api.status(),
      api.jobs('?limit=12'),
    ]);

    const badge = document.getElementById('badge-clips');
    badge.hidden = !status.clips_ready;
    badge.textContent = status.clips_ready;

    const avisos = await api.get('/api/notifications?limit=1&only_unread=true');
    const campana = document.getElementById('bell-count');
    campana.hidden = !avisos.unread;
    campana.textContent = avisos.unread > 9 ? '9+' : avisos.unread;
    const badgeComunidad = document.getElementById('badge-comunidad');
    badgeComunidad.hidden = !status.comunidad_toca;
    badgeComunidad.textContent = status.comunidad_toca;
    const badgeCoach = document.getElementById('badge-coach');
    badgeCoach.hidden = !avisos.unread;
    badgeCoach.textContent = avisos.unread;

    pintarMotor(Boolean(status.paused));

    const active = jobs.filter((job) => job.status === 'running'
      || (job.status === 'pending' && (!job.run_at || new Date(job.run_at) <= new Date())));
    const body = document.getElementById('worker-body');
    const latido = document.getElementById('motor-latido');
    const motor = status.motor || {};
    if (status.paused) {
      latido.className = 'latido pausa';
      body.innerHTML = `<div class="small" style="line-height:1.55">
          <b>En pausa.</b> Nada pesado en marcha: el ordenador es tuyo.
          <div class="muted tiny" style="margin-top:5px">${status.jobs_pending
            ? `${status.jobs_pending} tarea(s) esperando · las publicaciones siguen saliendo a su hora`
            : 'Las publicaciones programadas siguen saliendo a su hora'}</div>
        </div>`;
    } else if (active.length) {
      latido.className = 'latido trabajando';
      body.innerHTML = active.slice(0, 3).map((job) => `
        <div class="worker-job">
          <b>${escapeHtml(job.message || job.kind)}</b>
          <div class="bar"><i style="width:${Math.round((job.progress || 0) * 100)}%"></i></div>
        </div>`).join('') + proximosHtml(motor, true);
    } else {
      latido.className = 'latido esperando';
      body.innerHTML = `<div class="small" style="font-weight:500">Al día, esperando lo siguiente</div>
        ${proximosHtml(motor, false)}`;
    }

    const problems = [];
    if (!status.ffmpeg) problems.push('falta ffmpeg');
    if (status.dry_run) problems.push('modo simulación');
    const tone = !status.ffmpeg ? 'bad' : (status.dry_run ? 'warn' : '');
    document.getElementById('status-line').innerHTML =
      `<span class="dot ${tone}"></span> v${status.version} · ${status.disk_free_gb} GB libres` +
      (problems.length ? ` · ${escapeHtml(problems.join(' · '))}` : '');
  } catch {
    document.getElementById('status-line').innerHTML =
      '<span class="dot bad"></span> sin conexión con el servidor';
  }
}

/* -------------------------------------------- qué viene después (motor) */
// «Sin tareas activas» parecía que el motor estaba parado. Ahora dice cuándo
// vuelve a mirar tus canales, cuándo sale lo siguiente y qué está esperando.
function enCuanto(iso) {
  if (!iso) return '';
  const segundos = Math.round((new Date(iso) - new Date()) / 1000);
  if (segundos <= 45) return 'ahora';
  const minutos = Math.round(segundos / 60);
  if (minutos < 60) return `en ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `en ${horas} h${minutos % 60 ? ` ${minutos % 60} min` : ''}`;
  return fmt.date(iso, { weekday: 'short', hour: 'numeric', minute: '2-digit', hour12: true });
}

function proximosHtml(motor, compacto) {
  const filas = [];
  const sinVigilar = motor.sin_vigilar || [];
  if (motor.proxima_revision) {
    filas.push(`<div class="proximo"><span>Revisa tu canal</span><b>${enCuanto(motor.proxima_revision)}</b></div>`);
  } else if (!compacto && sinVigilar.length) {
    filas.push(`<div class="proximo-titulo">«${escapeHtml(sinVigilar[0].nombre)}» está conectado pero no se vigila.
      <a href="#cuentas" style="color:var(--accent-2)">Vigilarlo</a> para sacar clips.</div>`);
  } else if (!compacto && !motor.canales) {
    filas.push('<div class="proximo-titulo">Conecta un canal en <a href="#cuentas" style="color:var(--accent-2)">Cuentas</a> para que busque vídeos solo.</div>');
  }
  if (!compacto && motor.canal_con_error) {
    filas.push(`<div class="proximo-titulo" style="color:var(--amber)">No pudo leer «${escapeHtml(motor.canal_con_error)}» la última vez:
      <a href="#cuentas" style="color:var(--accent-2)">ver</a>.</div>`);
  }
  if (motor.proxima_publicacion) {
    filas.push(`<div class="proximo"><span>Publica</span><b>${enCuanto(motor.proxima_publicacion)}</b></div>`
      + (compacto ? '' : `<div class="proximo-titulo">${escapeHtml((motor.proxima_publicacion_titulo || '').slice(0, 60))}</div>`));
  }
  if (motor.reintento) {
    filas.push(`<div class="proximo"><span>${motor.esperando} reintento(s)</span><b>${enCuanto(motor.reintento)}</b></div>`);
  }
  return filas.length ? `<div style="display:flex;flex-direction:column;gap:6px;${compacto ? 'margin-top:4px' : ''}">${filas.join('')}</div>` : '';
}

/* --------------------------------------------- aparecer al hacer scroll */
const observador = 'IntersectionObserver' in window ? new IntersectionObserver((entradas) => {
  entradas.forEach((entrada) => {
    if (!entrada.isIntersecting) return;
    entrada.target.classList.add('visible');
    observador.unobserve(entrada.target);
  });
}, { rootMargin: '0px 0px -40px 0px', threshold: 0.05 }) : null;

function revelar(raiz) {
  if (!observador) return;
  const piezas = raiz.querySelectorAll(':scope > .card, :scope > .grid > *, :scope > .grid > div > .card, .stat, .clip, .idea, .problema, .paso');
  piezas.forEach((pieza, i) => {
    if (pieza.classList.contains('reveal')) return;
    pieza.classList.add('reveal');
    pieza.style.transitionDelay = `${Math.min(i, 8) * 45}ms`;
    observador.observe(pieza);
  });
}

// La aurora se para cuando la ventana no se ve: ni un ciclo de más mientras juegas
document.addEventListener('visibilitychange', () => {
  document.body.classList.toggle('quieto', document.hidden);
});

/* -------------------------------------------- paleta de comandos (Ctrl K) */
const sinTildes = (texto) => texto.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

function comandos() {
  const ir = (hash) => () => { location.hash = hash; };
  const vistas = Object.entries(VIEWS).map(([nombre, vista]) => ({
    grupo: 'Ir a', texto: vista.title, pista: vista.subtitle || '', icono: `i-${nombre}`, hacer: ir(`#${nombre}`),
  }));
  const acciones = [
    { texto: 'Importar un vídeo de YouTube', pista: 'pega el enlace', icono: 'i-videos',
      hacer: () => { location.hash = '#videos'; setTimeout(() => document.querySelector('[data-import]')?.click(), 300); } },
    { texto: 'Subir un vídeo desde mi PC', pista: 'para su kit y sus clips', icono: 'i-estudio', hacer: ir('#estudio?subir=1') },
    { texto: motorEnPausa ? 'Reanudar el motor' : 'Pausar el motor', pista: 'descargas y renders', icono: 'i-panel',
      hacer: () => document.getElementById('motor-boton').click() },
    { texto: 'Liberar espacio en el disco', pista: 'descartados, publicados, temporales', icono: 'i-clips', hacer: ir('#clips?liberar=1') },
    { texto: 'Reintentar todas las tareas con problemas', pista: '', icono: 'i-panel',
      hacer: async () => {
        const r = await api.post('/api/problemas/reintentar', {});
        toast(r.reintentados ? `${r.reintentados} tarea(s) de nuevo en la cola` : 'No había nada que reintentar');
      } },
    { texto: 'Usar mi sesión de YouTube', pista: 'cuando pide «no soy un robot»', icono: 'i-videos',
      hacer: () => usarSesionYouTube() },
    { texto: 'Ideas para la pestaña Comunidad', pista: 'encuestas, avisos, carruseles', icono: 'i-comunidad', hacer: ir('#comunidad') },
    { texto: 'Publicar también en YouTube Shorts', pista: 'dónde sale cada clip', icono: 'i-cuentas', hacer: ir('#cuentas') },
    { texto: 'Añadir una clave de IA', pista: 'Groq, Gemini, OpenRouter…', icono: 'i-ajustes', hacer: ir('#ajustes?seccion=ia') },
    { texto: 'Cambiar entre claro y oscuro', pista: '', icono: 'i-tema', hacer: () => botonTema.click() },
  ].map((a) => ({ ...a, grupo: 'Hacer' }));
  return [...acciones, ...vistas];
}

const cmdk = document.getElementById('cmdk');
const cmdkTexto = document.getElementById('cmdk-texto');
const cmdkLista = document.getElementById('cmdk-lista');
let cmdkItems = [];
let cmdkActivo = 0;

function pintarComandos() {
  const q = sinTildes(cmdkTexto.value.trim());
  cmdkItems = comandos().filter((c) => !q || sinTildes(`${c.texto} ${c.pista}`).includes(q));
  cmdkActivo = Math.min(cmdkActivo, Math.max(0, cmdkItems.length - 1));
  if (!cmdkItems.length) {
    cmdkLista.innerHTML = '<div class="cmdk-vacio">Nada por aquí. Prueba con otra palabra.</div>';
    return;
  }
  let grupo = '';
  cmdkLista.innerHTML = cmdkItems.map((c, i) => {
    const cabecera = c.grupo !== grupo ? `<div class="cmdk-grupo">${escapeHtml(c.grupo)}</div>` : '';
    grupo = c.grupo;
    return `${cabecera}<div class="cmdk-item ${i === cmdkActivo ? 'activo' : ''}" data-i="${i}">
      <svg class="ico"><use href="#${c.icono}"/></svg>${escapeHtml(c.texto)}<em>${escapeHtml(c.pista)}</em></div>`;
  }).join('');
  cmdkLista.querySelector('.activo')?.scrollIntoView({ block: 'nearest' });
}

function abrirComandos() {
  cmdk.hidden = false;
  cmdkTexto.value = '';
  cmdkActivo = 0;
  pintarComandos();
  setTimeout(() => cmdkTexto.focus(), 10);
}
function cerrarComandos() { cmdk.hidden = true; }

async function ejecutar(i) {
  const c = cmdkItems[i];
  if (!c) return;
  cerrarComandos();
  try { await c.hacer(); } catch (error) { toastError(error); }
}

document.getElementById('abrir-comandos').onclick = abrirComandos;
cmdkTexto.addEventListener('input', () => { cmdkActivo = 0; pintarComandos(); });
cmdkLista.addEventListener('click', (e) => {
  const fila = e.target.closest('[data-i]');
  if (fila) ejecutar(Number(fila.dataset.i));
});
cmdkLista.addEventListener('mousemove', (e) => {
  const fila = e.target.closest('[data-i]');
  if (fila && Number(fila.dataset.i) !== cmdkActivo) { cmdkActivo = Number(fila.dataset.i); pintarComandos(); }
});
cmdk.addEventListener('click', (e) => { if (e.target === cmdk) cerrarComandos(); });
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    if (cmdk.hidden) abrirComandos(); else cerrarComandos();
    return;
  }
  if (cmdk.hidden) return;
  if (e.key === 'Escape') { cerrarComandos(); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); cmdkActivo = (cmdkActivo + 1) % Math.max(1, cmdkItems.length); pintarComandos(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); cmdkActivo = (cmdkActivo - 1 + cmdkItems.length) % Math.max(1, cmdkItems.length); pintarComandos(); }
  else if (e.key === 'Enter') { e.preventDefault(); ejecutar(cmdkActivo); }
});

/* ----------------------------------------------------- pausar el motor */
let motorEnPausa = false;

function pintarMotor(enPausa) {
  motorEnPausa = enPausa;
  const caja = document.getElementById('worker-box');
  const boton = document.getElementById('motor-boton');
  caja.classList.toggle('en-pausa', enPausa);
  boton.textContent = enPausa ? '▶ Reanudar' : '⏸ Pausar';
  boton.title = enPausa
    ? 'Volver a bajar vídeos y montar clips'
    : 'Parar descargas y renders para usar el ordenador para otra cosa';
}

document.getElementById('motor-boton').addEventListener('click', async (evento) => {
  const boton = evento.currentTarget;
  boton.disabled = true;
  try {
    if (motorEnPausa) {
      await api.post('/api/motor/reanudar', {});
      pintarMotor(false);
      toast('Motor en marcha otra vez');
    } else {
      const estado = await api.post('/api/motor/pausa', {});
      pintarMotor(true);
      toast(estado.stopped
        ? `En pausa: ${estado.stopped} proceso(s) parados al momento`
        : 'En pausa: no se empezará nada pesado');
    }
    heartbeat();
  } catch (error) {
    toastError(error);
  } finally {
    boton.disabled = false;
  }
});

/* ------------------------------------------------- los colores de tu marca */
export function aplicarColores(tema) {
  const raiz = document.documentElement;
  if (!tema || !tema.custom) {
    ['--accent', '--accent-ink', '--accent-soft', '--accent-2'].forEach((v) => raiz.style.removeProperty(v));
    return;
  }
  const claro = raiz.dataset.theme === 'light';
  const acento = claro ? tema.accent_light : tema.accent_dark;
  const acento2 = claro ? tema.accent2_light : tema.accent2_dark;
  raiz.style.setProperty('--accent', acento);
  raiz.style.setProperty('--accent-2', acento2 || acento);
  raiz.style.setProperty('--accent-ink', claro ? tema.ink_light : tema.ink_dark);
  // versión translúcida del acento para los fondos suaves
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(acento.slice(i, i + 2), 16));
  raiz.style.setProperty('--accent-soft', `rgba(${r}, ${g}, ${b}, .13)`);
}

let temaMarca = null;

export async function cargarColores() {
  try {
    const datos = await api.get('/api/branding');
    temaMarca = datos.theme;
  } catch { temaMarca = null; }
  aplicarColores(temaMarca);
}

/* --------------------------------------------------------------- el tema */
const botonTema = document.getElementById('theme');

function aplicarTema(tema) {
  if (tema === 'light') document.documentElement.dataset.theme = 'light';
  else delete document.documentElement.dataset.theme;
  botonTema.title = tema === 'light' ? 'Cambiar a modo oscuro' : 'Cambiar a modo claro';
  aplicarColores(temaMarca);
  try { localStorage.setItem('kevil-tema', tema); } catch { /* modo privado */ }
}

botonTema.onclick = () => {
  aplicarTema(document.documentElement.dataset.theme === 'light' ? 'dark' : 'light');
};

aplicarTema(document.documentElement.dataset.theme === 'light' ? 'light' : 'dark');

/* ------------------------------------------------------- campana de avisos */
let avisosAbiertos = false;

async function pintarAvisos() {
  const caja = document.getElementById('avisos');
  const datos = await api.get('/api/notifications?limit=20');
  caja.innerHTML = `
    <header>
      <strong style="font-size:13px">Avisos</strong>
      ${datos.unread ? '<button class="btn sm ghost" id="leer-todo">Marcar leídos</button>' : ''}
    </header>
    ${datos.items.length ? datos.items.map((item) => `
      <div class="aviso ${escapeHtml(item.level)} ${item.read ? '' : 'no-leido'}">
        <span class="mark"></span>
        <div class="grow">
          <strong>${escapeHtml(item.title)}</strong>
          ${item.body ? `<p>${escapeHtml(item.body)}</p>` : ''}
          <div class="muted tiny" style="margin-top:5px">${fmt.relative(item.created_at)}</div>
          ${item.action_url ? `<a href="${escapeHtml(item.action_url)}">${escapeHtml(item.action_label || 'Ver')} →</a>` : ''}
        </div>
      </div>`).join('')
      : '<div class="aviso"><div class="muted small">Nada por ahora. Aquí te avisaré de tu ritmo de publicación y de las ideas nuevas.</div></div>'}`;

  const leerTodo = caja.querySelector('#leer-todo');
  if (leerTodo) {
    leerTodo.onclick = async () => {
      await api.post('/api/notifications/read');
      await pintarAvisos();
      heartbeat();
    };
  }
}

document.getElementById('bell').onclick = async () => {
  const caja = document.getElementById('avisos');
  avisosAbiertos = !avisosAbiertos;
  caja.hidden = !avisosAbiertos;
  if (avisosAbiertos) await pintarAvisos().catch(() => {});
};

document.addEventListener('click', (event) => {
  if (!avisosAbiertos) return;
  if (event.target.closest('#avisos') || event.target.closest('#bell')) return;
  avisosAbiertos = false;
  document.getElementById('avisos').hidden = true;
});

/* ------------------------------------------------------------------ inicio */
window.addEventListener('hashchange', navigate);
window.kevilFmt = fmt;   // cómodo para depurar desde la consola
activarVentanitas();
cargarColores();
// La zona horaria del equipo, por si Python no la pudo leer (Windows a veces no
// la da en el formato que hace falta). Con eso las horas buenas son las tuyas.
try {
  const zona = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (zona) api.post('/api/zona-horaria', { zona }).catch(() => {});
} catch { /* navegador sin Intl */ }
navigate();
heartbeat();
setInterval(heartbeat, 4000);
