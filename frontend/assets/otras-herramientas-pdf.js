// Bloque "También puedes generar desde este mismo documento" que aparece
// tras generar un resumen/esquema/tarjetas/test desde un PDF subido: enlaza
// a las otras 3 herramientas pasando ?documento_id= para que reutilicen el
// texto ya extraído sin tener que volver a subir el archivo (cada página ya
// sabe leer ese parámetro, ver inicializarDesdeDocumento en su script.js).

const HERRAMIENTAS = [
  { slug: "subida-pdf-resumen", etiqueta: "Resumen", icono: "📄" },
  { slug: "subida-pdf-esquemas", etiqueta: "Esquema", icono: "🗂️" },
  { slug: "subida-pdf-tarjetas", etiqueta: "Tarjetas", icono: "🃏" },
  { slug: "subida-pdf-generar-test", etiqueta: "Test", icono: "✏️" },
];

export function pintarAccesosOtrasHerramientas({ contenedor, documentoId, herramientaActual }) {
  if (!contenedor || !documentoId) return;
  const otras = HERRAMIENTAS.filter((h) => h.slug !== herramientaActual);
  contenedor.innerHTML = `
    <p class="otras-herramientas-titulo">También puedes generar desde este mismo documento:</p>
    <div class="otras-herramientas-botones">
      ${otras.map((h) => `<a class="btn btn-outline" href="/${h.slug}/?documento_id=${encodeURIComponent(documentoId)}">${h.icono} ${h.etiqueta}</a>`).join("")}
    </div>
  `;
  contenedor.classList.remove("hidden");
}
