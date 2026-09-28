// Vista previa de los rótulos: lo mismo que quema el render, pero en vivo.
//
// Usa las mismas tipografías (servidas por Kevil), el mismo tamaño que les da
// el render, los mismos colores, la pastilla, las palabras fuertes, los emojis
// y el salto al entrar. Así lo que eliges en «Crear» es lo que sale en el clip.

import { api } from './api.js';

let cargadas = null;

/** Las plantillas y sus extras, con las tipografías ya registradas. */
export async function cargarPlantillas() {
  if (cargadas) return cargadas;
  const [lista, extras] = await Promise.all([
    api.get('/api/flows/plantillas-rotulos'),
    api.get('/api/flows/plantillas-rotulos/extras'),
  ]);
  const archivos = new Map(lista.map((p) => [p.archivo, p.fuente]));
  archivos.set(extras.fuente_emoji.archivo, extras.fuente_emoji.familia);
  await Promise.all([...archivos].filter(([archivo]) => archivo).map(async ([archivo, familia]) => {
    try {
      const cara = new FontFace(`KV ${familia}`, `url(/api/flows/plantillas-rotulos/fuente/${encodeURIComponent(archivo)})`);
      document.fonts.add(await cara.load());
    } catch { /* sin la tipografía se ve con la del sistema: no es grave */ }
  }));
  cargadas = { lista, porId: Object.fromEntries(lista.map((p) => [p.id, p])), extras };
  return cargadas;
}

const FRASE_DE_MUESTRA = '¿Sabes qué? Gané la partida con 100 puntos jaja esto es increíble mira';

