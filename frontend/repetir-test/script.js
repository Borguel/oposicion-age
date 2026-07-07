async function obtenerAuthHeaders() {
  const { idToken } = await import("/assets/auth.js");
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return null;
  }
  return { "Authorization": "Bearer " + token };
}

let preguntas = [];
let respuestasUsuario = [];
// Preguntas marcadas con la banderita "revisar más tarde" y preguntas ya
// visitadas en esta sesión (para distinguir en el navegador el gris de "no
// visitada" del rojo de "visitada pero sin responder").
let marcadasRevision = [];
let visitadas = [];
let indicePreguntaActual = 0;
let tiempoInicio;
let intervaloTemporizador;
let ultimasEstadisticas = null;
// Segundos ya transcurridos al reanudar un test guardado, para que el
// contador siga sumando en vez de reiniciarse a 00:00.
let tiempoTranscurridoBase = 0;
let oposicionActual = "";
let textosFavoritas = new Set();
let botonFavoritaHTML = () => "";
let activarBotonFavorita = () => {};

function formatearMinSeg(segundos) {
  const m = String(Math.floor(segundos / 60)).padStart(2, '0');
  const s = String(segundos % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function tiempoTranscurridoActual() {
  return tiempoTranscurridoBase + Math.floor((Date.now() - tiempoInicio) / 1000);
}

function iniciarTemporizador(tiempoTranscurridoReanudado) {
  tiempoTranscurridoBase = tiempoTranscurridoReanudado || 0;
  tiempoInicio = Date.now();
  const elTemporizador = document.getElementById("temporizador");
  const elTexto = document.getElementById("temporizador-texto");
  elTemporizador.style.display = "flex";
  elTexto.textContent = `⏱ Tiempo: ${formatearMinSeg(tiempoTranscurridoBase)}`;
  document.getElementById("btn-toggle-temporizador").onclick = () => elTemporizador.classList.toggle("temporizador-oculto");
  intervaloTemporizador = setInterval(() => {
    const transcurrido = tiempoTranscurridoActual();
    elTexto.textContent = `⏱ Tiempo: ${formatearMinSeg(transcurrido)}`;
    if (transcurrido % 10 === 0) {
      import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
        autoguardarProgreso({
          respuestas_usuario: respuestasUsuario,
          marcadas_revision: marcadasRevision,
          indice_actual: indicePreguntaActual,
          tiempo_transcurrido_segundos: transcurrido
        });
      });
    }
  }, 1000);
}

function confirmarFinalizar() {
  const sinContestar = respuestasUsuario.filter(r => r === null).length;
  Swal.fire({
    icon: 'question',
    title: '¿Deseas finalizar el test?',
    text: sinContestar > 0
      ? `Has dejado ${sinContestar} pregunta${sinContestar > 1 ? 's' : ''} sin contestar.`
      : '¿Quieres finalizar el test y ver los resultados?',
    showCancelButton: true,
    confirmButtonText: 'Sí, corregir',
    cancelButtonText: 'Seguir revisando',
  }).then((result) => {
    if (result.isConfirmed) mostrarResultados();
  });
}

function actualizarNavegadorPreguntas() {
  const contenedor = document.getElementById("navegador-preguntas");
  if (!contenedor) return;
  import("/assets/navegador-preguntas.js").then(({ renderizarNavegadorPreguntas }) => {
    renderizarNavegadorPreguntas(contenedor, {
      total: preguntas.length,
      respuestasUsuario,
      visitadas,
      marcadasRevision,
      indiceActual: indicePreguntaActual,
      onSaltar: (idx) => mostrarPregunta(idx)
    });
  });
}

