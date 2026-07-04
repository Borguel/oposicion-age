// Renderizado compartido de "resultados de test" (resumen + tabla por tema +
// detalle filtrable de preguntas) y descarga en PDF. Antes cada página
// (test-generator, repetir-test, preguntas-falladas) tenía su propia
// versión -- así que ahora todas usan este mismo módulo para que el
// resultado sea siempre el mismo, sea cual sea el tipo de test.
//
// Requiere que la página ya tenga cargado jsPDF (para la descarga) via
// <script> normal antes de este módulo.

function calcularEstadisticas(preguntas, respuestasUsuario) {
  let aciertos = 0;
  preguntas.forEach((p, i) => {
    if (respuestasUsuario[i] === p.respuesta_correcta) aciertos++;
  });
  const sinResponder = respuestasUsuario.filter((r) => r === null || r === undefined).length;
  const fallos = preguntas.length - aciertos - sinResponder;
  const porcentaje = preguntas.length ? ((aciertos / preguntas.length) * 100).toFixed(1) : "0.0";
  const nota = (aciertos * 1 - fallos * 0.33).toFixed(2);
  const notaSobre10 = preguntas.length ? Math.max(0, (nota / preguntas.length) * 10).toFixed(2) : "0.00";
  const apto = parseFloat(notaSobre10) >= 5;
  return { aciertos, fallos, sinResponder, porcentaje, nota, notaSobre10, apto };
}

function agruparPorTema(preguntas, respuestasUsuario, listaTemas) {
  const stats = {};
  preguntas.forEach((p, i) => {
    const tema = (listaTemas || []).find((t) => t.id === p.tema_id);
    const temaId = tema ? tema.id : "desconocido";
    const tituloTema = tema ? tema.titulo : "Sin tema identificado";
    if (!stats[temaId]) {
      stats[temaId] = { titulo: tituloTema, total: 0, aciertos: 0, fallos: 0, blancos: 0 };
    }
    stats[temaId].total++;
    const seleccion = respuestasUsuario[i];
    if (seleccion === p.respuesta_correcta) stats[temaId].aciertos++;
    else if (seleccion === null || seleccion === undefined) stats[temaId].blancos++;
    else stats[temaId].fallos++;
  });
  return stats;
}

function acortarTitulo(titulo, maxLength = 55) {
  if (!titulo) return titulo;
  return titulo.length > maxLength ? titulo.slice(0, maxLength - 1).trimEnd() + "…" : titulo;
}

function quitarNumeracion(texto) {
  return (texto || "").replace(/^\s*\d+\s*[\.\)]\s*/, "");
}

// El texto de preguntas/opciones/explicaciones viene de la IA (a partir de
// temario o de un PDF subido por el usuario) y se interpola en innerHTML:
// se escapa para que un documento con "<script>" o similar como texto plano
// no pueda ejecutarse en el navegador de quien lo generó.
function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

/**
 * Racha de aciertos más larga dentro de este test (rachas de "en blanco"
 * cortan la racha igual que un fallo, solo cuenta consecutivos correctos).
 * Sirve para el mensaje motivacional -- un simple "llevas X aciertos
 * seguidos" anima mucho más que una estadística fría.
 */
function calcularMejorRacha(preguntas, respuestasUsuario) {
  let mejor = 0;
  let actual = 0;
  preguntas.forEach((p, i) => {
    if (respuestasUsuario[i] === p.respuesta_correcta) {
      actual++;
      mejor = Math.max(mejor, actual);
    } else {
      actual = 0;
    }
  });
  return mejor;
}

function mensajeMotivacional(mejorRacha) {
  if (mejorRacha >= 20) return `🔥 ¡Racha brutal! ${mejorRacha} aciertos seguidos en este test.`;
  if (mejorRacha >= 10) return `💪 ¡${mejorRacha} aciertos seguidos! Vas a por todas.`;
  if (mejorRacha >= 5) return `👏 Llevas ${mejorRacha} aciertos seguidos, ¡sigue así!`;
  return null;
}

/**
 * Pinta el bloque de resumen + tabla por tema + listado detallado dentro de
 * `contenedor`. Devuelve las estadísticas calculadas por si la página
 * necesita guardarlas (p. ej. para mandarlas al backend).
 */
