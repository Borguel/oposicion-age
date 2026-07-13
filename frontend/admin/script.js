// Panel de administración. El backend (requiere_admin) es la barrera real;
// aquí solo se comprueba esAdmin para no montar la UI a quien no lo es.
import { esAdmin, obtenerAuthHeaders } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

// ===== utilidades =====
function escapeHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

function oposicionActual() {
  return document.getElementById("admin-oposicion")?.value || "AGE";
}

async function api(metodo, ruta, cuerpo) {
  const headers = await obtenerAuthHeaders();
  if (!headers) return null;
  const opciones = { method: metodo, headers: { ...headers } };
  if (cuerpo !== undefined) {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(cuerpo);
  }
  const resp = await fetch(BACKEND_URL + ruta, opciones);
  if (resp.status === 403) {
    mostrarNoAutorizado();
    return null;
  }
  let datos = {};
  try { datos = await resp.json(); } catch { datos = {}; }
  if (!resp.ok) {
    alert(datos.error || "Ha ocurrido un error.");
    return null;
  }
  return datos;
}

const apiGet = (ruta) => api("GET", ruta);

function mostrarNoAutorizado() {
  document.getElementById("admin-contenido").style.display = "none";
  document.getElementById("admin-no-autorizado").style.display = "block";
}

// ===== modal =====
const modal = document.getElementById("admin-modal");
const modalContenido = document.getElementById("admin-modal-contenido");
function abrirModal(html) {
  modalContenido.innerHTML = html;
  modal.hidden = false;
}
function cerrarModal() {
  modal.hidden = true;
  modalContenido.innerHTML = "";
}
document.getElementById("admin-modal-cerrar").addEventListener("click", cerrarModal);
modal.addEventListener("click", (e) => { if (e.target === modal) cerrarModal(); });

// ===== pestañas =====
const RENDERS = {
  dashboard: renderDashboard,
  temario: renderTemario,
  preguntas: renderPreguntas,
  usuarios: renderUsuarios,
  reportes: renderReportes,
};
let pestanaActual = "dashboard";

