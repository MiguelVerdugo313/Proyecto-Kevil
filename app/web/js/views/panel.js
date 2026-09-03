// Panel: el resumen de todo lo que está pasando.

import { api } from '../lib/api.js';
import { emptyState, escapeHtml, fmt, jobPill } from '../lib/ui.js';

function statCard(label, value, hint, warn = false) {
  return `<div class="stat ${warn ? 'warn' : ''}">
    <div class="label">${escapeHtml(label)}</div>
    <div class="value">${value}</div>
    <div class="hint">${escapeHtml(hint)}</div>
  </div>`;
}

function healthRing(value) {
  const circumference = 2 * Math.PI * 20;
  const offset = circumference * (1 - value / 100);
  const color = value >= 70 ? 'var(--accent)' : value >= 45 ? 'var(--amber)' : 'var(--red)';
  return `<svg width="52" height="52" viewBox="0 0 52 52" style="flex:none">
    <circle cx="26" cy="26" r="20" fill="none" stroke="var(--surface-3)" stroke-width="5"/>
    <circle cx="26" cy="26" r="20" fill="none" stroke="${color}" stroke-width="5"
      stroke-linecap="round" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"
      transform="rotate(-90 26 26)"/>
    <text x="26" y="30" text-anchor="middle" font-size="14" font-weight="700" fill="var(--text)">${value}</text>
  </svg>`;
}

function accountCard(account) {
  return `<div class="list-row">
    ${healthRing(account.health)}
    <div class="grow" style="min-width:0">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
        <strong>${escapeHtml(account.name)}</strong>
        <span class="pill ${account.using_history ? 'ok' : ''}">${account.using_history ? 'aprendiendo de tu historial' : 'patrón base'}</span>
      </div>
      <div class="muted small" style="margin-top:4px">
        ${fmt.number(account.followers)} seguidores · ${account.maturity} ·
        ${account.published_7d} publicados esta semana · ${account.scheduled} en cola
      </div>
      <div class="small" style="margin-top:7px;display:flex;gap:6px;flex-wrap:wrap">
        ${account.best_hours.map((hour) => `<span class="pill violet">${escapeHtml(hour.label)}</span>`).join('')}
      </div>
    </div>
    <div class="right nowrap">
      <div class="muted tiny">recomendado</div>
      <strong>${account.recommended_per_day}/día</strong>
    </div>
  </div>`;
}

