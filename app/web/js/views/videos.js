// Vídeos originales: importar, descargar y cortar.

import { api } from '../lib/api.js';
import {
  confirmDialog, debounce, emptyState, escapeHtml, fmt, modal,
  statusPill, toast, toastError,
} from '../lib/ui.js';

let flows = [];
let filters = { status: '', q: '' };
let reloadView = () => location.reload();

function importDialog(reload) {
  modal({
    title: 'Importar un vídeo o un directo',
    body: `
      <div class="field">
        <label>Enlace de YouTube</label>
        <input type="text" id="v-url" placeholder="https://www.youtube.com/watch?v=…">
        <span class="help">Sirve para vídeos normales y para directos que ya han terminado.</span>
      </div>
      <div class="field">
        <label>Flujo</label>
        <select id="v-flow">
          ${flows.map((flow) => `<option value="${flow.id}" ${flow.is_default ? 'selected' : ''}>${escapeHtml(flow.icon)} ${escapeHtml(flow.name)}</option>`).join('')}
        </select>
      </div>`,
    actions: [
      { label: 'Cancelar' },
      {
        label: 'Importar y procesar',
        variant: 'primary',
        onClick: async (root) => {
          const url = root.querySelector('#v-url').value.trim();
          if (!url) { toast('Pega el enlace del vídeo', 'warn'); return false; }
          const button = root.querySelector('[data-action="1"]');
          button.disabled = true;
          button.textContent = 'Leyendo…';
          try {
            const video = await api.post('/api/videos/import', {
              url, flow_id: Number(root.querySelector('#v-flow').value) || null, start_now: true,
            });
            toast(`«${video.title}» en cola de descarga`);
            reload();
          } finally {
            button.disabled = false;
            button.textContent = 'Importar y procesar';
          }
        },
      },
    ],
  });
}

function processDialog(video, reload) {
  modal({
    title: `Volver a cortar «${video.title.slice(0, 50)}»`,
    body: `
      <p class="muted small" style="line-height:1.6">
        Se generarán clips nuevos con el flujo que elijas. Los clips en borrador anteriores se sustituyen;
        los ya programados o publicados no se tocan.
      </p>
      <div class="field"><label>Flujo</label>
        <select id="p-flow">${flows.map((flow) =>
          `<option value="${flow.id}" ${flow.is_default ? 'selected' : ''}>${escapeHtml(flow.icon)} ${escapeHtml(flow.name)}</option>`).join('')}</select>
      </div>`,
    actions: [
      { label: 'Cancelar' },
      {
        label: 'Cortar de nuevo',
        variant: 'primary',
        onClick: async (root) => {
          await api.post(`/api/videos/${video.id}/process`, {
            flow_id: Number(root.querySelector('#p-flow').value) || null,
          });
          toast('Cortando… los clips aparecerán en unos minutos');
          reload();
        },
      },
    ],
  });
}

