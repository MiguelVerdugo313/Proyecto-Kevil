// Arranque, navegación y latido de la interfaz.

import { api } from './lib/api.js';
import { escapeHtml, fmt, toastError } from './lib/ui.js';

import panel from './views/panel.js';
import estudio from './views/estudio.js';
import coach from './views/coach.js';
import cuentas from './views/cuentas.js';
import videos from './views/videos.js';
import clips from './views/clips.js';
import flujos from './views/flujos.js';
import agenda from './views/agenda.js';
import analitica from './views/analitica.js';
import ajustes from './views/ajustes.js';

const VIEWS = { panel, estudio, coach, cuentas, videos, clips, flujos, agenda, analitica, ajustes };

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
      api.jobs('?limit=6'),
    ]);

    const badge = document.getElementById('badge-clips');
    badge.hidden = !status.clips_ready;
    badge.textContent = status.clips_ready;

    const avisos = await api.get('/api/notifications?limit=1&only_unread=true');
    const campana = document.getElementById('bell-count');
    campana.hidden = !avisos.unread;
    campana.textContent = avisos.unread > 9 ? '9+' : avisos.unread;
    const badgeCoach = document.getElementById('badge-coach');
    badgeCoach.hidden = !avisos.unread;
    badgeCoach.textContent = avisos.unread;

    const active = jobs.filter((job) => job.status === 'running' || job.status === 'pending');
    const body = document.getElementById('worker-body');
    if (!active.length) {
      body.innerHTML = '<div class="muted small">Sin tareas activas</div>';
    } else {
      body.innerHTML = active.slice(0, 4).map((job) => `
        <div class="worker-job">
          <b>${escapeHtml(job.message || job.kind)}</b>
          <div class="bar"><i style="width:${Math.round((job.progress || 0) * 100)}%"></i></div>
        </div>`).join('');
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
  botonTema.textContent = tema === 'light' ? '◑' : '◐';
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
cargarColores();
navigate();
heartbeat();
setInterval(heartbeat, 4000);
