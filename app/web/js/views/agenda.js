// Agenda: calendario semanal de publicaciones y vista previa de huecos.

import { api } from '../lib/api.js';
import {
  confirmDialog, emptyState, escapeHtml, fmt, heatColor, modal,
  statusPill, toast, toastError,
} from '../lib/ui.js';

let weekOffset = 0;
let accountId = null;
let reloadView = () => location.reload();

function startOfWeek(offset = 0) {
  const date = new Date();
  const weekday = (date.getDay() + 6) % 7;           // lunes = 0
  date.setHours(0, 0, 0, 0);
  date.setDate(date.getDate() - weekday + offset * 7);
  return date;
}

function postDialog(post, reload) {
  modal({
    title: post.clip_title || `Publicación #${post.id}`,
    body: `
      <div class="grid" style="grid-template-columns:minmax(0,260px) minmax(0,1fr);gap:18px">
        <video class="preview" controls playsinline src="/api/clips/${post.clip_id}/file"
          poster="/api/clips/${post.clip_id}/thumb"></video>
        <div style="display:flex;flex-direction:column;gap:13px">
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            ${statusPill(post.status)}
            <span class="pill violet">@${escapeHtml(post.account_handle || post.account_name)}</span>
            ${post.slot_score ? `<span class="pill info">franja ${Math.round(post.slot_score * 100)}%</span>` : ''}
          </div>
          <p class="muted tiny">${escapeHtml(post.slot_reason || '')}</p>
          <div class="field"><label>Fecha y hora</label>
            <input type="datetime-local" id="p-when" value="${fmt.toLocalInput(post.scheduled_at)}"></div>
          <div class="field"><label>Descripción</label>
            <textarea id="p-caption" style="min-height:130px">${escapeHtml(post.caption)}</textarea></div>
          ${post.error ? `<p class="small" style="color:var(--red)">${escapeHtml(post.error.slice(0, 300))}</p>` : ''}
          ${post.share_url ? `<a class="btn sm" href="${escapeHtml(post.share_url)}" target="_blank" rel="noreferrer">Ver en TikTok</a>` : ''}
        </div>
      </div>`,
    wide: true,
    actions: post.status === 'published'
      ? [{ label: 'Cerrar' }]
      : [
        { label: 'Cancelar publicación', variant: 'danger', onClick: async () => {
          await api.del(`/api/posts/${post.id}`);
          toast('Publicación cancelada');
          reload();
        } },
        { label: 'Publicar ahora', onClick: async () => {
          if (!await confirmDialog('Publicar ahora', 'Se subirá a TikTok inmediatamente.', 'Publicar')) return false;
          await api.post(`/api/posts/${post.id}/publish-now`);
          toast('Subiendo a TikTok…');
          reload();
        } },
        { label: 'Guardar', variant: 'primary', onClick: async (root) => {
          await api.patch(`/api/posts/${post.id}`, {
            scheduled_at: fmt.fromLocalInput(root.querySelector('#p-when').value),
            caption: root.querySelector('#p-caption').value,
          });
          toast('Publicación actualizada');
          reload();
        } },
      ],
  });
}

async function previewSlots() {
  if (!accountId) { toast('Conecta antes una cuenta de TikTok', 'warn'); return; }
  const slots = await api.post('/api/schedule/plan', { account_id: accountId, count: 10, spread_days: 10 });
  modal({
    title: 'Próximos huecos recomendados',
    body: slots.length ? `<div class="list">${slots.map((slot) => `
      <div class="list-row">
        <div class="grow">
          <strong>${escapeHtml(new Date(slot.utc).toLocaleString('es-ES', { weekday: 'long', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }))}</strong>
          <div class="muted tiny">${escapeHtml(slot.reason)}</div>
        </div>
        <div style="width:120px"><div class="bar"><i style="width:${Math.round(slot.score * 100)}%"></i></div></div>
        <b class="small" style="width:40px;text-align:right">${Math.round(slot.score * 100)}%</b>
      </div>`).join('')}</div>`
      : '<p class="muted">No hay huecos libres con las reglas actuales. Prueba a ampliar el máximo diario o los días permitidos.</p>',
    actions: [{ label: 'Cerrar' }],
  });
}

