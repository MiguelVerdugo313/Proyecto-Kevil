// Comunidad: encuestas, avisos y publicaciones para entre vídeo y vídeo.
//
// YouTube no deja que ninguna aplicación publique en la pestaña Comunidad, así
// que Kevil las deja escritas, con su hora, y avisa cuando toca: copiar, pegar
// y listo. Al marcarlas como hechas, el coach las cuenta.

import { api } from '../lib/api.js';
import { emptyState, escapeHtml, fmt, toast, toastError } from '../lib/ui.js';

let reloadView = () => location.reload();

function copiar(texto, mensaje = 'Copiado') {
  navigator.clipboard.writeText(texto).then(
    () => toast(mensaje),
    () => toast('El navegador no ha dejado copiar', 'warn'),
  );
}

const DONDE = {
  youtube: { pill: 'pink', texto: 'YouTube · Comunidad', abrir: 'Abrir YouTube' },
  tiktok: { pill: 'violet', texto: 'TikTok · fotos', abrir: 'Abrir TikTok' },
};

function cuandoLargo(iso) {
  return fmt.date(iso, {
    weekday: 'long', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true,
  });
}

function opcionesHtml(idea) {
  if (!idea.opciones?.length) return '';
  return `<ol class="com-opciones">${idea.opciones.map((o, i) => `
    <li class="${idea.tipo === 'quiz' && idea.correcta === i ? 'correcta' : ''}">
      <span>${escapeHtml(o)}</span>
      ${idea.tipo === 'quiz' && idea.correcta === i ? '<em>correcta</em>' : ''}
      <button class="btn xs ghost" data-copiar-opcion="${idea.id}" data-i="${i}" title="Copiar esta opción">Copiar</button>
    </li>`).join('')}</ol>`;
}

function imagenesHtml(idea) {
  if (!idea.imagenes?.length) return '';
  return `<div class="com-imagenes">${idea.imagenes.map((src, i) => `
    <a href="${escapeHtml(src)}" download="comunidad-${idea.id}-${i + 1}.jpg" title="Descargar la imagen">
      <img src="${escapeHtml(src)}" alt="" loading="lazy"></a>`).join('')}
    <span class="muted tiny">Pulsa una imagen para guardarla y subirla con la publicación.</span></div>`;
}

function tarjeta(idea) {
  const donde = DONDE[idea.plataforma] || DONDE.youtube;
  const hecha = idea.estado === 'hecha';
  const programada = idea.estado === 'programada';
  return `<article class="idea com ${idea.estado === 'descartada' ? 'off' : ''}" data-idea="${idea.id}">
    <div class="idea-head">
      <div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
          <span class="com-icono" aria-hidden="true">${idea.icono}</span>
          <span class="pill">${escapeHtml(idea.tipo_nombre)}</span>
          <span class="pill ${donde.pill}">${donde.texto}</span>
          ${idea.origen === 'ia' ? '<span class="pill info">IA</span>' : ''}
        </div>
        <strong>${escapeHtml(idea.titulo)}</strong>
      </div>
    </div>
    <div class="com-texto" data-texto>${escapeHtml(idea.texto)}</div>
    ${opcionesHtml(idea)}
    ${imagenesHtml(idea)}
    ${idea.por_que ? `<p class="muted tiny" style="margin-top:10px;line-height:1.55">${escapeHtml(idea.por_que)}</p>` : ''}
    <div class="com-cuando">
      ${hecha ? `<span class="pill ok">publicada ${idea.hecha_at ? fmt.relative(idea.hecha_at) : ''}</span>`
        : `<label class="muted tiny" for="cuando-${idea.id}">${programada ? 'Te aviso el' : 'Mejor momento'}</label>
           <input type="datetime-local" id="cuando-${idea.id}" data-cuando value="${idea.cuando ? fmt.toLocalInput(idea.cuando) : ''}">
           ${idea.cuando ? `<span class="muted tiny">${escapeHtml(cuandoLargo(idea.cuando))}</span>` : ''}`}
    </div>
    <div class="idea-acciones">
      <button class="btn sm primary" data-copiar="${idea.id}">Copiar texto</button>
      <a class="btn sm" href="${escapeHtml(idea.enlace)}" target="_blank" rel="noreferrer">${donde.abrir}</a>
      ${hecha ? '' : `
        ${programada ? '' : `<button class="btn sm" data-programar="${idea.id}">Avísame a esa hora</button>`}
        <button class="btn sm ghost" data-hecha="${idea.id}">Ya la publiqué</button>
        <button class="btn sm ghost" data-editar="${idea.id}">Editar</button>
        <button class="btn sm ghost danger" data-descartar="${idea.id}">No me gusta</button>`}
    </div>
  </article>`;
}

function progreso(resumen) {
  const hechas = resumen.hechas_semana;
  const objetivo = resumen.objetivo_semana;
  const pct = Math.min(100, Math.round((hechas / objetivo) * 100));
  return `<div class="com-progreso">
    <div><b>${hechas}</b><span class="muted small"> de ${objetivo} esta semana</span></div>
    <div class="meter"><span style="width:${pct}%"></span></div>
  </div>`;
}

