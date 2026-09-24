// Gráficas pequeñas en SVG, sin librerías.
//
// Reglas (las de siempre para que se lean bien): barras finas (≤ 24 px) con el
// extremo redondeado y la base recta, 2 px de aire entre ellas, rejilla de un
// pelo y discreta, una sola etiqueta (el máximo) y el resto en la ventanita
// que sale al pasar el ratón o al llegar con el tabulador. Una sola serie por
// gráfica: el título ya dice qué es, así que no lleva leyenda.

import { LOCALE, escapeHtml } from './ui.js';

const ANCHO = 560;
const ALTO = 150;
const PIE = 22;          // espacio para las fechas
const ARRIBA = 18;       // espacio para la etiqueta del máximo

function barraRedondeada(x, y, w, h) {
  const r = Math.min(4, w / 2, h);
  const base = y + h;
  if (h <= 0) return '';
  return `M${x},${base} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} `
    + `Q${x + w},${y} ${x + w},${y + r} L${x + w},${base} Z`;
}

function diaCorto(iso) {
  const [a, m, d] = iso.split('-').map(Number);
  return new Date(a, m - 1, d);
}

function numeroLimpio(max) {
  if (max <= 5) return max;             // números pequeños: la barra más alta llega arriba
  const paso = 10 ** Math.floor(Math.log10(max));
  return Math.ceil(max / paso) * paso;
}

/**
 * serie: [{dia: 'AAAA-MM-DD', n: número}]
 * opciones: {unidad: ['publicación', 'publicaciones'], hoy: 'AAAA-MM-DD', vacio: 'texto'}
 */
export function barras(serie, opciones = {}) {
  const datos = serie || [];
  const total = datos.reduce((suma, d) => suma + (d.n || 0), 0);
  if (!datos.length || !total) {
    return `<div class="grafica-vacia">${escapeHtml(opciones.vacio || 'Sin datos todavía.')}</div>`;
  }
  const max = Math.max(...datos.map((d) => d.n || 0));
  const techo = numeroLimpio(max);
  const alto = ALTO - PIE - ARRIBA;
  const hueco = ANCHO / datos.length;
  const grosor = Math.min(24, hueco - 2);
  const [singular, plural] = opciones.unidad || ['', ''];
  const indiceMax = datos.findIndex((d) => d.n === max);

  // líneas sólo en números enteros: «0,5 publicaciones» no existe
  const fracciones = techo % 2 === 0 ? [0, 0.5, 1] : [0, 1];
  const rejilla = fracciones.map((f) => {
    const y = ARRIBA + alto - alto * f;
    return `<line class="rejilla" x1="0" x2="${ANCHO}" y1="${y}" y2="${y}"/>
      <text class="eje" x="${ANCHO}" y="${y - 4}" text-anchor="end">${Math.round(techo * f)}</text>`;
  }).join('');

  const marcas = datos.map((d, i) => {
    const x = i * hueco + (hueco - grosor) / 2;
    const h = d.n ? Math.max(3, (d.n / techo) * alto) : 0;
    const y = ARRIBA + alto - h;
    const fecha = diaCorto(d.dia);
    const texto = fecha.toLocaleDateString(LOCALE, { weekday: 'long', day: 'numeric', month: 'short' });
    const esHoy = opciones.hoy === d.dia;
    const etiqueta = i % 2 === 0 || esHoy
      ? `<text class="eje" x="${x + grosor / 2}" y="${ALTO - 6}" text-anchor="middle">${esHoy ? 'hoy' : fecha.getDate()}</text>`
      : '';
    const valor = i === indiceMax && max > 0
      ? `<text class="valor" x="${x + grosor / 2}" y="${y - 6}" text-anchor="middle">${d.n}</text>`
      : '';
    // la zona que responde al ratón es más grande que la barra
    return `<rect class="zona" x="${i * hueco}" y="${ARRIBA}" width="${hueco}" height="${alto}"
        tabindex="0" data-tip="${escapeHtml(`${d.n} ${d.n === 1 ? singular : plural}`.trim())}"
        data-tip-texto="${escapeHtml(texto)}"></rect>
      ${h ? `<path class="barra ${esHoy ? 'hoy' : ''}" d="${barraRedondeada(x, y, grosor, h)}"
        style="animation-delay:${i * 35}ms"></path>` : ''}
      ${valor}${etiqueta}`;
  }).join('');

  return `<div class="grafica"><svg viewBox="0 0 ${ANCHO} ${ALTO}" role="img"
      aria-label="${escapeHtml(opciones.titulo || 'Gráfica')}: ${total} en total">
      ${rejilla}${marcas}</svg></div>`;
}

/** Mini gráfica para las tarjetas: últimos días en gris y hoy en color. */
export function mini(serie) {
  const datos = (serie || []).slice(-12);
  if (!datos.length) return '';
  const max = Math.max(1, ...datos.map((d) => d.n || 0));
  const w = 100 / datos.length;
  return `<svg class="mini-grafica" viewBox="0 0 100 34" preserveAspectRatio="none" aria-hidden="true">
    ${datos.map((d, i) => {
      const h = d.n ? Math.max(2, (d.n / max) * 32) : 1;
      return `<rect class="${i === datos.length - 1 ? 'ult' : ''}" x="${i * w + 0.8}" y="${34 - h}"
        width="${Math.max(1, w - 1.6)}" height="${h}" rx="1"></rect>`;
    }).join('')}
  </svg>`;
}

/** La ventanita que acompaña al ratón (o al foco) sobre las barras. */
export function activarVentanitas() {
  const tip = document.getElementById('tip-grafica');
  if (!tip) return;

  const mostrar = (objetivo, x, y) => {
    tip.replaceChildren();
    const valor = document.createElement('b');
    valor.textContent = objetivo.dataset.tip;             // el valor manda
    const texto = document.createElement('span');
    texto.textContent = objetivo.dataset.tipTexto || '';  // la fecha, detrás
    tip.append(valor, texto);
    tip.hidden = false;
    const caja = tip.getBoundingClientRect();
    tip.style.left = `${Math.min(window.innerWidth - caja.width - 8, x + 14)}px`;
    tip.style.top = `${Math.max(8, y - caja.height - 12)}px`;
  };
  const ocultar = () => { tip.hidden = true; };

  document.addEventListener('pointermove', (evento) => {
    const objetivo = evento.target.closest?.('[data-tip]');
    if (objetivo) mostrar(objetivo, evento.clientX, evento.clientY);
    else if (!tip.hidden) ocultar();
  });
  document.addEventListener('focusin', (evento) => {
    const objetivo = evento.target.closest?.('[data-tip]');
    if (!objetivo) return;
    const caja = objetivo.getBoundingClientRect();
    mostrar(objetivo, caja.left + caja.width / 2, caja.top);
  });
  document.addEventListener('focusout', ocultar);
  document.addEventListener('scroll', ocultar, true);
}
