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
  const modalCerrar = document.querySelector(".modal-cerrar");
  const modalCerrarBtn = document.getElementById("modal-cerrar-btn");
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
      const [estadisticasRes, temasRes] = await Promise.all([
        fetch(`https://oposicion-age.onrender.com/estadisticas-completas${sufijo}`, { headers: authHeaders }),
        fetch(`https://oposicion-age.onrender.com/temas-disponibles${sufijo}`, { headers: authHeaders })
      ]);
      const estadisticasData = await estadisticasRes.json();
      const temasData = await temasRes.json();
      const estadisticas = estadisticasData.estadisticas ?? {};

      // Si hay error, usar la ruta antigua como fallback
      if (estadisticas.error) {
        console.warn("Usando ruta antigua como fallback");
        const resumenRes = await fetch(`https://oposicion-age.onrender.com/resumen-progreso${sufijo}`, { headers: authHeaders });
        const resumenData = await resumenRes.json();
        procesarDatos(resumenData.resumen ?? {}, temasData.temas || []);
      } else {
        procesarDatos(estadisticas, temasData.temas || []);
      }
    } catch (err) {
      console.error("Error cargando estadísticas:", err);
      alert("Hubo un problema al cargar tus estadísticas: " + err.message);
    } finally {
      refreshBtn.classList.remove('loading');
      refreshBtn.disabled = false;
    }
  }

  function procesarDatos(estadisticas, todosTemas) {
    const totalTests = estadisticas.tests_realizados ?? 0;
    const totalAciertos = estadisticas.total_aciertos ?? 0;
    const totalFallos = estadisticas.total_fallos ?? 0;
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
    const porcentajeAciertos = (totalAciertos + totalFallos) > 0 
      ? Math.round((totalAciertos / (totalAciertos + totalFallos)) * 100) 
      : 0;
    const porcentajeFallos = (totalAciertos + totalFallos) > 0 
      ? Math.round((totalFallos / (totalAciertos + totalFallos)) * 100) 
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
    document.getElementById("esquemas").textContent = esquemas;
    document.getElementById("tiempo").textContent = `${horas}h ${minutos}m`;
    document.getElementById("temas-nuevos").textContent = noEstudiados.length;

    document.getElementById("aprobados-porcentaje").textContent = porcentajeAprobados;
    document.getElementById("suspendidos-porcentaje").textContent = porcentajeSuspendidos;
    document.getElementById("aciertos-porcentaje").textContent = porcentajeAciertos;
    document.getElementById("fallos-porcentaje").textContent = porcentajeFallos;

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
              <li class="tema-item">
                <span class="tema-numero">Tema ${t.numeroTema}</span>
                <span class="tema-item-titulo">${t.titulo}</span>
                ${porcentaje !== null ? `<span class="tema-acierto">${porcentaje}% acierto</span>` : ''}
                <span class="tema-count">${count} pregunta${count === 1 ? '' : 's'} respondida${count === 1 ? '' : 's'}</span>
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
  btnVerTemasTop.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    this.closest('.tarjeta-temas').classList.toggle('activo');
  });

  btnVerNuevos.addEventListener('click', function() {
    modal.classList.add('show');
    void modal.offsetWidth;
    document.body.style.overflow = 'hidden';
  });

  modalCerrar.addEventListener('click', cerrarModal);
  modalCerrarBtn.addEventListener('click', cerrarModal);
  modal.addEventListener('click', (e) => {
    if (e.target === modal) cerrarModal();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && modal.classList.contains('show')) {
      cerrarModal();
    }
  });

  busquedaInput.addEventListener('input', filtrarTemas);

  refreshBtn.addEventListener('click', cargarDatos);

  function cerrarModal() {
    modal.classList.remove('show');
    document.body.style.overflow = '';
    busquedaInput.value = '';
    filtrarTemas();
  }

  cargarDatos();
});
