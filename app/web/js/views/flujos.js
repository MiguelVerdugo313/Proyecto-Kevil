// Flujos: el editor visual de todo el proceso, paso a paso.

import { api } from '../lib/api.js';
import {
  bindTagInputs, confirmDialog, escapeHtml, fieldHtml, modal,
  readFields, toast, toastError,
} from '../lib/ui.js';

let schema = null;
let flows = [];
let selectedId = null;
let openStep = null;
let dirty = false;
let reloadView = () => location.reload();

function stepDefinition(type) {
  return schema.steps.find((step) => step.type === type) || { label: type, fields: [], icon: '•' };
}

function summarize(step) {
  const definition = stepDefinition(step.type);
  const config = step.config || {};
  const pieces = [];
  for (const field of definition.fields.slice(0, 3)) {
    let value = config[field.key];
    if (Array.isArray(value)) value = value.slice(0, 2).join(', ') + (value.length > 2 ? '…' : '');
    if (typeof value === 'boolean') value = value ? 'sí' : 'no';
    if (field.type === 'select') {
      const option = (field.options || []).find((o) => String(o.value) === String(value));
      value = option ? option.label : value;
    }
    if (value !== undefined && value !== '') pieces.push(`${field.label}: ${value}`);
  }
  return pieces.join(' · ');
}

function stepHtml(step, index) {
  const definition = stepDefinition(step.type);
  const isOpen = openStep === step.type;
  const locked = Boolean(definition.locked);

  return `<div class="step ${step.enabled ? '' : 'off'} ${isOpen ? 'open' : ''}" data-step="${step.type}">
    <div class="step-head" data-toggle="${step.type}">
      <span class="step-num">${index + 1}</span>
      <span style="font-size:16px">${escapeHtml(definition.icon || '•')}</span>
      <div class="step-title">
        <strong>${escapeHtml(definition.label)}</strong>
        <span>${escapeHtml(summarize(step) || definition.description || '')}</span>
      </div>
      ${locked
        ? '<span class="pill" title="Este paso es imprescindible">siempre</span>'
        : `<label class="switch" onclick="event.stopPropagation()">
             <input type="checkbox" data-enable="${step.type}" ${step.enabled ? 'checked' : ''}>
             <span class="track"></span>
           </label>`}
      <span class="step-arrow">›</span>
    </div>
    ${isOpen ? `<div class="step-body">
      <p class="muted small" style="margin:12px 0 16px;line-height:1.6">${escapeHtml(definition.description || '')}</p>
      <div class="form-grid" data-config="${step.type}">
        ${definition.fields.map((field) => {
          const html = fieldHtml(field, (step.config || {})[field.key], `${step.type}-`);
          const full = ['textarea', 'tags'].includes(field.type);
          return full ? html.replace('class="field"', 'class="field full"') : html;
        }).join('')}
      </div>
    </div>` : ''}
  </div>`;
}

function currentFlow() {
  return flows.find((flow) => flow.id === selectedId) || flows[0];
}

/* -------------------------------------------------------- crear / duplicar */
function newFlowDialog(reload) {
  modal({
    title: 'Nuevo flujo',
    body: `
      <div class="field"><label>Nombre</label><input type="text" id="f-name" placeholder="Cortes para mi canal"></div>
      <div class="field"><label>Descripción</label><input type="text" id="f-desc" placeholder="Opcional"></div>
      <div class="field">
        <label>Partir de una plantilla</label>
        <select id="f-preset">
          ${schema.presets.map((preset) =>
            `<option value="${preset.index}">${escapeHtml(preset.icon)} ${escapeHtml(preset.name)} — ${escapeHtml(preset.description)}</option>`).join('')}
        </select>
      </div>`,
    actions: [
      { label: 'Cancelar' },
      { label: 'Crear flujo', variant: 'primary', onClick: async (root) => {
        const name = root.querySelector('#f-name').value.trim();
        if (!name) { toast('Ponle un nombre', 'warn'); return false; }
        const preset = Number(root.querySelector('#f-preset').value);
        const flow = await api.post('/api/flows', {
          name,
          description: root.querySelector('#f-desc').value.trim(),
          icon: schema.presets[preset]?.icon || '⚡',
          preset,
        });
        selectedId = flow.id;
        toast('Flujo creado');
        reload();
      } },
    ],
  });
}

