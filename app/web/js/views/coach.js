// Coach: cada cuánto publicar, cuándo, y sobre qué grabar el próximo vídeo.

import { api } from '../lib/api.js';
import { emptyState, escapeHtml, fmt, toast, toastError } from '../lib/ui.js';

let reloadView = () => location.reload();

const ESTADOS = {
  al_dia: { pill: 'ok', texto: 'Al día' },
  retrasado: { pill: 'warn', texto: 'Te toca publicar' },
  parado: { pill: 'bad', texto: 'Canal parado' },
  sin_datos: { pill: '', texto: 'Sin datos' },
};

function barraRegularidad(valor) {
  if (valor === null || valor === undefined) {
    return '<span class="muted small">aún no hay suficientes vídeos</span>';
  }
  const porcentaje = Math.round(valor * 100);
  const color = valor >= 0.7 ? 'var(--accent)' : valor >= 0.45 ? 'var(--amber)' : 'var(--red)';
  return `
    <div class="bar" style="margin-top:6px"><i style="width:${porcentaje}%;background:${color}"></i></div>
    <div class="muted tiny" style="margin-top:5px">
      ${porcentaje}% — ${valor >= 0.7 ? 'muy constante' : valor >= 0.45 ? 'mejorable' : 'irregular'}
    </div>`;
}

function ideaCard(idea) {
  const evidencia = idea.evidence || {};
  const medido = evidencia.ok;
  const nota = Math.round(idea.score * 100);
  const color = nota >= 60 ? 'ok' : nota >= 35 ? 'warn' : '';

  return `<div class="idea ${idea.status === 'descartada' ? 'off' : ''}" data-idea="${idea.id}">
    <div class="idea-head">
      <div style="min-width:0">
        <strong>${escapeHtml(idea.title)}</strong>
        <div class="muted tiny" style="margin-top:3px">
          buscar: <span class="mono">${escapeHtml(idea.topic)}</span> ·
          ${idea.source === 'ia' ? 'propuesta por IA' : 'sacada de tu canal'}
        </div>
      </div>
      <span class="pill ${color}">${nota}</span>
    </div>

    ${idea.hook ? `<p class="small" style="margin:9px 0 0;line-height:1.6">${escapeHtml(idea.hook)}</p>` : ''}
    ${idea.reason ? `<p class="muted tiny" style="margin:7px 0 0;line-height:1.6">${escapeHtml(idea.reason)}</p>` : ''}

    <div class="idea-datos">
      ${medido ? `
        <div><span class="muted tiny">demanda</span><b>${Math.round(idea.demand * 100)}%</b></div>
        <div><span class="muted tiny">competencia</span><b>${Math.round(idea.competition * 100)}%</b></div>
        <div><span class="muted tiny">visitas típicas</span><b>${fmt.number(evidencia.median_views || 0)}</b></div>`
      : `<div class="muted tiny">Sin datos de demanda${evidencia.error ? ` (${escapeHtml(evidencia.error)})` : ''}</div>`}
    </div>

    ${(evidencia.examples || []).length ? `
      <details class="ejemplos">
        <summary class="muted tiny">Lo que ya existe sobre esto</summary>
        ${evidencia.examples.map((e) => `
          <div class="tiny"><b>${fmt.number(e.views)}</b> · ${escapeHtml(e.title)}
            <span class="muted">— ${escapeHtml(e.channel)}</span></div>`).join('')}
      </details>` : ''}

    <div class="idea-acciones">
      <button class="btn sm ghost" data-copiar-idea="${idea.id}">Copiar título</button>
      ${idea.status === 'guardada'
        ? '<span class="pill ok">guardada</span>'
        : `<button class="btn sm" data-guardar-idea="${idea.id}">Guardar</button>`}
      ${idea.status === 'descartada'
        ? `<button class="btn sm ghost" data-restaurar-idea="${idea.id}">Recuperar</button>`
        : `<button class="btn sm ghost" data-descartar-idea="${idea.id}">Descartar</button>`}
    </div>
  </div>`;
}