function mostrarPregunta(i) {
  indicePreguntaActual = i;
  visitadas[i] = true;
  actualizarNavegadorPreguntas();
  const p = preguntas[i];
  let textoPregunta = p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, "");
  let html = `<form id="form-pregunta">
    <div class="pregunta-en-negrita">
      <span>${i + 1}. ${textoPregunta}</span>
      <div class="pregunta-acciones-header">
        ${botonFavoritaHTML(textosFavoritas.has(p.pregunta))}
        <button type="button" id="btn-marcar-revision" class="btn-marcar-revision${marcadasRevision[i] ? " activa" : ""}" aria-label="Marcar para revisión" title="Marcar para revisar más tarde">🔖</button>
      </div>
    </div>`;

  for (const letra in p.opciones) {
    const opcion = p.opciones[letra];
    const checked = respuestasUsuario[i] === letra ? "checked" : "";
    html += `
      <label class="opcion-respuesta">
        <input type="radio" name="respuesta" value="${letra}" ${checked}>
        <span class="opcion-letra">${letra}</span>
        <span class="opcion-texto">${opcion}</span>
      </label>`;
  }

  html += `
    <div class="botones-navegacion-test">
      ${i > 0 ? '<button type="button" id="btn-anterior" class="age-btn age-btn-outline">← Anterior</button>' : ''}
      <button type="submit" class="age-btn age-btn-primary">
        ${i + 1 < preguntas.length ? 'Siguiente →' : 'Finalizar test'}
      </button>
    </div>
  </form>`;

  document.getElementById("contenedor-test").innerHTML = html;
  activarBotonFavorita(document.getElementById("contenedor-test"), p, oposicionActual, textosFavoritas);

  document.getElementById("btn-marcar-revision").addEventListener("click", function () {
    marcadasRevision[i] = !marcadasRevision[i];
    this.classList.toggle("activa", marcadasRevision[i]);
    actualizarNavegadorPreguntas();
    import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
      autoguardarProgreso({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        indice_actual: i
      });
    });
  });

  document.querySelectorAll('input[name="respuesta"]').forEach((radio) => {
    radio.addEventListener("click", function () {
      // Si la opción pulsada ya era la marcada, un segundo clic la
      // desmarca y deja la pregunta en blanco -- más intuitivo que un
      // botón "Desmarcar" aparte para quien se equivoca al elegir.
      if (respuestasUsuario[i] === this.value) {
        this.checked = false;
        respuestasUsuario[i] = null;
      } else {
        respuestasUsuario[i] = this.value;
      }
      actualizarNavegadorPreguntas();
    });
  });

  // Guardar y salir / Finalizar son botones estáticos de la página (fuera de
  // #contenedor-test), así que se reasigna .onclick en vez de
  // addEventListener para no acumular listeners duplicados en cada pregunta.
  const botonGuardarSalir = document.getElementById("btn-guardar-salir");
  botonGuardarSalir.style.display = "block";
  botonGuardarSalir.disabled = false;
  botonGuardarSalir.textContent = "💾 Guardar y salir";
  botonGuardarSalir.onclick = async function () {
    const boton = this;
    boton.disabled = true;
    boton.textContent = "Guardando…";
    const { guardarProgresoInmediato } = await import("/assets/test-progreso.js");
    await guardarProgresoInmediato({
      respuestas_usuario: respuestasUsuario,
      marcadas_revision: marcadasRevision,
      indice_actual: indicePreguntaActual,
      tiempo_transcurrido_segundos: tiempoTranscurridoActual()
    });
    window.location.href = "/mis-tests/";
  };

  const botonFinalizar = document.getElementById("btn-finalizar");
  botonFinalizar.style.display = "block";
  botonFinalizar.onclick = confirmarFinalizar;

  if (i > 0) {
    document.getElementById("btn-anterior").addEventListener("click", () => mostrarPregunta(i - 1));
  }

  document.getElementById("form-pregunta").addEventListener("submit", function (e) {
    e.preventDefault();
    const seleccion = document.querySelector('input[name="respuesta"]:checked');
    respuestasUsuario[i] = seleccion ? seleccion.value : null;
    import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
      autoguardarProgreso({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        indice_actual: i + 1 < preguntas.length ? i + 1 : i,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      });
    });

    if (i + 1 < preguntas.length) {
      mostrarPregunta(i + 1);
    } else {
      confirmarFinalizar();
    }
  });
}

