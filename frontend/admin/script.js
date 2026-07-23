// Panel de administración. El backend (requiere_admin) es la barrera real;
// aquí solo se comprueba esAdmin para no montar la UI a quien no lo es.
import { esAdmin, obtenerPermisos, obtenerAuthHeaders } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { icono } from "/assets/icons.js";

// Inyecta los iconos SVG en los elementos estáticos del HTML marcados con
// data-icon (sidebar, botones de cerrar) -- se hace aquí en vez de a mano
// en el HTML para tener una sola fuente de verdad (icons.js).
function inyectarIconosEstaticos() {
  document.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 18));
  });
}

// Qué permiso necesita cada pestaña. Las de 'admin' solo las ve el super-admin.
const PERMISO_POR_PESTANA = {
  dashboard: "cualquiera", temario: "temario", preguntas: "temario", analitica: "temario",
  usuarios: "usuarios", reportes: "reportes", boe: "temario", bajas: "reportes", limites: "admin", auditoria: "admin", sistema: "admin",
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
  const nombreIcono = tipo === "error" ? "alerta" : tipo === "ok" ? "check" : "informacion";
  el.innerHTML = `<span class="admin-toast-icono">${icono(nombreIcono, 16)}</span><span>${escapeHtml(mensaje)}</span>`;
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
let elementoAntesDelModal = null;

function focablesDelModal() {
  return Array.from(modal.querySelectorAll('input, select, textarea, button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'));
}

function atraparTabEnModal(e) {
  if (e.key !== "Tab" || modal.hidden) return;
  const focables = focablesDelModal();
  if (!focables.length) return;
  const primero = focables[0];
  const ultimo = focables[focables.length - 1];
  if (e.shiftKey && document.activeElement === primero) {
    e.preventDefault();
    ultimo.focus();
  } else if (!e.shiftKey && document.activeElement === ultimo) {
    e.preventDefault();
    primero.focus();
  }
}

function abrirModal(html) {
  elementoAntesDelModal = document.activeElement;
  modalContenido.innerHTML = html;
  modal.hidden = false;
  // Mueve el foco dentro del modal al abrirlo (el botón de cerrar, siempre
  // presente) -- si no, quien navega con teclado seguiría con el foco en
  // un elemento que ha quedado detrás, invisible tras el modal.
  document.getElementById("admin-modal-cerrar")?.focus();
}
function cerrarModal() {
  modal.hidden = true;
  modalContenido.innerHTML = "";
  elementoAntesDelModal?.focus();
  elementoAntesDelModal = null;
}
document.getElementById("admin-modal-cerrar").addEventListener("click", cerrarModal);
modal.addEventListener("click", (e) => { if (e.target === modal) cerrarModal(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !modal.hidden) cerrarModal();
  atraparTabEnModal(e);
});

// ===== pestañas =====
const RENDERS = {
  dashboard: renderDashboard,
  temario: renderTemario,
  preguntas: renderPreguntas,
  analitica: renderAnalitica,
  usuarios: renderUsuarios,
  reportes: renderReportes,
  boe: renderBoe,
  bajas: renderBajas,
  limites: renderLimites,
  auditoria: renderAuditoria,
  sistema: renderSistema,
};
const TITULO_POR_PESTANA = {
  dashboard: "Dashboard", temario: "Temario", preguntas: "Preguntas", analitica: "Analítica",
  usuarios: "Usuarios", reportes: "Reportes", boe: "Vigilancia BOE", bajas: "Bajas", limites: "Límites", auditoria: "Auditoría", sistema: "Sistema",
};
let pestanaActual = "dashboard";

function activarPestana(nombre) {
  if (!puedeVer(nombre)) return;
  pestanaActual = nombre;
  document.querySelectorAll(".admin-tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === nombre));
  document.querySelectorAll(".admin-panel").forEach((p) => { p.hidden = p.id !== `panel-${nombre}`; });
  const titulo = document.getElementById("admin-titulo");
  if (titulo) titulo.textContent = TITULO_POR_PESTANA[nombre] || nombre;
  cerrarSidebar();
  RENDERS[nombre]();
}

// ===== sidebar móvil (cajón deslizante) =====
const sidebar = document.getElementById("admin-sidebar");
const sidebarOverlay = document.getElementById("admin-sidebar-overlay");
const menuBtn = document.getElementById("admin-menu-btn");
const sidebarCerrarBtn = document.getElementById("admin-sidebar-cerrar");

function abrirSidebar() {
  sidebar.classList.add("abierta");
  sidebarOverlay.classList.add("abierta");
  sidebarOverlay.hidden = false;
  menuBtn?.setAttribute("aria-expanded", "true");
}
function cerrarSidebar() {
  sidebar.classList.remove("abierta");
  sidebarOverlay.classList.remove("abierta");
  sidebarOverlay.hidden = true;
  menuBtn?.setAttribute("aria-expanded", "false");
}
menuBtn?.addEventListener("click", abrirSidebar);
sidebarCerrarBtn?.addEventListener("click", cerrarSidebar);
sidebarOverlay?.addEventListener("click", cerrarSidebar);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") cerrarSidebar(); });

function actualizarBadgeReportes(n) {
  const badge = document.getElementById("badge-reportes");
  if (!badge) return;
  badge.textContent = n;
  badge.hidden = !n;
}

function actualizarBadgeBoe(n) {
  const badge = document.getElementById("badge-boe");
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
  actualizarBadgeBoe((d.cambios_temario_pendientes || 0) + (d.avisos_oficiales_pendientes || 0));

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
    : `<span class="admin-vacio">Todos los temas tienen contenido. ${icono("check", 14)}</span>`;

  panel.innerHTML = `
    <div class="admin-cards">
      <div class="age-card admin-stat"><span class="admin-stat-ico" aria-hidden="true">${icono("usuarios", 22)}</span><span class="admin-stat-num">${d.usuarios_totales}</span><span class="admin-stat-lbl">Usuarios</span><span class="admin-stat-sub">+${d.usuarios_nuevos_7_dias || 0} en 7 días</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-ico" aria-hidden="true">${icono("rayo", 22)}</span><span class="admin-stat-num">${d.usuarios_activos_7_dias || 0}</span><span class="admin-stat-lbl">Activos (7 días)</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-ico" aria-hidden="true">${icono("matraz", 22)}</span><span class="admin-stat-num">${d.tests_ultimos_7_dias}</span><span class="admin-stat-lbl">Tests (7 días)</span><span class="admin-stat-sub">${d.tests_ultimos_30_dias} en 30 días</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-ico" aria-hidden="true">${icono("libros", 22)}</span><span class="admin-stat-num">${d.tests_total || 0}</span><span class="admin-stat-lbl">Tests totales</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-ico" aria-hidden="true">${icono("euro", 22)}</span><span class="admin-stat-num">${(d.mrr || 0).toFixed(2)}€</span><span class="admin-stat-lbl">Ingresos/mes (MRR)</span><span class="admin-stat-sub">${d.suscripciones_pago || 0} suscripciones de pago</span></div>
      <div class="age-card admin-stat"><span class="admin-stat-ico" aria-hidden="true">${icono("robot", 22)}</span><span class="admin-stat-num">${(d.coste_ia_mes || 0).toFixed(2)}€</span><span class="admin-stat-lbl">Coste IA (este mes)</span></div>
      <div class="age-card admin-stat admin-stat-clic ${alertaReportes ? "admin-stat-alerta" : ""}" id="stat-reportes"><span class="admin-stat-ico" aria-hidden="true">${icono("bandera", 22)}</span><span class="admin-stat-num">${d.reportes_pendientes}</span><span class="admin-stat-lbl">Reportes pendientes</span></div>
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
          <button class="admin-icono" data-renombrar-bloque="${escapeHtml(b.id)}" title="Renombrar bloque">${icono("lapiz", 14)}</button>
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
          <button class="admin-icono" data-renombrar-tema="${escapeHtml(b.id)}|${escapeHtml(t.id)}|${escapeHtml(t.titulo)}" title="Renombrar tema">${icono("lapiz", 14)}</button>
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
      <button class="age-btn age-btn-outline admin-filtros-btn" id="p-csv">${icono("descargar", 15)} CSV</button>
      <button class="age-btn age-btn-outline admin-filtros-btn" id="p-importar">${icono("subir", 15)} Importar</button>
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
  const [d, banco] = await Promise.all([
    apiGet(`/admin/api/analitica-contenido?oposicion=${oposicionActual()}`),
    apiGet(`/admin/api/banco-preguntas?oposicion=${oposicionActual()}`),
  ]);
  if (!d) return;
  const temas = d.temas || [];
  const hayBanco = banco && (banco.total_oposicion || Object.values(banco.totales_por_oposicion || {}).some((n) => n > 0));
  if (!temas.length && !(d.sin_actividad || []).length && !hayBanco) {
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

  const ETIQUETA_OPOSICION = { AGE: "AGE", GACE: "GACE", AUXILIAR: "Auxiliar" };
  const bancoHtml = !banco ? "" : `
    <div class="age-card admin-bloque">
      <h3>Banco de preguntas IA (Test Personalizado)</h3>
      <p class="admin-reporte-meta">Preguntas ya generadas y verificadas que se van acumulando por oposición. De momento solo se almacenan; sirve para ver cuándo hay volumen suficiente para reutilizarlas en vez de generar siempre desde cero.</p>
      <div class="admin-chips">
        ${Object.entries(banco.totales_por_oposicion || {}).map(([oid, total]) => `<span class="admin-chip"><strong>${escapeHtml(ETIQUETA_OPOSICION[oid] || oid)}:</strong> ${total}</span>`).join("")}
      </div>
      <h4 style="margin:18px 0 8px;">Por bloque (${escapeHtml(banco.oposicion)})</h4>
      ${(banco.por_bloque || []).length ? `
        <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Bloque</th><th class="admin-num">Preguntas</th></tr></thead>
          <tbody>${banco.por_bloque.map((b) => `<tr><td>${escapeHtml(b.titulo)}</td><td class="admin-num">${b.total}</td></tr>`).join("")}</tbody></table></div>
      ` : '<p class="admin-vacio">Todavía no hay preguntas en el banco de esta oposición.</p>'}
      ${(banco.por_tema || []).length ? `
        <h4 style="margin:18px 0 8px;">Por tema</h4>
        <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Bloque</th><th>Tema</th><th class="admin-num">Preguntas</th></tr></thead>
          <tbody>${banco.por_tema.map((t) => `<tr><td>${escapeHtml(t.bloque_titulo)}</td><td>${escapeHtml(t.titulo)}</td><td class="admin-num">${t.total}</td></tr>`).join("")}</tbody></table></div>
      ` : ""}
    </div>`;

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
      <div class="admin-chips">${(d.sin_actividad || []).map((t) => `<span class="admin-chip">${escapeHtml(t.titulo || t.tema_id)}</span>`).join("") || `<span class="admin-vacio">Todos los temas tienen actividad. ${icono("check", 14)}</span>`}</div>
    </div>

    ${bancoHtml}`;
}

// ===== Bajas (motivos de cancelación) =====
const ETIQUETA_MOTIVO_BAJA = {
  precio: "Es demasiado caro",
  aprobado: "Ya ha aprobado o no se presenta",
  no_lo_uso: "No lo usa lo suficiente",
  faltan_funciones: "Le faltan funciones que necesita",
  otro: "Otro motivo",
};

async function renderBajas() {
  const panel = document.getElementById("panel-bajas");
  panel.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/bajas`);
  if (!d) return;

  if (!d.total) {
    panel.innerHTML = `<div class="age-card"><p class="admin-vacio">Todavía no se ha dado de baja nadie. ${icono("check", 14)}</p></div>`;
    return;
  }

  const filaMotivo = (motivo, veces) => {
    const pct = d.total ? Math.round((veces / d.total) * 100) : 0;
    return `<div class="admin-analitica-fila">
        <div class="admin-analitica-tema">${escapeHtml(ETIQUETA_MOTIVO_BAJA[motivo] || motivo)}</div>
        <div class="admin-barra"><span class="admin-barra-relleno" style="width:${pct}%;background:var(--age-danger,#dc3545)"></span></div>
        <div class="admin-analitica-pct">${pct}% <span class="admin-reporte-meta">(${veces})</span></div>
      </div>`;
  };
  const motivosOrdenados = Object.entries(d.por_motivo || {}).sort((a, b) => b[1] - a[1]);

  const filaComentario = (c) => `
    <div class="admin-reporte">
      <div class="admin-reporte-cab">
        <span class="admin-reporte-estado admin-estado-pendiente">${escapeHtml(ETIQUETA_MOTIVO_BAJA[c.motivo] || c.motivo)}</span>
        <span class="admin-reporte-meta">${escapeHtml(c.oposicion || "-")} · ${escapeHtml(fechaCorta(c.fecha))}</span>
      </div>
      <p class="admin-reporte-motivo">${escapeHtml(c.comentario)}</p>
    </div>`;

  panel.innerHTML = `
    <div class="age-card admin-bloque">
      <h3>Por qué cancela la gente (${d.total} baja${d.total === 1 ? "" : "s"} en total)</h3>
      ${motivosOrdenados.map(([motivo, veces]) => filaMotivo(motivo, veces)).join("")}
    </div>

    <div class="age-card admin-bloque">
      <h3>Bajas por oposición</h3>
      <div class="admin-chips">${Object.entries(d.por_oposicion || {}).sort((a, b) => b[1] - a[1])
        .map(([op, veces]) => `<span class="admin-chip">${escapeHtml(op)}: ${veces}</span>`).join("") || '<span class="admin-vacio">Sin datos.</span>'}</div>
    </div>

    <div class="age-card admin-bloque">
      <h3>Comentarios recientes (${(d.comentarios_recientes || []).length})</h3>
      <p class="admin-reporte-meta">Solo se muestran las bajas en las que la persona escribió algo, sin vincularlas a su cuenta.</p>
      ${(d.comentarios_recientes || []).length
        ? d.comentarios_recientes.map(filaComentario).join("")
        : '<p class="admin-vacio">Nadie ha dejado un comentario todavía.</p>'}
    </div>`;
}

// ===== Usuarios =====
let paginaUsuarios = 1;
let ordenUsuarios = "";  // "" = por última actividad; "uso" = por mayor % de cupo
async function renderUsuarios() {
  const panel = document.getElementById("panel-usuarios");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <input id="u-busqueda" class="age-input" placeholder="Buscar por email…">
      <select id="u-plan" class="age-input"><option value="">Todos los planes</option><option value="gratis">Gratis</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
      <button class="age-btn age-btn-primary admin-filtros-btn" id="u-aplicar">Buscar</button>
      <button class="age-btn age-btn-outline admin-filtros-btn" id="u-csv">${icono("descargar", 15)} CSV</button>
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
  if (ordenUsuarios === "uso") params.set("orden", "uso");
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/usuarios?${params.toString()}`);
  if (!d) return;
  const celdaUso = (u) => {
    const pct = u.uso_pct || 0;
    const cls = pct >= 100 ? "u-uso-alto" : (pct >= 80 ? "u-uso-medio" : (pct > 0 ? "u-uso-ok" : "u-uso-cero"));
    const titulo = u.uso_tool ? `${u.uso_tool}: ${pct}% de su cupo` : "Sin uso este periodo";
    return `<span class="u-uso ${cls}" title="${escapeHtml(titulo)}"><span class="u-uso-punto"></span>${pct}%</span>`;
  };
  const filas = (d.usuarios || []).map((u) => `
    <tr class="admin-fila-click" data-uid="${escapeHtml(u.uid)}">
      <td>${escapeHtml(u.email || "(sin email)")}</td><td><span class="admin-chip">${escapeHtml(u.plan)}</span>${u.en_prueba ? ' <span class="admin-chip admin-chip-prueba">en prueba</span>' : ""}</td>
      <td>${(u.oposiciones_activas || []).map(escapeHtml).join(", ") || "-"}</td>
      <td>${celdaUso(u)}</td>
      <td class="admin-num">${fechaCorta(u.ultima_actividad)}</td></tr>`).join("")
    || `<tr><td colspan="5" class="admin-vacio">Sin usuarios.</td></tr>`;
  const totalPaginas = Math.max(1, Math.ceil((d.total || 0) / (d.por_pagina || 20)));
  const flechaUso = ordenUsuarios === "uso" ? " ▼" : "";
  cont.innerHTML = `
    <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Email</th><th>Plan</th><th>Oposiciones</th><th><button class="admin-orden-btn" id="u-orden-uso" title="Ordenar por mayor uso">Uso${flechaUso}</button></th><th class="admin-num">Últ. act.</th></tr></thead><tbody>${filas}</tbody></table></div>
    <div class="admin-paginacion">
      <button class="age-btn age-btn-outline admin-mini" id="u-prev" ${paginaUsuarios <= 1 ? "disabled" : ""}>◀ Anterior</button>
      <span>Página ${d.pagina} de ${totalPaginas} · ${d.total} usuarios</span>
      <button class="age-btn age-btn-outline admin-mini" id="u-next" ${paginaUsuarios >= totalPaginas ? "disabled" : ""}>Siguiente ▶</button>
    </div>`;
  cont.querySelectorAll(".admin-fila-click").forEach((tr) => tr.addEventListener("click", () => abrirUsuario(tr.dataset.uid)));
  cont.querySelector("#u-prev")?.addEventListener("click", () => { paginaUsuarios--; cargarUsuarios(); });
  cont.querySelector("#u-next")?.addEventListener("click", () => { paginaUsuarios++; cargarUsuarios(); });
  cont.querySelector("#u-orden-uso")?.addEventListener("click", () => {
    ordenUsuarios = ordenUsuarios === "uso" ? "" : "uso";
    paginaUsuarios = 1;
    cargarUsuarios();
  });
}

// ---- Ficha de cliente: piezas visuales reutilizables ----
function fichaPlanBadge(plan, enPrueba) {
  if (enPrueba) return `<span class="ficha-badge ficha-badge-prueba">⏳ En prueba (Premium)</span>`;
  const p = (plan || "gratis").toLowerCase();
  const map = { premium: ["Premium", "ficha-badge-premium"], basico: ["Básico", "ficha-badge-basico"], gratis: ["Gratis", "ficha-badge-gratis"] };
  const [txt, cls] = map[p] || map.gratis;
  return `<span class="ficha-badge ${cls}">${txt}</span>`;
}
function fichaEuros(n) { return (n || 0).toLocaleString("es", { minimumFractionDigits: 4, maximumFractionDigits: 4 }) + " €"; }
const _MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
function mesLegible(m) { const p = (m || "").split("-"); return (_MESES_CORTOS[(+p[1] || 1) - 1] || "") + " " + (p[0] || ""); }
function fichaMini(iconoHtml, num, label) {
  return `<div class="ficha-mini"><span class="ficha-mini-ico">${iconoHtml}</span><span class="ficha-mini-num">${(num || 0).toLocaleString("es")}</span><span class="ficha-mini-lbl">${label}</span></div>`;
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

function fichaUsoFila(f) {
  const per = f.periodo === "dia" ? "hoy" : "este mes";
  if (!f.limite) {
    return `<div class="ficha-uso-fila ficha-uso-off"><span class="ficha-uso-nombre">${escapeHtml(f.nombre)}</span><span class="ficha-uso-val">No incluido</span></div>`;
  }
  const pct = f.porcentaje == null ? 0 : Math.min(100, f.porcentaje);
  const cls = f.porcentaje >= 100 ? "ficha-uso-alto" : (f.porcentaje >= 80 ? "ficha-uso-medio" : "");
  return `<div class="ficha-uso-fila ${cls}">
    <div class="ficha-uso-cab"><span class="ficha-uso-nombre">${escapeHtml(f.nombre)}</span>
      <span class="ficha-uso-val">${(f.consumido || 0).toLocaleString("es")} / ${(f.limite || 0).toLocaleString("es")} ${escapeHtml(f.unidad)} <small>(${per})</small></span></div>
    <div class="ficha-uso-barra"><span class="ficha-uso-relleno" style="width:${pct}%"></span></div>
  </div>`;
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
            ${fichaPlanBadge(u.plan, u.en_prueba)}
            <span class="ficha-badge ${u.email_verificado ? "ficha-badge-ok" : "ficha-badge-warn"}">${u.email_verificado ? icono("check", 13) + " Verificado" : "Sin verificar"}</span>
            ${u.es_admin ? `<span class="ficha-badge ficha-badge-admin">${icono("corona", 13)} Admin total</span>` : ""}
            ${(!u.es_admin && (u.permisos || []).length) ? `<span class="ficha-badge ficha-badge-rol">${icono("escudo", 13)} ${(u.permisos || []).length} rol(es)</span>` : ""}
            ${u.bloqueado ? `<span class="ficha-badge ficha-badge-bloqueo">${icono("prohibido", 13)} Bloqueado</span>` : ""}
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
          <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("robot", 17)}</span><h3>Gasto en IA</h3></div>
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
            <summary>${icono("buscar", 14)} Buscar por rango de meses</summary>
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
          <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("libros", 17)}</span><h3>Contenido creado</h3></div>
          <div class="ficha-minis">
            ${fichaMini(icono("documento", 18), c.documentos, "Documentos")}
            ${fichaMini(icono("lapiz", 18), c.resumenes, "Resúmenes")}
            ${fichaMini(icono("esquema", 18), c.esquemas, "Esquemas")}
            ${fichaMini(icono("tarjeta", 18), c.tarjetas, "Tarjetas")}
            ${fichaMini(icono("matraz", 18), c.tests_pdf, "Tests de PDF")}
            ${fichaMini(icono("estrella", 18), c.favoritas, "Favoritas")}
            ${fichaMini(icono("repetir", 18), c.falladas, "A repasar")}
          </div>
        </div>
      </div>

      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("usuario", 17)}</span><h3>Datos de la cuenta</h3></div>
        <dl class="ficha-datos">
          <div><dt>Plan</dt><dd>${escapeHtml(u.plan)}${oposActivas.length ? " · " + oposActivas.map(escapeHtml).join(", ") : ""}</dd></div>
          <div><dt>Alta</dt><dd>${escapeHtml(fechaCorta(u.fecha_creacion))}</dd></div>
          <div><dt>Última actividad</dt><dd>${escapeHtml(fechaCorta(u.ultima_actividad))}</dd></div>
          <div><dt>Rendimiento</dt><dd>${(r.aciertos || 0)} aciertos · ${(r.fallos || 0)} fallos · ${(r.blancos || 0)} blancos</dd></div>
        </dl>
        ${override}
      </div>

      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("grafico", 17)}</span><h3>Uso de herramientas (periodo actual)</h3></div>
        ${((u.uso_herramientas || {}).filas || []).map(fichaUsoFila).join("")}
        <p class="ficha-uso-nota">Consumo frente al límite del plan de este usuario. El Test Personalizado se mide en preguntas. Si alguna barra se pone en rojo, está apurando su cupo.</p>
      </div>

      <details class="ficha-acordeon">
        <summary><span class="ficha-panel-ico">${icono("tarjeta", 16)}</span> Cambiar plan (soporte)</summary>
        <div class="ficha-acordeon-cuerpo">
          <div class="admin-form-fila">
            <select id="up-plan" class="age-input"><option value="gratis">Gratis</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
            <select id="up-oposicion" class="age-input"><option value="AGE">AGE</option><option value="GACE">GACE</option><option value="AUXILIAR">Auxiliar</option></select>
          </div>
          <input id="up-motivo" class="age-input" placeholder="Motivo (queda registrado)" style="margin-top:8px;">
          <button class="age-btn age-btn-primary" id="up-guardar" style="margin-top:10px;">Cambiar plan</button>
          <hr class="admin-sep">
          <h4 class="ficha-sub">${icono("arena", 15)} Prueba gratuita Premium</h4>
          <p class="ficha-prueba-estado">${u.en_prueba
            ? `En prueba hasta el <strong>${escapeHtml(fechaCorta(u.prueba_fin))}</strong>.`
            : (u.prueba_fin ? `Su prueba terminó el ${escapeHtml(fechaCorta(u.prueba_fin))}.` : "Nunca ha tenido una prueba.")}</p>
          <div class="admin-form-fila">
            <input id="up-prueba-dias" class="age-input" type="number" min="1" max="90" value="7" style="max-width:100px;">
            <button class="age-btn age-btn-outline admin-mini" id="up-prueba-otorgar">Otorgar/alargar prueba</button>
          </div>
        </div>
      </details>

      <details class="ficha-acordeon">
        <summary><span class="ficha-panel-ico">${icono("escudo", 16)}</span> Soporte y notas</summary>
        <div class="ficha-acordeon-cuerpo">
          <h4 class="ficha-sub">${icono("lapiz", 15)} Notas internas</h4>
          <div id="up-notas-lista" class="ficha-notas"></div>
          <textarea class="age-input" id="up-nota-nueva" rows="2" placeholder="Escribe una nota nueva…"></textarea>
          <button class="age-btn age-btn-primary admin-mini" id="up-nota-anadir" style="margin-top:6px;">+ Añadir nota</button>
          <h4 class="ficha-sub" style="margin-top:18px;">${icono("herramienta", 15)} Acciones de soporte</h4>
          <div class="ficha-soporte-acciones">
            <button class="age-btn admin-mini ficha-btn-soporte" id="up-racha">${icono("fuego", 15)} Resetear racha</button>
            <button class="age-btn admin-mini ficha-btn-soporte" id="up-limites">${icono("actualizar", 15)} Resetear límites de uso</button>
            <button class="age-btn admin-mini ficha-btn-soporte" id="up-reset-pass">${icono("llave", 15)} Enlace de contraseña</button>
            ${u.email_verificado ? "" : `<button class="age-btn admin-mini ficha-btn-soporte" id="up-verif">${icono("correo", 15)} Enlace de verificación</button>`}
          </div>
          <div id="up-enlace-caja"></div>
        </div>
      </details>

      <details class="ficha-acordeon ficha-acordeon-peligro">
        <summary><span class="ficha-panel-ico">${icono("candado", 16)}</span> Roles y administración</summary>
        <div class="ficha-acordeon-cuerpo">
          ${_permisos.admin ? `
            <p class="ficha-roles-intro">${u.es_admin ? "Este usuario es <strong>administrador total</strong> (acceso a todo)." : "Da acceso parcial marcando solo las secciones que necesite, sin hacerlo admin total."}</p>
            <div class="ficha-roles">
              ${(u.permisos_disponibles || ["temario", "reportes", "usuarios"]).map((p) => `
                <label class="ficha-rol ${u.es_admin ? "ficha-rol-off" : ""}">
                  <input type="checkbox" class="up-permiso" value="${escapeHtml(p)}" ${(u.permisos || []).includes(p) ? "checked" : ""} ${u.es_admin ? "disabled" : ""}>
                  <span class="ficha-rol-ico">${p === "temario" ? icono("libro", 17) : p === "reportes" ? icono("bandera", 17) : icono("usuarios", 17)}</span>
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
        <button class="ficha-nota-borrar" data-id="${escapeHtml(n.id)}" title="Eliminar nota">${icono("papelera", 14)}</button></div></div>`;
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
  document.getElementById("up-prueba-otorgar")?.addEventListener("click", async () => {
    const dias = parseInt(document.getElementById("up-prueba-dias").value, 10) || 7;
    const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/prueba`, { dias });
    if (r) { toast(r.mensaje || "Prueba actualizada."); cerrarModal(); cargarUsuarios(); }
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
    if (!confirm(`Vas a ELIMINAR por completo la cuenta de ${u.email}. Es IRREVERSIBLE (se borran todos sus datos y su suscripción). ¿Continuar?`)) return;
    if (!confirm("Confirma otra vez: esta acción no se puede deshacer.")) return;
    const r = await api("DELETE", `/admin/api/usuarios/${u.uid}`);
    if (r) { toast("Cuenta eliminada."); cerrarModal(); cargarUsuarios(); }
  });
}

