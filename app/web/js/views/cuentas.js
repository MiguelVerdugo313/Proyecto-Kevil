// Cuentas: canales de YouTube de origen y perfiles de TikTok de destino.

import { api } from '../lib/api.js';
import {
  confirmDialog, emptyState, escapeHtml, fieldHtml, fmt, modal,
  readFields, statusPill, toast, toastError,
} from '../lib/ui.js';

let cache = { accounts: [], sources: [], flows: [], tiktok: null };
let reloadView = () => location.reload();

/* ------------------------------------------------------------- diálogos */
async function addYouTube(reload) {
  const flowOptions = cache.flows.map((flow) =>
    `<option value="${flow.id}" ${flow.is_default ? 'selected' : ''}>${escapeHtml(flow.icon)} ${escapeHtml(flow.name)}</option>`).join('');
  const tiktokOptions = cache.accounts.filter((a) => a.platform === 'tiktok')
    .map((a) => `<option value="${a.id}">@${escapeHtml(a.handle || a.display_name)}</option>`).join('');

  modal({
    title: 'Conectar un canal de YouTube',
    body: `
      <div class="field">
        <label>URL o @usuario del canal</label>
        <input type="text" id="yt-url" placeholder="https://www.youtube.com/@micanal  ·  @micanal">
        <span class="help">Vale la URL del canal, el @usuario o el ID (UC…). No hace falta ninguna clave de API.</span>
      </div>
      <div class="form-grid">
        <div class="field">
          <label>Flujo que se aplicará</label>
          <select id="yt-flow">${flowOptions}</select>
        </div>
        <div class="field">
          <label>Publicar en</label>
          <select id="yt-target"><option value="">Primera cuenta disponible</option>${tiktokOptions}</select>
        </div>
        <div class="field">
          <label>Vídeos antiguos a traer</label>
          <input type="number" id="yt-backfill" value="20" min="0" max="300">
          <span class="help">0 = sólo los que se publiquen a partir de ahora.</span>
        </div>
        <div class="field">
          <label>Duración mínima (segundos)</label>
          <input type="number" id="yt-min" value="20" min="0">
        </div>
        <div class="field full">
          <label class="switch"><input type="checkbox" id="yt-lives" checked><span class="track"></span>
            <span class="switch-label">Incluir los directos ya emitidos</span></label>
        </div>
        <div class="field full">
          <label class="switch"><input type="checkbox" id="yt-auto" checked><span class="track"></span>
            <span class="switch-label">Vigilar el canal y procesar los vídeos nuevos automáticamente</span></label>
        </div>
      </div>`,
    actions: [
      { label: 'Cancelar' },
      {
        label: 'Conectar canal',
        variant: 'primary',
        onClick: async (root) => {
          const url = root.querySelector('#yt-url').value.trim();
          if (!url) { toast('Pega la URL del canal', 'warn'); return false; }
          const button = root.querySelector('[data-action="1"]');
          button.disabled = true;
          button.textContent = 'Leyendo el canal…';
          try {
            const result = await api.post('/api/accounts/youtube', {
              url,
              flow_id: Number(root.querySelector('#yt-flow').value) || null,
              target_account_id: Number(root.querySelector('#yt-target').value) || null,
              backfill_limit: Number(root.querySelector('#yt-backfill').value),
              min_duration_s: Number(root.querySelector('#yt-min').value),
              include_lives: root.querySelector('#yt-lives').checked,
              auto_ingest: root.querySelector('#yt-auto').checked,
            });
            toast(result.warning || `Canal «${result.account.display_name}» conectado`, result.warning ? 'warn' : 'ok');
            reload();
          } finally {
            button.disabled = false;
            button.textContent = 'Conectar canal';
          }
        },
      },
    ],
  });
}

