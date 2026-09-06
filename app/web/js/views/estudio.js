// Estudio: sube un vídeo y sal con el título, la descripción, las etiquetas
// y las miniaturas listas para pegar en YouTube.

import { api } from '../lib/api.js';
import {
  confirmDialog, emptyState, escapeHtml, fmt, modal, toast, toastError,
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
function subirDialog(reload) {
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
      <div class="field"><label>Título provisional</label>
        <input type="text" id="u-title" placeholder="Se usa el nombre del archivo si lo dejas vacío"></div>
      <div class="form-grid">
        <div class="field"><label class="switch"><input type="checkbox" id="u-ai" checked>
          <span class="track"></span><span class="switch-label">Generar con IA</span></label></div>
        <div class="field"><label class="switch"><input type="checkbox" id="u-img">
          <span class="track"></span><span class="switch-label">Miniatura con imagen de IA</span></label></div>
        <div class="field full"><label class="switch"><input type="checkbox" id="u-clips">
          <span class="track"></span><span class="switch-label">Sacar también clips verticales para TikTok</span></label></div>
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

  if (!Object.keys(kit).length) {
    return `<div class="card">${emptyState('✨', 'Este vídeo aún no tiene kit',
      'Genera títulos, descripción, etiquetas y miniaturas en un clic.',
      '<button class="btn primary" data-generar>Generar el kit</button>')}</div>`;
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
        </div>
      </div>

      ${kit.warning ? `<p class="small" style="color:var(--amber);margin-bottom:14px">${escapeHtml(kit.warning)}</p>` : ''}
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
        </div>` : '<p class="muted small">No se han generado miniaturas para este vídeo.</p>'}
        ${(kit.thumbnail_errors || []).map((e) => `<p class="tiny" style="color:var(--amber);margin-top:8px">${escapeHtml(e)}</p>`).join('')}
      </div>
    </div>`;
}

/* -------------------------------------------------------------- vista */
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
    const [videos, aiStatus] = await Promise.all([
      api.get('/api/studio/videos?limit=60'),
      api.get('/api/ai/status'),
    ]);

    if (!videos.length) {
      root.innerHTML = `
        ${aiStatus.enabled ? '' : avisoSinIA(aiStatus)}
        <div class="card">${emptyState('🎬', 'Todavía no hay vídeos en el estudio',
          'Sube un vídeo desde tu ordenador (o importa uno de YouTube) y Kevil te prepara el título, la descripción, las etiquetas y las miniaturas.',
          '<button class="btn primary" data-subir>Subir mi primer vídeo</button>')}</div>`;
      root.querySelector('[data-subir]').onclick = () => subirDialog(ctx.reload);
      return;
    }

    if (!videos.some((v) => v.id === selectedId)) {
      selectedId = (videos.find((v) => v.has_kit) || videos[0]).id;
    }
    const data = await api.get(`/api/videos/${selectedId}/kit`);

    root.innerHTML = `
      ${aiStatus.enabled ? '' : avisoSinIA(aiStatus)}
      <div class="grid" style="grid-template-columns:minmax(0,270px) minmax(0,1fr);gap:20px;align-items:start">
        <div class="card">
          <div class="card-head"><h3>Mis vídeos</h3></div>
          <div class="flow-list">
            ${videos.map((video) => `
              <div class="flow-card ${video.id === selectedId ? 'active' : ''}" data-video="${video.id}">
                <span class="emoji">${video.origin === 'local' ? '📁' : '▶️'}</span>
                <div class="meta">
                  <strong>${escapeHtml(video.title)}</strong>
                  <span>${video.has_kit
                    ? `kit listo · ${video.kit_thumbnails} miniaturas`
                    : (video.status === 'ready' ? 'sin kit' : escapeHtml(video.status))}</span>
                </div>
              </div>`).join('')}
          </div>
          <button class="btn" style="width:100%;justify-content:center;margin-top:14px" data-subir>⬆ Subir vídeo</button>
        </div>

        <div id="kit">${kitHtml(data)}</div>
      </div>`;

    bind(root, data, ctx);
  },

  async onRefresh(root) {
    const activos = await api.jobs('?status=running&limit=3');
    if (activos.some((job) => ['build_kit', 'analyze_local'].includes(job.kind))) {
      reloadView();
    }
  },
};

function avisoSinIA(aiStatus) {
  const proveedores = Object.entries(aiStatus.providers || {})
    .map(([, value]) => `<a href="${escapeHtml(value.keys_url)}" target="_blank" rel="noreferrer" style="color:var(--accent)">${escapeHtml(value.label)}</a>`)
    .join(' o ');
  return `<div class="card" style="border-color:rgba(255,181,69,.3);background:rgba(255,181,69,.06)">
    <strong style="font-size:13.5px">Sin IA configurada</strong>
    <p class="muted small" style="margin-top:7px;line-height:1.7">
      El kit se genera igual a partir de tu transcripción, pero con ${proveedores}
      los títulos y la descripción salen mucho mejor (y puedes crear fondos de miniatura).
      Se configura en <a href="#ajustes" style="color:var(--accent)">Ajustes</a>.
    </p>
  </div>`;
}

function bind(root, data, ctx) {
  root.querySelectorAll('[data-subir]').forEach((b) => { b.onclick = () => subirDialog(ctx.reload); });

  root.querySelectorAll('[data-video]').forEach((node) => {
    node.onclick = () => { selectedId = Number(node.dataset.video); ctx.reload(); };
  });

  const generar = root.querySelector('[data-generar]');
  if (generar) {
    generar.onclick = async () => {
      const usarIA = data.ai?.enabled;
      const conImagen = data.ai?.images_supported;
      if (data.kit && Object.keys(data.kit).length
        && !await confirmDialog('Regenerar el kit',
          'Se sustituyen los títulos, la descripción y las miniaturas actuales.', 'Regenerar')) return;
      await api.post(`/api/videos/${selectedId}/kit`, {
        use_ai: Boolean(usarIA), ai_image: Boolean(conImagen), thumbnail_count: 3,
      });
      toast('Generando el kit…');
      ctx.reload();
    };
  }

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

  root.querySelectorAll('[data-copiar]').forEach((boton) => {
    boton.onclick = () => {
      const que = boton.dataset.copiar;
      if (que === 'titulo') copiar(titulo, 'Título copiado');
      if (que === 'desc') copiar(root.querySelector('#kit-desc').value, 'Descripción copiada');
      if (que === 'tags') copiar((kit.tags || []).join(', '), 'Etiquetas copiadas');
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
