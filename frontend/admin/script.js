// Panel de administración. El backend (requiere_admin) es la barrera real;
// aquí solo se comprueba esAdmin para no montar la UI a quien no lo es.
import { esAdmin, obtenerPermisos, obtenerAuthHeaders, marcarContenidoListo } from "/assets/auth.js";
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
  dashboard: "cualquiera", temario: "temario", preguntas: "temario", analitica: "temario", calidad: "temario",
  usuarios: "usuarios", ingresos: "usuarios", reportes: "reportes", boe: "temario", bajas: "reportes", limites: "admin", auditoria: "admin", sistema: "admin", ranking: "admin",
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

// Controles "anterior/siguiente" reutilizables para listas paginadas por el
// backend (usuarios, reportes, auditoría -- todas devuelven {total,
// pagina, por_pagina}). clasePrefijo evita colisiones de id cuando hay más
// de una lista paginada en la misma pantalla.
function paginacionHtml(d, etiqueta, clasePrefijo) {
  const totalPaginas = Math.max(1, Math.ceil((d.total || 0) / (d.por_pagina || 20)));
  return `
    <div class="admin-paginacion">
      <button class="age-btn age-btn-outline admin-mini" id="${clasePrefijo}-prev" ${d.pagina <= 1 ? "disabled" : ""}>◀ Anterior</button>
      <span>Página ${d.pagina} de ${totalPaginas} · ${d.total} ${etiqueta}</span>
      <button class="age-btn age-btn-outline admin-mini" id="${clasePrefijo}-next" ${d.pagina >= totalPaginas ? "disabled" : ""}>Siguiente ▶</button>
    </div>`;
}
// Selector "segmentado" (grupo de pastillas, una activa a la vez) --
// componente compartido para no montar cada vez a mano la misma fila de
// botones sueltos que antes se repetía en Reportes, Vigilancia BOE y
// ahora también en el selector de grupo de la barra lateral. Cada botón
// admite un data-tab opcional (lo usa el selector de grupo genérico);
// Reportes/BOE, que ya tenían su propio cableado por id, simplemente
// mantienen los mismos ids que antes.
function segmentoHtml(botones) {
  return `<div class="admin-segmentado" role="tablist">${botones.map((b) => {
    const dataTab = b.tab ? ` data-tab="${escapeHtml(b.tab)}"` : "";
    // El badge se pinta siempre (oculto con "hidden" si b.badge es 0/undefined)
    // en vez de solo cuando hay algo, para que las actualizaciones en vivo
    // (ver _actualizarBadgesReportesDesglose) puedan des-ocultarlo con solo
    // tocar el atributo, sin tener que reconstruir el botón entero.
    const badge = b.tieneBadge ? `<span class="admin-segmento-badge" ${b.badge ? "" : "hidden"}>${b.badge || 0}</span>` : "";
    return `<button type="button" class="admin-segmento${b.activo ? " active" : ""}" id="${b.id}" role="tab" aria-selected="${b.activo ? "true" : "false"}"${dataTab}>${escapeHtml(b.label)}${badge}</button>`;
  }).join("")}</div>`;
}

function wirePaginacion(cont, clasePrefijo, onCambiarPagina) {
  cont.querySelector(`#${clasePrefijo}-prev`)?.addEventListener("click", () => onCambiarPagina(-1));
  cont.querySelector(`#${clasePrefijo}-next`)?.addEventListener("click", () => onCambiarPagina(1));
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

// Mismo criterio que _id_valido en blueprints/admin.py: evita el viaje al
// servidor para el caso típico (espacios, barras) antes de crear la ruta.
function _idValido(valor) {
  return Boolean(valor) && !valor.includes("/") && valor.length <= 60;
}

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

// ===== pestañas, agrupadas en la barra lateral =====
// Los botones de la barra representan GRUPOS, no cada vista suelta -- con
// 11 vistas en una lista plana la barra se quedaba larga (había que
// desplazarla para ver las últimas). Cada grupo con más de una vista
// ofrece DOS formas de elegirla, no una u otra:
// - enSidebar: desplegable en la propia barra lateral, para poder ir
//   directo a una vista concreta sin pasar antes por el panel (p. ej.
//   abrir "Contenido" y pulsar "Analítica" directamente).
// - enPanel: además, un selector de pastillas arriba del propio panel
//   (mismo patrón que ya usaban Reportes y Vigilancia BOE para sus dos
//   vistas internas) -- útil sobre todo en móvil, donde la barra lateral
//   se cierra sola al navegar (ver cerrarSidebar en activarPestana) y
//   este selector queda como la única forma de cambiar de vista sin
//   volver a abrir el menú.
// Los grupos de una sola vista (Dashboard, Vigilancia BOE) no llevan
// ninguno de los dos -- pulsar el botón ya lleva directo a su única vista.
const GRUPOS = {
  dashboard: { label: "Dashboard", pestanas: ["dashboard"], enPanel: false, enSidebar: false },
  contenido: { label: "Contenido", pestanas: ["temario", "preguntas", "analitica", "calidad"], enPanel: true, enSidebar: true },
  usuarios: { label: "Usuarios", pestanas: ["usuarios", "ingresos", "bajas", "reportes"], enPanel: true, enSidebar: true },
  boe: { label: "Vigilancia BOE", pestanas: ["boe"], enPanel: false, enSidebar: false },
  configuracion: { label: "Configuración", pestanas: ["limites", "sistema", "auditoria", "ranking"], enPanel: true, enSidebar: true },
};
const RENDERS = {
  dashboard: renderDashboard,
  temario: renderTemario,
  preguntas: renderPreguntas,
  analitica: renderAnalitica,
  calidad: renderCalidadIA,
  usuarios: renderUsuarios,
  ingresos: renderIngresos,
  reportes: renderReportes,
  boe: renderBoe,
  bajas: renderBajas,
  limites: renderLimites,
  auditoria: renderAuditoria,
  sistema: renderSistema,
  ranking: renderRanking,
};
const TITULO_POR_PESTANA = {
  dashboard: "Dashboard", temario: "Temario", preguntas: "Preguntas", analitica: "Analítica", calidad: "Calidad IA",
  usuarios: "Usuarios", ingresos: "Ingresos", reportes: "Reportes", boe: "Vigilancia BOE", bajas: "Bajas", limites: "Límites", auditoria: "Auditoría", sistema: "Sistema",
  ranking: "Clasificación",
};
const LABEL_SUBTAB = {
  temario: "Temario", preguntas: "Preguntas", analitica: "Analítica", calidad: "Calidad IA",
  usuarios: "Usuarios", ingresos: "Ingresos", bajas: "Bajas", reportes: "Reportes",
  limites: "Límites", sistema: "Sistema", auditoria: "Auditoría", ranking: "Clasificación",
};
function grupoDePestana(pestana) {
  return Object.keys(GRUPOS).find((g) => GRUPOS[g].pestanas.includes(pestana)) || null;
}
let pestanaActual = "dashboard";
// Recuerda la última subvista visitada de cada grupo (p. ej. si entraste
// por "Bajas", volver ahí y no siempre a "Usuarios" al pulsar el grupo).
let ultimaPestanaPorGrupo = {};

// Selector de pastillas arriba del panel activo (grupos con enPanel) --
// se oculta si el grupo no lo usa o si este admin en concreto solo tiene
// permiso para ver una de sus vistas (no tiene sentido un selector de una
// sola opción).
function renderSelectorGrupo(grupoId) {
  const cont = document.getElementById("admin-subtabs");
  if (!cont) return;
  const grupo = GRUPOS[grupoId];
  const visibles = grupo && grupo.enPanel ? grupo.pestanas.filter((p) => puedeVer(p)) : [];
  if (visibles.length <= 1) { cont.hidden = true; cont.innerHTML = ""; return; }
  cont.hidden = false;
  cont.innerHTML = segmentoHtml(visibles.map((p) => ({
    id: `subtab-${p}`, tab: p, label: LABEL_SUBTAB[p], activo: p === pestanaActual,
    tieneBadge: p === "reportes",
    badge: p === "reportes" ? _reportesPreguntasPendientesCache + _reportesSoportePendientesCache : 0,
  })));
  cont.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => activarPestana(b.dataset.tab)));
}

// Desplegable de un grupo en la propia barra lateral (grupos con
// enSidebar) -- pinta sus botones una vez al arrancar (con las vistas que
// este admin puede ver) y se abre/cierra sin volver a pintarlos.
function pintarSubmenuSidebar(grupoId) {
  const cont = document.getElementById(`admin-submenu-${grupoId}`);
  if (!cont) return;
  const visibles = GRUPOS[grupoId].pestanas.filter((p) => puedeVer(p));
  cont.innerHTML = visibles.map((p) => `<button type="button" class="admin-subtab" data-tab="${p}">${LABEL_SUBTAB[p]}</button>`).join("");
  cont.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => activarPestana(b.dataset.tab)));
}
// Acordeón exclusivo: abrir un desplegable cierra los demás, para que la
// barra lateral no acumule varios abiertos a la vez.
function alternarSubmenuSidebar(grupoId, forzarAbierto) {
  const cont = document.getElementById(`admin-submenu-${grupoId}`);
  const boton = document.querySelector(`.admin-tab[data-grupo="${grupoId}"]`);
  if (!cont || !boton) return;
  const abrir = forzarAbierto != null ? forzarAbierto : cont.hidden;
  if (abrir) {
    Object.keys(GRUPOS).forEach((g) => { if (g !== grupoId && GRUPOS[g].enSidebar) alternarSubmenuSidebar(g, false); });
  }
  cont.hidden = !abrir;
  boton.setAttribute("aria-expanded", String(abrir));
}