async function addTikTok(reload) {
  const config = cache.tiktok;
  modal({
    title: 'Conectar una cuenta de TikTok',
    body: `
      ${config.configured ? `
        <p class="muted" style="line-height:1.7">
          Todo listo. Al pulsar el botón se abre TikTok para que autorices la aplicación;
          al volver, la cuenta queda conectada.
        </p>
        <a class="btn primary" href="/api/oauth/tiktok/start" style="align-self:flex-start">Autorizar en TikTok</a>
      ` : `
        <div class="card" style="padding:16px;background:rgba(255,181,69,.07);border-color:rgba(255,181,69,.3)">
          <strong style="font-size:13.5px">Falta configurar tu app de TikTok</strong>
          <p class="muted small" style="margin-top:8px;line-height:1.7">
            1. Entra en <span class="mono">developers.tiktok.com</span> y crea una app.<br>
            2. Activa los permisos <span class="mono">video.publish</span>, <span class="mono">video.upload</span>,
               <span class="mono">user.info.basic</span> y <span class="mono">video.list</span>.<br>
            3. Añade esta URL de retorno:<br>
            <span class="mono" style="display:inline-block;margin-top:6px;padding:5px 9px;border-radius:8px;background:var(--bg-soft)">${escapeHtml(config.redirect_uri)}</span><br>
            4. Copia la clave y el secreto en <a href="#ajustes" style="color:var(--accent)">Ajustes</a>.
          </p>
        </div>`}

      <div style="border-top:1px solid var(--line);padding-top:16px">
        <strong style="font-size:13.5px">O crea una cuenta de prueba</strong>
        <p class="muted small" style="margin:6px 0 12px;line-height:1.6">
          Sirve para montar todo el flujo sin publicar de verdad: los clips se generan y se programan,
          y la publicación se simula.
        </p>
        <div class="form-grid">
          <div class="field"><label>Nombre</label><input type="text" id="tt-name" placeholder="Mi cuenta"></div>
          <div class="field"><label>@usuario</label><input type="text" id="tt-handle" placeholder="micuenta"></div>
        </div>
      </div>`,
    actions: [
      { label: 'Cerrar' },
      {
        label: 'Crear cuenta de prueba',
        onClick: async (root) => {
          const name = root.querySelector('#tt-name').value.trim();
          if (!name) { toast('Ponle un nombre a la cuenta', 'warn'); return false; }
          await api.post('/api/accounts/tiktok/manual', {
            display_name: name,
            handle: root.querySelector('#tt-handle').value.trim(),
          });
          toast('Cuenta de prueba creada');
          reload();
        },
      },
    ],
  });
}

function traerShortsDialog(reload) {
  const flowOptions = cache.flows
    .map((flow) => `<option value="${flow.id}" ${flow.name.startsWith('Shorts a TikTok') ? 'selected' : ''}>${escapeHtml(flow.icon)} ${escapeHtml(flow.name)}</option>`)
    .join('');
  const tiktokOptions = cache.accounts.filter((a) => a.platform === 'tiktok')
    .map((a) => `<option value="${a.id}">@${escapeHtml(a.handle || a.display_name)}</option>`).join('');

  modal({
    title: 'Pasar tus Shorts a TikTok',
    body: `
      <p class="muted small" style="line-height:1.7">
        Kevil mira la pestaña de <b>Shorts</b> de tu canal, baja cada uno y lo publica
        tal cual en TikTok (ya son verticales: no se recortan ni se les añade nada).
        Los Shorts nuevos que subas se republicarán solos.
      </p>
      <div class="field">
        <label>URL o @usuario del canal</label>
        <input type="text" id="sh-url" placeholder="https://www.youtube.com/@micanal">
      </div>
      <div class="form-grid">
        <div class="field"><label>Flujo</label><select id="sh-flow">${flowOptions}</select></div>
        <div class="field"><label>Publicar en</label>
          <select id="sh-target"><option value="">Primera cuenta disponible</option>${tiktokOptions}</select></div>
        <div class="field"><label>Cuántos traer</label>
          <input type="number" id="sh-limit" value="30" min="1" max="200"></div>
        <div class="field"><label class="switch"><input type="checkbox" id="sh-auto" checked>
          <span class="track"></span><span class="switch-label">Vigilar los nuevos</span></label></div>
      </div>`,
    actions: [
      { label: 'Cancelar' },
      { label: 'Traer mis Shorts', variant: 'primary', onClick: async (root) => {
        const url = root.querySelector('#sh-url').value.trim();
        if (!url) { toast('Pega la URL del canal', 'warn'); return false; }
        const boton = root.querySelector('[data-action="1"]');
        boton.disabled = true;
        boton.textContent = 'Leyendo el canal…';
        try {
          const resultado = await api.post('/api/sources/shorts', {
            url,
            flow_id: Number(root.querySelector('#sh-flow').value) || null,
            target_account_id: Number(root.querySelector('#sh-target').value) || null,
            limit: Number(root.querySelector('#sh-limit').value),
            auto_ingest: root.querySelector('#sh-auto').checked,
          });
          toast(resultado.warning || 'Buscando tus Shorts…', resultado.warning ? 'warn' : 'ok');
          reload();
        } finally {
          boton.disabled = false;
          boton.textContent = 'Traer mis Shorts';
        }
      } },
    ],
  });
}

