// Crear: de un enlace de YouTube o un archivo del PC a clips, eligiendo cómo
// quedan (plantilla de rótulos, encuadre, limpieza, que la IA elija) y viendo
// en un móvil cómo va a salir. Después, el progreso paso a paso.

import { api } from '../lib/api.js';
import { cargarPlantillas, muestraHtml, vistaRotulos } from '../lib/rotulos.js';
import { escapeHtml, fmt, statusPill, toast, toastError } from '../lib/ui.js';

let vista = null;            // la vista previa animada
let sondeo = null;           // el temporizador del progreso
let archivoElegido = null;   // el vídeo del PC, si se ha elegido
let urlObjeto = '';

const DURACIONES = [
  { valor: '15-30', nombre: 'Cortos', detalle: '15-30 s', min: 15, max: 30 },
  { valor: '30-60', nombre: 'Medios', detalle: '30-60 s', min: 30, max: 60 },
  { valor: '30-90', nombre: 'Con contexto', detalle: '30-90 s', min: 30, max: 90 },
  { valor: '60-180', nombre: 'Largos', detalle: '1-3 min', min: 60, max: 180 },
];

function idDeYouTube(url) {
  const m = (url || '').match(/(?:youtu\.be\/|v=|shorts\/|live\/|embed\/)([\w-]{11})/);
  return m ? m[1] : '';
}

function parametros() {
  const q = (location.hash.split('?')[1] || '');
  return Object.fromEntries(new URLSearchParams(q));
}

function limpiarTodo() {
  if (vista) { vista.parar(); vista = null; }
  clearInterval(sondeo); sondeo = null;
  if (urlObjeto) { URL.revokeObjectURL(urlObjeto); urlObjeto = ''; }
}

/* ------------------------------------------------------------ el móvil */
function movilHtml() {
  return `<div class="movil" aria-label="Vista previa en TikTok">
    <div class="movil-pantalla" id="movil-pantalla">
      <div class="movil-fondo" id="movil-fondo"></div>
      <div class="movil-oscuro"></div>
      <div class="movil-barra"><span>9:41</span><i class="movil-isla"></i><span class="movil-iconos">▮▮▮ ◔</span></div>
      <div class="movil-pestanas"><span>Siguiendo</span><b>Para ti</b></div>
      <div class="movil-lado">
        <i class="movil-avatar"></i>
        <span><svg viewBox="0 0 24 24"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.4 5c2 0 3.6 1.2 4.6 2.7C12 6.2 13.6 5 15.6 5 19 5 21.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21z"/></svg>24,5K</span>
        <span><svg viewBox="0 0 24 24"><path d="M4 5h16v11H9l-5 4z"/></svg>482</span>
        <span><svg viewBox="0 0 24 24"><path d="M14 4l7 7-7 7v-4c-5 0-8 1.5-10 5 1-5 4-9 10-10z"/></svg>Compartir</span>
      </div>
      <div class="movil-texto"><b>@kevil</b><p id="movil-titulo">Tu vídeo · Parte 1</p><small>♫ sonido original</small></div>
      <div class="movil-nav"><span>Inicio</span><span>Amigos</span><b>+</b><span>Bandeja</span><span>Perfil</span></div>
    </div>
  </div>
  <p class="muted tiny" style="text-align:center;margin-top:10px">Así saldrán los rótulos. El render final es idéntico.</p>`;
}

function pintarFondo(root, encuadre) {
  const fondo = root.querySelector('#movil-fondo');
  if (!fondo) return;
  const url = root.querySelector('#crear-url')?.value || '';
  const id = idDeYouTube(url);
  let medio = '';
  if (archivoElegido && urlObjeto) {
    medio = `<video src="${urlObjeto}" muted autoplay loop playsinline></video>`;
  } else if (id) {
    medio = `<img src="https://i.ytimg.com/vi/${id}/hqdefault.jpg" alt="" onerror="this.remove()">`;
  }
  fondo.className = `movil-fondo encuadre-${encuadre}`;
  fondo.innerHTML = medio
    ? `<div class="mf-borroso">${medio}</div><div class="mf-principal">${medio}</div>
       ${encuadre === 'split' ? `<div class="mf-zoom">${medio}</div>` : ''}`
    : '<div class="mf-vacio"></div>';
}

