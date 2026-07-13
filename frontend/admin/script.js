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

function fechaCorta(valor) {
  return (valor || "").slice(0, 10) || "-";
}

// ===== toasts (avisos flotantes, sustituyen a alert) =====
function toast(mensaje, tipo = "ok") {
  const cont = document.getElementById("admin-toasts");
  if (!cont) return;
  const el = document.createElement("div");
  el.className = `admin-toast admin-toast-${tipo}`;
  const icono = tipo === "error" ? "⚠️" : tipo === "ok" ? "✅" : "ℹ️";
  el.innerHTML = `<span class="admin-toast-icono">${icono}</span><span>${escapeHtml(mensaje)}</span>`;
  cont.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transform = "translateY(12px)"; }, 3200);
  setTimeout(() => el.remove(), 3600);
}

async function api(metodo, ruta, cuerpo) {
  const headers = await obtenerAuthHeaders();
  if (!headers) return null;
  const opciones = { method: metodo, headers: { ...headers } };
  if (cuerpo !== undefined) {
    opciones.headers["Content-Type"] = "application/json";
    opciones.body = JSON.stringify(cuerpo);
  }
  let resp;
  try {
    resp = await fetch(BACKEND_URL + ruta, opciones);
  } catch {
    toast("Sin conexión con el servidor.", "error");
    return null;
  }
  if (resp.status === 403) {
    mostrarNoAutorizado();
    return null;
  }
  let datos = {};
  try { datos = await resp.json(); } catch { datos = {}; }
  if (!resp.ok) {
    toast(datos.error || "Ha ocurrido un error.", "error");
    return null;
  }
  return datos;
}

const apiGet = (ruta) => api("GET", ruta);

// Descarga un CSV protegido (manda el token, recibe el fichero y fuerza la
// descarga desde un blob local).
async function descargarCSV(ruta, nombre) {
  const headers = await obtenerAuthHeaders();
  if (!headers) return;
  let resp;
  try {
    resp = await fetch(BACKEND_URL + ruta, { headers });
  } catch {
    toast("Sin conexión con el servidor.", "error");
    return;
  }
  if (!resp.ok) { toast("No se pudo generar el CSV.", "error"); return; }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  toast("Descarga iniciada.");
}

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
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !modal.hidden) cerrarModal(); });

// ===== pestañas =====
const RENDERS = {
  dashboard: renderDashboard,
  temario: renderTemario,
  preguntas: renderPreguntas,
  usuarios: renderUsuarios,
  reportes: renderReportes,
  auditoria: renderAuditoria,
};
let pestanaActual = "dashboard";

