// Estudio: sube un vídeo y sal con el título, la descripción, las etiquetas
// y las miniaturas listas para pegar en YouTube.

import { api } from '../lib/api.js';
import {
  STATUS_LABELS, confirmDialog, escapeHtml, fmt, modal, toast, toastError,
} from '../lib/ui.js';

let selectedId = null;
let reloadView = () => location.reload();

/* ----------------------------------------------------------- utilidades */
function copiar(texto, mensaje = 'Copiado') {
  navigator.clipboard.writeText(texto).then(
    () => toast(mensaje),
    () => toast('El navegador no ha dejado copiar', 'warn'),
  );
}

function marcaRevision(nivel) {
  return { ok: '✓', warn: '!', bad: '×' }[nivel] || '·';
}

/* --------------------------------------------------------------- subida */
function subirDialog(reload, archivos = null) {
  modal({
    title: 'Subir un vídeo tuyo',
    body: `
      <p class="muted small" style="line-height:1.7">
        Sube el vídeo tal cual lo tienes y Kevil te devuelve el título, la descripción
        con capítulos, las etiquetas, los hashtags y varias miniaturas para elegir.
      </p>
      <div class="dropzone" id="dz">
        <div class="big">⬆️</div>
        <strong>Arrastra el vídeo aquí</strong>
        <span class="muted small">o pulsa para elegirlo · mp4, mov, mkv, webm…</span>
        <input type="file" id="file" accept="video/*" hidden>
      </div>
      <div id="elegido" class="muted small"></div>
      <div class="field"><label>¿De qué va el vídeo? <span class="muted tiny">(lo que más ayuda)</span></label>
        <textarea id="u-contexto" style="min-height:74px"
          placeholder="Ej.: Gameplay de Friday Night Funkin', jugué la actualización del mod Animania"></textarea>
        <span class="help">Dilo con tus palabras: el juego, qué haces, si es directo. Kevil escribe el título, la
          descripción, las etiquetas y las miniaturas <b>sólo con esto</b> y lo que se oiga en el vídeo; no se inventa nada.</span></div>
      <div class="field"><label>Título provisional</label>
        <input type="text" id="u-title" placeholder="Se usa el nombre del archivo si lo dejas vacío"></div>
      <div class="form-grid">
        <div class="field"><label class="switch"><input type="checkbox" id="u-ai" checked>
          <span class="track"></span><span class="switch-label">Generar con IA</span></label></div>
        <div class="field"><label class="switch"><input type="checkbox" id="u-img">
          <span class="track"></span><span class="switch-label">Miniatura con imagen de IA</span></label></div>
        <div class="field full"><label class="switch"><input type="checkbox" id="u-clips" checked>
          <span class="track"></span><span class="switch-label">Sacar también clips verticales para TikTok y Shorts</span></label></div>
      </div>
      <div id="progreso" hidden>
        <div class="bar"><i id="barra" style="width:0%"></i></div>
        <div class="muted tiny" id="progreso-txt" style="margin-top:6px">Subiendo…</div>
      </div>`,
    actions: [
      { label: 'Cancelar' },
      {
        label: 'Subir y generar',
        variant: 'primary',
        onClick: (root) => new Promise((resolve, reject) => {
          const input = root.querySelector('#file');
          if (!input.files || !input.files[0]) {
            toast('Elige primero un vídeo', 'warn');
            resolve(false);
            return;
          }
          const datos = new FormData();
          datos.append('file', input.files[0]);
          datos.append('title', root.querySelector('#u-title').value.trim());
          datos.append('contexto', root.querySelector('#u-contexto').value.trim());
          datos.append('use_ai', root.querySelector('#u-ai').checked);
          datos.append('ai_image', root.querySelector('#u-img').checked);
          datos.append('make_clips', root.querySelector('#u-clips').checked);

          root.querySelector('#progreso').hidden = false;
          const boton = root.querySelector('[data-action="1"]');
          boton.disabled = true;

          // XMLHttpRequest para poder mostrar el progreso de la subida
          const peticion = new XMLHttpRequest();
          peticion.open('POST', '/api/videos/upload');
          peticion.upload.onprogress = (evento) => {
            if (!evento.lengthComputable) return;
            const porcentaje = Math.round((evento.loaded / evento.total) * 100);
            root.querySelector('#barra').style.width = `${porcentaje}%`;
            root.querySelector('#progreso-txt').textContent =
              `Subiendo… ${porcentaje}% (${(evento.loaded / 1048576).toFixed(1)} MB)`;
          };
          peticion.onload = () => {
            if (peticion.status >= 200 && peticion.status < 300) {
              const video = JSON.parse(peticion.responseText);
              selectedId = video.id;
              toast('Vídeo subido: generando el kit…');
              reload();
              resolve(true);
            } else {
              let detalle = 'Error al subir';
              try { detalle = JSON.parse(peticion.responseText).detail || detalle; } catch { /* nada */ }
              boton.disabled = false;
              reject(new Error(detalle));
            }
          };
          peticion.onerror = () => { boton.disabled = false; reject(new Error('Fallo de red al subir')); };
          peticion.send(datos);
        }),
      },
    ],
    onOpen(root) {
      const zona = root.querySelector('#dz');
      const input = root.querySelector('#file');
      const elegido = root.querySelector('#elegido');
      const mostrar = () => {
        const archivo = input.files?.[0];
        elegido.textContent = archivo
          ? `${archivo.name} · ${(archivo.size / 1048576).toFixed(1)} MB`
          : '';
        if (archivo && !root.querySelector('#u-title').value) {
          root.querySelector('#u-title').value = archivo.name.replace(/\.[^.]+$/, '');
        }
      };
      zona.onclick = () => input.click();
      input.onchange = mostrar;
      if (archivos && archivos.length) { input.files = archivos; mostrar(); }
      zona.ondragover = (event) => { event.preventDefault(); zona.classList.add('over'); };
      zona.ondragleave = () => zona.classList.remove('over');
      zona.ondrop = (event) => {
        event.preventDefault();
        zona.classList.remove('over');
        input.files = event.dataTransfer.files;
        mostrar();
      };
    },
  });
}