// ===== Reportes =====
// La pestaña "Reportes" agrupa dos cosas distintas que comparten el mismo
// permiso ("reportes"): los reportes de una pregunta de test concreta
// (cruzados con el banco oficial) y los mensajes de soporte generales que
// un usuario manda desde Mi Cuenta (solo texto libre, sin pregunta
// asociada) -- de ahí el selector de vista para no mezclarlos en una
// misma lista con campos tan distintos.
let estadoReportes = "pendiente";
let vistaReportes = "preguntas";
async function renderReportes() {
  const panel = document.getElementById("panel-reportes");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <div style="display:flex;gap:8px;margin-bottom:12px;">
        <button type="button" class="age-btn ${vistaReportes === "preguntas" ? "age-btn-primary" : "age-btn-outline"} admin-mini" id="r-vista-preguntas">Preguntas reportadas</button>
        <button type="button" class="age-btn ${vistaReportes === "soporte" ? "age-btn-primary" : "age-btn-outline"} admin-mini" id="r-vista-soporte">Mensajes de soporte</button>
      </div>
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
  const cargarVistaActual = () => (vistaReportes === "soporte" ? cargarSoporte() : cargarReportes());
  sel.addEventListener("change", () => { estadoReportes = sel.value; cargarVistaActual(); });
  panel.querySelector("#r-vista-preguntas").addEventListener("click", () => { vistaReportes = "preguntas"; renderReportes(); });
  panel.querySelector("#r-vista-soporte").addEventListener("click", () => { vistaReportes = "soporte"; renderReportes(); });
  cargarVistaActual();
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
    cont.innerHTML = `<p class="admin-vacio">No hay reportes en este estado. ${icono("check", 14)}</p>`;
    return;
  }
  const clase = (e) => e === "revisado" ? "admin-estado-revisado" : e === "descartado" ? "admin-estado-descartado" : "admin-estado-pendiente";
  cont.innerHTML = d.reportes.map((r) => {
    const po = r.pregunta_oficial;
    const detalle = po
      ? `<div class="admin-reporte-oficial">
           ${["A", "B", "C", "D"].map((k) => `<div class="admin-op-linea ${po.respuesta_correcta === k ? "admin-op-correcta" : ""}">${k}) ${escapeHtml((po.opciones || {})[k] || "")}${po.respuesta_correcta === k ? " " + icono("check", 13) : ""}</div>`).join("")}
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

// ===== Vigilancia BOE: cambios de temario propuestos + avisos oficiales =====
// Nunca se aplican/publican solos -- el dueño los aprueba/descarta aquí
// (ver vigilancia_boe.py). Mismo patrón que Reportes: filtro por estado +
// dos vistas dentro de la misma pestaña.
let estadoBoe = "pendiente";
let vistaBoe = "cambios";

// Recordatorio manual del token de GitHub (GITHUB_TOKEN en Render) que usa
// publicacion_estatica_boe.py para publicar los avisos en las páginas
// públicas -- un token fine-grained caduca sí o sí (aquí se generó el
// 23/07/2026 con caducidad de 90 días), y GitHub no lo renueva solo: hay
// que generar uno nuevo a mano y pegarlo en Render antes de esa fecha, o
// la publicación en las páginas públicas empezará a fallar en silencio
// (Firestore + email siguen funcionando igualmente, ver docstring del
// módulo). Fecha fija a mano porque no hay forma de leer la caducidad real
// del token desde la propia web.
const _GITHUB_TOKEN_CADUCA = new Date("2026-10-21T00:00:00");

function _avisoTokenGithubHtml() {
  const msPorDia = 24 * 60 * 60 * 1000;
  const diasRestantes = Math.ceil((_GITHUB_TOKEN_CADUCA - new Date()) / msPorDia);
  const fechaLegible = _GITHUB_TOKEN_CADUCA.toLocaleDateString("es-ES", { day: "2-digit", month: "2-digit", year: "numeric" });
  const urgente = diasRestantes <= 14;
  const estilo = urgente ? "background:var(--age-danger-bg);border-left-color:var(--age-danger);" : "";
  const mensaje = diasRestantes < 0
    ? `⚠️ El token de GitHub caducó el <strong>${fechaLegible}</strong>: la publicación automática en las páginas públicas puede estar fallando. Genera uno nuevo (GitHub → Settings → Developer settings → Fine-grained tokens, permiso Contents: Read and write) y actualiza <code>GITHUB_TOKEN</code> en Render.`
    : `El token de GitHub (<code>GITHUB_TOKEN</code> en Render) caduca el <strong>${fechaLegible}</strong> (quedan ${diasRestantes} días). Antes de esa fecha, genera uno nuevo y actualízalo en Render para que la publicación en las páginas públicas no deje de funcionar.`;
  return `<div class="admin-aviso" style="${estilo}">${mensaje}</div>`;
}

function _avisoTemasFaltantesHtml(temasFaltantes) {
  if (!temasFaltantes || !temasFaltantes.length) return "";
  const lista = temasFaltantes.map((t) => `${escapeHtml(t.oposicion)} ${escapeHtml(t.bloque_id)}/${escapeHtml(t.tema_id)}`).join(", ");
  return `<div class="admin-aviso" style="background:var(--age-danger-bg);border-left-color:var(--age-danger);">
    ⚠️ ${temasFaltantes.length === 1 ? "Hay un tema" : `Hay ${temasFaltantes.length} temas`} referenciado${temasFaltantes.length === 1 ? "" : "s"} en <code>LEYES_VIGILADAS</code> que ya no existe${temasFaltantes.length === 1 ? "" : "n"} en el temario (${lista}) -- esa ley ha dejado de vigilarse en silencio para esos temas. Revisa <code>vigilancia_boe.py</code> y actualiza el bloque/tema.
  </div>`;
}

async function _cargarSaludVigilancia() {
  const cont = document.getElementById("boe-salud");
  if (!cont) return;
  const d = await apiGet("/admin/api/vigilancia-boe-salud");
  if (!d) return;
  cont.innerHTML = _avisoTemasFaltantesHtml(d.temas_faltantes);
}

// Tipos reconocidos por publicacion_estatica_boe.ETIQUETA_TIPO_AVISO -- si
// se amplía esa lista en Python, hay que reflejarlo aquí también.
const ETIQUETA_TIPO_AVISO_MANUAL = {
  convocatoria: "Convocatoria", lista_admitidos: "Lista de admitidos", tribunal: "Tribunal calificador",
  fecha_examen: "Fecha de examen", llamamiento_extraordinario: "Llamamiento extraordinario",
  aprobados: "Relación de aprobados", otro: "Aviso oficial",
};

// Campos compartidos entre "Añadir aviso manual" y "Editar aviso" -- misma
// forma en los dos sitios, con ids prefijados para poder repetirla varias
// veces en la misma página (una por tarjeta al editar).
function _formCamposAvisoHtml(prefix, v = {}) {
  const opcionesTipo = Object.entries(ETIQUETA_TIPO_AVISO_MANUAL)
    .map(([val, t]) => `<option value="${val}" ${v.tipo === val ? "selected" : ""}>${t}</option>`).join("");
  const op = (val) => (v.oposicion === val ? "selected" : "");
  return `
    <div style="display:grid;gap:10px;grid-template-columns:1fr 1fr;">
      <label style="font-size:13px;font-weight:600;">Oposición
        <select id="${prefix}-oposicion" class="age-input">
          <option value="AGE" ${op("AGE")}>AGE</option>
          <option value="GACE" ${op("GACE")}>GACE</option>
          <option value="AUXILIAR" ${op("AUXILIAR")}>Auxiliar</option>
        </select>
      </label>
      <label style="font-size:13px;font-weight:600;">Tipo
        <select id="${prefix}-tipo" class="age-input">${opcionesTipo}</select>
      </label>
    </div>
    <label style="font-size:13px;font-weight:600;display:block;margin-top:10px;">Texto del tipo, a mano (opcional)
      <input type="text" id="${prefix}-tipo-personalizado" class="age-input"
             placeholder="Si ninguna opción de Tipo encaja, escribe aquí y se mostrará esto en su lugar"
             value="${escapeHtml(v.tipo_personalizado || "")}" />
    </label>
    <label style="font-size:13px;font-weight:600;display:block;margin-top:10px;">Título
      <input type="text" id="${prefix}-titulo" class="age-input"
             placeholder="Ej: Llamamiento extraordinario del ejercicio único (AGE)" value="${escapeHtml(v.titulo || "")}" />
    </label>
    <label style="font-size:13px;font-weight:600;display:block;margin-top:10px;">Resumen (opcional)
      <textarea id="${prefix}-resumen" class="age-input" rows="2">${escapeHtml(v.resumen || "")}</textarea>
    </label>
    <div style="display:grid;gap:10px;grid-template-columns:1fr 1fr;margin-top:10px;">
      <label style="font-size:13px;font-weight:600;">Enlace a la resolución
        <input type="url" id="${prefix}-url" class="age-input" placeholder="https://..." value="${escapeHtml(v.url_boe || "")}" />
      </label>
      <label style="font-size:13px;font-weight:600;">Enlace a INAP (opcional)
        <input type="url" id="${prefix}-url-inap" class="age-input"
               placeholder="Si se deja vacío, se usa el genérico de procesos selectivos de INAP" value="${escapeHtml(v.url_inap || "")}" />
      </label>
    </div>
    <label style="font-size:13px;font-weight:600;display:block;margin-top:10px;max-width:220px;">Fecha (AAAAMMDD)
      <input type="text" id="${prefix}-fecha" class="age-input" placeholder="20260715" value="${escapeHtml(v.fecha_boe || "")}" />
    </label>`;
}

function _leerCamposAviso(prefix) {
  return {
    oposicion: document.getElementById(`${prefix}-oposicion`).value,
    tipo: document.getElementById(`${prefix}-tipo`).value,
    tipo_personalizado: document.getElementById(`${prefix}-tipo-personalizado`).value.trim(),
    titulo: document.getElementById(`${prefix}-titulo`).value.trim(),
    resumen: document.getElementById(`${prefix}-resumen`).value.trim(),
    url_boe: document.getElementById(`${prefix}-url`).value.trim(),
    url_inap: document.getElementById(`${prefix}-url-inap`).value.trim(),
    fecha_boe: document.getElementById(`${prefix}-fecha`).value.trim(),
  };
}

function _formAvisoManualHtml() {
  return `
    <div class="age-card" id="boe-form-manual" hidden style="margin-bottom:14px;">
      <p class="admin-seccion-titulo" style="margin-top:0;">Añadir aviso manual</p>
      <p class="admin-reporte-meta" style="margin-bottom:14px;">Para lo que la vigilancia automática del BOE no puede detectar sola -- p. ej. una resolución publicada solo en el portal del INAP, no en el BOE. Se crea "pendiente", igual que los detectados solos: hay que aprobarlo para que se publique.</p>
      ${_formCamposAvisoHtml("bfm")}
      <div style="display:flex;gap:8px;margin-top:14px;">
        <button type="button" class="age-btn age-btn-primary admin-mini" id="bfm-crear">Crear aviso pendiente</button>
        <button type="button" class="age-btn age-btn-outline admin-mini" id="bfm-cancelar">Cancelar</button>
      </div>
    </div>`;
}

async function _crearAvisoManual() {
  const datos = _leerCamposAviso("bfm");
  if (!datos.titulo) { toast("Falta el título."); return; }
  const r = await api("POST", "/admin/api/avisos-oficiales", datos);
  if (r) {
    toast("Aviso creado como pendiente.");
    document.getElementById("boe-form-manual").hidden = true;
    estadoBoe = "pendiente";
    cargarAvisosOficiales();
  }
}

async function _guardarEdicionAviso(id) {
  const datos = _leerCamposAviso(`edit-${id}`);
  if (!datos.titulo) { toast("Falta el título."); return; }
  const r = await api("PUT", `/admin/api/avisos-oficiales/${id}`, datos);
  if (r) { toast("Aviso corregido."); cargarAvisosOficiales(); }
}

async function renderBoe() {
  const panel = document.getElementById("panel-boe");
  panel.innerHTML = `
    ${_avisoTokenGithubHtml()}
    <div id="boe-salud"></div>
    <div class="age-card admin-filtros">
      <div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;">
        <button type="button" class="age-btn ${vistaBoe === "cambios" ? "age-btn-primary" : "age-btn-outline"} admin-mini" id="boe-vista-cambios">Cambios de temario</button>
        <button type="button" class="age-btn ${vistaBoe === "avisos" ? "age-btn-primary" : "age-btn-outline"} admin-mini" id="boe-vista-avisos">Avisos oficiales</button>
        ${vistaBoe === "avisos" ? `<button type="button" class="age-btn age-btn-outline admin-mini" id="boe-mostrar-form-manual" style="margin-left:auto;">+ Añadir aviso manual</button>` : ""}
      </div>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;">Estado
        <select id="boe-estado" class="age-input" style="max-width:180px;">
          <option value="pendiente">Pendientes</option>
          <option value="${vistaBoe === "cambios" ? "aprobado" : "publicado"}">${vistaBoe === "cambios" ? "Aprobados" : "Publicados"}</option>
          <option value="descartado">Descartados</option>
          <option value="todos">Todos</option>
        </select>
      </label>
    </div>
    ${vistaBoe === "avisos" ? _formAvisoManualHtml() : ""}
    <div class="age-card"><div id="boe-lista"><p class="admin-cargando">Cargando…</p></div></div>`;
  if (vistaBoe === "avisos") {
    panel.querySelector("#boe-mostrar-form-manual").addEventListener("click", () => {
      panel.querySelector("#boe-form-manual").hidden = false;
    });
    panel.querySelector("#bfm-cancelar").addEventListener("click", () => {
      panel.querySelector("#boe-form-manual").hidden = true;
    });
    panel.querySelector("#bfm-crear").addEventListener("click", _crearAvisoManual);
  }
  const sel = panel.querySelector("#boe-estado");
  sel.value = estadoBoe;
  const cargarVistaActual = () => (vistaBoe === "avisos" ? cargarAvisosOficiales() : cargarCambiosTemario());
  sel.addEventListener("change", () => { estadoBoe = sel.value; cargarVistaActual(); });
  panel.querySelector("#boe-vista-cambios").addEventListener("click", () => { vistaBoe = "cambios"; estadoBoe = "pendiente"; renderBoe(); });
  panel.querySelector("#boe-vista-avisos").addEventListener("click", () => { vistaBoe = "avisos"; estadoBoe = "pendiente"; renderBoe(); });
  cargarVistaActual();
  _cargarSaludVigilancia();
}

function _diffHtml(texto_eliminar, texto_anadir) {
  return `
    <div class="admin-boe-diff">
      <p class="admin-boe-diff-quita">${escapeHtml(texto_eliminar)}</p>
      <p class="admin-boe-diff-pon">${escapeHtml(texto_anadir)}</p>
    </div>`;
}

async function cargarCambiosTemario() {
  const cont = document.getElementById("boe-lista");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/cambios-temario?estado=${estadoBoe}`);
  if (!d) return;
  const pendientes = (d.cambios || []).filter((c) => c.estado === "pendiente").length;
  if (estadoBoe === "pendiente") actualizarBadgeBoe(pendientes + _avisosPendientesCache);
  if (!(d.cambios || []).length) {
    cont.innerHTML = `<p class="admin-vacio">No hay cambios de temario en este estado. ${icono("check", 14)}</p>`;
    return;
  }
  const clase = (e) => e === "aprobado" ? "admin-estado-revisado" : e === "descartado" ? "admin-estado-descartado" : "admin-estado-pendiente";
  cont.innerHTML = d.cambios.map((c) => `
    <div class="admin-reporte">
      <div class="admin-reporte-cab">
        <span class="admin-reporte-estado ${clase(c.estado)}">${escapeHtml(c.estado)}</span>
        <span class="admin-reporte-meta">${escapeHtml(c.oposicion || "-")} · ${escapeHtml(c.bloque_id || "")}/${escapeHtml(c.tema_id || "")} · ${escapeHtml(fechaCorta(c.fecha_deteccion))}</span>
      </div>
      <p class="admin-reporte-preg">${escapeHtml(c.resumen)}</p>
      <p class="admin-reporte-meta"><strong>Ley:</strong> ${escapeHtml(c.ley_nombre || "-")}</p>
      ${_diffHtml(c.texto_eliminar, c.texto_anadir)}
      <div class="admin-reporte-acciones">
        ${c.estado !== "aprobado" ? `<button class="age-btn age-btn-primary admin-mini" data-aprobar="${escapeHtml(c.id)}">Aprobar y publicar</button>` : ""}
        ${c.estado !== "descartado" ? `<button class="age-btn age-btn-outline admin-mini" data-descartar-cambio="${escapeHtml(c.id)}">Descartar</button>` : ""}
      </div>
    </div>`).join("");
  cont.querySelectorAll("[data-aprobar]").forEach((b) => b.addEventListener("click", () => cambiarEstadoCambioTemario(b.dataset.aprobar, "aprobado")));
  cont.querySelectorAll("[data-descartar-cambio]").forEach((b) => b.addEventListener("click", () => cambiarEstadoCambioTemario(b.dataset.descartarCambio, "descartado")));
}