/* ------------------------------------------------------------------ vista */
export default {
  title: 'Flujos',
  subtitle: 'Define cómo se corta, se edita y se publica cada vídeo',

  actions: [
    { label: '+ Nuevo flujo', variant: 'primary', onClick: () => newFlowDialog(reloadView) },
  ],

  async render(root, ctx) {
    reloadView = ctx.reload;
    if (!schema) schema = await api.flowSchema();
    flows = await api.flows();
    if (!flows.length) {
      root.innerHTML = '<div class="card"><p class="muted">No hay flujos. Crea uno para empezar.</p></div>';
      return;
    }
    if (!flows.some((flow) => flow.id === selectedId)) selectedId = flows[0].id;
    const flow = currentFlow();
    dirty = false;

    root.innerHTML = `
      <div class="grid" style="grid-template-columns:minmax(0,280px) minmax(0,1fr);gap:20px;align-items:start">
        <div class="card">
          <div class="card-head"><h3>Mis flujos</h3></div>
          <div class="flow-list">
            ${flows.map((item) => `
              <div class="flow-card ${item.id === selectedId ? 'active' : ''}" data-flow="${item.id}">
                <span class="emoji">${escapeHtml(item.icon)}</span>
                <div class="meta">
                  <strong>${escapeHtml(item.name)}</strong>
                  <span>${item.is_default ? 'Por defecto · ' : ''}${escapeHtml(item.description || 'Sin descripción')}</span>
                </div>
              </div>`).join('')}
          </div>
          <button class="btn" style="width:100%;justify-content:center;margin-top:14px" data-new>+ Nuevo flujo</button>
        </div>

        <div class="card">
          <div class="card-head" style="flex-wrap:wrap">
            <div style="display:flex;gap:11px;align-items:center;min-width:0;flex:1 1 240px;max-width:100%">
              <span style="font-size:22px">${escapeHtml(flow.icon)}</span>
              <div style="min-width:0">
                <input type="text" id="flow-name" value="${escapeHtml(flow.name)}"
                  style="border:0;background:none;font-size:16px;font-weight:650;padding:0;width:100%">
                <input type="text" id="flow-desc" value="${escapeHtml(flow.description)}" placeholder="Descripción corta"
                  style="border:0;background:none;font-size:12px;color:var(--muted);padding:2px 0 0;width:100%">
              </div>
            </div>
            <div style="display:flex;gap:7px;flex-wrap:wrap;flex:0 0 auto">
              ${flow.is_default ? '<span class="pill ok">por defecto</span>'
                : '<button class="btn sm ghost" data-default>Marcar por defecto</button>'}
              <button class="btn sm ghost" data-duplicate>Duplicar</button>
              <button class="btn sm danger" data-delete>Borrar</button>
              <button class="btn sm primary" data-save>Guardar cambios</button>
            </div>
          </div>

          <p class="muted small" style="margin-bottom:16px;line-height:1.6">
            Los pasos se ejecutan en orden. Pulsa en cualquiera para desplegar sus opciones;
            los que llevan interruptor se pueden desactivar.
          </p>

          <div id="steps">${(flow.steps || []).map(stepHtml).join('')}</div>
        </div>
      </div>`;

    bindTagInputs(root);

    root.querySelectorAll('[data-flow]').forEach((node) => {
      node.onclick = async () => {
        if (dirty && !await confirmDialog('Cambios sin guardar',
          'Si cambias de flujo perderás lo que has tocado. ¿Seguimos?', 'Cambiar igualmente')) return;
        selectedId = Number(node.dataset.flow);
        openStep = null;
        ctx.reload();
      };
    });

    root.querySelector('[data-new]').onclick = () => newFlowDialog(ctx.reload);

    // Abrir/cerrar un paso guardando antes lo editado en el que estaba abierto
    root.querySelectorAll('[data-toggle]').forEach((node) => {
      node.onclick = () => {
        collectOpenStep(root, flow);
        openStep = openStep === node.dataset.toggle ? null : node.dataset.toggle;
        const container = root.querySelector('#steps');
        container.innerHTML = (flow.steps || []).map(stepHtml).join('');
        bindTagInputs(container);
        rebind(root, flow, ctx);
      };
    });

    root.querySelectorAll('[data-enable]').forEach((input) => {
      input.onchange = () => {
        const step = flow.steps.find((s) => s.type === input.dataset.enable);
        step.enabled = input.checked;
        dirty = true;
        input.closest('.step').classList.toggle('off', !step.enabled);
      };
    });

    root.querySelector('[data-save]').onclick = async () => {
      collectOpenStep(root, flow);
      try {
        await api.put(`/api/flows/${flow.id}`, {
          name: root.querySelector('#flow-name').value.trim() || flow.name,
          description: root.querySelector('#flow-desc').value.trim(),
          steps: flow.steps,
        });
        dirty = false;
        toast('Flujo guardado');
        ctx.reload();
      } catch (error) { toastError(error); }
    };

    root.querySelector('[data-duplicate]').onclick = async () => {
      const copy = await api.post(`/api/flows/${flow.id}/duplicate`);
      selectedId = copy.id;
      toast('Flujo duplicado');
      ctx.reload();
    };

    const makeDefault = root.querySelector('[data-default]');
    if (makeDefault) {
      makeDefault.onclick = async () => {
        await api.post(`/api/flows/${flow.id}/default`);
        toast('Ahora es el flujo por defecto');
        ctx.reload();
      };
    }

    root.querySelector('[data-delete]').onclick = async () => {
      if (!await confirmDialog('Borrar flujo', `¿Seguro que quieres borrar «${flow.name}»?`, 'Borrar')) return;
      await api.del(`/api/flows/${flow.id}`);
      selectedId = null;
      toast('Flujo borrado');
      ctx.reload();
    };

    root.querySelector('#flow-name').oninput = () => { dirty = true; };
    root.querySelector('#flow-desc').oninput = () => { dirty = true; };
  },
};

// Vuelve a enlazar los eventos de la lista de pasos tras redibujarla.
function rebind(root, flow, ctx) {
  root.querySelectorAll('[data-toggle]').forEach((node) => {
    node.onclick = () => {
      collectOpenStep(root, flow);
      openStep = openStep === node.dataset.toggle ? null : node.dataset.toggle;
      const container = root.querySelector('#steps');
      container.innerHTML = (flow.steps || []).map(stepHtml).join('');
      bindTagInputs(container);
      rebind(root, flow, ctx);
    };
  });
  root.querySelectorAll('[data-enable]').forEach((input) => {
    input.onchange = () => {
      const step = flow.steps.find((s) => s.type === input.dataset.enable);
      step.enabled = input.checked;
      dirty = true;
      input.closest('.step').classList.toggle('off', !step.enabled);
    };
  });
}

// Lee los campos del paso desplegado y los guarda en memoria.
function collectOpenStep(root, flow) {
  if (!openStep) return;
  const container = root.querySelector(`[data-config="${openStep}"]`);
  if (!container) return;
  const step = flow.steps.find((s) => s.type === openStep);
  if (!step) return;
  step.config = { ...step.config, ...readFields(container) };
  dirty = true;
}
