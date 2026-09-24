// Clips: revisar, retocar, aprobar y programar.

import { api } from '../lib/api.js';
import {
  confirmDialog, emptyState, escapeHtml, fmt, modal,
  statusPill, toast, toastError,
} from '../lib/ui.js';

let filters = { status: '', video: null };
let accounts = [];
let reloadView = () => location.reload();
// Modo «elegir para borrar»: los clips marcados se guardan aquí por su id
let eligiendo = false;
const elegidos = new Set();

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
            <span class="pill info">viralidad ${Math.round(clip.score * 100)}</span>
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
                ${[['blur', 'Fondo borroso (recomendado)'], ['crop', 'Recorte completo'], ['smart', 'Recorte con seguimiento'], ['split', 'Arriba + zoom abajo']]
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
            <span class="help" id="c-when-help">Buscando la mejor hora…</span>
          </div>
        </div>
      </div>`,
    actions: [
      { label: 'Borrar', variant: 'danger', onClick: async () => {
        if (!await confirmDialog('Borrar el clip',
          'Se borra el vídeo de tu ordenador y desaparece de la lista. Si estaba programado, esa publicación se cancela.',
          'Borrar')) return false;
        const r = await api.post('/api/clips/delete', { ids: [clip.id] });
        if (r.skipped) { toast('Se está subiendo ahora mismo: espera a que termine', 'warn'); return false; }
        toast(`Clip borrado${r.freed_mb ? ` · ${r.freed_mb} MB liberados` : ''}`);
        reload();
      } },
      { label: 'Descartar', onClick: async () => {
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
        // Si la hora es la que propuso el motor, se manda con su motivo: así
        // sigue siendo «suya» y puede recolocarla si cambia algo.
        const propia = propuesta && when === propuesta.local;
        await api.post(`/api/clips/${clip.id}/approve`, {
          account_id: accountId,
          scheduled_at: when ? fmt.fromLocalInput(when) : null,
          slot_reason: propia ? propuesta.reason : '',
        });
        toast(when ? `Clip programado para el ${fmt.date(fmt.fromLocalInput(when))}` : 'Clip programado a la mejor hora');
        reload();
      } },
    ],
    onOpen: (root) => {
      const cuenta = root.querySelector('#c-account');
      cuenta.addEventListener('change', () => proponer(root, clip));
      proponer(root, clip);
    },
  });
}

// La fecha no se deja vacía: se rellena con la hora que elegiría el motor, que
// se puede cambiar. Así se ve cuándo va a salir antes de aprobarlo.
let propuesta = null;

async function proponer(root, clip) {
  const campo = root.querySelector('#c-when');
  const ayuda = root.querySelector('#c-when-help');
  const accountId = Number(root.querySelector('#c-account').value) || null;
  propuesta = null;
  if (!accountId) {
    ayuda.textContent = 'Conecta una cuenta para que el motor proponga la hora.';
    return;
  }
  const programado = [clip.post].find((p) => p && p.status === 'scheduled' && p.account_id === accountId);
  if (programado) {
    campo.value = fmt.toLocalInput(programado.scheduled_at);
    ayuda.textContent = `Ya estaba programado: ${fmt.date(programado.scheduled_at)}.`;
    return;
  }
  try {
    const datos = await api.get(`/api/clips/${clip.id}/propuesta?account_id=${accountId}`);
    propuesta = { ...datos, local: fmt.toLocalInput(datos.scheduled_at) };
    campo.value = propuesta.local;
    ayuda.innerHTML = `El motor propone el <b>${escapeHtml(fmt.date(datos.scheduled_at, {
      weekday: 'long', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true,
    }))}</b> (${escapeHtml(datos.reason)}). Cámbiala si prefieres otra.`;
  } catch {
    ayuda.textContent = 'Deja la fecha vacía y el motor elegirá la mejor hora al aprobar.';
  }
}

/* ------------------------------------------------------ liberar espacio */
const QUE_SE_BORRA = [
  ['temporales', 'Archivos temporales', 'restos de los renders'],
  ['descartados', 'Clips descartados', 'los que dijiste que no'],
  ['publicados', 'Clips ya publicados', 'ya están en TikTok o en YouTube'],
  ['originales', 'Vídeos originales', 'de los que ya no queda nada por montar'],
  ['huerfanos', 'Archivos sueltos', 'descargas cortadas y restos que no son de nadie'],
];

async function liberarEspacio() {
  const plan = await api.get('/api/storage/free');
  const partes = plan.parts || {};
  modal({
    title: 'Liberar espacio',
    body: `
      <p class="muted small" style="line-height:1.7">
        Se borra <b>sólo lo que ya no hace falta</b>. Los clips por revisar, los
        programados y los que se están montando <b>no se tocan</b>.
      </p>
      <div style="margin-top:14px">
        ${QUE_SE_BORRA.map(([clave, nombre, detalle]) => `
          <div style="display:flex;justify-content:space-between;gap:12px;padding:9px 0;border-bottom:1px solid var(--line)">
            <span><b class="small">${nombre}</b><br><span class="muted tiny">${detalle}</span></span>
            <b class="small nowrap">${fmtMB(partes[clave])}</b>
          </div>`).join('')}
        <div style="display:flex;justify-content:space-between;padding:12px 0 0">
          <b>En total</b><b style="color:var(--accent-2)">${fmtMB(plan.total_mb)}</b>
        </div>
      </div>
      <p class="muted tiny" style="margin-top:14px">
        Ahora mismo Kevil ocupa ${fmtMB(plan.usage?.total_mb)} en tu disco.
      </p>`,
    actions: [
      { label: 'Cancelar' },
      { label: 'Liberar espacio', variant: 'primary', onClick: async () => {
        const r = await api.post('/api/storage/free', {});
        toast(r.freed_mb ? `${fmtMB(r.freed_mb)} liberados` : 'No había nada que borrar');
        reloadView();
      } },
    ],
  });
}

function fmtMB(mb) {
  const n = Number(mb || 0);
  return n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${n.toFixed(n < 10 ? 1 : 0)} MB`;
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
    { label: '🧹 Liberar espacio', onClick: () => liberarEspacio() },
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
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            ${filters.video ? '<button class="btn sm ghost" data-clear-video>Quitar filtro de vídeo</button>' : ''}
            ${filters.status === 'rejected' && clips.length
              ? '<button class="btn sm danger" data-vaciar-descartados>Borrar todos los descartados</button>' : ''}
            ${clips.length ? `<button class="btn sm ${eligiendo ? 'primary' : 'ghost'}" data-elegir>
                ${eligiendo ? 'Terminar' : 'Elegir para borrar'}</button>` : ''}
            <span class="muted small">${clips.length} clip(s)</span>
          </div>
        </div>

        ${eligiendo ? `<div class="barra-borrar">
          <span><b id="n-elegidos">${elegidos.size}</b> elegido(s) · pulsa en los clips que ya no quieras</span>
          <div style="display:flex;gap:8px">
            <button class="btn sm ghost" data-todos>Elegir todos</button>
            <button class="btn sm danger" data-borrar-elegidos ${elegidos.size ? '' : 'disabled'}>Borrar elegidos</button>
          </div>
        </div>` : ''}

        ${clips.length ? `<div class="clip-grid">${clips.map((clip) => `
          <div class="clip ${eligiendo && elegidos.has(clip.id) ? 'elegido' : ''}" data-open="${clip.id}">
            <div class="thumb">
              ${eligiendo ? `<span class="marca-eleccion">${elegidos.has(clip.id) ? '✓' : ''}</span>` : ''}
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
        const id = Number(node.dataset.open);
        if (eligiendo) {
          // eligiendo, pulsar marca o desmarca en vez de abrir la ficha
          if (elegidos.has(id)) elegidos.delete(id); else elegidos.add(id);
          ctx.reload();
          return;
        }
        openClip(id, ctx.reload).catch(toastError);
      };
    });

    const botonElegir = root.querySelector('[data-elegir]');
    if (botonElegir) {
      botonElegir.onclick = () => {
        eligiendo = !eligiendo;
        elegidos.clear();
        ctx.reload();
      };
    }
    const todos = root.querySelector('[data-todos]');
    if (todos) todos.onclick = () => { clips.forEach((c) => elegidos.add(c.id)); ctx.reload(); };

    const borrarElegidos = root.querySelector('[data-borrar-elegidos]');
    if (borrarElegidos) {
      borrarElegidos.onclick = async () => {
        const ids = [...elegidos];
        if (!ids.length) return;
        if (!await confirmDialog('Borrar clips',
          `Se borran ${ids.length} clip(s) de tu ordenador y de la lista. Los que estuvieran programados se cancelan.`,
          `Borrar ${ids.length}`)) return;
        try {
          const r = await api.post('/api/clips/delete', { ids });
          toast(`${r.deleted} clip(s) borrados · ${r.freed_mb} MB liberados`
            + (r.skipped ? ` · ${r.skipped} se estaban subiendo y se han dejado` : ''));
          eligiendo = false;
          elegidos.clear();
          ctx.reload();
        } catch (error) { toastError(error); }
      };
    }

    const vaciar = root.querySelector('[data-vaciar-descartados]');
    if (vaciar) {
      vaciar.onclick = async () => {
        if (!await confirmDialog('Borrar los descartados',
          `Se borran los ${clips.length} clip(s) descartados de tu ordenador y de la lista.`, 'Borrar')) return;
        try {
          const r = await api.post('/api/clips/delete', { status: 'rejected' });
          toast(`${r.deleted} clip(s) borrados · ${r.freed_mb} MB liberados`);
          ctx.reload();
        } catch (error) { toastError(error); }
      };
    }
  },

  async onRefresh() {
    const busy = await api.clips('?status=rendering&limit=1');
    if (busy.length) reloadView();
  },
};
