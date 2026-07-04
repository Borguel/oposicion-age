import { idToken } from "/assets/auth.js";

const BACKEND_URL = "https://oposicion-age.onrender.com";

function formatearFecha(iso) {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(iso));
  } catch (e) {
    return "";
  }
}

function filaContenido({ label, icono, existe, cantidad, urlVer, urlGenerar, urlAleatorias, textoGenerar }) {
  const acciones = [];
  if (existe) {
    acciones.push(`<a class="documento-card-btn principal" href="${urlVer}">Ver</a>`);
    if (urlAleatorias) {
      acciones.push(`<a class="documento-card-btn" href="${urlAleatorias}">10 aleatorias</a>`);
    }
    acciones.push(`<a class="documento-card-btn" href="${urlGenerar}">Generar más</a>`);
  } else {
    acciones.push(`<a class="documento-card-btn principal" href="${urlGenerar}">${textoGenerar}</a>`);
  }
  const etiquetaCantidad = existe && cantidad ? ` (${cantidad})` : "";
  return `
    <div class="documento-card-fila">
      <span class="documento-card-fila-label">${icono} ${label}${etiquetaCantidad}</span>
      <div class="documento-card-fila-acciones">${acciones.join("")}</div>
    </div>
  `;
}

function tarjetaDocumento(doc) {
  const nombreCorto = (doc.titulo || doc.nombre_archivo || "Documento").slice(0, 90);
  const meta = [
    doc.nombre_archivo,
    doc.num_paginas ? `${doc.num_paginas} páginas` : null,
    doc.fecha_subida ? `subido el ${formatearFecha(doc.fecha_subida)}` : null
  ].filter(Boolean).join(" · ");

  const filas = [
    filaContenido({
      label: "Resumen",
      icono: "📄",
      existe: doc.tiene_resumen,
      urlVer: `/subida-pdf-resumen/?documento_id=${doc.id}&ver=resumen`,
      urlGenerar: `/subida-pdf-resumen/?documento_id=${doc.id}`,
      textoGenerar: "Generar resumen"
    }),
    filaContenido({
      label: "Esquema",
      icono: "🗂️",
      existe: doc.tiene_esquema,
      urlVer: `/subida-pdf-esquemas/?documento_id=${doc.id}&ver=esquema`,
      urlGenerar: `/subida-pdf-esquemas/?documento_id=${doc.id}`,
      textoGenerar: "Generar esquema"
    }),
    filaContenido({
      label: "Tarjetas",
      icono: "🃏",
      existe: doc.num_tarjetas > 0,
      cantidad: doc.num_tarjetas,
      urlVer: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=todas`,
      urlAleatorias: `/subida-pdf-tarjetas/?documento_id=${doc.id}&ver=tarjetas&modo=aleatorias&cantidad=10`,
      urlGenerar: `/subida-pdf-tarjetas/?documento_id=${doc.id}`,
      textoGenerar: "Generar tarjetas"
    }),
    filaContenido({
      label: "Test",
      icono: "🧪",
      existe: doc.num_tests > 0,
      cantidad: doc.num_tests ? `${doc.num_tests} intento${doc.num_tests > 1 ? "s" : ""}` : null,
      urlVer: `/subida-pdf-generar-test/?documento_id=${doc.id}&ver=test`,
      urlGenerar: `/subida-pdf-generar-test/?documento_id=${doc.id}`,
      textoGenerar: "Generar test"
    })
  ].join("");

  return `
    <div class="documento-card">
      <div class="documento-card-header">
        <div class="documento-card-icon">📘</div>
        <div>
          <p class="documento-card-titulo">${nombreCorto}</p>
          <p class="documento-card-meta">${meta}</p>
        </div>
      </div>
      ${filas}
    </div>
  `;
}

async function cargarMisDocumentos() {
  const token = await idToken();
  if (!token) return; // usuario no ha iniciado sesión: la sección se queda oculta

  try {
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return;
    const datos = await res.json();
    const documentos = datos.documentos || [];
    if (documentos.length === 0) return;

    document.getElementById('mis-documentos-lista').innerHTML = documentos.map(tarjetaDocumento).join("");
    document.getElementById('mis-documentos-seccion').classList.remove('hidden');
  } catch (e) {
    console.error('Error cargando "Mis documentos":', e);
  }
}

cargarMisDocumentos();
