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
  let temasFiltrados = [];
  let todosLosTemas = [];
  let temasTest = [];
  let temasTocados = new Set();

  // Función para cargar datos
  async function cargarDatos() {
    try {
      // Resetear valores
      document.querySelectorAll('.valor').forEach(el => {
        if (!el.id.startsWith('tendencia')) {
          el.textContent = '...';
        }
      });
      document.querySelectorAll('.progress-fill').forEach(el => el.style.width = '0%');
      document.getElementById("tendencia-media").innerHTML = '<span>...</span>';
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

      const { obtenerOposicionActual } = await import("/assets/oposicion.js");
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
        procesarDatos(resumenData.resumen ?? {}, temasData.temas || [], racha);
      } else {
        procesarDatos(estadisticas, temasData.temas || [], racha);
      }
    } catch (err) {
      console.error("Error cargando estadísticas:", err);
      alert("Hubo un problema al cargar tus estadísticas: " + err.message);
    } finally {
      refreshBtn.classList.remove('loading');
      refreshBtn.disabled = false;
    }
  }

  function procesarDatos(estadisticas, todosTemas, racha) {
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
    document.getElementById("tests").textContent = totalTests;
    document.getElementById("aprobados").textContent = aprobados;
    document.getElementById("suspendidos").textContent = suspendidos;
    document.getElementById("media").textContent = puntuacionMedia.toFixed(1);
    document.getElementById("aciertos").textContent = totalAciertos;
    document.getElementById("fallos").textContent = totalFallos;
    document.getElementById("blancos").textContent = totalBlancos;
    document.getElementById("esquemas").textContent = esquemas;
    document.getElementById("tiempo").textContent = `${horas}h ${minutos}m`;
    document.getElementById("temas-nuevos").textContent = noEstudiados.length;

    document.getElementById("aprobados-porcentaje").textContent = porcentajeAprobados;
    document.getElementById("suspendidos-porcentaje").textContent = porcentajeSuspendidos;
    document.getElementById("aciertos-porcentaje").textContent = porcentajeAciertos;
    document.getElementById("fallos-porcentaje").textContent = porcentajeFallos;
    document.getElementById("blancos-porcentaje").textContent = porcentajeBlancos;

    document.getElementById("aprobados-progress").style.width = `${porcentajeAprobados}%`;
    document.getElementById("suspendidos-progress").style.width = `${porcentajeSuspendidos}%`;

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
    renderizarEvolucion(historial);
    renderizarInsignias({
      testsRealizados: totalTests,
      testsAprobados: aprobados,
      puntuacionMedia: puntuacionMedia,
      esquemas: esquemas,
      totalArchivos: totalArchivos,
      rachaMaxima: racha.racha_maxima ?? 0
    });
  }

  // Insignias: logros calculados a partir de datos que ya se piden para el
  // resto de la página (más /mi-racha), sin ninguna ruta nueva. Cada una
  // tiene un umbral simple; si no está conseguida se muestra en gris con
  // el progreso actual para animar a seguir usando la web.
  const INSIGNIAS = [
    { icono: "🎯", titulo: "Primer test", descripcion: "Completa tu primer test", valor: (d) => d.testsRealizados, umbral: 1 },
    { icono: "🔥", titulo: "Racha de 3 días", descripcion: "Estudia 3 días seguidos", valor: (d) => d.rachaMaxima, umbral: 3 },
    { icono: "🔥", titulo: "Racha de 7 días", descripcion: "Estudia 7 días seguidos", valor: (d) => d.rachaMaxima, umbral: 7 },
    { icono: "🔥", titulo: "Racha de 30 días", descripcion: "Estudia 30 días seguidos", valor: (d) => d.rachaMaxima, umbral: 30 },
    { icono: "📚", titulo: "10 tests", descripcion: "Completa 10 tests", valor: (d) => d.testsRealizados, umbral: 10 },
    { icono: "🎓", titulo: "50 tests", descripcion: "Completa 50 tests", valor: (d) => d.testsRealizados, umbral: 50 },
    { icono: "✅", titulo: "10 aprobados", descripcion: "Aprueba 10 tests", valor: (d) => d.testsAprobados, umbral: 10 },
    { icono: "🏆", titulo: "Excelencia", descripcion: "Nota media de 8 o más", valor: (d) => d.puntuacionMedia, umbral: 8 },
    { icono: "🗂️", titulo: "Esquematizador", descripcion: "Genera 5 esquemas", valor: (d) => d.esquemas, umbral: 5 },
    { icono: "📄", titulo: "Documentalista", descripcion: "Sube 3 documentos PDF", valor: (d) => d.totalArchivos, umbral: 3 }
  ];

  function renderizarInsignias(datos) {
    const contenedor = document.getElementById("insignias-grid");
    contenedor.innerHTML = INSIGNIAS.map((insignia) => {
      const actual = insignia.valor(datos) || 0;
      const conseguida = actual >= insignia.umbral;
      const actualMostrado = Number.isInteger(insignia.umbral) ? Math.floor(Math.min(actual, insignia.umbral)) : Math.min(actual, insignia.umbral).toFixed(1);
      return `
        <div class="insignia${conseguida ? " conseguida" : ""}" title="${insignia.descripcion}">
          <div class="insignia-icono">${insignia.icono}</div>
          <div class="insignia-titulo">${insignia.titulo}</div>
          <div class="insignia-estado">${conseguida ? "Conseguida" : `${actualMostrado}/${insignia.umbral}`}</div>
        </div>
      `;
    }).join("");
  }

  // Gráfica de evolución de la nota: una línea sencilla en SVG (sin
  // depender de ninguna librería) con los últimos tests, en la misma
  // escala 0-10 que "Puntuación media". Cada punto se colorea según si
  // ese test se aprobó o no, y muestra un tooltip nativo con la fecha.
  const MAX_TESTS_EVOLUCION = 15;

  function renderizarEvolucion(historial) {
    const contenedor = document.getElementById("evolucion-grafica");
    const vacio = document.getElementById("evolucion-vacio");
    const tarjeta = document.getElementById("tarjeta-evolucion");
    const recientes = historial.slice(-MAX_TESTS_EVOLUCION);

    if (recientes.length < 2) {
      contenedor.style.display = "none";
      vacio.style.display = "block";
      return;
    }
    contenedor.style.display = "block";
    vacio.style.display = "none";

    const ancho = 600;
    const alto = 160;
    const margen = 20;
    const notas = recientes.map(t => Math.round((t.puntuacion_final ?? 0) * 100) / 10);
    const paso = (ancho - margen * 2) / (recientes.length - 1);

    const coordX = (i) => margen + i * paso;
    const coordY = (nota) => alto - margen - (nota / 10) * (alto - margen * 2);

    const puntos = notas.map((nota, i) => `${coordX(i)},${coordY(nota)}`).join(" ");

    const circulos = recientes.map((t, i) => {
      const nota = notas[i];
      const color = t.resultado === "aprobado" ? "var(--age-success)" : "var(--age-danger)";
      const fecha = t.fecha ? new Date(t.fecha).toLocaleDateString("es-ES") : "";
      return `<circle cx="${coordX(i)}" cy="${coordY(nota)}" r="4" fill="${color}"><title>${fecha}: ${nota.toFixed(1)}/10</title></circle>`;
    }).join("");

    const lineaAprobado = coordY(5);

    contenedor.innerHTML = `
      <svg viewBox="0 0 ${ancho} ${alto}" preserveAspectRatio="none" class="evolucion-svg">
        <line x1="${margen}" y1="${lineaAprobado}" x2="${ancho - margen}" y2="${lineaAprobado}" class="evolucion-linea-aprobado" />
        <polyline points="${puntos}" fill="none" class="evolucion-linea" />
        ${circulos}
      </svg>
    `;
    tarjeta.style.display = "flex";
  }

  // "Tema flojo" = ha respondido al menos 3 preguntas de ese tema (para que
  // no sea ruido de una sola pregunta con mala suerte) y acierta menos del
  // 60%. Se muestran como mucho los 3 peores, de menor a mayor acierto.
  const UMBRAL_ACIERTO_FLOJO = 60;
  const MINIMO_PREGUNTAS_FLOJO = 3;

  function mostrarTemasFlojos(rendimientoPorTema, todosTemas) {
    const tarjeta = document.getElementById("tarjeta-temas-flojos");
    const lista = document.getElementById("lista-temas-flojos");

    const temasFlojos = Object.entries(rendimientoPorTema || {})
      .map(([id, r]) => {
        const respondidas = (r.aciertos || 0) + (r.fallos || 0);
        const porcentaje = respondidas > 0 ? Math.round((r.aciertos / respondidas) * 100) : null;
        return { id, respondidas, porcentaje };
      })
      .filter(t => t.respondidas >= MINIMO_PREGUNTAS_FLOJO && t.porcentaje !== null && t.porcentaje < UMBRAL_ACIERTO_FLOJO)
      .sort((a, b) => a.porcentaje - b.porcentaje)
      .slice(0, 3);

    if (temasFlojos.length === 0) {
      tarjeta.style.display = "none";
      return;
    }

    lista.innerHTML = "";
    temasFlojos.forEach(t => {
      const tema = todosTemas.find(x => x.id === t.id);
      const nombre = tema ? tema.titulo : `Tema ${t.id}`;
      const li = document.createElement("li");
      li.innerHTML = `
        <div class="tema-flojo-info">
          <span class="tema-flojo-nombre" title="${nombre}">${nombre}</span>
          <span class="tema-flojo-porcentaje">${t.porcentaje}% de acierto</span>
        </div>
        <a class="btn-repasar-tema" href="/test-generator/?temas=${encodeURIComponent(t.id)}">Repasar</a>
      `;
      lista.appendChild(li);
    });
    tarjeta.style.display = "flex";
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

  refreshBtn.addEventListener('click', cargarDatos);

  function cerrarModal() {
    cerrarModalGenerico(modal);
    busquedaInput.value = '';
    filtrarTemas();
  }

  cargarDatos();
});