function activarPestana(nombre) {
  pestanaActual = nombre;
  document.querySelectorAll(".admin-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === nombre));
  document.querySelectorAll(".admin-panel").forEach((p) => { p.hidden = p.id !== `panel-${nombre}`; });
  RENDERS[nombre]();
}

function actualizarBadgeReportes(n) {
  const badge = document.getElementById("badge-reportes");
  if (!badge) return;
  badge.textContent = n;
  badge.hidden = !n;
}

// ===== Dashboard =====
async function renderDashboard() {
  const panel = document.getElementById("panel-dashboard");
  panel.innerHTML = `<p class="admin-cargando">Cargando panel…</p>`;
  const d = await apiGet(`/admin/api/resumen?oposicion=${oposicionActual()}`);
  if (!d) return;
  actualizarBadgeReportes(d.reportes_pendientes || 0);

  const planes = Object.entries(d.usuarios_por_plan || {})
    .map(([plan, n]) => `<span class="admin-chip">${escapeHtml(plan)}: <strong>${n}</strong></span>`).join("");
  const temas = (d.top_temas_fallados || []).map((t) => `
    <tr><td>${escapeHtml(t.titulo || t.tema_id)}</td><td class="admin-num">${t.fallos}</td></tr>`).join("")
    || `<tr><td colspan="2" class="admin-vacio">Sin datos de fallos todavía.</td></tr>`;

  const salud = d.salud_contenido || {};
  const preg = d.preguntas_stats || {};
  const sinContenido = salud.temas_sin_contenido || [];
  const alertaReportes = (d.reportes_pendientes || 0) > 0;

  const huecos = sinContenido.length
    ? sinContenido.map((t) => `
        <button type="button" class="admin-chip admin-chip-warn admin-hueco" data-bloque="${escapeHtml(t.bloque)}" data-tema="${escapeHtml(t.tema)}">
          ${escapeHtml(t.titulo)} →
        </button>`).join("")
    : `<span class="admin-vacio">Todos los temas tienen contenido. 🎉</span>`;

  panel.innerHTML = `
    <div class="admin-cards">
      <div class="age-card admin-stat"><span class="admin-stat-num">${d.usuarios_totales}</span><span class="admin-stat-lbl">Usuarios</span><span class="admin-stat-sub">+${d.usuarios_nuevos_7_dias || 0} en 7 días</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-num">${d.usuarios_activos_7_dias || 0}</span><span class="admin-stat-lbl">Activos (7 días)</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-num">${d.tests_ultimos_7_dias}</span><span class="admin-stat-lbl">Tests (7 días)</span><span class="admin-stat-sub">${d.tests_ultimos_30_dias} en 30 días</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-num">${d.tests_total || 0}</span><span class="admin-stat-lbl">Tests totales</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-num">${(d.mrr || 0).toFixed(2)}€</span><span class="admin-stat-lbl">Ingresos/mes (MRR)</span><span class="admin-stat-sub">${d.suscripciones_pago || 0} suscripciones de pago</span></div>
      <div class="age-card admin-stat admin-stat-clic ${alertaReportes ? "admin-stat-alerta" : ""}" id="stat-reportes"><span class="admin-stat-num">${d.reportes_pendientes}</span><span class="admin-stat-lbl">Reportes pendientes</span></div>
    </div>

    <div class="age-card admin-bloque">
      <h3>Contenido de ${escapeHtml(d.oposicion || oposicionActual())}</h3>
      <div class="admin-datos-grid">
        <div class="admin-dato-caja"><span class="admin-dato-caja-num">${salud.temas_total || 0}</span><span class="admin-dato-caja-lbl">Temas</span></div>
        <div class="admin-dato-caja"><span class="admin-dato-caja-num">${preg.activas || 0}</span><span class="admin-dato-caja-lbl">Preguntas activas</span></div>
        <div class="admin-dato-caja"><span class="admin-dato-caja-num">${sinContenido.length}</span><span class="admin-dato-caja-lbl">Temas sin fichas</span></div>
        <div class="admin-dato-caja"><span class="admin-dato-caja-num">${preg.sin_explicacion || 0}</span><span class="admin-dato-caja-lbl">Sin explicación</span></div>
        <div class="admin-dato-caja"><span class="admin-dato-caja-num">${(salud.temas_borrador || 0) + (salud.bloques_borrador || 0)}</span><span class="admin-dato-caja-lbl">En borrador</span></div>
      </div>
    </div>

    <div class="age-card admin-bloque">
      <h3>Temas sin contenido — huecos por rellenar</h3>
      <div class="admin-chips">${huecos}</div>
    </div>

    <div class="age-card admin-bloque">
      <h3>Usuarios por plan</h3>
      <div class="admin-chips">${planes || '<span class="admin-vacio">Sin usuarios.</span>'}</div>
    </div>

    <div class="age-card admin-bloque">
      <h3>Top 5 temas más fallados (todos los usuarios)</h3>
      <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Tema</th><th class="admin-num">Fallos</th></tr></thead><tbody>${temas}</tbody></table></div>
    </div>`;

  panel.querySelector("#stat-reportes")?.addEventListener("click", () => activarPestana("reportes"));
  panel.querySelectorAll(".admin-hueco").forEach((b) => b.addEventListener("click", () => {
    temaSeleccionado = { bloque: b.dataset.bloque, tema: b.dataset.tema, titulo: b.textContent.trim() };
    activarPestana("temario");
    setTimeout(cargarChunks, 250); // tras montar el panel de temario
  }));
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
        <button type="button" class="admin-tema-item ${t.num_chunks ? "" : "sin-contenido"}" data-bloque="${escapeHtml(b.id)}" data-tema="${escapeHtml(t.id)}">
          <span>${escapeHtml(t.titulo)}${t.publicado ? "" : ' <span class="admin-badge-alerta">borrador</span>'}</span>
          <span class="admin-badge">${t.num_chunks}</span>
        </button>`).join("")}
    </div>`).join("") || '<p class="admin-vacio">Sin bloques.</p>';

  panel.innerHTML = `
    <div class="admin-temario-grid">
      <div class="age-card admin-arbol">${arbol}</div>
      <div class="age-card admin-chunks" id="admin-chunks"><p class="admin-vacio">Elige un tema para ver y editar sus fichas.</p></div>
    </div>`;

  panel.querySelectorAll("[data-bloque-pub]").forEach((chk) => chk.addEventListener("change", async () => {
    const r = await api("PATCH", `/admin/api/temario/${oposicionActual()}/${chk.dataset.bloquePub}/publicado`, { publicado: chk.checked });
    if (r) { toast(chk.checked ? "Bloque publicado." : "Bloque pasado a borrador."); renderTemario(); }
  }));
  panel.querySelectorAll(".admin-tema-item").forEach((btn) => btn.addEventListener("click", () => {
    temaSeleccionado = { bloque: btn.dataset.bloque, tema: btn.dataset.tema, titulo: btn.textContent.trim() };
    cargarChunks();
  }));

  // Si venimos de un hueco del dashboard, cargar directamente sus fichas.
  if (temaSeleccionado) cargarChunks();
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
        <button type="button" class="age-btn age-btn-primary admin-mini admin-chunk-guardar">Guardar</button>
        <button type="button" class="age-btn age-btn-outline admin-mini admin-chunk-borrar">Eliminar</button>
      </div>
    </div>`).join("") || '<p class="admin-vacio">Este tema no tiene fichas todavía. Añade la primera abajo.</p>';
  cont.innerHTML = `
    <h3>${escapeHtml(temaSeleccionado.bloque)} · ${escapeHtml(temaSeleccionado.tema)} — fichas</h3>
    ${chunks}
    <div class="admin-chunk admin-chunk-nuevo">
      <input class="age-input admin-nuevo-titulo" placeholder="Título de la nueva ficha (opcional)">
      <textarea class="age-input admin-nuevo-texto" rows="4" placeholder="Texto de la nueva ficha…"></textarea>
      <button type="button" class="age-btn age-btn-primary admin-mini" id="admin-add-chunk">+ Añadir ficha</button>
    </div>`;

  cont.querySelectorAll(".admin-chunk[data-id]").forEach((div) => {
    const id = div.dataset.id;
    div.querySelector(".admin-chunk-guardar").addEventListener("click", async () => {
      const r = await api("PUT", `/admin/api/temario/${oposicionActual()}/${temaSeleccionado.bloque}/${temaSeleccionado.tema}/${id}`,
        { titulo: div.querySelector(".admin-chunk-titulo").value, texto: div.querySelector(".admin-chunk-texto").value });
      if (r) toast("Ficha guardada.");
    });
    div.querySelector(".admin-chunk-borrar").addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta ficha?")) return;
      const r = await api("DELETE", `/admin/api/temario/${oposicionActual()}/${temaSeleccionado.bloque}/${temaSeleccionado.tema}/${id}`);
      if (r) { toast("Ficha eliminada."); cargarChunks(); }
    });
  });
  cont.querySelector("#admin-add-chunk").addEventListener("click", async () => {
    const texto = cont.querySelector(".admin-nuevo-texto").value.trim();
    if (!texto) { toast("El texto no puede estar vacío.", "error"); return; }
    const r = await api("POST", `/admin/api/temario/${oposicionActual()}/${temaSeleccionado.bloque}/${temaSeleccionado.tema}`,
      { titulo: cont.querySelector(".admin-nuevo-titulo").value, texto });
    if (r) { toast("Ficha añadida."); cargarChunks(); }
  });
}

// ===== Preguntas =====
async function renderPreguntas() {
  const panel = document.getElementById("panel-preguntas");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <input id="f-texto" class="age-input" placeholder="Buscar en el enunciado…">
      <input id="f-bloque" class="age-input" placeholder="Bloque (ej. bloque_01)">
      <input id="f-anio" class="age-input" placeholder="Año (ej. 2025)">
      <button class="age-btn age-btn-outline admin-filtros-btn" id="f-aplicar">Filtrar</button>
      <button class="age-btn age-btn-outline admin-filtros-btn" id="p-csv">⬇ CSV</button>
      <button class="age-btn age-btn-primary admin-filtros-btn" id="p-nueva">+ Nueva</button>
    </div>
    <div class="age-card"><div id="preguntas-tabla"><p class="admin-cargando">Cargando…</p></div></div>`;
  panel.querySelector("#f-aplicar").addEventListener("click", cargarPreguntas);
  panel.querySelector("#p-nueva").addEventListener("click", () => modalPregunta(null));
  panel.querySelector("#p-csv").addEventListener("click", () => descargarCSV(`/admin/api/preguntas/export?oposicion=${oposicionActual()}`, `preguntas_${oposicionActual()}.csv`));
  panel.querySelector("#f-texto").addEventListener("keydown", (e) => { if (e.key === "Enter") cargarPreguntas(); });
  cargarPreguntas();
}