/* ------------------------------------------------------------ formulario */
function galeriaHtml(datos, elegida) {
  return datos.lista.map((p) => `
    <button type="button" class="plantilla ${p.id === elegida ? 'on' : ''}" data-plantilla="${p.id}" title="${escapeHtml(p.descripcion)}">
      <span class="plantilla-muestra">${muestraHtml(p, datos)}</span>
      <span class="plantilla-nombre">${escapeHtml(p.nombre)}</span>
    </button>`).join('');
}

function interruptor(id, texto, detalle, activo) {
  return `<label class="opcion">
    <span class="opcion-texto"><b>${texto}</b>${detalle ? `<small>${detalle}</small>` : ''}</span>
    <span class="switch"><input type="checkbox" id="${id}" ${activo ? 'checked' : ''}><span class="track"></span></span>
  </label>`;
}

function formularioHtml(op, datos, ultimos) {
  const v = op.valores;
  const duracion = DURACIONES.find((d) => d.min === v.segment.min_duration && d.max === v.segment.max_duration)?.valor || '30-90';
  return `<div class="crear">
    <div class="crear-form">
      ${ultimos.length ? `<div class="crear-ultimos">${ultimos.map((u) => `
        <a class="crear-ultimo" href="#crear?video=${u.id}">
          <span class="crear-ultimo-icono">▶</span>
          <span class="grow" style="min-width:0"><b>${escapeHtml(u.title)}</b>
            <small class="muted">${u.origin === 'local' ? 'Archivo del PC' : 'YouTube'} · ${fmt.relative ? fmt.relative(u.created_at) : ''}</small></span>
          ${statusPill(u.status)}<span class="muted">→</span></a>`).join('')}</div>` : ''}

      <div class="crear-cabeza">
        <h2>Crea clips de tu vídeo</h2>
        <p class="muted">Pega un enlace de YouTube o elige un vídeo del PC. Kevil busca los mejores momentos,
          los pasa a vertical con rótulos y los deja listos para TikTok y Shorts.</p>
      </div>

      <div class="fuente-tabs" role="tablist">
        <button type="button" class="on" data-fuente="enlace">▶ YouTube</button>
        <button type="button" data-fuente="archivo">⬆ Archivo del PC</button>
      </div>
      <div data-panel="enlace">
        <input id="crear-url" class="crear-url" type="url" placeholder="https://www.youtube.com/watch?v=…" autocomplete="off">
      </div>
      <div data-panel="archivo" hidden>
        <label class="soltar" id="soltar">
          <input type="file" id="crear-archivo" accept="video/*,.mkv" hidden>
          <span class="soltar-icono">⬆</span>
          <b id="soltar-nombre">Suelta aquí un vídeo o pulsa para elegirlo</b>
          <small class="muted">MP4, MOV, MKV, WEBM…
            ${op.voz_en_la_nube ? '· se transcribe con Groq (Whisper)' : '· para rótulos añade una clave de Groq (gratis) en Ajustes → IA'}</small>
        </label>
      </div>
      <textarea id="crear-contexto" rows="2" placeholder="¿De qué va? (opcional) Ej.: «FNF, el mod Animania». Ayuda a la IA a no inventarse nada."></textarea>

      <section class="bloque">
        <header><span class="bloque-icono">✦</span><b>Momentos</b></header>
        ${interruptor('op-ia', 'Que la IA elija los mejores', op.ia
          ? 'Nota de 0 a 100 por gancho, enganche, valor y compartible'
          : 'Sin IA configurada: se puntúan con reglas', v.segment.ai_pick)}
        <div class="duraciones" role="radiogroup">
          ${DURACIONES.map((d) => `<button type="button" data-duracion="${d.valor}" class="${d.valor === duracion ? 'on' : ''}">
            <b>${d.nombre}</b><small>${d.detalle}</small></button>`).join('')}
        </div>
      </section>

      <section class="bloque">
        <header><span class="bloque-icono">▣</span><b>Encuadre</b><small class="muted">cómo pasa a vertical</small></header>
        <div class="encuadres" role="radiogroup">
          ${op.encuadres.map((e) => `<button type="button" data-encuadre="${e.value}" class="${e.value === v.reframe.mode ? 'on' : ''}">
            <i class="mini-encuadre encuadre-${e.value}"></i><span>${escapeHtml(e.label.split('(')[0].trim())}</span></button>`).join('')}
        </div>
      </section>

      <section class="bloque">
        <header><span class="bloque-icono">Aa</span><b>Rótulos</b></header>
        ${interruptor('op-rotulos', 'Poner rótulos', 'Lo que se dice, palabra a palabra', v.subtitles.enabled)}
        <div class="plantillas" id="plantillas">${galeriaHtml(datos, v.subtitles.template)}</div>
        <label class="campo-linea"><span>Altura en pantalla</span>
          <input type="range" id="op-altura" min="20" max="90" step="1" value="${v.subtitles.position_y}"></label>
      </section>

      <section class="bloque">
        <header><span class="bloque-icono">✂</span><b>Limpieza</b><small class="muted">al montar cada clip</small></header>
        ${interruptor('op-muletillas', 'Quitar muletillas', '«eh», «em», «mmm»… (nunca palabras de verdad)', v.cleanup.remove_fillers)}
        ${interruptor('op-silencios', 'Acortar los silencios', 'Donde nadie habla. Ojo en gameplays: si pasa algo en pantalla, también se va', v.cleanup.remove_silences)}
        <label class="campo-linea"><span>Silencio máximo <b id="op-pausa-valor">${v.cleanup.max_pause.toFixed(1)} s</b></span>
          <input type="range" id="op-pausa" min="0.4" max="2" step="0.1" value="${v.cleanup.max_pause}"></label>
      </section>

      <label class="campo-linea"><span>Publicar y programar con el flujo</span>
        <select id="op-flujo">${op.flujos.map((f) => `<option value="${f.id}" ${f.id === op.flow_id ? 'selected' : ''}>${escapeHtml(f.icon || '')} ${escapeHtml(f.name)}</option>`).join('')}</select>
      </label>

      <button class="btn primary crear-boton" id="crear-boton" type="button">Crear clips</button>
      <p class="muted tiny" style="text-align:center">Lo que elijas aquí vale sólo para este vídeo: tus flujos no cambian.</p>
    </div>

    <aside class="crear-vista">${movilHtml()}</aside>
  </div>`;
}