function activarPestana(nombre) {
  if (!puedeVer(nombre)) return;
  pestanaActual = nombre;
  const grupoId = grupoDePestana(nombre);
  if (grupoId) ultimaPestanaPorGrupo[grupoId] = nombre;

  document.querySelectorAll(".admin-tab[data-grupo]").forEach((b) => b.classList.toggle("active", b.dataset.grupo === grupoId));
  document.querySelectorAll(".admin-subtab").forEach((b) => b.classList.toggle("active", b.dataset.tab === nombre));
  if (grupoId && GRUPOS[grupoId].enSidebar) alternarSubmenuSidebar(grupoId, true);
  renderSelectorGrupo(grupoId);

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

// Desglose de reportes_pendientes por bandeja (preguntas reportadas /
// mensajes de soporte), para poder avisar en cada pestaña de cuál de las
// dos tiene algo nuevo -- se actualizan con lo último que se sepa (el
// dashboard al cargar, o la propia lista al visitarla en estado
// "pendiente"), igual que ya hacía _cambiosPendientesCache/
// _avisosPendientesCache para Vigilancia BOE.
let _reportesPreguntasPendientesCache = 0;
let _reportesSoportePendientesCache = 0;

// Pinta los tres avisos que dependen de este desglose: los dos badges de
// las sub-pestañas dentro del panel Reportes (si está montado) y el badge
// de la propia pastilla "Reportes" del selector de grupo (si está
// montada) -- se llama tanto al construir esas pastillas como cada vez
// que cambia el desglose, para no dejar un número obsoleto en pantalla
// tras marcar algo como revisado/descartado.
function _actualizarBadgesReportesDesglose() {
  const bp = document.getElementById("r-vista-preguntas")?.querySelector(".admin-segmento-badge");
  if (bp) { bp.textContent = _reportesPreguntasPendientesCache; bp.hidden = !_reportesPreguntasPendientesCache; }
  const bs = document.getElementById("r-vista-soporte")?.querySelector(".admin-segmento-badge");
  if (bs) { bs.textContent = _reportesSoportePendientesCache; bs.hidden = !_reportesSoportePendientesCache; }
  const total = _reportesPreguntasPendientesCache + _reportesSoportePendientesCache;
  const bpill = document.getElementById("subtab-reportes")?.querySelector(".admin-segmento-badge");
  if (bpill) { bpill.textContent = total; bpill.hidden = !total; }
}

function actualizarBadgeBoe(n) {
  // La pestaña en sí es siempre visible (con permiso, ver el bucle de
  // inicio de DOMContentLoaded más abajo) -- a petición del usuario
  // (15/08/2026): antes se ocultaba entera si no había nada pendiente, y
  // eso la hacía imposible de encontrar para entrar a comprobar el estado
  // o lanzar una revisión manual cuando no había avisos esperando. Solo el
  // número en rojo es condicional, igual que el resto de badges (Usuarios,
  // Reportes).
  const badge = document.getElementById("badge-boe");
  if (badge) { badge.textContent = n; badge.hidden = !n; }
}

// ===== Dashboard =====
async function renderDashboard() {
  const panel = document.getElementById("panel-dashboard");
  panel.innerHTML = `<p class="admin-cargando">Cargando panel…</p>`;
  const d = await apiGet(`/admin/api/resumen?oposicion=${oposicionActual()}`);
  if (!d) return;
  actualizarBadgeReportes(d.reportes_pendientes || 0);
  _reportesPreguntasPendientesCache = d.reportes_pendientes_preguntas || 0;
  _reportesSoportePendientesCache = d.reportes_pendientes_soporte || 0;
  _actualizarBadgesReportesDesglose();
  actualizarBadgeBoe((d.cambios_temario_pendientes || 0) + (d.avisos_oficiales_pendientes || 0));

  const salud = d.salud_contenido || {};
  const preg = d.preguntas_stats || {};
  const sinContenido = salud.temas_sin_contenido || [];
  const alertaReportes = (d.reportes_pendientes || 0) > 0;
  const puedeAbrirUsuario = puedeVer("usuarios");

  const huecos = sinContenido.length
    ? sinContenido.map((t) => `
        <button type="button" class="admin-chip admin-chip-warn admin-hueco" data-bloque="${escapeHtml(t.bloque)}" data-tema="${escapeHtml(t.tema)}">
          ${escapeHtml(t.titulo)} →
        </button>`).join("")
    : `<span class="admin-vacio">Todos los temas tienen contenido. ${icono("check", 14)}</span>`;

  // Usuarios por plan: barra segmentada de N colores (derivados de tokens --age-*).
  const PALETA_PLANES = ["var(--age-primary)", "var(--age-success)", "var(--age-warning)", "var(--age-primary-dark)"];
  const entradasPlanes = Object.entries(d.usuarios_por_plan || {});
  const totalPlanes = entradasPlanes.reduce((s, [, n]) => s + (n || 0), 0);
  const planesHtml = totalPlanes === 0
    ? `<p class="admin-vacio">Sin usuarios todavía.</p>`
    : `
      <div class="admin-planes-barra">${entradasPlanes.map(([plan, n], i) => {
        const pct = ((n || 0) / totalPlanes) * 100;
        return `<span class="admin-planes-seg" style="width:${pct.toFixed(2)}%; background:${PALETA_PLANES[i % PALETA_PLANES.length]}" title="${escapeHtml(plan)}: ${n}"></span>`;
      }).join("")}</div>
      <div class="admin-planes-leyenda">${entradasPlanes.map(([plan, n], i) => `
        <span class="admin-planes-item">
          <i class="admin-planes-dot" style="background:${PALETA_PLANES[i % PALETA_PLANES.length]}" aria-hidden="true"></i>
          ${escapeHtml(plan)} <strong>${n}</strong>
          <span class="admin-planes-pct">(${(((n || 0) / totalPlanes) * 100).toFixed(0)}%)</span>
        </span>`).join("")}</div>`;

  // Top gastadores IA: lista numerada en vez de tabla.
  const gastadores = d.top_gastadores_ia || [];
  const gastadoresHtml = gastadores.length
    ? gastadores.map((g, i) => `
        <li class="admin-ranking-item ${puedeAbrirUsuario ? "admin-fila-click" : ""}"
            data-uid-gasto="${escapeHtml(g.uid)}"
            ${puedeAbrirUsuario ? 'tabindex="0" role="button"' : ""}
            aria-label="Ver ficha de ${escapeHtml(g.email || "usuario sin email")}">
          <span class="admin-ranking-pos">${i + 1}</span>
          <span class="admin-ranking-info">
            <span class="admin-ranking-titulo">${escapeHtml(g.email || "(sin email)")}</span>
            <span class="admin-ranking-meta"><span class="admin-chip">${escapeHtml(g.plan)}</span></span>
          </span>
          <span class="admin-ranking-valor">${(g.coste_mes || 0).toFixed(4)}€</span>
        </li>`).join("")
    : `<li class="admin-vacio admin-ranking-vacio">Sin consumo de IA este mes.</li>`;

  // Top temas fallados: lista numerada en vez de tabla.
  const temasFallados = d.top_temas_fallados || [];
  const temasHtml = temasFallados.length
    ? temasFallados.map((t, i) => `
        <li class="admin-ranking-item">
          <span class="admin-ranking-pos">${i + 1}</span>
          <span class="admin-ranking-info">
            <span class="admin-ranking-titulo">${escapeHtml(t.titulo || t.tema_id)}</span>
          </span>
          <span class="admin-ranking-valor admin-ranking-valor-danger">${t.fallos} fallos</span>
        </li>`).join("")
    : `<li class="admin-vacio admin-ranking-vacio">Sin datos de fallos todavía.</li>`;

  panel.innerHTML = `
    <div class="admin-hero-grid">
      <div class="admin-hero admin-hero-primary${puedeAbrirUsuario ? " admin-hero-clic" : ""}" id="hero-ingresos" ${puedeAbrirUsuario ? 'tabindex="0" role="button" aria-label="Ver el detalle de ingresos"' : ""}>
        <div class="admin-hero-cab"><span>${icono("euro", 18)} Ingresos / mes (MRR)</span></div>
        <div class="admin-hero-num">${(d.mrr || 0).toFixed(2)}€</div>
        <div class="admin-hero-sub">${d.suscripciones_pago || 0} suscripciones de pago</div>
      </div>
      <div class="admin-hero admin-hero-navy${puedeAbrirUsuario ? " admin-hero-clic" : ""}" id="hero-usuarios" ${puedeAbrirUsuario ? 'tabindex="0" role="button" aria-label="Ver la lista de usuarios"' : ""}>
        <div class="admin-hero-cab"><span>${icono("usuarios", 18)} Usuarios totales</span></div>
        <div class="admin-hero-num">${d.usuarios_totales}</div>
        <div class="admin-hero-sub">+${d.usuarios_nuevos_7_dias || 0} en los últimos 7 días</div>
      </div>
    </div>

    <div class="admin-kpi-grid">
      <div class="age-card admin-kpi"><span class="admin-kpi-ico">${icono("rayo", 18)}</span><span class="admin-kpi-num">${d.usuarios_activos_7_dias || 0}</span><span class="admin-kpi-lbl">Activos (7 días)</span></div>
      <div class="age-card admin-kpi"><span class="admin-kpi-ico">${icono("matraz", 18)}</span><span class="admin-kpi-num">${d.tests_ultimos_7_dias}</span><span class="admin-kpi-lbl">Tests (7 días)</span><span class="admin-kpi-sub">${d.tests_ultimos_30_dias} en 30 días</span></div>
      <div class="age-card admin-kpi"><span class="admin-kpi-ico">${icono("libros", 18)}</span><span class="admin-kpi-num">${d.tests_total || 0}</span><span class="admin-kpi-lbl">Tests totales</span></div>
      <div class="age-card admin-kpi"><span class="admin-kpi-ico">${icono("robot", 18)}</span><span class="admin-kpi-num">${(d.coste_ia_mes || 0).toFixed(2)}€</span><span class="admin-kpi-lbl">Coste IA (mes)</span></div>
      <div class="age-card admin-kpi admin-kpi-clic ${alertaReportes ? "admin-kpi-alerta" : ""}" id="stat-reportes"><span class="admin-kpi-ico">${icono("bandera", 18)}</span><span class="admin-kpi-num">${d.reportes_pendientes}</span><span class="admin-kpi-lbl">Reportes pendientes</span></div>
    </div>

    <div class="admin-dash-grid">
      <div class="admin-dash-col">
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
      </div>

      <div class="admin-dash-col">
        <div class="age-card admin-bloque">
          <h3>Usuarios por plan</h3>
          ${planesHtml}
        </div>

        <div class="age-card admin-bloque">
          <h3>Usuarios que más IA consumen (este mes)</h3>
          <ol class="admin-ranking">${gastadoresHtml}</ol>
        </div>

        <div class="age-card admin-bloque">
          <h3>Top 5 temas más fallados (todos los usuarios)</h3>
          <ol class="admin-ranking">${temasHtml}</ol>
        </div>
      </div>
    </div>`;

  panel.querySelector("#stat-reportes")?.addEventListener("click", () => activarPestana("reportes"));

  if (puedeAbrirUsuario) {
    const irAIngresos = () => activarPestana("ingresos");
    const irAUsuarios = () => activarPestana("usuarios");
    panel.querySelector("#hero-ingresos")?.addEventListener("click", irAIngresos);
    panel.querySelector("#hero-ingresos")?.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); irAIngresos(); } });
    panel.querySelector("#hero-usuarios")?.addEventListener("click", irAUsuarios);
    panel.querySelector("#hero-usuarios")?.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); irAUsuarios(); } });
  }

  panel.querySelectorAll("[data-uid-gasto]").forEach((li) => {
    if (!puedeAbrirUsuario) return;
    const abrir = () => abrirUsuario(li.dataset.uidGasto);
    li.addEventListener("click", abrir);
    li.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); }
    });
  });

  panel.querySelectorAll(".admin-hueco").forEach((b) => b.addEventListener("click", () => {
    temaSeleccionado = { bloque: b.dataset.bloque, tema: b.dataset.tema, titulo: b.textContent.trim() };
    activarPestana("temario");
    setTimeout(cargarChunks, 250); // tras montar el panel de temario
  }));
}

