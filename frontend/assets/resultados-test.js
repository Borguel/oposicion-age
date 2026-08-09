// Renderizado compartido de "resultados de test" (resumen + tabla por tema +
// detalle filtrable de preguntas) y descarga en PDF. Antes cada página
// (test-generator, repetir-test, preguntas-falladas) tenía su propia
// versión -- así que ahora todas usan este mismo módulo para que el
// resultado sea siempre el mismo, sea cual sea el tipo de test.
//
// Requiere que la página ya tenga cargado jsPDF (para la descarga) via
// <script> normal antes de este módulo.
import { icono } from "/assets/icons.js";
import anime from "/assets/vendor/anime.esm.js";

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

/**
 * Nota alternativa como si las preguntas marcadas como "duda" no contaran
 * en absoluto (ni acierto ni fallo, ni en el numerador ni en el
 * denominador) -- reutiliza calcularEstadisticas sobre el subconjunto
 * filtrado en vez de duplicar la fórmula de puntuación.
 */
function calcularEstadisticasSinDudas(preguntas, respuestasUsuario, marcadasDuda) {
  const preguntasFiltradas = [];
  const respuestasFiltradas = [];
  preguntas.forEach((p, i) => {
    if (!marcadasDuda[i]) {
      preguntasFiltradas.push(p);
      respuestasFiltradas.push(respuestasUsuario[i]);
    }
  });
  return { stats: calcularEstadisticas(preguntasFiltradas, respuestasFiltradas), numRestantes: preguntasFiltradas.length };
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

/**
 * Momento de autor de la pantalla de resultados (05/08/2026, a petición del
 * usuario: "más profesional, no animaciones básicas"): el veredicto entra
 * solo y decidido (sin rebote, es un examen, no un juego), las dos cifras
 * principales cuentan desde 0 -- el número ES el contenido de esta
 * pantalla, no decoración -- y el resto se revela en el orden en que se
 * lee, con la nota alternativa (si hay preguntas marcadas como duda)
 * teniendo su propio gesto de aparición para que se lea como una variante
 * aparte, no como una casilla más. Se coloca aquí (no en cada página) para
 * que las 8 pantallas que reutilizan este módulo lo hereden igual.
 */
function animarEntradaResultado(contenedor) {
  const veredicto = contenedor.querySelector(".resultado-veredicto");
  if (!veredicto || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const cajasNota = contenedor.querySelectorAll(".resultado-resumen-card > .resultado-notas-grid > .resultado-nota-box");
  const numeros = contenedor.querySelectorAll(".resultado-resumen-card > .resultado-notas-grid .resultado-nota-num");
  const notaAlternativa = contenedor.querySelector(".resultado-nota-alternativa");
  const tiles = contenedor.querySelectorAll(".resultado-resumen-tile");
  const racha = contenedor.querySelector(".mensaje-racha-test");

  anime.set(veredicto, { opacity: 0, scale: 0.85 });
  anime.set(cajasNota, { opacity: 0, translateY: 10 });
  if (notaAlternativa) anime.set(notaAlternativa, { opacity: 0, translateY: 14 });
  anime.set(tiles, { opacity: 0, translateY: 10 });
  if (racha) anime.set(racha, { opacity: 0, translateY: 8 });

  const tl = anime.timeline({ easing: "cubicBezier(0.16, 1, 0.3, 1)" });

  tl.add({ targets: veredicto, opacity: 1, scale: 1, duration: 450 }, 0);

  tl.add({ targets: cajasNota, opacity: 1, translateY: 0, duration: 350, delay: anime.stagger(70) }, 250);
  const duracionConteo = 650;
  numeros.forEach((el) => {
    const hasta = Number(el.dataset.hasta);
    const decimales = Number(el.dataset.decimales);
    el.textContent = (0).toFixed(decimales);
    const contador = { valor: 0 };
    tl.add({
      targets: contador,
      valor: hasta,
      duration: duracionConteo,
      easing: "easeOutQuad",
      update: () => { el.textContent = contador.valor.toFixed(decimales); },
    }, 300);
  });

  const finNotas = 300 + duracionConteo;
  if (notaAlternativa) {
    tl.add({ targets: notaAlternativa, opacity: 1, translateY: 0, duration: 400 }, finNotas);
  }
  const inicioTiles = notaAlternativa ? finNotas + 300 : finNotas - 150;
  tl.add({ targets: tiles, opacity: 1, translateY: 0, duration: 220, delay: anime.stagger(60) }, inicioTiles);

  if (racha) {
    const finTiles = inicioTiles + Math.max(0, tiles.length - 1) * 60 + 220;
    tl.add({ targets: racha, opacity: 1, translateY: 0, duration: 300 }, finTiles);
  }
}

function mensajeMotivacional(mejorRacha) {
  if (mejorRacha >= 20) return `${icono("fuego", 16)} ¡Racha brutal! ${mejorRacha} aciertos seguidos en este test.`;
  if (mejorRacha >= 10) return `${icono("rayo", 16)} ¡${mejorRacha} aciertos seguidos! Vas a por todas.`;
  if (mejorRacha >= 5) return `${icono("estrella", 16)} Llevas ${mejorRacha} aciertos seguidos, ¡sigue así!`;
  return null;
}

/**
 * Pinta el bloque de resumen + tabla por tema + listado detallado dentro de
 * `contenedor`. Devuelve las estadísticas calculadas por si la página
 * necesita guardarlas (p. ej. para mandarlas al backend).
 */
export function renderizarResultadosTest({ contenedor, preguntas, respuestasUsuario, listaTemas = [], marcadasDuda = [] }) {
  const stats = calcularEstadisticas(preguntas, respuestasUsuario);
  const statsPorTema = agruparPorTema(preguntas, respuestasUsuario, listaTemas);
  const mejorRacha = calcularMejorRacha(preguntas, respuestasUsuario);
  const mensajeRacha = mensajeMotivacional(mejorRacha);

  // Las preguntas marcadas como "duda" no cuentan para la nota principal
  // (como una pregunta anulada en un examen oficial: ni acierto ni fallo,
  // ni en el numerador ni en el denominador) -- solo se recalcula si se ha
  // marcado al menos una, para no cambiar la pantalla de resultados en el
  // caso común de que nadie use la función. Si se han marcado TODAS, no
  // queda ninguna con la que calcular nada y se usa la nota con todas
  // contando, para no mostrar un resultado vacío.
  const numDudas = marcadasDuda.filter(Boolean).length;
  let statsSinDudas = null;
  if (numDudas > 0) {
    const { stats: statsFiltradas, numRestantes } = calcularEstadisticasSinDudas(preguntas, respuestasUsuario, marcadasDuda);
    statsSinDudas = { ...statsFiltradas, numDudas, numRestantes };
  }
  const usaStatsSinDudas = !!(statsSinDudas && statsSinDudas.numRestantes > 0);
  const statsPrincipales = usaStatsSinDudas ? statsSinDudas : stats;

  let detalleHTML = "";
  preguntas.forEach((p, i) => {
    const correcta = p.respuesta_correcta || "No indicada";
    const seleccion = respuestasUsuario[i];
    const explicacion = p.explicacion || "Sin explicación.";
    let clase = "fallo";
    if (seleccion === correcta) clase = "acierto";
    else if (seleccion === null || seleccion === undefined) clase = "blanco";
    const claseCompleta = marcadasDuda[i] ? `${clase} duda` : clase;
    const avisoDudaHTML = marcadasDuda[i]
      ? ` <span class="aviso-pregunta-duda">${icono("pregunta", 14)} Pregunta marcada como dudosa</span>`
      : "";

    detalleHTML += `<div class="${claseCompleta}">
      <div class="pregunta-en-negrita">${i + 1}. ${escaparHtml(quitarNumeracion(p.pregunta))}${avisoDudaHTML}</div>`;
    if (p.imagen) {
      detalleHTML += `<div class="pregunta-imagen"><img src="${escaparHtml(p.imagen)}" alt="Figura de la pregunta ${i + 1}" loading="lazy"></div>`;
    }
    for (const letra in p.opciones) {
      let tipoRespuesta = "detalle-opcion";
      let iconoOpcion = "";
      if (letra === correcta) {
        tipoRespuesta = "detalle-opcion correcta";
        iconoOpcion = `<span class="icono-correcto">${icono("check", 15)}</span>`;
      }
      if (letra === seleccion && seleccion !== correcta) {
        tipoRespuesta = "detalle-opcion incorrecta";
        iconoOpcion = `<span class="icono-incorrecto">${icono("cruz", 15)}</span>`;
      }
      detalleHTML += `<div class="${tipoRespuesta}">${iconoOpcion}${letra}) ${escaparHtml(p.opciones[letra])}</div>`;
    }
    const idExp = `exp-${i}-${Math.random().toString(36).slice(2, 6)}`;
    detalleHTML += `<div class="detalle-acciones-fila">`;
    detalleHTML += `<button type="button" class="detalle-explicacion-btn" data-toggle-target="${idExp}">${icono("libro", 15)} Mostrar/Ocultar Explicación</button>`;
    // En todas las preguntas, acierte o no -- también en las acertadas se
    // puede querer pedir una aclaración adicional al tutor.
    detalleHTML += `<button type="button" class="detalle-tutor-btn" data-tutor="${i}" title="Que Tu Tutor te explique esta pregunta">${icono("graduacion", 15)} Pregúntale a Tu Tutor</button>`;
    detalleHTML += `<button type="button" class="detalle-reportar-btn" data-reportar="${i}" title="Avisar de un error en esta pregunta">${icono("alerta", 15)} Reportar error</button>`;
    detalleHTML += `</div>`;
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

  // La nota principal ya excluye las preguntas marcadas como duda (ver
  // statsPrincipales más arriba); aparte, en su propio bloque (no como una
  // tercera casilla más del mismo grid -- así se evita que una etiqueta
  // larga se salga de su caja en móvil), se explica con una frase qué nota
  // habría salido si esas preguntas SÍ contaran, con el mismo formato
  // "nota de este test / nota examen oficial" que arriba para que se lea
  // igual de claro. Si se han marcado TODAS las preguntas como duda no hay
  // con qué calcular esa alternativa, así que solo se avisa de que se han
  // contado igualmente.
  const notaAlternativaHTML = usaStatsSinDudas ? `
    <div class="resultado-nota-alternativa">
      <p class="resultado-nota-alternativa-texto">Teniendo en cuenta ${statsSinDudas.numDudas === 1 ? "la pregunta marcada" : `las ${statsSinDudas.numDudas} preguntas marcadas`} como dudosa${statsSinDudas.numDudas === 1 ? "" : "s"}, tu nota sería:</p>
      <div class="resultado-notas-grid resultado-notas-grid-alt">
        <div class="resultado-nota-box">
          <span class="resultado-nota-label">Nota de este test</span>
          <span class="resultado-nota-valor">${stats.nota}<small> / ${preguntas.length}</small></span>
        </div>
        <div class="resultado-nota-box">
          <span class="resultado-nota-label">Nota examen oficial</span>
          <span class="resultado-nota-valor">${stats.notaOficial100}<small> / 100</small></span>
        </div>
      </div>
      <p class="resultado-nota-alternativa-pie">${stats.apto ? "Seguirías aprobando." : "No aprobarías."}</p>
    </div>` : (numDudas > 0 ? `
    <div class="resultado-nota-alternativa">
      <p class="resultado-nota-alternativa-texto">Has marcado como duda las ${numDudas} preguntas del test: no queda ninguna otra con la que calcular una nota alternativa, así que se cuentan igualmente en la nota de arriba.</p>
    </div>` : "");

  contenedor.innerHTML = `
    <div class="resultado-resumen-card">
      <div class="resultado-veredicto ${statsPrincipales.apto ? "aprobado" : "suspendido"}">
        <span class="resultado-veredicto-texto">${statsPrincipales.apto ? icono("check", 16) + " Aprobado" : icono("cruz", 16) + " Suspendido"}</span>
      </div>

      <div class="resultado-notas-grid">
        <div class="resultado-nota-box">
          <span class="resultado-nota-label">Nota de este test</span>
          <span class="resultado-nota-valor"><span class="resultado-nota-num" data-hasta="${statsPrincipales.nota}" data-decimales="2">${statsPrincipales.nota}</span><small> / ${usaStatsSinDudas ? statsSinDudas.numRestantes : preguntas.length}</small></span>
        </div>
        <div class="resultado-nota-box">
          <span class="resultado-nota-label">Nota examen oficial</span>
          <span class="resultado-nota-valor"><span class="resultado-nota-num" data-hasta="${statsPrincipales.notaOficial100}" data-decimales="1">${statsPrincipales.notaOficial100}</span><small> / 100</small></span>
        </div>
      </div>
      ${notaAlternativaHTML}

      <div class="resultado-resumen-grid">
        <div class="resultado-resumen-tile tile-acierto">
          <span class="tile-info"><span class="tile-icono">${icono("check", 16)}</span>Aciertos</span>
          <span class="tile-valor">${statsPrincipales.aciertos}</span>
        </div>
        <div class="resultado-resumen-tile tile-fallo">
          <span class="tile-info"><span class="tile-icono">${icono("cruz", 16)}</span>Fallos</span>
          <span class="tile-valor">${statsPrincipales.fallos}</span>
        </div>
        <div class="resultado-resumen-tile tile-blanco">
          <span class="tile-info"><span class="tile-icono">${icono("pausa", 16)}</span>En blanco</span>
          <span class="tile-valor">${statsPrincipales.sinResponder}</span>
        </div>
        <div class="resultado-resumen-tile tile-porcentaje">
          <span class="tile-info"><span class="tile-icono">${icono("diana", 16)}</span>Acierto</span>
          <span class="tile-valor">${statsPrincipales.porcentaje}%</span>
        </div>
      </div>
      ${rachaHTML}
    </div>
    <div class="analisis-ia-bloque">
      <button type="button" id="btn-analisis-ia" class="btn age-btn-outline">${icono("robot", 16)} Ver análisis de mi rendimiento con IA</button>
      <div id="analisis-ia-resultado"></div>
    </div>
    <div class="resultado-temas-desplegable">
      <button type="button" class="resultado-toggle-btn resultado-temas-toggle" id="btn-temas-toggle" aria-expanded="false">
        <span class="resultado-toggle-icono">${icono("grafico", 16)}</span>
        <span class="resultado-toggle-texto">Estadísticas por tema</span>
        <span class="resultado-toggle-chevron">▾</span>
      </button>
      <div class="resultado-temas-panel" id="panel-temas" style="display:none;">${tablaTemasHTML}</div>
    </div>
    <div class="resultado-detalle-cabecera">
      <h3 class="resultado-detalle-titulo">${icono("lista", 18)} Detalle de preguntas</h3>
      <div class="resultado-filtro-dropdown" id="filtro-dropdown">
        <button type="button" class="resultado-toggle-btn resultado-filtro-btn" id="btn-filtro-preguntas" aria-expanded="false">
          <span class="resultado-toggle-icono">${icono("buscar", 16)}</span>
          <span class="resultado-toggle-texto" id="filtro-preguntas-label">Todas las preguntas</span>
          <span class="resultado-toggle-chevron">▾</span>
        </button>
        <div class="resultado-filtro-panel" id="panel-filtro-preguntas" style="display:none;">
          <label class="resultado-filtro-opcion"><input type="checkbox" data-filtro-valor="acierto" checked> ${icono("check", 14)} Aciertos</label>
          <label class="resultado-filtro-opcion"><input type="checkbox" data-filtro-valor="fallo" checked> ${icono("cruz", 14)} Fallos</label>
          <label class="resultado-filtro-opcion"><input type="checkbox" data-filtro-valor="blanco" checked> ${icono("pausa", 14)} En blanco</label>
          <label class="resultado-filtro-opcion"><input type="checkbox" data-filtro-valor="duda"> ${icono("pregunta", 14)} Dudosas</label>
        </div>
      </div>
    </div>
    <div class="lista-detalle-preguntas">${detalleHTML}</div>
  `;

  animarEntradaResultado(contenedor);

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
  const ETIQUETA_FILTRO = { acierto: "Aciertos", fallo: "Fallos", blanco: "En blanco", duda: "Dudosas" };

  // "duda" no es una categoría de corrección (acierto/fallo/blanco son
  // excluyentes entre sí y cubren el 100% de las preguntas) sino una marca
  // adicional que puede combinarse con cualquiera de ellas, así que se trata
  // aparte: cuando está marcada, restringe (AND) en vez de sumar (OR) al
  // conjunto de categorías activas.
  function aplicarFiltroPreguntas() {
    const activos = checksFiltro.filter((c) => c.checked).map((c) => c.dataset.filtroValor);
    const coreActivos = activos.filter((v) => v !== "duda");
    const soloDudas = activos.includes("duda");
    const todasCategorias = coreActivos.length === 0 || coreActivos.length === checksFiltro.length - 1;
    const etiquetas = [];
    if (!todasCategorias) etiquetas.push(...coreActivos.map((v) => ETIQUETA_FILTRO[v]));
    if (soloDudas) etiquetas.push("Dudosas");
    labelFiltro.textContent = etiquetas.length ? etiquetas.join(", ") : "Todas las preguntas";
    contenedor.querySelectorAll(".lista-detalle-preguntas > div").forEach((item) => {
      const coincideCategoria = todasCategorias || coreActivos.some((v) => item.classList.contains(v));
      const coincideDuda = !soloDudas || item.classList.contains("duda");
      item.style.display = coincideCategoria && coincideDuda ? "block" : "none";
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

  // "Pregúntale a Tu Tutor": abre la burbuja flotante ya cargada con esta
  // pregunta y su respuesta correcta. Disponible en todas las preguntas, no
  // solo en las falladas -- el mensaje inicial se adapta según se haya
  // acertado o no, para no dar por hecho un fallo que no existe.
  contenedor.querySelectorAll("[data-tutor]").forEach((boton) => {
    boton.addEventListener("click", () => {
      const indice = Number(boton.dataset.tutor);
      const p = preguntas[indice];
      if (!p) return;
      if (!window.tutorWidget || typeof window.tutorWidget.abrirConPregunta !== "function") {
        // El widget aún no ha montado (raro en esta pantalla): no romper nada.
        return;
      }
      const acerto = respuestasUsuario[indice] === p.respuesta_correcta;
      window.tutorWidget.abrirConPregunta({
        enunciado: quitarNumeracion(p.pregunta || ""),
        opciones: p.opciones || {},
        respuestaCorrecta: p.respuesta_correcta || "",
        respuestaUsuario: respuestasUsuario[indice],
        explicacion: p.explicacion || "",
        mensajeInicial: acerto
          ? "¿Puedes explicarme mejor esta pregunta? La he acertado pero quiero entenderla del todo."
          : "¿Puedes explicarme esta pregunta? Quiero entender por qué me he equivocado.",
      });
    });
  });

  // Reportar error en una pregunta: manda el texto de la pregunta y el motivo
  // a /reportar-pregunta (colección reportes_preguntas) para que el panel
  // admin lo revise. Se pide el motivo con un prompt sencillo.
  contenedor.querySelectorAll("[data-reportar]").forEach((boton) => {
    boton.addEventListener("click", async () => {
      const preg = preguntas[Number(boton.dataset.reportar)];
      if (!preg) return;
      const motivo = window.prompt("¿Qué error has visto en esta pregunta? Lo revisará el equipo.");
      if (!motivo || !motivo.trim()) return;
      boton.disabled = true;
      try {
        const [{ obtenerAuthHeaders }, { BACKEND_URL }, { obtenerOposicionActual }] = await Promise.all([
          import("/assets/auth.js"), import("/assets/firebase-config.js"), import("/assets/oposicion.js"),
        ]);
        const headers = await obtenerAuthHeaders();
        if (!headers) return;
        const resp = await fetch(BACKEND_URL + "/reportar-pregunta", {
          method: "POST",
          headers: { ...headers, "Content-Type": "application/json" },
          body: JSON.stringify({ pregunta_texto: preg.pregunta || "", motivo: motivo.trim(), oposicion: obtenerOposicionActual() }),
        });
        boton.textContent = resp.ok ? "Reportado, ¡gracias!" : "No se pudo reportar";
        if (!resp.ok) boton.disabled = false;
      } catch {
        boton.textContent = "No se pudo reportar";
        boton.disabled = false;
      }
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

  // Lo que se devuelve (y lo que se manda a descargarResultadosPDF) usa la
  // nota principal, que ya excluye las dudas -- "conDudas" lleva la cifra
  // alternativa de "si contaran" para que el PDF pueda mostrar la misma
  // aclaración que ya se ve en pantalla.
  return {
    ...statsPrincipales,
    totalPreguntas: usaStatsSinDudas ? statsSinDudas.numRestantes : preguntas.length,
    numDudas,
    conDudas: usaStatsSinDudas ? stats : null,
    todasDudas: numDudas > 0 && !usaStatsSinDudas,
  };
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
    doc.text("Domina tu Opo", margin, pageHeight - 10);
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
  doc.text(`Nota de este test: ${stats.nota} / ${stats.totalPreguntas ?? preguntas.length}   ·   Nota examen oficial: ${stats.notaOficial100} / 100 (${stats.apto ? "Aprobado" : "Suspendido"})`, pageWidth / 2, yPos, { align: "center" });
  yPos += 8;
  if (stats.conDudas) {
    doc.setTextColor(110);
    doc.text(`Si ${stats.numDudas === 1 ? "esa pregunta" : `esas ${stats.numDudas} preguntas`} marcada${stats.numDudas === 1 ? "" : "s"} como duda contara${stats.numDudas === 1 ? "" : "n"}: ${stats.conDudas.notaOficial100} / 100`, pageWidth / 2, yPos, { align: "center" });
    doc.setTextColor(0);
    yPos += 8;
  } else if (stats.todasDudas) {
    doc.setTextColor(110);
    doc.text(`Todas las preguntas se marcaron como duda: se cuentan igualmente para la nota.`, pageWidth / 2, yPos, { align: "center" });
    doc.setTextColor(0);
    yPos += 8;
  }
  yPos += 6;
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