/* --------------------------------------------------- ajustes de una fuente */
function sourceSettings(source, reload) {
  const flowOptions = cache.flows.map((flow) =>
    `<option value="${flow.id}" ${flow.id === source.flow_id ? 'selected' : ''}>${escapeHtml(flow.icon)} ${escapeHtml(flow.name)}</option>`).join('');
  const tiktokOptions = cache.accounts.filter((a) => a.platform === 'tiktok')
    .map((a) => `<option value="${a.id}" ${a.id === source.target_account_id ? 'selected' : ''}>@${escapeHtml(a.handle || a.display_name)}</option>`).join('');

  modal({
    title: `Ajustes de «${source.name}»`,
    body: `
      <div class="form-grid">
        <div class="field full"><label>Nombre</label><input type="text" id="s-name" value="${escapeHtml(source.name)}"></div>
        <div class="field full"><label>URL</label><input type="text" id="s-url" value="${escapeHtml(source.url)}"></div>
        <div class="field"><label>Flujo</label><select id="s-flow">${flowOptions}</select></div>
        <div class="field"><label>Publicar en</label>
          <select id="s-target"><option value="">Primera disponible</option>${tiktokOptions}</select></div>
        <div class="field"><label>Vídeos antiguos</label>
          <input type="number" id="s-backfill" value="${source.backfill_limit}" min="0" max="300"></div>
        <div class="field"><label>Duración mínima (s)</label>
          <input type="number" id="s-min" value="${source.min_duration_s}" min="0"></div>
        <div class="field"><label class="switch"><input type="checkbox" id="s-auto" ${source.auto_ingest ? 'checked' : ''}>
          <span class="track"></span><span class="switch-label">Vigilancia automática</span></label></div>
        <div class="field"><label class="switch"><input type="checkbox" id="s-lives" ${source.include_lives ? 'checked' : ''}>
          <span class="track"></span><span class="switch-label">Incluir directos</span></label></div>
        <div class="field"><label class="switch"><input type="checkbox" id="s-shorts" ${source.include_shorts ? 'checked' : ''}>
          <span class="track"></span><span class="switch-label">Incluir Shorts</span></label></div>
        <div class="field"><label class="switch"><input type="checkbox" id="s-enabled" ${source.enabled ? 'checked' : ''}>
          <span class="track"></span><span class="switch-label">Activo</span></label></div>
      </div>
      ${source.last_error ? `<p class="small" style="color:var(--red)">Último error: ${escapeHtml(source.last_error)}</p>` : ''}`,
    actions: [
      { label: 'Cancelar' },
      {
        label: 'Guardar',
        variant: 'primary',
        onClick: async (root) => {
          await api.patch(`/api/sources/${source.id}`, {
            name: root.querySelector('#s-name').value.trim(),
            url: root.querySelector('#s-url').value.trim(),
            flow_id: Number(root.querySelector('#s-flow').value) || null,
            target_account_id: Number(root.querySelector('#s-target').value) || null,
            backfill_limit: Number(root.querySelector('#s-backfill').value),
            min_duration_s: Number(root.querySelector('#s-min').value),
            auto_ingest: root.querySelector('#s-auto').checked,
            include_lives: root.querySelector('#s-lives').checked,
            include_shorts: root.querySelector('#s-shorts').checked,
            enabled: root.querySelector('#s-enabled').checked,
          });
          toast('Guardado');
          reload();
        },
      },
    ],
  });
}

/* ---------------------------------------------- dónde sale cada clip */
// Lo decide el paso «Publicación» de cada flujo; aquí se ve y se cambia sin
// abrir el editor. Sólo salen los flujos que se usan: los demás, plegados.
function interruptor(flujo, clave, etiqueta, desactivado = false) {
  return `<label class="switch ${desactivado ? 'apagado' : ''}"><input type="checkbox" data-destino="${flujo.id}" data-clave="${clave}"
      ${flujo[clave] ? 'checked' : ''} ${desactivado ? 'disabled' : ''}><span class="track"></span>
      <span class="switch-label">${etiqueta}</span></label>`;
}

function frase(flujo) {
  const donde = [flujo.tiktok && 'TikTok', flujo.shorts && 'YouTube Shorts'].filter(Boolean);
  return donde.length ? `salen en <b>${donde.join('</b> y en <b>')}</b>` : '<b>no se publican</b> (sólo se exportan)';
}

