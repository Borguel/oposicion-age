// Exporta un resumen del progreso del usuario a PDF, con el mismo patrón
// (cursor de posición + asegurarEspacio/nuevaPagina + splitTextToSize) que
// ya usa resultados-test.js para que ninguna línea quede cortada entre
// páginas. Deliberadamente en su propio módulo -- resultados-test.js
// exporta el PDF de UN test, esto exporta el resumen agregado de toda la
// oposición.
export function descargarResumenProgresoPDF(datos) {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const margin = 18;
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const anchoTexto = pageWidth - margin * 2;
  const limiteInferior = pageHeight - 22;
  let yPos = 0;
  let pagina = 0;

  function pintarPie() {
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(150);
    doc.text(`Página ${pagina + 1}`, pageWidth - margin, pageHeight - 10, { align: "right" });
    doc.text("Domina tu Opo", margin, pageHeight - 10);
    doc.setTextColor(0);
  }

  function nuevaPagina() {
    doc.addPage();
    pagina++;
    yPos = 24;
    pintarPie();
  }

  function asegurarEspacio(alturaNecesaria) {
    if (yPos + alturaNecesaria > limiteInferior) nuevaPagina();
  }

  function titulo(texto) {
    asegurarEspacio(14);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(14);
    doc.setTextColor(20);
    doc.text(texto, margin, yPos);
    yPos += 4;
    doc.setDrawColor(230);
    doc.line(margin, yPos, pageWidth - margin, yPos);
    yPos += 8;
  }

  function fila(etiqueta, valor) {
    asegurarEspacio(7);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(11);
    doc.setTextColor(90);
    doc.text(etiqueta, margin, yPos);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(20);
    doc.text(String(valor), pageWidth - margin, yPos, { align: "right" });
    yPos += 7;
  }

  function parrafo(texto) {
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10.5);
    doc.setTextColor(60);
    const lineas = doc.splitTextToSize(texto, anchoTexto);
    lineas.forEach((linea) => {
      asegurarEspacio(6);
      doc.text(linea, margin, yPos);
      yPos += 6;
    });
    doc.setTextColor(0);
  }

  // --- Portada ---
  pagina = 0;
  yPos = 28;
  doc.setFont("helvetica", "bold");
  doc.setFontSize(22);
  doc.setTextColor(20);
  doc.text("Resumen de tu progreso", pageWidth / 2, yPos, { align: "center" });
  yPos += 9;
  doc.setFont("helvetica", "normal");
  doc.setFontSize(11);
  doc.setTextColor(110);
  doc.text(`${datos.nombreOposicion} · ${new Date().toLocaleDateString("es-ES", { day: "2-digit", month: "long", year: "numeric" })}`, pageWidth / 2, yPos, { align: "center" });
  doc.setTextColor(0);
  yPos += 14;
  pintarPie();

  // --- Resumen general ---
  titulo("Resumen general");
  fila("Tests realizados", datos.testsRealizados);
  fila("Tests aprobados", `${datos.testsAprobados} (${datos.porcentajeAprobados}%)`);
  fila("Tests suspendidos", `${datos.testsSuspendidos} (${datos.porcentajeSuspendidos}%)`);
  fila("Puntuación media", `${datos.puntuacionMedia.toFixed(1)} / 10`);
  fila("Tiempo dedicado a hacer tests", datos.tiempoTotalTexto);
  yPos += 4;

  // --- Aciertos y fallos ---
  titulo("Aciertos y fallos");
  fila("Aciertos totales", `${datos.totalAciertos} (${datos.porcentajeAciertos}%)`);
  fila("Fallos totales", `${datos.totalFallos} (${datos.porcentajeFallos}%)`);
  fila("En blanco", `${datos.totalBlancos} (${datos.porcentajeBlancos}%)`);
  yPos += 4;

  // --- Temas flojos ---
  if (datos.temasFlojos && datos.temasFlojos.length) {
    titulo("Temas a repasar");
    datos.temasFlojos.forEach((t) => fila(t.nombre, `${t.porcentaje}% de acierto`));
    yPos += 4;
  }

  // --- Insignias conseguidas ---
  if (datos.insigniasConseguidas && datos.insigniasConseguidas.length) {
    titulo("Insignias conseguidas");
    parrafo(datos.insigniasConseguidas.join("   ·   "));
    yPos += 4;
  }

  // --- Evolución reciente ---
  if (datos.historialReciente && datos.historialReciente.length) {
    titulo("Evolución reciente");
    datos.historialReciente.forEach((t) => {
      const fecha = t.fecha ? new Date(t.fecha).toLocaleDateString("es-ES") : "—";
      fila(fecha, `${t.nota.toFixed(1)}/10 · ${t.resultado === "aprobado" ? "Aprobado" : "Suspendido"}`);
    });
  }

  doc.save(datos.nombreArchivo || "resumen-progreso.pdf");
}
