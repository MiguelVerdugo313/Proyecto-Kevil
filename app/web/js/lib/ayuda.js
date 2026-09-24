// «¿Qué hago?»: cada error explicado con sus pasos y botones que lo arreglan.
//
// El servidor ya manda el diagnóstico (título, porqué, pasos y acciones); aquí
// sólo se pinta y se conectan los botones. Así el mismo fallo se explica igual
// en el panel, en los vídeos y en la ficha de un clip.

import { api } from './api.js';
import { escapeHtml, modal, toast, toastError } from './ui.js';

export function ayudaHtml(diag, { detalle = '', abierto = false } = {}) {
  if (!diag) return '';
  return `<details class="ayuda ${diag.pasajero ? 'pasajero' : ''}" ${abierto ? 'open' : ''}>
    <summary>${escapeHtml(diag.titulo)}<em>¿Qué hago?</em></summary>
    ${diag.por_que ? `<p class="por-que">${escapeHtml(diag.por_que)}</p>` : ''}
    <ol>${(diag.pasos || []).map((paso) => `<li>${escapeHtml(paso)}</li>`).join('')}</ol>
    <div class="botones">
      ${(diag.acciones || []).map((accion, i) => `<button class="btn sm ${i === 0 ? 'primary' : ''}"
        type="button" data-ayuda-accion="${escapeHtml(accion.id)}">${escapeHtml(accion.label)}</button>`).join('')}
    </div>
    ${detalle ? `<div class="detalle">${escapeHtml(detalle.slice(0, 400))}</div>` : ''}
  </details>`;
}

/**
 * Conecta los botones de ayuda de un contenedor.
 * handlers: {reintentar(boton), descartar(boton)} para lo que depende de dónde esté.
 */
export function activarAyuda(root, handlers = {}) {
  root.querySelectorAll('[data-ayuda-accion]').forEach((boton) => {
    boton.onclick = async (evento) => {
      evento.preventDefault();
      const accion = boton.dataset.ayudaAccion;
      boton.disabled = true;
      try {
        if (accion === 'sesion_youtube') await usarSesionYouTube();
        else if (accion === 'cookies_txt') await subirCookies();
        else if (accion === 'liberar') location.hash = '#clips?liberar=1';
        else if (accion === 'cuentas') location.hash = '#cuentas';
        else if (handlers[accion]) await handlers[accion](boton);
        else if (accion === 'reintentar' || accion === 'descartar') {
          toast('Usa el botón de la tarea para esto', 'warn');
        }
      } catch (error) {
        toastError(error);
      } finally {
        boton.disabled = false;
      }
    };
  });
}

/* ------------------------------------------------ tu sesión de YouTube */
export async function usarSesionYouTube() {
  toast('Probando la sesión de YouTube de tus navegadores… (tarda unos segundos)');
  const r = await api.post('/api/youtube/sesion/probar', {});
  mostrarResultadoSesion(r);
  return r;
}

export function mostrarResultadoSesion(r) {
  const nombres = { firefox: 'Firefox', edge: 'Edge', chrome: 'Chrome', brave: 'Brave',
    opera: 'Opera', vivaldi: 'Vivaldi', chromium: 'Chromium' };
  modal({
    title: r.ok ? 'Listo: YouTube ya te reconoce' : 'Ningún navegador ha servido todavía',
    body: `
      <p class="muted" style="line-height:1.6">${escapeHtml(r.mensaje || '')}</p>
      ${(r.intentos || []).length ? `<div class="revision">${r.intentos.map((i) => `
        <div class="check ${i.resultado === 'Funciona' ? 'ok' : 'bad'}">
          <span class="marca">${i.resultado === 'Funciona' ? '✓' : '×'}</span>
          <div><b>${escapeHtml(nombres[i.navegador] || i.navegador)}</b> · ${escapeHtml(i.resultado)}</div>
        </div>`).join('')}</div>` : ''}
      ${r.ok ? '' : `<div class="tip" style="margin:4px 0 0">
        <b>Lo que casi siempre funciona:</b> abre YouTube en <b>Firefox</b>, entra con tu cuenta,
        cierra Firefox y vuelve a pulsar «Probar otra vez». Si usas Chrome, ciérralo del todo
        (también el icono junto al reloj) antes de probar. Y si nada sirve, sube un cookies.txt.
      </div>`}`,
    actions: r.ok ? [{ label: 'Perfecto', variant: 'primary' }] : [
      { label: 'Subir cookies.txt', onClick: async () => { await subirCookies(); } },
      { label: 'Probar otra vez', variant: 'primary', onClick: async () => { await usarSesionYouTube(); } },
    ],
  });
}

export function subirCookies() {
  return new Promise((resolve) => {
    const entrada = document.createElement('input');
    entrada.type = 'file';
    entrada.accept = '.txt,text/plain';
    entrada.onchange = async () => {
      const archivo = entrada.files?.[0];
      if (!archivo) { resolve(false); return; }
      const datos = new FormData();
      datos.append('archivo', archivo);
      try {
        const respuesta = await fetch('/api/youtube/sesion/archivo', { method: 'POST', body: datos });
        const r = await respuesta.json();
        if (!respuesta.ok) throw new Error(r.detail || 'No se pudo guardar el archivo');
        toast(`Cookies de YouTube guardadas${r.reintentados ? ` · ${r.reintentados} tarea(s) vuelven a la cola` : ''}`);
        resolve(true);
      } catch (error) {
        toastError(error);
        resolve(false);
      }
    };
    entrada.click();
  });
}