function activarPestana(nombre) {
  pestanaActual = nombre;
  document.querySelectorAll(".admin-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === nombre));
  document.querySelectorAll(".admin-panel").forEach((p) => { p.hidden = p.id !== `panel-${nombre}`; });
  RENDERS[nombre]();
}

// ===== Dashboard =====
async function renderDashboard() {
  const panel = document.getElementById("panel-dashboard");
  panel.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet("/admin/api/resumen");
  if (!d) return;
  const planes = Object.entries(d.usuarios_por_plan || {})
    .map(([plan, n]) => `<span class="admin-chip">${escapeHtml(plan)}: <strong>${n}</strong></span>`).join("");
  const temas = (d.top_temas_fallados || []).map((t) => `
    <tr><td>${escapeHtml(t.titulo || t.tema_id)}</td><td class="admin-num">${t.fallos}</td></tr>`).join("")
    || `<tr><td colspan="2" class="admin-vacio">Sin datos de fallos todavía.</td></tr>`;
  panel.innerHTML = `
    <div class="admin-cards">
      <div class="age-card admin-stat"><span class="admin-stat-num">${d.usuarios_totales}</span><span class="admin-stat-lbl">Usuarios totales</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-num">${d.tests_ultimos_7_dias}</span><span class="admin-stat-lbl">Tests (7 días)</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-num">${d.tests_ultimos_30_dias}</span><span class="admin-stat-lbl">Tests (30 días)</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-num">${d.reportes_pendientes}</span><span class="admin-stat-lbl">Reportes pendientes</span></div>
    </div>
    <div class="age-card admin-bloque">
      <h3>Usuarios por plan</h3>
      <div class="admin-chips">${planes || '<span class="admin-vacio">Sin usuarios.</span>'}</div>
    </div>
    <div class="age-card admin-bloque">
      <h3>Top 5 temas más fallados (todos los usuarios)</h3>
      <table class="admin-tabla"><thead><tr><th>Tema</th><th class="admin-num">Fallos</th></tr></thead><tbody>${temas}</tbody></table>
    </div>`;
}

// ===== Temario =====
let temaSeleccionado = null;
async function renderTemario() {
  const panel = document.getElementById("panel-temario");
  panel.innerHTML = `<p class="admin-cargando">Cargando temario…</p>`;
  const d = await apiGet(`/admin/api/temario/${oposicionActual()}`);
  if (!d) return;
  const arbol = (d.bloques || []).map((b) => `
    <div class="admin-bloque-arbol">
      <div class="admin-bloque-cab">
        <span class="admin-bloque-titulo">${escapeHtml(b.titulo)}</span>
        <label class="admin-toggle" title="Publicado / borrador">
          <input type="checkbox" data-bloque-pub="${escapeHtml(b.id)}" ${b.publicado ? "checked" : ""}>
          <span>${b.publicado ? "Publicado" : "Borrador"}</span>
        </label>
      </div>
      ${b.temas.map((t) => `
        <button type="button" class="admin-tema-item" data-bloque="${escapeHtml(b.id)}" data-tema="${escapeHtml(t.id)}">
          ${escapeHtml(t.titulo)} <span class="admin-badge">${t.num_chunks}</span>
        </button>`).join("")}
    </div>`).join("") || '<p class="admin-vacio">Sin bloques.</p>';

  panel.innerHTML = `
    <div class="admin-temario-grid">
      <div class="age-card admin-arbol">${arbol}</div>
      <div class="age-card admin-chunks" id="admin-chunks"><p class="admin-vacio">Elige un tema para ver sus fichas.</p></div>
    </div>`;

  panel.querySelectorAll("[data-bloque-pub]").forEach((chk) => chk.addEventListener("change", async () => {
    await api("PATCH", `/admin/api/temario/${oposicionActual()}/${chk.dataset.bloquePub}/publicado`, { publicado: chk.checked });
    renderTemario();
  }));
  panel.querySelectorAll(".admin-tema-item").forEach((btn) => btn.addEventListener("click", () => {
    temaSeleccionado = { bloque: btn.dataset.bloque, tema: btn.dataset.tema, titulo: btn.textContent.trim() };
    cargarChunks();
  }));
}

async function cargarChunks() {
  const cont = document.getElementById("admin-chunks");
  if (!cont || !temaSeleccionado) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/temario/${oposicionActual()}/${temaSeleccionado.bloque}/${temaSeleccionado.tema}`);
  if (!d) return;
  const chunks = (d.chunks || []).map((c) => `
    <div class="admin-chunk" data-id="${escapeHtml(c.id)}">
      <input class="age-input admin-chunk-titulo" value="${escapeHtml(c.titulo)}" placeholder="Título (opcional)">
      <textarea class="age-input admin-chunk-texto" rows="5">${escapeHtml(c.texto)}</textarea>
      <div class="admin-chunk-acciones">
        <button type="button" class="age-btn age-btn-primary admin-chunk-guardar">Guardar</button>
        <button type="button" class="age-btn age-btn-outline admin-chunk-borrar">Eliminar</button>
      </div>
    </div>`).join("") || '<p class="admin-vacio">Este tema no tiene fichas todavía.</p>';
  cont.innerHTML = `
    <h3>${escapeHtml(temaSeleccionado.tema)} — fichas</h3>
    ${chunks}
    <div class="admin-chunk admin-chunk-nuevo">
      <input class="age-input admin-nuevo-titulo" placeholder="Título del nuevo chunk (opcional)">
      <textarea class="age-input admin-nuevo-texto" rows="4" placeholder="Texto del nuevo chunk…"></textarea>
      <button type="button" class="age-btn age-btn-primary" id="admin-add-chunk">+ Añadir chunk</button>
    </div>`;

  cont.querySelectorAll(".admin-chunk[data-id]").forEach((div) => {
    const id = div.dataset.id;
    div.querySelector(".admin-chunk-guardar").addEventListener("click", async () => {
      await api("PUT", `/admin/api/temario/${oposicionActual()}/${temaSeleccionado.bloque}/${temaSeleccionado.tema}/${id}`,
        { titulo: div.querySelector(".admin-chunk-titulo").value, texto: div.querySelector(".admin-chunk-texto").value });
    });
    div.querySelector(".admin-chunk-borrar").addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta ficha?")) return;
      await api("DELETE", `/admin/api/temario/${oposicionActual()}/${temaSeleccionado.bloque}/${temaSeleccionado.tema}/${id}`);
      cargarChunks();
    });
  });
  cont.querySelector("#admin-add-chunk").addEventListener("click", async () => {
    const texto = cont.querySelector(".admin-nuevo-texto").value.trim();
    if (!texto) { alert("El texto no puede estar vacío."); return; }
    await api("POST", `/admin/api/temario/${oposicionActual()}/${temaSeleccionado.bloque}/${temaSeleccionado.tema}`,
      { titulo: cont.querySelector(".admin-nuevo-titulo").value, texto });
    cargarChunks();
  });
}

// ===== Preguntas =====
async function renderPreguntas() {
  const panel = document.getElementById("panel-preguntas");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <input id="f-bloque" class="age-input" placeholder="Bloque (ej. bloque_01)">
      <input id="f-tema" class="age-input" placeholder="Tema (ej. bloque_01-tema_01)">
      <input id="f-anio" class="age-input" placeholder="Año (ej. 2025)">
      <button class="age-btn age-btn-outline" id="f-aplicar">Filtrar</button>
      <button class="age-btn age-btn-primary" id="p-nueva">+ Nueva pregunta</button>
    </div>
    <div class="age-card"><div id="preguntas-tabla"><p class="admin-cargando">Cargando…</p></div></div>`;
  panel.querySelector("#f-aplicar").addEventListener("click", cargarPreguntas);
  panel.querySelector("#p-nueva").addEventListener("click", () => modalPregunta(null));
  cargarPreguntas();
}

async function cargarPreguntas() {
  const cont = document.getElementById("preguntas-tabla");
  if (!cont) return;
  const params = new URLSearchParams({ oposicion: oposicionActual() });
  const bloque = document.getElementById("f-bloque")?.value.trim();
  const tema = document.getElementById("f-tema")?.value.trim();
  const anio = document.getElementById("f-anio")?.value.trim();
  if (bloque) params.set("bloque", bloque);
  if (tema) params.set("tema", tema);
  if (anio) params.set("anio", anio);
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/preguntas?${params.toString()}`);
  if (!d) return;
  window._preguntasCache = {};
  const filas = (d.preguntas || []).map((p) => {
    window._preguntasCache[p.id] = p;
    return `<tr class="${p.activa ? "" : "admin-inactiva"}">
      <td>${escapeHtml(p.pregunta.slice(0, 90))}${p.pregunta.length > 90 ? "…" : ""}</td>
      <td class="admin-num">${p.veces_fallada}</td>
      <td>${escapeHtml(p.examen || "-")}</td>
      <td>
        <button class="age-btn age-btn-outline admin-mini" data-editar="${escapeHtml(p.id)}">Editar</button>
        ${p.activa ? `<button class="age-btn age-btn-outline admin-mini" data-desactivar="${escapeHtml(p.id)}">Desactivar</button>` : '<span class="admin-badge-off">inactiva</span>'}
      </td></tr>`;
  }).join("") || `<tr><td colspan="4" class="admin-vacio">Sin preguntas con estos filtros.</td></tr>`;
  cont.innerHTML = `<table class="admin-tabla"><thead><tr><th>Enunciado</th><th class="admin-num">Fallos</th><th>Examen</th><th>Acciones</th></tr></thead><tbody>${filas}</tbody></table>`;
  cont.querySelectorAll("[data-editar]").forEach((b) => b.addEventListener("click", () => modalPregunta(window._preguntasCache[b.dataset.editar])));
  cont.querySelectorAll("[data-desactivar]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("¿Desactivar esta pregunta? (no se borra, solo deja de usarse)")) return;
    await api("DELETE", `/admin/api/preguntas/${b.dataset.desactivar}?oposicion=${oposicionActual()}`);
    cargarPreguntas();
  }));
}

function modalPregunta(p) {
  const o = p ? p.opciones || {} : {};
  const correcta = p ? p.respuesta_correcta : "A";
  const radios = ["A", "B", "C", "D"].map((k) => `
    <div class="admin-opcion">
      <label class="admin-opcion-radio"><input type="radio" name="correcta" value="${k}" ${correcta === k ? "checked" : ""}> ${k}</label>
      <input class="age-input" id="op-${k}" value="${escapeHtml(o[k] || "")}" placeholder="Opción ${k}">
    </div>`).join("");
  abrirModal(`
    <h2>${p ? "Editar pregunta" : "Nueva pregunta"}</h2>
    <label>Enunciado</label>
    <textarea class="age-input" id="q-enunciado" rows="3">${escapeHtml(p ? p.pregunta : "")}</textarea>
    <label>Opciones (marca la correcta)</label>
    ${radios}
    <label>Explicación</label>
    <textarea class="age-input" id="q-explicacion" rows="3">${escapeHtml(p ? p.explicacion : "")}</textarea>
    <div class="admin-form-fila">
      <div><label>Tema (bloque-tema)</label><input class="age-input" id="q-tema" value="${escapeHtml(p ? p.tema_id : "")}"></div>
      <div><label>Examen / año</label><input class="age-input" id="q-examen" value="${escapeHtml(p ? p.examen : "")}"></div>
    </div>
    <button class="age-btn age-btn-primary" id="q-guardar" style="margin-top:14px;">Guardar</button>`);

  document.getElementById("q-guardar").addEventListener("click", async () => {
    const cuerpo = {
      oposicion: oposicionActual(),
      pregunta: document.getElementById("q-enunciado").value,
      opciones: { A: document.getElementById("op-A").value, B: document.getElementById("op-B").value, C: document.getElementById("op-C").value, D: document.getElementById("op-D").value },
      respuesta_correcta: document.querySelector('input[name="correcta"]:checked')?.value || "A",
      explicacion: document.getElementById("q-explicacion").value,
      tema_id: document.getElementById("q-tema").value,
      examen: document.getElementById("q-examen").value,
    };
    const r = p
      ? await api("PUT", `/admin/api/preguntas/${p.id}`, cuerpo)
      : await api("POST", "/admin/api/preguntas", cuerpo);
    if (r) { cerrarModal(); if (pestanaActual === "preguntas") cargarPreguntas(); }
  });
}

// ===== Usuarios =====
let paginaUsuarios = 1;
async function renderUsuarios() {
  const panel = document.getElementById("panel-usuarios");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <input id="u-busqueda" class="age-input" placeholder="Buscar por email…">
      <select id="u-plan" class="age-input"><option value="">Todos los planes</option><option value="gratis">Gratis</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
      <button class="age-btn age-btn-outline" id="u-aplicar">Buscar</button>
    </div>
    <div class="age-card"><div id="usuarios-tabla"><p class="admin-cargando">Cargando…</p></div></div>`;
  panel.querySelector("#u-aplicar").addEventListener("click", () => { paginaUsuarios = 1; cargarUsuarios(); });
  cargarUsuarios();
}

async function cargarUsuarios() {
  const cont = document.getElementById("usuarios-tabla");
  if (!cont) return;
  const params = new URLSearchParams({ pagina: paginaUsuarios });
  const busqueda = document.getElementById("u-busqueda")?.value.trim();
  const plan = document.getElementById("u-plan")?.value;
  if (busqueda) params.set("busqueda", busqueda);
  if (plan) params.set("plan", plan);
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/usuarios?${params.toString()}`);
  if (!d) return;
  window._usuariosCache = {};
  const filas = (d.usuarios || []).map((u) => {
    window._usuariosCache[u.uid] = u;
    return `<tr class="admin-fila-click" data-uid="${escapeHtml(u.uid)}">
      <td>${escapeHtml(u.email)}</td><td><span class="admin-chip">${escapeHtml(u.plan)}</span></td>
      <td>${(u.oposiciones_activas || []).map(escapeHtml).join(", ") || "-"}</td>
      <td>${escapeHtml((u.ultima_actividad || "").slice(0, 10) || "-")}</td></tr>`;
  }).join("") || `<tr><td colspan="4" class="admin-vacio">Sin usuarios.</td></tr>`;
  const totalPaginas = Math.max(1, Math.ceil((d.total || 0) / (d.por_pagina || 20)));
  cont.innerHTML = `
    <table class="admin-tabla"><thead><tr><th>Email</th><th>Plan</th><th>Oposiciones</th><th>Últ. actividad</th></tr></thead><tbody>${filas}</tbody></table>
    <div class="admin-paginacion">
      <button class="age-btn age-btn-outline admin-mini" id="u-prev" ${paginaUsuarios <= 1 ? "disabled" : ""}>◀</button>
      <span>Página ${d.pagina} de ${totalPaginas} (${d.total} usuarios)</span>
      <button class="age-btn age-btn-outline admin-mini" id="u-next" ${paginaUsuarios >= totalPaginas ? "disabled" : ""}>▶</button>
    </div>`;
  cont.querySelectorAll(".admin-fila-click").forEach((tr) => tr.addEventListener("click", () => panelUsuario(window._usuariosCache[tr.dataset.uid])));
  cont.querySelector("#u-prev")?.addEventListener("click", () => { paginaUsuarios--; cargarUsuarios(); });
  cont.querySelector("#u-next")?.addEventListener("click", () => { paginaUsuarios++; cargarUsuarios(); });
}

function panelUsuario(u) {
  abrirModal(`
    <h2>${escapeHtml(u.email)}</h2>
    <p class="admin-dato"><strong>UID:</strong> ${escapeHtml(u.uid)}</p>
    <p class="admin-dato"><strong>Plan:</strong> ${escapeHtml(u.plan)}</p>
    <p class="admin-dato"><strong>Alta:</strong> ${escapeHtml((u.fecha_creacion || "").slice(0, 10) || "-")}</p>
    <hr class="admin-sep">
    <h3>Cambiar plan (soporte)</h3>
    <div class="admin-form-fila">
      <select id="up-plan" class="age-input"><option value="gratis">Gratis</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
      <select id="up-oposicion" class="age-input"><option value="AGE">AGE</option><option value="GACE">GACE</option><option value="AUXILIAR">Auxiliar</option></select>
    </div>
    <input id="up-motivo" class="age-input" placeholder="Motivo (queda registrado)" style="margin-top:8px;">
    <button class="age-btn age-btn-primary" id="up-guardar" style="margin-top:10px;">Cambiar plan</button>
    <hr class="admin-sep">
    <button class="age-btn age-btn-outline" id="up-racha">Resetear racha de estudio</button>`);
  document.getElementById("up-plan").value = u.plan;
  document.getElementById("up-guardar").addEventListener("click", async () => {
    const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/plan`, {
      plan: document.getElementById("up-plan").value,
      oposicion: document.getElementById("up-oposicion").value,
      motivo: document.getElementById("up-motivo").value,
    });
    if (r) { cerrarModal(); cargarUsuarios(); }
  });
  document.getElementById("up-racha").addEventListener("click", async () => {
    if (!confirm("¿Resetear la racha de este usuario a 0?")) return;
    const r = await api("POST", `/admin/api/usuarios/${u.uid}/resetear-racha`);
    if (r) alert("Racha reseteada.");
  });
}