export function renderizarResultadosTest({ contenedor, preguntas, respuestasUsuario, listaTemas = [] }) {
  const stats = calcularEstadisticas(preguntas, respuestasUsuario);
  const statsPorTema = agruparPorTema(preguntas, respuestasUsuario, listaTemas);
  const mejorRacha = calcularMejorRacha(preguntas, respuestasUsuario);
  const mensajeRacha = mensajeMotivacional(mejorRacha);

  let detalleHTML = "";
  preguntas.forEach((p, i) => {
    const correcta = p.respuesta_correcta || "No indicada";
    const seleccion = respuestasUsuario[i];
    const explicacion = p.explicacion || "Sin explicación.";
    let clase = "fallo";
    if (seleccion === correcta) clase = "acierto";
    else if (seleccion === null || seleccion === undefined) clase = "blanco";

    detalleHTML += `<div class="${clase}" style="margin-bottom:25px;">
      <div class="pregunta-en-negrita">${i + 1}. ${escaparHtml(quitarNumeracion(p.pregunta))}</div>`;
    for (const letra in p.opciones) {
      let tipoRespuesta = "resp-neutra";
      let icono = "";
      if (letra === correcta) {
        tipoRespuesta = "resp-correcta";
        icono = '<span class="icono-correcto">✅</span>';
      }
      if (letra === seleccion && seleccion !== correcta) {
        tipoRespuesta = "resp-incorrecta";
        icono = '<span class="icono-incorrecto">❌ </span>';
      }
      detalleHTML += `<div class="${tipoRespuesta}">${icono}${letra}) ${escaparHtml(p.opciones[letra])}</div>`;
    }
    const idExp = `exp-${i}-${Math.random().toString(36).slice(2, 6)}`;
    detalleHTML += `<button type="button" class="btn age-btn-toggle-exp" data-toggle-target="${idExp}" style="margin-top: 10px; background: #e9ecef; color: #495057;">📘 Mostrar/Ocultar Explicación</button>`;
    detalleHTML += `<div id="${idExp}" style="display:none; margin-top: 10px; padding: 15px; background: #f8f9fa; border-radius: 8px;"><strong>Explicación:</strong> ${escaparHtml(explicacion)}</div></div>`;
  });

  const filasTema = Object.values(statsPorTema).map((t) => {
    const resolucion = t.total ? ((t.aciertos / t.total) * 100).toFixed(0) : "0";
    return `
      <tr>
        <td>${escaparHtml(acortarTitulo(t.titulo))}</td>
        <td>${t.total}</td>
        <td class="celda-acierto">${t.aciertos}</td>
        <td class="celda-fallo">${t.fallos}</td>
        <td class="celda-blanco">${t.blancos}</td>
        <td>${resolucion}%</td>
      </tr>`;
  }).join("");

  const tablaTemasHTML = `
    <div class="tabla-temas-container">
      <table class="tabla-temas">
        <thead>
          <tr><th>Tema</th><th>Preguntas</th><th>Aciertos</th><th>Fallos</th><th>Blanco</th><th>% resolución</th></tr>
        </thead>
        <tbody>${filasTema}</tbody>
      </table>
    </div>`;

  const rachaHTML = mensajeRacha
    ? `<div class="mensaje-racha-test">${mensajeRacha}</div>`
    : "";

  contenedor.innerHTML = `
    <div style='background:#f8f9fa;padding:25px;border-radius:12px;margin-bottom:25px;'>
      <h3>📊 Resumen del Test</h3>
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 15px; margin: 15px 0;">
        <div style="background: #e8f5e9; padding: 15px; border-radius: 10px;">
          <p style="color:green; font-weight:600;">✅ Aciertos: ${stats.aciertos}</p>
        </div>
        <div style="background: #ffebee; padding: 15px; border-radius: 10px;">
          <p style="color:red; font-weight:600;">❌ Fallos: ${stats.fallos}</p>
        </div>
        <div style="background: #e9ecef; padding: 15px; border-radius: 10px;">
          <p style="color:#495057; font-weight:600;">⏸ En blanco: ${stats.sinResponder}</p>
        </div>
        <div style="background: #e7f5ff; padding: 15px; border-radius: 10px;">
          <p style="color:#1c7ed6; font-weight:600;">🎯 Porcentaje: ${stats.porcentaje}%</p>
        </div>
      </div>
      <p><strong>📘 Nota de este test:</strong> ${stats.nota} / ${preguntas.length}</p>
      <p><strong>📏 Nota estilo examen oficial:</strong> ${stats.notaSobre10} / 10 — <span style="color:${stats.apto ? "#2e7d32" : "#c62828"}; font-weight:700;">${stats.apto ? "Apto" : "No apto"}</span></p>
      <div style='background:#e9ecef;border-radius:10px;overflow:hidden;margin-top:15px;height:20px;'>
        <div style='width:${stats.porcentaje}%;background:linear-gradient(to right,#4caf50,#81c784);height:100%;display:flex;align-items:center;justify-content:center;color:white;font-weight:600;'>
          ${stats.porcentaje}%
        </div>
      </div>
      ${rachaHTML}
    </div>
    <div class="analisis-ia-bloque">
      <button type="button" id="btn-analisis-ia" class="btn age-btn-outline">🤖 Ver análisis de mi rendimiento con IA</button>
      <div id="analisis-ia-resultado"></div>
    </div>
    <h3>📈 Estadísticas por tema</h3>
    ${tablaTemasHTML}
    <div class="filtros-container">
      <button type="button" class="btn btn-accent" data-filtro="todos">🟡 Todos</button>
      <button type="button" class="btn btn-primary" data-filtro="acierto">✅ Aciertos</button>
      <button type="button" class="btn btn-danger" data-filtro="fallo">❌ Fallos</button>
      <button type="button" class="btn" style="background: #adb5bd; color: white;" data-filtro="blanco">⏸ En blanco</button>
    </div>
    <h3 style="margin-top: 20px;">📝 Detalle de preguntas</h3>
    <div class="lista-detalle-preguntas">${detalleHTML}</div>
  `;

  // Filtros (delegado, sin onclick inline)
  contenedor.querySelectorAll("[data-filtro]").forEach((boton) => {
    boton.addEventListener("click", () => {
      const filtro = boton.dataset.filtro;
      contenedor.querySelectorAll(".lista-detalle-preguntas > div").forEach((item) => {
        item.style.display = filtro === "todos" || item.classList.contains(filtro) ? "block" : "none";
      });
    });
  });

  // Mostrar/ocultar explicación
  contenedor.querySelectorAll("[data-toggle-target]").forEach((boton) => {
    boton.addEventListener("click", () => {
      const destino = document.getElementById(boton.dataset.toggleTarget);
      if (destino) destino.style.display = destino.style.display === "none" ? "block" : "none";
    });
  });

  // Análisis de rendimiento con IA (bajo demanda, no automático: usa el
  // histórico acumulado del usuario, no solo este test, así que se pide
  // explícitamente en vez de disparar una llamada a IA en cada resultado).
  const btnAnalisisIA = contenedor.querySelector("#btn-analisis-ia");
  if (btnAnalisisIA) {
    btnAnalisisIA.addEventListener("click", async () => {
      const destino = contenedor.querySelector("#analisis-ia-resultado");
      btnAnalisisIA.disabled = true;
      btnAnalisisIA.textContent = "Analizando tu rendimiento...";
      destino.innerHTML = "";
      try {
        const { idToken } = await import("/assets/auth.js");
        const { obtenerOposicionActual } = await import("/assets/oposicion.js");
        const token = await idToken();
        if (!token) return;
        const res = await fetch(`https://oposicion-age.onrender.com/analisis-rendimiento?oposicion=${encodeURIComponent(obtenerOposicionActual())}`, {
          headers: { "Authorization": "Bearer " + token }
        });
        const datos = await res.json();
        destino.innerHTML = `<p>${datos.analisis || datos.mensaje || "No se ha podido generar el análisis ahora mismo."}</p>`;
      } catch (err) {
        destino.innerHTML = `<p>No se ha podido generar el análisis ahora mismo.</p>`;
        console.error(err);
      } finally {
        btnAnalisisIA.style.display = "none";
      }
    });
  }

  return stats;
}

