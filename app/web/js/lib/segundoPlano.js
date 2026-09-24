// Cómo sale cada publicación y qué hace falta para que salga sola.
//
// YouTube deja programar: el Short se sube antes y queda «Programado» dentro
// de YouTube. TikTok no deja a ninguna app programar: Kevil lo publica a su
// hora desde el PC, así que tiene que estar encendido (en segundo plano vale).

import { api } from './api.js';
import { confirmDialog, toast, toastError } from './ui.js';

export async function estadoSegundoPlano() {
  try { return await api.get('/api/segundo-plano'); } catch { return null; }
}

export function comoSaleHtml(estado, { compacto = false } = {}) {
  if (!estado) return '';
  const pendientes = estado.pendientes_tiktok || 0;
  return `<div class="card como-sale">
    <div class="como-sale-grid">
      <div class="como-sale-item ok">
        <span class="plataforma-marca yt">YouTube Shorts</span>
        <strong>Quedan programados en YouTube</strong>
        <p class="muted small">En cuanto apruebas un clip, Kevil lo sube y lo deja como <b>«Programado»</b> en
          YouTube Studio → Contenido. A su hora YouTube lo publica solo, <b>aunque apagues el PC</b>.</p>
      </div>
      <div class="como-sale-item ${pendientes ? 'warn' : ''}">
        <span class="plataforma-marca tt">TikTok</span>
        <strong>Los publica Kevil a la hora exacta</strong>
        <p class="muted small">TikTok <b>no deja programar</b> a otras aplicaciones: no los verás como programados
          en TikTok. Kevil los sube él mismo a su hora, así que el PC tiene que estar encendido con Kevil abierto
          o en segundo plano.${pendientes ? ` Ahora hay <b>${pendientes}</b> esperando.` : ''}</p>
        ${compacto ? '' : `<div class="como-sale-opciones">
          <label class="switch"><input type="checkbox" data-sp="segundo_plano" ${estado.segundo_plano ? 'checked' : ''}>
            <span class="track"></span><span class="switch-label">Seguir en segundo plano al cerrar la ventana</span></label>
          <label class="switch ${estado.arranque_disponible ? '' : 'apagado'}"><input type="checkbox" data-sp="arrancar_con_windows"
            ${estado.arranca_con_windows ? 'checked' : ''} ${estado.arranque_disponible ? '' : 'disabled'}>
            <span class="track"></span><span class="switch-label">Arrancar con Windows (en segundo plano)</span></label>
          <span class="muted tiny">Si el PC estaba apagado a la hora, el clip no sale de madrugada: se mueve al siguiente buen hueco y te aviso.</span>
        </div>`}
      </div>
    </div>
  </div>`;
}

export function activarSegundoPlano(root, reload) {
  root.querySelectorAll('[data-sp]').forEach((casilla) => {
    casilla.onchange = async () => {
      casilla.disabled = true;
      try {
        await api.put('/api/segundo-plano', { [casilla.dataset.sp]: casilla.checked });
        toast(casilla.checked ? 'Activado' : 'Desactivado');
        reload?.();
      } catch (error) {
        toastError(error);
        casilla.checked = !casilla.checked;
      } finally {
        casilla.disabled = false;
      }
    };
  });
  const salir = root.querySelector('[data-salir-del-todo]');
  if (salir) {
    salir.onclick = async () => {
      if (!await confirmDialog('Cerrar Kevil del todo',
        'Se para también lo que corre en segundo plano: los clips de TikTok no saldrán hasta que lo vuelvas a abrir. Los Shorts ya programados en YouTube salen igual.',
        'Cerrar del todo')) return;
      await api.post('/api/salir', {});
      document.body.innerHTML = '<div style="display:grid;place-items:center;height:100vh;font-family:inherit;color:#aaa">Kevil se ha cerrado. Ya puedes cerrar esta ventana.</div>';
    };
  }
}