// ===== Reportes =====
async function renderReportes() {
  const panel = document.getElementById("panel-reportes");
  panel.innerHTML = `<div class="age-card"><div id="reportes-lista"><p class="admin-cargando">Cargando…</p></div></div>`;
  cargarReportes();
}

async function cargarReportes() {
  const cont = document.getElementById("reportes-lista");
  if (!cont) return;
  const d = await apiGet("/admin/api/reportes?estado=pendiente");
  if (!d) return;
  if (!(d.reportes || []).length) {
    cont.innerHTML = `<p class="admin-vacio">No hay reportes pendientes. 🎉</p>`;
    return;
  }
  cont.innerHTML = d.reportes.map((r) => `
    <div class="admin-reporte">
      <p class="admin-reporte-preg">${escapeHtml(r.pregunta_texto)}</p>
      <p class="admin-reporte-motivo"><strong>Motivo:</strong> ${escapeHtml(r.motivo)}</p>
      <div class="admin-reporte-acciones">
        <button class="age-btn age-btn-primary admin-mini" data-editar-preg="${escapeHtml(r.pregunta_texto)}">Editar esta pregunta</button>
        <button class="age-btn age-btn-outline admin-mini" data-revisado="${escapeHtml(r.id)}">Marcar revisado</button>
        <button class="age-btn age-btn-outline admin-mini" data-descartar="${escapeHtml(r.id)}">Descartar</button>
      </div>
    </div>`).join("");
  cont.querySelectorAll("[data-revisado]").forEach((b) => b.addEventListener("click", () => cambiarEstadoReporte(b.dataset.revisado, "revisado")));
  cont.querySelectorAll("[data-descartar]").forEach((b) => b.addEventListener("click", () => cambiarEstadoReporte(b.dataset.descartar, "descartado")));
  cont.querySelectorAll("[data-editar-preg]").forEach((b) => b.addEventListener("click", () => buscarYEditarPregunta(b.dataset.editarPreg)));
}