async function mostrarResultados() {
  clearInterval(intervaloTemporizador);
  document.getElementById("temporizador").style.display = "none";
  document.getElementById("navegador-preguntas").style.display = "none";
  document.getElementById("contenedor-test").innerHTML = "";
  document.getElementById("contenedor-test").style.display = "none";
  document.getElementById("btn-guardar-salir").style.display = "none";
  document.getElementById("btn-finalizar").style.display = "none";
  const cont = document.getElementById("contenedor-resultados");
  cont.style.display = "block";

  const { renderizarResultadosTest } = await import("/assets/resultados-test.js");
  ultimasEstadisticas = renderizarResultadosTest({
    contenedor: cont,
    preguntas,
    respuestasUsuario,
    listaTemas: []
  });

  document.getElementById("btn-descargar-pdf").style.display = "block";

  const segundosTotales = tiempoTranscurridoActual();
  const { testIdEnCurso, limpiarSeguimiento } = await import("/assets/test-progreso.js");
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    await fetch("https://oposicion-age.onrender.com/guardar-test", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({
        contenido: preguntas,
        respuestas: respuestasUsuario,
        metadatos: { tiempo: segundosTotales, tipo: "repetido", temas: [] },
        oposicion: obtenerOposicionActual(),
        test_id: testIdEnCurso()
      })
    });
    limpiarSeguimiento();
  } catch (err) {
    console.error("❌ Error al guardar test:", err);
  }
}

document.getElementById("btn-descargar-pdf").addEventListener("click", async () => {
  const { descargarResultadosPDF } = await import("/assets/resultados-test.js");
  descargarResultadosPDF({
    preguntas,
    respuestasUsuario,
    stats: ultimasEstadisticas,
    titulo: "Resultados del test repetido"
  });
});