// ===== Temario =====
let temaSeleccionado = null;
// Qué bloques están desplegados en la lista -- persiste entre renderTemario()
// (p. ej. tras renombrar algo) para no cerrar de golpe lo que el admin ya
// tenía abierto.
const bloquesAbiertos = new Set();
async function renderTemario() {
  const panel = document.getElementById("panel-temario");
  panel.innerHTML = `<p class="admin-cargando">Cargando temario…</p>`;
  const d = await apiGet(`/admin/api/temario/${oposicionActual()}`);
  if (!d) return;
  const op = oposicionActual();
  const bloques = d.bloques || [];
  if (temaSeleccionado) bloquesAbiertos.add(temaSeleccionado.bloque);
  const totalTemas = bloques.reduce((n, b) => n + b.temas.length, 0);
  const arbol = `
    <div class="tem-cab">
      <span>Estructura del programa</span>
      <span class="ficha-badge">${totalTemas} tema${totalTemas === 1 ? "" : "s"} en total</span>
    </div>
    ${bloques.map((b) => {
      const abierto = bloquesAbiertos.has(b.id);
      const totalChunks = b.temas.reduce((n, t) => n + (t.num_chunks || 0), 0);
      return `
      <div class="tem-bloque">
        <button type="button" class="tem-bloque-cab" data-toggle-bloque="${escapeHtml(b.id)}" aria-expanded="${abierto}">
          <span class="tem-bloque-chevron">›</span>
          <span class="tem-bloque-ico" aria-hidden="true">${icono("carpeta", 20)}</span>
          <span class="tem-bloque-info">
            <span class="tem-bloque-titulo">${escapeHtml(b.titulo)}</span>
            <span class="tem-bloque-meta">${b.temas.length} tema${b.temas.length === 1 ? "" : "s"} · ${totalChunks} ficha${totalChunks === 1 ? "" : "s"}</span>
          </span>
          <span class="ficha-badge ${b.publicado ? "ficha-badge-ok" : "ficha-badge-gratis"}">${b.publicado ? "Publicado" : "Borrador"}</span>
        </button>
        <div class="tem-bloque-cuerpo" ${abierto ? "" : "hidden"}>
          <div class="tem-bloque-acciones">
            <button type="button" class="admin-icono" data-renombrar-bloque="${escapeHtml(b.id)}" title="Renombrar bloque">${icono("lapiz", 14)} Renombrar</button>
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
        </div>
      </div>`;
    }).join("") || '<p class="admin-vacio">Sin bloques todavía.</p>'}`;

  panel.innerHTML = `
    <div class="admin-filtros">
      <button class="age-btn age-btn-primary admin-mini" id="t-nuevo-bloque">+ Nuevo bloque</button>
    </div>
    <div class="admin-temario-grid">
      <div class="age-card admin-arbol">${arbol}</div>
      <div class="age-card admin-chunks" id="admin-chunks"><p class="admin-vacio">Elige un tema para ver y editar sus fichas.</p></div>
    </div>`;

  panel.querySelectorAll("[data-toggle-bloque]").forEach((btn) => btn.addEventListener("click", () => {
    const id = btn.dataset.toggleBloque;
    const cuerpo = btn.nextElementSibling;
    const abrir = cuerpo.hidden;
    cuerpo.hidden = !abrir;
    btn.setAttribute("aria-expanded", String(abrir));
    if (abrir) bloquesAbiertos.add(id); else bloquesAbiertos.delete(id);
  }));
  panel.querySelector("#t-nuevo-bloque").addEventListener("click", async () => {
    const id = (prompt("Id del nuevo bloque (ej. bloque_07):") || "").trim();
    if (!id) return;
    if (!_idValido(id)) { toast("Id no válido: sin espacios ni barras, máximo 60 caracteres.", "error"); return; }
    const titulo = (prompt("Título del bloque:", "") || "").trim() || id;
    const r = await api("POST", `/admin/api/temario/${op}/nuevo-bloque`, { id, titulo });
    if (r) { toast("Bloque creado."); renderTemario(); }
  });
  panel.querySelectorAll(".admin-nuevo-tema").forEach((btn) => btn.addEventListener("click", async () => {
    const id = (prompt("Id del nuevo tema (ej. tema_03):") || "").trim();
    if (!id) return;
    if (!_idValido(id)) { toast("Id no válido: sin espacios ni barras, máximo 60 caracteres.", "error"); return; }
    const titulo = (prompt("Título del tema:", "") || "").trim() || id;
    const r = await api("POST", `/admin/api/temario/${op}/${btn.dataset.bloque}/nuevo-tema`, { id, titulo });
    if (r) { toast("Tema creado."); renderTemario(); }
  }));
  panel.querySelectorAll("[data-renombrar-bloque]").forEach((btn) => btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const titulo = (prompt("Nuevo título del bloque:") || "").trim();
    if (!titulo) return;
    const r = await api("PATCH", `/admin/api/temario/${op}/${btn.dataset.renombrarBloque}`, { titulo });
    if (r) { toast("Bloque renombrado."); renderTemario(); }
  }));
  panel.querySelectorAll("[data-renombrar-tema]").forEach((btn) => btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const [bloque, tema, actual] = btn.dataset.renombrarTema.split("|");
    const titulo = (prompt("Nuevo título del tema:", actual) || "").trim();
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
    <div class="age-card" id="preguntas-tabla"><p class="admin-cargando">Cargando…</p></div>`;
  panel.querySelector("#f-aplicar").addEventListener("click", cargarPreguntas);
  panel.querySelector("#p-nueva").addEventListener("click", () => modalPregunta(null));
  panel.querySelector("#p-importar").addEventListener("click", modalImportar);
  panel.querySelector("#p-csv").addEventListener("click", () => descargarCSV(`/admin/api/preguntas/export?oposicion=${oposicionActual()}`, `preguntas_${oposicionActual()}.csv`));
  panel.querySelector("#f-texto").addEventListener("keydown", (e) => { if (e.key === "Enter") cargarPreguntas(); });
  cargarPreguntas();
}

function preguntaFilaHtml(p) {
  const sinExpl = !(p.explicacion || "").trim();
  return `
    <div class="preg-fila ${p.activa ? "" : "preg-fila-inactiva"}">
      <div class="preg-fila-txt">
        <span>${escapeHtml(p.pregunta.slice(0, 100))}${p.pregunta.length > 100 ? "…" : ""}</span>
        ${sinExpl ? '<span class="admin-badge-alerta">sin explicación</span>' : ""}
        ${p.activa ? "" : '<span class="admin-badge-off">inactiva</span>'}
      </div>
      <div class="preg-fila-meta">
        <span class="admin-badge" title="Veces fallada por los usuarios">${p.veces_fallada} fallo${p.veces_fallada === 1 ? "" : "s"}</span>
        <button class="admin-icono" data-editar="${escapeHtml(p.id)}" title="Editar">${icono("lapiz", 14)}</button>
        ${p.activa
          ? `<button class="admin-icono" data-desactivar="${escapeHtml(p.id)}" title="Desactivar">${icono("papelera", 14)}</button>`
          : `<button class="admin-icono" data-reactivar="${escapeHtml(p.id)}" title="Reactivar">${icono("actualizar", 14)}</button>`}
      </div>
    </div>`;
}

// Qué bloques de Preguntas están desplegados -- mismo patrón que
// bloquesAbiertos en Temario, para que no se cierre todo tras editar algo.
const bloquesAbiertosPreguntas = new Set();
async function cargarPreguntas() {
  const cont = document.getElementById("preguntas-tabla");
  if (!cont) return;
  const params = new URLSearchParams({ oposicion: oposicionActual() });
  const bloqueFiltro = document.getElementById("f-bloque")?.value.trim();
  const anio = document.getElementById("f-anio")?.value.trim();
  const texto = (document.getElementById("f-texto")?.value.trim() || "").toLowerCase();
  if (bloqueFiltro) params.set("bloque", bloqueFiltro);
  if (anio) params.set("anio", anio);
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const [d, temario] = await Promise.all([
    apiGet(`/admin/api/preguntas?${params.toString()}`),
    apiGet(`/admin/api/temario/${oposicionActual()}`),
  ]);
  if (!d) return;
  window._preguntasCache = {};
  let lista = d.preguntas || [];
  if (texto) lista = lista.filter((p) => (p.pregunta || "").toLowerCase().includes(texto));
  lista.forEach((p) => { window._preguntasCache[p.id] = p; });

  // Agrupa por bloque/tema a partir del propio tema_id ("bloque_01-tema_01"
  // -- mismo criterio que _bloque_de_tema en blueprints/admin.py), cruzado
  // con el temario real para mostrar títulos y detectar huecos (temas sin
  // ninguna pregunta) igual que ya hace la vista de Temario.
  const porBloque = new Map();
  const sinTema = [];
  lista.forEach((p) => {
    const temaId = p.tema_id || "";
    const bloqueId = temaId.includes("-") ? temaId.split("-")[0] : "";
    if (!bloqueId) { sinTema.push(p); return; }
    if (!porBloque.has(bloqueId)) porBloque.set(bloqueId, new Map());
    const porTema = porBloque.get(bloqueId);
    if (!porTema.has(temaId)) porTema.set(temaId, []);
    porTema.get(temaId).push(p);
  });

  const bloquesConocidos = (temario?.bloques || []).map((b) => {
    const porTema = porBloque.get(b.id) || new Map();
    porBloque.delete(b.id);
    // Las preguntas guardan el tema_id completo ("bloque_01-tema_01"), pero
    // el temario identifica cada tema solo por su id corto ("tema_01") --
    // hay que reconstruir la clave completa para que casen.
    const temas = b.temas.map((t) => ({ id: t.id, titulo: t.titulo, preguntas: porTema.get(`${b.id}-${t.id}`) || [] }));
    porTema.forEach((preguntas, temaId) => { if (!b.temas.some((t) => `${b.id}-${t.id}` === temaId)) temas.push({ id: temaId, titulo: temaId, preguntas }); });
    return { id: b.id, titulo: b.titulo, temas, desconocido: false };
  });
  // Bloques con preguntas cuyo id ya no existe en el temario actual (borrado
  // o escrito a mano al importar) -- se muestran igual, marcados, para que
  // no queden preguntas invisibles.
  const bloquesDesconocidos = Array.from(porBloque.entries()).map(([bloqueId, porTema]) => ({
    id: bloqueId, titulo: bloqueId,
    temas: Array.from(porTema.entries()).map(([temaId, preguntas]) => ({ id: temaId, titulo: temaId, preguntas })),
    desconocido: true,
  }));
  const bloques = [...bloquesConocidos, ...bloquesDesconocidos];

  const bloqueHtml = (b) => {
    const totalPreguntas = b.temas.reduce((n, t) => n + t.preguntas.length, 0);
    const sinExplBloque = b.temas.reduce((n, t) => n + t.preguntas.filter((p) => !(p.explicacion || "").trim()).length, 0);
    const abierto = bloquesAbiertosPreguntas.has(b.id);
    const badge = b.desconocido
      ? `<span class="ficha-badge ficha-badge-warn">Bloque no encontrado</span>`
      : totalPreguntas === 0
        ? `<span class="ficha-badge ficha-badge-gratis">Sin preguntas</span>`
        : `<span class="ficha-badge ${sinExplBloque ? "ficha-badge-warn" : "ficha-badge-ok"}">${totalPreguntas}${sinExplBloque ? ` · ${sinExplBloque} sin explicación` : ""}</span>`;
    return `
      <div class="tem-bloque">
        <button type="button" class="tem-bloque-cab" data-toggle-bloque-preg="${escapeHtml(b.id)}" aria-expanded="${abierto}">
          <span class="tem-bloque-chevron">›</span>
          <span class="tem-bloque-ico" aria-hidden="true">${icono("pregunta", 20)}</span>
          <span class="tem-bloque-info">
            <span class="tem-bloque-titulo">${escapeHtml(b.titulo)}</span>
            <span class="tem-bloque-meta">${b.temas.length} tema${b.temas.length === 1 ? "" : "s"} · ${totalPreguntas} pregunta${totalPreguntas === 1 ? "" : "s"}</span>
          </span>
          ${badge}
        </button>
        <div class="tem-bloque-cuerpo" ${abierto ? "" : "hidden"}>
          ${b.temas.map((t) => `
            <div class="preg-tema-grupo">
              <p class="preg-tema-titulo">${escapeHtml(t.titulo)} <span class="admin-badge">${t.preguntas.length}</span></p>
              ${t.preguntas.map(preguntaFilaHtml).join("") || '<p class="admin-vacio">Sin preguntas en este tema.</p>'}
            </div>`).join("") || '<p class="admin-vacio">Sin temas.</p>'}
        </div>
      </div>`;
  };

  cont.innerHTML = `
    <div class="tem-cab">
      <span>${lista.length} pregunta${lista.length === 1 ? "" : "s"} en total</span>
      <span class="ficha-badge">${bloques.length} bloque${bloques.length === 1 ? "" : "s"}</span>
    </div>
    ${bloques.map(bloqueHtml).join("") || '<p class="admin-vacio">Sin bloques en el temario todavía.</p>'}
    ${sinTema.length ? `
      <div class="tem-bloque">
        <button type="button" class="tem-bloque-cab" data-toggle-bloque-preg="__sin_tema__" aria-expanded="${bloquesAbiertosPreguntas.has("__sin_tema__")}">
          <span class="tem-bloque-chevron">›</span>
          <span class="tem-bloque-ico" aria-hidden="true">${icono("alerta", 20)}</span>
          <span class="tem-bloque-info">
            <span class="tem-bloque-titulo">Sin tema asignado</span>
            <span class="tem-bloque-meta">${sinTema.length} pregunta${sinTema.length === 1 ? "" : "s"} sin bloque/tema válido</span>
          </span>
          <span class="ficha-badge ficha-badge-warn">${sinTema.length}</span>
        </button>
        <div class="tem-bloque-cuerpo" ${bloquesAbiertosPreguntas.has("__sin_tema__") ? "" : "hidden"}>
          ${sinTema.map(preguntaFilaHtml).join("")}
        </div>
      </div>` : ""}`;

  cont.querySelectorAll("[data-toggle-bloque-preg]").forEach((btn) => btn.addEventListener("click", () => {
    const id = btn.dataset.toggleBloquePreg;
    const cuerpo = btn.nextElementSibling;
    const abrir = cuerpo.hidden;
    cuerpo.hidden = !abrir;
    btn.setAttribute("aria-expanded", String(abrir));
    if (abrir) bloquesAbiertosPreguntas.add(id); else bloquesAbiertosPreguntas.delete(id);
  }));
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
    const elEnunciado = document.getElementById("q-enunciado");
    if (!elEnunciado.value.trim()) { toast("Falta el enunciado de la pregunta.", "error"); elEnunciado.focus(); return; }
    for (const k of ["A", "B", "C", "D"]) {
      const elOpcion = document.getElementById(`op-${k}`);
      if (!elOpcion.value.trim()) { toast(`Falta el texto de la opción ${k}.`, "error"); elOpcion.focus(); return; }
    }
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

  const ETIQUETA_OPOSICION = { AGE: "AGE", GACE: "GACE", AUXILIAR: "Auxiliar", METRO: "Metro" };
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

  // "recientes" (con uid/email) solo llega si el permiso de quien pide la
  // lista incluye "usuarios" -- ver bajas_listar en blueprints/admin.py.
  // Va primero y siempre que haya alguna, aunque d.total sea 0 más abajo
  // no puede pasar a la vez, pero se comprueba por separado por claridad.
  const recientesHtml = Array.isArray(d.recientes) ? `
    <div class="age-card admin-bloque">
      <h3>Bajas recientes (${d.recientes.length})</h3>
      <p class="admin-reporte-meta">Se escribe en cuanto alguien pulsa "cancelar", no cuando el periodo ya pagado termina -- para poder ofrecerle algo o hacerle seguimiento a tiempo, antes de que se vaya de verdad.</p>
      ${d.recientes.length ? d.recientes.map((b) => `
        <div class="admin-reporte admin-fila-click" data-uid="${escapeHtml(b.uid)}" tabindex="0" role="button" aria-label="Ver ficha de ${escapeHtml(b.email || "usuario sin email")}">
          <div class="admin-reporte-cab">
            <span class="admin-reporte-estado ${b.efectiva ? "admin-estado-descartado" : "admin-estado-pendiente"}">${b.efectiva ? "Baja efectiva" : "Pendiente · aún activo"}</span>
            <span class="admin-reporte-meta">${escapeHtml(b.oposicion || "-")} · ${escapeHtml(fechaCorta(b.fecha))}</span>
          </div>
          <p class="admin-reporte-motivo">
            <strong>${escapeHtml(b.nombre || b.email || "(sin email)")}</strong>
            — ${escapeHtml(ETIQUETA_MOTIVO_BAJA[b.motivo] || b.motivo)}
            ${!b.efectiva && b.proxima_renovacion ? ` · activo hasta ${fechaCorta(b.proxima_renovacion)}` : ""}
          </p>
          ${b.comentario ? `<p class="admin-reporte-motivo">"${escapeHtml(b.comentario)}"</p>` : ""}
        </div>`).join("")
        : '<p class="admin-vacio">Todavía no se ha dado de baja nadie.</p>'}
    </div>` : "";

  if (!d.total) {
    panel.innerHTML = recientesHtml || `<div class="age-card"><p class="admin-vacio">Todavía no se ha dado de baja nadie. ${icono("check", 14)}</p></div>`;
    panel.querySelectorAll("[data-uid]").forEach((fila) => {
      const abrir = () => abrirUsuario(fila.dataset.uid);
      fila.addEventListener("click", abrir);
      fila.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); } });
    });
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
    ${recientesHtml}

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

  panel.querySelectorAll("[data-uid]").forEach((fila) => {
    const abrir = () => abrirUsuario(fila.dataset.uid);
    fila.addEventListener("click", abrir);
    fila.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); } });
  });
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
    </div>
    <div id="usuarios-tabla"><p class="admin-cargando">Cargando…</p></div>`;
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

// ===== Clasificación (ranking): participantes de demostración =====
// Vive en su propia pestaña (grupo "configuracion"), separada a propósito
// de "Usuarios" -- aunque ya no se guardan como documentos en "usuarios"
// (ver blueprints/admin.py, colección aparte "ranking_demo"), mezclarlo
// visualmente con la lista de usuarios reales seguía siendo confuso.
async function renderRanking() {
  const panel = document.getElementById("panel-ranking");
  panel.innerHTML = `
    <div class="age-card admin-bloque">
      <h3>Participantes de demostración</h3>
      <p class="admin-reporte-meta">
        Añade 30 entradas de ejemplo a /ranking (nombre inventado + racha) para que no se vea
        vacío mientras hay pocos usuarios apuntados de verdad. No son cuentas reales -- no
        cuentan como usuarios en ningún otro sitio del panel. Bórralas en cuanto haya
        suficientes participantes reales.
      </p>
      <p class="admin-reporte-meta" id="ranking-demo-estado"><em>Comprobando…</em></p>
      <div class="admin-filtros-btn" style="display:flex; gap:10px; margin-top:10px;">
        <button class="age-btn age-btn-primary" id="ranking-demo-sembrar">Crear demostración</button>
        <button class="age-btn age-btn-outline" id="ranking-demo-borrar">Borrar demostración</button>
      </div>
    </div>`;

  const elEstado = panel.querySelector("#ranking-demo-estado");
  async function actualizarEstado() {
    const r = await apiGet("/admin/api/ranking/demo");
    if (!r) return;
    elEstado.innerHTML = r.cantidad
      ? `Ahora mismo hay <strong>${r.cantidad}</strong> participantes de demostración en la clasificación.`
      : "No hay ningún participante de demostración ahora mismo.";
  }
  panel.querySelector("#ranking-demo-sembrar").addEventListener("click", async () => {
    const r = await api("POST", "/admin/api/ranking/demo");
    if (r) { toast(r.mensaje || "Hecho."); actualizarEstado(); }
  });
  panel.querySelector("#ranking-demo-borrar").addEventListener("click", async () => {
    if (!confirm("¿Borrar los participantes de demostración de la clasificación?")) return;
    const r = await api("DELETE", "/admin/api/ranking/demo");
    if (r) { toast(r.mensaje || "Hecho."); actualizarEstado(); }
  });
  actualizarEstado();
}

// ===== Ingresos =====
// Detalle de cada cliente (una fila por oposición activada, no por
// usuario) -- lo que hay detrás del MRR del dashboard, para llevar un
// control real de la cartera: quién paga, cuánto, desde cuándo, si está
// en riesgo (cancelación programada, pago fallido, sin actividad
// reciente), quién está en prueba y quién se ha ido.
let paginaIngresos = 1;

const ESTADO_CLIENTE_LABEL = {
  activo: ["Activo", "admin-chip-ok"],
  cancelando: ["Cancelando", "admin-chip-warn"],
  baja: ["Baja", "admin-chip-warn"],
  prueba: ["En prueba", "admin-chip"],
};

const ESTADO_SUSCRIPCION_LABEL = {
  active: ["Al día", "admin-chip-ok"],
  trialing: ["En prueba", "admin-chip-ok"],
  past_due: ["Pago fallido", "admin-chip-warn"],
  unpaid: ["Impagada", "admin-chip-warn"],
  canceled: ["Cancelada", "admin-chip-warn"],
  incomplete: ["Incompleta", "admin-chip-warn"],
  incomplete_expired: ["Incompleta (caducada)", "admin-chip-warn"],
};

function _paramsIngresos() {
  const params = new URLSearchParams();
  const busqueda = document.getElementById("i-busqueda")?.value.trim();
  const plan = document.getElementById("i-plan")?.value;
  const oposicion = document.getElementById("i-oposicion")?.value;
  const estado = document.getElementById("i-estado")?.value;
  if (busqueda) params.set("busqueda", busqueda);
  if (plan) params.set("plan", plan);
  if (oposicion) params.set("oposicion", oposicion);
  if (estado) params.set("estado", estado);
  return params;
}

async function renderIngresos() {
  const panel = document.getElementById("panel-ingresos");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <input id="i-busqueda" class="age-input" placeholder="Buscar por email…">
      <select id="i-estado" class="age-input">
        <option value="">Todos los estados</option>
        <option value="activo">Activos</option>
        <option value="cancelando">Cancelando</option>
        <option value="baja">Bajas</option>
        <option value="prueba">En prueba</option>
      </select>
      <select id="i-plan" class="age-input"><option value="">Todos los planes</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
      <select id="i-oposicion" class="age-input"><option value="">Todas las oposiciones</option><option value="AGE">AGE</option><option value="GACE">GACE</option><option value="AUXILIAR">Auxiliar</option></select>
      <button class="age-btn age-btn-primary admin-filtros-btn" id="i-aplicar">Buscar</button>
      <button class="age-btn age-btn-outline admin-filtros-btn" id="i-csv">${icono("descargar", 15)} CSV</button>
    </div>
    <div id="ingresos-contenido"><p class="admin-cargando">Cargando…</p></div>`;
  panel.querySelector("#i-aplicar").addEventListener("click", () => { paginaIngresos = 1; cargarIngresos(); });
  panel.querySelector("#i-estado").addEventListener("change", () => { paginaIngresos = 1; cargarIngresos(); });
  panel.querySelector("#i-csv").addEventListener("click", () => {
    descargarCSV(`/admin/api/ingresos/export?${_paramsIngresos().toString()}`, "ingresos.csv");
  });
  panel.querySelector("#i-busqueda").addEventListener("keydown", (e) => { if (e.key === "Enter") { paginaIngresos = 1; cargarIngresos(); } });
  cargarIngresos();
}

async function cargarIngresos() {
  const cont = document.getElementById("ingresos-contenido");
  if (!cont) return;
  const params = _paramsIngresos();
  params.set("pagina", paginaIngresos);
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/ingresos?${params.toString()}`);
  if (!d) return;
  const r = d.resumen || {};
  const porEstado = r.por_estado || {};
  const desglosePlan = Object.entries(r.por_plan || {})
    .map(([p, n]) => `${p === "premium" ? "Premium" : "Básico"}: ${n}`).join(" · ") || "—";
  const desgloseEstado = ["activo", "cancelando", "baja", "prueba"]
    .filter((e) => porEstado[e]).map((e) => `${ESTADO_CLIENTE_LABEL[e][0]}: ${porEstado[e]}`).join(" · ") || "—";

  const filas = (d.filas || []).map((f) => {
    const [estadoClienteLbl, estadoClienteCls] = ESTADO_CLIENTE_LABEL[f.estado_cliente] || [f.estado_cliente || "—", "admin-chip"];
    const planLbl = f.plan === "premium" ? "Premium" : f.plan === "basico" ? "Básico" : "—";
    const fechaClave = f.proxima_renovacion || f.prueba_fin;
    // El estado de cliente (activo/cancelando/...) no distingue un pago que
    // está fallando de verdad (past_due/unpaid/incomplete en Stripe) de uno
    // que está simplemente al día -- se añade aparte, solo cuando avisa de
    // algo, para no duplicar información en la fila cuando todo va bien.
    const estadoPago = ESTADO_SUSCRIPCION_LABEL[f.estado_suscripcion];
    const avisoPago = estadoPago && estadoPago[1] === "admin-chip-warn"
      ? ` <span class="admin-chip admin-chip-warn" title="Estado del pago en Stripe">${escapeHtml(estadoPago[0])}</span>`
      : "";
    return `
      <tr class="admin-fila-click" data-uid="${escapeHtml(f.uid)}" tabindex="0" role="button" aria-label="Ver ficha de ${escapeHtml(f.email || "usuario sin email")}">
        <td>
          <div class="admin-td-principal">${escapeHtml(f.nombre || f.email || "(sin email)")}</div>
          ${f.nombre ? `<div class="admin-td-secundario">${escapeHtml(f.email || "")}</div>` : ""}
        </td>
        <td>${escapeHtml(f.oposicion)}</td>
        <td><span class="admin-chip ${estadoClienteCls}">${escapeHtml(estadoClienteLbl)}</span>${f.cancela_al_final ? ` <span class="admin-chip admin-chip-warn" title="Se cancela al terminar el periodo ya pagado">Se cancela</span>` : ""}${avisoPago}</td>
        <td>${planLbl}</td>
        <td class="admin-num">${(f.precio || 0).toFixed(2)}€</td>
        <td>${fechaCorta(fechaClave)}</td>
        <td>${fechaCorta(f.cliente_desde)}</td>
        <td>${f.activo_7_dias ? `${icono("check", 14)} Sí` : "No"}</td>
      </tr>`;
  }).join("");

  cont.innerHTML = `
    <div class="admin-ingresos-resumen">
      <div class="admin-ingresos-metrica"><span class="admin-ingresos-num">${(r.mrr || 0).toFixed(2)}€</span><span class="admin-ingresos-lbl">MRR (de esta búsqueda)</span></div>
      <div class="admin-ingresos-metrica"><span class="admin-ingresos-num">${r.suscripciones || 0}</span><span class="admin-ingresos-lbl">Suscripciones de pago</span></div>
      <div class="admin-ingresos-metrica"><span class="admin-ingresos-num">${(r.arpu || 0).toFixed(2)}€</span><span class="admin-ingresos-lbl">Ingreso medio (ARPU)</span></div>
      <div class="admin-ingresos-metrica admin-ingresos-metrica-desglose"><span class="admin-ingresos-lbl">${escapeHtml(desgloseEstado)}</span><span class="admin-ingresos-lbl">${escapeHtml(desglosePlan)}</span></div>
    </div>
    <div class="admin-scroll"><table class="admin-tabla">
      <thead><tr><th>Cliente</th><th>Oposición</th><th>Estado</th><th>Plan</th><th class="admin-num">Precio</th><th>Renueva / vence</th><th>Cliente desde</th><th>Activo (7d)</th></tr></thead>
      <tbody>${filas || `<tr><td colspan="8"><p class="admin-vacio">Sin clientes que coincidan.</p></td></tr>`}</tbody>
    </table></div>
    ${paginacionHtml(d, "clientes", "i")}`;

  cont.querySelectorAll("[data-uid]").forEach((fila) => {
    const abrir = () => abrirUsuario(fila.dataset.uid);
    fila.addEventListener("click", abrir);
    fila.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); } });
  });
  wirePaginacion(cont, "i", (delta) => { paginaIngresos += delta; cargarIngresos(); });
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
        <select class="age-input" id="nu-oposicion"><option value="AGE">AGE</option><option value="GACE">GACE</option><option value="AUXILIAR">Auxiliar</option><option value="METRO">Metro</option></select>
      </div>
    </div>
    <label class="admin-rol-check" style="margin-top:12px;"><input type="checkbox" id="nu-verificado"> <span>Marcar email como verificado</span></label>
    <label class="admin-rol-check"><input type="checkbox" id="nu-admin"> <span>Hacer administrador total</span></label>
    <p class="admin-dato" style="margin-top:8px;"><strong>Roles (acceso parcial, si no es admin):</strong></p>
    ${["temario", "reportes", "usuarios"].map((p) => `
      <label class="admin-rol-check"><input type="checkbox" class="nu-permiso" value="${p}"> <span>${p === "temario" ? "Temario y preguntas" : p === "reportes" ? "Reportes" : "Usuarios y planes"}</span></label>`).join("")}
    <button class="age-btn age-btn-primary" id="nu-crear" style="margin-top:14px;">Crear usuario</button>`);
  document.getElementById("nu-crear").addEventListener("click", async () => {
    const elEmail = document.getElementById("nu-email");
    const elPass = document.getElementById("nu-pass");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(elEmail.value.trim())) { toast("Email no válido.", "error"); elEmail.focus(); return; }
    if (elPass.value.length < 6) { toast("La contraseña debe tener al menos 6 caracteres.", "error"); elPass.focus(); return; }
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
  const totalPaginas = Math.max(1, Math.ceil((d.total || 0) / (d.por_pagina || 20)));
  const flechaUso = ordenUsuarios === "uso" ? " ▼" : "";
  const tarjetaAnadir = _permisos.admin ? `
    <button type="button" class="u-card u-card-anadir" id="u-anadir">
      <span class="u-card-anadir-ico">${icono("mas", 22)}</span>
      <span>Añadir usuario</span>
    </button>` : "";
  cont.innerHTML = `
    <div class="u-grid-cab">
      <span>${d.total} usuario${d.total === 1 ? "" : "s"}</span>
      <button class="admin-orden-btn" id="u-orden-uso" title="Ordenar por mayor uso">Ordenar por uso${flechaUso}</button>
    </div>
    <div class="u-grid">${(d.usuarios || []).map(tarjetaUsuario).join("") || '<p class="admin-vacio">Sin usuarios.</p>'}${tarjetaAnadir}</div>
    <div class="admin-paginacion">
      <button class="age-btn age-btn-outline admin-mini" id="u-prev" ${paginaUsuarios <= 1 ? "disabled" : ""}>◀ Anterior</button>
      <span>Página ${d.pagina} de ${totalPaginas} · ${d.total} usuarios</span>
      <button class="age-btn age-btn-outline admin-mini" id="u-next" ${paginaUsuarios >= totalPaginas ? "disabled" : ""}>Siguiente ▶</button>
    </div>`;
  cont.querySelectorAll(".u-card[data-uid]").forEach((card) => card.addEventListener("click", (e) => {
    if (e.target.closest("[data-eliminar]")) return;
    abrirUsuario(card.dataset.uid);
  }));
  cont.querySelector("#u-anadir")?.addEventListener("click", modalCrearUsuario);
  cont.querySelectorAll("[data-eliminar]").forEach((btn) => btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const email = btn.dataset.email;
    if (!confirm(`Vas a ELIMINAR por completo la cuenta de ${email}. Es IRREVERSIBLE (se borran todos sus datos y su suscripción). ¿Continuar?`)) return;
    if (!confirm("Confirma otra vez: esta acción no se puede deshacer.")) return;
    const r = await api("DELETE", `/admin/api/usuarios/${btn.dataset.eliminar}`);
    if (r) { toast("Cuenta eliminada."); cargarUsuarios(); }
  }));
  cont.querySelector("#u-prev")?.addEventListener("click", () => { paginaUsuarios--; cargarUsuarios(); });
  cont.querySelector("#u-next")?.addEventListener("click", () => { paginaUsuarios++; cargarUsuarios(); });
  cont.querySelector("#u-orden-uso")?.addEventListener("click", () => {
    ordenUsuarios = ordenUsuarios === "uso" ? "" : "uso";
    paginaUsuarios = 1;
    cargarUsuarios();
  });
}

function tarjetaUsuario(u) {
  const inicial = (u.nombre || u.email || "?").trim().charAt(0).toUpperCase() || "?";
  const pct = u.uso_pct || 0;
  const cls = pct >= 100 ? "u-card-uso-alto" : (pct >= 80 ? "u-card-uso-medio" : "");
  const usoTitulo = u.uso_tool ? `${u.uso_tool} · ${pct}% de su cupo` : "Sin uso este periodo";
  const oposiciones = (u.oposiciones_activas || []).map(escapeHtml).join(", ") || "Sin oposición activa";
  return `
    <div class="u-card" data-uid="${escapeHtml(u.uid)}">
      <div class="u-card-cab">
        <div class="u-card-avatar">${escapeHtml(inicial)}</div>
        <div class="u-card-id">
          <h3 class="u-card-nombre" title="${escapeHtml(u.nombre || u.email || "")}">${escapeHtml(u.nombre || u.email || "(sin email)")}</h3>
          <p class="u-card-email" title="${escapeHtml(u.email || "")}">${escapeHtml(u.email || "(sin email)")}</p>
        </div>
        ${fichaPlanBadge(u.plan, u.en_prueba)}
      </div>
      <div class="u-card-fila"><span class="u-card-fila-ico">${icono("diana", 15)}</span><span class="u-card-fila-lbl">${oposiciones}</span></div>
      <div class="u-card-uso">
        <div class="u-card-uso-cab"><span>Uso${u.uso_tool ? " · " + escapeHtml(u.uso_tool) : ""}</span><span title="${escapeHtml(usoTitulo)}">${pct}%</span></div>
        <div class="u-card-uso-barra"><span class="u-card-uso-relleno ${cls}" style="width:${Math.min(100, pct)}%"></span></div>
      </div>
      <div class="u-card-pie">
        <span class="u-card-actividad">Últ. actividad: ${fechaCorta(u.ultima_actividad)}</span>
        <div class="u-card-acciones">
          <button type="button" class="u-card-btn" title="Ver ficha">${icono("lapiz", 15)}</button>
          ${_permisos.admin ? `<button type="button" class="u-card-btn u-card-btn-peligro" data-eliminar="${escapeHtml(u.uid)}" data-email="${escapeHtml(u.email || "")}" title="Eliminar cuenta">${icono("papelera", 15)}</button>` : ""}
        </div>
      </div>
    </div>`;
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
// "2026-07-29" -> "29/07". Etiqueta corta para las barras y el detalle del
// histórico diario de gasto en IA (coste_ia_historico_diario).
function diaLegible(d) {
  const p = (d || "").split("-");
  return p.length === 3 ? `${p[2]}/${p[1]}` : (d || "");
}

// modo: "mes" (coste_ia_historico) o "dia" (coste_ia_historico_diario) --
// mismo componente visual para las dos vistas del gasto en IA, solo cambia
// qué campo de cada punto usar y cuántas barras caben cómodas.
function fichaCosteBarras(hist, modo = "mes") {
  if (!hist || !hist.length) return '<p class="ficha-vacio">Sin consumo de IA todavía.</p>';
  const clave = modo === "dia" ? "dia" : "mes";
  const etiqueta = modo === "dia" ? diaLegible : mesLegible;
  const barras = hist.slice(modo === "dia" ? -14 : -12);
  const max = Math.max(...barras.map((h) => h.coste)) || 1;
  return `<div class="ficha-barras" role="group" aria-label="Gasto de IA por ${modo === "dia" ? "día" : "mes"}">${barras.map((h) => {
    const alt = h.coste > 0 ? Math.max(8, Math.round((h.coste / max) * 100)) : 3;
    const tip = `${etiqueta(h[clave])}: ${fichaEuros(h.coste)} · ${(h.tokens || 0).toLocaleString("es")} tokens · ${h.llamadas || 0} llamadas`;
    return `<button type="button" class="ficha-barra-col" data-clave="${escapeHtml(h[clave])}" title="${tip}"><div class="ficha-barra-wrap"><div class="ficha-barra" style="height:${alt}%"></div></div><span class="ficha-barra-lbl">${escapeHtml(etiqueta(h[clave]))}</span></button>`;
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

// La ficha de usuario se organiza en pestañas (antes era todo un único
// scroll largo con 3 <details> plegables al final -- "caótico" según el
// dueño). vistaFicha/modoCosteFicha persisten entre aperturas, mismo
// patrón que vistaReportes/vistaBoe.
let vistaFicha = "resumen";
let modoCosteFicha = "mes";

async function abrirUsuario(uid) {
  abrirModal(`<p class="admin-cargando">Cargando ficha…</p>`);
  const u = await apiGet(`/admin/api/usuarios/${uid}`);
  if (!u) { cerrarModal(); return; }
  pintarFicha(u);
}

function pintarFicha(u) {
  const inicial = (u.nombre || u.email || "?").trim().charAt(0).toUpperCase() || "?";
  const pestanas = [
    { id: "resumen", label: "Resumen" },
    { id: "gasto", label: "Uso y gasto" },
    { id: "soporte", label: "Soporte" },
  ];
  if (_permisos.admin) pestanas.push({ id: "admin", label: "Administración" });
  if (!pestanas.some((p) => p.id === vistaFicha)) vistaFicha = "resumen";

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
        <div class="ficha-kpi"><span class="ficha-kpi-num">${(u.rendimiento || {}).porcentaje != null ? u.rendimiento.porcentaje + "%" : "–"}</span><span class="ficha-kpi-lbl">Acierto global</span></div>
      </div>

      <div class="ficha-selector">${segmentoHtml(pestanas.map((p) => ({ id: `fv-${p.id}`, label: p.label, activo: vistaFicha === p.id })))}</div>
      <div id="ficha-cuerpo">${fichaVistaHtml(vistaFicha, u)}</div>
    </div>`);

  document.getElementById("up-copiar-uid").addEventListener("click", () => {
    navigator.clipboard?.writeText(u.uid).then(() => toast("UID copiado.")).catch(() => toast("No se pudo copiar.", "error"));
  });
  pestanas.forEach((p) => {
    document.getElementById(`fv-${p.id}`).addEventListener("click", () => { vistaFicha = p.id; pintarFicha(u); });
  });
  wireFichaVista(vistaFicha, u);
}

function fichaVistaHtml(vista, u) {
  const c = u.contenido_creado || {};
  const r = u.rendimiento || {};
  const oposActivas = u.oposiciones_activas || [];

  if (vista === "resumen") {
    const override = u.admin_override
      ? `<div class="admin-aviso"><strong>Último cambio de soporte:</strong> ${escapeHtml(u.admin_override.cambio || "")} — ${escapeHtml(u.admin_override.motivo || "sin motivo")} (${escapeHtml(fechaCorta(u.admin_override.fecha))})</div>`
      : "";
    return `
      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("usuario", 17)}</span><h3>Datos de la cuenta</h3></div>
        <dl class="ficha-datos">
          <div><dt>Plan</dt><dd>${escapeHtml(u.plan)}${oposActivas.length ? " · " + oposActivas.map(escapeHtml).join(", ") : ""}</dd></div>
          <div><dt>Alta</dt><dd>${escapeHtml(fechaCorta(u.fecha_creacion))}</dd></div>
          <div><dt>Última actividad</dt><dd>${escapeHtml(fechaCorta(u.ultima_actividad))}</dd></div>
          <div><dt>Rendimiento</dt><dd>${(r.aciertos || 0)} aciertos · ${(r.fallos || 0)} fallos · ${(r.blancos || 0)} blancos</dd></div>
          <div><dt>Apellidos</dt><dd>${u.apellidos ? escapeHtml(u.apellidos) : "–"}</dd></div>
          <div><dt>Teléfono</dt><dd>${u.telefono ? escapeHtml(u.telefono) : "–"}</dd></div>
          <div><dt>Dirección</dt><dd>${u.direccion ? escapeHtml(u.direccion) : "–"}</dd></div>
        </dl>
        ${override}
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
      </div>`;
  }

  if (vista === "gasto") {
    const hist = modoCosteFicha === "dia" ? (u.coste_ia_historico_diario || []) : (u.coste_ia_historico || []);
    const clave = modoCosteFicha === "dia" ? "dia" : "mes";
    const etiqueta = modoCosteFicha === "dia" ? diaLegible : mesLegible;
    return `
      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("grafico", 17)}</span><h3>Uso de herramientas (periodo actual)</h3></div>
        ${((u.uso_herramientas || {}).filas || []).map(fichaUsoFila).join("")}
        <p class="ficha-uso-nota">Consumo frente al límite del plan de este usuario. El Test Personalizado se mide en preguntas. Si alguna barra se pone en rojo, está apurando su cupo.</p>
      </div>
      <div class="ficha-panel ficha-coste">
        <div class="ficha-panel-cab-fila">
          <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("robot", 17)}</span><h3>Gasto en IA</h3></div>
          ${_permisos.admin ? segmentoHtml([
            { id: "fc-mes", label: "Por mes", activo: modoCosteFicha === "mes" },
            { id: "fc-dia", label: "Por día", activo: modoCosteFicha === "dia" },
          ]) : ""}
        </div>
        ${_permisos.admin ? `
        <div class="ficha-coste-cifras">
          <div class="ficha-coste-grande"><span class="ficha-coste-num">${fichaEuros(u.coste_ia_mes)}</span><span class="ficha-coste-lbl">este mes</span></div>
          <div class="ficha-coste-sec">
            <div><strong>${fichaEuros(u.coste_ia_total)}</strong><span>histórico</span></div>
            <div><strong>${(u.tokens_ia_total || 0).toLocaleString("es")}</strong><span>tokens</span></div>
          </div>
        </div>
        ${fichaCosteBarras(hist, modoCosteFicha)}
        <p class="ficha-coste-detalle" id="up-coste-detalle">${hist.length ? `Toca una barra para ver el detalle de ese ${modoCosteFicha === "dia" ? "día" : "mes"}.` : ""}</p>
        ${hist.length ? `
        <details class="ficha-rango">
          <summary>${icono("buscar", 14)} Buscar por rango de ${modoCosteFicha === "dia" ? "días" : "meses"}</summary>
          <div class="ficha-rango-cuerpo">
            <div class="ficha-rango-selects">
              <label>Desde <select id="up-rango-desde" class="age-input">${hist.map((h) => `<option value="${escapeHtml(h[clave])}">${etiqueta(h[clave])}</option>`).join("")}</select></label>
              <label>Hasta <select id="up-rango-hasta" class="age-input">${hist.map((h) => `<option value="${escapeHtml(h[clave])}">${etiqueta(h[clave])}</option>`).join("")}</select></label>
            </div>
            <div class="ficha-rango-res" id="up-rango-res"></div>
          </div>
        </details>` : ""}` : `<p class="ficha-vacio">Solo visible para administradores totales.</p>`}
      </div>`;
  }

  if (vista === "soporte") {
    return `
      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("tarjeta", 17)}</span><h3>Cambiar plan</h3></div>
        <div class="admin-form-fila">
          <select id="up-plan" class="age-input"><option value="gratis">Gratis</option><option value="basico">Básico</option><option value="premium">Premium</option></select>
          <select id="up-oposicion" class="age-input"><option value="AGE">AGE</option><option value="GACE">GACE</option><option value="AUXILIAR">Auxiliar</option><option value="METRO">Metro</option></select>
        </div>
        <input id="up-motivo" class="age-input" placeholder="Motivo (queda registrado)" style="margin-top:8px;">
        <button class="age-btn age-btn-primary" id="up-guardar" style="margin-top:10px;">Cambiar plan</button>
      </div>
      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("arena", 17)}</span><h3>Prueba gratuita Premium</h3></div>
        <p class="ficha-prueba-estado">${u.en_prueba
          ? `En prueba en alguna oposición hasta el <strong>${escapeHtml(fechaCorta(u.prueba_fin))}</strong>.`
          : (u.prueba_fin ? `Su última prueba terminó el ${escapeHtml(fechaCorta(u.prueba_fin))}.` : "Nunca ha tenido una prueba.")}</p>
        <p class="ficha-prueba-nota"><small>Cada oposición tiene su propia prueba. Esto otorga/alarga la de la oposición seleccionada arriba (Cambiar plan).</small></p>
        <div class="admin-form-fila">
          <input id="up-prueba-dias" class="age-input" type="number" min="1" max="90" value="7" style="max-width:100px;">
          <button class="age-btn age-btn-outline admin-mini" id="up-prueba-otorgar">Otorgar/alargar prueba</button>
        </div>
      </div>
      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("lapiz", 17)}</span><h3>Notas internas</h3></div>
        <div id="up-notas-lista" class="ficha-notas"></div>
        <textarea class="age-input" id="up-nota-nueva" rows="2" placeholder="Escribe una nota nueva…"></textarea>
        <button class="age-btn age-btn-primary admin-mini" id="up-nota-anadir" style="margin-top:6px;">+ Añadir nota</button>
      </div>
      <div class="ficha-panel">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("herramienta", 17)}</span><h3>Acciones de soporte</h3></div>
        <div class="ficha-soporte-acciones">
          <button class="age-btn admin-mini ficha-btn-soporte" id="up-racha">${icono("fuego", 15)} Resetear racha</button>
          <button class="age-btn admin-mini ficha-btn-soporte" id="up-limites">${icono("actualizar", 15)} Resetear límites de uso</button>
          <button class="age-btn admin-mini ficha-btn-soporte" id="up-reset-pass">${icono("llave", 15)} Enlace de contraseña</button>
          ${u.email_verificado ? "" : `<button class="age-btn admin-mini ficha-btn-soporte" id="up-verif">${icono("correo", 15)} Enlace de verificación</button>`}
        </div>
        <div id="up-enlace-caja"></div>
      </div>`;
  }

  if (vista === "admin") {
    return `
      <div class="ficha-panel ficha-panel-peligro">
        <div class="ficha-panel-cab"><span class="ficha-panel-ico">${icono("candado", 17)}</span><h3>Roles y administración</h3></div>
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
      </div>`;
  }

  return "";
}

function wireFichaVista(vista, u) {
  if (vista === "gasto") {
    document.getElementById("fc-mes")?.addEventListener("click", () => { modoCosteFicha = "mes"; pintarFicha(u); });
    document.getElementById("fc-dia")?.addEventListener("click", () => { modoCosteFicha = "dia"; pintarFicha(u); });
    const hist = modoCosteFicha === "dia" ? (u.coste_ia_historico_diario || []) : (u.coste_ia_historico || []);
    const clave = modoCosteFicha === "dia" ? "dia" : "mes";
    const etiqueta = modoCosteFicha === "dia" ? diaLegible : mesLegible;
    // Las barras se deslizan en horizontal en vez de apretarse todas en el
    // ancho disponible (ver .ficha-barras en style.css) -- se arranca ya
    // desplazado al final para que el día/mes más reciente se vea sin
    // tener que arrastrar primero.
    const barrasEl = document.querySelector(".ficha-barras");
    if (barrasEl) barrasEl.scrollLeft = barrasEl.scrollWidth;
    const detalle = document.getElementById("up-coste-detalle");
    document.querySelectorAll(".ficha-barra-col").forEach((b) => b.addEventListener("click", () => {
      const h = hist.find((x) => String(x[clave]) === b.dataset.clave);
      if (h && detalle) detalle.innerHTML = `<strong>${etiqueta(h[clave])}:</strong> ${fichaEuros(h.coste)} · ${(h.tokens || 0).toLocaleString("es")} tokens (${(h.tokens_in || 0).toLocaleString("es")} entrada / ${(h.tokens_out || 0).toLocaleString("es")} salida) · ${h.llamadas || 0} llamadas`;
      document.querySelectorAll(".ficha-barra-col").forEach((x) => x.classList.toggle("activa", x === b));
    }));
    const rangoDesde = document.getElementById("up-rango-desde");
    const rangoHasta = document.getElementById("up-rango-hasta");
    const calcularRango = () => {
      if (!rangoDesde || !rangoHasta) return;
      let a = rangoDesde.value, b = rangoHasta.value;
      if (a > b) { [a, b] = [b, a]; }
      const sel = hist.filter((h) => h[clave] >= a && h[clave] <= b);
      const coste = sel.reduce((s, h) => s + (h.coste || 0), 0);
      const tokens = sel.reduce((s, h) => s + (h.tokens || 0), 0);
      const llamadas = sel.reduce((s, h) => s + (h.llamadas || 0), 0);
      document.getElementById("up-rango-res").innerHTML =
        `<strong>${etiqueta(a)} → ${etiqueta(b)}:</strong> ${fichaEuros(coste)} · ${tokens.toLocaleString("es")} tokens · ${llamadas.toLocaleString("es")} llamadas`;
    };
    if (rangoDesde && rangoHasta) {
      rangoDesde.value = hist.length ? hist[0][clave] : "";
      rangoHasta.value = hist.length ? hist[hist.length - 1][clave] : "";
      rangoDesde.addEventListener("change", calcularRango);
      rangoHasta.addEventListener("change", calcularRango);
      calcularRango();
    }
    return;
  }

  if (vista === "soporte") {
    document.getElementById("up-plan").value = u.plan;
    document.getElementById("up-oposicion").value = oposicionActual();
    document.getElementById("up-guardar").addEventListener("click", async () => {
      const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/plan`, {
        plan: document.getElementById("up-plan").value,
        oposicion: document.getElementById("up-oposicion").value,
        motivo: document.getElementById("up-motivo").value,
      });
      if (r) { toast("Plan actualizado."); cerrarModal(); cargarUsuarios(); }
    });
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
      const oposicion = document.getElementById("up-oposicion").value;
      const r = await api("PATCH", `/admin/api/usuarios/${u.uid}/prueba`, { dias, oposicion });
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
    return;
  }

  if (vista === "admin") {
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
let paginaReportes = 1;
async function renderReportes() {
  const panel = document.getElementById("panel-reportes");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <div class="admin-reportes-selector">
        ${segmentoHtml([
          { id: "r-vista-preguntas", label: "Preguntas reportadas", activo: vistaReportes === "preguntas", tieneBadge: true, badge: _reportesPreguntasPendientesCache },
          { id: "r-vista-soporte", label: "Mensajes de soporte", activo: vistaReportes === "soporte", tieneBadge: true, badge: _reportesSoportePendientesCache },
        ])}
      </div>
      <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;margin-top:12px;">Estado
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
  sel.addEventListener("change", () => { estadoReportes = sel.value; paginaReportes = 1; cargarVistaActual(); });
  panel.querySelector("#r-vista-preguntas").addEventListener("click", () => { vistaReportes = "preguntas"; paginaReportes = 1; renderReportes(); });
  panel.querySelector("#r-vista-soporte").addEventListener("click", () => { vistaReportes = "soporte"; paginaReportes = 1; renderReportes(); });
  cargarVistaActual();
}

async function cargarReportes() {
  const cont = document.getElementById("reportes-lista");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/reportes?estado=${estadoReportes}&pagina=${paginaReportes}`);
  if (!d) return;
  // d.total (no la longitud de esta página) -- el backend ya filtra por
  // "pendiente" en la consulta, así que es el recuento real, no solo el de
  // la página actual. El badge combinado suma esto con el de soporte (no
  // se sustituye sin más por d.total, o se perdería de vista el otro).
  if (estadoReportes === "pendiente") {
    _reportesPreguntasPendientesCache = d.total || 0;
    actualizarBadgeReportes(_reportesPreguntasPendientesCache + _reportesSoportePendientesCache);
    _actualizarBadgesReportesDesglose();
  }
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
        ${r.uid && puedeVer("usuarios") ? `<button class="age-btn age-btn-outline admin-mini" data-ver-perfil="${escapeHtml(r.uid)}">${icono("usuario", 13)} Ver perfil</button>` : ""}
      </div>
    </div>`;
  }).join("") + paginacionHtml(d, "reportes", "rep-pag");
  cont.querySelectorAll("[data-revisado]").forEach((b) => b.addEventListener("click", () => cambiarEstadoReporte(b.dataset.revisado, "revisado")));
  cont.querySelectorAll("[data-descartar]").forEach((b) => b.addEventListener("click", () => cambiarEstadoReporte(b.dataset.descartar, "descartado")));
  cont.querySelectorAll("[data-editar-preg]").forEach((b) => b.addEventListener("click", () => buscarYEditarPregunta(b.dataset.editarPreg)));
  cont.querySelectorAll("[data-ver-perfil]").forEach((b) => b.addEventListener("click", () => abrirUsuario(b.dataset.verPerfil)));
  wirePaginacion(cont, "rep-pag", (delta) => { paginaReportes += delta; cargarReportes(); });
}

