import { idToken } from "/assets/auth.js";
import { icono } from "/assets/icons.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";

// Iconos de las tarjetas de herramientas y del banner "Mis documentos": se
// pintan aquí, una sola vez, a partir de los data-icon del HTML (en vez de
// emoji sueltos incrustados en el markup).
document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

// Este hub de herramientas se podía ver entero sin haber iniciado sesión.
// Ahora se exige login nada más cargar la página, como en el resto de
// herramientas de IA.
async function exigirLogin() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
  }
}
exigirLogin();

async function cargarResumenDocumentos() {
  const token = await idToken();
  if (!token) return; // usuario no ha iniciado sesión: el banner se queda oculto

  try {
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return;
    const datos = await res.json();
    const documentos = datos.documentos || [];
    if (documentos.length === 0) return;

    const pendientes = documentos.filter(d => !d.tiene_resumen || !d.tiene_esquema || d.num_tarjetas === 0 || d.num_tests === 0).length;
    const resumen = document.getElementById('mis-documentos-banner-resumen');
    resumen.textContent = pendientes > 0
      ? `${documentos.length} documento${documentos.length > 1 ? "s" : ""} guardado${documentos.length > 1 ? "s" : ""} · ${pendientes} con contenido aún por generar`
      : `${documentos.length} documento${documentos.length > 1 ? "s" : ""} guardado${documentos.length > 1 ? "s" : ""}, listos para repasar`;

    document.getElementById('mis-documentos-banner').classList.remove('hidden');
  } catch (e) {
    console.error('Error cargando resumen de "Mis documentos":', e);
  }
}

cargarResumenDocumentos();