// Carga el último test al cargar la página; si se llega con ?resume=<id>
// desde "Mis Tests" reanuda ese borrador tal cual se dejó, y si se llega con
// ?repetir=<id> empieza un intento NUEVO (sin las respuestas de la vez
// anterior) a partir del contenido de ESE test concreto, no solo el último.
window.addEventListener("load", async () => {
  const { idDesdeUrlResume, usarTestId, cargarTestEnProgreso, generarTestId, guardarContenidoInicial, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
  const resumeId = idDesdeUrlResume();
  const repetirId = new URLSearchParams(window.location.search).get("repetir");
  try {
    if (resumeId) {
      const guardado = await cargarTestEnProgreso(resumeId);
      if (!guardado || !guardado.contenido || !guardado.contenido.length) {
        document.getElementById("contenedor-test").innerHTML = "<p>No se ha encontrado ese test guardado.</p>";
        return;
      }
      usarTestId(resumeId);
      preguntas = guardado.contenido;
      respuestasUsuario = Array.isArray(guardado.respuestas_usuario) && guardado.respuestas_usuario.length === preguntas.length
        ? guardado.respuestas_usuario
        : Array(preguntas.length).fill(null);
      marcadasRevision = Array.isArray(guardado.marcadas_revision) && guardado.marcadas_revision.length === preguntas.length
        ? guardado.marcadas_revision
        : Array(preguntas.length).fill(false);
      indicePreguntaActual = guardado.indice_actual || 0;
      // No se guarda un historial de "visitadas" -- se asume que se llegó
      // hasta indice_actual avanzando en orden.
      visitadas = Array(preguntas.length).fill(false);
      for (let k = 0; k <= indicePreguntaActual && k < visitadas.length; k++) visitadas[k] = true;
      const { obtenerOposicionActual: obtenerOposicionResume } = await import("/assets/oposicion.js");
      oposicionActual = guardado.oposicion || obtenerOposicionResume();
      const favoritasApiResume = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApiResume.botonFavoritaHTML;
      activarBotonFavorita = favoritasApiResume.activarBotonFavorita;
      textosFavoritas = await favoritasApiResume.cargarTextosFavoritas(oposicionActual);
      iniciarTemporizador(guardado.tiempo_transcurrido_segundos || 0);
      document.getElementById("navegador-preguntas").style.display = "flex";
      mostrarPregunta(indicePreguntaActual);
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        indice_actual: indicePreguntaActual,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      }));
      return;
    }

    if (repetirId) {
      const authHeadersRepetir = await obtenerAuthHeaders();
      if (!authHeadersRepetir) return;
      const resRepetir = await fetch(`https://oposicion-age.onrender.com/mi-test/${repetirId}`, { headers: authHeadersRepetir });
      const datosRepetir = await resRepetir.json();
      // Un test ya finalizado guarda sus preguntas bajo "preguntas" (con el
      // resultado de aquel intento ya incluido); aquí solo interesa el
      // enunciado/opciones/respuesta_correcta/explicacion para arrancar un
      // intento nuevo, así que basta reutilizar ese mismo array tal cual.
      const preguntasRepetir = datosRepetir.test?.preguntas;
      if (!resRepetir.ok || !preguntasRepetir || !preguntasRepetir.length) {
        document.getElementById("contenedor-test").innerHTML = "<p>No se ha encontrado ese test.</p>";
        return;
      }
      preguntas = preguntasRepetir;
      respuestasUsuario = Array(preguntas.length).fill(null);
      marcadasRevision = Array(preguntas.length).fill(false);
      visitadas = Array(preguntas.length).fill(false);
      const { obtenerOposicionActual } = await import("/assets/oposicion.js");
      const oposicion = obtenerOposicionActual();
      oposicionActual = oposicion;
      const favoritasApiRepetir = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApiRepetir.botonFavoritaHTML;
      activarBotonFavorita = favoritasApiRepetir.activarBotonFavorita;
      textosFavoritas = await favoritasApiRepetir.cargarTextosFavoritas(oposicion);
      generarTestId();
      guardarContenidoInicial({
        oposicion, tipo: "repetido", temas: [],
        contenido: preguntas,
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        indice_actual: 0,
        pagina_origen: "/repetir-test/"
      });
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        indice_actual: indicePreguntaActual,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      }));
      iniciarTemporizador();
      document.getElementById("navegador-preguntas").style.display = "flex";
      mostrarPregunta(0);
      return;
    }

    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const oposicion = obtenerOposicionActual();
    const res = await fetch(`https://oposicion-age.onrender.com/ultimo-test?oposicion=${encodeURIComponent(oposicion)}`, { headers: authHeaders });
    const datos = await res.json();

    if (!datos.test || datos.test.length === 0) {
      document.getElementById("contenedor-test").innerHTML = "<p>No se ha encontrado ningún test anterior.</p>";
      return;
    }

    preguntas = datos.test;
    respuestasUsuario = Array(preguntas.length).fill(null);
    marcadasRevision = Array(preguntas.length).fill(false);
    visitadas = Array(preguntas.length).fill(false);
    oposicionActual = oposicion;
    const favoritasApiUltimo = await import("/assets/favoritas.js");
    botonFavoritaHTML = favoritasApiUltimo.botonFavoritaHTML;
    activarBotonFavorita = favoritasApiUltimo.activarBotonFavorita;
    textosFavoritas = await favoritasApiUltimo.cargarTextosFavoritas(oposicion);
    generarTestId();
    guardarContenidoInicial({
      oposicion, tipo: "repetido", temas: [],
      contenido: preguntas,
      respuestas_usuario: respuestasUsuario,
      marcadas_revision: marcadasRevision,
      indice_actual: 0,
      pagina_origen: "/repetir-test/"
    });
    activarGuardadoAlSalir(() => ({
      respuestas_usuario: respuestasUsuario,
      marcadas_revision: marcadasRevision,
      indice_actual: indicePreguntaActual,
      tiempo_transcurrido_segundos: tiempoTranscurridoActual()
    }));
    iniciarTemporizador();
    document.getElementById("navegador-preguntas").style.display = "flex";
    mostrarPregunta(0);
  } catch (err) {
    console.error("Error:", err);
    document.getElementById("contenedor-test").innerHTML = "<p>Error al cargar el test.</p>";
  }
});