async function pintarFormulario(root) {
  const [op, datos, videos] = await Promise.all([
    api.get('/api/crear/opciones'),
    cargarPlantillas(),
    api.videos('?limit=1').catch(() => []),
  ]);
  const ultimos = (Array.isArray(videos) ? videos : (videos.items || [])).slice(0, 1);
  root.innerHTML = formularioHtml(op, datos, ultimos);

  const estado = {
    fuente: 'enlace',
    plantilla: op.valores.subtitles.template || 'kevil',
    encuadre: op.valores.reframe.mode,
    duracion: root.querySelector('[data-duracion].on')?.dataset.duracion || '30-90',
  };

  vista = vistaRotulos(root.querySelector('#movil-pantalla'), datos, {
    plantilla: estado.plantilla, posicionY: op.valores.subtitles.position_y,
  });
  pintarFondo(root, estado.encuadre);

  const $ = (sel) => root.querySelector(sel);
  const refrescarRotulos = () => {
    const activos = $('#op-rotulos').checked;
    $('#plantillas').classList.toggle('apagado', !activos);
    root.querySelector('.rot-capa').hidden = !activos;
  };
  refrescarRotulos();

  root.querySelectorAll('[data-fuente]').forEach((b) => {
    b.onclick = () => {
      estado.fuente = b.dataset.fuente;
      root.querySelectorAll('[data-fuente]').forEach((x) => x.classList.toggle('on', x === b));
      root.querySelectorAll('[data-panel]').forEach((p) => { p.hidden = p.dataset.panel !== estado.fuente; });
      pintarFondo(root, estado.encuadre);
    };
  });
  $('#crear-url').addEventListener('input', () => {
    pintarFondo(root, estado.encuadre);
    const id = idDeYouTube($('#crear-url').value);
    $('#movil-titulo').textContent = id ? 'Tu vídeo · Parte 1' : 'Tu vídeo · Parte 1';
  });

  const elegirArchivo = (archivo) => {
    if (!archivo) return;
    archivoElegido = archivo;
    if (urlObjeto) URL.revokeObjectURL(urlObjeto);
    urlObjeto = URL.createObjectURL(archivo);
    $('#soltar-nombre').textContent = `${archivo.name} · ${(archivo.size / 1024 / 1024).toFixed(0)} MB`;
    $('#soltar').classList.add('lleno');
    $('#movil-titulo').textContent = `${archivo.name.replace(/\.[^.]+$/, '')} · Parte 1`;
    pintarFondo(root, estado.encuadre);
  };
  $('#crear-archivo').onchange = (e) => elegirArchivo(e.target.files[0]);
  const zona = $('#soltar');
  zona.addEventListener('dragover', (e) => { e.preventDefault(); zona.classList.add('encima'); });
  zona.addEventListener('dragleave', () => zona.classList.remove('encima'));
  zona.addEventListener('drop', (e) => {
    e.preventDefault(); zona.classList.remove('encima');
    elegirArchivo(e.dataTransfer.files[0]);
  });

  root.querySelectorAll('[data-plantilla]').forEach((b) => {
    b.onclick = () => {
      estado.plantilla = b.dataset.plantilla;
      root.querySelectorAll('[data-plantilla]').forEach((x) => x.classList.toggle('on', x === b));
      if (!$('#op-rotulos').checked) { $('#op-rotulos').checked = true; refrescarRotulos(); }
      vista.cambiar(estado.plantilla);
    };
  });
  root.querySelectorAll('[data-encuadre]').forEach((b) => {
    b.onclick = () => {
      estado.encuadre = b.dataset.encuadre;
      root.querySelectorAll('[data-encuadre]').forEach((x) => x.classList.toggle('on', x === b));
      pintarFondo(root, estado.encuadre);
    };
  });
  root.querySelectorAll('[data-duracion]').forEach((b) => {
    b.onclick = () => {
      estado.duracion = b.dataset.duracion;
      root.querySelectorAll('[data-duracion]').forEach((x) => x.classList.toggle('on', x === b));
    };
  });
  $('#op-rotulos').onchange = refrescarRotulos;
  $('#op-altura').oninput = () => vista.cambiar(null, { posicionY: Number($('#op-altura').value) });
  $('#op-pausa').oninput = () => { $('#op-pausa-valor').textContent = `${Number($('#op-pausa').value).toFixed(1)} s`; };

  $('#crear-boton').onclick = async () => {
    const d = DURACIONES.find((x) => x.valor === estado.duracion) || DURACIONES[2];
    const ajustes = {
      subtitles: { enabled: $('#op-rotulos').checked, template: estado.plantilla, position_y: Number($('#op-altura').value) },
      reframe: { mode: estado.encuadre },
      cleanup: {
        remove_fillers: $('#op-muletillas').checked,
        remove_silences: $('#op-silencios').checked,
        max_pause: Number($('#op-pausa').value),
      },
      segment: { ai_pick: $('#op-ia').checked, min_duration: d.min, max_duration: d.max },
    };
    const flujo = Number($('#op-flujo').value) || null;
    const contexto = $('#crear-contexto').value.trim();
    const boton = $('#crear-boton');
    boton.disabled = true;
    try {
      let video;
      if (estado.fuente === 'archivo') {
        if (!archivoElegido) throw new Error('Elige primero el vídeo del PC.');
        boton.textContent = 'Subiendo el vídeo…';
        const form = new FormData();
        form.append('file', archivoElegido);
        if (flujo) form.append('flow_id', String(flujo));
        form.append('ajustes', JSON.stringify(ajustes));
        form.append('contexto', contexto);
        const r = await fetch('/api/crear/archivo', { method: 'POST', body: form });
        const cuerpo = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(cuerpo.detail || 'No se ha podido subir el vídeo.');
        video = cuerpo;
      } else {
        const url = $('#crear-url').value.trim();
        if (!url) throw new Error('Pega el enlace del vídeo de YouTube.');
        boton.textContent = 'Leyendo el vídeo…';
        video = await api.post('/api/crear/enlace', { url, flow_id: flujo, ajustes, contexto });
      }
      toast('¡En marcha! Te enseño cómo va');
      location.hash = `#crear?video=${video.id}`;
    } catch (error) {
      toastError(error);
      boton.disabled = false;
      boton.textContent = 'Crear clips';
    }
  };
}

