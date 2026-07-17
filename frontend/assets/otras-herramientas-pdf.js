// Bloque "También puedes generar desde este mismo documento" que aparece
// tras generar un resumen/esquema/tarjetas/test desde un PDF subido: enlaza
// a las otras 3 herramientas pasando ?documento_id= para que reutilicen el
// texto ya extraído sin tener que volver a subir el archivo (cada página ya
// sabe leer ese parámetro, ver inicializarDesdeDocumento en su script.js).

import { icono } from "/assets/icons.js";

const HERRAMIENTAS = [
  { slug: "subida-pdf-resumen", etiqueta: "Resumen", icono: "documento" },
  { slug: "subida-pdf-esquemas", etiqueta: "Esquema", icono: "esquema" },
  { slug: "subida-pdf-tarjetas", etiqueta: "Tarjetas", icono: "tarjeta" },
  { slug: "subida-pdf-generar-test", etiqueta: "Test", icono: "lapiz" },
];

export function pintarAccesosOtrasHerramientas({ contenedor, documentoId, herramientaActual }) {
  if (!contenedor || !documentoId) return;
  const otras = HERRAMIENTAS.filter((h) => h.slug !== herramientaActual);
  contenedor.innerHTML = `
    <p class="otras-herramientas-titulo">También puedes generar desde este mismo documento:</p>
    <div class="otras-herramientas-botones">
      ${otras.map((h) => `<a class="btn btn-outline" href="/${h.slug}/?documento_id=${encodeURIComponent(documentoId)}">${icono(h.icono, 16)} ${h.etiqueta}</a>`).join("")}
    </div>
  `;
  contenedor.classList.remove("hidden");
}