function filaDestino(flujo, d) {
  const sinYouTube = !d.youtube;
  return `<div class="destino-fila">
    <div class="grow" style="min-width:0">
      <strong>${escapeHtml(flujo.icon)} ${escapeHtml(flujo.name)}</strong>
      ${flujo.is_default ? '<span class="pill" style="margin-left:6px">por defecto</span>' : ''}
      <div class="muted small" style="margin-top:3px">
        ${flujo.canales.length ? `Los clips de ${flujo.canales.map((c) => `«${escapeHtml(c)}»`).join(', ')}` : 'Sus clips'}
        ${frase(flujo)}.
        ${flujo.shorts && sinYouTube ? '<span style="color:var(--amber)">Falta autorizar tu canal para que salgan en Shorts.</span>' : ''}
      </div>
    </div>
    <div class="destino-interruptores">
      ${interruptor(flujo, 'tiktok', 'TikTok')}
      ${interruptor(flujo, 'shorts', 'YouTube Shorts')}
    </div>
  </div>`;
}

function destinosHtml(d) {
  const enUso = d.flujos.filter((f) => f.en_uso);
  const otros = d.flujos.filter((f) => !f.en_uso);
  const ningunoAShorts = enUso.length && !enUso.some((f) => f.shorts);
  return `<div class="card">
    <div class="card-head">
      <div>
        <h3>Dónde sale cada clip</h3>
        <p class="muted small" style="margin-top:4px">
          TikTok: ${d.tiktok.length ? d.tiktok.map((c) => `<b>${escapeHtml(c.nombre)}</b>${c.prueba ? ' (prueba)' : ''}`).join(', ') : '<span style="color:var(--amber)">sin cuenta</span>'}
          · YouTube Shorts: ${d.youtube ? `<b>${escapeHtml(d.youtube.nombre)}</b>`
            : d.youtube_sin_permiso ? '<span style="color:var(--amber)">canal sin permiso para publicar</span>'
            : '<span class="muted">sin canal</span>'}
        </p>
      </div>
      ${!d.youtube && d.youtube_sin_permiso ? '<a class="btn sm primary" href="/api/oauth/youtube/start">Autorizar para publicar</a>' : ''}
    </div>
    ${d.youtube && ningunoAShorts ? `<div class="destino-aviso">
      <span>Tu canal puede publicar Shorts, pero ahora mismo los clips <b>sólo van a TikTok</b>.</span>
      <button class="btn sm primary" data-shorts-todos>Publicar también en Shorts</button>
    </div>` : ''}
    <div class="destinos">${enUso.map((f) => filaDestino(f, d)).join('')}</div>
    ${otros.length ? `<details class="destinos-otros"><summary class="muted small">Otros flujos (${otros.length})</summary>
      <div class="destinos">${otros.map((f) => filaDestino(f, d)).join('')}</div></details>` : ''}
    <p class="muted tiny" style="margin-top:12px;line-height:1.6">
      Cada clip también se puede mandar a otro sitio al aprobarlo. Google deja subir unos 6 Shorts al día;
      los que no quepan salen al día siguiente.</p>
  </div>`;
}

function activarDestinos(root, reload) {
  root.querySelectorAll('[data-destino]').forEach((casilla) => {
    casilla.onchange = async () => {
      casilla.disabled = true;
      try {
        await api.put(`/api/destinos/${casilla.dataset.destino}`, { [casilla.dataset.clave]: casilla.checked });
        toast('Guardado: los clips nuevos saldrán así');
        reload();
      } catch (error) {
        toastError(error);
        casilla.checked = !casilla.checked;
        casilla.disabled = false;
      }
    };
  });
  const todos = root.querySelector('[data-shorts-todos]');
  if (todos) {
    todos.onclick = async () => {
      todos.disabled = true;
      const ids = [...root.querySelectorAll('.destinos [data-clave="shorts"]')]
        .filter((c) => !c.closest('.destinos-otros')).map((c) => c.dataset.destino);
      try {
        for (const id of ids) await api.put(`/api/destinos/${id}`, { shorts: true });
        toast('Listo: los clips saldrán en TikTok y en YouTube Shorts');
        reload();
      } catch (error) { toastError(error); todos.disabled = false; }
    };
  }
}

/* ----------------------------------------------- estrategia de publicación */
// Si la cuenta usa una zona que no está en la lista, se añade: guardar sin
// tocarla no puede cambiártela por la primera de la lista.
function conZonaActual(field, valor) {
  if (field.key !== 'timezone' || !valor || field.options.some((o) => o.value === valor)) return field;
  return { ...field, options: [{ value: valor, label: valor }, ...field.options] };
}

