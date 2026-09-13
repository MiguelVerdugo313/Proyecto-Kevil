// Utilidades de interfaz: formato, avisos, ventanas modales y campos de formulario.

/* ----------------------------------------------------------------- formato */
export const fmt = {
  number(value) {
    const n = Number(value || 0);
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace('.', ',') + ' M';
    if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1).replace('.', ',') + ' mil';
    return String(n);
  },

  duration(seconds) {
    const total = Math.round(Number(seconds || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
  },

  date(value, options) {
    if (!value) return '—';
    return new Date(value).toLocaleString('es-ES',
      options || { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  },

  day(value) {
    if (!value) return '—';
    return new Date(value).toLocaleDateString('es-ES', { weekday: 'short', day: '2-digit', month: 'short' });
  },

  time(value) {
    if (!value) return '—';
    return new Date(value).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  },

  relative(value) {
    if (!value) return '—';
    const diff = (new Date(value) - new Date()) / 1000;
    const abs = Math.abs(diff);
    const rtf = new Intl.RelativeTimeFormat('es', { numeric: 'auto' });
    if (abs < 60) return rtf.format(Math.round(diff), 'second');
    if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
    return rtf.format(Math.round(diff / 86400), 'day');
  },

  // Convierte una fecha ISO (UTC) al valor que espera <input type="datetime-local">
  toLocalInput(value) {
    const date = value ? new Date(value) : new Date();
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date - offset).toISOString().slice(0, 16);
  },

  fromLocalInput(value) {
    return value ? new Date(value).toISOString() : null;
  },
};

export function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/* ------------------------------------------------------------------ estados */
export const STATUS_LABELS = {
  discovered: 'Detectado', queued: 'En cola', downloading: 'Descargando', ready: 'Listo',
  processing: 'Cortando', done: 'Procesado', error: 'Error', ignored: 'Ignorado',
  draft: 'Borrador', rendering: 'Renderizando', rendered: 'Por revisar', approved: 'Aprobado',
  scheduled: 'Programado', publishing: 'Publicando', published: 'Publicado',
  failed: 'Fallido', rejected: 'Descartado', cancelled: 'Cancelado',
  pending: 'En espera', running: 'En marcha', connected: 'Conectada',
  needs_auth: 'Falta autorizar', disabled: 'Desactivada',
};

export const STATUS_TONE = {
  ready: 'info', done: 'ok', published: 'ok', connected: 'ok', rendered: 'info',
  approved: 'info', scheduled: 'violet', publishing: 'violet', running: 'violet',
  downloading: 'violet', processing: 'violet', rendering: 'violet',
  error: 'bad', failed: 'bad', needs_auth: 'warn', queued: 'warn', pending: 'warn',
  rejected: '', cancelled: '', draft: '', discovered: '',
};

export function statusPill(status) {
  const label = STATUS_LABELS[status] || status || '—';
  const tone = STATUS_TONE[status] ?? '';
  return `<span class="pill ${tone}">${escapeHtml(label)}</span>`;
}

// Las tareas del motor usan sus propias palabras (una tarea no está «procesada»).
const JOB_LABELS = {
  pending: 'En espera', running: 'En marcha', done: 'Terminada',
  failed: 'Fallida', cancelled: 'Cancelada',
};

export function jobPill(status) {
  const tone = { done: 'ok', running: 'violet', pending: 'warn', failed: 'bad' }[status] ?? '';
  return `<span class="pill ${tone}">${escapeHtml(JOB_LABELS[status] || status)}</span>`;
}

/* ------------------------------------------------------------------- avisos */
export function toast(message, type = 'ok', timeout = 4200) {
  const root = document.getElementById('toasts');
  const node = document.createElement('div');
  node.className = `toast ${type}`;
  node.innerHTML = `<span class="mark"></span><div>${escapeHtml(message)}</div>`;
  root.appendChild(node);
  setTimeout(() => {
    node.style.transition = 'opacity .25s, transform .25s';
    node.style.opacity = '0';
    node.style.transform = 'translateY(8px)';
    setTimeout(() => node.remove(), 260);
  }, timeout);
}

export function toastError(error) {
  toast(error?.message || String(error), 'error', 6500);
}

/* ------------------------------------------------------------------- modales */
export function modal({ title, body, actions = [], wide = false, onOpen }) {
  const root = document.getElementById('modal-root');
  root.hidden = false;
  root.innerHTML = `
    <div class="modal ${wide ? 'wide' : ''}">
      <div class="modal-head">
        <h3>${escapeHtml(title)}</h3>
        <button class="x" data-close>×</button>
      </div>
      <div class="modal-body">${body}</div>
      ${actions.length ? `<div class="modal-foot">${actions.map((a, i) =>
        `<button class="btn ${a.variant || ''}" data-action="${i}">${escapeHtml(a.label)}</button>`
      ).join('')}</div>` : ''}
    </div>`;

  const close = () => { root.hidden = true; root.innerHTML = ''; };
  root.querySelector('[data-close]').onclick = close;
  root.onclick = (event) => { if (event.target === root) close(); };
  document.onkeydown = (event) => { if (event.key === 'Escape' && !root.hidden) close(); };

  actions.forEach((action, index) => {
    const button = root.querySelector(`[data-action="${index}"]`);
    if (!button) return;
    button.onclick = async () => {
      try {
        const result = await action.onClick?.(root, close);
        if (result !== false) close();
      } catch (error) {
        toastError(error);
      }
    };
  });

  onOpen?.(root, close);
  return { root, close };
}

export function confirmDialog(title, message, confirmLabel = 'Sí, continuar') {
  return new Promise((resolve) => {
    modal({
      title,
      body: `<p class="muted" style="line-height:1.6">${escapeHtml(message)}</p>`,
      actions: [
        { label: 'Cancelar', onClick: () => resolve(false) },
        { label: confirmLabel, variant: 'danger', onClick: () => resolve(true) },
      ],
    });
  });
}

/* ------------------------------------------------- campos de formulario */
export function fieldHtml(field, value, prefix = '') {
  const id = `${prefix}${field.key}`;
  const help = field.help ? `<span class="help">${escapeHtml(field.help)}</span>` : '';
  const current = value === undefined || value === null ? field.default : value;
  let control = '';

  switch (field.type) {
    case 'bool':
      return `<div class="field">
        <label class="switch">
          <input type="checkbox" id="${id}" data-key="${field.key}" data-type="bool" ${current ? 'checked' : ''}>
          <span class="track"></span>
          <span class="switch-label">${escapeHtml(field.label)}</span>
        </label>${help}
      </div>`;

    case 'select':
      control = `<select id="${id}" data-key="${field.key}" data-type="text">
        ${(field.options || []).map((option) =>
          `<option value="${escapeHtml(option.value)}" ${String(option.value) === String(current) ? 'selected' : ''}>${escapeHtml(option.label)}</option>`
        ).join('')}
      </select>`;
      break;

    case 'number':
      control = `<input type="number" id="${id}" data-key="${field.key}" data-type="number"
        value="${escapeHtml(current)}" ${field.min !== undefined ? `min="${field.min}"` : ''}
        ${field.max !== undefined ? `max="${field.max}"` : ''} step="${field.step || 1}">`;
      break;

    case 'slider':
      control = `<div style="display:flex;align-items:center;gap:10px">
        <input type="range" id="${id}" data-key="${field.key}" data-type="number"
          value="${escapeHtml(current)}" min="${field.min ?? 0}" max="${field.max ?? 1}" step="${field.step || 0.01}"
          oninput="this.nextElementSibling.textContent=this.value">
        <b class="mono small" style="min-width:44px;text-align:right">${escapeHtml(current)}</b>
      </div>`;
      break;

    case 'color':
      control = `<input type="color" id="${id}" data-key="${field.key}" data-type="text" value="${escapeHtml(current || '#ffffff')}">`;
      break;

    case 'textarea':
      control = `<textarea id="${id}" data-key="${field.key}" data-type="text">${escapeHtml(current || '')}</textarea>`;
      break;

    case 'tags':
      control = `<div class="tags" data-key="${field.key}" data-type="tags" id="${id}">
        ${(current || []).map((tag) => tagHtml(tag)).join('')}
        <input type="text" placeholder="añadir…" data-tag-input>
      </div>`;
      break;

    default:
      control = `<input type="text" id="${id}" data-key="${field.key}" data-type="text" value="${escapeHtml(current ?? '')}">`;
  }

  return `<div class="field"><label for="${id}">${escapeHtml(field.label)}</label>${control}${help}</div>`;
}

export function tagHtml(tag) {
  return `<span class="tag" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}<button type="button">×</button></span>`;
}

// Activa los campos de etiquetas dentro de un contenedor.
export function bindTagInputs(container) {
  container.querySelectorAll('.tags').forEach((box) => {
    const input = box.querySelector('[data-tag-input]');
    if (!input) return;
    input.onkeydown = (event) => {
      if (event.key === 'Enter' || event.key === ',') {
        event.preventDefault();
        const value = input.value.trim().replace(/^#/, '');
        if (value) input.insertAdjacentHTML('beforebegin', tagHtml(value));
        input.value = '';
      } else if (event.key === 'Backspace' && !input.value) {
        box.querySelector('.tag:last-of-type')?.remove();
      }
    };
    box.onclick = (event) => {
      if (event.target.tagName === 'BUTTON') event.target.closest('.tag').remove();
      else input.focus();
    };
  });
}

// Lee todos los campos marcados con data-key de un contenedor.
export function readFields(container) {
  const result = {};
  container.querySelectorAll('[data-key]').forEach((node) => {
    const key = node.dataset.key;
    const type = node.dataset.type;
    if (type === 'bool') result[key] = node.checked;
    else if (type === 'number') result[key] = Number(node.value);
    else if (type === 'tags') result[key] = [...node.querySelectorAll('.tag')].map((t) => t.dataset.tag);
    else result[key] = node.value;
  });
  return result;
}

/* ------------------------------------------------------------------ varios */
export function debounce(fn, wait = 320) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

export function emptyState(icon, title, text, actionHtml = '') {
  return `<div class="empty">
    <div class="big">${icon}</div>
    <h3>${escapeHtml(title)}</h3>
    <p class="muted" style="max-width:460px;margin:0 auto 16px;line-height:1.6">${escapeHtml(text)}</p>
    ${actionHtml}
  </div>`;
}

export function heatColor(value) {
  const v = Math.max(0, Math.min(1, Number(value) || 0));
  if (v < 0.02) return 'rgba(255,255,255,.04)';
  // de violeta apagado a turquesa intenso
  const hue = 258 - v * 90;
  return `hsl(${hue} ${45 + v * 40}% ${16 + v * 34}%)`;
}