export default {
  title: 'Coach',
  subtitle: 'Cada cuánto publicar, cuándo y sobre qué',
  refreshMs: 15000,

  actions: [
    { label: 'Buscar ideas', variant: 'primary', onClick: async () => {
      await api.post('/api/ideas/generate', { count: 6, validate_demand: true });
      toast('Buscando ideas… tarda un poco porque se comprueba la demanda real');
    } },
    { label: 'Revisar ahora', onClick: async () => {
      await api.post('/api/coach/check');
      toast('Revisando tu canal…');
    } },
  ],

  async render(root, ctx) {
    reloadView = ctx.reload;
    const [data, ideas] = await Promise.all([api.get('/api/coach'), api.get('/api/ideas?limit=30')]);
    const stats = data.stats;
    const estado = ESTADOS[data.state] || ESTADOS.sin_datos;

    root.innerHTML = `
      <div class="grid side">
        <div style="display:flex;flex-direction:column;gap:20px">
          <div class="card" style="border-color:${data.state === 'parado' ? 'rgba(255,107,129,.35)' : 'var(--line)'}">
            <div class="card-head">
              <div>
                <h3>${escapeHtml(data.headline)}</h3>
                <p class="muted small" style="margin-top:6px;line-height:1.7;max-width:640px">
                  ${escapeHtml(data.detail)}
                </p>
              </div>
              <span class="pill ${estado.pill}">${escapeHtml(estado.texto)}</span>
            </div>

            <div class="grid cols-4" style="margin-top:8px">
              <div class="stat">
                <div class="label">Tu ritmo real</div>
                <div class="value">${stats.cadence_days ? `${stats.cadence_days} d` : '—'}</div>
                <div class="hint">entre vídeo y vídeo</div>
              </div>
              <div class="stat">
                <div class="label">Tu objetivo</div>
                <div class="value">${data.target_days} d</div>
                <div class="hint">${data.target_per_week} vídeos/semana</div>
              </div>
              <div class="stat">
                <div class="label">Último vídeo</div>
                <div class="value">${stats.days_since_last !== null ? `${Math.round(stats.days_since_last)} d` : '—'}</div>
                <div class="hint">${stats.last_upload_at ? fmt.day(stats.last_upload_at) : 'sin datos'}</div>
              </div>
              <div class="stat">
                <div class="label">Próxima subida</div>
                <div class="value" style="font-size:19px">${
                  !data.next_upload_at ? '—' : (data.overdue_days > 0 ? 'Ya' : fmt.day(data.next_upload_at))}</div>
                <div class="hint">${
                  !data.next_upload_at ? 'define tu objetivo'
                    : (data.overdue_days > 0
                      ? `te tocaba hace ${Math.round(data.overdue_days)} día(s)`
                      : fmt.relative(data.next_upload_at))}</div>
              </div>
            </div>

            ${data.actions.length ? `<div class="acciones">
              ${data.actions.map((a) => `<div class="accion">→ ${escapeHtml(a)}</div>`).join('')}
            </div>` : ''}
          </div>

          <div class="card">
            <div class="card-head">
              <div>
                <h3>Ideas para tus próximos vídeos</h3>
                <p class="muted small" style="margin-top:4px">
                  Se proponen con IA y se comprueban buscándolas en YouTube: demanda real y competencia.
                </p>
              </div>
              <button class="btn sm primary" data-ideas>Buscar ideas</button>
            </div>
            ${ideas.length
              ? `<div class="ideas">${ideas.map(ideaCard).join('')}</div>`
              : emptyState('💡', 'Todavía no hay ideas',
                  'Pulsa «Buscar ideas» y Kevil propondrá temas concretos según lo que ya publicas, comprobando si tienen público.')}
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:20px">
          <div class="card">
            <div class="card-head"><h3>Regularidad</h3></div>
            ${barraRegularidad(stats.regularity)}
            <div class="list" style="margin-top:14px">
              <div class="list-row"><span class="grow">Vídeos conocidos</span><b>${stats.known_uploads}</b></div>
              <div class="list-row"><span class="grow">Últimos 30 días</span><b>${stats.uploads_30d}</b></div>
              <div class="list-row"><span class="grow">Últimos 90 días</span><b>${stats.uploads_90d}</b></div>
              <div class="list-row"><span class="grow">Visitas típicas</span><b>${fmt.number(stats.median_views)}</b></div>
            </div>
          </div>

          <div class="card">
            <div class="card-head">
              <h3>Mejores franjas</h3>
              <span class="muted tiny">${escapeHtml(stats.slots_source || '')}</span>
            </div>
            ${(stats.best_slots || []).length ? `<div class="list">
              ${stats.best_slots.map((slot) => `
                <div class="list-row">
                  <span class="grow">${escapeHtml(slot.label)}</span>
                  ${slot.videos
                    ? `<span class="muted tiny">${slot.videos} vídeo(s) · ${fmt.number(slot.avg_views)} de media</span>`
                    : '<span class="muted tiny">referencia</span>'}
                </div>`).join('')}
            </div>` : '<p class="muted small">Aún no hay datos suficientes.</p>'}
          </div>

          ${(stats.top_videos || []).length ? `<div class="card">
            <div class="card-head"><h3>Lo que mejor te funciona</h3></div>
            <div class="list">
              ${stats.top_videos.map((video) => `
                <div class="list-row">
                  <div class="grow" style="min-width:0">
                    <strong style="font-size:12.5px;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                      ${escapeHtml(video.title)}</strong>
                    <span class="muted tiny">${video.published_at ? fmt.day(video.published_at) : ''}</span>
                  </div>
                  <b class="small">${fmt.number(video.views)}</b>
                </div>`).join('')}
            </div>
          </div>` : ''}
        </div>
      </div>`;

    const botonIdeas = root.querySelector('[data-ideas]');
    if (botonIdeas) {
      botonIdeas.onclick = async () => {
        botonIdeas.disabled = true;
        botonIdeas.textContent = 'Buscando…';
        try {
          await api.post('/api/ideas/generate', { count: 6, validate_demand: true });
          toast('Buscando ideas… se comprueba la demanda de cada tema');
        } catch (error) { toastError(error); }
        botonIdeas.disabled = false;
        botonIdeas.textContent = 'Buscar ideas';
      };
    }

    const cambiarEstado = async (id, status) => {
      await api.patch(`/api/ideas/${id}`, { status });
      ctx.reload();
    };
    root.querySelectorAll('[data-guardar-idea]').forEach((b) => {
      b.onclick = () => cambiarEstado(b.dataset.guardarIdea, 'guardada');
    });
    root.querySelectorAll('[data-descartar-idea]').forEach((b) => {
      b.onclick = () => cambiarEstado(b.dataset.descartarIdea, 'descartada');
    });
    root.querySelectorAll('[data-restaurar-idea]').forEach((b) => {
      b.onclick = () => cambiarEstado(b.dataset.restaurarIdea, 'nueva');
    });
    root.querySelectorAll('[data-copiar-idea]').forEach((b) => {
      b.onclick = () => {
        const idea = ideas.find((i) => i.id === Number(b.dataset.copiarIdea));
        navigator.clipboard.writeText(idea.title).then(() => toast('Título copiado'));
      };
    });
  },

  async onRefresh() {
    const activos = await api.jobs('?status=running&limit=3');
    if (activos.some((job) => ['generate_ideas', 'coach_check'].includes(job.kind))) {
      reloadView();
    }
  },
};
