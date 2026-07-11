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
  const nota = (aciertos * 1 - fallos / 3).toFixed(2);
  const notaOficial100 = preguntas.length ? Math.max(0, (nota / preguntas.length) * 100).toFixed(1) : "0.0";
  const apto = parseFloat(notaOficial100) >= 50;
  return { aciertos, fallos, sinResponder, porcentaje, nota, notaOficial100, apto };
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
export function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

/**
 * Si la explicación viene con el patrón "A) ... B) ... C) ... D) ..." (el
 * formato que ahora se le pide a la IA), la separa en una línea por opción
 * para que se lea con orden en vez de como un único párrafo corrido.
 * Devuelve null si el texto no sigue ese patrón (explicaciones antiguas ya
 * guardadas antes de este cambio), y entonces se muestra tal cual.
 */
function separarExplicacionPorOpcion(texto) {
  const limpio = (texto || "").trim();
  if (!/^[A-D]\)\s/.test(limpio)) return null;
  const partes = limpio.split(/\s(?=[A-D]\)\s)/).map((s) => s.trim()).filter(Boolean);
  return partes.length >= 2 ? partes : null;
}

function formatearExplicacionHTML(texto) {
  const partes = separarExplicacionPorOpcion(texto);
  if (!partes) return `<p class="explicacion-texto">${escaparHtml(texto)}</p>`;
  const lineas = partes
    .map((p) => `<p class="explicacion-linea">${escaparHtml(p).replace(/^([A-D]\))/, "<strong>$1</strong>")}</p>`)
    .join("");
  return `<div class="explicacion-estructurada">${lineas}</div>`;
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

    detalleHTML += `<div class="${clase}">
      <div class="pregunta-en-negrita">${i + 1}. ${escaparHtml(quitarNumeracion(p.pregunta))}</div>`;
    for (const letra in p.opciones) {
      let tipoRespuesta = "detalle-opcion";
      let icono = "";
      if (letra === correcta) {
        tipoRespuesta = "detalle-opcion correcta";
        icono = '<span class="icono-correcto">✅</span>';
      }
      if (letra === seleccion && seleccion !== correcta) {
        tipoRespuesta = "detalle-opcion incorrecta";
        icono = '<span class="icono-incorrecto">❌</span>';
      }
      detalleHTML += `<div class="${tipoRespuesta}">${icono}${letra}) ${escaparHtml(p.opciones[letra])}</div>`;
    }
    const idExp = `exp-${i}-${Math.random().toString(36).slice(2, 6)}`;
    detalleHTML += `<button type="button" class="detalle-explicacion-btn" data-toggle-target="${idExp}">📘 Mostrar/Ocultar Explicación</button>`;
    detalleHTML += `<div id="${idExp}" class="detalle-explicacion-panel" style="display:none;"><strong>Explicación:</strong>${formatearExplicacionHTML(explicacion)}</div></div>`;
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
    <div class="resultado-resumen-card">
      <div class="resultado-veredicto ${stats.apto ? "aprobado" : "suspendido"}">
        <span class="resultado-veredicto-texto">${stats.apto ? "✅ Aprobado" : "❌ Suspendido"}</span>
      </div>

      <div class="resultado-notas-grid">
        <div class="resultado-nota-box">
          <span class="resultado-nota-label">Nota de este test</span>
          <span class="resultado-nota-valor">${stats.nota}<small> / ${preguntas.length}</small></span>
        </div>
        <div class="resultado-nota-box">
          <span class="resultado-nota-label">Nota examen oficial</span>
          <span class="resultado-nota-valor">${stats.notaOficial100}<small> / 100</small></span>
        </div>
      </div>

      <div class="resultado-resumen-grid">
        <div class="resultado-resumen-tile tile-acierto">
          <span class="tile-info"><span class="tile-icono">✅</span>Aciertos</span>
          <span class="tile-valor">${stats.aciertos}</span>
        </div>
        <div class="resultado-resumen-tile tile-fallo">
          <span class="tile-info"><span class="tile-icono">❌</span>Fallos</span>
          <span class="tile-valor">${stats.fallos}</span>
        </div>
        <div class="resultado-resumen-tile tile-blanco">
          <span class="tile-info"><span class="tile-icono">⏸</span>En blanco</span>
          <span class="tile-valor">${stats.sinResponder}</span>
        </div>
        <div class="resultado-resumen-tile tile-porcentaje">
          <span class="tile-info"><span class="tile-icono">🎯</span>Acierto</span>
          <span class="tile-valor">${stats.porcentaje}%</span>
        </div>
      </div>
      ${rachaHTML}
    </div>
    <div class="analisis-ia-bloque">
      <button type="button" id="btn-analisis-ia" class="btn age-btn-outline">🤖 Ver análisis de mi rendimiento con IA</button>
      <div id="analisis-ia-resultado"></div>
    </div>
    <div class="resultado-temas-desplegable">
      <button type="button" class="resultado-toggle-btn resultado-temas-toggle" id="btn-temas-toggle" aria-expanded="false">
        <span class="resultado-toggle-icono">📈</span>
        <span class="resultado-toggle-texto">Estadísticas por tema</span>
        <span class="resultado-toggle-chevron">▾</span>
      </button>
      <div class="resultado-temas-panel" id="panel-temas" style="display:none;">${tablaTemasHTML}</div>
    </div>
    <div class="resultado-detalle-cabecera">
      <h3 class="resultado-detalle-titulo">📝 Detalle de preguntas</h3>
      <div class="resultado-filtro-dropdown" id="filtro-dropdown">
        <button type="button" class="resultado-toggle-btn resultado-filtro-btn" id="btn-filtro-preguntas" aria-expanded="false">
          <span class="resultado-toggle-icono">🔍</span>
          <span class="resultado-toggle-texto" id="filtro-preguntas-label">Todas las preguntas</span>
          <span class="resultado-toggle-chevron">▾</span>
        </button>
        <div class="resultado-filtro-panel" id="panel-filtro-preguntas" style="display:none;">
          <label class="resultado-filtro-opcion"><input type="checkbox" data-filtro-valor="acierto" checked> ✅ Aciertos</label>
          <label class="resultado-filtro-opcion"><input type="checkbox" data-filtro-valor="fallo" checked> ❌ Fallos</label>
          <label class="resultado-filtro-opcion"><input type="checkbox" data-filtro-valor="blanco" checked> ⏸ En blanco</label>
        </div>
      </div>
    </div>
    <div class="lista-detalle-preguntas">${detalleHTML}</div>
  `;

  // Desplegable de estadísticas por tema (no se usa <details> nativo porque
  // en algunos navegadores móviles el summary con marcador personalizado no
  // responde bien al toque).
  const btnTemasToggle = contenedor.querySelector("#btn-temas-toggle");
  if (btnTemasToggle) {
    btnTemasToggle.addEventListener("click", () => {
      const panel = contenedor.querySelector("#panel-temas");
      const abierto = panel.style.display !== "none";
      panel.style.display = abierto ? "none" : "block";
      btnTemasToggle.setAttribute("aria-expanded", String(!abierto));
      btnTemasToggle.classList.toggle("abierto", !abierto);
    });
  }

  // Filtro de preguntas: un único desplegable con checkboxes en vez de
  // botones sueltos, para poder combinar varias categorías a la vez (p. ej.
  // ver fallos y en blanco juntos) sin ocupar tanto espacio.
  const dropdownFiltro = contenedor.querySelector("#filtro-dropdown");
  const btnFiltro = contenedor.querySelector("#btn-filtro-preguntas");
  const panelFiltro = contenedor.querySelector("#panel-filtro-preguntas");
  const labelFiltro = contenedor.querySelector("#filtro-preguntas-label");
  const checksFiltro = Array.from(contenedor.querySelectorAll("[data-filtro-valor]"));
  const ETIQUETA_FILTRO = { acierto: "Aciertos", fallo: "Fallos", blanco: "En blanco" };

  function aplicarFiltroPreguntas() {
    const activos = checksFiltro.filter((c) => c.checked).map((c) => c.dataset.filtroValor);
    const todas = activos.length === 0 || activos.length === checksFiltro.length;
    labelFiltro.textContent = todas ? "Todas las preguntas" : activos.map((v) => ETIQUETA_FILTRO[v]).join(", ");
    contenedor.querySelectorAll(".lista-detalle-preguntas > div").forEach((item) => {
      item.style.display = todas || activos.some((v) => item.classList.contains(v)) ? "block" : "none";
    });
  }

  if (btnFiltro) {
    btnFiltro.addEventListener("click", (e) => {
      e.stopPropagation();
      const abierto = panelFiltro.style.display !== "none";
      panelFiltro.style.display = abierto ? "none" : "block";
      btnFiltro.setAttribute("aria-expanded", String(!abierto));
      btnFiltro.classList.toggle("abierto", !abierto);
    });
    checksFiltro.forEach((c) => c.addEventListener("change", aplicarFiltroPreguntas));
    document.addEventListener("click", (e) => {
      if (!dropdownFiltro.contains(e.target)) {
        panelFiltro.style.display = "none";
        btnFiltro.setAttribute("aria-expanded", "false");
        btnFiltro.classList.remove("abierto");
      }
    });
  }

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
  doc.text(`Nota de este test: ${stats.nota} / ${preguntas.length}   ·   Nota examen oficial: ${stats.notaOficial100} / 100 (${stats.apto ? "Aprobado" : "Suspendido"})`, pageWidth / 2, yPos, { align: "center" });
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
    const partesExplicacion = separarExplicacionPorOpcion(explicacion) || [explicacion];
    const lineasPorParteExplicacion = partesExplicacion.map((parte) => doc.splitTextToSize(parte, anchoTexto));
    const lineasExplicacion = lineasPorParteExplicacion.flat();

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
    lineasPorParteExplicacion.forEach((lineas) => {
      escribirLineas(lineas);
      if (partesExplicacion.length > 1) yPos += 1.5;
    });

    yPos += 6;
    asegurarEspacio(4);
    doc.setDrawColor(225);
    doc.line(margin, yPos, pageWidth - margin, yPos);
    yPos += 10;
  });

  doc.save(nombreArchivo);
}
