import { icono } from "/assets/icons.js";
import { marcarContenidoListo } from "/assets/auth.js";
import { activarPopover } from "/assets/popover.js";

function inyectarIconosEstaticos() {
  document.querySelectorAll("[data-icon]").forEach((el) => {
    el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 20));
  });
}

// Anillos de progreso (Nota media / Aprobados): el círculo relleno es en
// realidad un trazo con stroke-dasharray = circunferencia y
// stroke-dashoffset = circunferencia * (1 - pct/100) -- a "pct" en 100%
// no queda offset y el trazo se ve completo; a 0% el offset es la
// circunferencia entera y no se ve nada.
function actualizarAnillo(id, pct, nivel) {
  const circulo = document.getElementById(id);
  if (!circulo) return;
  const r = parseFloat(circulo.getAttribute("r")) || 42;
  const circunferencia = 2 * Math.PI * r;
  const pctSeguro = Math.max(0, Math.min(100, pct));
  circulo.style.strokeDasharray = `${circunferencia}`;
  circulo.style.strokeDashoffset = `${circunferencia * (1 - pctSeguro / 100)}`;
  circulo.classList.remove("nivel-bajo", "nivel-medio", "nivel-alto");
  if (nivel) circulo.classList.add(nivel);
}

// Línea+bola de "Tiempo dedicado": puramente decorativa (no representa
// datos reales, como tampoco lo hace en la referencia visual de la que
// parte este diseño). La bola recorre la línea de izquierda a derecha
// la primera vez que se visita esta página en cada sesión de navegador
// (sessionStorage) -- dentro de la misma sesión, en cargas o
// actualizaciones posteriores aparece ya fija en el punto final, sin
// repetir la animación cada vez. Se usa getPointAtLength en vez de CSS
// offset-path para que la posición encaje siempre con el trazado real
// del <path>, cualquiera que sea el ancho al que el SVG se escale en
// pantalla.
//
// La animación no se lanza nada más cargar la página: la tarjeta queda
// por debajo de "de un vistazo" (y a veces del aviso de temas flojos),
// así que si se animara en ese momento terminaría antes de que el
// usuario llegara a bajar hasta ahí -- se ve la bola ya quieta y parece
// que nunca se movió. En su lugar se espera a que la tarjeta entre en
// pantalla (IntersectionObserver) para reproducirla en el momento en que
// de verdad se puede ver.
function animarLineaTiempo(primeraVisita) {
  const trazado = document.getElementById("tiempo-linea");
  const bola = document.getElementById("tiempo-bola");
  const tarjeta = document.getElementById("tarjeta-tiempo");
  if (!trazado || !bola || !tarjeta) return;
  const longitudTotal = trazado.getTotalLength();
  const puntoFinal = trazado.getPointAtLength(longitudTotal);
  const sinMovimiento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (!primeraVisita || sinMovimiento) {
    bola.setAttribute("cx", puntoFinal.x);
    bola.setAttribute("cy", puntoFinal.y);
    return;
  }

  const puntoInicial = trazado.getPointAtLength(0);
  bola.setAttribute("cx", puntoInicial.x);
  bola.setAttribute("cy", puntoInicial.y);

  function reproducir() {
    // 2.6s y easeInOutCubic (arranca y termina suave, más rápida solo en
    // el tramo central) en vez de 1.4s con easeOut -- a menos de 1.5s el
    // movimiento pasaba casi desapercibido si no se estaba mirando fijo
    // a la tarjeta en el instante exacto en que entraba en pantalla.
    const duracionMs = 2600;
    let inicio = null;
    function easeInOutCubic(t) {
      return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    }
    function paso(marcaTiempo) {
      if (inicio === null) inicio = marcaTiempo;
      const progreso = Math.min((marcaTiempo - inicio) / duracionMs, 1);
      const suavizado = easeInOutCubic(progreso);
      const punto = trazado.getPointAtLength(longitudTotal * suavizado);
      bola.setAttribute("cx", punto.x);
      bola.setAttribute("cy", punto.y);
      if (progreso < 1) requestAnimationFrame(paso);
    }
    requestAnimationFrame(paso);
  }

  if (!("IntersectionObserver" in window)) {
    reproducir();
    return;
  }
  const observador = new IntersectionObserver((entradas) => {
    if (!entradas[0].isIntersecting) return;
    observador.disconnect();
    reproducir();
  }, { threshold: 0.4 });
  observador.observe(tarjeta);
}

// "puntuacion_final" guardado en historial_tests es la puntuación en
// bruto (aciertos - fallos/3, sin normalizar -- puede ser cualquier rango
// según el nº de preguntas del test), NO la nota sobre 10. Se recalcula
// aquí la nota sobre 10 a partir de aciertos/fallos/blancos (siempre
// presentes en cada entrada del historial), con la misma fórmula que
// calcular_resultado_test en utils.py, en vez de usar directamente ese
// campo -- usarlo tal cual producía notas absurdas (p.ej. 36.7) en la
// gráfica de evolución.
function notaSobre10(t) {
  const aciertos = t.aciertos || 0;
  const fallos = t.fallos || 0;
  const blancos = t.blancos || 0;
  const total = aciertos + fallos + blancos;
  if (!total) return 0;
  const puntuacion = aciertos - fallos / 3;
  return Math.round((puntuacion / total) * 1000) / 100;
}