async function cambiarEstadoCambioTemario(id, estado) {
  const r = await api("PATCH", `/admin/api/cambios-temario/${id}`, { estado });
  if (r) { toast(estado === "aprobado" ? "Cambio aplicado al temario." : "Propuesta descartada."); cargarCambiosTemario(); }
}

let _avisosPendientesCache = 0;
async function cargarAvisosOficiales() {
  const cont = document.getElementById("boe-lista");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/avisos-oficiales?estado=${estadoBoe}`);
  if (!d) return;
  const pendientes = (d.avisos || []).filter((a) => a.estado === "pendiente").length;
  if (estadoBoe === "pendiente") { _avisosPendientesCache = pendientes; actualizarBadgeBoe(pendientes); }
  if (!(d.avisos || []).length) {
    cont.innerHTML = `<p class="admin-vacio">No hay avisos oficiales en este estado. ${icono("check", 14)}</p>`;
    return;
  }
  const clase = (e) => e === "publicado" ? "admin-estado-revisado" : e === "descartado" ? "admin-estado-descartado" : "admin-estado-pendiente";
  cont.innerHTML = d.avisos.map((a) => `
    <div class="admin-reporte">
      <div class="admin-reporte-cab">
        <span class="admin-reporte-estado ${clase(a.estado)}">${escapeHtml(a.estado)}</span>
        <span class="admin-reporte-meta">${escapeHtml(a.oposicion || "-")} · ${escapeHtml(a.tipo_personalizado || ETIQUETA_TIPO_AVISO_MANUAL[a.tipo] || a.tipo || "")} · ${escapeHtml(fechaCorta(a.fecha_deteccion))}</span>
      </div>
      <p class="admin-reporte-preg">${escapeHtml(a.titulo)}</p>
      ${a.resumen ? `<p class="admin-reporte-motivo">${escapeHtml(a.resumen)}</p>` : ""}
      ${a.url_boe ? `<p class="admin-reporte-meta"><a href="${escapeHtml(a.url_boe)}" target="_blank" rel="noopener">Ver la resolución ↗</a></p>` : ""}
      <div class="admin-reporte-acciones">
        ${a.estado !== "publicado" ? `<button class="age-btn age-btn-primary admin-mini" data-publicar="${escapeHtml(a.id)}">Publicar</button>` : ""}
        ${a.estado !== "descartado" ? `<button class="age-btn age-btn-outline admin-mini" data-descartar-aviso="${escapeHtml(a.id)}">Descartar</button>` : ""}
        <button class="age-btn age-btn-outline admin-mini" data-editar="${escapeHtml(a.id)}">Editar</button>
      </div>
      <div class="age-card" id="editar-${escapeHtml(a.id)}" hidden style="margin-top:10px;">
        <p class="admin-seccion-titulo" style="margin-top:0;">Corregir aviso</p>
        <p class="admin-reporte-meta" style="margin-bottom:14px;">
          ${a.estado === "publicado"
            ? "Este aviso ya está publicado: al guardar se corrige también la página pública, pero NO se vuelve a avisar por email (ya se envió)."
            : "Se corrige el contenido guardado; el estado (pendiente/publicado/descartado) no cambia aquí."}
        </p>
        ${_formCamposAvisoHtml(`edit-${escapeHtml(a.id)}`, a)}
        <div style="display:flex;gap:8px;margin-top:14px;">
          <button type="button" class="age-btn age-btn-primary admin-mini" data-guardar-edicion="${escapeHtml(a.id)}">Guardar cambios</button>
          <button type="button" class="age-btn age-btn-outline admin-mini" data-cancelar-edicion="${escapeHtml(a.id)}">Cancelar</button>
        </div>
      </div>
    </div>`).join("");
  cont.querySelectorAll("[data-publicar]").forEach((b) => b.addEventListener("click", () => cambiarEstadoAvisoOficial(b.dataset.publicar, "publicado")));
  cont.querySelectorAll("[data-descartar-aviso]").forEach((b) => b.addEventListener("click", () => cambiarEstadoAvisoOficial(b.dataset.descartarAviso, "descartado")));
  cont.querySelectorAll("[data-editar]").forEach((b) => b.addEventListener("click", () => {
    document.getElementById(`editar-${b.dataset.editar}`).hidden = false;
  }));
  cont.querySelectorAll("[data-cancelar-edicion]").forEach((b) => b.addEventListener("click", () => {
    document.getElementById(`editar-${b.dataset.cancelarEdicion}`).hidden = true;
  }));
  cont.querySelectorAll("[data-guardar-edicion]").forEach((b) => b.addEventListener("click", () => _guardarEdicionAviso(b.dataset.guardarEdicion)));
}

async function cambiarEstadoAvisoOficial(id, estado) {
  const r = await api("PATCH", `/admin/api/avisos-oficiales/${id}`, { estado });
  if (r) { toast(estado === "publicado" ? "Aviso publicado." : "Aviso descartado."); cargarAvisosOficiales(); }
}

async function cargarSoporte() {
  const cont = document.getElementById("reportes-lista");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/soporte?estado=${estadoReportes}`);
  if (!d) return;
  if (!(d.mensajes || []).length) {
    cont.innerHTML = `<p class="admin-vacio">No hay mensajes en este estado. ${icono("check", 14)}</p>`;
    return;
  }
  const clase = (e) => e === "revisado" ? "admin-estado-revisado" : e === "descartado" ? "admin-estado-descartado" : "admin-estado-pendiente";
  cont.innerHTML = d.mensajes.map((m) => `
    <div class="admin-reporte">
      <div class="admin-reporte-cab">
        <span class="admin-reporte-estado ${clase(m.estado)}">${escapeHtml(m.estado)}</span>
        <span class="admin-reporte-meta">${escapeHtml(m.email || "-")} · ${escapeHtml(fechaCorta(m.fecha))}</span>
      </div>
      <p class="admin-reporte-motivo">${escapeHtml(m.mensaje)}</p>
      <div class="admin-reporte-acciones">
        ${m.estado !== "revisado" ? `<button class="age-btn age-btn-outline admin-mini" data-soporte-revisado="${escapeHtml(m.id)}">Marcar revisado</button>` : ""}
        ${m.estado !== "descartado" ? `<button class="age-btn age-btn-outline admin-mini" data-soporte-descartar="${escapeHtml(m.id)}">Descartar</button>` : ""}
      </div>
    </div>`).join("");
  cont.querySelectorAll("[data-soporte-revisado]").forEach((b) => b.addEventListener("click", () => cambiarEstadoSoporte(b.dataset.soporteRevisado, "revisado")));
  cont.querySelectorAll("[data-soporte-descartar]").forEach((b) => b.addEventListener("click", () => cambiarEstadoSoporte(b.dataset.soporteDescartar, "descartado")));
}

