import { icono } from "/assets/icons.js";

async function importAuth() {
  return import("/assets/auth.js");
}

const elCargando = document.getElementById("avisos-cargando");
const elLista = document.getElementById("avisos-lista");
const elVacio = document.getElementById("avisos-vacio");

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
    elLista.innerHTML = notis.map((n) => `
      <a class="avisos-item ${vistas.has(n.id) ? "" : "avisos-item-nuevo"}" href="${n.href}">
        <span class="avisos-item-icono">${icono(n.iconoNombre, 20)}</span>
        <span class="avisos-item-texto">${escapeHtmlBuscador(n.texto)}</span>
      </a>
    `).join("");
    marcarNotificacionesComoVistas(notis.map((n) => n.id));
  } catch (e) {
    elCargando.hidden = true;
    elVacio.hidden = false;
    elVacio.textContent = "No se han podido cargar los avisos. Inténtalo de nuevo más tarde.";
  }
  marcarContenidoListo();
}

cargarAvisos();