// El backend guarda "fecha" con datetime.utcnow().isoformat(), que no lleva
// sufijo "Z" ni offset -- sin él, `new Date(...)` interpreta esos números
// como hora LOCAL en vez de UTC (así lo dice el propio estándar ECMA-262
// para cadenas de fecha-hora sin zona horaria). El resultado: un test hecho
// de madrugada en España (p. ej. 00:30, ya "hoy" en local pero todavía
// "ayer" en UTC con el huso de verano) podía aparecer bajo el día
// equivocado tanto en el calendario de estudio como en la gráfica de
// evolución. Forzando la "Z" se interpreta de verdad como UTC y luego se
// lee ya convertido a la hora local del navegador.
function parsearFechaUTC(fechaIso) {
  if (!fechaIso) return null;
  const iso = /Z|[+-]\d{2}:\d{2}$/.test(fechaIso) ? fechaIso : `${fechaIso}Z`;
  const d = new Date(iso);
  return isNaN(d) ? null : d;
}

function fechaLocalYMD(fechaIso) {
  const d = parsearFechaUTC(fechaIso);
  if (!d) return "";
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

async function obtenerAuthHeaders() {
  const { obtenerAuthHeaders: fn } = await import("/assets/auth.js");
  return fn();
}

document.addEventListener("DOMContentLoaded", async function () {
  inyectarIconosEstaticos();
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("basico"))) return;

  localStorage.setItem("age_visito_estadisticas", "1");

  // sessionStorage (no localStorage): se anima una vez por sesión de
  // navegador, no una única vez en la vida de la cuenta -- con
  // localStorage, en cuanto se veía una vez ya no volvía a jugarse jamás
  // en ese navegador, así que era fácil no llegar a verla nunca (por
  // ejemplo, si la tarjeta quedaba fuera de pantalla la primera vez).
  const primeraVisitaTiempo = !sessionStorage.getItem("age_estadisticas_tiempo_animado");
  sessionStorage.setItem("age_estadisticas_tiempo_animado", "1");
  // Solo se reproduce una vez por carga de página, aunque el usuario pulse
  // "actualizar" varias veces (cada pulsación vuelve a llamar a
  // cargarDatos, que dispara animarLineaTiempo en su bloque finally).
  let animacionTiempoYaLanzada = false;

  const refreshBtn = document.getElementById("estadisticas-refresh");
  const exportarPdfBtn = document.getElementById("estadisticas-exportar-pdf");
  let temasTest = [];
  let temasTocados = new Set();
  let datosParaExportarPDF = null;

  // Revela la página en cuanto se confirma el acceso, sin esperar a que
  // termine cargarDatos() -- antes se quedaba oculta hasta que las 3
  // peticiones de datos (estadísticas + temas + racha) terminaban, así
  // que en una conexión lenta la página entera parecía "quedarse
  // pillada" en blanco. El HTML ya trae de fábrica su propio esqueleto
  // (los "—" de "de un vistazo", los textos "Cargando…" del mapa de
  // temario/evolución/insignias) para ese hueco de tiempo -- es
  // exactamente lo que auth.js pide para llamar a marcarContenidoListo:
  // no hace falta esperar a los datos reales, solo a tener algo que
  // enseñar nada más entrar.
  marcarContenidoListo();

  // Función para cargar datos
  async function cargarDatos() {
    try {
      const { fijarTexto, fijarHTML } = await import("/assets/dom.js");
      // Resetear valores
      document.querySelectorAll('.valor').forEach(el => {
        if (!el.id.startsWith('tendencia')) {
          el.textContent = '...';
        }
      });
      document.querySelectorAll('.vistazo-mini-fill, .respuestas-segmento').forEach(el => el.style.width = '0%');
      document.querySelectorAll('.anillo-progreso').forEach(el => actualizarAnillo(el.id, 0, null));
      document.getElementById('tile-nota-media').removeAttribute('data-nivel');
      fijarHTML("tendencia-media", '<span>...</span>');
      fijarTexto("vistazo-aprobados-detalle", '— aprobados · — suspendidos');
      // Resetear valores PDF
      fijarTexto("total-archivos", '...');
      fijarTexto("total-tests-pdf", '...');
      fijarTexto("total-resumenes-pdf", '...');
      fijarTexto("total-esquemas-pdf", '...');
      fijarTexto("total-tarjetas-pdf", '...');
      fijarTexto("total-paginas", '...');
      refreshBtn.classList.add('loading');
      refreshBtn.disabled = true;

      const authHeaders = await obtenerAuthHeaders();
      if (!authHeaders) return;

      const { obtenerOposicionActual, OPOSICIONES } = await import("/assets/oposicion.js");
      const oposicion = obtenerOposicionActual();
      const sufijo = `?oposicion=${encodeURIComponent(oposicion)}`;

      // NUEVO: Usar la ruta de estadísticas completas que incluye datos PDF
      const [estadisticasRes, temasRes, rachaRes] = await Promise.all([
        fetch(`https://oposicion-age.onrender.com/estadisticas-completas${sufijo}`, { headers: authHeaders }),
        fetch(`https://oposicion-age.onrender.com/temas-disponibles${sufijo}`, { headers: authHeaders }),
        fetch(`https://oposicion-age.onrender.com/mi-racha`, { headers: authHeaders })
      ]);
      const estadisticasData = await estadisticasRes.json();
      const temasData = await temasRes.json();
      const racha = rachaRes.ok ? await rachaRes.json() : { racha_actual: 0, racha_maxima: 0 };
      const estadisticas = estadisticasData.estadisticas ?? {};

      // Si hay error, usar la ruta antigua como fallback
      if (estadisticas.error) {
        console.warn("Usando ruta antigua como fallback");
        const resumenRes = await fetch(`https://oposicion-age.onrender.com/resumen-progreso${sufijo}`, { headers: authHeaders });
        const resumenData = await resumenRes.json();
        procesarDatos(resumenData.resumen ?? {}, temasData.temas || [], racha, oposicion, OPOSICIONES);
      } else {
        procesarDatos(estadisticas, temasData.temas || [], racha, oposicion, OPOSICIONES);
      }
    } catch (err) {
      console.error("Error cargando estadísticas:", err);
      const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
      mostrarErrorGlobal("No se han podido cargar tus estadísticas. Comprueba tu conexión e inténtalo de nuevo.");
    } finally {
      refreshBtn.classList.remove('loading');
      refreshBtn.disabled = false;
      // marcarContenidoListo() ya se llamó al entrar (ver más arriba);
      // aquí solo queda lanzar la animación de la bola, aplazada con
      // requestAnimationFrame porque animarLineaTiempo mide el <path>
      // con getTotalLength/getPointAtLength, que fuerza a recalcular el
      // layout del SVG.
      requestAnimationFrame(() => {
        animarLineaTiempo(primeraVisitaTiempo && !animacionTiempoYaLanzada);
        animacionTiempoYaLanzada = true;
      });
    }
  }

  function procesarDatos(estadisticas, todosTemas, racha, oposicion, OPOSICIONES) {
    const totalTests = estadisticas.tests_realizados ?? 0;
    const totalAciertos = estadisticas.total_aciertos ?? 0;
    const totalFallos = estadisticas.total_fallos ?? 0;
    const totalBlancos = estadisticas.total_blancos ?? 0;
    const historial = estadisticas.historial_tests ?? [];
    temasTest = estadisticas.temas_test ?? [];
    const rendimientoPorTema = estadisticas.rendimiento_por_tema ?? {};
    const esquemas = estadisticas.esquemas_realizados ?? 0;
    const aprobados = estadisticas.tests_aprobados ?? 0;
    const suspendidos = estadisticas.tests_suspendidos ?? 0;
    const puntuacionMedia = estadisticas.puntuacion_media_test ?? 0;
    const tiempoTotalSegundos = estadisticas.tiempo_total ?? 0;

    // NUEVOS DATOS PDF
    const testsPdf = estadisticas.tests_pdf_realizados ?? estadisticas.total_tests_pdf ?? 0;
    const resumenesPdf = estadisticas.resumenes_pdf_realizados ?? estadisticas.total_resumenes_pdf ?? 0;
    const esquemasPdf = estadisticas.esquemas_pdf_realizados ?? estadisticas.total_esquemas_pdf ?? 0;
    const tarjetasPdf = estadisticas.tarjetas_pdf_realizados ?? estadisticas.total_tarjetas_pdf ?? 0;
    const totalArchivos = estadisticas.total_archivos_procesados ?? 0;
    const totalPaginas = estadisticas.paginas_analizadas ?? 0;

    const horas = String(Math.floor(tiempoTotalSegundos / 3600)).padStart(2, '0');
    const minutos = String(Math.floor((tiempoTotalSegundos % 3600) / 60)).padStart(2, '0');

    const porcentajeAprobados = totalTests > 0 ? Math.round((aprobados / totalTests) * 100) : 0;
    const porcentajeSuspendidos = totalTests > 0 ? Math.round((suspendidos / totalTests) * 100) : 0;
    const totalRespuestas = totalAciertos + totalFallos + totalBlancos;
    const porcentajeAciertos = totalRespuestas > 0
      ? Math.round((totalAciertos / totalRespuestas) * 100)
      : 0;
    const porcentajeFallos = totalRespuestas > 0
      ? Math.round((totalFallos / totalRespuestas) * 100)
      : 0;
    const porcentajeBlancos = totalRespuestas > 0
      ? Math.round((totalBlancos / totalRespuestas) * 100)
      : 0;

    const todosLosTemasIds = todosTemas.map(t => t.id);
    temasTocados = new Set([...temasTest, ...Object.keys(rendimientoPorTema)]);

    // Actualizar estadísticas principales
    document.getElementById("vistazo-tests").textContent = totalTests;
    document.getElementById("vistazo-media").textContent = puntuacionMedia.toFixed(1);
    document.getElementById("vistazo-racha").textContent = racha.racha_actual ?? 0;

    // Nota media (0-10): mismos umbrales que la tendencia de más abajo
    // (rojo por debajo de 3, verde a partir de más de 5, ámbar en medio)
    // para que el color del anillo, el tinte de la tarjeta y la pastilla
    // de tendencia cuenten siempre la misma historia.
    const nivelNota = puntuacionMedia < 3 ? "nivel-bajo" : puntuacionMedia > 5 ? "nivel-alto" : "nivel-medio";
    document.getElementById("tile-nota-media").dataset.nivel = nivelNota.replace("nivel-", "");
    actualizarAnillo("anillo-media", (puntuacionMedia / 10) * 100, nivelNota);

    // Por debajo del 25% es una mala señal (rojo), de 25% a 50% aviso
    // (ámbar), y solo a partir del 50% es un dato realmente positivo
    // (verde) -- antes salía siempre en verde, dando la sensación de que
    // iba bien aunque el % de aprobados fuera muy bajo.
    const nivelAprobados = porcentajeAprobados < 25 ? "nivel-bajo" : porcentajeAprobados < 50 ? "nivel-medio" : "nivel-alto";
    const fillEl = document.getElementById("vistazo-aprobados-fill");
    document.getElementById("vistazo-aprobados-pct").textContent = `${porcentajeAprobados}%`;
    actualizarAnillo("anillo-aprobados", porcentajeAprobados, nivelAprobados);
    fillEl.classList.remove("nivel-bajo", "nivel-medio", "nivel-alto");
    fillEl.classList.add(nivelAprobados);
    document.getElementById("vistazo-aprobados-detalle").textContent = `${aprobados} aprobados · ${suspendidos} suspendidos`;
    fillEl.style.width = `${porcentajeAprobados}%`;

    document.getElementById("aciertos").textContent = totalAciertos;
    document.getElementById("fallos").textContent = totalFallos;
    document.getElementById("blancos").textContent = totalBlancos;
    document.getElementById("tiempo").textContent = `${horas}h ${minutos}m`;

    document.getElementById("aciertos-porcentaje").textContent = porcentajeAciertos;
    document.getElementById("fallos-porcentaje").textContent = porcentajeFallos;
    document.getElementById("blancos-porcentaje").textContent = porcentajeBlancos;

    document.getElementById("barra-aciertos").style.width = `${porcentajeAciertos}%`;
    document.getElementById("barra-fallos").style.width = `${porcentajeFallos}%`;
    document.getElementById("barra-blancos").style.width = `${porcentajeBlancos}%`;

    let tendenciaHTML = '<span class="tendencia-neutral">→ Estable</span>';
    if (puntuacionMedia > 5) {
      tendenciaHTML = `<span class="tendencia-up">↑ Mejorando</span>`;
    } else if (puntuacionMedia < 3) {
      tendenciaHTML = `<span class="tendencia-down">↓ Requiere atención</span>`;
    }
    document.getElementById("tendencia-media").innerHTML = tendenciaHTML;

    // NUEVO: Actualizar estadísticas PDF
    document.getElementById("total-archivos").textContent = totalArchivos;
    document.getElementById("total-tests-pdf").textContent = testsPdf;
    document.getElementById("total-resumenes-pdf").textContent = resumenesPdf;
    document.getElementById("total-esquemas-pdf").textContent = esquemasPdf;
    document.getElementById("total-tarjetas-pdf").textContent = tarjetasPdf;
    document.getElementById("total-paginas").textContent = totalPaginas;

    mostrarTemasFlojos(rendimientoPorTema, todosTemas);
    pintarMapaTemario(todosTemas, rendimientoPorTema);
    renderizarCoberturaTemario(temasTocados.size, todosLosTemasIds.length);
    renderizarEvolucion(historial);
    renderizarCalendarioRacha(historial);
    const insigniasConseguidas = renderizarInsignias({
      testsRealizados: totalTests,
      testsAprobados: aprobados,
      puntuacionMedia: puntuacionMedia,
      esquemas: esquemas,
      totalArchivos: totalArchivos,
      rachaMaxima: racha.racha_maxima ?? 0
    });

    const temasFlojosPDF = Object.entries(rendimientoPorTema || {})
      .map(([id, r]) => {
        const respondidas = (r.aciertos || 0) + (r.fallos || 0);
        const porcentajeAcierto = respondidas > 0 ? Math.round((r.aciertos / respondidas) * 100) : null;
        const tema = todosTemas.find(x => x.id === id);
        return { nombre: tema ? tema.titulo : `Tema ${id}`, respondidas, porcentaje: porcentajeAcierto };
      })
      .filter(t => t.respondidas >= MINIMO_PREGUNTAS_FLOJO && t.porcentaje !== null && t.porcentaje < UMBRAL_ACIERTO_FLOJO)
      .sort((a, b) => a.porcentaje - b.porcentaje)
      .slice(0, 3);

    datosParaExportarPDF = {
      nombreOposicion: (OPOSICIONES.find(o => o.id === oposicion) || {}).nombre || "Domina tu Opo",
      testsRealizados: totalTests,
      testsAprobados: aprobados,
      testsSuspendidos: suspendidos,
      porcentajeAprobados,
      porcentajeSuspendidos,
      puntuacionMedia,
      tiempoTotalTexto: `${horas}h ${minutos}m`,
      totalAciertos,
      totalFallos,
      totalBlancos,
      porcentajeAciertos,
      porcentajeFallos,
      porcentajeBlancos,
      temasFlojos: temasFlojosPDF,
      insigniasConseguidas,
      historialReciente: historial.slice(-10).map(t => ({
        fecha: t.fecha,
        nota: notaSobre10(t),
        resultado: t.resultado
      })),
      nombreArchivo: "resumen-progreso.pdf"
    };
  }

  // Insignias: logros calculados a partir de datos que ya se piden para el
  // resto de la página (más /mi-racha), sin ninguna ruta nueva. Cada una
  // tiene un umbral simple; si no está conseguida se muestra en gris con
  // el progreso actual para animar a seguir usando la web.
  const INSIGNIAS = [
    { icono: "diana", titulo: "Primer test", descripcion: "Completa tu primer test", valor: (d) => d.testsRealizados, umbral: 1, unidad: "test" },
    { icono: "fuego", titulo: "Racha de 3 días", descripcion: "Estudia 3 días seguidos", valor: (d) => d.rachaMaxima, umbral: 3, unidad: "días" },
    { icono: "fuego", titulo: "Racha de 7 días", descripcion: "Estudia 7 días seguidos", valor: (d) => d.rachaMaxima, umbral: 7, unidad: "días" },
    { icono: "fuego", titulo: "Racha de 30 días", descripcion: "Estudia 30 días seguidos", valor: (d) => d.rachaMaxima, umbral: 30, unidad: "días" },
    { icono: "libros", titulo: "10 tests", descripcion: "Completa 10 tests", valor: (d) => d.testsRealizados, umbral: 10, unidad: "tests" },
    { icono: "graduacion", titulo: "50 tests", descripcion: "Completa 50 tests", valor: (d) => d.testsRealizados, umbral: 50, unidad: "tests" },
    { icono: "check", titulo: "10 aprobados", descripcion: "Aprueba 10 tests", valor: (d) => d.testsAprobados, umbral: 10, unidad: "aprobados" },
    { icono: "trofeo", titulo: "Excelencia", descripcion: "Nota media de 8 o más", valor: (d) => d.puntuacionMedia, umbral: 8, unidad: "puntos" },
    { icono: "esquema", titulo: "Esquematizador", descripcion: "Genera 5 esquemas", valor: (d) => d.esquemas, umbral: 5, unidad: "esquemas" },
    { icono: "documento", titulo: "Documentalista", descripcion: "Sube 3 documentos PDF", valor: (d) => d.totalArchivos, umbral: 3, unidad: "documentos" }
  ];

  function renderizarInsignias(datos) {
    const contenedor = document.getElementById("insignias-grid");
    const conseguidas = [];
    const pendientes = [];
    contenedor.innerHTML = INSIGNIAS.map((insignia) => {
      const actual = insignia.valor(datos) || 0;
      const conseguida = actual >= insignia.umbral;
      if (conseguida) {
        conseguidas.push(insignia.titulo);
      } else {
        pendientes.push({ insignia, actual, progreso: actual / insignia.umbral });
      }
      const actualMostrado = Number.isInteger(insignia.umbral) ? Math.floor(Math.min(actual, insignia.umbral)) : Math.min(actual, insignia.umbral).toFixed(1);
      return `
        <div class="insignia${conseguida ? " conseguida" : ""}" title="${insignia.descripcion}">
          <div class="insignia-icono">${icono(insignia.icono, 22)}</div>
          <div class="insignia-titulo">${insignia.titulo}</div>
          <div class="insignia-estado">${conseguida ? "Conseguida" : `${actualMostrado}/${insignia.umbral}`}</div>
        </div>
      `;
    }).join("");

    renderizarInsigniaSiguiente(pendientes);
    return conseguidas;
  }

  function renderizarInsigniaSiguiente(pendientes) {
    const contenedor = document.getElementById("insignia-siguiente");
    // La "más cercana" es la de mayor progreso relativo (actual/umbral), y
    // solo se muestra si hay algo de progreso real -- si el usuario aún no
    // ha hecho nada, sugerir "te faltan 8 puntos de nota" no tiene sentido.
    const candidatas = pendientes.filter(p => p.progreso > 0);
    if (candidatas.length === 0) {
      contenedor.style.display = "none";
      return;
    }
    const mejor = candidatas.reduce((a, b) => (b.progreso > a.progreso ? b : a));
    const { insignia, actual } = mejor;
    const restante = insignia.umbral - actual;
    const restanteTexto = Number.isInteger(insignia.umbral) ? Math.ceil(restante) : restante.toFixed(1);

    contenedor.innerHTML = `
      <span class="insignia-siguiente-icono">${icono(insignia.icono, 20)}</span>
      <span class="insignia-siguiente-texto">Te falta poco para <strong>${insignia.titulo}</strong>: ${restanteTexto} ${insignia.unidad} más y la consigues.</span>
    `;
    contenedor.style.display = "flex";
  }

  // Gráfica de evolución de la nota: una línea sencilla en SVG (sin
  // depender de ninguna librería) con los últimos tests, en la misma
  // escala 0-10 que "Puntuación media". Cada punto se colorea según si
  // ese test se aprobó o no, y muestra un tooltip nativo con la fecha.
  const MAX_TESTS_EVOLUCION = 15;

  function renderizarEvolucion(historial) {
    const contenedor = document.getElementById("evolucion-grafica");
    const vacio = document.getElementById("evolucion-vacio");
    const caption = document.getElementById("evolucion-caption");
    const tarjeta = document.getElementById("tarjeta-evolucion");
    const recientes = historial.slice(-MAX_TESTS_EVOLUCION);

    if (recientes.length < 2) {
      contenedor.style.display = "none";
      caption.style.display = "none";
      vacio.style.display = "block";
      return;
    }
    contenedor.style.display = "block";
    vacio.style.display = "none";

    // El viewBox usa el ancho REAL en px del contenedor (no un ancho fijo
    // arbitrario) y una altura fija -- así el mapeo es 1:1 en vez de
    // depender de que el navegador reescale el SVG de forma uniforme o no
    // uniforme, que antes dejaba el texto (fechas, eje 0/5/10) aplastado
    // en pantallas estrechas o diminuto si se corregía solo con
    // aspect-ratio.
    const ancho = Math.max(280, Math.round(contenedor.getBoundingClientRect().width));
    const alto = 190;
    const margenIzq = 20;
    const margenDer = 20;
    const margenSup = 20;
    // Margen inferior más grande que el resto -- deja hueco para las
    // fechas del eje X (antes no había ninguna referencia de fecha visible
    // en la propia gráfica, solo en el texto de mejor/peor debajo).
    const margenInf = 40;
    const notas = recientes.map(notaSobre10);
    const paso = (ancho - margenIzq - margenDer) / (recientes.length - 1);

    const coordX = (i) => margenIzq + i * paso;
    // Se acota la nota a [0, 10] solo para calcular la posición en el
    // gráfico (un test muy malo con muchos fallos puede dar una nota
    // negativa según la fórmula oficial) -- así un caso extremo se queda
    // pegado al borde en vez de disparar la línea fuera del recuadro.
    const coordY = (nota) => alto - margenInf - (Math.max(0, Math.min(10, nota)) / 10) * (alto - margenSup - margenInf);

    const puntos = notas.map((nota, i) => `${coordX(i)},${coordY(nota)}`).join(" ");

    // Se marca con un círculo más grande el mejor y el peor test del
    // periodo mostrado, para que salten a la vista sin tener que pasar el
    // ratón por cada punto.
    const mejorIdx = notas.indexOf(Math.max(...notas));
    const peorIdx = notas.indexOf(Math.min(...notas));

    const circulos = recientes.map((t, i) => {
      const nota = notas[i];
      const esExtremo = i === mejorIdx || i === peorIdx;
      const color = t.resultado === "aprobado" ? "var(--age-success)" : "var(--age-danger)";
      const fecha = parsearFechaUTC(t.fecha)?.toLocaleDateString("es-ES") ?? "";
      const claseExtra = esExtremo ? " evolucion-punto-extremo" : "";
      return `<circle cx="${coordX(i)}" cy="${coordY(nota)}" r="${esExtremo ? 6 : 4}" fill="${color}" class="${claseExtra}"><title>${fecha}: ${nota.toFixed(1)}/10</title></circle>`;
    }).join("");

    const lineaAprobado = coordY(5);
    const ejeX = margenIzq - 4;
    const ejeLabels = `
      <text x="${ejeX}" y="${coordY(10) + 3}" text-anchor="end" class="evolucion-eje-texto">10</text>
      <text x="${ejeX}" y="${coordY(5) + 3}" text-anchor="end" class="evolucion-eje-texto">5</text>
      <text x="${ejeX}" y="${coordY(0) + 3}" text-anchor="end" class="evolucion-eje-texto">0</text>
    `;

    // Fechas bajo el eje X: no se etiqueta cada punto (con 15 tests se
    // amontonarían), se reparten como mucho ~6 etiquetas incluyendo
    // siempre el primero y el último.
    const MAX_ETIQUETAS_FECHA = 6;
    const salto = Math.max(1, Math.ceil(recientes.length / MAX_ETIQUETAS_FECHA));
    const indicesEtiquetas = [];
    for (let i = 0; i < recientes.length; i += salto) indicesEtiquetas.push(i);
    if (indicesEtiquetas[indicesEtiquetas.length - 1] !== recientes.length - 1) {
      indicesEtiquetas.push(recientes.length - 1);
    }
    const yEtiquetaFecha = alto - margenInf + 16;
    const etiquetasFecha = indicesEtiquetas.map((i) => {
      const t = recientes[i];
      if (!t.fecha) return "";
      const fechaCorta = parsearFechaUTC(t.fecha)?.toLocaleDateString("es-ES", { day: "numeric", month: "numeric" }) ?? "";
      return `<text x="${coordX(i)}" y="${yEtiquetaFecha}" text-anchor="middle" class="evolucion-eje-texto">${fechaCorta}</text>`;
    }).join("");

    contenedor.innerHTML = `
      <svg viewBox="0 0 ${ancho} ${alto}" class="evolucion-svg">
        <line x1="${margenIzq}" y1="${lineaAprobado}" x2="${ancho - margenDer}" y2="${lineaAprobado}" class="evolucion-linea-aprobado" />
        ${ejeLabels}
        ${etiquetasFecha}
        <polyline points="${puntos}" fill="none" class="evolucion-linea" />
        ${circulos}
      </svg>
    `;
    tarjeta.style.display = "flex";

    const fechaMejor = parsearFechaUTC(recientes[mejorIdx].fecha)?.toLocaleDateString("es-ES") ?? "";
    const fechaPeor = parsearFechaUTC(recientes[peorIdx].fecha)?.toLocaleDateString("es-ES") ?? "";
    caption.textContent = `Mejor: ${notas[mejorIdx].toFixed(1)} (${fechaMejor}) · Peor: ${notas[peorIdx].toFixed(1)} (${fechaPeor})`;
    caption.style.display = "block";
  }

  // Se muestran siempre los 3 temas con peor % de acierto que tengan al
  // menos una pregunta respondida (antes esta tarjeta y la de "Peor
  // rendimiento" de la sección "Tus temas" mostraban prácticamente la
  // misma lista por separado -- ahora es un único sitio). El tono del
  // mensaje sí cambia: solo se pone en plan de alarma si de verdad hay
  // algún tema por debajo del umbral de "flojo" (>= 3 preguntas y < 60%
  // de acierto, para que no sea ruido de una sola pregunta con mala
  // suerte); si no, es simplemente informativo.
  const UMBRAL_ACIERTO_FLOJO = 60;
  const MINIMO_PREGUNTAS_FLOJO = 3;
  const MINIMO_PREGUNTAS_RANKING = 1;

  function mostrarTemasFlojos(rendimientoPorTema, todosTemas) {
    const tarjeta = document.getElementById("tarjeta-temas-flojos");
    const lista = document.getElementById("lista-temas-flojos");
    const descripcion = document.getElementById("recomendacion-descripcion");

    const temasConDatos = Object.entries(rendimientoPorTema || {})
      .map(([id, r]) => {
        const respondidas = (r.aciertos || 0) + (r.fallos || 0);
        const porcentaje = respondidas > 0 ? Math.round((r.aciertos / respondidas) * 100) : null;
        return { id, respondidas, porcentaje };
      })
      .filter(t => t.respondidas >= MINIMO_PREGUNTAS_RANKING && t.porcentaje !== null)
      .sort((a, b) => a.porcentaje - b.porcentaje)
      .slice(0, 3);

    if (temasConDatos.length === 0) {
      tarjeta.style.display = "none";
      return;
    }

    const hayAlarma = temasConDatos.some(t => t.respondidas >= MINIMO_PREGUNTAS_FLOJO && t.porcentaje < UMBRAL_ACIERTO_FLOJO);
    descripcion.textContent = hayAlarma
      ? "Estos son los temas donde menos aciertas. Un repaso rápido ahora mismo puede subirte mucho la nota."
      : "Todavía no tienes ningún tema por debajo del 60% de acierto -- aquí tienes los que más margen de mejora tienen.";

    lista.innerHTML = "";
    temasConDatos.forEach(t => {
      const tema = todosTemas.find(x => x.id === t.id);
      const nombre = tema ? tema.titulo : `Tema ${t.id}`;
      const li = document.createElement("li");
      li.innerHTML = `
        <div class="tema-flojo-info">
          <span class="tema-flojo-nombre" title="${nombre}">${nombre}</span>
          <span class="tema-flojo-porcentaje">${t.porcentaje}% de acierto</span>
        </div>
        <a class="btn-repasar-tema" href="/test-personalizado/?temas=${encodeURIComponent(t.id)}">Repasar</a>
      `;
      lista.appendChild(li);
    });
    tarjeta.style.display = "block";
  }

  // Mapa de temario: bloques x temas coloreados por % de acierto real,
  // en vez de solo "estudiado sí/no" (que es lo que ya cuentan Cobertura
  // y Temas no estudiados/más estudiados). Mismos umbrales que
  // mostrarTemasFlojos (>=3 preguntas para tener confianza en el %),
  // pero aquí en vez de ocultar los temas con pocas preguntas se pintan
  // igual (con menor énfasis) para no dejar huecos raros en el mapa.
  async function pintarMapaTemario(todosTemas, rendimientoPorTema) {
    const contenedor = document.getElementById("mapa-temario-bloques");
    const vacio = document.getElementById("mapa-temario-vacio");
    if (!contenedor) return;
    if (!todosTemas || todosTemas.length === 0) {
      contenedor.innerHTML = "";
      if (vacio) vacio.style.display = "block";
      return;
    }
    if (vacio) vacio.style.display = "none";

    const { agruparTemasPorBloque } = await import("/assets/temas-numeracion.js");
    const grupos = agruparTemasPorBloque(todosTemas);

    contenedor.innerHTML = grupos.map((grupo) => {
      const celdas = grupo.temas.map((t) => {
        const r = (rendimientoPorTema || {})[t.id];
        const respondidas = r ? (r.aciertos || 0) + (r.fallos || 0) : 0;
        const porcentaje = respondidas > 0 ? Math.round((r.aciertos / respondidas) * 100) : null;
        const pocasPreguntas = respondidas > 0 && respondidas < MINIMO_PREGUNTAS_FLOJO;

        let nivel = "sin-datos";
        if (porcentaje !== null) {
          nivel = porcentaje < 50 ? "nivel-1" : porcentaje < 65 ? "nivel-2" : porcentaje < 80 ? "nivel-3" : "nivel-4";
        }

        const detalle = porcentaje === null
          ? "Todavía sin preguntas respondidas"
          : `${porcentaje}% de acierto (${respondidas} pregunta${respondidas === 1 ? "" : "s"})${pocasPreguntas ? " -- pocas preguntas todavía" : ""}`;
        const clases = ["mapa-temario-celda", nivel, pocasPreguntas ? "pocas-preguntas" : ""].filter(Boolean).join(" ");
        const href = `/test-personalizado/?temas=${encodeURIComponent(t.id)}`;

        // El nivel de acierto no puede depender solo del color de la
        // celda (daltonismo, y en móvil no hay hover para el title): el
        // popover muestra el % exacto como texto antes de ir a practicar,
        // con el mismo patrón de activarPopover() que el resto del sitio.
        return `
          <div class="mapa-temario-celda-root">
            <button type="button" class="${clases}" data-popover-toggle aria-label="Tema ${t.numeroTema}: ${t.titulo}, ${detalle}">${t.numeroTema}</button>
            <div class="age-popover mapa-temario-celda-panel" data-popover-panel>
              <p class="mapa-temario-celda-panel-titulo">Tema ${t.numeroTema}: ${t.titulo}</p>
              <p class="mapa-temario-celda-panel-detalle">${detalle}</p>
              <a class="mapa-temario-celda-panel-cta" href="${href}">Practicar este tema →</a>
            </div>
          </div>
        `;
      }).join("");

      return `
        <div class="mapa-temario-bloque">
          <div class="mapa-temario-bloque-titulo">Bloque ${grupo.numeroRomano}: ${grupo.titulo}</div>
          <div class="mapa-temario-grid">${celdas}</div>
        </div>
      `;
    }).join("");

    // El panel se centra sobre la celda por defecto (ver CSS), pero en
    // celdas pegadas al borde de la rejilla eso lo saca de la pantalla --
    // se corrige aquí midiendo su posición real cada vez que se abre, en
    // vez de fijar un único borde que solo funciona en el resto de casos.
    contenedor.querySelectorAll(".mapa-temario-celda-root").forEach((raiz) => {
      activarPopover(raiz, {
        onAbrir: () => {
          const panel = raiz.querySelector(".mapa-temario-celda-panel");
          if (!panel) return;
          panel.style.left = "";
          panel.style.right = "";
          panel.style.transform = "";
          const margen = 8;
          const rect = panel.getBoundingClientRect();
          if (rect.left < margen) {
            panel.style.left = "0";
            panel.style.transform = "none";
          } else if (rect.right > window.innerWidth - margen) {
            panel.style.left = "auto";
            panel.style.right = "0";
            panel.style.transform = "none";
          }
        },
      });
    });
  }

  function renderizarCoberturaTemario(totalTocados, totalTemas) {
    const porcentaje = totalTemas > 0 ? Math.round((totalTocados / totalTemas) * 100) : 0;
    document.getElementById("cobertura-texto").textContent = `${totalTocados} de ${totalTemas} temas trabajados`;
    document.getElementById("cobertura-porcentaje").textContent = `${porcentaje}%`;
    document.getElementById("cobertura-fill").style.width = `${porcentaje}%`;
  }

  // Calendario de estudio: vista de mes real (no un mapa de calor de
  // semanas), navegable hacia atrás/adelante o saltando a un mes/año
  // concreto. Los días con actividad salen de las fechas de
  // "historial_tests" (única fuente real disponible hoy; no hay un
  // registro diario de actividad general, solo de tests).
  let historialCalendario = [];
  let mesCalendarioActual = null; // Date con día 1 del mes mostrado

  function renderizarCalendarioRacha(historial) {
    historialCalendario = historial || [];
    const tarjeta = document.getElementById("tarjeta-calendario");
    const titulo = document.getElementById("calendario-titulo");
    if (historialCalendario.length === 0) {
      tarjeta.style.display = "none";
      titulo.style.display = "none";
      return;
    }
    if (!mesCalendarioActual) {
      const hoy = new Date();
      mesCalendarioActual = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
    }
    tarjeta.style.display = "flex";
    titulo.style.display = "block";
    pintarCalendarioMes();
  }

  function pintarCalendarioMes() {
    const contenedor = document.getElementById("calendario-grafica");
    const etiquetaMes = document.getElementById("calendario-mes-actual");
    const inputMes = document.getElementById("calendario-mes-input");
    const botonSiguiente = document.getElementById("calendario-mes-siguiente");

    const anio = mesCalendarioActual.getFullYear();
    const mes = mesCalendarioActual.getMonth();

    // Cuántos tests hizo cada día, para pintar una escala de intensidad
    // (1 test = verde claro, 2 = verde medio, 3+ = verde oscuro) en vez de
    // un simple sí/no.
    const testsPorDia = new Map();
    historialCalendario.forEach(t => {
      const clave = fechaLocalYMD(t.fecha);
      if (!clave) return;
      testsPorDia.set(clave, (testsPorDia.get(clave) || 0) + 1);
    });

    const hoy = new Date();
    hoy.setHours(0, 0, 0, 0);
    const esMesActual = anio === hoy.getFullYear() && mes === hoy.getMonth();

    etiquetaMes.textContent = mesCalendarioActual.toLocaleDateString("es-ES", { month: "long", year: "numeric" });
    inputMes.value = `${anio}-${String(mes + 1).padStart(2, "0")}`;
    // No tiene sentido navegar a meses futuros (no puede haber tests ahí).
    botonSiguiente.disabled = esMesActual;

    // Lunes = 0 ... domingo = 6, para que la rejilla empiece en lunes.
    const primerDiaSemana = (new Date(anio, mes, 1).getDay() + 6) % 7;
    const diasEnMes = new Date(anio, mes + 1, 0).getDate();

    const celdas = [];
    for (let i = 0; i < primerDiaSemana; i++) {
      celdas.push(`<div class="calendario-celda vacia"></div>`);
    }
    for (let dia = 1; dia <= diasEnMes; dia++) {
      const clave = `${anio}-${String(mes + 1).padStart(2, "0")}-${String(dia).padStart(2, "0")}`;
      const numTests = testsPorDia.get(clave) || 0;
      const nivel = numTests >= 3 ? "nivel-3" : numTests === 2 ? "nivel-2" : numTests === 1 ? "nivel-1" : "";
      const esHoy = esMesActual && dia === hoy.getDate();
      const clases = ["calendario-celda", nivel, esHoy ? "hoy" : ""].filter(Boolean).join(" ");
      const titulo = numTests === 0 ? `${dia}` : `${dia}: ${numTests} test${numTests === 1 ? "" : "s"}`;
      celdas.push(`<div class="${clases}" title="${titulo}">${dia}</div>`);
    }
    contenedor.innerHTML = celdas.join("");
  }

  // Cierre sin persistencia: si el usuario se va a otra página y vuelve
  // (o simplemente recarga), el aviso vuelve a aparecer si sigue habiendo
  // temas con margen de mejora -- a diferencia del onboarding, aquí no
  // interesa que se quede oculto para siempre, porque los temas flojos
  // cambian con el tiempo y es información que conviene seguir viendo.
  document.getElementById("recomendacion-cerrar").addEventListener("click", () => {
    document.getElementById("tarjeta-temas-flojos").style.display = "none";
  });

  document.getElementById("calendario-mes-anterior").addEventListener("click", () => {
    mesCalendarioActual.setMonth(mesCalendarioActual.getMonth() - 1);
    pintarCalendarioMes();
  });
  document.getElementById("calendario-mes-siguiente").addEventListener("click", () => {
    mesCalendarioActual.setMonth(mesCalendarioActual.getMonth() + 1);
    pintarCalendarioMes();
  });
  document.getElementById("calendario-mes-input").addEventListener("change", (evento) => {
    const [anio, mes] = evento.target.value.split("-").map(Number);
    if (!anio || !mes) return;
    mesCalendarioActual = new Date(anio, mes - 1, 1);
    pintarCalendarioMes();
  });

  refreshBtn.addEventListener('click', cargarDatos);

  exportarPdfBtn.addEventListener('click', async () => {
    if (!datosParaExportarPDF) return;
    exportarPdfBtn.disabled = true;
    const textoOriginal = exportarPdfBtn.textContent;
    exportarPdfBtn.textContent = "Generando…";
    try {
      const { descargarResumenProgresoPDF } = await import("/assets/progreso-pdf.js");
      descargarResumenProgresoPDF(datosParaExportarPDF);
    } catch (e) {
      console.error("Error exportando el PDF de progreso:", e);
      const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
      mostrarErrorGlobal("No se pudo generar el PDF. Inténtalo de nuevo.");
    } finally {
      exportarPdfBtn.disabled = false;
      exportarPdfBtn.textContent = textoOriginal;
    }
  });

  cargarDatos();
});