export default {
  title: 'Panel',
  subtitle: 'Todo lo que está pasando ahora mismo',
  refreshMs: 8000,

  actions: [
    {
      label: 'Importar vídeo',
      variant: 'primary',
      onClick: () => { location.hash = '#videos'; setTimeout(() => document.querySelector('[data-import]')?.click(), 250); },
    },
  ],

  async render(root) {
    const data = await api.dashboard();
    const counters = data.counters;

    const noAccounts = data.accounts.length === 0 && counters.channels === 0;

    root.innerHTML = `
      ${noAccounts ? `
      <div class="card" style="background:var(--accent-soft);border-color:var(--line-strong)">
        <div class="card-head"><h3>Bienvenido a Kevil Studio 👋</h3></div>
        <p class="muted" style="line-height:1.7;max-width:720px">
          Kevil corta tus vídeos y directos en clips verticales, los publica en TikTok y en
          YouTube Shorts a la mejor hora, y te prepara las subidas de tu canal. Todo en tu ordenador.
        </p>
        <div class="grid cols-3" style="margin-top:18px">
          <div class="stat"><div class="label">Paso 1</div><div class="value" style="font-size:16px">Conecta tu canal</div>
            <div class="hint">Pega la URL de tu canal de YouTube</div></div>
          <div class="stat"><div class="label">Paso 2</div><div class="value" style="font-size:16px">Elige el flujo</div>
            <div class="hint">Cómo se corta, se edita y se publica</div></div>
          <div class="stat"><div class="label">Paso 3</div><div class="value" style="font-size:16px">Conecta los destinos</div>
            <div class="hint">TikTok y/o YouTube Shorts, o modo simulación</div></div>
        </div>
        <div style="margin-top:18px"><a class="btn primary" href="#cuentas">Empezar por las cuentas</a></div>
      </div>` : ''}

      <div class="grid cols-4">
        ${statCard('Clips por revisar', counters.clips_ready, `${counters.clips} generados en total`)}
        ${statCard('Programados', counters.scheduled, 'a la espera de su hora')}
        ${statCard('Publicados (7 días)', counters.published_7d, `${counters.channels} canal(es) vigilados`)}
        ${statCard('Vistas (7 días)', fmt.number(counters.views_week), counters.failed ? `${counters.failed} publicación(es) con error` : 'todo en orden', counters.failed > 0)}
      </div>

      <div class="grid side">
        <div style="display:flex;flex-direction:column;gap:20px">
          <div class="card">
            <div class="card-head">
              <h3>Próximas publicaciones</h3>
              <a class="btn sm ghost" href="#agenda">Ver la agenda</a>
            </div>
            ${data.upcoming.length ? `<div class="list">${data.upcoming.map((post) => `
              <div class="list-row">
                <div class="avatar">${escapeHtml((post.account_name || '?').slice(0, 1).toUpperCase())}</div>
                <div class="grow" style="min-width:0">
                  <strong style="display:block;font-size:13px">${escapeHtml(post.clip_title || 'Clip')}</strong>
                  <span class="muted small">@${escapeHtml(post.account_handle || post.account_name)} · ${escapeHtml(post.slot_reason || '')}</span>
                </div>
                <div class="right nowrap">
                  <div class="small">${fmt.date(post.scheduled_at)}</div>
                  <div class="muted tiny">${fmt.relative(post.scheduled_at)}</div>
                </div>
              </div>`).join('')}</div>`
              : emptyState('🗓️', 'Nada programado todavía', 'Cuando apruebes clips aparecerán aquí con su hora.')}
          </div>

          <div class="card">
            <div class="card-head">
              <h3>Clips esperando tu visto bueno</h3>
              <a class="btn sm ghost" href="#clips">Ver todos</a>
            </div>
            ${data.review.length ? `<div class="clip-grid compact">${data.review.slice(0, 8).map((clip) => `
              <div class="clip" data-clip="${clip.id}">
                <div class="thumb">
                  ${clip.has_thumb ? `<img src="/api/clips/${clip.id}/thumb" alt="">` : '<span style="font-size:26px">🎬</span>'}
                  <div class="score">${Math.round(clip.score * 100)}</div>
                  <div class="dur">${fmt.duration(clip.duration_s)}</div>
                </div>
                <div class="body">
                  <strong>${escapeHtml(clip.title)}</strong>
                  <span class="src">${escapeHtml(clip.video_title)}</span>
                </div>
              </div>`).join('')}</div>`
              : emptyState('✂️', 'Sin clips pendientes', 'Importa un vídeo o espera a que se procesen los que hay en cola.')}
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:20px">
          <div class="card">
            <div class="card-head"><h3>Tus cuentas</h3><a class="btn sm ghost" href="#cuentas">Gestionar</a></div>
            ${data.accounts.length ? `<div class="list">${data.accounts.map(accountCard).join('')}</div>`
              : emptyState('◍', 'Sin cuentas conectadas', 'Conecta TikTok o tu canal de YouTube para publicar automáticamente.')}
          </div>

          <div class="card">
            <div class="card-head"><h3>Actividad</h3></div>
            <div id="feed">${data.events.map((event) => `
              <div class="event ${escapeHtml(event.level)}">
                <span class="mark"></span>
                <div class="grow">${escapeHtml(event.message)}</div>
                <time>${fmt.time(event.created_at)}</time>
              </div>`).join('') || '<div class="muted small">Sin actividad todavía.</div>'}
            </div>
          </div>

          ${data.jobs.length ? `<div class="card">
            <div class="card-head"><h3>Tareas en marcha</h3></div>
            ${data.jobs.map((job) => `
              <div style="margin-bottom:13px">
                <div style="display:flex;justify-content:space-between;gap:10px;margin-bottom:6px">
                  <span class="small">${escapeHtml(job.message || job.kind)}</span>
                  ${jobPill(job.status)}
                </div>
                <div class="bar"><i style="width:${Math.round(job.progress * 100)}%"></i></div>
              </div>`).join('')}
          </div>` : ''}
        </div>
      </div>`;

    root.querySelectorAll('[data-clip]').forEach((node) => {
      node.onclick = () => { location.hash = '#clips'; };
    });
  },

  async onRefresh(root) {
    try {
      const data = await api.dashboard();
      const feed = root.querySelector('#feed');
      if (feed) {
        feed.innerHTML = data.events.map((event) => `
          <div class="event ${escapeHtml(event.level)}">
            <span class="mark"></span>
            <div class="grow">${escapeHtml(event.message)}</div>
            <time>${fmt.time(event.created_at)}</time>
          </div>`).join('');
      }
    } catch (error) {
      void error;
    }
  },
};