/* ------------------------------------------------------------ progreso */
const ICONOS = { hecho: '✓', ahora: '', pendiente: '', error: '!' };

function barrasHtml(v) {
  if (!v || !v.total && v.total !== 0) return '';
  const filas = [['gancho', 'Gancho'], ['enganche', 'Enganche'], ['valor', 'Valor'], ['compartible', 'Compartible']];
  return `<div class="nota-barras">${filas.map(([k, n]) => `
    <span>${n}</span><i><em style="width:${(v[k] / 25) * 100}%"></em></i><b>${v[k]}</b>`).join('')}</div>`;
}

function tarjetaClip(c) {
  const v = c.viralidad || {};
  const nota = v.total ?? Math.round((c.score || 0) * 100);
  return `<a class="clip-mini" href="#clips?video=${c.video_id}">
    <div class="clip-mini-img">${c.has_thumb ? `<img src="/api/clips/${c.id}/thumb" alt="" loading="lazy">` : '<i></i>'}
      <span class="clip-nota ${nota >= 70 ? 'alta' : nota >= 45 ? 'media' : ''}">${nota}</span>
      <span class="clip-dur">${fmt.duration ? fmt.duration(c.duration_s) : `${Math.round(c.duration_s)} s`}</span></div>
    <div class="clip-mini-cuerpo">
      <b>${escapeHtml(c.title)}</b>
      ${c.hook ? `<p class="muted small">«${escapeHtml(c.hook)}»</p>` : ''}
      ${barrasHtml(v)}
      ${v.motivo ? `<p class="muted tiny">${escapeHtml(v.motivo)}</p>` : ''}
      <div style="margin-top:6px">${statusPill(c.status)} ${v.fuente === 'ia' ? '<span class="pill info">IA</span>' : ''}</div>
    </div></a>`;
}