async function cargarPreguntas() {
  const cont = document.getElementById("preguntas-tabla");
  if (!cont) return;
  const params = new URLSearchParams({ oposicion: oposicionActual() });
  const bloque = document.getElementById("f-bloque")?.value.trim();
  const anio = document.getElementById("f-anio")?.value.trim();
  const texto = (document.getElementById("f-texto")?.value.trim() || "").toLowerCase();
  if (bloque) params.set("bloque", bloque);
  if (anio) params.set("anio", anio);
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/preguntas?${params.toString()}`);
  if (!d) return;
  window._preguntasCache = {};
  let lista = d.preguntas || [];
  if (texto) lista = lista.filter((p) => (p.pregunta || "").toLowerCase().includes(texto));
  const filas = lista.map((p) => {
    window._preguntasCache[p.id] = p;
    const sinExpl = !(p.explicacion || "").trim();
    return `<tr class="${p.activa ? "" : "admin-inactiva"}">
      <td>${escapeHtml(p.pregunta.slice(0, 90))}${p.pregunta.length > 90 ? "…" : ""} ${sinExpl ? '<span class="admin-badge-alerta">sin explicación</span>' : ""}</td>
      <td>${escapeHtml(p.tema_id || "-")}</td>
      <td class="admin-num">${p.veces_fallada}</td>
      <td class="admin-td-acciones">
        <button class="age-btn age-btn-outline admin-mini" data-editar="${escapeHtml(p.id)}">Editar</button>
        ${p.activa
          ? `<button class="age-btn age-btn-outline admin-mini" data-desactivar="${escapeHtml(p.id)}">Desactivar</button>`
          : `<button class="age-btn age-btn-outline admin-mini" data-reactivar="${escapeHtml(p.id)}">Reactivar</button>`}
      </td></tr>`;
  }).join("") || `<tr><td colspan="4" class="admin-vacio">Sin preguntas con estos filtros.</td></tr>`;
  cont.innerHTML = `
    <p class="admin-reporte-meta" style="margin-bottom:8px;">${lista.length} pregunta(s)</p>
    <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Enunciado</th><th>Tema</th><th class="admin-num">Fallos</th><th>Acciones</th></tr></thead><tbody>${filas}</tbody></table></div>`;
  cont.querySelectorAll("[data-editar]").forEach((b) => b.addEventListener("click", () => modalPregunta(window._preguntasCache[b.dataset.editar])));
  cont.querySelectorAll("[data-desactivar]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("¿Desactivar esta pregunta? (no se borra, solo deja de usarse)")) return;
    const r = await api("DELETE", `/admin/api/preguntas/${b.dataset.desactivar}?oposicion=${oposicionActual()}`);
    if (r) { toast("Pregunta desactivada."); cargarPreguntas(); }
  }));
  cont.querySelectorAll("[data-reactivar]").forEach((b) => b.addEventListener("click", async () => {
    const r = await api("POST", `/admin/api/preguntas/${b.dataset.reactivar}/reactivar?oposicion=${oposicionActual()}`);
    if (r) { toast("Pregunta reactivada."); cargarPreguntas(); }
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
    if (r) { toast(p ? "Pregunta actualizada." : "Pregunta creada."); cerrarModal(); if (pestanaActual === "preguntas") cargarPreguntas(); }
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
      <button class="age-btn age-btn-primary admin-filtros-btn" id="u-aplicar">Buscar</button>
      <button class="age-btn age-btn-outline admin-filtros-btn" id="u-csv">⬇ CSV</button>
    </div>
    <div class="age-card"><div id="usuarios-tabla"><p class="admin-cargando">Cargando…</p></div></div>`;
  panel.querySelector("#u-aplicar").addEventListener("click", () => { paginaUsuarios = 1; cargarUsuarios(); });
  panel.querySelector("#u-csv").addEventListener("click", () => {
    const params = new URLSearchParams();
    const b = document.getElementById("u-busqueda")?.value.trim();
    const pl = document.getElementById("u-plan")?.value;
    if (b) params.set("busqueda", b);
    if (pl) params.set("plan", pl);
    descargarCSV(`/admin/api/usuarios/export?${params.toString()}`, "usuarios.csv");
  });
  panel.querySelector("#u-busqueda").addEventListener("keydown", (e) => { if (e.key === "Enter") { paginaUsuarios = 1; cargarUsuarios(); } });
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
  const filas = (d.usuarios || []).map((u) => `
    <tr class="admin-fila-click" data-uid="${escapeHtml(u.uid)}">
      <td>${escapeHtml(u.email || "(sin email)")}</td><td><span class="admin-chip">${escapeHtml(u.plan)}</span></td>
      <td>${(u.oposiciones_activas || []).map(escapeHtml).join(", ") || "-"}</td>
      <td class="admin-num">${fechaCorta(u.ultima_actividad)}</td></tr>`).join("")
    || `<tr><td colspan="4" class="admin-vacio">Sin usuarios.</td></tr>`;
  const totalPaginas = Math.max(1, Math.ceil((d.total || 0) / (d.por_pagina || 20)));
  cont.innerHTML = `
    <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Email</th><th>Plan</th><th>Oposiciones</th><th class="admin-num">Últ. act.</th></tr></thead><tbody>${filas}</tbody></table></div>
    <div class="admin-paginacion">
      <button class="age-btn age-btn-outline admin-mini" id="u-prev" ${paginaUsuarios <= 1 ? "disabled" : ""}>◀ Anterior</button>
      <span>Página ${d.pagina} de ${totalPaginas} · ${d.total} usuarios</span>
      <button class="age-btn age-btn-outline admin-mini" id="u-next" ${paginaUsuarios >= totalPaginas ? "disabled" : ""}>Siguiente ▶</button>
    </div>`;
  cont.querySelectorAll(".admin-fila-click").forEach((tr) => tr.addEventListener("click", () => abrirUsuario(tr.dataset.uid)));
  cont.querySelector("#u-prev")?.addEventListener("click", () => { paginaUsuarios--; cargarUsuarios(); });
  cont.querySelector("#u-next")?.addEventListener("click", () => { paginaUsuarios++; cargarUsuarios(); });
}