async function cambiarEstadoReporte(id, estado) {
  const r = await api("PATCH", `/admin/api/reportes/${id}`, { estado });
  if (r) { toast(estado === "revisado" ? "Reporte marcado como revisado." : "Reporte descartado."); cargarReportes(); }
}

// ===== Calidad IA: auto-rechazos de la verificación automática (ver
// errores_generacion.py, fuente="auto_verificacion") -- a diferencia de
// Reportes (fuente="usuario_admin"), esto no lo escribe ningún usuario: es
// la propia verificación descartando una pregunta recién redactada por la
// IA, antes de que llegue a nadie (15/08/2026, a petición del usuario tras
// ver en los logs de producción varios rechazos "desfase_legal" seguidos
// en un mismo bloque). Fase 1 (solo lectura/triaje, ver el docstring de
// errores_generacion.py): el análisis agregado automático y el ajuste del
// prompt de generación quedan para más adelante.
let filtroTipoErroresIA = "todos";
let filtroResueltoErroresIA = "pendiente";
let filtroOposicionErroresIA = "todas";
let paginaErroresIA = 1;
let busquedaErroresIA = "";

const ETIQUETA_TIPO_ERROR_IA = {
  desfase_legal: "Desfase legal", respuesta_incorrecta: "Respuesta incorrecta",
  distractor_implausible: "Distractor poco creíble", ambiguedad: "Ambigüedad", otro: "Otro",
};