export default {
  title: 'Vídeos',
  subtitle: 'Los originales de YouTube que alimentan tus clips',
  refreshMs: 10000,

  actions: [
    { label: '+ Importar vídeo', variant: 'primary', onClick: () => importDialog(reloadView) },
  ],

  async render(root, ctx) {
    reloadView = ctx.reload;
    const query = new URLSearchParams();
    if (filters.status) query.set('status', filters.status);
    if (filters.q) query.set('q', filters.q);

    const [videos, flowList] = await Promise.all([
      api.videos(query.toString() ? `?${query}` : ''),
      api.flows(),
    ]);
    flows = flowList;

    root.innerHTML = `
      <div class="card">
        <div class="card-head">
          <div style="display:flex;gap:9px;align-items:center;flex-wrap:wrap">
            <input type="text" id="q" placeholder="Buscar por título…" value="${escapeHtml(filters.q)}" style="width:230px">
            <select id="f-status" style="width:180px">
              <option value="">Todos los estados</option>
              <option value="discovered">Detectados</option>
              <option value="queued">En cola</option>
              <option value="ready">Descargados</option>
              <option value="done">Procesados</option>
              <option value="error">Con error</option>
            </select>
          </div>
          <button class="btn" data-import>+ Importar vídeo</button>
        </div>

        ${videos.length ? `
        <table class="table">
          <thead><tr><th>Vídeo</th><th>Duración</th><th>Clips</th><th>Estado</th><th></th></tr></thead>
          <tbody>${videos.map((video) => `
            <tr>
              <td style="max-width:420px">
                <div style="display:flex;gap:11px;align-items:center">
                  ${video.thumbnail_url ? `<img src="${escapeHtml(video.thumbnail_url)}" style="width:74px;height:42px;object-fit:cover;border-radius:8px;flex:none" alt="">`
                    : '<div class="avatar" style="width:74px;height:42px;border-radius:8px">▶</div>'}
                  <div style="min-width:0">
                    <strong style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(video.title)}</strong>
                    <span class="muted tiny">
                      ${video.was_live ? '<span class="pill pink" style="margin-right:5px">directo</span>' : ''}
                      ${escapeHtml(video.source_name || 'importado')} ·
                      ${video.published_at ? fmt.day(video.published_at) : 'sin fecha'}
                      ${video.transcript_words ? ` · ${fmt.number(video.transcript_words)} palabras transcritas` : ''}
                    </span>
                    ${video.error ? `<div class="tiny" style="color:var(--red)">${escapeHtml(video.error.slice(0, 110))}</div>` : ''}
                  </div>
                </div>
              </td>
              <td class="small nowrap">${fmt.duration(video.duration_s)}</td>
              <td class="small">${video.clips_count || '—'}</td>
              <td>${statusPill(video.status)}${video.downloaded ? '' : '<span class="pill" style="margin-left:5px">sin archivo</span>'}</td>
              <td><div class="actions">
                ${video.downloaded
                  ? `<button class="btn sm" data-process="${video.id}">Cortar</button>`
                  : `<button class="btn sm" data-ingest="${video.id}">Descargar</button>`}
                ${video.clips_count ? `<a class="btn sm ghost" href="#clips?video=${video.id}">Ver clips</a>` : ''}
                <button class="btn sm danger" data-del="${video.id}">Borrar</button>
              </div></td>
            </tr>`).join('')}
          </tbody>
        </table>` : emptyState('▶', 'Todavía no hay vídeos',
          'Conecta un canal en «Cuentas» o importa un enlace suelto de YouTube.',
          '<button class="btn primary" data-import>Importar un vídeo</button>')}
      </div>`;

    root.querySelector('#f-status').value = filters.status;
    root.querySelector('#f-status').onchange = (event) => {
      filters.status = event.target.value;
      ctx.reload();
    };
    root.querySelector('#q').oninput = debounce((event) => {
      filters.q = event.target.value.trim();
      ctx.reload();
    }, 400);

    root.querySelectorAll('[data-import]').forEach((b) => { b.onclick = () => importDialog(ctx.reload); });

    root.querySelectorAll('[data-ingest]').forEach((button) => {
      button.onclick = async () => {
        button.disabled = true;
        try {
          await api.post(`/api/videos/${button.dataset.ingest}/ingest`, {});
          toast('Descarga en cola');
          ctx.reload();
        } catch (error) { toastError(error); button.disabled = false; }
      };
    });

    root.querySelectorAll('[data-process]').forEach((button) => {
      button.onclick = () => processDialog(videos.find((v) => v.id === Number(button.dataset.process)), ctx.reload);
    });

    root.querySelectorAll('[data-del]').forEach((button) => {
      button.onclick = async () => {
        if (!await confirmDialog('Borrar vídeo', 'Se borrarán también sus clips. El archivo original se conserva en el disco.', 'Borrar')) return;
        await api.del(`/api/videos/${button.dataset.del}`);
        toast('Vídeo borrado');
        ctx.reload();
      };
    });
  },

  async onRefresh(root) {
    const rows = root.querySelectorAll('tbody tr');
    if (!rows.length) return;
    const videos = await api.videos(filters.status ? `?status=${filters.status}` : '');
    const busy = videos.some((v) => ['queued', 'downloading', 'processing'].includes(v.status));
    if (busy) reloadView();
  },
};