/* ------------------------------------------------------------- el kit */
function kitHtml(data) {
  const kit = data.kit || {};
  const video = data.video;
  const titulos = kit.titles || [];
  const elegido = kit.chosen_title || titulos[0] || '';

  if (data.generando) return generandoHtml(video, data.generando);
  if (kit.falta_contexto) return preguntaHtml(video, kit, data);
  if (!Object.keys(kit).length) {
    return `<div class="card">
      <div class="kit-vacio">
        <div>
          <p class="nota-mano">paso 2 de 3</p>
          <h3 style="font-size:24px;margin-top:6px">Prepara el kit de <span class="acento">este vídeo</span></h3>
          <p class="muted small" style="margin-top:10px;line-height:1.7">
            <b style="color:var(--text)">${escapeHtml(video.title)}</b> · ${fmt.duration(video.duration_s)}<br>
            Kevil lee el vídeo y te deja listo todo lo que pide YouTube. Tarda un par de minutos
            y puedes seguir haciendo otras cosas mientras.
          </p>
          <div class="field" style="margin-top:14px">
            <label>¿De qué va el vídeo?</label>
            <textarea id="g-contexto" style="min-height:70px"
              placeholder="Ej.: Gameplay de Friday Night Funkin', jugué la actualización del mod Animania">${escapeHtml(video.contexto || '')}</textarea>
          </div>
          <div style="display:flex;flex-direction:column;gap:10px;margin:16px 0 18px">
            <label class="switch"><input type="checkbox" id="g-ia" ${data.ai?.enabled ? 'checked' : ''} ${data.ai?.enabled ? '' : 'disabled'}>
              <span class="track"></span><span class="switch-label">Con IA ${data.ai?.enabled ? '' : '(añade una clave en Ajustes)'}</span></label>
            <label class="switch"><input type="checkbox" id="g-img" ${data.ai?.images_supported ? '' : 'disabled'}>
              <span class="track"></span><span class="switch-label">Fondo de miniatura hecho con IA</span></label>
          </div>
          <button class="btn primary" data-generar>✦ Generar el kit</button>
        </div>
        <div class="que-sale">
          ${[
            ['Títulos', '5 opciones, pensadas para que hagan clic'],
            ['Descripción', 'con capítulos y enlaces'],
            ['Etiquetas y hashtags', 'para que YouTube lo entienda'],
            ['Miniaturas', 'varias en 1280×720 para elegir'],
            ['Revisión', 'lo que falta antes de publicar'],
            ['Clips', 'verticales para TikTok y Shorts'],
          ].map(([t, d]) => `<div class="item"><strong>${t}</strong><span>${d}</span></div>`).join('')}
        </div>
      </div>
    </div>`;
  }

  return `
    <div class="card">
      <div class="card-head">
        <div style="min-width:0">
          <h3>${escapeHtml(video.title)}</h3>
          <p class="muted small" style="margin-top:4px">
            ${fmt.duration(video.duration_s)} ·
            ${kit.generated_by?.startsWith('ia') ? `generado con IA (${escapeHtml(kit.generated_by.slice(3))})` : 'generado en local'}
            ${kit.updated_at ? ` · ${fmt.relative(kit.updated_at)}` : ''}
          </p>
        </div>
        <div style="display:flex;gap:7px;flex-wrap:wrap">
          <button class="btn sm ghost" data-generar>Regenerar</button>
          ${video.clips_count
            ? `<a class="btn sm" href="#clips?video=${video.id}">${video.clips_count === 1 ? 'Ver su clip' : `Ver sus ${video.clips_count} clips`}</a>`
            : (video.downloaded ? '<button class="btn sm" data-sacar-clips>Sacar clips</button>' : '')}
          <button class="btn sm primary" data-subir-youtube>Subir a YouTube</button>
        </div>
      </div>

      ${kit.youtube?.url ? `<div class="tip" style="margin-bottom:16px">
        <b>Ya está en tu canal</b> como ${escapeHtml(PRIVACIDAD[kit.youtube.privacy] || kit.youtube.privacy || '')}
        · <a href="${escapeHtml(kit.youtube.url)}" target="_blank" rel="noreferrer" style="color:var(--accent-2)">abrirlo en YouTube</a>
        ${kit.youtube.warning ? `<br><span style="color:var(--amber)">${escapeHtml(kit.youtube.warning)}</span>` : ''}
      </div>` : ''}

      ${kit.warning ? `<p class="small" style="color:var(--amber);margin-bottom:14px">${escapeHtml(kit.warning)}</p>` : ''}

      <details class="de-que-va" ${video.contexto ? '' : 'open'}>
        <summary><b>De qué va el vídeo</b> <span class="muted small">· ${video.contexto
          ? escapeHtml(video.contexto.slice(0, 90)) + (video.contexto.length > 90 ? '…' : '')
          : 'no lo has contado: cuéntalo y el kit sale mucho mejor'}</span></summary>
        <textarea id="g-contexto" style="min-height:70px;margin-top:10px"
          placeholder="Ej.: Gameplay de Friday Night Funkin', jugué la actualización del mod Animania">${escapeHtml(video.contexto || '')}</textarea>
        <div style="display:flex;gap:8px;margin-top:8px;align-items:center;flex-wrap:wrap">
          <button class="btn sm primary" data-rehacer>Rehacer el kit con esto</button>
          <span class="muted tiny">Kevil escribe sólo con esto y lo que se oiga en el vídeo.</span>
        </div>
      </details>
      ${kit.notes ? `<div class="tip"><b>Consejo:</b> ${escapeHtml(kit.notes)}</div>` : ''}

      <div class="kit-grid">
        <div>
          <div class="field">
            <label>Títulos propuestos <span class="muted tiny">(pulsa para elegir)</span></label>
            <div class="opciones">
              ${titulos.map((titulo) => `
                <button class="opcion ${titulo === elegido ? 'sel' : ''}" data-titulo="${escapeHtml(titulo)}">
                  <span>${escapeHtml(titulo)}</span>
                  <em>${titulo.length}</em>
                </button>`).join('')}
            </div>
            <button class="btn sm" style="margin-top:8px" data-copiar="titulo">Copiar el título elegido</button>
          </div>

          <div class="field" style="margin-top:18px">
            <label>Descripción</label>
            <textarea id="kit-desc" style="min-height:230px">${escapeHtml(kit.description || '')}</textarea>
            <div style="display:flex;gap:7px;margin-top:8px">
              <button class="btn sm" data-copiar="desc">Copiar descripción</button>
              <button class="btn sm ghost" data-guardar>Guardar cambios</button>
            </div>
          </div>
        </div>

        <div>
          <div class="field">
            <label>Etiquetas <span class="muted tiny">(${(kit.tags || []).length})</span></label>
            <div class="tags-view">${(kit.tags || []).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join('') || '<span class="muted small">ninguna</span>'}</div>
            <button class="btn sm" style="margin-top:8px" data-copiar="tags">Copiar etiquetas</button>
          </div>

          <div class="field" style="margin-top:16px">
            <label>Hashtags</label>
            <div class="tags-view">${(kit.hashtags || []).map((t) => `<span class="tag">#${escapeHtml(t)}</span>`).join('') || '<span class="muted small">ninguno</span>'}</div>
          </div>

          ${(kit.chapters || []).length ? `
          <div class="field" style="margin-top:16px">
            <label>Capítulos</label>
            <div class="chapters">
              ${kit.chapters.map((c) => `<div><b>${escapeHtml(fmt.duration(c.time))}</b> ${escapeHtml(c.title)}</div>`).join('')}
            </div>
          </div>` : ''}

          <div class="field" style="margin-top:16px">
            <label>Revisión antes de publicar</label>
            <div class="revision">
              ${(kit.review || []).map((c) => `
                <div class="check ${escapeHtml(c.level)}">
                  <span class="marca">${marcaRevision(c.level)}</span>${escapeHtml(c.text)}
                </div>`).join('')}
            </div>
          </div>
        </div>
      </div>

      <div style="margin-top:22px">
        <label class="muted small" style="display:block;margin-bottom:10px">
          Miniaturas <span class="tiny">(1280×720 · descarga la que más te guste)</span>
        </label>
        ${(kit.thumbnails || []).length ? `<div class="miniaturas">
          ${kit.thumbnails.map((thumb, index) => `
            <figure class="mini ${kit.chosen_thumbnail === index ? 'sel' : ''}" data-mini="${index}">
              <img src="/api/videos/${video.id}/kit/thumbnail/${index}?v=${encodeURIComponent(kit.updated_at || '')}" alt="" loading="lazy">
              <figcaption>
                <span class="pill ${thumb.source === 'ia' ? 'violet' : ''}">${escapeHtml(thumb.source)}</span>
                <span class="muted tiny">${escapeHtml(thumb.style || '')}</span>
                <a class="btn sm ghost" href="/api/videos/${video.id}/kit/thumbnail/${index}?download=true" download>Descargar</a>
              </figcaption>
            </figure>`).join('')}
        </div>` : `<div class="sin-miniaturas">
          <p class="small"><b>No han salido miniaturas de este vídeo.</b></p>
          ${(kit.thumbnail_errors || []).map((e) => `<p class="tiny" style="color:var(--amber);margin-top:6px">${escapeHtml(e)}</p>`).join('')}
          <button class="btn sm" style="margin-top:10px" data-miniaturas>Volver a intentarlo</button>
        </div>`}
        ${(kit.thumbnails || []).length ? (kit.thumbnail_errors || []).map((e) => `<p class="tiny" style="color:var(--amber);margin-top:8px">${escapeHtml(e)}</p>`).join('') : ''}
        ${kit.thumbnail_prompt ? `<div class="prompt-miniatura">
          <label class="muted small">Prompt para crear la miniatura con otra IA
            <span class="tiny">(ChatGPT, Gemini, Ideogram, Leonardo… pega esto y pide la imagen)</span></label>
          <textarea id="kit-prompt" readonly style="min-height:86px">${escapeHtml(kit.thumbnail_prompt)}</textarea>
          <button class="btn sm" style="margin-top:8px" data-copiar="prompt">Copiar el prompt</button>
        </div>` : ''}
      </div>
    </div>`;
}

// Sin voz en el vídeo y sin saber de qué va, lo que escriba la IA es inventado:
// mejor preguntar. Una línea basta.
function preguntaHtml(video, kit, data) {
  return `<div class="card pregunta-kit">
    <p class="nota-mano">antes de escribir nada…</p>
    <h3 style="font-size:22px;margin-top:6px">¿De qué va <span class="acento">este vídeo</span>?</h3>
    <p class="muted small" style="margin-top:10px;line-height:1.7;max-width:640px">
      <b style="color:var(--text)">${escapeHtml(video.title)}</b> · ${fmt.duration(video.duration_s)}<br>
      Kevil no puede saberlo solo: ${escapeHtml(kit.motivo || 'no hay voz que transcribir')}. Cuéntalo con tus
      palabras (el juego, qué haces, si es un directo) y el título, la descripción, las etiquetas y las
      miniaturas saldrán de eso, sin inventar.
    </p>
    <textarea id="g-contexto" style="min-height:90px;margin-top:14px"
      placeholder="Ej.: Gameplay de Friday Night Funkin', jugué la actualización del mod Animania. Sin comentarios, solo jugando.">${escapeHtml(video.contexto || '')}</textarea>
    <div style="display:flex;gap:10px;margin-top:12px;align-items:center;flex-wrap:wrap">
      <button class="btn primary" data-rehacer>✦ Preparar el kit con esto</button>
      <button class="btn ghost sm" data-forzar>Hazlo sólo con el título</button>
      ${data.ai?.enabled ? '' : '<span class="muted tiny">Sin IA: se hará con tus palabras tal cual.</span>'}
    </div>
  </div>`;
}

function generandoHtml(video, trabajo) {
  const porcentaje = Math.round((trabajo.progress || 0) * 100);
  return `<div class="card">
    <p class="nota-mano">un momento…</p>
    <h3 style="font-size:22px;margin-top:6px">Preparando el kit de «${escapeHtml(video.title.slice(0, 70))}»</h3>
    <p class="muted small" style="margin:10px 0 16px">${escapeHtml(trabajo.message || 'Leyendo el vídeo…')}</p>
    <div class="bar" style="height:7px"><i style="width:${porcentaje}%"></i></div>
    <p class="muted tiny" style="margin-top:8px">${porcentaje}% · esta pantalla se actualiza sola</p>
  </div>`;
}

/* Los tres pasos, siempre a la vista: dónde estás y qué toca */
function pasosHtml(data) {
  const kit = data?.kit || {};
  const hayVideo = Boolean(data?.video);
  const hayKit = Object.keys(kit).length > 0 && !kit.falta_contexto;
  const subido = Boolean(kit.youtube?.url);
  const estado = (hecho, actual) => (hecho ? 'hecho' : (actual ? 'actual' : ''));
  return `<div class="pasos">
    <div class="paso ${estado(hayVideo, !hayVideo)}"><span class="n">${hayVideo ? '✓' : '1'}</span>
      <div><strong>Sube tu vídeo</strong><span>Arrástralo aquí abajo o pulsa «Subir vídeo». También sirven los de tu canal.</span></div></div>
    <div class="paso ${estado(hayKit, hayVideo && !hayKit)}"><span class="n">${hayKit ? '✓' : '2'}</span>
      <div><strong>Kevil prepara el kit</strong><span>Títulos, descripción, hashtags, miniaturas y clips.</span></div></div>
    <div class="paso ${estado(subido, hayKit && !subido)}"><span class="n">${subido ? '✓' : '3'}</span>
      <div><strong>Publica</strong><span>Súbelo a YouTube desde aquí y deja los clips en la agenda.</span></div></div>
  </div>`;
}

function filaVideo(video) {
  const estado = video.falta_contexto
    ? { punto: 'warn', texto: 'dime de qué va' }
    : video.has_kit
    ? { punto: 'ok', texto: `kit listo · ${video.kit_thumbnails} miniaturas` }
    : video.status === 'error'
      ? { punto: 'bad', texto: 'con error' }
      : ['downloading', 'processing', 'queued'].includes(video.status)
        ? { punto: 'run', texto: STATUS_LABELS[video.status] || video.status }
        : { punto: '', texto: 'sin kit todavía' };
  return `<button class="video-fila ${video.id === selectedId ? 'sel' : ''}" data-video="${video.id}" type="button">
    ${video.thumbnail_url
      ? `<img src="${escapeHtml(video.thumbnail_url)}" alt="" loading="lazy">`
      : `<span class="sin-imagen">${video.origin === 'local' ? '📁' : '▶'}</span>`}
    <span class="meta">
      <strong>${escapeHtml(video.title)}</strong>
      <span><i class="estado-punto ${estado.punto}"></i>${escapeHtml(estado.texto)}${video.duration_s ? ` · ${fmt.duration(video.duration_s)}` : ''}</span>
    </span>
  </button>`;
}

/* -------------------------------------------------------------- vista */
/* ------------------------------------------------ subir a YouTube */
const PRIVACIDAD = { public: 'público', unlisted: 'oculto', private: 'privado' };

function subirAYouTubeDialog(data, reload) {
  const video = data.video || {};
  const kit = data.kit || {};
  const titulo = kit.chosen_title || (kit.titles || [])[0] || video.title || '';
  const miniaturas = kit.thumbnails || [];
  const elegida = Number.isInteger(kit.chosen_thumbnail) ? kit.chosen_thumbnail : 0;

  modal({
    title: 'Subir a YouTube',
    wide: true,
    body: `
      <p class="muted small" style="line-height:1.7">
        Se sube <b>el vídeo tal cual</b> a tu canal, con el título, la descripción,
        las etiquetas y la miniatura que has elegido aquí. Nada de copiar y pegar.
      </p>

      <div class="form-grid" style="margin-top:16px">
        <div class="field full">
          <label>Título</label>
          <input type="text" id="sub-titulo" value="${escapeHtml(titulo)}" maxlength="100">
          <span class="help">Hasta 100 caracteres, que es lo que admite YouTube.</span>
        </div>
        <div class="field full">
          <label>Descripción</label>
          <textarea id="sub-desc" style="min-height:150px">${escapeHtml(kit.description || '')}</textarea>
        </div>
        <div class="field">
          <label>Quién puede verlo</label>
          <select id="sub-privacidad">
            <option value="private">Privado (sólo tú, para revisarlo antes)</option>
            <option value="unlisted">Oculto (sólo con el enlace)</option>
            <option value="public">Público</option>
          </select>
        </div>
        <div class="field">
          <label>Publicarlo más tarde <span class="muted tiny">(opcional)</span></label>
          <input type="datetime-local" id="sub-cuando">
          <span class="help">Si pones fecha, sube en privado y se hace público solo.</span>
        </div>
      </div>

      ${miniaturas.length ? `
        <div class="field full" style="margin-top:6px">
          <label>Miniatura</label>
          <div class="miniaturas" id="sub-minis">
            ${miniaturas.map((thumb, index) => `
              <figure class="mini ${index === elegida ? 'sel' : ''}" data-elegir="${index}">
                <img src="/api/videos/${video.id}/kit/thumbnail/${index}" alt="" loading="lazy">
                <figcaption><span class="muted tiny">${escapeHtml(thumb.style || '')}</span></figcaption>
              </figure>`).join('')}
          </div>
          <span class="help">YouTube sólo admite miniatura propia si tienes el canal
            verificado por teléfono. Si no la acepta, el vídeo sube igual.</span>
        </div>` : ''}

      <p class="muted tiny" style="margin-top:14px">
        Cada subida gasta 1.600 de las 10.000 unidades diarias que da Google:
        salen unas <b>6 al día</b> entre vídeos y Shorts.
      </p>`,
    onOpen: (nodo) => {
      let seleccion = elegida;
      nodo.querySelectorAll('[data-elegir]').forEach((figura) => {
        figura.onclick = () => {
          seleccion = Number(figura.dataset.elegir);
          nodo.querySelectorAll('[data-elegir]').forEach((f) => f.classList.remove('sel'));
          figura.classList.add('sel');
        };
      });
      nodo.dataset.seleccion = String(seleccion);
      nodo.addEventListener('click', () => {
        const marcada = nodo.querySelector('[data-elegir].sel');
        if (marcada) nodo.dataset.seleccion = marcada.dataset.elegir;
      });
    },
    actions: [
      { label: 'Cancelar' },
      { label: 'Subir ahora', variant: 'primary', onClick: async (nodo) => {
        const cuando = nodo.querySelector('#sub-cuando').value;
        await api.post(`/api/videos/${video.id}/youtube`, {
          title: nodo.querySelector('#sub-titulo').value.trim(),
          description: nodo.querySelector('#sub-desc').value,
          tags: kit.tags || [],
          thumbnail_index: miniaturas.length ? Number(nodo.dataset.seleccion || 0) : null,
          privacy_status: nodo.querySelector('#sub-privacidad').value,
          publish_at: cuando ? new Date(cuando).toISOString() : null,
        });
        toast('Subiendo a YouTube… lo verás en el motor');
        setTimeout(reload, 900);
        return true;
      } },
    ],
  });
}

/* ---------------------------------------------- miniatura para un directo */
function miniaturaDirectoDialog() {
  modal({
    title: 'Miniatura para un directo',
    body: `
      <p class="muted small" style="line-height:1.7">
        Para un directo que todavía no has hecho no hay fotogramas de los que
        tirar. Kevil coge el fondo de <b>tu carpeta de marca</b>
        (<span class="mono">data/branding</span>), eligiendo lo que mejor pegue
        con el tema; si ahí no hay nada, lo genera con IA; y si tampoco, monta
        un fondo con tu color.
      </p>
      <div class="form-grid" style="margin-top:16px">
        <div class="field full"><label>Texto de la miniatura</label>
          <input type="text" id="dir-texto" maxlength="40" placeholder="ZOMBIS A LAS 7">
          <span class="help">Dos o tres palabras en grande. Más no se lee.</span></div>
        <div class="field full"><label>¿De qué va el directo?</label>
          <input type="text" id="dir-tema" placeholder="zombis, supervivencia, Minecraft">
          <span class="help">Con esto se elige qué imagen tuya usar de fondo.</span></div>
      </div>
      <div id="dir-salida" style="margin-top:16px"></div>`,
    actions: [
      { label: 'Cerrar' },
      { label: 'Crear la miniatura', variant: 'primary', onClick: async (root) => {
        const texto = root.querySelector('#dir-texto').value.trim();
        if (!texto) { toastError('Escribe el texto que va en la miniatura.'); return false; }
        const salida = root.querySelector('#dir-salida');
        salida.innerHTML = '<span class="muted small">Montándola…</span>';
        try {
          const r = await api.post('/api/brandkit/live-thumbnail', {
            text: texto, topic: root.querySelector('#dir-tema').value.trim(),
          });
          const origen = { marca: 'tu carpeta de marca', ia: 'IA', degradado: 'tu color' };
          salida.innerHTML = `
            <img src="${r.url}&t=${Date.now()}" alt="Miniatura del directo"
              style="width:100%;border-radius:var(--r);border:1px solid var(--line)">
            <p class="muted tiny" style="margin-top:8px">
              Fondo: ${escapeHtml(origen[r.source] || r.source)}
              ${r.background ? `· ${escapeHtml(r.background)}` : ''}
              · guardada en <span class="mono">data/media/miniaturas</span>
            </p>`;
        } catch (error) {
          salida.innerHTML = `<span style="color:var(--red)" class="small">${escapeHtml(error.message)}</span>`;
        }
        return false;
      } },
    ],
  });
}

export default {
  title: 'Estudio',
  subtitle: 'Sube un vídeo y sal con todo listo para publicar',
  refreshMs: 8000,

  actions: [
    { label: '🎥 Miniatura de directo', onClick: () => miniaturaDirectoDialog() },
    { label: '⬆ Subir vídeo', variant: 'primary', onClick: () => subirDialog(reloadView) },
  ],

  async render(root, ctx) {
    reloadView = ctx.reload;
    const [videos, aiStatus, trabajos] = await Promise.all([
      api.get('/api/studio/videos?limit=80'),
      api.get('/api/ai/status'),
      api.jobs('?limit=20'),
    ]);

    if (new URLSearchParams(location.hash.split('?')[1] || '').get('subir')) {
      setTimeout(() => subirDialog(ctx.reload), 200);
    }

    if (!videos.length) {
      root.innerHTML = `
        ${pasosHtml(null)}
        ${aiStatus.enabled ? '' : avisoSinIA(aiStatus)}
        <div class="card">
          <div class="dropzone" data-soltar>
            <div class="big">⬆️</div>
            <p class="nota-mano">empieza aquí</p>
            <strong style="font-size:17px">Arrastra tu vídeo aquí</strong>
            <span class="muted small">o pulsa para elegirlo · mp4, mov, mkv, webm…</span>
          </div>
        </div>`;
      activarSoltar(root, ctx);
      return;
    }

    if (!videos.some((v) => v.id === selectedId)) {
      selectedId = (videos.find((v) => v.has_kit) || videos[0]).id;
    }
    const data = await api.get(`/api/videos/${selectedId}/kit`);
    data.generando = trabajos.find((job) => ['build_kit', 'analyze_local'].includes(job.kind)
      && ['running', 'pending'].includes(job.status) && Number(job.payload?.video_id) === selectedId);

    root.innerHTML = `
      ${pasosHtml(data)}
      ${aiStatus.enabled ? '' : avisoSinIA(aiStatus)}
      <div class="estudio">
        <div class="card" style="padding:18px">
          <div class="dropzone" data-soltar style="padding:18px 14px;margin-bottom:14px">
            <strong>⬆ Subir vídeo</strong>
            <span class="muted tiny">arrástralo aquí o pulsa</span>
          </div>
          <input type="text" id="buscar-video" placeholder="Buscar en mis vídeos…" style="margin-bottom:10px">
          <div class="videos-lista">${videos.map(filaVideo).join('')}</div>
        </div>

        <div id="kit">${kitHtml(data)}</div>
      </div>`;

    activarSoltar(root, ctx);
    root.querySelector('#buscar-video').oninput = (e) => {
      const q = e.target.value.trim().toLowerCase();
      root.querySelectorAll('.video-fila').forEach((fila) => {
        fila.hidden = q && !fila.textContent.toLowerCase().includes(q);
      });
    };
    bind(root, data, ctx);
  },

  async onRefresh(root) {
    const activos = await api.jobs('?limit=10');
    const enMarcha = activos.some((job) => ['build_kit', 'analyze_local'].includes(job.kind)
      && ['running', 'pending'].includes(job.status));
    if (enMarcha || root.querySelector('.bar')) reloadView();
  },
};

/* Arrastrar un vídeo a la página abre la subida con él ya puesto */
function activarSoltar(root, ctx) {
  root.querySelectorAll('[data-soltar]').forEach((zona) => {
    zona.onclick = () => subirDialog(ctx.reload);
    zona.ondragover = (e) => { e.preventDefault(); zona.classList.add('over'); };
    zona.ondragleave = () => zona.classList.remove('over');
    zona.ondrop = (e) => {
      e.preventDefault();
      zona.classList.remove('over');
      subirDialog(ctx.reload, e.dataTransfer.files);
    };
  });
}

function avisoSinIA(aiStatus) {
  const proveedores = Object.entries(aiStatus.providers || {})
    .map(([, value]) => `<a href="${escapeHtml(value.keys_url)}" target="_blank" rel="noreferrer" style="color:var(--accent)">${escapeHtml(value.label)}</a>`)
    .join(' o ');
  return `<div class="card" style="border-color:rgba(255,181,69,.3);background:rgba(255,181,69,.06)">
    <strong style="font-size:13.5px">Sin IA configurada</strong>
    <p class="muted small" style="margin-top:7px;line-height:1.7">
      El kit se genera igual a partir de tu transcripción, pero con ${proveedores}
      los títulos y la descripción salen mucho mejor (y puedes crear fondos de miniatura).
      <a href="#ajustes?seccion=ia" style="color:var(--accent-2);text-decoration:underline">Añadir una clave</a> (las hay gratis: Groq, Gemini, OpenRouter…).
    </p>
  </div>`;
}

function bind(root, data, ctx) {
  root.querySelectorAll('[data-subir]').forEach((b) => { b.onclick = () => subirDialog(ctx.reload); });

  root.querySelectorAll('[data-video]').forEach((node) => {
    node.onclick = () => { selectedId = Number(node.dataset.video); ctx.reload(); };
  });

  // Pedir el kit, con lo que hayas contado del vídeo
  const pedirKit = async ({ preguntar = false, forzar = false } = {}) => {
    const usarIA = data.ai?.enabled;
    const conImagen = data.ai?.images_supported;
    const hayKit = data.kit && Object.keys(data.kit).length && !data.kit.falta_contexto;
    if (preguntar && hayKit
      && !await confirmDialog('Regenerar el kit',
        'Se sustituyen los títulos, la descripción y las miniaturas actuales.', 'Regenerar')) return;
    const casillaIA = root.querySelector('#g-ia');
    const casillaImg = root.querySelector('#g-img');
    const contexto = root.querySelector('#g-contexto');
    if (contexto && !contexto.value.trim() && !forzar && root.querySelector('.pregunta-kit')) {
      toast('Escribe en una línea de qué va el vídeo', 'warn');
      contexto.focus();
      return;
    }
    await api.post(`/api/videos/${selectedId}/kit`, {
      use_ai: casillaIA ? casillaIA.checked : Boolean(usarIA),
      ai_image: casillaImg ? casillaImg.checked : Boolean(conImagen),
      thumbnail_count: 3,
      contexto: contexto ? contexto.value : null,
      forzar,
    });
    toast('Preparando el kit…');
    ctx.reload();
  };
  const generar = root.querySelector('[data-generar]');
  if (generar) generar.onclick = () => pedirKit({ preguntar: true }).catch(toastError);
  const rehacer = root.querySelector('[data-rehacer]');
  if (rehacer) rehacer.onclick = () => pedirKit().catch(toastError);
  const forzar = root.querySelector('[data-forzar]');
  if (forzar) forzar.onclick = () => pedirKit({ forzar: true }).catch(toastError);
  const reintentarMinis = root.querySelector('[data-miniaturas]');
  if (reintentarMinis) reintentarMinis.onclick = () => pedirKit().catch(toastError);

  const kit = data.kit || {};
  const titulo = kit.chosen_title || (kit.titles || [])[0] || '';

  root.querySelectorAll('[data-titulo]').forEach((boton) => {
    boton.onclick = async () => {
      await api.patch(`/api/videos/${selectedId}/kit`, { chosen_title: boton.dataset.titulo });
      root.querySelectorAll('[data-titulo]').forEach((b) => b.classList.remove('sel'));
      boton.classList.add('sel');
      toast('Título elegido');
    };
  });

  root.querySelectorAll('[data-mini]').forEach((figura) => {
    figura.onclick = async (event) => {
      if (event.target.tagName === 'A') return;
      await api.patch(`/api/videos/${selectedId}/kit`, { chosen_thumbnail: Number(figura.dataset.mini) });
      root.querySelectorAll('[data-mini]').forEach((f) => f.classList.remove('sel'));
      figura.classList.add('sel');
      toast('Miniatura elegida');
    };
  });

  const sacarClips = root.querySelector('[data-sacar-clips]');
  if (sacarClips) {
    sacarClips.onclick = async () => {
      try {
        await api.post(`/api/videos/${selectedId}/process`, {});
        toast('Cortando… los clips aparecerán en Clips en unos minutos');
      } catch (error) { toastError(error); }
    };
  }

  const botonSubir = root.querySelector('[data-subir-youtube]');
  if (botonSubir) {
    botonSubir.onclick = () => subirAYouTubeDialog(data, () => ctx.reload());
  }

  root.querySelectorAll('[data-copiar]').forEach((boton) => {
    boton.onclick = () => {
      const que = boton.dataset.copiar;
      if (que === 'titulo') copiar(titulo, 'Título copiado');
      if (que === 'desc') copiar(root.querySelector('#kit-desc').value, 'Descripción copiada');
      if (que === 'tags') copiar((kit.tags || []).join(', '), 'Etiquetas copiadas');
      if (que === 'prompt') copiar(kit.thumbnail_prompt || '', 'Prompt copiado: pégalo en tu IA de imágenes');
    };
  });

  const guardar = root.querySelector('[data-guardar]');
  if (guardar) {
    guardar.onclick = async () => {
      try {
        await api.patch(`/api/videos/${selectedId}/kit`, {
          description: root.querySelector('#kit-desc').value,
        });
        toast('Descripción guardada');
        ctx.reload();
      } catch (error) { toastError(error); }
    };
  }
}