async function cambiarEstadoSoporte(id, estado) {
  const r = await api("PATCH", `/admin/api/soporte/${id}`, { estado });
  if (r) { toast(estado === "revisado" ? "Mensaje marcado como revisado." : "Mensaje descartado."); cargarSoporte(); }
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
function _etiquetaAccionMapa() {
  const i14 = (n) => icono(n, 14);
  return {
    usuario_cambiar_plan: `${i14("tarjeta")} Cambio de plan`, usuario_resetear_racha: `${i14("fuego")} Reset de racha`,
    admin_dar: `${i14("corona")} Dar admin`, admin_quitar: `${i14("prohibido")} Quitar admin`,
    pregunta_crear: `${i14("mas")} Crear pregunta`, pregunta_editar: `${i14("lapiz")} Editar pregunta`,
    pregunta_desactivar: `${i14("papelera")} Desactivar pregunta`, pregunta_reactivar: `${i14("actualizar")} Reactivar pregunta`,
    temario_anadir_ficha: `${i14("mas")} Añadir ficha`, temario_editar_ficha: `${i14("lapiz")} Editar ficha`,
    temario_borrar_ficha: `${i14("papelera")} Borrar ficha`, publicado: `${i14("check")} Publicar`, borrador: `${i14("lapiz")} A borrador`,
    reporte_revisado: `${i14("check")} Reporte revisado`, reporte_descartado: `${i14("cruz")} Reporte descartado`,
    soporte_revisado: `${i14("check")} Mensaje de soporte revisado`, soporte_descartado: `${i14("cruz")} Mensaje de soporte descartado`,
  };
}
function etiquetaAccion(a) { return _etiquetaAccionMapa()[a] || a; }

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
      <td>${etiquetaAccion(e.accion)}</td>
      <td>${escapeHtml(e.objetivo || "-")}${e.detalle ? `<br><span class="admin-reporte-meta">${escapeHtml(e.detalle)}</span>` : ""}</td>
      <td>${escapeHtml(e.email_admin || "-")}</td>
    </tr>`;
  }).join("");
  cont.innerHTML = `
    <p class="admin-reporte-meta" style="margin-bottom:8px;">Últimas ${d.entradas.length} de ${d.total} acciones</p>
    <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Fecha (UTC)</th><th>Acción</th><th>Sobre</th><th>Admin</th></tr></thead><tbody>${filas}</tbody></table></div>`;
}

// ===== Sistema (salud + banner) =====
// ===== Límites de uso (editable) =====
const _NOMBRE_PLAN = { gratis: "Gratis", basico: "Básico", premium: "Premium" };
async function renderLimites() {
  const panel = document.getElementById("panel-limites");
  panel.innerHTML = `<p class="admin-cargando">Cargando límites…</p>`;
  const cfg = await apiGet("/admin/api/limites");
  if (!cfg) return;
  const planes = cfg.planes || ["gratis", "basico", "premium"];
  const celda = (tipo, plan) => {
    const c = (cfg.tools[tipo] || {})[plan] || { periodo: "mes", limite: 0 };
    return `<div class="lim-plan lim-plan-${plan}">
      <span class="lim-plan-nombre">${_NOMBRE_PLAN[plan] || plan}</span>
      <div class="lim-plan-campos">
        <input type="number" min="0" inputmode="numeric" class="age-input lim-num" data-tipo="${tipo}" data-plan="${plan}" value="${c.limite}" aria-label="Usos de ${_NOMBRE_PLAN[plan] || plan}">
        <select class="age-input lim-per" data-tipo="${tipo}" data-plan="${plan}" aria-label="Periodo de ${_NOMBRE_PLAN[plan] || plan}">
          <option value="dia" ${c.periodo === "dia" ? "selected" : ""}>al día</option>
          <option value="mes" ${c.periodo === "mes" ? "selected" : ""}>al mes</option>
        </select>
      </div>
    </div>`;
  };
  const tarjetaTool = (m) => `
    <div class="age-card lim-tool">
      <div class="lim-tool-cab"><h3>${escapeHtml(m.nombre)}${m.unidad === "preguntas" ? '<span class="lim-unidad">cupo en preguntas</span>' : ""}</h3><p>${escapeHtml(m.descripcion)}</p></div>
      <div class="lim-planes">${planes.map((p) => celda(m.id, p)).join("")}</div>
    </div>`;
  const tarjetaPaginas = `
    <div class="age-card lim-tool">
      <div class="lim-tool-cab"><h3>${icono("documento", 17)} Máximo de páginas por PDF subido</h3><p>Tope de páginas de un documento según el plan (no es un cupo de usos).</p></div>
      <div class="lim-planes">${planes.map((p) => `
        <div class="lim-plan lim-plan-${p}"><span class="lim-plan-nombre">${_NOMBRE_PLAN[p] || p}</span>
          <div class="lim-plan-campos"><input type="number" min="1" inputmode="numeric" class="age-input lim-pag" data-plan="${p}" value="${(cfg.max_paginas || {})[p] || 0}" aria-label="Páginas de ${_NOMBRE_PLAN[p] || p}"><span class="lim-pag-uni">págs</span></div>
        </div>`).join("")}</div>
    </div>`;
  panel.innerHTML = `
    <div class="age-card lim-intro"><p>Define cuántas veces puede usar cada herramienta cada perfil. <strong>0</strong> significa que ese plan <strong>no incluye</strong> la herramienta. El periodo (día/mes) marca cada cuánto se renueva el cupo. Los cambios se aplican en unos segundos.</p></div>
    ${(cfg.meta || []).map(tarjetaTool).join("")}
    ${tarjetaPaginas}
    <div class="lim-barra"><button class="age-btn age-btn-primary" id="lim-guardar">${icono("guardar", 15)} Guardar cambios</button></div>`;
  document.getElementById("lim-guardar").addEventListener("click", async () => {
    const tools = {};
    document.querySelectorAll(".lim-num").forEach((inp) => {
      const t = inp.dataset.tipo, p = inp.dataset.plan;
      const per = document.querySelector(`.lim-per[data-tipo="${t}"][data-plan="${p}"]`).value;
      tools[t] = tools[t] || {};
      tools[t][p] = { periodo: per, limite: Math.max(0, parseInt(inp.value, 10) || 0) };
    });
    const maxPaginas = {};
    document.querySelectorAll(".lim-pag").forEach((inp) => {
      maxPaginas[inp.dataset.plan] = Math.max(1, parseInt(inp.value, 10) || 1);
    });
    const r = await api("PUT", "/admin/api/limites", { tools, max_paginas: maxPaginas });
    if (r) toast("Límites guardados. Se aplican en unos segundos.");
  });
}

// Formato "datetime-local" (sin segundos, hora local del navegador) <->
// ISO en UTC que espera el backend (planes.py/promociones.py parsean con
// datetime.fromisoformat). Vive aquí porque solo lo usa el formulario de
// promoción; si otro panel necesitara lo mismo, se movería a un helper
// compartido.
function isoAInputLocal(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function inputLocalAIso(valor) {
  if (!valor) return "";
  const d = new Date(valor);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().slice(0, 19);
}

async function renderSistema() {
  const panel = document.getElementById("panel-sistema");
  panel.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const [sis, banner, promo] = await Promise.all([
    apiGet("/admin/api/sistema"), apiGet("/admin/api/banner"), apiGet("/admin/api/promocion"),
  ]);
  if (!sis) return;
  const diag = sis.diagnostico || {};
  const servicios = (sis.servicios || []).map((s) => {
    // 3 estados: verde (OK), rojo (crítico sin configurar), ámbar (opcional
    // sin configurar -> no es un problema, no alarma).
    const estado = s.ok
      ? { punto: '<span class="sis-punto"></span>', txt: "Configurado", cls: "sis-ok" }
      : (s.critico
        ? { punto: '<span class="sis-punto"></span>', txt: "Falta (crítico)", cls: "sis-ko" }
        : { punto: '<span class="sis-punto"></span>', txt: "Opcional, sin configurar", cls: "sis-opt" });
    return `<tr class="${estado.cls}">
      <td>${estado.punto} ${escapeHtml(s.nombre)}</td>
      <td>${estado.txt}</td>
      <td class="admin-reporte-meta">${escapeHtml(s.detalle)}</td>
    </tr>`;
  }).join("");
  const b = banner || { activo: false, texto: "", tipo: "info" };
  const p = promo || { activo: false, plan: "premium", descuento_pct: 0, duracion_texto: "", fecha_fin: "", stripe_promotion_code: "", mensaje: "" };
  // Panel de diagnóstico: semáforo global + cosas a vigilar.
  const todoOk = diag.todo_ok !== false;
  const avisos = [];
  if (diag.banner_activo) avisos.push(`<span class="sis-aviso sis-aviso-info">${icono("megafono", 15)} Hay un aviso global ACTIVO en la web ahora mismo</span>`);
  if ((diag.opcionales_ko || []).length) avisos.push(`<span class="sis-aviso sis-aviso-soft">${icono("alerta", 15)} Servicios opcionales sin configurar: ${diag.opcionales_ko.map(escapeHtml).join(", ")}</span>`);
  panel.innerHTML = `
    <div class="age-card admin-bloque sis-diagnostico ${todoOk ? "sis-diag-ok" : "sis-diag-ko"}">
      <div class="sis-diag-cab"><span class="sis-diag-ico">${todoOk ? icono("check", 26) : icono("alerta", 26)}</span>
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
    </div>
    <div class="age-card admin-bloque">
      <h3>${icono("destellos", 17)} Promoción / descuento temporal</h3>
      <p class="admin-reporte-meta">Muestra un banner con cuenta atrás a quien todavía NO tenga el plan elegido (visitantes sin cuenta incluidos). A quien ya lo tenga activo no le sale nada.</p>
      <label class="admin-toggle" style="margin:8px 0;"><input type="checkbox" id="promo-activo" ${p.activo ? "checked" : ""}> <span>Activar promoción</span></label>
      <label>Plan al que aplica</label>
      <select class="age-input" id="promo-plan">
        <option value="basico" ${p.plan === "basico" ? "selected" : ""}>Básico</option>
        <option value="premium" ${p.plan === "premium" ? "selected" : ""}>Premium</option>
      </select>
      <label>% de descuento (solo para el texto del aviso)</label>
      <input class="age-input" id="promo-descuento" type="number" min="0" max="100" value="${p.descuento_pct || 0}">
      <label>Duración del descuento (texto libre, ej. "2 meses")</label>
      <input class="age-input" id="promo-duracion" maxlength="60" value="${escapeHtml(p.duracion_texto)}" placeholder="Ej. 2 meses">
      <label>Termina el</label>
      <input class="age-input" id="promo-fecha-fin" type="datetime-local" value="${isoAInputLocal(p.fecha_fin)}">
      <label>Código de promoción de Stripe</label>
      <input class="age-input" id="promo-codigo" maxlength="80" value="${escapeHtml(p.stripe_promotion_code)}" placeholder="Ej. promo_1AbCdE...">
      <p class="admin-reporte-meta">Créalo antes en el Dashboard de Stripe (Productos → Cupones → Código promocional) y pega aquí su ID: al activarlo, se aplica solo al comprar el plan elegido arriba. Si lo dejas vacío, el aviso se muestra igualmente pero sin descuento automático en el pago.</p>
      <label>Mensaje del aviso (opcional, si lo dejas vacío se genera uno automático)</label>
      <input class="age-input" id="promo-mensaje" maxlength="200" value="${escapeHtml(p.mensaje)}" placeholder="Ej. 20% de descuento en Premium durante 2 meses">
      <button class="age-btn age-btn-primary" id="promo-guardar" style="margin-top:12px;">Guardar promoción</button>
    </div>`;
  panel.querySelector("#ban-guardar").addEventListener("click", async () => {
    const r = await api("PUT", "/admin/api/banner", {
      activo: panel.querySelector("#ban-activo").checked,
      texto: panel.querySelector("#ban-texto").value,
      tipo: panel.querySelector("#ban-tipo").value,
    });
    if (r) toast(r.activo ? "Aviso activado." : "Aviso guardado (oculto).");
  });
  panel.querySelector("#promo-guardar").addEventListener("click", async () => {
    const fechaFin = panel.querySelector("#promo-fecha-fin").value;
    const r = await api("PUT", "/admin/api/promocion", {
      activo: panel.querySelector("#promo-activo").checked,
      plan: panel.querySelector("#promo-plan").value,
      descuento_pct: parseInt(panel.querySelector("#promo-descuento").value, 10) || 0,
      duracion_texto: panel.querySelector("#promo-duracion").value,
      fecha_fin: inputLocalAIso(fechaFin),
      stripe_promotion_code: panel.querySelector("#promo-codigo").value,
      mensaje: panel.querySelector("#promo-mensaje").value,
    });
    if (r) toast(r.activo ? "Promoción activada." : "Promoción guardada (oculta).");
  });
}

// ===== init =====
document.addEventListener("DOMContentLoaded", async () => {
  inyectarIconosEstaticos();
  _permisos = await obtenerPermisos();
  if (!_permisos.admin && _permisos.permisos.length === 0) {
    mostrarNoAutorizado();
    return;
  }
  document.getElementById("admin-contenido").style.display = "flex";
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