async function abrirUsuario(uid) {
  abrirModal(`<p class="admin-cargando">Cargando ficha…</p>`);
  const u = await apiGet(`/admin/api/usuarios/${uid}`);
  if (!u) { cerrarModal(); return; }
  const override = u.admin_override
    ? `<div class="admin-aviso"><strong>Último cambio de soporte:</strong> ${escapeHtml(u.admin_override.cambio || "")} — ${escapeHtml(u.admin_override.motivo || "sin motivo")} (${escapeHtml(fechaCorta(u.admin_override.fecha))})</div>`
    : "";
  abrirModal(`
    <h2>${escapeHtml(u.email || "(sin email)")}</h2>
    <p class="admin-dato admin-dato-mono"><strong>UID:</strong> ${escapeHtml(u.uid)}<button class="admin-copiar" id="up-copiar-uid">copiar</button></p>
    <div class="admin-datos-grid">
      <div class="admin-dato-caja"><span class="admin-dato-caja-num">${u.tests_total}</span><span class="admin-dato-caja-lbl">Tests</span></div>
      <div class="admin-dato-caja"><span class="admin-dato-caja-num">${u.racha_actual}</span><span class="admin-dato-caja-lbl">Racha</span></div>
      <div class="admin-dato-caja"><span class="admin-dato-caja-num">${u.ultima_nota != null ? escapeHtml(u.ultima_nota) : "-"}</span><span class="admin-dato-caja-lbl">Últ. nota</span></div>
    </div>
    <p class="admin-dato"><strong>Plan actual:</strong> ${escapeHtml(u.plan)} · <strong>Alta:</strong> ${escapeHtml(fechaCorta(u.fecha_creacion))} · <strong>Últ. actividad:</strong> ${escapeHtml(fechaCorta(u.ultima_actividad))}</p>
    <p class="admin-dato"><strong>Email verificado:</strong> ${u.email_verificado ? "sí" : "no"}</p>
    ${override}
    <hr class="admin-sep">
    <h3>Cambiar plan (soporte)</h3>
    <div class="admin-form-fila">
      <select id="up-plan" class="age-input"><option value="gratis">Gratis</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
      <select id="up-oposicion" class="age-input"><option value="AGE">AGE</option><option value="GACE">GACE</option><option value="AUXILIAR">Auxiliar</option></select>
    </div>
    <input id="up-motivo" class="age-input" placeholder="Motivo (queda registrado)" style="margin-top:8px;">
    <button class="age-btn age-btn-primary" id="up-guardar" style="margin-top:10px;">Cambiar plan</button>
    <hr class="admin-sep">
    <h3>Administración</h3>
    <p class="admin-dato"><strong>Es administrador:</strong> ${u.es_admin ? "sí ✅" : "no"}</p>
    <button class="age-btn ${u.es_admin ? "age-btn-outline" : "age-btn-primary"}" id="up-admin">${u.es_admin ? "Quitar admin" : "Hacer admin"}</button>
    <button class="age-btn age-btn-outline" id="up-racha" style="margin-top:8px;">Resetear racha de estudio</button>`);
  document.getElementById("up-plan").value = u.plan;
  document.getElementById("up-oposicion").value = oposicionActual();
  document.getElementById("up-copiar-uid").addEventListener("click", () => {
    navigator.clipboard?.writeText(u.uid).then(() => toast("UID copiado.")).catch(() => toast("No se pudo copiar.", "error"));
  });
  document.getElementById("up-guardar").addEventListener("click", async () => {
    const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/plan`, {
      plan: document.getElementById("up-plan").value,
      oposicion: document.getElementById("up-oposicion").value,
      motivo: document.getElementById("up-motivo").value,
    });
    if (r) { toast("Plan actualizado."); cerrarModal(); cargarUsuarios(); }
  });
  document.getElementById("up-admin").addEventListener("click", async () => {
    const dar = !u.es_admin;
    if (!confirm(dar ? "¿Dar permisos de administrador a este usuario?" : "¿Quitar los permisos de administrador?")) return;
    const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/admin`, { admin: dar });
    if (r) { toast(r.mensaje || "Hecho."); u.es_admin = dar; abrirUsuario(u.uid); }
  });
  document.getElementById("up-racha").addEventListener("click", async () => {
    if (!confirm("¿Resetear la racha de este usuario a 0?")) return;
    const r = await api("POST", `/admin/api/usuarios/${u.uid}/resetear-racha`);
    if (r) toast("Racha reseteada.");
  });
}