const STRATEGY_FIELDS = [
  { key: 'timezone', label: 'Zona horaria', type: 'select', default: 'America/Bogota',
    options: [
      ['America/Bogota', 'Colombia, Perú, Ecuador (UTC−5)'],
      ['America/Mexico_City', 'México (centro)'],
      ['America/Guatemala', 'Centroamérica (UTC−6)'],
      ['America/Caracas', 'Venezuela (UTC−4)'],
      ['America/Santiago', 'Chile'],
      ['America/Argentina/Buenos_Aires', 'Argentina (UTC−3)'],
      ['America/Sao_Paulo', 'Brasil (Brasilia)'],
      ['America/New_York', 'EE. UU. (este)'],
      ['America/Los_Angeles', 'EE. UU. (pacífico)'],
      ['Europe/Madrid', 'España'],
      ['UTC', 'UTC'],
    ].map(([value, label]) => ({ value, label })),
    help: 'Las horas buenas se calculan en esta zona. Kevil pone la de tu ordenador.' },
  { key: 'max_per_day', label: 'Máximo por día', type: 'number', default: 3, min: 1, max: 12 },
  { key: 'min_gap_hours', label: 'Horas entre publicaciones', type: 'number', default: 3, min: 0.5, max: 48, step: 0.5 },
  { key: 'jitter_minutes', label: 'Variación aleatoria (min)', type: 'number', default: 12, min: 0, max: 60,
    help: 'Evita publicar siempre al mismo minuto exacto.' },
  { key: 'warmup', label: 'Calentar cuentas nuevas', type: 'bool', default: true,
    help: 'Empieza con menos publicaciones al día y sube según crece la cuenta.' },
  { key: 'min_samples', label: 'Publicaciones para aprender', type: 'number', default: 6, min: 3, max: 60,
    help: 'A partir de aquí el motor usa tu propio historial en vez del patrón base.' },
];

async function strategyDialog(accountId, reload) {
  const data = await api.get(`/api/accounts/${accountId}/strategy`);
  const strategy = data.strategy;
  const heat = data.heatmap.matrix;
  const quiet = strategy.quiet_hours || { start: 1, end: 7 };

  const heatHtml = `
    <div class="heat" id="heat">
      <span class="lbl"></span>
      ${Array.from({ length: 24 }, (_, hour) => `<span class="hour">${hour % 3 === 0 ? hour : ''}</span>`).join('')}
      ${data.days.map((day, index) => `
        <span class="lbl">${escapeHtml(day.slice(0, 3))}</span>
        ${heat[index].map((value, hour) => `
          <span class="cell" data-day="${index}" data-hour="${hour}"
            title="${escapeHtml(day)} ${fmt.hour(hour)} · ${Math.round(value * 100)}%"
            style="background:${heatColorLocal(value)}"></span>`).join('')}`).join('')}
    </div>`;

  modal({
    title: 'Estrategia de publicación',
    wide: true,
    body: `
      <div class="grid cols-3" style="gap:12px">
        <div class="stat"><div class="label">Estado</div><div class="value" style="font-size:18px">${escapeHtml(data.state.maturity)}</div>
          <div class="hint">${fmt.number(data.state.followers)} seguidores</div></div>
        <div class="stat"><div class="label">Ritmo recomendado</div><div class="value" style="font-size:18px">${data.state.recommended_per_day}/día</div>
          <div class="hint">${data.state.published_7d} publicados esta semana</div></div>
        <div class="stat"><div class="label">Fuente de horarios</div><div class="value" style="font-size:18px">${data.state.using_history ? 'Tu historial' : 'Patrón base'}</div>
          <div class="hint">${data.state.learned_samples} muestras acumuladas</div></div>
      </div>

      <div>
        <div class="card-head" style="margin-bottom:10px">
          <h3 style="font-size:14px">Mejores horas (pulsa una casilla para ajustarla)</h3>
          <span class="muted tiny">clic = +20% · clic derecho = −20%</span>
        </div>
        ${heatHtml}
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px">
          ${data.best_hours.map((hour) => `<span class="pill violet">${escapeHtml(hour.label)} · ${hour.percent}%</span>`).join('')}
        </div>
      </div>

      <div class="form-grid" id="strategy-fields">
        ${STRATEGY_FIELDS.map((field) => fieldHtml(conZonaActual(field, strategy[field.key]), strategy[field.key])).join('')}
        <div class="field"><label>Silencio desde (hora)</label>
          <input type="number" id="quiet-start" min="0" max="23" value="${quiet.start}"></div>
        <div class="field"><label>Silencio hasta (hora)</label>
          <input type="number" id="quiet-end" min="0" max="23" value="${quiet.end}"></div>
        <div class="field full">
          <label>Días permitidos</label>
          <div style="display:flex;gap:6px;flex-wrap:wrap" id="days">
            ${data.days.map((day, index) => `
              <button type="button" class="btn sm ${(strategy.allowed_days || []).includes(index) ? 'primary' : ''}"
                data-day="${index}">${escapeHtml(day.slice(0, 3))}</button>`).join('')}
          </div>
        </div>
      </div>`,
    actions: [
      { label: 'Cancelar' },
      {
        label: 'Guardar estrategia',
        variant: 'primary',
        onClick: async (root) => {
          const values = readFields(root.querySelector('#strategy-fields'));
          const allowed = [...root.querySelectorAll('#days [data-day]')]
            .filter((button) => button.classList.contains('primary'))
            .map((button) => Number(button.dataset.day));
          await api.put(`/api/accounts/${accountId}/strategy`, {
            ...strategy,
            ...values,
            allowed_days: allowed.length ? allowed : [0, 1, 2, 3, 4, 5, 6],
            quiet_hours: {
              start: Number(root.querySelector('#quiet-start').value),
              end: Number(root.querySelector('#quiet-end').value),
            },
            heatmap: heat,
          });
          toast('Estrategia guardada');
          reload();
        },
      },
    ],
    onOpen(root) {
      root.querySelectorAll('#days [data-day]').forEach((button) => {
        button.onclick = () => button.classList.toggle('primary');
      });
      const adjust = (cell, delta) => {
        const day = Number(cell.dataset.day);
        const hour = Number(cell.dataset.hour);
        heat[day][hour] = Math.max(0, Math.min(1, Number((heat[day][hour] + delta).toFixed(2))));
        cell.style.background = heatColorLocal(heat[day][hour]);
        cell.title = `${data.days[day]} ${fmt.hour(hour)} · ${Math.round(heat[day][hour] * 100)}%`;
      };
      root.querySelectorAll('#heat .cell').forEach((cell) => {
        cell.onclick = () => adjust(cell, 0.2);
        cell.oncontextmenu = (event) => { event.preventDefault(); adjust(cell, -0.2); };
      });
    },
  });
}