export default {
  title: 'Agenda',
  subtitle: 'Cuándo sale cada clip y por qué a esa hora',
  refreshMs: 20000,

  actions: [
    { label: 'Ver huecos recomendados', onClick: () => previewSlots().catch(toastError) },
  ],

  async render(root, ctx) {
    reloadView = ctx.reload;
    const [posts, accounts] = await Promise.all([
      api.posts('?days=45&include_past=true'),
      api.accounts('tiktok'),
    ]);
    if (!accountId && accounts.length) accountId = accounts[0].id;

    const heat = accountId ? await api.get(`/api/schedule/heatmap?account_id=${accountId}`) : null;

    const weekStart = startOfWeek(weekOffset);
    const days = Array.from({ length: 7 }, (_, index) => {
      const date = new Date(weekStart);
      date.setDate(date.getDate() + index);
      return date;
    });
    const today = new Date().toDateString();

    const postsByDay = new Map();
    posts.forEach((post) => {
      const key = new Date(post.scheduled_at).toDateString();
      if (!postsByDay.has(key)) postsByDay.set(key, []);
      postsByDay.get(key).push(post);
    });

    root.innerHTML = `
      <div class="card">
        <div class="card-head">
          <div style="display:flex;gap:8px;align-items:center">
            <button class="btn sm ghost" data-week="-1">‹</button>
            <strong>${escapeHtml(weekStart.toLocaleDateString('es-ES', { day: '2-digit', month: 'long' }))}
              — ${escapeHtml(days[6].toLocaleDateString('es-ES', { day: '2-digit', month: 'long', year: 'numeric' }))}</strong>
            <button class="btn sm ghost" data-week="1">›</button>
            ${weekOffset !== 0 ? '<button class="btn sm ghost" data-week="0">Hoy</button>' : ''}
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            ${accounts.length > 1 ? `<select id="acc" style="width:190px">${accounts.map((account) =>
              `<option value="${account.id}" ${account.id === accountId ? 'selected' : ''}>@${escapeHtml(account.handle || account.display_name)}</option>`).join('')}</select>` : ''}
            <span class="muted small">${posts.filter((p) => p.status === 'scheduled').length} programados</span>
          </div>
        </div>

        <div class="calendar">
          ${days.map((date) => {
            const list = (postsByDay.get(date.toDateString()) || [])
              .sort((a, b) => new Date(a.scheduled_at) - new Date(b.scheduled_at));
            return `<div class="cal-day ${date.toDateString() === today ? 'today' : ''}">
              <div class="d">
                <span>${escapeHtml(date.toLocaleDateString('es-ES', { weekday: 'short' }))}</span>
                <b>${date.getDate()}</b>
              </div>
              ${list.map((post) => `
                <div class="cal-post ${escapeHtml(post.status)}" data-post="${post.id}">
                  <b>${fmt.time(post.scheduled_at)}</b>
                  <span>${escapeHtml(post.clip_title || 'Clip')}</span>
                </div>`).join('') || '<span class="muted tiny">—</span>'}
            </div>`;
          }).join('')}
        </div>
      </div>

      ${heat ? `<div class="card">
        <div class="card-head">
          <div>
            <h3>Mapa de mejores horas</h3>
            <p class="muted small" style="margin-top:4px">
              ${heat.using_history
                ? `Aprendido de tus ${heat.samples} publicaciones con datos.`
                : 'Todavía con el patrón base: en cuanto haya historial propio, se ajusta solo.'}
              Zona horaria: ${escapeHtml(heat.timezone)}.
            </p>
          </div>
          <a class="btn sm ghost" href="#cuentas">Editar estrategia</a>
        </div>
        <div class="heat">
          <span class="lbl"></span>
          ${Array.from({ length: 24 }, (_, hour) => `<span class="hour">${hour % 3 === 0 ? hour : ''}</span>`).join('')}
          ${heat.days.map((day, index) => `
            <span class="lbl">${escapeHtml(day.slice(0, 3))}</span>
            ${heat.matrix[index].map((value, hour) => `
              <span class="cell" title="${escapeHtml(day)} ${hour}:00 · ${Math.round(value * 100)}%"
                style="background:${heatColor(value)}"></span>`).join('')}`).join('')}
        </div>
      </div>` : ''}

      <div class="card">
        <div class="card-head"><h3>Historial reciente</h3></div>
        ${posts.length ? `<table class="table">
          <thead><tr><th>Clip</th><th>Cuenta</th><th>Momento</th><th>Estado</th><th>Resultado</th></tr></thead>
          <tbody>${posts.slice().reverse().slice(0, 25).map((post) => `
            <tr data-post="${post.id}" style="cursor:pointer">
              <td><strong>${escapeHtml(post.clip_title || 'Clip')}</strong>
                <div class="muted tiny">${escapeHtml(post.slot_reason || '')}</div></td>
              <td class="small">@${escapeHtml(post.account_handle || post.account_name)}</td>
              <td class="small nowrap">${fmt.date(post.scheduled_at)}<div class="muted tiny">${fmt.relative(post.scheduled_at)}</div></td>
              <td>${statusPill(post.status)}</td>
              <td class="small">${post.metrics?.views ? `${fmt.number(post.metrics.views)} vistas` : '—'}</td>
            </tr>`).join('')}</tbody>
        </table>` : emptyState('🗓️', 'Sin publicaciones todavía',
          'Aprueba clips en la pantalla «Clips» y aparecerán aquí con su hora asignada.')}
      </div>`;

    root.querySelectorAll('[data-week]').forEach((button) => {
      button.onclick = () => {
        const value = Number(button.dataset.week);
        weekOffset = value === 0 ? 0 : weekOffset + value;
        ctx.reload();
      };
    });

    const selector = root.querySelector('#acc');
    if (selector) selector.onchange = () => { accountId = Number(selector.value); ctx.reload(); };

    root.querySelectorAll('[data-post]').forEach((node) => {
      node.onclick = () => {
        const post = posts.find((p) => p.id === Number(node.dataset.post));
        if (post) postDialog(post, ctx.reload);
      };
    });
  },

  async onRefresh() {
    const publishing = await api.posts('?status=publishing&days=2');
    if (publishing.length) reloadView();
  },
};