// ===== Reportes =====
let estadoReportes = "pendiente";
async function renderReportes() {
  const panel = document.getElementById("panel-reportes");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;">Estado
        <select id="r-estado" class="age-input" style="max-width:180px;">
          <option value="pendiente">Pendientes</option>
          <option value="revisado">Revisados</option>
          <option value="descartado">Descartados</option>
          <option value="todos">Todos</option>
        </select>
      </label>
    </div>
    <div class="age-card"><div id="reportes-lista"><p class="admin-cargando">Cargando…</p></div></div>`;
  const sel = panel.querySelector("#r-estado");
  sel.value = estadoReportes;
  sel.addEventListener("change", () => { estadoReportes = sel.value; cargarReportes(); });
  cargarReportes();
}

async function cargarReportes() {
  const cont = document.getElementById("reportes-lista");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/reportes?estado=${estadoReportes}`);
  if (!d) return;
  const pendientes = (d.reportes || []).filter((r) => r.estado === "pendiente").length;
  if (estadoReportes === "pendiente") actualizarBadgeReportes(pendientes);
  if (!(d.reportes || []).length) {
    cont.innerHTML = `<p class="admin-vacio">No hay reportes en este estado. 🎉</p>`;
    return;
  }
  const clase = (e) => e === "revisado" ? "admin-estado-revisado" : e === "descartado" ? "admin-estado-descartado" : "admin-estado-pendiente";
  cont.innerHTML = d.reportes.map((r) => {
    const po = r.pregunta_oficial;
    const detalle = po
      ? `<div class="admin-reporte-oficial">
           ${["A", "B", "C", "D"].map((k) => `<div class="admin-op-linea ${po.respuesta_correcta === k ? "admin-op-correcta" : ""}">${k}) ${escapeHtml((po.opciones || {})[k] || "")}${po.respuesta_correcta === k ? " ✔" : ""}</div>`).join("")}
           ${po.explicacion ? `<p class="admin-reporte-meta"><strong>Explicación:</strong> ${escapeHtml(po.explicacion)}</p>` : ""}
           ${po.activa ? "" : '<span class="admin-badge-alerta">ya desactivada</span>'}
         </div>`
      : `<p class="admin-reporte-meta">No se ha localizado en el banco oficial de ${escapeHtml(r.oposicion || "-")} (puede ser una pregunta generada por IA).</p>`;
    return `
    <div class="admin-reporte">
      <div class="admin-reporte-cab">
        <span class="admin-reporte-estado ${clase(r.estado)}">${escapeHtml(r.estado)}</span>
        <span class="admin-reporte-meta">${escapeHtml(r.oposicion || "-")} · ${escapeHtml(fechaCorta(r.fecha))}</span>
      </div>
      <p class="admin-reporte-preg">${escapeHtml(r.pregunta_texto)}</p>
      ${detalle}
      <p class="admin-reporte-motivo"><strong>Motivo del usuario:</strong> ${escapeHtml(r.motivo)}</p>
      <div class="admin-reporte-acciones">
        <button class="age-btn age-btn-primary admin-mini" data-editar-preg="${escapeHtml(r.pregunta_texto)}">Editar pregunta</button>
        ${r.estado !== "revisado" ? `<button class="age-btn age-btn-outline admin-mini" data-revisado="${escapeHtml(r.id)}">Marcar revisado</button>` : ""}
        ${r.estado !== "descartado" ? `<button class="age-btn age-btn-outline admin-mini" data-descartar="${escapeHtml(r.id)}">Descartar</button>` : ""}
      </div>
    </div>`;
  }).join("");
  cont.querySelectorAll("[data-revisado]").forEach((b) => b.addEventListener("click", () => cambiarEstadoReporte(b.dataset.revisado, "revisado")));
  cont.querySelectorAll("[data-descartar]").forEach((b) => b.addEventListener("click", () => cambiarEstadoReporte(b.dataset.descartar, "descartado")));
  cont.querySelectorAll("[data-editar-preg]").forEach((b) => b.addEventListener("click", () => buscarYEditarPregunta(b.dataset.editarPreg)));
}