function normalizar(palabra) {
  return (palabra || '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9ñ]/g, '');
}

function limpiar(palabra, mayus) {
  const t = (palabra || '').trim().replace(/[.,;:…]+$/, '').replace(/^[-—]+/, '');
  return mayus ? t.toUpperCase() : t;
}

/** Contorno con sombras (lo que en el render hace el borde de ASS). */
function contorno(px, color, sombra, brillo) {
  const capas = [];
  if (px > 0) {
    const pasos = 16;
    for (let i = 0; i < pasos; i += 1) {
      const a = (i / pasos) * Math.PI * 2;
      capas.push(`${(Math.cos(a) * px).toFixed(2)}px ${(Math.sin(a) * px).toFixed(2)}px 0 ${color}`);
    }
  }
  if (sombra > 0) capas.push(`${sombra}px ${sombra}px 0 rgba(0,0,0,.44)`);
  if (brillo) capas.push(`0 0 ${Math.max(6, px * 3)}px ${brillo}`, `0 0 ${Math.max(10, px * 5)}px ${brillo}`);
  return capas.join(', ') || 'none';
}

function grupos(palabras, porLinea) {
  const salida = [];
  let actual = [];
  palabras.forEach((p) => {
    const cierra = actual.length && /[.!?…]$/.test(actual[actual.length - 1].crudo);
    if (actual.length >= porLinea || cierra) { salida.push(actual); actual = []; }
    actual.push(p);
  });
  if (actual.length) salida.push(actual);
  return salida;
}

/**
 * Monta la vista previa animada en `nodo` (una caja con la proporción 9:16).
 * Devuelve { cambiar(plantillaId, opciones), parar() }.
 */
export function vistaRotulos(nodo, datos, { plantilla = 'kevil', posicionY = 66, frase = FRASE_DE_MUESTRA } = {}) {
  let tpl = datos.porId[plantilla] || datos.lista[0];
  let altura = posicionY;
  let temporizador = null;
  let paso = 0;
  const capa = document.createElement('div');
  capa.className = 'rot-capa';
  nodo.appendChild(capa);

  const fuertes = new Set(datos.extras.fuertes);
  const esFuerte = (p) => { const n = normalizar(p); return /\d/.test(n) || fuertes.has(n); };

  function pintar() {
    const escala = nodo.clientWidth / 1080;
    if (!escala) return;
    const mayus = tpl.mayus;
    const palabras = frase.split(/\s+/).map((crudo) => ({ crudo, texto: limpiar(crudo, mayus) }))
      .filter((p) => p.texto);
    const lineas = grupos(palabras, tpl.palabras || 3);
    const total = palabras.length;
    const indice = paso % total;
    let cuenta = 0;
    let linea = lineas[0];
    let activa = 0;
    for (const g of lineas) {
      if (indice < cuenta + g.length) { linea = g; activa = indice - cuenta; break; }
      cuenta += g.length;
    }
    const tamano = tpl.tamano * escala;                    // tamaño ASS en píxeles de pantalla
    const css = tamano * tpl.em;                           // lo mismo en CSS
    const borde = tpl.caja ? 0 : (tpl.borde || 0) * escala;
    const sombra = tpl.caja ? 0 : (tpl.sombra || 0) * escala;
    const ancho = nodo.clientWidth * (1 - 0.14);

    const partes = linea.map((p, i) => {
      const fuerte = tpl.enfasis && esFuerte(p.texto);
      const esActiva = i === activa && (tpl.activo || tpl.crece !== 1);
      let color = tpl.color;
      if (esActiva) color = tpl.activo || (fuerte ? tpl.enfasis : tpl.color);
      else if (fuerte) color = tpl.enfasis;
      const estilo = [`color:${color}`];
      if (esActiva && tpl.crece !== 1) estilo.push(`font-size:${tpl.crece}em`);
      let clase = 'rot-palabra';
      if (esActiva && tpl.pastilla) {
        clase += ' rot-pastilla';
        estilo.push(`background:${tpl.pastilla}`, `text-shadow:${contorno(borde / 3, tpl.color_borde, 0)}`);
      }
      return `<span class="${clase}" style="${estilo.join(';')}">${p.texto.replace(/[<>&]/g, '')}</span>`;
    }).join(' ');

    const primeraDelGrupo = activa === 0;
    const emoji = tpl.emojis
      ? linea.map((p) => datos.extras.emojis[normalizar(p.crudo)]).find(Boolean)
      : '';
    const colorEmoji = tpl.activo || tpl.color;
    capa.innerHTML = `
      <div class="rot-linea ${primeraDelGrupo ? (tpl.entrada === 'pop' && !tpl.pastilla ? 'rot-pop' : 'rot-fade') : ''}"
        style="top:${altura}%;font-family:'KV ${tpl.fuente}',system-ui,sans-serif;font-size:${css.toFixed(2)}px;
        font-weight:${tpl.negrita ? 800 : 400};max-width:${ancho}px;
        text-shadow:${contorno(borde, tpl.color_borde, sombra, tpl.brillo)};
        ${tpl.caja ? `background:${tpl.caja}d9;padding:${(0.18 * css).toFixed(1)}px ${(0.32 * css).toFixed(1)}px;border-radius:${(0.28 * css).toFixed(1)}px;` : ''}">
        ${emoji && primeraDelGrupo !== null ? `<span class="rot-emoji" style="font-family:'KV ${datos.extras.fuente_emoji.familia}';color:${colorEmoji};
          font-size:${(tamano * 0.95 * datos.extras.fuente_emoji.em).toFixed(1)}px;
          text-shadow:${contorno(4 * escala, '#000', 3 * escala)}">${emoji}</span>` : ''}
        ${partes}
      </div>`;
    // si no cabe, encoge la línea (como el render)
    const caja = capa.firstElementChild;
    if (caja && caja.scrollWidth > ancho) {
      caja.style.fontSize = `${(css * ancho / caja.scrollWidth).toFixed(2)}px`;
    }
  }

  function vuelta() {
    pintar();
    paso += 1;
    temporizador = setTimeout(vuelta, 420);
  }
  vuelta();

  const observador = new ResizeObserver(() => pintar());
  observador.observe(nodo);

  return {
    cambiar(id, { posicionY: y } = {}) {
      if (id && datos.porId[id]) tpl = datos.porId[id];
      if (y !== undefined) altura = y;
      paso = 0;
      pintar();
    },
    parar() {
      clearTimeout(temporizador);
      observador.disconnect();
      capa.remove();
    },
  };
}

/** Una muestra quieta (para la galería): dos palabras con su estilo. */
export function muestraHtml(tpl, datos) {
  const mayus = tpl.mayus;
  const a = limpiar('Gané', mayus);
  const b = limpiar('100', mayus);
  const escala = 0.2;
  const css = tpl.tamano * tpl.em * escala;
  const borde = tpl.caja ? 0 : Math.max(1, (tpl.borde || 0) * escala);
  const activo = tpl.activo || tpl.color;
  const pastilla = tpl.pastilla ? `background:${tpl.pastilla};` : '';
  const caja = tpl.caja ? `background:${tpl.caja}e6;padding:3px 8px;border-radius:7px;` : '';
  const emoji = tpl.emojis ? `<span style="font-family:'KV ${datos.extras.fuente_emoji.familia}';color:${activo};font-size:${(css * 0.95).toFixed(1)}px;margin-right:4px">${datos.extras.emojis['gane'] || ''}</span>` : '';
  return `<span class="rot-muestra" style="font-family:'KV ${tpl.fuente}',system-ui;font-size:${css.toFixed(1)}px;
    font-weight:${tpl.negrita ? 800 : 400};text-shadow:${contorno(borde, tpl.color_borde, tpl.sombra ? 1.5 : 0, tpl.brillo)};${caja}">
    ${emoji}<span class="rot-palabra ${tpl.pastilla ? 'rot-pastilla' : ''}" style="color:${activo};${pastilla}">${a}</span>
    <span style="color:${tpl.enfasis || tpl.color}">${b}</span></span>`;
}