export default {
  title: 'Comunidad',
  subtitle: 'Encuestas, avisos y publicaciones para entre vídeo y vídeo',

  actions: () => [
    { label: '✦ Proponer otras', variant: 'primary', onClick: () => proponerOtras() },
  ],

  async render(root, ctx) {
    reloadView = ctx.reload;
    const datos = await api.get('/api/comunidad');
    const ideas = datos.ideas || [];
    const programadas = ideas.filter((i) => i.estado === 'programada');
    const propuestas = ideas.filter((i) => i.estado === 'propuesta');
    const hechas = ideas.filter((i) => i.estado === 'hecha');

    root.innerHTML = `
      <div class="card com-intro">
        <div>
          <h3>Tu canal, también entre vídeo y vídeo</h3>
          <p class="muted small" style="margin-top:6px;line-height:1.7;max-width:640px">
            Las publicaciones de la pestaña <b>Comunidad</b> de YouTube (encuestas, avisos de directo, imágenes)
            y los carruseles de fotos de TikTok mantienen a tu gente enganchada y suben lo que YouTube enseña de tus vídeos.
            YouTube no deja que ninguna aplicación las publique por ti, así que Kevil te las deja <b>escritas con tus datos</b>,
            te propone la hora y <b>te avisa</b> cuando toca: copiar, pegar y listo.
            ${datos.ia ? '' : '<br>Con una clave de IA en <a href="#ajustes?seccion=ia" style="color:var(--accent)">Ajustes</a> quedan con más gracia.'}
          </p>
        </div>
        ${progreso(datos.resumen)}
      </div>

      ${programadas.length ? `<h3 class="com-seccion">Programadas <span class="muted small">· te aviso a su hora</span></h3>
        <div class="ideas">${programadas.map(tarjeta).join('')}</div>` : ''}

      <h3 class="com-seccion">Propuestas para esta semana</h3>
      ${propuestas.length ? `<div class="ideas">${propuestas.map(tarjeta).join('')}</div>`
        : `<div class="card">${emptyState('💬', 'No quedan propuestas', 'Pulsa «Proponer otras» y Kevil escribe unas nuevas con lo último de tu canal.',
          '<button class="btn primary" data-proponer>Proponer otras</button>')}</div>`}

      ${hechas.length ? `<details class="com-hechas"><summary class="muted small">Ya publicadas (${hechas.length})</summary>
        <div class="ideas" style="margin-top:12px">${hechas.map(tarjeta).join('')}</div></details>` : ''}`;

    const buscar = (id) => ideas.find((i) => i.id === id);
    const cambiar = async (id, cambios, mensaje) => {
      try {
        await api.patch(`/api/comunidad/${id}`, cambios);
        if (mensaje) toast(mensaje);
        ctx.reload();
      } catch (error) { toastError(error); }
    };
    const cuandoDe = (id) => {
      const valor = root.querySelector(`[data-idea="${id}"] [data-cuando]`)?.value;
      return valor ? fmt.fromLocalInput(valor) : null;
    };

    root.querySelectorAll('[data-proponer]').forEach((b) => { b.onclick = () => proponerOtras(); });
    root.querySelectorAll('[data-copiar]').forEach((b) => {
      b.onclick = () => copiar(buscar(b.dataset.copiar).texto, 'Texto copiado: pégalo en la publicación');
    });
    root.querySelectorAll('[data-copiar-opcion]').forEach((b) => {
      b.onclick = () => copiar(buscar(b.dataset.copiarOpcion).opciones[Number(b.dataset.i)], 'Opción copiada');
    });
    root.querySelectorAll('[data-programar]').forEach((b) => {
      b.onclick = () => {
        const cuando = cuandoDe(b.dataset.programar);
        if (!cuando) { toast('Elige antes el día y la hora', 'warn'); return; }
        cambiar(b.dataset.programar, { estado: 'programada', cuando }, `Te aviso el ${cuandoLargo(cuando)}`);
      };
    });
    // cambiar la hora de una programada la reprograma
    root.querySelectorAll('[data-cuando]').forEach((campo) => {
      campo.onchange = () => {
        const id = campo.closest('[data-idea]').dataset.idea;
        if (buscar(id).estado !== 'programada' || !campo.value) return;
        const cuando = fmt.fromLocalInput(campo.value);
        cambiar(id, { cuando }, `Te aviso el ${cuandoLargo(cuando)}`);
      };
    });
    root.querySelectorAll('[data-hecha]').forEach((b) => {
      b.onclick = () => cambiar(b.dataset.hecha, { estado: 'hecha' }, '¡Bien! Cuenta para tu semana');
    });
    root.querySelectorAll('[data-descartar]').forEach((b) => {
      b.onclick = () => cambiar(b.dataset.descartar, { estado: 'descartada' }, 'Quitada');
    });
    root.querySelectorAll('[data-editar]').forEach((b) => {
      b.onclick = () => {
        const tarjetaNodo = root.querySelector(`[data-idea="${b.dataset.editar}"]`);
        const caja = tarjetaNodo.querySelector('[data-texto]');
        if (caja.querySelector('textarea')) return;
        const idea = buscar(b.dataset.editar);
        caja.innerHTML = `<textarea style="min-height:120px;width:100%">${escapeHtml(idea.texto)}</textarea>
          <button class="btn sm primary" style="margin-top:8px" data-guardar>Guardar</button>`;
        caja.querySelector('[data-guardar]').onclick = () => cambiar(idea.id, {
          texto: caja.querySelector('textarea').value,
        }, 'Guardado');
      };
    });
  },
};

async function proponerOtras() {
  toast('Escribiendo propuestas con lo último de tu canal…');
  try {
    await api.post('/api/comunidad/proponer', { ia: true });
    toast('Listas: propuestas nuevas');
    reloadView();
  } catch (error) { toastError(error); }
}
