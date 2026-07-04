import { idToken } from "/assets/auth.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";

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