function heatColorLocal(value) {
  const v = Math.max(0, Math.min(1, Number(value) || 0));
  if (v < 0.02) return 'rgba(255,255,255,.04)';
  const hue = 258 - v * 90;
  return `hsl(${hue} ${45 + v * 40}% ${16 + v * 34}%)`;
}

/* ------------------------------------------------------------------ vista */
export default {
  title: 'Cuentas',
  subtitle: 'De dónde sale el contenido y a dónde va',

  actions: [
    { label: '↻ Shorts a TikTok', onClick: () => traerShortsDialog(reloadView) },
    { label: '+ Canal de YouTube', onClick: () => addYouTube(reloadView) },
    { label: '+ Cuenta de TikTok', variant: 'primary', onClick: () => addTikTok(reloadView) },
  ],

  async render(root, ctx) {
    const [accounts, sources, flows, tiktokConfig, ytConfig, destinos] = await Promise.all([
      api.accounts(), api.sources(), api.flows(),
      api.get('/api/tiktok/config'), api.get('/api/youtube/config'), api.get('/api/destinos'),
    ]);
    cache = { accounts, sources, flows, tiktok: tiktokConfig };

    const youtube = accounts.filter((a) => a.platform === 'youtube');
    const tiktok = accounts.filter((a) => a.platform === 'tiktok');
    const reload = ctx.reload;
    reloadView = reload;

    // El canal que autorizaste para publicar, ¿se vigila también para sacar clips?
    const vigilado = (cuenta) => Boolean(cuenta.vigilado);
    // el aviso grande sólo si no lo quitaste tú a propósito
    const sinVigilar = youtube.filter((cuenta) => !cuenta.vigilado && !cuenta.quitado);

    root.innerHTML = `
      ${sinVigilar.length ? `<div class="card aviso-vigilar">
        <div>
          <h3>Tu canal está conectado, pero no se vigila</h3>
          <p class="muted small" style="margin-top:6px;line-height:1.6">
            Autorizarlo sirve para <b>publicar</b> Shorts. Para que Kevil <b>saque clips</b> de tus vídeos y directos
            hay que vigilarlo: lo revisa cada poco y corta lo nuevo solo.</p>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          ${sinVigilar.map((cuenta) => `<button class="btn primary" data-vigilar="${cuenta.id}">
            Vigilar «${escapeHtml(cuenta.display_name)}»</button>`).join('')}
        </div>
      </div>` : ''}

      <div class="card">
        <div class="card-head">
          <div>
            <h3>Canales vigilados <span class="muted small" style="font-weight:400">· de aquí salen los clips</span></h3>
            <p class="muted small" style="margin-top:4px">Se revisan solos cada poco en busca de vídeos y directos nuevos.</p>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <button class="btn" data-add-shorts>↻ Shorts a TikTok</button>
            <button class="btn" data-add-yt>+ Conectar canal</button>
          </div>
        </div>
        ${sources.length ? `
        <table class="table">
          <thead><tr><th>Canal</th><th>Flujo</th><th>Automático</th><th>Última revisión</th><th></th></tr></thead>
          <tbody>
            ${sources.map((source) => {
              const flow = flows.find((f) => f.id === source.flow_id);
              return `<tr>
                <td>
                  <strong>${escapeHtml(source.name)}</strong>
                  <div class="muted tiny">${escapeHtml(source.url)}</div>
                  ${source.last_error ? `<div class="tiny" style="color:var(--red)">${escapeHtml(source.last_error.slice(0, 90))}</div>` : ''}
                </td>
                <td>${flow ? `${escapeHtml(flow.icon)} ${escapeHtml(flow.name)}` : '<span class="muted">por defecto</span>'}</td>
                <td>${source.auto_ingest ? '<span class="pill ok">activo</span>' : '<span class="pill">manual</span>'}
                    ${source.kind === 'shorts' ? '<span class="pill violet">shorts</span>' : ''}
                    ${source.include_lives ? '<span class="pill pink">directos</span>' : ''}</td>
                <td class="small muted">${source.last_checked_at ? fmt.relative(source.last_checked_at) : 'nunca'}</td>
                <td><div class="actions">
                  <button class="btn sm" data-sync="${source.id}">Revisar ahora</button>
                  <button class="btn sm ghost" data-source="${source.id}">Ajustes</button>
                  <button class="btn sm danger" data-del-source="${source.id}">Quitar</button>
                </div></td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>` : emptyState('▶', 'Ningún canal vigilado', sinVigilar.length
          ? 'Pulsa «Vigilar» arriba y Kevil empezará a buscar tus vídeos.'
          : 'Pega la URL de tu canal de YouTube y Kevil se encargará del resto.',
          '<button class="btn primary" data-add-yt>Vigilar un canal</button>')}
      </div>

      ${destinosHtml(destinos)}

      <div class="card">
        <div class="card-head">
          <div>
            <h3>Cuentas de TikTok</h3>
            <p class="muted small" style="margin-top:4px">
              ${tiktokConfig.configured ? 'App configurada: puedes autorizar cuentas reales.'
                : 'Sin credenciales de app: las publicaciones se simularán.'}
            </p>
          </div>
          <button class="btn" data-add-tt>+ Conectar TikTok</button>
        </div>
        ${tiktok.length ? `<div class="list">${tiktok.map((account) => `
          <div class="list-row">
            <div class="avatar">${account.avatar_url ? `<img src="${escapeHtml(account.avatar_url)}" style="width:100%;height:100%;object-fit:cover;border-radius:12px">`
              : escapeHtml((account.display_name || '?').slice(0, 1).toUpperCase())}</div>
            <div class="grow" style="min-width:0">
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <strong>${escapeHtml(account.display_name)}</strong>
                ${statusPill(account.status)}
                ${account.has_token ? '' : '<span class="pill warn">simulación</span>'}
              </div>
              <div class="muted small" style="margin-top:3px">
                @${escapeHtml(account.handle || '—')} ·
                ${fmt.number(account.stats?.followers || 0)} seguidores ·
                ${account.state?.scheduled || 0} programados ·
                ritmo ${account.state?.recommended_per_day || '—'}/día
              </div>
              ${account.status_detail ? `<div class="tiny" style="color:var(--amber);margin-top:3px">${escapeHtml(account.status_detail)}</div>` : ''}
            </div>
            <div class="actions">
              <button class="btn sm" data-strategy="${account.id}">Estrategia</button>
              <button class="btn sm ghost" data-refresh="${account.id}">Actualizar</button>
              <button class="btn sm danger" data-del-account="${account.id}">Quitar</button>
            </div>
          </div>`).join('')}</div>`
          : emptyState('◍', 'Sin cuentas de TikTok', 'Conecta tu cuenta para publicar, o crea una de prueba para ver todo el flujo funcionando.',
            '<button class="btn primary" data-add-tt>Conectar TikTok</button>')}
      </div>

      ${youtube.length ? `<div class="card">
        <div class="card-head">
          <div>
            <h3>Mis canales de YouTube</h3>
            <p class="muted small" style="margin-top:4px">
              ${ytConfig.connected
                ? `Puedes publicar Shorts · te quedan <b style="color:var(--text)">${ytConfig.quota.uploads_left}</b> subidas hoy`
                : 'Para publicar Shorts hay que autorizar el canal en Ajustes → YouTube.'}
            </p>
          </div>
          ${ytConfig.configured && !ytConfig.connected
            ? '<a class="btn sm primary" href="/api/oauth/youtube/start">Autorizar para publicar</a>'
            : '<a class="btn sm ghost" href="#ajustes">Ajustes de YouTube</a>'}
        </div>
        <div class="list">${youtube.map((account) => `
          <div class="list-row">
            <div class="avatar">${account.avatar_url ? `<img src="${escapeHtml(account.avatar_url)}" style="width:100%;height:100%;object-fit:cover">` : '▶'}</div>
            <div class="grow" style="min-width:0">
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <strong>${escapeHtml(account.display_name)}</strong>
                ${vigilado(account)
                  ? '<span class="pill ok" title="Kevil busca sus vídeos y saca clips">vigilado · saca clips</span>'
                  : '<span class="pill warn">no se vigila</span>'}
                ${account.has_token
                  ? '<span class="pill ok">publica Shorts</span>'
                  : '<span class="pill">sin permiso para publicar</span>'}
              </div>
              <div class="muted small" style="margin-top:3px">
                ${fmt.number(account.stats?.subscribers || 0)} suscriptores</div>
            </div>
            <div class="actions">
              ${vigilado(account) ? '' : `<button class="btn sm primary" data-vigilar="${account.id}">Vigilar</button>`}
              <button class="btn sm danger" data-del-account="${account.id}">Quitar</button>
            </div>
          </div>`).join('')}</div>
      </div>` : ''}`;

    root.querySelectorAll('[data-vigilar]').forEach((boton) => {
      boton.onclick = async () => {
        boton.disabled = true;
        try {
          const fuente = await api.post(`/api/accounts/${boton.dataset.vigilar}/vigilar`);
          toast(`Vigilando «${fuente.name}»: en unos minutos verás sus vídeos en «Vídeos»`);
          reload();
        } catch (error) { toastError(error); boton.disabled = false; }
      };
    });
    activarDestinos(root, reload);

    root.querySelectorAll('[data-add-yt]').forEach((b) => { b.onclick = () => addYouTube(reload); });
    root.querySelectorAll('[data-add-tt]').forEach((b) => { b.onclick = () => addTikTok(reload); });
    root.querySelectorAll('[data-add-shorts]').forEach((b) => {
      b.onclick = () => traerShortsDialog(reload);
    });

    root.querySelectorAll('[data-sync]').forEach((button) => {
      button.onclick = async () => {
        button.disabled = true;
        try {
          await api.post(`/api/sources/${button.dataset.sync}/sync`);
          toast('Revisando el canal… lo verás en Vídeos en unos segundos');
        } catch (error) { toastError(error); }
        button.disabled = false;
      };
    });

    root.querySelectorAll('[data-source]').forEach((button) => {
      button.onclick = () => sourceSettings(sources.find((s) => s.id === Number(button.dataset.source)), reload);
    });

    root.querySelectorAll('[data-strategy]').forEach((button) => {
      button.onclick = () => strategyDialog(Number(button.dataset.strategy), reload).catch(toastError);
    });

    root.querySelectorAll('[data-refresh]').forEach((button) => {
      button.onclick = async () => {
        await api.post(`/api/accounts/${button.dataset.refresh}/refresh`);
        toast('Actualizando datos de la cuenta…');
      };
    });

    root.querySelectorAll('[data-del-source]').forEach((button) => {
      button.onclick = async () => {
        if (!await confirmDialog('Quitar canal', 'Se dejará de vigilar. Los vídeos ya descargados se mantienen.', 'Quitar')) return;
        await api.del(`/api/sources/${button.dataset.delSource}`);
        toast('Canal quitado');
        reload();
      };
    });

    root.querySelectorAll('[data-del-account]').forEach((button) => {
      button.onclick = async () => {
        if (!await confirmDialog('Quitar cuenta', 'Se borrará la conexión y sus publicaciones programadas.', 'Quitar')) return;
        await api.del(`/api/accounts/${button.dataset.delAccount}`);
        toast('Cuenta quitada');
        reload();
      };
    });
  },
};