function limpiarTextoPDF(texto) {
  if (!texto) return "";
  return texto
    .replace(/✅/g, "[Correcta] ")
    .replace(/❌/g, "[Incorrecta] ")
    .replace(/⏸/g, "[En blanco] ")
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, "");
}

/**
 * Genera un PDF de los resultados en A4 estándar. A diferencia de la
 * versión anterior, mide el alto de CADA bloque de pregunta antes de
 * dibujarlo y salta de página entero si no cabe -- así ninguna pregunta
 * queda partida a media frase entre dos páginas -- y añade cabecera,
 * pie de página con numeración y algo más de aire entre bloques.
 */
export function descargarResultadosPDF({ preguntas, respuestasUsuario, stats, titulo = "Resultados del Test", nombreArchivo = "resultados-test.pdf" }) {
  const { jsPDF } = window.jspdf;
  const doc = new jsPDF({ unit: "mm", format: "a4" });
  const margin = 18;
  const pageWidth = doc.internal.pageSize.getWidth();
  const pageHeight = doc.internal.pageSize.getHeight();
  const anchoTexto = pageWidth - margin * 2;
  const limiteInferior = pageHeight - 22;
  let yPos = 0;
  let pagina = 0;

  function nuevaPagina() {
    doc.addPage();
    pagina++;
    yPos = 24;
    pintarPie();
  }

  function pintarPie() {
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(150);
    doc.text(`Página ${pagina + 1}`, pageWidth - margin, pageHeight - 10, { align: "right" });
    doc.text("Oposición AGE", margin, pageHeight - 10);
    doc.setTextColor(0);
  }

  function asegurarEspacio(alturaNecesaria) {
    if (yPos + alturaNecesaria > limiteInferior) nuevaPagina();
  }

  function escribirLineas(lineas, opciones = {}) {
    const color = doc.getTextColor();
    lineas.forEach((linea) => {
      const alturaAntes = yPos;
      asegurarEspacio(6);
      if (yPos !== alturaAntes) doc.setTextColor(color);
      doc.text(linea, opciones.x ?? margin, yPos);
      yPos += opciones.interlineado ?? 6;
    });
  }

  // --- Portada / cabecera ---
  pagina = 0;
  yPos = 26;
  doc.setFont("helvetica", "bold");
  doc.setFontSize(20);
  doc.text(titulo, pageWidth / 2, yPos, { align: "center" });
  yPos += 10;
  doc.setFont("helvetica", "normal");
  doc.setFontSize(11);
  doc.setTextColor(110);
  const fecha = new Date().toLocaleDateString("es-ES", { day: "2-digit", month: "long", year: "numeric" });
  doc.text(fecha, pageWidth / 2, yPos, { align: "center" });
  doc.setTextColor(0);
  yPos += 12;

  doc.setFontSize(12);
  doc.setFont("helvetica", "bold");
  const resumen = `Aciertos: ${stats.aciertos}    Fallos: ${stats.fallos}    En blanco: ${stats.sinResponder}    Porcentaje: ${stats.porcentaje}%`;
  doc.text(resumen, pageWidth / 2, yPos, { align: "center" });
  yPos += 8;
  doc.setFont("helvetica", "normal");
  doc.text(`Nota de este test: ${stats.nota} / ${preguntas.length}   ·   Nota estilo examen oficial: ${stats.notaSobre10} / 10 (${stats.apto ? "Apto" : "No apto"})`, pageWidth / 2, yPos, { align: "center" });
  yPos += 14;
  doc.setDrawColor(220);
  doc.line(margin, yPos, pageWidth - margin, yPos);
  yPos += 12;
  pintarPie();

  // --- Preguntas ---
  doc.setFontSize(11);
  preguntas.forEach((p, i) => {
    const textoPregunta = `${i + 1}. ${limpiarTextoPDF(quitarNumeracion(p.pregunta))}`;
    const lineasPregunta = doc.splitTextToSize(textoPregunta, anchoTexto);

    const correcta = p.respuesta_correcta;
    const seleccion = respuestasUsuario[i];
    const acerto = seleccion === correcta;

    const lineasPorOpcion = Object.keys(p.opciones).map((letra) => {
      let texto = `${letra}) ${limpiarTextoPDF(p.opciones[letra])}`;
      let color = [40, 40, 40];
      if (letra === correcta) {
        texto += " [Respuesta correcta]";
        color = [46, 125, 50];
      } else if (letra === seleccion && !acerto) {
        texto += " [Tu respuesta]";
        color = [198, 40, 40];
      }
      return { lineas: doc.splitTextToSize(texto, anchoTexto), color };
    });
    const explicacion = limpiarTextoPDF(p.explicacion || "Sin explicación disponible.");
    const lineasExplicacion = doc.splitTextToSize(explicacion, anchoTexto);

    // Alto total estimado del bloque (pregunta + opciones + "Explicación:" + texto + margen)
    const totalLineas =
      lineasPregunta.length +
      lineasPorOpcion.reduce((sum, o) => sum + o.lineas.length, 0) +
      1 + lineasExplicacion.length;
    const altoBloque = totalLineas * 6 + 14;

    // Si el bloque entero no cabe en lo que queda de página (y tampoco es
    // más grande que una página completa), se salta de página antes de
    // empezarlo para no partirlo por la mitad.
    if (altoBloque <= limiteInferior - 24 && yPos + altoBloque > limiteInferior) {
      nuevaPagina();
    }

    doc.setFont("helvetica", "bold");
    doc.setTextColor(0);
    escribirLineas(lineasPregunta, { interlineado: 6.5 });
    yPos += 2;

    doc.setFont("helvetica", "normal");
    lineasPorOpcion.forEach(({ lineas, color }) => {
      doc.setTextColor(...color);
      escribirLineas(lineas);
    });
    doc.setTextColor(0);
    yPos += 3;

    asegurarEspacio(6);
    doc.setFont("helvetica", "bold");
    doc.text("Explicación:", margin, yPos);
    yPos += 6;
    doc.setFont("helvetica", "normal");
    escribirLineas(lineasExplicacion);

    yPos += 6;
    asegurarEspacio(4);
    doc.setDrawColor(225);
    doc.line(margin, yPos, pageWidth - margin, yPos);
    yPos += 10;
  });

  doc.save(nombreArchivo);
}
