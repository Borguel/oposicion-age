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

async function obtenerAuthHeaders() {
  const { idToken } = await import("/assets/auth.js");
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return null;
  }
  return { "Authorization": "Bearer " + token };
}

document.addEventListener("DOMContentLoaded", async function () {
  localStorage.setItem("age_visito_estadisticas", "1");

  const refreshBtn = document.getElementById("estadisticas-refresh");
  const modal = document.getElementById("modal-temas");
  const modalCerrar = document.getElementById("modal-cerrar");
  const modalCerrarBtn = document.getElementById("modal-cerrar-btn");
  const modalTop = document.getElementById("modal-temas-top");
  const modalTopCerrar = document.getElementById("modal-temas-top-cerrar");
  const modalTopCerrarBtn = document.getElementById("modal-temas-top-cerrar-btn");
  const btnVerNuevos = document.getElementById("btn-ver-nuevos");
  const btnVerTemasTop = document.getElementById("btn-ver-temas-top");
  const busquedaInput = document.getElementById("modal-busqueda-input");
  const exportarPdfBtn = document.getElementById("estadisticas-exportar-pdf");
  let temasFiltrados = [];
  let todosLosTemas = [];
  let temasTest = [];
  let temasTocados = new Set();
  let datosParaExportarPDF = null;

  // Función para cargar datos
  async function cargarDatos() {
    try {
      // Resetear valores
      document.querySelectorAll('.valor').forEach(el => {
        if (!el.id.startsWith('tendencia')) {
          el.textContent = '...';
        }
      });
      document.querySelectorAll('.vistazo-mini-fill, .respuestas-segmento').forEach(el => el.style.width = '0%');
      document.getElementById("tendencia-media").innerHTML = '<span>...</span>';
      document.getElementById("vistazo-aprobados-detalle").textContent = '— aprobados · — suspendidos';
      // Resetear valores PDF
      document.getElementById("total-archivos").textContent = '...';
      document.getElementById("total-tests-pdf").textContent = '...';
      document.getElementById("total-resumenes-pdf").textContent = '...';
      document.getElementById("total-esquemas-pdf").textContent = '...';
      document.getElementById("total-tarjetas-pdf").textContent = '...';
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
      alert("Hubo un problema al cargar tus estadísticas: " + err.message);
    } finally {
      refreshBtn.classList.remove('loading');
      refreshBtn.disabled = false;
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

    // "Más estudiado" = tema con más preguntas realmente contestadas
    // (rendimiento_por_tema, que cuenta preguntas de verdad), y si un tema no
    // tiene ese detalle (tests antiguos sin tema_id por pregunta) se cae al
    // conteo antiguo por nº de tests que lo incluían entre sus temas.
    const contadorPreguntas = {};
    Object.entries(rendimientoPorTema).forEach(([id, r]) => {
      contadorPreguntas[id] = (r.aciertos || 0) + (r.fallos || 0) + (r.blancos || 0);
    });
    historial.forEach(test => {
      (test.temas || []).forEach(t => {
        if (!(t in contadorPreguntas)) contadorPreguntas[t] = (contadorPreguntas[t] || 0) + 1;
      });
    });

    const topTemasEntries = Object.entries(contadorPreguntas)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3);

    const todosLosTemasIds = todosTemas.map(t => t.id);
    temasTocados = new Set([...temasTest, ...Object.keys(rendimientoPorTema)]);
    const noEstudiados = todosLosTemasIds.filter(t => !temasTocados.has(t));

    // Actualizar estadísticas principales
    document.getElementById("vistazo-tests").textContent = totalTests;
    document.getElementById("vistazo-media").textContent = puntuacionMedia.toFixed(1);
    document.getElementById("vistazo-racha").textContent = racha.racha_actual ?? 0;
    // Por debajo del 25% es una mala señal (rojo), de 25% a 50% aviso
    // (ámbar), y solo a partir del 50% es un dato realmente positivo
    // (verde) -- antes salía siempre en verde, dando la sensación de que
    // iba bien aunque el % de aprobados fuera muy bajo.
    const nivelAprobados = porcentajeAprobados < 25 ? "nivel-bajo" : porcentajeAprobados < 50 ? "nivel-medio" : "nivel-alto";
    const pctEl = document.getElementById("vistazo-aprobados-pct");
    const fillEl = document.getElementById("vistazo-aprobados-fill");
    pctEl.textContent = `${porcentajeAprobados}%`;
    pctEl.classList.remove("nivel-bajo", "nivel-medio", "nivel-alto");
    pctEl.classList.add(nivelAprobados);
    fillEl.classList.remove("nivel-bajo", "nivel-medio", "nivel-alto");
    fillEl.classList.add(nivelAprobados);
    document.getElementById("vistazo-aprobados-detalle").textContent = `${aprobados} aprobados · ${suspendidos} suspendidos`;
    fillEl.style.width = `${porcentajeAprobados}%`;

    document.getElementById("aciertos").textContent = totalAciertos;
    document.getElementById("fallos").textContent = totalFallos;
    document.getElementById("blancos").textContent = totalBlancos;
    document.getElementById("tiempo").textContent = `${horas}h ${minutos}m`;
    document.getElementById("temas-nuevos").textContent = noEstudiados.length;

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

    actualizarTemas(topTemasEntries, todosTemas, rendimientoPorTema);
    temasFiltrados = noEstudiados;
    todosLosTemas = todosTemas;
    mostrarTemasNoEstudiados(noEstudiados, todosTemas);
    mostrarTemasFlojos(rendimientoPorTema, todosTemas);
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
      nombreOposicion: (OPOSICIONES.find(o => o.id === oposicion) || {}).nombre || "Oposición AGE",
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
    { icono: "🎯", titulo: "Primer test", descripcion: "Completa tu primer test", valor: (d) => d.testsRealizados, umbral: 1, unidad: "test" },
    { icono: "🔥", titulo: "Racha de 3 días", descripcion: "Estudia 3 días seguidos", valor: (d) => d.rachaMaxima, umbral: 3, unidad: "días" },
    { icono: "🔥", titulo: "Racha de 7 días", descripcion: "Estudia 7 días seguidos", valor: (d) => d.rachaMaxima, umbral: 7, unidad: "días" },
    { icono: "🔥", titulo: "Racha de 30 días", descripcion: "Estudia 30 días seguidos", valor: (d) => d.rachaMaxima, umbral: 30, unidad: "días" },
    { icono: "📚", titulo: "10 tests", descripcion: "Completa 10 tests", valor: (d) => d.testsRealizados, umbral: 10, unidad: "tests" },
    { icono: "🎓", titulo: "50 tests", descripcion: "Completa 50 tests", valor: (d) => d.testsRealizados, umbral: 50, unidad: "tests" },
    { icono: "✅", titulo: "10 aprobados", descripcion: "Aprueba 10 tests", valor: (d) => d.testsAprobados, umbral: 10, unidad: "aprobados" },
    { icono: "🏆", titulo: "Excelencia", descripcion: "Nota media de 8 o más", valor: (d) => d.puntuacionMedia, umbral: 8, unidad: "puntos" },
    { icono: "🗂️", titulo: "Esquematizador", descripcion: "Genera 5 esquemas", valor: (d) => d.esquemas, umbral: 5, unidad: "esquemas" },
    { icono: "📄", titulo: "Documentalista", descripcion: "Sube 3 documentos PDF", valor: (d) => d.totalArchivos, umbral: 3, unidad: "documentos" }
  ];

  function renderizarInsignias(datos) {
    const contenedor = document.getElementById("insignias-grid");
    const conseguidas = [];
    const pendientes = [];
    contenedor.innerHTML = INSIGNIAS.map((insignia) => {
      const actual = insignia.valor(datos) || 0;
      const conseguida = actual >= insignia.umbral;
      if (conseguida) {
        conseguidas.push(`${insignia.icono} ${insignia.titulo}`);
      } else {
        pendientes.push({ insignia, actual, progreso: actual / insignia.umbral });
      }
      const actualMostrado = Number.isInteger(insignia.umbral) ? Math.floor(Math.min(actual, insignia.umbral)) : Math.min(actual, insignia.umbral).toFixed(1);
      return `
        <div class="insignia${conseguida ? " conseguida" : ""}" title="${insignia.descripcion}">
          <div class="insignia-icono">${insignia.icono}</div>
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
      <span class="insignia-siguiente-icono">${insignia.icono}</span>
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
      const fecha = t.fecha ? new Date(t.fecha).toLocaleDateString("es-ES") : "";
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
      const fechaCorta = new Date(t.fecha).toLocaleDateString("es-ES", { day: "numeric", month: "numeric" });
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

    const fechaMejor = recientes[mejorIdx].fecha ? new Date(recientes[mejorIdx].fecha).toLocaleDateString("es-ES") : "";
    const fechaPeor = recientes[peorIdx].fecha ? new Date(recientes[peorIdx].fecha).toLocaleDateString("es-ES") : "";
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
    tarjeta.style.display = "flex";
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
    if (historialCalendario.length === 0) {
      tarjeta.style.display = "none";
      return;
    }
    if (!mesCalendarioActual) {
      const hoy = new Date();
      mesCalendarioActual = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
    }
    tarjeta.style.display = "flex";
    pintarCalendarioMes();
  }

  function pintarCalendarioMes() {
    const contenedor = document.getElementById("calendario-grafica");
    const etiquetaMes = document.getElementById("calendario-mes-actual");
    const inputMes = document.getElementById("calendario-mes-input");
    const botonSiguiente = document.getElementById("calendario-mes-siguiente");

    const anio = mesCalendarioActual.getFullYear();
    const mes = mesCalendarioActual.getMonth();

    const diasConActividad = new Set(
      historialCalendario.map(t => (t.fecha || "").slice(0, 10)).filter(Boolean)
    );

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
      const activo = diasConActividad.has(clave);
      const esHoy = esMesActual && dia === hoy.getDate();
      const clases = ["calendario-celda", activo ? "con-actividad" : "", esHoy ? "hoy" : ""].filter(Boolean).join(" ");
      celdas.push(`<div class="${clases}" title="${dia}${activo ? ": estudiaste" : ""}">${dia}</div>`);
    }
    contenedor.innerHTML = celdas.join("");
  }

  async function actualizarTemas(temasEntries, todosTemas, rendimientoPorTema) {
    const listaTemas = document.getElementById("lista-temas-top");
    const valorTop = document.getElementById("temas-top-valor");
    const detalleTop = document.getElementById("temas-top-detalle");
    listaTemas.innerHTML = '';
    if (temasEntries.length === 0) {
      valorTop.textContent = '0';
      detalleTop.textContent = 'Aún no has estudiado ningún tema';
      const li = document.createElement('li');
      li.textContent = 'No hay temas estudiados aún.';
      li.style.color = '#777';
      li.style.fontStyle = 'italic';
      listaTemas.appendChild(li);
      return;
    }
    const [idTop, countTop] = temasEntries[0];
    const temaTop = todosTemas.find(t => t.id === idTop);
    valorTop.textContent = countTop;
    detalleTop.textContent = `Preguntas en tu tema más estudiado: ${temaTop ? temaTop.titulo : `Tema ${idTop}`}`;

    // Mismo formato agrupado por bloque que "Temas no estudiados", pero aquí
    // añadiendo el % de acierto y las preguntas respondidas de cada tema.
    const datosPorId = new Map();
    temasEntries.forEach(([id, count]) => {
      const r = (rendimientoPorTema || {})[id];
      const totalRespondidas = r ? (r.aciertos || 0) + (r.fallos || 0) : 0;
      const porcentaje = totalRespondidas > 0 ? Math.round((r.aciertos / totalRespondidas) * 100) : null;
      datosPorId.set(id, { count, porcentaje });
    });

    const { agruparTemasPorBloque } = await import("/assets/temas-numeracion.js");
    const grupos = agruparTemasPorBloque(todosTemas)
      .map((grupo) => ({ ...grupo, temas: grupo.temas.filter((t) => datosPorId.has(t.id)) }))
      .filter((grupo) => grupo.temas.length > 0);

    grupos.forEach((grupo) => {
      const liBloque = document.createElement('li');
      liBloque.className = 'tema-bloque-grupo';
      liBloque.innerHTML = `
        <div class="tema-bloque-header">Bloque ${grupo.numeroRomano}: ${grupo.titulo}</div>
        <ul class="tema-bloque-lista">
          ${grupo.temas.map((t) => {
            const { count, porcentaje } = datosPorId.get(t.id);
            return `
              <li class="tema-item tema-item-con-datos">
                <div class="tema-item-cabecera">
                  <span class="tema-numero">Tema ${t.numeroTema}</span>
                  <span class="tema-item-titulo">${t.titulo}</span>
                </div>
                <div class="tema-item-stats">
                  ${porcentaje !== null ? `<span class="tema-acierto">${porcentaje}% acierto</span>` : ''}
                  <span class="tema-count">${count} pregunta${count === 1 ? '' : 's'} respondida${count === 1 ? '' : 's'}</span>
                </div>
              </li>
            `;
          }).join('')}
        </ul>
      `;
      listaTemas.appendChild(liBloque);
    });
  }

  async function mostrarTemasNoEstudiados(temasIds, todosTemas) {
    const listaTemas = document.getElementById("lista-temas-nuevos");
    listaTemas.innerHTML = '';
    if (temasIds.length === 0) {
      const li = document.createElement('li');
      li.textContent = '¡Enhorabuena! Has estudiado todos los temas disponibles.';
      li.style.color = '#777';
      li.style.fontStyle = 'italic';
      li.style.textAlign = 'center';
      listaTemas.appendChild(li);
      return;
    }
    const { agruparTemasPorBloque } = await import("/assets/temas-numeracion.js");
    const idsPendientes = new Set(temasIds);
    const grupos = agruparTemasPorBloque(todosTemas)
      .map((grupo) => ({ ...grupo, temas: grupo.temas.filter((t) => idsPendientes.has(t.id)) }))
      .filter((grupo) => grupo.temas.length > 0);

    grupos.forEach((grupo) => {
      const liBloque = document.createElement('li');
      liBloque.className = 'tema-bloque-grupo';
      liBloque.innerHTML = `
        <div class="tema-bloque-header">Bloque ${grupo.numeroRomano}: ${grupo.titulo}</div>
        <ul class="tema-bloque-lista">
          ${grupo.temas.map((t) => `
            <li class="tema-item">
              <span class="tema-numero">Tema ${t.numeroTema}</span>
              <span class="tema-item-titulo">${t.titulo}</span>
            </li>
          `).join('')}
        </ul>
      `;
      listaTemas.appendChild(liBloque);
    });
  }

  function filtrarTemas() {
    const filtro = busquedaInput.value.toLowerCase().trim();
    const temasFiltradosLocal = todosLosTemas
      .filter(t => !temasTocados.has(t.id))
      .filter(t => t.titulo.toLowerCase().includes(filtro) || t.id.toString().includes(filtro));
    mostrarTemasNoEstudiados(temasFiltradosLocal.map(t => t.id), todosLosTemas);
  }

  // Eventos interactivos
  function abrirModalGenerico(modalEl) {
    modalEl.classList.add('show');
    void modalEl.offsetWidth;
    document.body.style.overflow = 'hidden';
  }

  function cerrarModalGenerico(modalEl) {
    modalEl.classList.remove('show');
    document.body.style.overflow = '';
  }

  btnVerTemasTop.addEventListener('click', function(e) {
    e.preventDefault();
    abrirModalGenerico(modalTop);
  });

  modalTopCerrar.addEventListener('click', () => cerrarModalGenerico(modalTop));
  modalTopCerrarBtn.addEventListener('click', () => cerrarModalGenerico(modalTop));
  modalTop.addEventListener('click', (e) => {
    if (e.target === modalTop) cerrarModalGenerico(modalTop);
  });

  btnVerNuevos.addEventListener('click', function() {
    abrirModalGenerico(modal);
  });

  modalCerrar.addEventListener('click', cerrarModal);
  modalCerrarBtn.addEventListener('click', cerrarModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) cerrarModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    if (modal.classList.contains('show')) cerrarModal();
    if (modalTop.classList.contains('show')) cerrarModalGenerico(modalTop);
  });

  busquedaInput.addEventListener('input', filtrarTemas);

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
      alert("No se pudo generar el PDF. Inténtalo de nuevo.");
    } finally {
      exportarPdfBtn.disabled = false;
      exportarPdfBtn.textContent = textoOriginal;
    }
  });

  function cerrarModal() {
    cerrarModalGenerico(modal);
    busquedaInput.value = '';
    filtrarTemas();
  }

  cargarDatos();
});