async function cambiarEstadoReporte(id, estado) {
  const r = await api("PATCH", `/admin/api/reportes/${id}`, { estado });
  if (r) { toast(estado === "revisado" ? "Reporte marcado como revisado." : "Reporte descartado."); cargarReportes(); }
}

// Desde un reporte, localiza la pregunta oficial por su texto y abre el modal
// de edición ya cargada (si es una pregunta generada por IA que no está en la
// colección oficial, avisa de que no se puede editar centralmente).
async function buscarYEditarPregunta(textoPregunta) {
  const d = await apiGet(`/admin/api/preguntas?oposicion=${oposicionActual()}`);
  if (!d) return;
  const encontrada = (d.preguntas || []).find((p) => p.pregunta.trim() === textoPregunta.trim());
  if (!encontrada) {
    toast("Esa pregunta no está en el banco oficial de esta oposición (puede ser generada por IA). Cambia de oposición si procede.", "error");
    return;
  }
  modalPregunta(encontrada);
}

// ===== Auditoría =====
const _ACCION_ETIQUETA = {
  usuario_cambiar_plan: "💳 Cambio de plan", usuario_resetear_racha: "🔥 Reset de racha",
  admin_dar: "👑 Dar admin", admin_quitar: "🚫 Quitar admin",
  pregunta_crear: "➕ Crear pregunta", pregunta_editar: "✏️ Editar pregunta",
  pregunta_desactivar: "🗑️ Desactivar pregunta", pregunta_reactivar: "♻️ Reactivar pregunta",
  temario_anadir_ficha: "➕ Añadir ficha", temario_editar_ficha: "✏️ Editar ficha",
  temario_borrar_ficha: "🗑️ Borrar ficha", publicado: "✅ Publicar", borrador: "📝 A borrador",
  reporte_revisado: "✔️ Reporte revisado", reporte_descartado: "✖️ Reporte descartado",
};
function etiquetaAccion(a) { return _ACCION_ETIQUETA[a] || a; }