async function cambiarEstadoReporte(id, estado) {
  const r = await api("PATCH", `/admin/api/reportes/${id}`, { estado });
  if (r) cargarReportes();
}

// Desde un reporte, localiza la pregunta oficial por su texto y abre el modal
// de edición ya cargada (si es una pregunta generada por IA que no está en la
// colección oficial, avisa de que no se puede editar centralmente).
async function buscarYEditarPregunta(textoPregunta) {
  const d = await apiGet(`/admin/api/preguntas?oposicion=${oposicionActual()}`);
  if (!d) return;
  const encontrada = (d.preguntas || []).find((p) => p.pregunta.trim() === textoPregunta.trim());
  if (!encontrada) {
    alert("Esta pregunta no está en el banco de preguntas oficiales de la oposición seleccionada (puede ser generada por IA). Cambia de oposición o edítala desde su origen.");
    return;
  }
  modalPregunta(encontrada);
}

// ===== init =====
document.addEventListener("DOMContentLoaded", async () => {
  if (!(await esAdmin())) {
    mostrarNoAutorizado();
    return;
  }
  document.getElementById("admin-contenido").style.display = "block";
  document.querySelectorAll(".admin-tab").forEach((b) => b.addEventListener("click", () => activarPestana(b.dataset.tab)));
  document.getElementById("admin-oposicion").addEventListener("change", () => RENDERS[pestanaActual]());
  activarPestana("dashboard");
});