async function renderCalidadIA() {
  const panel = document.getElementById("panel-calidad");
  panel.innerHTML = `
    <div class="age-card admin-filtros">
      <p class="admin-calidad-intro">Preguntas que la propia verificación automática ha descartado durante la generación de un test, antes de llegar a ningún usuario -- para ver si un tema falla por casualidad o de forma repetida, y por qué motivo exacto.</p>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;">
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;">Estado
          <select id="ia-resuelto" class="age-input" style="max-width:160px;">
            <option value="pendiente">Sin revisar</option>
            <option value="resuelto">Revisados</option>
            <option value="todos">Todos</option>
          </select>
        </label>
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;">Tipo
          <select id="ia-tipo" class="age-input" style="max-width:200px;">
            <option value="todos">Todos</option>
            ${Object.entries(ETIQUETA_TIPO_ERROR_IA).map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}
          </select>
        </label>
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;">Oposición
          <select id="ia-oposicion" class="age-input" style="max-width:160px;">
            <option value="todas">Todas</option>
            <option value="AGE">AGE</option>
            <option value="GACE">GACE</option>
            <option value="AUXILIAR">Auxiliar</option>
          </select>
        </label>
        <input type="search" id="ia-buscar" class="age-input" placeholder="Buscar por tema o motivo…" style="flex:1;min-width:200px;">
        <button type="button" id="ia-exportar" class="age-btn age-btn-outline admin-mini">${icono("descargar", 14)} Exportar CSV</button>
      </div>
    </div>
    <div class="age-card" id="ia-resumen"></div>
    <div class="age-card"><div id="ia-lista"><p class="admin-cargando">Cargando…</p></div></div>`;

  const selResuelto = panel.querySelector("#ia-resuelto");
  const selTipo = panel.querySelector("#ia-tipo");
  const selOposicion = panel.querySelector("#ia-oposicion");
  const inputBuscar = panel.querySelector("#ia-buscar");
  const btnExportar = panel.querySelector("#ia-exportar");
  selResuelto.value = filtroResueltoErroresIA;
  selTipo.value = filtroTipoErroresIA;
  selOposicion.value = filtroOposicionErroresIA;
  inputBuscar.value = busquedaErroresIA;

  selResuelto.addEventListener("change", () => { filtroResueltoErroresIA = selResuelto.value; paginaErroresIA = 1; cargarErroresIA(); });
  selTipo.addEventListener("change", () => { filtroTipoErroresIA = selTipo.value; paginaErroresIA = 1; cargarErroresIA(); });
  selOposicion.addEventListener("change", () => { filtroOposicionErroresIA = selOposicion.value; paginaErroresIA = 1; cargarErroresIA(); });
  // Con debounce (350ms): sin esto, cada tecla pulsada dispara su propia
  // petición al backend, la mayoría descartadas antes de llegar a pintarse.
  let debounceBuscarIA;
  inputBuscar.addEventListener("input", () => {
    clearTimeout(debounceBuscarIA);
    debounceBuscarIA = setTimeout(() => { busquedaErroresIA = inputBuscar.value.trim(); paginaErroresIA = 1; cargarErroresIA(); }, 350);
  });
  btnExportar.addEventListener("click", () => {
    const params = new URLSearchParams({ resuelto: filtroResueltoErroresIA, tipo_error: filtroTipoErroresIA, oposicion: filtroOposicionErroresIA });
    if (busquedaErroresIA) params.set("q", busquedaErroresIA);
    descargarCSV(`/admin/api/errores-ia/export?${params}`, "calidad_ia.csv");
  });

  cargarErroresIA();
}