async function renderAuditoria() {
  const panel = document.getElementById("panel-auditoria");
  panel.innerHTML = `<div class="age-card"><div id="auditoria-lista"><p class="admin-cargando">Cargando…</p></div></div>`;
  const d = await apiGet("/admin/api/auditoria?limite=150");
  const cont = document.getElementById("auditoria-lista");
  if (!d) return;
  if (!(d.entradas || []).length) {
    cont.innerHTML = `<p class="admin-vacio">Aún no hay acciones registradas.</p>`;
    return;
  }
  const filas = d.entradas.map((e) => {
    const fecha = (e.fecha || "").replace("T", " ").slice(0, 16);
    return `<tr>
      <td>${escapeHtml(fecha)}</td>
      <td>${escapeHtml(etiquetaAccion(e.accion))}</td>
      <td>${escapeHtml(e.objetivo || "-")}${e.detalle ? `<br><span class="admin-reporte-meta">${escapeHtml(e.detalle)}</span>` : ""}</td>
      <td>${escapeHtml(e.email_admin || "-")}</td>
    </tr>`;
  }).join("");
  cont.innerHTML = `
    <p class="admin-reporte-meta" style="margin-bottom:8px;">Últimas ${d.entradas.length} de ${d.total} acciones</p>
    <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Fecha (UTC)</th><th>Acción</th><th>Sobre</th><th>Admin</th></tr></thead><tbody>${filas}</tbody></table></div>`;
}

// ===== init =====
document.addEventListener("DOMContentLoaded", async () => {
  if (!(await esAdmin())) {
    mostrarNoAutorizado();
    return;
  }
  document.getElementById("admin-contenido").style.display = "block";
  document.querySelectorAll(".admin-tab").forEach((b) => b.addEventListener("click", () => activarPestana(b.dataset.tab)));
  document.getElementById("admin-oposicion").addEventListener("change", () => { temaSeleccionado = null; RENDERS[pestanaActual](); });
  activarPestana("dashboard");
});
