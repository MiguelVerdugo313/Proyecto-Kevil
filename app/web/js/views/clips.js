// Clips: revisar, retocar, aprobar y programar.

import { api } from '../lib/api.js';
import {
  confirmDialog, emptyState, escapeHtml, fmt, modal,
  statusPill, toast, toastError,
} from '../lib/ui.js';

let filters = { status: '', video: null };
let accounts = [];
let reloadView = () => location.reload();

const FILTERS = [
  { value: '', label: 'Todos' },
  { value: 'rendered', label: 'Por revisar' },
  { value: 'draft', label: 'Borradores' },
  { value: 'scheduled', label: 'Programados' },
  { value: 'published', label: 'Publicados' },
  { value: 'failed', label: 'Con error' },
  { value: 'rejected', label: 'Descartados' },
];

/* ------------------------------------------------------- ficha de un clip */
async function openClip(clipId, reload) {
  const clip = await api.get(`/api/clips/${clipId}`);
  const reframe = (clip.render_config || {}).reframe || {};
  const accountOptions = accounts.map((account) =>
    `<option value="${account.id}">@${escapeHtml(account.handle || account.display_name)}</option>`).join('');

  modal({
    title: clip.title || `Clip #${clip.id}`,
    wide: true,
    body: `
      <div class="grid" style="grid-template-columns:minmax(0,300px) minmax(0,1fr);gap:20px">
        <div>
          ${clip.has_file
            ? `<video class="preview" controls playsinline poster="${clip.has_thumb ? `/api/clips/${clip.id}/thumb` : ''}"
                 src="/api/clips/${clip.id}/file"></video>`
            : `<div class="empty" style="padding:40px 16px">
                 <div class="big">🎬</div><p class="muted small">Todavía sin renderizar</p>
               </div>`}
          <div style="display:flex;gap:6px;margin-top:10px;flex-wrap:wrap">
            ${statusPill(clip.status)}
            <span class="pill">${fmt.duration(clip.duration_s)}</span>
            <span class="pill info">gancho ${Math.round(clip.score * 100)}%</span>
          </div>
          <p class="muted tiny" style="margin-top:9px;line-height:1.55">
            Del original: ${fmt.duration(clip.start_s)} → ${fmt.duration(clip.end_s)}<br>
            ${escapeHtml(clip.reason || '')}
          </p>
          ${clip.error ? `<p class="small" style="color:var(--red);margin-top:8px">${escapeHtml(clip.error.slice(0, 260))}</p>` : ''}
        </div>

        <div style="display:flex;flex-direction:column;gap:14px">
          <div class="field"><label>Título interno</label>
            <input type="text" id="c-title" value="${escapeHtml(clip.title)}"></div>
          <div class="field"><label>Gancho (texto sobreimpreso)</label>
            <input type="text" id="c-hook" value="${escapeHtml(clip.hook)}"></div>
          <div class="field"><label>Descripción de TikTok</label>
            <textarea id="c-caption" style="min-height:120px">${escapeHtml(clip.caption)}</textarea></div>

          <div class="form-grid">
            <div class="field"><label>Inicio (s)</label>
              <input type="number" id="c-start" step="0.1" value="${clip.start_s}"></div>
            <div class="field"><label>Fin (s)</label>
              <input type="number" id="c-end" step="0.1" value="${clip.end_s}"></div>
            <div class="field"><label>Encuadre</label>
              <select id="c-mode">
                ${[['blur', 'Fondo desenfocado'], ['crop', 'Recorte completo'], ['smart', 'Recorte con seguimiento'], ['split', 'Arriba + zoom abajo']]
                  .map(([value, label]) => `<option value="${value}" ${(reframe.mode || 'blur') === value ? 'selected' : ''}>${label}</option>`).join('')}
              </select></div>
            <div class="field"><label>Centro horizontal</label>
              <div style="display:flex;align-items:center;gap:10px">
                <input type="range" id="c-focus" min="0" max="1" step="0.01" value="${reframe.focus_x ?? 0.5}"
                  oninput="this.nextElementSibling.textContent=this.value">
                <b class="mono small">${reframe.focus_x ?? 0.5}</b>
              </div></div>
          </div>

          <div class="field">
            <label>Programar en</label>
            <div style="display:flex;gap:8px">
              <select id="c-account" style="flex:1">${accountOptions || '<option value="">Sin cuentas de TikTok</option>'}</select>
              <input type="datetime-local" id="c-when" style="flex:1">
            </div>
            <span class="help">Deja la fecha vacía para que el motor elija la mejor hora automáticamente.</span>
          </div>
        </div>
      </div>`,
    actions: [
      { label: 'Descartar', variant: 'danger', onClick: async () => {
        await api.post(`/api/clips/${clip.id}/reject`);
        toast('Clip descartado');
        reload();
      } },
      { label: 'Guardar y renderizar', onClick: async (root) => {
        await saveClip(root, clip);
        await api.post(`/api/clips/${clip.id}/render`);
        toast('Renderizando de nuevo…');
        reload();
      } },
      { label: 'Aprobar y programar', variant: 'primary', onClick: async (root) => {
        await saveClip(root, clip);
        const when = root.querySelector('#c-when').value;
        const accountId = Number(root.querySelector('#c-account').value) || null;
        if (!accountId) { toast('Conecta antes una cuenta de TikTok', 'warn'); return false; }
        await api.post(`/api/clips/${clip.id}/approve`, {
          account_id: accountId,
          scheduled_at: when ? fmt.fromLocalInput(when) : null,
        });
        toast('Clip programado');
        reload();
      } },
    ],
  });
}

