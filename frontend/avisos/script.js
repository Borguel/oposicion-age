import { icono } from "/assets/icons.js";

async function importAuth() {
  return import("/assets/auth.js");
}

const elCargando = document.getElementById("avisos-cargando");
const elLista = document.getElementById("avisos-lista");
const elVacio = document.getElementById("avisos-vacio");

// Externo (avisos oficiales, directo al BOE) abre en pestaña nueva -- mismo
// criterio que auth.js/atributosEnlace, duplicado aquí (no exportado desde
// auth.js) por ser una línea trivial que no vale la pena exponer como API.
function atributosEnlace(href) {
  return href.startsWith("http") ? ' target="_blank" rel="noopener"' : "";
}

function renderizarItem(n, vistas, escapeHtmlBuscador) {
  return `
    <a class="avisos-item ${vistas.has(n.id) ? "" : "avisos-item-nuevo"}" href="${n.href}"${atributosEnlace(n.href)}>
      <span class="avisos-item-icono">${icono(n.iconoNombre, 20)}</span>
      <span class="avisos-item-cuerpo">
        <span class="avisos-item-texto">${escapeHtmlBuscador(n.texto)}</span>
        ${n.fecha ? `<span class="avisos-item-fecha">${escapeHtmlBuscador(n.fecha)}</span>` : ""}
      </span>
    </a>
  `;
}

function renderizarSeccion(titulo, notis, vistas, escapeHtmlBuscador) {
  if (!notis.length) return "";
  return `
    <section class="avisos-seccion">
      <h2 class="avisos-seccion-titulo">${titulo}</h2>
      <div class="avisos-seccion-lista">
        ${notis.map((n) => renderizarItem(n, vistas, escapeHtmlBuscador)).join("")}
      </div>
    </section>
  `;
}

async function cargarAvisos() {
  const {
    calcularNotificaciones, obtenerNotificacionesVistas, marcarNotificacionesComoVistas,
    escapeHtmlBuscador, marcarContenidoListo,
  } = await importAuth();

  try {
    const notis = await calcularNotificaciones();
    elCargando.hidden = true;

    if (!notis.length) {
      elVacio.hidden = false;
      marcarContenidoListo();
      return;
    }

    const vistas = obtenerNotificacionesVistas();
    const personales = notis.filter((n) => n.categoria !== "oficial");
    const oficiales = notis.filter((n) => n.categoria === "oficial");
    elLista.innerHTML =
      renderizarSeccion("Tus recordatorios", personales, vistas, escapeHtmlBuscador) +
      renderizarSeccion("Avisos oficiales", oficiales, vistas, escapeHtmlBuscador);
    marcarNotificacionesComoVistas(notis.map((n) => n.id));
  } catch (e) {
    elCargando.hidden = true;
    elVacio.hidden = false;
    elVacio.textContent = "No se han podido cargar los avisos. Inténtalo de nuevo más tarde.";
  }
  marcarContenidoListo();
}

cargarAvisos();
