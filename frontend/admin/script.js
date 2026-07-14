// Panel de administración. El backend (requiere_admin) es la barrera real;
// aquí solo se comprueba esAdmin para no montar la UI a quien no lo es.
import { esAdmin, obtenerPermisos, obtenerAuthHeaders } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

// Qué permiso necesita cada pestaña. Las de 'admin' solo las ve el super-admin.
const PERMISO_POR_PESTANA = {
  dashboard: "cualquiera", temario: "temario", preguntas: "temario", analitica: "temario",
  usuarios: "usuarios", reportes: "reportes", auditoria: "admin", sistema: "admin",
};
let _permisos = { admin: false, permisos: [] };
function puedeVer(pestana) {
  const req = PERMISO_POR_PESTANA[pestana];
  if (_permisos.admin) return true;
  if (req === "admin") return false;
  if (req === "cualquiera") return _permisos.permisos.length > 0;
  return _permisos.permisos.includes(req);
}

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
  analitica: renderAnalitica,
  usuarios: renderUsuarios,
  reportes: renderReportes,
  auditoria: renderAuditoria,
  sistema: renderSistema,
};
let pestanaActual = "dashboard";

function activarPestana(nombre) {
  if (!puedeVer(nombre)) return;
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
      <div class="age-card admin-stat"><span class="admin-stat-num">${(d.coste_ia_mes || 0).toFixed(2)}€</span><span class="admin-stat-lbl">Coste IA (este mes)</span></div>
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
      <h3>Usuarios que más IA consumen (este mes)</h3>
      <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Email</th><th>Plan</th><th class="admin-num">Coste</th></tr></thead><tbody>${
        (d.top_gastadores_ia || []).map((g) => `<tr class="admin-fila-click" data-uid-gasto="${escapeHtml(g.uid)}"><td>${escapeHtml(g.email || "(sin email)")}</td><td><span class="admin-chip">${escapeHtml(g.plan)}</span></td><td class="admin-num">${(g.coste_mes || 0).toFixed(4)}€</td></tr>`).join("")
        || '<tr><td colspan="3" class="admin-vacio">Sin consumo de IA este mes.</td></tr>'}</tbody></table></div>
    </div>

    <div class="age-card admin-bloque">
      <h3>Top 5 temas más fallados (todos los usuarios)</h3>
      <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Tema</th><th class="admin-num">Fallos</th></tr></thead><tbody>${temas}</tbody></table></div>
    </div>`;

  panel.querySelector("#stat-reportes")?.addEventListener("click", () => activarPestana("reportes"));
  panel.querySelectorAll("[data-uid-gasto]").forEach((tr) => tr.addEventListener("click", () => {
    if (puedeVer("usuarios")) abrirUsuario(tr.dataset.uidGasto);
  }));
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
  const op = oposicionActual();
  const arbol = (d.bloques || []).map((b) => `
    <div class="admin-bloque-arbol">
      <div class="admin-bloque-cab">
        <span class="admin-bloque-titulo">${escapeHtml(b.titulo)}
          <button class="admin-icono" data-renombrar-bloque="${escapeHtml(b.id)}" title="Renombrar bloque">✏️</button>
        </span>
        <label class="admin-toggle" title="Publicado / borrador">
          <input type="checkbox" data-bloque-pub="${escapeHtml(b.id)}" ${b.publicado ? "checked" : ""}>
          <span>${b.publicado ? "Publicado" : "Borrador"}</span>
        </label>
      </div>
      ${b.temas.map((t) => `
        <div class="admin-tema-fila">
          <button type="button" class="admin-tema-item ${t.num_chunks ? "" : "sin-contenido"}" data-bloque="${escapeHtml(b.id)}" data-tema="${escapeHtml(t.id)}">
            <span>${escapeHtml(t.titulo)}${t.publicado ? "" : ' <span class="admin-badge-alerta">borrador</span>'}</span>
            <span class="admin-badge">${t.num_chunks}</span>
          </button>
          <button class="admin-icono" data-renombrar-tema="${escapeHtml(b.id)}|${escapeHtml(t.id)}|${escapeHtml(t.titulo)}" title="Renombrar tema">✏️</button>
        </div>`).join("")}
      <button class="age-btn age-btn-outline admin-mini admin-nuevo-tema" data-bloque="${escapeHtml(b.id)}" style="margin-top:6px;">+ Tema</button>
    </div>`).join("") || '<p class="admin-vacio">Sin bloques todavía.</p>';

  panel.innerHTML = `
    <div class="admin-filtros">
      <button class="age-btn age-btn-primary admin-mini" id="t-nuevo-bloque">+ Nuevo bloque</button>
    </div>
    <div class="admin-temario-grid">
      <div class="age-card admin-arbol">${arbol}</div>
      <div class="age-card admin-chunks" id="admin-chunks"><p class="admin-vacio">Elige un tema para ver y editar sus fichas.</p></div>
    </div>`;

  panel.querySelector("#t-nuevo-bloque").addEventListener("click", async () => {
    const id = prompt("Id del nuevo bloque (ej. bloque_07):");
    if (!id) return;
    const titulo = prompt("Título del bloque:", "") || id;
    const r = await api("POST", `/admin/api/temario/${op}/nuevo-bloque`, { id: id.trim(), titulo });
    if (r) { toast("Bloque creado."); renderTemario(); }
  });
  panel.querySelectorAll(".admin-nuevo-tema").forEach((btn) => btn.addEventListener("click", async () => {
    const id = prompt("Id del nuevo tema (ej. tema_03):");
    if (!id) return;
    const titulo = prompt("Título del tema:", "") || id;
    const r = await api("POST", `/admin/api/temario/${op}/${btn.dataset.bloque}/nuevo-tema`, { id: id.trim(), titulo });
    if (r) { toast("Tema creado."); renderTemario(); }
  }));
  panel.querySelectorAll("[data-renombrar-bloque]").forEach((btn) => btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const titulo = prompt("Nuevo título del bloque:");
    if (!titulo) return;
    const r = await api("PATCH", `/admin/api/temario/${op}/${btn.dataset.renombrarBloque}`, { titulo });
    if (r) { toast("Bloque renombrado."); renderTemario(); }
  }));
  panel.querySelectorAll("[data-renombrar-tema]").forEach((btn) => btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const [bloque, tema, actual] = btn.dataset.renombrarTema.split("|");
    const titulo = prompt("Nuevo título del tema:", actual);
    if (!titulo || titulo === actual) return;
    const r = await api("PATCH", `/admin/api/temario/${op}/${bloque}/${tema}/titulo`, { titulo });
    if (r) { toast("Tema renombrado."); renderTemario(); }
  }));

  panel.querySelectorAll("[data-bloque-pub]").forEach((chk) => chk.addEventListener("change", async () => {
    const r = await api("PATCH", `/admin/api/temario/${op}/${chk.dataset.bloquePub}/publicado`, { publicado: chk.checked });
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
      <button class="age-btn age-btn-outline admin-filtros-btn" id="p-importar">⬆ Importar</button>
      <button class="age-btn age-btn-primary admin-filtros-btn" id="p-nueva">+ Nueva</button>
    </div>
    <div class="age-card"><div id="preguntas-tabla"><p class="admin-cargando">Cargando…</p></div></div>`;
  panel.querySelector("#f-aplicar").addEventListener("click", cargarPreguntas);
  panel.querySelector("#p-nueva").addEventListener("click", () => modalPregunta(null));
  panel.querySelector("#p-importar").addEventListener("click", modalImportar);
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
      <input type="radio" name="correcta" id="rc-${k}" value="${k}" class="admin-opcion-check" ${correcta === k ? "checked" : ""}>
      <label for="rc-${k}" class="admin-opcion-letra">${k}</label>
      <input class="age-input admin-opcion-txt" id="op-${k}" value="${escapeHtml(o[k] || "")}" placeholder="Opción ${k}">
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

const _EJEMPLO_IMPORT = JSON.stringify([{
  pregunta: "¿Enunciado de ejemplo?",
  opciones: { A: "Opción A", B: "Opción B", C: "Opción C", D: "Opción D" },
  respuesta_correcta: "A",
  explicacion: "Por qué es la A (opcional).",
  tema_id: "bloque_01-tema_01",
}], null, 2);

function modalImportar() {
  abrirModal(`
    <h2>Importar examen (por lote)</h2>
    <p class="admin-reporte-meta">Pega una lista JSON de preguntas. Se crearán en <strong>${escapeHtml(oposicionActual())}</strong>. Las que no pasen validación se te indicarán sin bloquear al resto.</p>
    <label>Nombre del examen (opcional, se aplica a las que no lo traigan)</label>
    <input class="age-input" id="imp-examen" placeholder="Ej. AGE 2025">
    <label>Preguntas (JSON)</label>
    <textarea class="age-input" id="imp-json" rows="12" placeholder='${escapeHtml(_EJEMPLO_IMPORT)}'></textarea>
    <button class="age-btn age-btn-outline admin-mini" id="imp-ejemplo" style="margin-top:8px;">Rellenar con ejemplo</button>
    <button class="age-btn age-btn-primary" id="imp-enviar" style="margin-top:8px;">Importar</button>
    <div id="imp-resultado" style="margin-top:12px;"></div>`);
  document.getElementById("imp-ejemplo").addEventListener("click", () => { document.getElementById("imp-json").value = _EJEMPLO_IMPORT; });
  document.getElementById("imp-enviar").addEventListener("click", async () => {
    let preguntas;
    try {
      preguntas = JSON.parse(document.getElementById("imp-json").value);
    } catch {
      toast("El JSON no es válido. Revisa las comas y comillas.", "error");
      return;
    }
    if (!Array.isArray(preguntas)) { toast("Debe ser una lista [ ... ].", "error"); return; }
    const r = await api("POST", "/admin/api/preguntas/importar", {
      oposicion: oposicionActual(), examen: document.getElementById("imp-examen").value, preguntas,
    });
    if (!r) return;
    const errores = (r.errores || []).map((e) => `<li>Fila ${e.indice + 1}: ${escapeHtml(e.error)}</li>`).join("");
    document.getElementById("imp-resultado").innerHTML = `
      <div class="admin-aviso"><strong>${r.creadas}</strong> de ${r.total} preguntas creadas.${errores ? `<ul style="margin-top:6px;">${errores}</ul>` : ""}</div>`;
    toast(`${r.creadas} preguntas importadas.`);
    if (pestanaActual === "preguntas") cargarPreguntas();
  });
}

// ===== Analítica de contenido =====
async function renderAnalitica() {
  const panel = document.getElementById("panel-analitica");
  panel.innerHTML = `<p class="admin-cargando">Cargando analítica…</p>`;
  const d = await apiGet(`/admin/api/analitica-contenido?oposicion=${oposicionActual()}`);
  if (!d) return;
  const temas = d.temas || [];
  if (!temas.length && !(d.sin_actividad || []).length) {
    panel.innerHTML = `<div class="age-card"><p class="admin-vacio">Todavía no hay actividad de estudio en ${escapeHtml(oposicionActual())}.</p></div>`;
    return;
  }

  const barra = (t) => {
    const pct = t.tasa_acierto == null ? 0 : t.tasa_acierto;
    const color = pct >= 70 ? "var(--age-success,#28a745)" : pct >= 50 ? "#d98324" : "var(--age-danger,#dc3545)";
    return `<div class="admin-barra"><span class="admin-barra-relleno" style="width:${pct}%;background:${color}"></span></div>`;
  };
  const filaEstudio = (t) => `<tr>
      <td>${escapeHtml(t.titulo || t.tema_id)}</td>
      <td class="admin-num">${t.intentos}</td>
      <td class="admin-num">${t.tasa_acierto == null ? "-" : t.tasa_acierto + "%"}</td>
    </tr>`;

  // Peor tasa de acierto: solo temas con volumen suficiente (>=20 respondidas)
  // para que el % sea significativo.
  const peores = temas.filter((t) => t.respondidas >= 20)
    .sort((a, b) => (a.tasa_acierto ?? 101) - (b.tasa_acierto ?? 101)).slice(0, 10);

  panel.innerHTML = `
    <div class="age-card admin-bloque">
      <h3>Temas más estudiados (${escapeHtml(d.oposicion)})</h3>
      <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Tema</th><th class="admin-num">Intentos</th><th class="admin-num">Acierto</th></tr></thead>
        <tbody>${temas.slice(0, 15).map(filaEstudio).join("") || '<tr><td colspan="3" class="admin-vacio">Sin datos.</td></tr>'}</tbody></table></div>
    </div>

    <div class="age-card admin-bloque">
      <h3>Temas con peor tasa de acierto</h3>
      <p class="admin-reporte-meta">Solo temas con 20+ preguntas respondidas. Útil para detectar temario flojo o preguntas mal redactadas.</p>
      ${peores.length ? peores.map((t) => `
        <div class="admin-analitica-fila">
          <div class="admin-analitica-tema">${escapeHtml(t.titulo || t.tema_id)}</div>
          ${barra(t)}
          <div class="admin-analitica-pct">${t.tasa_acierto}% <span class="admin-reporte-meta">(${t.respondidas})</span></div>
        </div>`).join("") : '<p class="admin-vacio">Aún no hay temas con volumen suficiente.</p>'}
    </div>

    <div class="age-card admin-bloque">
      <h3>Temas sin ninguna actividad (${(d.sin_actividad || []).length})</h3>
      <p class="admin-reporte-meta">Nadie ha hecho preguntas de estos temas todavía.</p>
      <div class="admin-chips">${(d.sin_actividad || []).map((t) => `<span class="admin-chip">${escapeHtml(t.titulo || t.tema_id)}</span>`).join("") || '<span class="admin-vacio">Todos los temas tienen actividad. 🎉</span>'}</div>
    </div>`;
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
      ${_permisos.admin ? '<button class="age-btn age-btn-outline admin-filtros-btn" id="u-crear">+ Crear usuario</button>' : ""}
    </div>
    <div class="age-card"><div id="usuarios-tabla"><p class="admin-cargando">Cargando…</p></div></div>`;
  panel.querySelector("#u-aplicar").addEventListener("click", () => { paginaUsuarios = 1; cargarUsuarios(); });
  panel.querySelector("#u-crear")?.addEventListener("click", modalCrearUsuario);
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

function modalCrearUsuario() {
  abrirModal(`
    <h2>Crear usuario</h2>
    <p class="admin-reporte-meta">Se crea la cuenta con email y contraseña. Comunícale la contraseña al usuario; podrá cambiarla luego.</p>
    <label>Email</label>
    <input class="age-input" id="nu-email" type="email" placeholder="persona@correo.com">
    <label>Contraseña (mín. 6 caracteres)</label>
    <input class="age-input" id="nu-pass" type="text" placeholder="Contraseña inicial">
    <label>Nombre (opcional)</label>
    <input class="age-input" id="nu-nombre" placeholder="Nombre">
    <div class="admin-form-fila">
      <div><label>Plan de partida</label>
        <select class="age-input" id="nu-plan"><option value="">Gratis</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
      </div>
      <div><label>Para la oposición</label>
        <select class="age-input" id="nu-oposicion"><option value="AGE">AGE</option><option value="GACE">GACE</option><option value="AUXILIAR">Auxiliar</option></select>
      </div>
    </div>
    <label class="admin-rol-check" style="margin-top:12px;"><input type="checkbox" id="nu-verificado"> <span>Marcar email como verificado</span></label>
    <label class="admin-rol-check"><input type="checkbox" id="nu-admin"> <span>Hacer administrador total</span></label>
    <p class="admin-dato" style="margin-top:8px;"><strong>Roles (acceso parcial, si no es admin):</strong></p>
    ${["temario", "reportes", "usuarios"].map((p) => `
      <label class="admin-rol-check"><input type="checkbox" class="nu-permiso" value="${p}"> <span>${p === "temario" ? "Temario y preguntas" : p === "reportes" ? "Reportes" : "Usuarios y planes"}</span></label>`).join("")}
    <button class="age-btn age-btn-primary" id="nu-crear" style="margin-top:14px;">Crear usuario</button>`);
  document.getElementById("nu-crear").addEventListener("click", async () => {
    const cuerpo = {
      email: document.getElementById("nu-email").value,
      password: document.getElementById("nu-pass").value,
      nombre: document.getElementById("nu-nombre").value,
      plan: document.getElementById("nu-plan").value || undefined,
      oposicion: document.getElementById("nu-oposicion").value,
      email_verificado: document.getElementById("nu-verificado").checked,
      admin: document.getElementById("nu-admin").checked,
      permisos: Array.from(document.querySelectorAll(".nu-permiso:checked")).map((c) => c.value),
    };
    const r = await api("POST", "/admin/api/usuarios", cuerpo);
    if (r) { toast("Usuario creado."); cerrarModal(); paginaUsuarios = 1; cargarUsuarios(); }
  });
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

// ---- Ficha de cliente: piezas visuales reutilizables ----
function fichaPlanBadge(plan) {
  const p = (plan || "gratis").toLowerCase();
  const map = { premium: ["Premium", "ficha-badge-premium"], basico: ["Básico", "ficha-badge-basico"], gratis: ["Gratis", "ficha-badge-gratis"] };
  const [txt, cls] = map[p] || map.gratis;
  return `<span class="ficha-badge ${cls}">${txt}</span>`;
}
function fichaEuros(n) { return (n || 0).toLocaleString("es", { minimumFractionDigits: 4, maximumFractionDigits: 4 }) + " €"; }
const _MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
function mesLegible(m) { const p = (m || "").split("-"); return (_MESES_CORTOS[(+p[1] || 1) - 1] || "") + " " + (p[0] || ""); }
function fichaMini(icono, num, label) {
  return `<div class="ficha-mini"><span class="ficha-mini-ico">${icono}</span><span class="ficha-mini-num">${(num || 0).toLocaleString("es")}</span><span class="ficha-mini-lbl">${label}</span></div>`;
}
function fichaCosteBarras(hist) {
  if (!hist || !hist.length) return '<p class="ficha-vacio">Sin consumo de IA todavía.</p>';
  const barras = hist.slice(-12); // últimos 12 meses en el gráfico
  const max = Math.max(...barras.map((h) => h.coste)) || 1;
  return `<div class="ficha-barras" role="group" aria-label="Gasto de IA por mes">${barras.map((h) => {
    const alt = h.coste > 0 ? Math.max(8, Math.round((h.coste / max) * 100)) : 3;
    const tip = `${mesLegible(h.mes)}: ${fichaEuros(h.coste)} · ${(h.tokens || 0).toLocaleString("es")} tokens · ${h.llamadas || 0} llamadas`;
    return `<button type="button" class="ficha-barra-col" data-mes="${escapeHtml(h.mes)}" title="${tip}"><div class="ficha-barra-wrap"><div class="ficha-barra" style="height:${alt}%"></div></div><span class="ficha-barra-lbl">${escapeHtml((h.mes || "").slice(5))}</span></button>`;
  }).join("")}</div>`;
}

async function abrirUsuario(uid) {
  abrirModal(`<p class="admin-cargando">Cargando ficha…</p>`);
  const u = await apiGet(`/admin/api/usuarios/${uid}`);
  if (!u) { cerrarModal(); return; }
  const c = u.contenido_creado || {};
  const r = u.rendimiento || {};
  const inicial = (u.email || "?").trim().charAt(0).toUpperCase() || "?";
  const oposActivas = (u.oposiciones_activas || []);
  const override = u.admin_override
    ? `<div class="admin-aviso"><strong>Último cambio de soporte:</strong> ${escapeHtml(u.admin_override.cambio || "")} — ${escapeHtml(u.admin_override.motivo || "sin motivo")} (${escapeHtml(fechaCorta(u.admin_override.fecha))})</div>`
    : "";
  abrirModal(`
    <div class="ficha">
      <div class="ficha-cabecera">
        <div class="ficha-avatar">${escapeHtml(inicial)}</div>
        <div class="ficha-id">
          <h2 class="ficha-email">${escapeHtml(u.email || "(sin email)")}</h2>
          ${u.nombre ? `<p class="ficha-nombre">${escapeHtml(u.nombre)}</p>` : ""}
          <div class="ficha-badges">
            ${fichaPlanBadge(u.plan)}
            <span class="ficha-badge ${u.email_verificado ? "ficha-badge-ok" : "ficha-badge-warn"}">${u.email_verificado ? "✓ Verificado" : "Sin verificar"}</span>
            ${u.es_admin ? '<span class="ficha-badge ficha-badge-admin">👑 Admin total</span>' : ""}
            ${(!u.es_admin && (u.permisos || []).length) ? `<span class="ficha-badge ficha-badge-rol">🛡️ ${(u.permisos || []).length} rol(es)</span>` : ""}
            ${u.bloqueado ? '<span class="ficha-badge ficha-badge-bloqueo">🚫 Bloqueado</span>' : ""}
          </div>
          <p class="ficha-uid"><span>UID: ${escapeHtml(u.uid)}</span><button class="admin-copiar" id="up-copiar-uid">copiar</button></p>
        </div>
      </div>

      <div class="ficha-kpis">
        <div class="ficha-kpi"><span class="ficha-kpi-num">${(u.tests_total || 0).toLocaleString("es")}</span><span class="ficha-kpi-lbl">Tests hechos</span></div>
        <div class="ficha-kpi"><span class="ficha-kpi-num">${u.racha_actual || 0}</span><span class="ficha-kpi-lbl">Racha (máx ${u.racha_maxima || 0})</span></div>
        <div class="ficha-kpi"><span class="ficha-kpi-num">${u.ultima_nota != null ? escapeHtml(u.ultima_nota) : "–"}</span><span class="ficha-kpi-lbl">Última nota</span></div>
        <div class="ficha-kpi"><span class="ficha-kpi-num">${r.porcentaje != null ? r.porcentaje + "%" : "–"}</span><span class="ficha-kpi-lbl">Acierto global</span></div>
      </div>

      <div class="ficha-cols">
        <div class="ficha-panel ficha-coste">
          <div class="ficha-panel-cab"><span class="ficha-panel-ico">🤖</span><h3>Gasto en IA</h3></div>
          <div class="ficha-coste-cifras">
            <div class="ficha-coste-grande"><span class="ficha-coste-num">${fichaEuros(u.coste_ia_mes)}</span><span class="ficha-coste-lbl">este mes</span></div>
            <div class="ficha-coste-sec">
              <div><strong>${fichaEuros(u.coste_ia_total)}</strong><span>histórico</span></div>
              <div><strong>${(u.tokens_ia_total || 0).toLocaleString("es")}</strong><span>tokens</span></div>
            </div>
          </div>
          ${fichaCosteBarras(u.coste_ia_historico)}
          <p class="ficha-coste-detalle" id="up-coste-detalle">${(u.coste_ia_historico || []).length ? "Toca una barra para ver el detalle de ese mes." : ""}</p>
          ${(u.coste_ia_historico || []).length ? `
          <details class="ficha-rango">
            <summary>🔎 Buscar por rango de meses</summary>
            <div class="ficha-rango-cuerpo">
              <div class="ficha-rango-selects">
                <label>Desde <select id="up-rango-desde" class="age-input">${(u.coste_ia_historico || []).map((h) => `<option value="${escapeHtml(h.mes)}">${mesLegible(h.mes)}</option>`).join("")}</select></label>
                <label>Hasta <select id="up-rango-hasta" class="age-input">${(u.coste_ia_historico || []).map((h) => `<option value="${escapeHtml(h.mes)}">${mesLegible(h.mes)}</option>`).join("")}</select></label>
              </div>
              <div class="ficha-rango-res" id="up-rango-res"></div>
            </div>
          </details>` : ""}
        </div>

        <div class="ficha-panel">
          <div class="ficha-panel-cab"><span class="ficha-panel-ico">📚</span><h3>Contenido creado</h3></div>
          <div class="ficha-minis">
            ${fichaMini("📄", c.documentos, "Documentos")}
            ${fichaMini("📝", c.resumenes, "Resúmenes")}
            ${fichaMini("🗂️", c.esquemas, "Esquemas")}
            ${fichaMini("🃏", c.tarjetas, "Tarjetas")}
            ${fichaMini("🧪", c.tests_pdf, "Tests de PDF")}
            ${fichaMini("⭐", c.favoritas, "Favoritas")}
            ${fichaMini("🔁", c.falladas, "A repasar")}
          </div>
        </div>
      </div>

      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">🪪</span><h3>Datos de la cuenta</h3></div>
        <dl class="ficha-datos">
          <div><dt>Plan</dt><dd>${escapeHtml(u.plan)}${oposActivas.length ? " · " + oposActivas.map(escapeHtml).join(", ") : ""}</dd></div>
          <div><dt>Alta</dt><dd>${escapeHtml(fechaCorta(u.fecha_creacion))}</dd></div>
          <div><dt>Última actividad</dt><dd>${escapeHtml(fechaCorta(u.ultima_actividad))}</dd></div>
          <div><dt>Rendimiento</dt><dd>${(r.aciertos || 0)} aciertos · ${(r.fallos || 0)} fallos · ${(r.blancos || 0)} blancos</dd></div>
        </dl>
        ${override}
      </div>

      <details class="ficha-acordeon">
        <summary><span class="ficha-panel-ico">💳</span> Cambiar plan (soporte)</summary>
        <div class="ficha-acordeon-cuerpo">
          <div class="admin-form-fila">
            <select id="up-plan" class="age-input"><option value="gratis">Gratis</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
            <select id="up-oposicion" class="age-input"><option value="AGE">AGE</option><option value="GACE">GACE</option><option value="AUXILIAR">Auxiliar</option></select>
          </div>
          <input id="up-motivo" class="age-input" placeholder="Motivo (queda registrado)" style="margin-top:8px;">
          <button class="age-btn age-btn-primary" id="up-guardar" style="margin-top:10px;">Cambiar plan</button>
        </div>
      </details>

      <details class="ficha-acordeon">
        <summary><span class="ficha-panel-ico">🛟</span> Soporte y notas</summary>
        <div class="ficha-acordeon-cuerpo">
          <h4 class="ficha-sub">📝 Notas internas</h4>
          <div id="up-notas-lista" class="ficha-notas"></div>
          <textarea class="age-input" id="up-nota-nueva" rows="2" placeholder="Escribe una nota nueva…"></textarea>
          <button class="age-btn age-btn-primary admin-mini" id="up-nota-anadir" style="margin-top:6px;">+ Añadir nota</button>
          <h4 class="ficha-sub" style="margin-top:18px;">🛠️ Acciones de soporte</h4>
          <div class="ficha-soporte-acciones">
            <button class="age-btn admin-mini ficha-btn-soporte" id="up-racha">🔥 Resetear racha</button>
            <button class="age-btn admin-mini ficha-btn-soporte" id="up-limites">♻️ Resetear límites de uso</button>
            <button class="age-btn admin-mini ficha-btn-soporte" id="up-reset-pass">🔑 Enlace de contraseña</button>
            ${u.email_verificado ? "" : '<button class="age-btn admin-mini ficha-btn-soporte" id="up-verif">✉️ Enlace de verificación</button>'}
          </div>
          <div id="up-enlace-caja"></div>
        </div>
      </details>

      <details class="ficha-acordeon ficha-acordeon-peligro">
        <summary><span class="ficha-panel-ico">🔐</span> Roles y administración</summary>
        <div class="ficha-acordeon-cuerpo">
          ${_permisos.admin ? `
            <p class="ficha-roles-intro">${u.es_admin ? "Este usuario es <strong>administrador total</strong> (acceso a todo)." : "Da acceso parcial marcando solo las secciones que necesite, sin hacerlo admin total."}</p>
            <div class="ficha-roles">
              ${(u.permisos_disponibles || ["temario", "reportes", "usuarios"]).map((p) => `
                <label class="ficha-rol ${u.es_admin ? "ficha-rol-off" : ""}">
                  <input type="checkbox" class="up-permiso" value="${escapeHtml(p)}" ${(u.permisos || []).includes(p) ? "checked" : ""} ${u.es_admin ? "disabled" : ""}>
                  <span class="ficha-rol-ico">${p === "temario" ? "📖" : p === "reportes" ? "🚩" : "👥"}</span>
                  <span class="ficha-rol-txt"><strong>${p === "temario" ? "Temario y preguntas" : p === "reportes" ? "Reportes de preguntas" : "Usuarios y planes"}</strong><small>${p === "temario" ? "Editar y subir temario, gestionar preguntas" : p === "reportes" ? "Revisar reportes de preguntas de los usuarios" : "Ver usuarios, cambiar planes y roles"}</small></span>
                </label>`).join("")}
            </div>
            <button class="age-btn age-btn-outline admin-mini" id="up-roles" ${u.es_admin ? "disabled" : ""} style="margin-top:10px;">Guardar roles</button>
            <hr class="admin-sep">
            <div class="ficha-admin-acciones">
              <button class="age-btn ${u.es_admin ? "age-btn-outline" : "age-btn-primary"}" id="up-admin">${u.es_admin ? "Quitar admin total" : "Hacer admin total"}</button>
              <button class="age-btn age-btn-outline admin-mini" id="up-bloqueo">${u.bloqueado ? "Restaurar acceso" : "Bloquear acceso"}</button>
              <button class="age-btn age-btn-outline admin-mini ficha-btn-peligro" id="up-eliminar">Eliminar cuenta</button>
            </div>
          ` : `<p class="admin-reporte-meta">Solo un administrador total puede cambiar roles y administración.</p>`}
        </div>
      </details>
    </div>`);
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
  // ---- Notas internas (lista: añadir / eliminar) ----
  let notas = Array.isArray(u.notas_lista) ? u.notas_lista.slice() : [];
  const renderNotas = () => {
    const cont = document.getElementById("up-notas-lista");
    if (!cont) return;
    if (!notas.length) { cont.innerHTML = '<p class="ficha-notas-vacio">Sin notas todavía.</p>'; return; }
    cont.innerHTML = notas.map((n) => {
      const meta = [n.autor, n.fecha ? fechaCorta(n.fecha) : ""].filter(Boolean).join(" · ");
      return `<div class="ficha-nota"><div class="ficha-nota-txt">${escapeHtml(n.texto || "")}</div>
        <div class="ficha-nota-pie">${meta ? `<span class="ficha-nota-meta">${escapeHtml(meta)}</span>` : "<span></span>"}
        <button class="ficha-nota-borrar" data-id="${escapeHtml(n.id)}" title="Eliminar nota">🗑</button></div></div>`;
    }).join("");
    cont.querySelectorAll(".ficha-nota-borrar").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("¿Eliminar esta nota?")) return;
      const r = await api("DELETE", `/admin/api/usuarios/${u.uid}/notas/${b.dataset.id}`);
      if (r) { notas = notas.filter((x) => x.id !== b.dataset.id); renderNotas(); toast("Nota eliminada."); }
    }));
  };
  renderNotas();
  document.getElementById("up-nota-anadir")?.addEventListener("click", async () => {
    const ta = document.getElementById("up-nota-nueva");
    const texto = (ta.value || "").trim();
    if (!texto) { toast("Escribe algo en la nota.", "error"); return; }
    const r = await api("POST", `/admin/api/usuarios/${u.uid}/notas`, { texto });
    if (r && r.nota) { notas.push(r.nota); ta.value = ""; renderNotas(); toast("Nota añadida."); }
  });
  // ---- Gasto IA: tocar barra para ver el mes ----
  const hist = u.coste_ia_historico || [];
  const detalle = document.getElementById("up-coste-detalle");
  document.querySelectorAll(".ficha-barra-col").forEach((b) => b.addEventListener("click", () => {
    const h = hist.find((x) => x.mes === b.dataset.mes);
    if (h && detalle) detalle.innerHTML = `<strong>${mesLegible(h.mes)}:</strong> ${fichaEuros(h.coste)} · ${(h.tokens || 0).toLocaleString("es")} tokens (${(h.tokens_in || 0).toLocaleString("es")} entrada / ${(h.tokens_out || 0).toLocaleString("es")} salida) · ${h.llamadas || 0} llamadas`;
    document.querySelectorAll(".ficha-barra-col").forEach((x) => x.classList.toggle("activa", x === b));
  }));
  // ---- Gasto IA: rango de meses ----
  const rangoDesde = document.getElementById("up-rango-desde");
  const rangoHasta = document.getElementById("up-rango-hasta");
  const calcularRango = () => {
    if (!rangoDesde || !rangoHasta) return;
    let a = rangoDesde.value, b = rangoHasta.value;
    if (a > b) { [a, b] = [b, a]; }
    const sel = hist.filter((h) => h.mes >= a && h.mes <= b);
    const coste = sel.reduce((s, h) => s + (h.coste || 0), 0);
    const tokens = sel.reduce((s, h) => s + (h.tokens || 0), 0);
    const llamadas = sel.reduce((s, h) => s + (h.llamadas || 0), 0);
    document.getElementById("up-rango-res").innerHTML =
      `<strong>${mesLegible(a)} → ${mesLegible(b)}:</strong> ${fichaEuros(coste)} · ${tokens.toLocaleString("es")} tokens · ${llamadas.toLocaleString("es")} llamadas`;
  };
  if (rangoDesde && rangoHasta) {
    rangoDesde.value = hist.length ? hist[0].mes : "";
    rangoHasta.value = hist.length ? hist[hist.length - 1].mes : "";
    rangoDesde.addEventListener("change", calcularRango);
    rangoHasta.addEventListener("change", calcularRango);
    calcularRango();
  }
  document.getElementById("up-admin")?.addEventListener("click", async () => {
    const dar = !u.es_admin;
    if (!confirm(dar ? "¿Dar permisos de administrador TOTAL a este usuario?" : "¿Quitar los permisos de administrador?")) return;
    const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/admin`, { admin: dar });
    if (r) { toast(r.mensaje || "Hecho."); u.es_admin = dar; abrirUsuario(u.uid); }
  });
  document.getElementById("up-roles")?.addEventListener("click", async () => {
    const permisos = Array.from(document.querySelectorAll(".up-permiso:checked")).map((c) => c.value);
    const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/roles`, { permisos });
    if (r) { toast(r.mensaje || "Roles actualizados."); u.permisos = permisos; }
  });
  document.getElementById("up-racha").addEventListener("click", async () => {
    if (!confirm("¿Resetear la racha de este usuario a 0?")) return;
    const r = await api("POST", `/admin/api/usuarios/${u.uid}/resetear-racha`);
    if (r) toast("Racha reseteada.");
  });
  document.getElementById("up-limites").addEventListener("click", async () => {
    if (!confirm("¿Poner a cero los contadores de uso de IA de este usuario?")) return;
    const r = await api("POST", `/admin/api/usuarios/${u.uid}/resetear-limites`);
    if (r) toast("Límites de uso reseteados.");
  });
  const mostrarEnlace = async (tipo) => {
    const r = await api("POST", `/admin/api/usuarios/${u.uid}/enlace`, { tipo });
    if (!r) return;
    const caja = document.getElementById("up-enlace-caja");
    caja.innerHTML = `<div class="admin-aviso">Enlace de ${tipo === "verificacion" ? "verificación" : "contraseña"} (pásaselo al usuario):
      <input class="age-input" style="margin-top:6px;" readonly value="${escapeHtml(r.enlace)}"></div>`;
    const input = caja.querySelector("input");
    input.addEventListener("click", () => input.select());
    input.select();
    navigator.clipboard?.writeText(r.enlace).then(() => toast("Enlace copiado al portapapeles.")).catch(() => {});
  };
  document.getElementById("up-reset-pass").addEventListener("click", () => mostrarEnlace("password"));
  document.getElementById("up-verif")?.addEventListener("click", () => mostrarEnlace("verificacion"));
  document.getElementById("up-bloqueo")?.addEventListener("click", async () => {
    const bloquear = !u.bloqueado;
    if (!confirm(bloquear ? "¿Bloquear el acceso de este usuario? No podrá iniciar sesión." : "¿Restaurar el acceso de este usuario?")) return;
    const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/bloqueo`, { bloqueado: bloquear });
    if (r) { toast(r.mensaje || "Hecho."); u.bloqueado = bloquear; abrirUsuario(u.uid); }
  });
  document.getElementById("up-eliminar")?.addEventListener("click", async () => {
    if (!confirm(`⚠️ Vas a ELIMINAR por completo la cuenta de ${u.email}. Es IRREVERSIBLE (se borran todos sus datos y su suscripción). ¿Continuar?`)) return;
    if (!confirm("Confirma otra vez: esta acción no se puede deshacer.")) return;
    const r = await api("DELETE", `/admin/api/usuarios/${u.uid}`);
    if (r) { toast("Cuenta eliminada."); cerrarModal(); cargarUsuarios(); }
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

// ===== Sistema (salud + banner) =====
async function renderSistema() {
  const panel = document.getElementById("panel-sistema");
  panel.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const [sis, banner] = await Promise.all([apiGet("/admin/api/sistema"), apiGet("/admin/api/banner")]);
  if (!sis) return;
  const diag = sis.diagnostico || {};
  const servicios = (sis.servicios || []).map((s) => {
    // 3 estados: verde (OK), rojo (crítico sin configurar), ámbar (opcional
    // sin configurar -> no es un problema, no alarma).
    const estado = s.ok
      ? { punto: "🟢", txt: "Configurado", cls: "sis-ok" }
      : (s.critico
        ? { punto: "🔴", txt: "Falta (crítico)", cls: "sis-ko" }
        : { punto: "🟡", txt: "Opcional, sin configurar", cls: "sis-opt" });
    return `<tr class="${estado.cls}">
      <td>${estado.punto} ${escapeHtml(s.nombre)}</td>
      <td>${estado.txt}</td>
      <td class="admin-reporte-meta">${escapeHtml(s.detalle)}</td>
    </tr>`;
  }).join("");
  const b = banner || { activo: false, texto: "", tipo: "info" };
  // Panel de diagnóstico: semáforo global + cosas a vigilar.
  const todoOk = diag.todo_ok !== false;
  const avisos = [];
  if (diag.banner_activo) avisos.push(`<span class="sis-aviso sis-aviso-info">📢 Hay un aviso global ACTIVO en la web ahora mismo</span>`);
  if ((diag.opcionales_ko || []).length) avisos.push(`<span class="sis-aviso sis-aviso-soft">🟡 Servicios opcionales sin configurar: ${diag.opcionales_ko.map(escapeHtml).join(", ")}</span>`);
  panel.innerHTML = `
    <div class="age-card admin-bloque sis-diagnostico ${todoOk ? "sis-diag-ok" : "sis-diag-ko"}">
      <div class="sis-diag-cab"><span class="sis-diag-ico">${todoOk ? "✅" : "⚠️"}</span>
        <div><h3>${todoOk ? "Todo en orden" : "Atención necesaria"}</h3>
        <p class="admin-reporte-meta">${todoOk ? "Todos los servicios críticos están configurados y la web funciona." : "Servicios críticos sin configurar: " + (diag.criticos_ko || []).map(escapeHtml).join(", ")}</p></div>
      </div>
      ${avisos.length ? `<div class="sis-avisos">${avisos.join("")}</div>` : ""}
    </div>
    <div class="age-card admin-bloque">
      <h3>Estado de los servicios</h3>
      <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Servicio</th><th>Estado</th><th>Para qué</th></tr></thead><tbody>${servicios}</tbody></table></div>
    </div>
    <div class="age-card admin-bloque">
      <h3>Aviso global del sitio</h3>
      <p class="admin-reporte-meta">Se muestra a todos los usuarios en la parte superior de la web.</p>
      <label class="admin-toggle" style="margin:8px 0;"><input type="checkbox" id="ban-activo" ${b.activo ? "checked" : ""}> <span>Mostrar el aviso</span></label>
      <label>Texto</label>
      <input class="age-input" id="ban-texto" maxlength="300" value="${escapeHtml(b.texto)}" placeholder="Ej. Mantenimiento programado el viernes de 22h a 23h.">
      <label>Tipo</label>
      <select class="age-input" id="ban-tipo">
        <option value="info" ${b.tipo === "info" ? "selected" : ""}>Info (azul)</option>
        <option value="aviso" ${b.tipo === "aviso" ? "selected" : ""}>Aviso (naranja)</option>
        <option value="urgente" ${b.tipo === "urgente" ? "selected" : ""}>Urgente (rojo)</option>
      </select>
      <button class="age-btn age-btn-primary" id="ban-guardar" style="margin-top:12px;">Guardar aviso</button>
    </div>`;
  panel.querySelector("#ban-guardar").addEventListener("click", async () => {
    const r = await api("PUT", "/admin/api/banner", {
      activo: panel.querySelector("#ban-activo").checked,
      texto: panel.querySelector("#ban-texto").value,
      tipo: panel.querySelector("#ban-tipo").value,
    });
    if (r) toast(r.activo ? "Aviso activado." : "Aviso guardado (oculto).");
  });
}

// ===== init =====
document.addEventListener("DOMContentLoaded", async () => {
  _permisos = await obtenerPermisos();
  if (!_permisos.admin && _permisos.permisos.length === 0) {
    mostrarNoAutorizado();
    return;
  }
  document.getElementById("admin-contenido").style.display = "block";
  // Ocultar las pestañas para las que no se tiene permiso y quedarnos con la
  // primera visible.
  let primera = null;
  document.querySelectorAll(".admin-tab").forEach((b) => {
    if (puedeVer(b.dataset.tab)) {
      b.addEventListener("click", () => activarPestana(b.dataset.tab));
      if (!primera) primera = b.dataset.tab;
    } else {
      b.hidden = true;
    }
  });
  document.getElementById("admin-oposicion").addEventListener("change", () => { temaSeleccionado = null; RENDERS[pestanaActual](); });
  activarPestana(primera || "dashboard");
});
