// Analítica: qué has publicado y cómo ha funcionado.

import { api } from '../lib/api.js';
import { emptyState, escapeHtml, fmt, toast } from '../lib/ui.js';

let days = 30;

export default {
  title: 'Analítica',
  subtitle: 'Rendimiento de lo publicado y aprendizaje del motor',

  actions: [
    { label: 'Actualizar métricas', onClick: async () => {
      await api.post('/api/maintenance/refresh-metrics');
      toast('Pidiendo datos a TikTok…');
    } },
  ],

  async render(root, ctx) {
    const data = await api.analytics(days);
    const max = Math.max(1, ...data.series.map((point) => point.views || point.posts));

    root.innerHTML = `
      <div class="card">
        <div class="card-head">
          <h3>Últimos ${days} días</h3>
          <div style="display:flex;gap:6px">
            ${[7, 30, 90].map((value) => `
              <button class="btn sm ${value === days ? 'primary' : 'ghost'}" data-days="${value}">${value} días</button>`).join('')}
          </div>
        </div>

        <div class="grid cols-4" style="margin-bottom:20px">
          <div class="stat"><div class="label">Publicados</div><div class="value">${data.totals.published}</div>
            <div class="hint">en el periodo</div></div>
          <div class="stat"><div class="label">Vistas</div><div class="value">${fmt.number(data.totals.views)}</div>
            <div class="hint">acumuladas</div></div>
          <div class="stat"><div class="label">Media por vídeo</div><div class="value">${fmt.number(data.totals.avg_views)}</div>
            <div class="hint">vistas</div></div>
          <div class="stat"><div class="label">Me gusta</div><div class="value">${fmt.number(data.totals.likes)}</div>
            <div class="hint">en total</div></div>
        </div>

        ${data.series.length ? `
          <div class="spark">
            ${data.series.map((point) => `
              <i style="height:${Math.max(3, Math.round((point.views || point.posts) / max * 100))}%"
                 title="${escapeHtml(point.date)} · ${point.posts} publicación(es) · ${fmt.number(point.views)} vistas"></i>`).join('')}
          </div>
          <div class="muted tiny" style="display:flex;justify-content:space-between;margin-top:8px">
            <span>${escapeHtml(data.series[0].date)}</span>
            <span>${escapeHtml(data.series[data.series.length - 1].date)}</span>
          </div>`
          : emptyState('◔', 'Sin datos todavía',
            'En cuanto publiques (y TikTok devuelva métricas) verás aquí la evolución. En modo simulación no hay métricas reales.')}
      </div>

      <div class="grid side">
        <div class="card">
          <div class="card-head"><h3>Clips con mejor resultado</h3></div>
          ${data.top.length ? `<table class="table">
            <thead><tr><th>Clip</th><th>Publicado</th><th class="right">Vistas</th><th class="right">Likes</th></tr></thead>
            <tbody>${data.top.map((item) => `
              <tr>
                <td><strong>${escapeHtml(item.title || 'Clip')}</strong></td>
                <td class="small muted nowrap">${fmt.date(item.published_at)}</td>
                <td class="right">${fmt.number(item.views)}</td>
                <td class="right">${fmt.number(item.likes)}</td>
              </tr>`).join('')}</tbody>
          </table>` : '<p class="muted small">Nada que mostrar por ahora.</p>'}
        </div>

        <div class="card">
          <div class="card-head"><h3>Estado de las cuentas</h3></div>
          ${data.accounts.length ? `<div class="list">${data.accounts.map((account) => `
            <div class="list-row" style="flex-direction:column;align-items:stretch;gap:8px">
              <div style="display:flex;justify-content:space-between;gap:10px">
                <strong>@${escapeHtml(account.handle || account.name)}</strong>
                <span class="pill ${account.health >= 70 ? 'ok' : account.health >= 45 ? 'warn' : 'bad'}">salud ${account.health}</span>
              </div>
              <div class="muted small">
                ${fmt.number(account.state.followers)} seguidores ·
                ${account.state.published_7d} esta semana ·
                tendencia ${account.state.trend > 0 ? '▲' : account.state.trend < 0 ? '▼' : '='}
                ${Math.abs(Math.round((account.state.trend || 0) * 100))}%
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap">
                ${account.best_hours.map((hour) => `<span class="pill violet">${escapeHtml(hour.label)}</span>`).join('')}
              </div>
            </div>`).join('')}</div>`
            : '<p class="muted small">Conecta una cuenta de TikTok para ver su evolución.</p>'}
        </div>
      </div>`;

    root.querySelectorAll('[data-days]').forEach((button) => {
      button.onclick = () => { days = Number(button.dataset.days); ctx.reload(); };
    });
  },
};
