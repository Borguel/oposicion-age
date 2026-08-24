import { icono } from "/assets/icons.js";
import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

const HERRAMIENTAS = [
  { slug: "subida-pdf-resumen", etiqueta: "Resumen", icono: "documento", tipo: "resumen" },
  { slug: "subida-pdf-esquemas", etiqueta: "Esquema", icono: "esquema", tipo: "esquema" },
  { slug: "subida-pdf-tarjetas", etiqueta: "Tarjetas", icono: "tarjeta", tipo: "tarjetas" },
  { slug: "subida-pdf-generar-test", etiqueta: "Test", icono: "lapiz", tipo: "test" },
];

// Bug real (23/08/2026): estos enlaces mandaban siempre a la herramienta
// SIN "?ver=", así que aunque el documento ya tuviera un resumen/esquema/
// test/tarjetas guardado, pulsar aquí disparaba una generación nueva sin
// avisar -- gastando una regeneración de las contadas (ver
// LIMITE_GENERACIONES_POR_DOCUMENTO) solo por querer VER lo que ya
// existía. Se consulta /documento/<id>/estado (mismo documento, un único
// fetch) para saber qué tipos ya están generados y añadir "&ver=<tipo>"
// solo en esos casos -- si el fetch falla, se muestran los enlaces sin
// "ver" como hasta ahora (nunca se bloquea el acceso por esto).
export async function pintarAccesosOtrasHerramientas({ contenedor, documentoId, herramientaActual }) {
  if (!contenedor || !documentoId) return;
  const otras = HERRAMIENTAS.filter((h) => h.slug !== herramientaActual);

  let estado = {};
  try {
    const token = await idToken();
    if (token) {
      const resp = await fetch(`${BACKEND_URL}/documento/${encodeURIComponent(documentoId)}/estado`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (resp.ok) estado = await resp.json();
    }
  } catch (e) { /* se muestran los enlaces sin "ver", ver comentario de arriba */ }

  contenedor.innerHTML = `
    <p class="otras-herramientas-titulo">También puedes generar desde este mismo documento:</p>
    <div class="otras-herramientas-botones">
      ${otras.map((h) => {
        const yaGenerado = estado[`tiene_${h.tipo}`];
        const ver = yaGenerado ? `&ver=${h.tipo}` : "";
        return `<a class="btn btn-outline" href="/${h.slug}/?documento_id=${encodeURIComponent(documentoId)}${ver}">${icono(h.icono, 16)} ${h.etiqueta}</a>`;
      }).join("")}
    </div>
  `;
  contenedor.classList.remove("hidden");
}