async function cargarErroresIA() {
  const cont = document.getElementById("ia-lista");
  const resumenCont = document.getElementById("ia-resumen");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const params = new URLSearchParams({ resuelto: filtroResueltoErroresIA, tipo_error: filtroTipoErroresIA, oposicion: filtroOposicionErroresIA, pagina: paginaErroresIA });
  if (busquedaErroresIA) params.set("q", busquedaErroresIA);
  const d = await apiGet(`/admin/api/errores-ia?${params}`);
  if (!d) return;

  if (resumenCont) {
    const porTipo = d.resumen?.por_tipo || {};
    const totalTodos = Object.values(porTipo).reduce((s, n) => s + n, 0);
    if (!totalTodos) {
      resumenCont.innerHTML = `<p class="admin-vacio">Sin auto-rechazos registrados todavía. ${icono("check", 14)}</p>`;
    } else {
      const chipsTipo = Object.entries(porTipo).sort((a, b) => b[1] - a[1])
        .map(([tipo, n]) => `<span class="admin-calidad-chip">${escapeHtml(ETIQUETA_TIPO_ERROR_IA[tipo] || tipo)}: <strong>${n}</strong></span>`).join("");
      const topTemas = d.resumen?.top_temas || [];
      const chipsTemas = topTemas.map((t) => `<button type="button" class="admin-calidad-chip admin-calidad-chip-tema" data-buscar-tema="${escapeHtml(t.tema_id)}" title="Filtrar por este tema">${escapeHtml(t.tema_id)}: <strong>${t.total}</strong></button>`).join("");
      resumenCont.innerHTML = `
        <p class="admin-calidad-resumen-titulo">${totalTodos} en total (sin aplicar los filtros de arriba) -- por tipo:</p>
        <div class="admin-calidad-chips">${chipsTipo}</div>
        ${topTemas.length ? `<details class="ficha-rango"><summary>Temas con más rechazos</summary><div class="admin-calidad-chips" style="margin-top:10px;">${chipsTemas}</div></details>` : ""}
      `;
      resumenCont.querySelectorAll("[data-buscar-tema]").forEach((b) => b.addEventListener("click", () => {
        busquedaErroresIA = b.dataset.buscarTema;
        paginaErroresIA = 1;
        renderCalidadIA();
      }));
    }
  }

  if (!(d.entradas || []).length) {
    cont.innerHTML = `<p class="admin-vacio">Nada que revisar con estos filtros. ${icono("check", 14)}</p>`;
    return;
  }
  cont.innerHTML = d.entradas.map((e) => `
    <div class="admin-reporte">
      <div class="admin-reporte-cab">
        <span class="admin-calidad-tipo">${escapeHtml(ETIQUETA_TIPO_ERROR_IA[e.tipo_error] || e.tipo_error)}</span>
        <span class="admin-reporte-meta">${escapeHtml(e.tema_id)} · intento ${e.intento_numero ?? "-"} · ${escapeHtml(fechaCorta(e.timestamp))}</span>
      </div>
      ${e.pregunta_texto ? `<p class="admin-reporte-preg">${escapeHtml(e.pregunta_texto)}</p>` : ""}
      <p class="admin-reporte-motivo"><strong>Motivo del rechazo:</strong> ${escapeHtml(e.detalle || "(sin detalle)")}</p>
      <div class="admin-reporte-acciones">
        ${e.resuelto
          ? `<button class="age-btn age-btn-outline admin-mini" data-reabrir="${escapeHtml(e.id)}">Marcar sin revisar</button>`
          : `<button class="age-btn age-btn-primary admin-mini" data-revisado="${escapeHtml(e.id)}">Marcar revisado</button>`}
      </div>
    </div>`).join("") + paginacionHtml(d, "resultados", "ia-pag");

  cont.querySelectorAll("[data-revisado]").forEach((b) => b.addEventListener("click", () => marcarErrorIA(b.dataset.revisado, true)));
  cont.querySelectorAll("[data-reabrir]").forEach((b) => b.addEventListener("click", () => marcarErrorIA(b.dataset.reabrir, false)));
  wirePaginacion(cont, "ia-pag", (delta) => { paginaErroresIA += delta; cargarErroresIA(); });
}