async function saveClip(root, clip) {
  const payload = {
    title: root.querySelector('#c-title').value,
    hook: root.querySelector('#c-hook').value,
    caption: root.querySelector('#c-caption').value,
    start_s: Number(root.querySelector('#c-start').value),
    end_s: Number(root.querySelector('#c-end').value),
    reframe: {
      mode: root.querySelector('#c-mode').value,
      focus_x: Number(root.querySelector('#c-focus').value),
    },
  };
  const reframe = (clip.render_config || {}).reframe || {};
  const untouched = payload.start_s === clip.start_s
    && payload.end_s === clip.end_s
    && payload.reframe.mode === (reframe.mode || 'blur')
    && payload.reframe.focus_x === (reframe.focus_x ?? 0.5);
  if (untouched) delete payload.reframe;
  await api.patch(`/api/clips/${clip.id}`, payload);
}

/* ------------------------------------------------------------------ vista */
export default {
  title: 'Clips',
  subtitle: 'Revisa, retoca y aprueba antes de publicar',
  refreshMs: 12000,

  actions: [
    { label: 'Aprobar todos los revisables', onClick: async () => {
      const pending = await api.clips('?status=rendered&limit=200');
      if (!pending.length) { toast('No hay clips pendientes', 'warn'); return; }
      if (!await confirmDialog('Aprobar todo',
        `Se programarán ${pending.length} clip(s) en las mejores horas disponibles.`, 'Programar todos')) return;
      let ok = 0;
      for (const clip of pending) {
        try { await api.post(`/api/clips/${clip.id}/approve`, {}); ok += 1; } catch { /* seguimos */ }
      }
      toast(`${ok} clip(s) programados`);
      reloadView();
    } },
  ],

  async render(root, ctx) {
    reloadView = ctx.reload;
    const hash = new URLSearchParams((location.hash.split('?')[1] || ''));
    if (hash.get('video')) filters.video = Number(hash.get('video'));

    const query = new URLSearchParams();
    if (filters.status) query.set('status', filters.status);
    if (filters.video) query.set('video_id', filters.video);

    const [clips, accountList] = await Promise.all([
      api.clips(query.toString() ? `?${query}` : ''),
      api.accounts('tiktok'),
    ]);
    accounts = accountList;

    root.innerHTML = `
      <div class="card">
        <div class="card-head">
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            ${FILTERS.map((filter) => `
              <button class="btn sm ${filters.status === filter.value ? 'primary' : 'ghost'}"
                data-filter="${filter.value}">${escapeHtml(filter.label)}</button>`).join('')}
          </div>
          <div style="display:flex;gap:8px;align-items:center">
            ${filters.video ? '<button class="btn sm ghost" data-clear-video>Quitar filtro de vídeo</button>' : ''}
            <span class="muted small">${clips.length} clip(s)</span>
          </div>
        </div>

        ${clips.length ? `<div class="clip-grid">${clips.map((clip) => `
          <div class="clip" data-open="${clip.id}">
            <div class="thumb">
              ${clip.has_thumb ? `<img src="/api/clips/${clip.id}/thumb" alt="" loading="lazy">` : '<span style="font-size:28px">🎬</span>'}
              <div class="play">▶</div>
              <div class="score">${Math.round(clip.score * 100)}</div>
              <div class="dur">${fmt.duration(clip.duration_s)}</div>
            </div>
            <div class="body">
              <strong>${escapeHtml(clip.title || 'Clip')}</strong>
              <span class="src">${escapeHtml(clip.video_title)}</span>
              <div style="display:flex;gap:5px;flex-wrap:wrap">${statusPill(clip.status)}
                ${clip.post ? `<span class="pill violet">${fmt.date(clip.post.scheduled_at)}</span>` : ''}</div>
              <div class="foot">
                ${clip.has_file ? `<a class="btn sm ghost" href="/api/clips/${clip.id}/download" download onclick="event.stopPropagation()">Descargar</a>` : ''}
                <button class="btn sm" data-open="${clip.id}">Abrir</button>
              </div>
            </div>
          </div>`).join('')}</div>`
          : emptyState('✂️', 'Sin clips por aquí',
            'Cuando se procese un vídeo aparecerán aquí sus mejores momentos, ya en vertical.',
            '<a class="btn primary" href="#videos">Ir a Vídeos</a>')}
      </div>`;

    root.querySelectorAll('[data-filter]').forEach((button) => {
      button.onclick = () => { filters.status = button.dataset.filter; ctx.reload(); };
    });
    const clearVideo = root.querySelector('[data-clear-video]');
    if (clearVideo) clearVideo.onclick = () => { filters.video = null; location.hash = '#clips'; ctx.reload(); };

    root.querySelectorAll('[data-open]').forEach((node) => {
      node.onclick = (event) => {
        event.stopPropagation();
        openClip(Number(node.dataset.open), ctx.reload).catch(toastError);
      };
    });
  },

  async onRefresh() {
    const busy = await api.clips('?status=rendering&limit=1');
    if (busy.length) reloadView();
  },
};
