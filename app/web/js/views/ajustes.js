// Ajustes: credenciales, motor y mantenimiento.

import { api } from '../lib/api.js';
import { confirmDialog, escapeHtml, fmt, jobPill, toast, toastError } from '../lib/ui.js';

export default {
  title: 'Ajustes',
  subtitle: 'Credenciales, rendimiento y estado del sistema',
  refreshMs: 6000,

  async render(root, ctx) {
    const [config, status, jobs, ia] = await Promise.all([
      api.settings(), api.status(), api.jobs('?limit=25'), api.get('/api/ai/status'),
    ]);
    const values = config.settings;
    const proveedor = values.ai_provider || '';
    const meta = ia.providers[proveedor] || null;

    root.innerHTML = `
      <div class="grid side">
        <div style="display:flex;flex-direction:column;gap:20px">
          <div class="card">
            <div class="card-head">
              <div><h3>Inteligencia artificial</h3>
                <p class="muted small" style="margin-top:4px">
                  Para los títulos, la descripción, los hashtags y las ideas. Opcional:
                  sin clave todo se genera en local (peor, pero funciona).</p></div>
              ${ia.enabled ? '<span class="pill ok">activa</span>' : '<span class="pill warn">sin configurar</span>'}
            </div>
            <div class="form-grid">
              <div class="field"><label>Proveedor</label>
                <select id="ai-prov">
                  <option value="">Ninguno (sólo local)</option>
                  ${Object.entries(ia.providers).map(([clave, valor]) =>
                    `<option value="${clave}" ${proveedor === clave ? 'selected' : ''}>${escapeHtml(valor.label)}</option>`).join('')}
                </select>
                ${meta ? `<span class="help">Consigue tu clave en
                  <a href="${escapeHtml(meta.keys_url)}" target="_blank" rel="noreferrer" style="color:var(--teal)">${escapeHtml(meta.keys_url)}</a></span>` : ''}
              </div>
              <div class="field"><label>Clave de API</label>
                <input type="password" id="ai-key" value="${escapeHtml(values.ai_api_key || '')}" placeholder="sk-…"></div>
              <div class="field"><label>Modelo de texto</label>
                <input type="text" id="ai-model" list="modelos-texto" value="${escapeHtml(values.ai_text_model || '')}"
                  placeholder="${escapeHtml((meta?.text_models || [''])[0])}">
                <datalist id="modelos-texto">
                  ${(meta?.text_models || []).map((m) => `<option value="${escapeHtml(m)}">`).join('')}
                </datalist>
              </div>
              <div class="field"><label>Modelo de imagen (miniaturas)</label>
                <input type="text" id="ai-image" list="modelos-imagen" value="${escapeHtml(values.ai_image_model || '')}"
                  placeholder="${escapeHtml((meta?.image_models || [''])[0])}">
                <datalist id="modelos-imagen">
                  ${(meta?.image_models || []).map((m) => `<option value="${escapeHtml(m)}">`).join('')}
                </datalist>
              </div>
            </div>
            <div style="margin-top:14px;display:flex;gap:9px;align-items:center">
              <button class="btn" data-probar-ia>Probar la conexión</button>
              <span class="muted small" id="ia-resultado"></span>
            </div>
          </div>

          <div class="card">
            <div class="card-head"><h3>Tu canal</h3></div>
            <div class="form-grid">
              <div class="field full"><label>¿De qué va tu canal?</label>
                <input type="text" id="ch-topic" value="${escapeHtml(values.channel_topic || '')}"
                  placeholder="Gameplays de Minecraft y juegos de supervivencia">
                <span class="help">Cuanto más concreto, mejores serán las ideas y los textos.</span></div>
              <div class="field"><label>Vídeos por semana (objetivo)</label>
                <input type="number" id="ch-week" min="0.25" max="14" step="0.25" value="${values.target_uploads_per_week}">
                <span class="help">Marca el ritmo que el coach usará para avisarte.</span></div>
              <div class="field"><label>Idioma</label>
                <select id="ch-lang">
                  ${[['es','Español'],['en','Inglés'],['pt','Portugués']].map(([v,l]) =>
                    `<option value="${v}" ${values.channel_language === v ? 'selected' : ''}>${l}</option>`).join('')}
                </select></div>
              <div class="field full"><label class="switch">
                <input type="checkbox" id="ch-desktop" ${values.notifications_desktop ? 'checked' : ''}>
                <span class="track"></span>
                <span class="switch-label">Avisos en el escritorio (además de la campana)</span></label></div>
            </div>
          </div>

          <div class="card">
            <div class="card-head">
              <div><h3>TikTok</h3>
                <p class="muted small" style="margin-top:4px">Necesario sólo para publicar de verdad.</p></div>
              ${status.tiktok_configured ? '<span class="pill ok">configurado</span>' : '<span class="pill warn">sin configurar</span>'}
            </div>
            <div class="form-grid">
              <div class="field"><label>Client key</label>
                <input type="text" id="s-key" value="${escapeHtml(values.tiktok_client_key || '')}" placeholder="aw…"></div>
              <div class="field"><label>Client secret</label>
                <input type="password" id="s-secret" value="${escapeHtml(values.tiktok_client_secret || '')}" placeholder="••••••••"></div>
              <div class="field full">
                <label>URL de retorno (cópiala en tu app de TikTok)</label>
                <input type="text" value="${escapeHtml(config.tiktok_redirect_uri)}" readonly class="mono">
              </div>
            </div>
          </div>

          <div class="card">
            <div class="card-head"><h3>Motor</h3></div>
            <div class="form-grid">
              <div class="field"><label>Tareas en paralelo</label>
                <input type="number" id="s-workers" min="1" max="8" value="${values.workers}">
                <span class="help">Más tareas a la vez = más rápido, pero más carga en el equipo.</span></div>
              <div class="field"><label>Revisar canales cada (minutos)</label>
                <input type="number" id="s-watch" min="1" max="1440" value="${values.watch_interval_minutes}"></div>
              <div class="field"><label>Ruta de ffmpeg</label>
                <input type="text" id="s-ffmpeg" value="${escapeHtml(values.ffmpeg_path)}"></div>
              <div class="field"><label>Ruta de ffprobe</label>
                <input type="text" id="s-ffprobe" value="${escapeHtml(values.ffprobe_path)}"></div>
              <div class="field full">
                <label class="switch"><input type="checkbox" id="s-dry" ${values.dry_run ? 'checked' : ''}>
                  <span class="track"></span>
                  <span class="switch-label">Modo simulación (procesa y programa todo, pero no publica en TikTok)</span></label>
              </div>
            </div>
            <div style="margin-top:16px;display:flex;gap:9px">
              <button class="btn primary" data-save>Guardar ajustes</button>
              <span class="muted small" style="align-self:center">Los cambios se aplican al momento; algunos, al reiniciar.</span>
            </div>
          </div>

          <div class="card">
            <div class="card-head">
              <h3>Tareas recientes</h3>
              <button class="btn sm ghost" data-clear>Limpiar terminadas</button>
            </div>
            ${jobs.length ? `<table class="table">
              <thead><tr><th>Tarea</th><th>Estado</th><th>Progreso</th><th></th></tr></thead>
              <tbody>${jobs.map((job) => `
                <tr>
                  <td><strong class="small">${escapeHtml(job.message || job.kind)}</strong>
                    <div class="muted tiny">${escapeHtml(job.kind)} · ${fmt.relative(job.created_at)}</div>
                    ${job.error ? `<div class="tiny" style="color:var(--red)">${escapeHtml(job.error.split('\n')[0].slice(0, 130))}</div>` : ''}</td>
                  <td>${jobPill(job.status)}</td>
                  <td style="width:150px"><div class="bar"><i style="width:${Math.round(job.progress * 100)}%"></i></div></td>
                  <td class="right">${job.status === 'failed'
                    ? `<button class="btn sm" data-retry="${job.id}">Reintentar</button>` : ''}</td>
                </tr>`).join('')}</tbody>
            </table>` : '<p class="muted small">Sin tareas registradas.</p>'}
          </div>
        </div>

        <div style="display:flex;flex-direction:column;gap:20px">
          <div class="card">
            <div class="card-head"><h3>Estado</h3></div>
            <div class="list">
              <div class="list-row"><span class="grow">Versión</span><b>${escapeHtml(config.version)}</b></div>
              <div class="list-row"><span class="grow">ffmpeg</span>
                ${status.ffmpeg ? '<span class="pill ok">disponible</span>' : '<span class="pill bad">no encontrado</span>'}</div>
              <div class="list-row"><span class="grow">Publicación</span>
                ${status.dry_run ? '<span class="pill warn">simulación</span>'
                  : status.tiktok_configured ? '<span class="pill ok">real</span>' : '<span class="pill warn">simulación</span>'}</div>
              <div class="list-row"><span class="grow">Espacio libre</span><b>${status.disk_free_gb} GB</b></div>
              <div class="list-row"><span class="grow">Cuentas</span>
                <b>${status.accounts.youtube} YT · ${status.accounts.tiktok} TT</b></div>
              <div class="list-row"><span class="grow">Cola</span>
                <b>${status.jobs_running} en marcha · ${status.jobs_pending} en espera</b></div>
            </div>
            <p class="muted tiny" style="margin-top:14px;line-height:1.6">
              Carpeta de datos:<br><span class="mono">${escapeHtml(config.data_dir)}</span>
            </p>
          </div>

          <div class="card">
            <div class="card-head"><h3>Cómo funciona</h3></div>
            <ul class="muted small" style="margin:0;padding-left:18px;line-height:1.9">
              <li><b style="color:var(--text)">Clips:</b> vigila tus canales, corta los
                vídeos y directos, los pasa a 9:16 con rótulos y los publica en TikTok
                a tu mejor hora.</li>
              <li><b style="color:var(--text)">Estudio:</b> subes un vídeo y te devuelve
                títulos, descripción con capítulos, etiquetas y miniaturas.</li>
              <li><b style="color:var(--text)">Coach:</b> calcula tu ritmo real, te avisa
                si te retrasas y propone temas comprobando su demanda en YouTube.</li>
            </ul>
          </div>
        </div>
      </div>`;

    root.querySelector('[data-save]').onclick = async () => {
      try {
        await api.put('/api/settings', {
          tiktok_client_key: root.querySelector('#s-key').value.trim(),
          tiktok_client_secret: root.querySelector('#s-secret').value.trim(),
          workers: Number(root.querySelector('#s-workers').value),
          watch_interval_minutes: Number(root.querySelector('#s-watch').value),
          ffmpeg_path: root.querySelector('#s-ffmpeg').value.trim(),
          ffprobe_path: root.querySelector('#s-ffprobe').value.trim(),
          dry_run: root.querySelector('#s-dry').checked,
          ai_provider: root.querySelector('#ai-prov').value,
          ai_api_key: root.querySelector('#ai-key').value.trim(),
          ai_text_model: root.querySelector('#ai-model').value.trim(),
          ai_image_model: root.querySelector('#ai-image').value.trim(),
          channel_topic: root.querySelector('#ch-topic').value.trim(),
          channel_language: root.querySelector('#ch-lang').value,
          target_uploads_per_week: Number(root.querySelector('#ch-week').value),
          notifications_desktop: root.querySelector('#ch-desktop').checked,
        });
        toast('Ajustes guardados');
        ctx.reload();
      } catch (error) { toastError(error); }
    };

    root.querySelector('[data-probar-ia]').onclick = async (event) => {
      const salida = root.querySelector('#ia-resultado');
      event.target.disabled = true;
      salida.textContent = 'Probando…';
      salida.style.color = 'var(--muted)';
      try {
        const resultado = await api.post('/api/ai/test');
        salida.textContent = `Funciona: ${resultado.model} responde «${resultado.answer}»`;
        salida.style.color = 'var(--green)';
      } catch (error) {
        salida.textContent = error.message;
        salida.style.color = 'var(--red)';
      }
      event.target.disabled = false;
    };

    root.querySelector('[data-clear]').onclick = async () => {
      if (!await confirmDialog('Limpiar tareas', 'Se borrarán las tareas terminadas, fallidas y canceladas.', 'Limpiar')) return;
      await api.del('/api/jobs/finished');
      toast('Historial limpio');
      ctx.reload();
    };

    root.querySelectorAll('[data-retry]').forEach((button) => {
      button.onclick = async () => {
        await api.post(`/api/jobs/${button.dataset.retry}/retry`);
        toast('Tarea reencolada');
        ctx.reload();
      };
    });
  },

  async onRefresh(root) {
    const jobs = await api.jobs('?status=running&limit=1');
    if (jobs.length) {
      const bar = root.querySelector('.bar > i');
      if (bar) bar.style.width = `${Math.round(jobs[0].progress * 100)}%`;
    }
  },
};