async function marcarErrorIA(id, resuelto) {
  const r = await api("PATCH", `/admin/api/errores-ia/${id}`, { resuelto });
  if (r) { toast(resuelto ? "Marcado como revisado." : "Marcado como sin revisar."); cargarErroresIA(); }
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
  // Checkboxes, no un desplegable: una misma resolución (p. ej. un
  // llamamiento extraordinario) puede afectar a varias oposiciones a la
  // vez -- se publica una sola vez y llega a las páginas/usuarios de
  // todas las marcadas.
  const oposicionesMarcadas = v.oposiciones || (v.oposicion ? [v.oposicion] : []);
  const checkboxesOposicion = [["AGE", "AGE"], ["GACE", "GACE"], ["AUXILIAR", "Auxiliar"]]
    .map(([val, etiqueta]) => `
        <label style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;margin-right:16px;">
          <input type="checkbox" class="${prefix}-oposicion" value="${val}" ${oposicionesMarcadas.includes(val) ? "checked" : ""} />
          ${etiqueta}
        </label>`).join("");
  return `
    <div style="display:grid;gap:10px;grid-template-columns:1fr 1fr;">
      <div>
        <span style="font-size:13px;font-weight:600;display:block;margin-bottom:6px;">Oposiciones afectadas</span>
        ${checkboxesOposicion}
      </div>
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
  const oposiciones = Array.from(document.querySelectorAll(`.${prefix}-oposicion:checked`)).map((c) => c.value);
  return {
    oposiciones,
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
    <div class="age-card boe-hero">
      <h3>Filtros de vigilancia</h3>
      <p class="admin-reporte-meta">Supervisión automática de cambios legislativos y publicaciones oficiales.</p>
      <div class="boe-hero-botones">
        <button type="button" class="boe-hero-btn ${vistaBoe === "cambios" ? "activo" : ""}" id="boe-vista-cambios">${icono("documento", 18)} Cambios de temario</button>
        <button type="button" class="boe-hero-btn ${vistaBoe === "avisos" ? "activo" : ""}" id="boe-vista-avisos">${icono("megafono", 18)} Avisos oficiales</button>
      </div>
    </div>

    <div class="boe-stat">
      <div class="boe-stat-cab"><span>Alertas pendientes</span><span class="boe-stat-ico">${icono("campana", 18)}</span></div>
      <div class="boe-stat-num" id="boe-stat-num">${_cambiosPendientesCache + _avisosPendientesCache}</div>
      <div class="boe-stat-sub" id="boe-stat-sub">${_cambiosPendientesCache} cambio${_cambiosPendientesCache === 1 ? "" : "s"} de temario · ${_avisosPendientesCache} aviso${_avisosPendientesCache === 1 ? "" : "s"} oficial${_avisosPendientesCache === 1 ? "" : "es"}</div>
      <div class="boe-stat-barra" id="boe-stat-barra"></div>
    </div>

    <div class="age-card admin-filtros">
      <div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap;align-items:center;">
        <h3 style="margin:0;">Propuestas de actualización</h3>
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
    <div id="boe-lista"><p class="admin-cargando">Cargando…</p></div>`;
  _actualizarStatBoe();
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

// Composición de la tarjeta "Alertas pendientes": nº de cambios de temario +
// avisos oficiales pendientes (cacheados por la última vez que se cargó esa
// lista en estado "pendiente", igual que ya hace el badge de la pestaña).
function _actualizarStatBoe() {
  const num = document.getElementById("boe-stat-num");
  const sub = document.getElementById("boe-stat-sub");
  const barra = document.getElementById("boe-stat-barra");
  if (!num) return;
  const total = _cambiosPendientesCache + _avisosPendientesCache;
  num.textContent = total;
  sub.textContent = `${_cambiosPendientesCache} cambio${_cambiosPendientesCache === 1 ? "" : "s"} de temario · ${_avisosPendientesCache} aviso${_avisosPendientesCache === 1 ? "" : "s"} oficial${_avisosPendientesCache === 1 ? "" : "es"}`;
  barra.innerHTML = total
    ? `<span class="boe-stat-seg boe-stat-seg-cambios" style="width:${(_cambiosPendientesCache / total) * 100}%"></span><span class="boe-stat-seg boe-stat-seg-avisos" style="width:${(_avisosPendientesCache / total) * 100}%"></span>`
    : `<span class="boe-stat-seg boe-stat-seg-avisos" style="width:100%"></span>`;
}

function _diffHtml(texto_eliminar, texto_anadir) {
  return `
    <div class="admin-boe-diff">
      <p class="admin-boe-diff-quita">− ${escapeHtml(texto_eliminar)}</p>
      <p class="admin-boe-diff-pon">+ ${escapeHtml(texto_anadir)}</p>
    </div>`;
}

async function cargarCambiosTemario() {
  const cont = document.getElementById("boe-lista");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/cambios-temario?estado=${estadoBoe}`);
  if (!d) return;
  const pendientes = (d.cambios || []).filter((c) => c.estado === "pendiente").length;
  if (estadoBoe === "pendiente") { _cambiosPendientesCache = pendientes; actualizarBadgeBoe(pendientes + _avisosPendientesCache); _actualizarStatBoe(); }
  if (!(d.cambios || []).length) {
    cont.innerHTML = `<p class="admin-vacio">No hay cambios de temario en este estado. ${icono("check", 14)}</p>`;
    return;
  }
  const clase = (e) => e === "aprobado" ? "admin-estado-revisado" : e === "descartado" ? "admin-estado-descartado" : "admin-estado-pendiente";
  cont.innerHTML = d.cambios.map((c) => `
    <div class="admin-reporte">
      <div class="admin-reporte-cab">
        <span class="admin-reporte-estado ${clase(c.estado)}">${escapeHtml(c.estado)}</span>
        ${c.boe_id ? `<span class="admin-reporte-meta boe-ref">Ref: ${escapeHtml(c.boe_id)}</span>` : ""}
        <span class="admin-reporte-meta">${escapeHtml(c.oposicion || "-")} · ${escapeHtml(c.bloque_id || "")}/${escapeHtml(c.tema_id || "")} · ${escapeHtml(fechaCorta(c.fecha_deteccion))}</span>
      </div>
      <p class="admin-reporte-preg">${escapeHtml(c.ley_nombre || c.resumen)}</p>
      ${c.ley_nombre ? `<p class="admin-reporte-meta">${escapeHtml(c.resumen)}</p>` : ""}
      ${_diffHtml(c.texto_eliminar, c.texto_anadir)}
      ${c.revisado_por_email ? `<p class="admin-reporte-meta boe-revisado">Aplicado por: ${escapeHtml(c.revisado_por_email)} · Fecha: ${escapeHtml(fechaCorta(c.fecha_revision))}</p>` : ""}
      <div class="boe-card-acciones">
        ${c.estado !== "aprobado" ? `<button class="age-btn age-btn-primary" data-aprobar="${escapeHtml(c.id)}">Aprobar cambio</button>` : ""}
        ${c.estado !== "descartado" ? `<button class="age-btn age-btn-outline" data-descartar-cambio="${escapeHtml(c.id)}">Ignorar</button>` : ""}
      </div>
    </div>`).join("");
  cont.querySelectorAll("[data-aprobar]").forEach((b) => b.addEventListener("click", () => cambiarEstadoCambioTemario(b.dataset.aprobar, "aprobado")));
  cont.querySelectorAll("[data-descartar-cambio]").forEach((b) => b.addEventListener("click", () => cambiarEstadoCambioTemario(b.dataset.descartarCambio, "descartado")));
}

async function cambiarEstadoCambioTemario(id, estado) {
  const r = await api("PATCH", `/admin/api/cambios-temario/${id}`, { estado });
  if (r) { toast(estado === "aprobado" ? "Cambio aplicado al temario." : "Propuesta descartada."); cargarCambiosTemario(); }
}

let _cambiosPendientesCache = 0;
let _avisosPendientesCache = 0;
async function cargarAvisosOficiales() {
  const cont = document.getElementById("boe-lista");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/avisos-oficiales?estado=${estadoBoe}`);
  if (!d) return;
  const pendientes = (d.avisos || []).filter((a) => a.estado === "pendiente").length;
  if (estadoBoe === "pendiente") { _avisosPendientesCache = pendientes; actualizarBadgeBoe(pendientes); _actualizarStatBoe(); }
  if (!(d.avisos || []).length) {
    cont.innerHTML = `<p class="admin-vacio">No hay avisos oficiales en este estado. ${icono("check", 14)}</p>`;
    return;
  }
  const clase = (e) => e === "publicado" ? "admin-estado-revisado" : e === "descartado" ? "admin-estado-descartado" : "admin-estado-pendiente";
  cont.innerHTML = d.avisos.map((a) => `
    <div class="admin-reporte">
      <div class="admin-reporte-cab">
        <span class="admin-reporte-estado ${clase(a.estado)}">${escapeHtml(a.estado)}</span>
        <span class="admin-reporte-meta">${escapeHtml((a.oposiciones || []).join(" + ") || "-")} · ${escapeHtml(a.tipo_personalizado || ETIQUETA_TIPO_AVISO_MANUAL[a.tipo] || a.tipo || "")} · ${escapeHtml(fechaCorta(a.fecha_deteccion))}</span>
      </div>
      <p class="admin-reporte-preg">${escapeHtml(a.titulo)}</p>
      ${a.resumen ? `<p class="admin-reporte-motivo">${escapeHtml(a.resumen)}</p>` : ""}
      ${a.url_boe ? `<p class="admin-reporte-meta"><a href="${escapeHtml(a.url_boe)}" target="_blank" rel="noopener">Ver la resolución ↗</a></p>` : ""}
      ${a.revisado_por_email ? `<p class="admin-reporte-meta boe-revisado">Aplicado por: ${escapeHtml(a.revisado_por_email)} · Fecha: ${escapeHtml(fechaCorta(a.fecha_revision))}</p>` : ""}
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
  // Mismo criterio que cargarReportes: el nº real de mensajes en este
  // estado (no solo si la lista está vacía) para no dejar el badge
  // desactualizado -- va antes del "vacío" de abajo a propósito, si no
  // nunca se llegaría a poner a 0.
  if (estadoReportes === "pendiente") {
    _reportesSoportePendientesCache = (d.mensajes || []).length;
    actualizarBadgeReportes(_reportesPreguntasPendientesCache + _reportesSoportePendientesCache);
    _actualizarBadgesReportesDesglose();
  }
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
        ${m.uid && puedeVer("usuarios") ? `<button class="age-btn age-btn-outline admin-mini" data-ver-perfil="${escapeHtml(m.uid)}">${icono("usuario", 13)} Ver perfil</button>` : ""}
      </div>
    </div>`).join("");
  cont.querySelectorAll("[data-ver-perfil]").forEach((b) => b.addEventListener("click", () => abrirUsuario(b.dataset.verPerfil)));
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

let paginaAuditoria = 1;
async function renderAuditoria() {
  const panel = document.getElementById("panel-auditoria");
  panel.innerHTML = `<div class="age-card"><div id="auditoria-lista"><p class="admin-cargando">Cargando…</p></div></div>`;
  await cargarAuditoria();
}
async function cargarAuditoria() {
  const cont = document.getElementById("auditoria-lista");
  if (!cont) return;
  cont.innerHTML = `<p class="admin-cargando">Cargando…</p>`;
  const d = await apiGet(`/admin/api/auditoria?pagina=${paginaAuditoria}`);
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
    <div class="admin-scroll"><table class="admin-tabla"><thead><tr><th>Fecha (UTC)</th><th>Acción</th><th>Sobre</th><th>Admin</th></tr></thead><tbody>${filas}</tbody></table></div>
    ${paginacionHtml(d, "acciones", "aud-pag")}`;
  wirePaginacion(cont, "aud-pag", (delta) => { paginaAuditoria += delta; cargarAuditoria(); });
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
  const b = banner || { activo: false, texto: "", tipo: "info", fuente: "default", animacion: "ninguna" };
  const p = promo || { activo: false, plan: "premium", descuento_pct: 0, duracion_texto: "", fecha_fin: "", stripe_promotion_code: "", mensaje: "", fuente: "default", animacion: "ninguna" };
  // Fuente/animación: mismas claves que FUENTES_AVISO_VALIDAS/ANIMACIONES_AVISO_VALIDAS
  // en blueprints/admin.py y FUENTES_AVISO en frontend/assets/auth.js -- se
  // duplica aquí (en vez de importar auth.js) para no acoplar el bundle del
  // admin a los efectos secundarios que auth.js dispara al cargarse (inyecta
  // banners reales en cualquier página que lo importe).
  const OPCIONES_FUENTE = [
    ["default", "Predeterminada"],
    ["redondeada", "Redondeada"],
    ["elegante", "Elegante"],
    ["impacto", "Llamativa (Impacto)"],
  ];
  const OPCIONES_ANIMACION = [
    ["ninguna", "Ninguna (estático)"],
    ["parpadeo", "Parpadeo suave"],
    ["deslizante", "Deslizante (cinta en movimiento)"],
    ["rebote", "Rebote sutil"],
  ];
  const FUENTES_CSS = {
    redondeada: "'Trebuchet MS', Verdana, sans-serif",
    elegante: "Georgia, 'Times New Roman', serif",
    impacto: "Impact, 'Arial Black', sans-serif",
  };
  const opcionesSelect = (opciones, actual) => opciones.map(([v, lbl]) =>
    `<option value="${v}" ${actual === v ? "selected" : ""}>${escapeHtml(lbl)}</option>`).join("");
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
      <h3>${icono("megafono", 17)} Aviso global del sitio</h3>
      <p class="admin-reporte-meta">Se muestra a todos los usuarios en la parte superior de la web.</p>
      <label class="admin-toggle" style="margin:8px 0;"><input type="checkbox" id="ban-activo" ${b.activo ? "checked" : ""}> <span>Mostrar el aviso</span></label>
      <label>Texto</label>
      <input class="age-input" id="ban-texto" maxlength="300" value="${escapeHtml(b.texto)}" placeholder="Ej. Mantenimiento programado el viernes de 22h a 23h.">
      <div class="admin-form-fila" style="margin-top:10px;">
        <div>
          <label>Tipo</label>
          <select class="age-input" id="ban-tipo">
            <option value="info" ${b.tipo === "info" ? "selected" : ""}>Info (azul)</option>
            <option value="aviso" ${b.tipo === "aviso" ? "selected" : ""}>Aviso (naranja)</option>
            <option value="urgente" ${b.tipo === "urgente" ? "selected" : ""}>Urgente (rojo)</option>
          </select>
        </div>
        <div>
          <label>Letra</label>
          <select class="age-input" id="ban-fuente">${opcionesSelect(OPCIONES_FUENTE, b.fuente)}</select>
        </div>
        <div>
          <label>Animación</label>
          <select class="age-input" id="ban-animacion">${opcionesSelect(OPCIONES_ANIMACION, b.animacion)}</select>
        </div>
      </div>
      <div class="sis-preview">
        <p class="sis-preview-lbl">Vista previa</p>
        <div id="ban-preview"></div>
      </div>
      <button class="age-btn age-btn-primary" id="ban-guardar" style="margin-top:12px;">Guardar aviso</button>
    </div>
    <div class="age-card admin-bloque">
      <h3>${icono("destellos", 17)} Promoción / descuento temporal</h3>
      <p class="admin-reporte-meta">Muestra un banner con cuenta atrás a quien todavía NO tenga el plan elegido (visitantes sin cuenta incluidos). A quien ya lo tenga activo no le sale nada.</p>
      <label class="admin-toggle" style="margin:8px 0;"><input type="checkbox" id="promo-activo" ${p.activo ? "checked" : ""}> <span>Activar promoción</span></label>
      <div class="admin-form-fila">
        <div>
          <label>Plan al que aplica</label>
          <select class="age-input" id="promo-plan">
            <option value="basico" ${p.plan === "basico" ? "selected" : ""}>Básico</option>
            <option value="premium" ${p.plan === "premium" ? "selected" : ""}>Premium</option>
          </select>
        </div>
        <div>
          <label>% de descuento (solo para el texto del aviso)</label>
          <input class="age-input" id="promo-descuento" type="number" min="0" max="100" value="${p.descuento_pct || 0}">
        </div>
      </div>
      <div class="admin-form-fila">
        <div>
          <label>Duración del descuento (texto libre, ej. "2 meses")</label>
          <input class="age-input" id="promo-duracion" maxlength="60" value="${escapeHtml(p.duracion_texto)}" placeholder="Ej. 2 meses">
        </div>
        <div>
          <label>Termina el</label>
          <input class="age-input" id="promo-fecha-fin" type="datetime-local" value="${isoAInputLocal(p.fecha_fin)}">
        </div>
      </div>
      <div class="admin-form-fila">
        <div>
          <label>Letra</label>
          <select class="age-input" id="promo-fuente">${opcionesSelect(OPCIONES_FUENTE, p.fuente)}</select>
        </div>
        <div>
          <label>Animación</label>
          <select class="age-input" id="promo-animacion">${opcionesSelect(OPCIONES_ANIMACION, p.animacion)}</select>
        </div>
      </div>
      <label>Código de promoción de Stripe</label>
      <input class="age-input" id="promo-codigo" maxlength="80" value="${escapeHtml(p.stripe_promotion_code)}" placeholder="Ej. promo_1AbCdE...">
      <p class="admin-reporte-meta">Créalo antes en el Dashboard de Stripe (Productos → Cupones → Código promocional) y pega aquí su ID: al activarlo, se aplica solo al comprar el plan elegido arriba. Si lo dejas vacío, el aviso se muestra igualmente pero sin descuento automático en el pago.</p>
      <label>Mensaje del aviso (opcional, si lo dejas vacío se genera uno automático)</label>
      <input class="age-input" id="promo-mensaje" maxlength="200" value="${escapeHtml(p.mensaje)}" placeholder="Ej. 20% de descuento en Premium durante 2 meses">
      <div class="sis-preview">
        <p class="sis-preview-lbl">Vista previa</p>
        <div id="promo-preview"></div>
      </div>
      <button class="age-btn age-btn-primary" id="promo-guardar" style="margin-top:12px;">Guardar promoción</button>
    </div>`;
  // Vista previa en vivo: reutiliza las clases públicas reales
  // (age-banner-global/age-banner-promo, ya cargadas vía theme.css en el
  // propio admin) para que se vea pixel-a-pixel igual que en la web.
  const aplicarFuenteAnimacion = (elTexto, contenedor, fuente, animacion) => {
    elTexto.style.fontFamily = FUENTES_CSS[fuente] || "";
    elTexto.classList.remove("age-anim-parpadeo", "age-anim-deslizante", "age-anim-rebote");
    contenedor.classList.remove("age-banner-scroll");
    if (animacion && animacion !== "ninguna") {
      elTexto.classList.add(`age-anim-${animacion}`);
      if (animacion === "deslizante") contenedor.classList.add("age-banner-scroll");
    }
  };
  const pintarPreviewBanner = () => {
    const cont = panel.querySelector("#ban-preview");
    if (!cont) return;
    const texto = panel.querySelector("#ban-texto").value.trim() || "Así se verá tu aviso.";
    const tipo = panel.querySelector("#ban-tipo").value;
    cont.innerHTML = `<div class="age-banner-global age-banner-${tipo}"><span class="age-banner-global-texto">${escapeHtml(texto)}</span></div>`;
    aplicarFuenteAnimacion(
      cont.querySelector(".age-banner-global-texto"), cont.querySelector(".age-banner-global"),
      panel.querySelector("#ban-fuente").value, panel.querySelector("#ban-animacion").value
    );
  };
  const pintarPreviewPromo = () => {
    const cont = panel.querySelector("#promo-preview");
    if (!cont) return;
    const nombrePlan = panel.querySelector("#promo-plan").value === "premium" ? "Premium" : "Básico";
    const descuento = parseInt(panel.querySelector("#promo-descuento").value, 10) || 0;
    const duracion = panel.querySelector("#promo-duracion").value.trim();
    const mensaje = panel.querySelector("#promo-mensaje").value.trim()
      || `${descuento}% de descuento en el plan ${nombrePlan}${duracion ? " durante " + duracion : ""}`;
    cont.innerHTML = `<div class="age-banner-promo">
      <span class="age-banner-promo-texto"><span class="age-banner-promo-texto-int">${icono("destellos", 16)} <strong>${escapeHtml(mensaje)}</strong></span></span>
      <span class="age-banner-promo-cuenta">
        <span class="age-banner-promo-chip">02d</span><span class="age-banner-promo-sep">:</span><span class="age-banner-promo-chip">14h</span><span class="age-banner-promo-sep">:</span><span class="age-banner-promo-chip">33m</span><span class="age-banner-promo-sep">:</span><span class="age-banner-promo-chip">10s</span>
      </span>
    </div>`;
    aplicarFuenteAnimacion(
      cont.querySelector(".age-banner-promo-texto-int"), cont.querySelector(".age-banner-promo-texto"),
      panel.querySelector("#promo-fuente").value, panel.querySelector("#promo-animacion").value
    );
  };
  pintarPreviewBanner();
  pintarPreviewPromo();
  ["ban-texto", "ban-tipo", "ban-fuente", "ban-animacion"].forEach((id) => {
    panel.querySelector(`#${id}`).addEventListener("input", pintarPreviewBanner);
  });
  ["promo-plan", "promo-descuento", "promo-duracion", "promo-mensaje", "promo-fuente", "promo-animacion"].forEach((id) => {
    panel.querySelector(`#${id}`).addEventListener("input", pintarPreviewPromo);
  });

  panel.querySelector("#ban-guardar").addEventListener("click", async () => {
    const r = await api("PUT", "/admin/api/banner", {
      activo: panel.querySelector("#ban-activo").checked,
      texto: panel.querySelector("#ban-texto").value,
      tipo: panel.querySelector("#ban-tipo").value,
      fuente: panel.querySelector("#ban-fuente").value,
      animacion: panel.querySelector("#ban-animacion").value,
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
      fuente: panel.querySelector("#promo-fuente").value,
      animacion: panel.querySelector("#promo-animacion").value,
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
    marcarContenidoListo();
    return;
  }
  document.getElementById("admin-contenido").style.display = "flex";

  Object.keys(GRUPOS).filter((g) => GRUPOS[g].enSidebar).forEach(pintarSubmenuSidebar);

  // Oculta grupos enteros sin NINGUNA vista visible para este admin (según
  // su permiso), y deja el resto cableado -- dentro de un grupo visible,
  // sus subvistas sin permiso ya se filtran solas al pintar el selector/
  // desplegable (renderSelectorGrupo/pintarSubmenuSidebar). Un solo clic en
  // cualquier grupo lleva a su última vista visitada (o a la primera
  // visible la primera vez) -- activarPestana ya se encarga de desplegar
  // el submenú de ese grupo si lo tiene, no hace falta un manejador aparte
  // solo para desplegar.
  let primeraPestanaVisible = null;
  document.querySelectorAll(".admin-tab[data-grupo]").forEach((b) => {
    const grupoId = b.dataset.grupo;
    const grupo = GRUPOS[grupoId];
    const visibles = grupo.pestanas.filter((p) => puedeVer(p));
    if (visibles.length === 0) {
      b.hidden = true;
      const contenedor = b.closest("[data-grupo-contenedor]");
      if (contenedor) contenedor.hidden = true;
      return;
    }
    if (!primeraPestanaVisible) primeraPestanaVisible = visibles[0];
    b.addEventListener("click", () => activarPestana(ultimaPestanaPorGrupo[grupoId] || visibles[0]));
  });

  document.getElementById("admin-oposicion").addEventListener("change", () => { temaSeleccionado = null; RENDERS[pestanaActual](); });
  activarPestana(primeraPestanaVisible || "dashboard");
  marcarContenidoListo();
});
