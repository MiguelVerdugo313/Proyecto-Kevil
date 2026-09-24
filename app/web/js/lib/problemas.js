// Tareas con problemas, agrupadas por causa y con su arreglo al lado.
//
// Antes salía una fila por intento («Unable to download…» cuatro veces para el
// mismo clip). Ahora: una tarjeta por causa, qué significa, qué hacer, y
// botones para reintentar todo lo de esa causa o quitarlo de la lista.

import { api } from './api.js';
import { activarAyuda, ayudaHtml } from './ayuda.js';
import { escapeHtml, fmt, toast } from './ui.js';

export async function problemasHtml() {
  const datos = await api.get('/api/problemas');
  if (!datos.total) return { html: '', total: 0 };
  const html = `<div class="card" id="problemas">
    <div class="card-head">
      <div>
        <h3>Tareas con problemas</h3>
        <p class="muted small" style="margin-top:4px">
          ${datos.total} tarea(s)${datos.duplicados ? ` · ${datos.duplicados} intento(s) repetidos ocultos` : ''}.
          Lo pasajero se reintenta solo; lo demás tiene su arreglo abajo.
        </p>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn sm" data-problemas-descartar>Quitar de la lista</button>
        <button class="btn sm primary" data-problemas-reintentar>Reintentar todo</button>
      </div>
    </div>
    ${datos.grupos.map((grupo) => `
      <div class="problema" data-tipo="${escapeHtml(grupo.tipo)}">
        <div class="problema-head">
          <div class="num">${grupo.total}</div>
          <div class="grow" style="min-width:0">
            ${ayudaHtml(grupo, { abierto: datos.grupos.length === 1 })}
            <div class="problema-lista">
              ${grupo.trabajos.slice(0, 5).map((t) => `
                <div class="problema-item">
                  <b>${escapeHtml(t.que)}</b>
                  <span class="grow" title="${escapeHtml(t.detalle)}">${escapeHtml(t.titulo || t.mensaje)}</span>
                  <span class="tiny">${t.finished_at ? fmt.relative(t.finished_at) : ''}</span>
                  <button class="btn sm ghost" data-reintentar-uno="${t.id}">Reintentar</button>
                </div>`).join('')}
              ${grupo.total > 5 ? `<div class="muted tiny">y ${grupo.total - 5} más</div>` : ''}
            </div>
          </div>
        </div>
      </div>`).join('')}
  </div>`;
  return { html, total: datos.total };
}

export function activarProblemas(root, recargar) {
  const caja = root.querySelector('#problemas');
  if (!caja) return;

  caja.querySelectorAll('.problema').forEach((grupo) => {
    const tipo = grupo.dataset.tipo;
    activarAyuda(grupo, {
      reintentar: async () => {
        const r = await api.post('/api/problemas/reintentar', { tipo });
        toast(`${r.reintentados} tarea(s) otra vez en la cola`);
        recargar();
      },
      descartar: async () => {
        await api.post('/api/problemas/descartar', { tipo });
        toast('Quitado de la lista');
        recargar();
      },
    });
  });
  caja.querySelectorAll('[data-reintentar-uno]').forEach((boton) => {
    boton.onclick = async () => {
      await api.post('/api/problemas/reintentar', { job_id: Number(boton.dataset.reintentarUno) });
      toast('Otra vez en la cola');
      recargar();
    };
  });
  caja.querySelector('[data-problemas-reintentar]').onclick = async () => {
    const r = await api.post('/api/problemas/reintentar', {});
    toast(`${r.reintentados} tarea(s) otra vez en la cola`);
    recargar();
  };
  caja.querySelector('[data-problemas-descartar]').onclick = async () => {
    await api.post('/api/problemas/descartar', {});
    toast('Lista limpia');
    recargar();
  };
}