async function pintarProgreso(root, videoId) {
  const pintar = async () => {
    const p = await api.get(`/api/crear/${videoId}/progreso`);
    const pasos = p.pasos.map((paso, i) => `
      <li class="cpaso ${paso.estado}">
        <span class="cpaso-marca">${paso.estado === 'ahora' ? '<i class="girando"></i>' : (ICONOS[paso.estado] || i + 1)}</span>
        <span class="cpaso-texto"><b>${escapeHtml(paso.nombre)}</b>${paso.detalle ? `<small>${escapeHtml(paso.detalle)}</small>` : ''}</span>
      </li>`).join('');
    let clips = [];
    if (p.clips) clips = await api.clips(`?video_id=${videoId}`);
    root.innerHTML = `<div class="progreso-crear">
      <a class="muted small" href="#crear">← Crear otro</a>
      <div class="card">
        <div style="display:flex;gap:14px;align-items:center">
          ${p.video.thumbnail_url ? `<img class="progreso-mini" src="${escapeHtml(p.video.thumbnail_url)}" alt="">` : '<span class="progreso-mini vacio">▶</span>'}
          <div class="grow" style="min-width:0"><h3 style="font-size:17px">${escapeHtml(p.video.title)}</h3>
            <p class="muted small">${p.terminado ? (p.clips ? `${p.montados} clip(s) listos` : 'Terminado') : 'Trabajando… puedes cerrar esta pantalla, sigue solo'}</p></div>
          <b class="progreso-num">${Math.round(p.porcentaje * 100)}%</b>
        </div>
        <div class="progreso-barra"><i style="width:${Math.round(p.porcentaje * 100)}%"></i></div>
        <ol class="cpasos">${pasos}</ol>
      </div>
      ${clips.length ? `<div class="card-head" style="margin-top:6px"><h3>Clips</h3>
        <a class="btn sm" href="#clips?video=${videoId}">Revisar y publicar →</a></div>
        <div class="clips-mini">${clips.sort((a, b) => (b.viralidad?.total || 0) - (a.viralidad?.total || 0)).map(tarjetaClip).join('')}</div>` : ''}
    </div>`;
    return p;
  };
  const primera = await pintar();
  if (!primera.terminado && !primera.error) {
    sondeo = setInterval(async () => {
      if (!location.hash.startsWith('#crear')) { clearInterval(sondeo); return; }
      try {
        const p = await pintar();
        if (p.terminado || p.error) clearInterval(sondeo);
      } catch { /* se reintenta en la siguiente vuelta */ }
    }, 2500);
  }
}

export default {
  title: 'Crear',
  subtitle: 'De un vídeo largo a clips verticales con rótulos',
  async render(root) {
    limpiarTodo();
    archivoElegido = null;
    const { video } = parametros();
    if (video) await pintarProgreso(root, Number(video));
    else await pintarFormulario(root);
  },
};
