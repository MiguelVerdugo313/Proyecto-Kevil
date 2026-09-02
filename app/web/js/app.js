// Arranque, navegación y latido de la interfaz.

import { api } from './lib/api.js';
import { escapeHtml, fmt, toastError } from './lib/ui.js';

import panel from './views/panel.js';
import cuentas from './views/cuentas.js';
import videos from './views/videos.js';
import clips from './views/clips.js';
import flujos from './views/flujos.js';
import agenda from './views/agenda.js';
import analitica from './views/analitica.js';
import ajustes from './views/ajustes.js';

const VIEWS = { panel, cuentas, videos, clips, flujos, agenda, analitica, ajustes };

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

/* ------------------------------------------------------------------ inicio */
window.addEventListener('hashchange', navigate);
window.kevilFmt = fmt;   // cómodo para depurar desde la consola
navigate();
heartbeat();
setInterval(heartbeat, 4000);
