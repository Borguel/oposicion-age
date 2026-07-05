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
  document.getElementById("temporizador").style.display = "block";
  document.getElementById("temporizador").textContent = `⏱ Tiempo: ${formatearMinSeg(tiempoTranscurridoBase)}`;
  intervaloTemporizador = setInterval(() => {
    const transcurrido = tiempoTranscurridoActual();
    document.getElementById("temporizador").textContent = `⏱ Tiempo: ${formatearMinSeg(transcurrido)}`;
    if (transcurrido % 10 === 0) {
      import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
        autoguardarProgreso({
          respuestas_usuario: respuestasUsuario,
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

function mostrarPregunta(i) {
  indicePreguntaActual = i;
  const p = preguntas[i];
  let textoPregunta = p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, "");
  let html = `<form id="form-pregunta">
    <div class="pregunta-en-negrita">
      <span>${i + 1}. ${textoPregunta}</span>
      ${botonFavoritaHTML(textosFavoritas.has(p.pregunta))}
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
      <button type="button" id="btn-desmarcar" class="age-btn age-btn-outline">Desmarcar</button>
      <button type="button" id="btn-guardar-salir" class="age-btn age-btn-outline">💾 Guardar y salir</button>
    </div>
    <button type="submit" class="age-btn age-btn-primary age-btn-block" style="margin-top:12px;">
      ${i + 1 < preguntas.length ? 'Siguiente →' : 'Finalizar test'}
    </button>
    <button type="button" id="btn-finalizar" class="btn btn-danger btn-block" style="margin-top:10px;">Finalizar Test</button>
  </form>`;

  document.getElementById("contenedor-test").innerHTML = html;
  activarBotonFavorita(document.getElementById("contenedor-test"), p, oposicionActual, textosFavoritas);

  document.getElementById("btn-desmarcar").addEventListener("click", () => {
    document.querySelectorAll('input[name="respuesta"]:checked').forEach(el => el.checked = false);
    respuestasUsuario[i] = null;
  });

  document.getElementById("btn-guardar-salir").addEventListener("click", async function () {
    const boton = this;
    boton.disabled = true;
    boton.textContent = "Guardando…";
    const { guardarProgresoInmediato } = await import("/assets/test-progreso.js");
    await guardarProgresoInmediato({
      respuestas_usuario: respuestasUsuario,
      indice_actual: indicePreguntaActual,
      tiempo_transcurrido_segundos: tiempoTranscurridoActual()
    });
    window.location.href = "/mis-tests/";
  });

  if (i > 0) {
    document.getElementById("btn-anterior").addEventListener("click", () => mostrarPregunta(i - 1));
  }

  document.getElementById("btn-finalizar").addEventListener("click", confirmarFinalizar);

  document.getElementById("form-pregunta").addEventListener("submit", function (e) {
    e.preventDefault();
    const seleccion = document.querySelector('input[name="respuesta"]:checked');
    respuestasUsuario[i] = seleccion ? seleccion.value : null;
    import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
      autoguardarProgreso({
        respuestas_usuario: respuestasUsuario,
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
  document.getElementById("contenedor-test").innerHTML = "";
  document.getElementById("contenedor-test").style.display = "none";
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
      const { obtenerOposicionActual: obtenerOposicionResume } = await import("/assets/oposicion.js");
      oposicionActual = guardado.oposicion || obtenerOposicionResume();
      const favoritasApiResume = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApiResume.botonFavoritaHTML;
      activarBotonFavorita = favoritasApiResume.activarBotonFavorita;
      textosFavoritas = await favoritasApiResume.cargarTextosFavoritas(oposicionActual);
      iniciarTemporizador(guardado.tiempo_transcurrido_segundos || 0);
      mostrarPregunta(guardado.indice_actual || 0);
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
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
        indice_actual: 0,
        pagina_origen: "/repetir-test/"
      });
      activarGuardadoAlSalir(() => ({
        respuestas_usuario: respuestasUsuario,
        indice_actual: indicePreguntaActual,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      }));
      iniciarTemporizador();
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
      indice_actual: 0,
      pagina_origen: "/repetir-test/"
    });
    activarGuardadoAlSalir(() => ({
      respuestas_usuario: respuestasUsuario,
      indice_actual: indicePreguntaActual,
      tiempo_transcurrido_segundos: tiempoTranscurridoActual()
    }));
    iniciarTemporizador();
    mostrarPregunta(0);
  } catch (err) {
    console.error("Error:", err);
    document.getElementById("contenedor-test").innerHTML = "<p>Error al cargar el test.</p>";
  }
});
