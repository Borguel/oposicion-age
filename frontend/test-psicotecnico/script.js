// Test Psicotécnico: las dos pruebas aptitudinales (razonamiento verbal y
// razonamiento espacial) de una oposición con prueba psicotécnica propia
// (hoy, solo Metro -- ver oposiciones.coleccion_psicotecnico). A propósito
// NO comparte página con /test-oficial/: aquí no hay selector de temas, ni
// reparto, ni checkbox de exclusión -- cada prueba se hace siempre por
// separado, nunca mezclada con la otra ni con el temario. Pero, igual que
// en Test Oficial, el usuario sí elige cuántas preguntas quiere (hasta 75,
// las que tiene cada prueba) y si quiere cronometrarlo o no.
// El motor de hacer el test en sí (temporizador, autoguardado, navegador de
// preguntas, resultados, reanudar) es el mismo que usan las demás páginas
// de test (ver /test-oficial/, /test-personalizado/).
import { icono } from "/assets/icons.js";
import { marcarContenidoListo } from "/assets/auth.js";

const TIPO_TEST = "psicotecnico";
const ENDPOINT_GENERAR = "/generar-test-psicotecnico";
const NOMBRE_PRUEBA = { verbal: "razonamiento verbal", espacial: "razonamiento espacial" };

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

async function obtenerAuthHeaders() {
  const { obtenerAuthHeaders: fn } = await import("/assets/auth.js");
  return fn();
}

let preguntas = [];
let indicePreguntaActual = 0;
let respuestasUsuario = [];
let marcadasRevision = [];
let marcadasDuda = [];
let visitadas = [];
let tiempoInicio;
let intervaloTemporizador;
let tiempoLimite = null;
let intervaloCronometro = null;
let aciertos = 0;
let fallos = 0;
let sinResponder = 0;
let porcentaje = 0;
let tiempoTotalAsignado = 0;
let tiempoTranscurridoBase = 0;
let oposicionActual = "";
let textosFavoritas = new Set();
let botonFavoritaHTML = () => "";
let activarBotonFavorita = () => {};
let pruebaElegida = "";

function tiempoTranscurridoActual() {
  if (tiempoLimite !== null) return tiempoTotalAsignado - tiempoLimite;
  return tiempoTranscurridoBase + Math.floor((Date.now() - tiempoInicio) / 1000);
}

document.addEventListener("DOMContentLoaded", function() {
  document.getElementById('modo_cronometrado').addEventListener('change', function() {
    document.getElementById('tiempo_cronometro').style.display = this.checked ? 'flex' : 'none';
  });
});

// Elegir una prueba (verbal/espacial) no la arranca directamente -- revela
// el formulario de "cuántas preguntas / cronómetro o no", igual que Test
// Oficial deja configurar el test antes de generarlo.
function elegirPrueba(prueba) {
  pruebaElegida = prueba;
  document.getElementById("prueba_elegida").value = prueba;
  document.getElementById("btn-prueba-verbal").classList.toggle("selected", prueba === "verbal");
  document.getElementById("btn-prueba-espacial").classList.toggle("selected", prueba === "espacial");
  document.getElementById("titulo-formulario-psicotecnico").textContent =
    `Configura tu prueba de ${NOMBRE_PRUEBA[prueba]}`;
  document.getElementById("tarjeta-formulario").style.display = "block";
}
document.getElementById("btn-prueba-verbal").addEventListener("click", () => elegirPrueba("verbal"));
document.getElementById("btn-prueba-espacial").addEventListener("click", () => elegirPrueba("espacial"));

function ocultarSelectorPsicotecnico() {
  document.getElementById("selector-psicotecnico").style.display = "none";
  document.getElementById("tarjeta-formulario").style.display = "none";
}

async function guardarTestAutomaticamente() {
  const contenido = preguntas;
  const respuestas = respuestasUsuario;
  const tiempo = tiempoTranscurridoActual();
  const metadatos = { tipo: TIPO_TEST, tiempo, temas: [] };
  const { testIdEnCurso, limpiarSeguimiento } = await import("/assets/test-progreso.js");
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const oposicion = obtenerOposicionActual();
    const res = await fetch("https://oposicion-age.onrender.com/guardar-test", {
      method: "POST",
      headers: {"Content-Type": "application/json", ...authHeaders},
      body: JSON.stringify({ contenido, respuestas, metadatos, oposicion, test_id: testIdEnCurso(), marcadas_duda: marcadasDuda })
    });
    const datos = await res.json();
    if (!res.ok) {
      Swal.fire("Error al guardar", datos.error || "No se pudo guardar el test.", "error");
    } else {
      limpiarSeguimiento();
    }
  } catch (e) {
    console.error("Error al guardar test:", e);
  }
}

function formatearTiempo(segundos) {
  const m = String(Math.floor(segundos / 60)).padStart(2, '0');
  const s = String(segundos % 60).padStart(2, '0');
  return `${m}:${s}`;
}

// tiempoRestanteReanudado/tiempoTranscurridoReanudado: igual que en
// /test-oficial/, para que al reanudar un test guardado el cronómetro (o el
// contador libre) continúe desde donde se dejó en vez de reiniciarse.
function iniciarTemporizador(tiempoRestanteReanudado, tiempoTranscurridoReanudado) {
  tiempoInicio = Date.now();
  const elTemporizador = document.getElementById("temporizador");
  const elTexto = document.getElementById("temporizador-texto");
  elTemporizador.style.display = "flex";
  const botonToggle = document.getElementById("btn-toggle-temporizador");
  botonToggle.onclick = () => elTemporizador.classList.toggle("temporizador-oculto");
  if (document.getElementById('modo_cronometrado').checked) {
    if (tiempoRestanteReanudado == null) {
      const minutos = parseInt(document.getElementById('minutos_cronometro').value) || 20;
      tiempoLimite = minutos * 60;
      tiempoTotalAsignado = tiempoLimite;
    } else {
      tiempoLimite = tiempoRestanteReanudado;
    }
    document.getElementById("barra-progreso-tiempo").style.display = "block";
    elTexto.innerHTML = `${icono("reloj", 16)} Tiempo restante: <span class="pulse">${formatearTiempo(tiempoLimite)}</span>`;
    elTemporizador.classList.toggle("temporizador-urgente", tiempoLimite <= 300);
    intervaloTemporizador = setInterval(() => {
      tiempoLimite--;
      if (tiempoLimite <= 0) {
        clearInterval(intervaloTemporizador);
        Swal.fire({
          title: '¡Tiempo terminado!',
          text: 'Se ha finalizado el test automáticamente.',
          icon: 'warning',
          confirmButtonText: 'Ver resultados'
        }).then(() => {
          mostrarResultados();
        });
        return;
      }
      elTexto.innerHTML = `${icono("reloj", 16)} Tiempo restante: <span class="pulse">${formatearTiempo(tiempoLimite)}</span>`;
      elTemporizador.classList.toggle("temporizador-urgente", tiempoLimite <= 300);
      const porcentajeTiempo = ((tiempoTotalAsignado - tiempoLimite) / tiempoTotalAsignado) * 100;
      document.getElementById("progreso-tiempo").style.width = `${porcentajeTiempo}%`;
      const elTextoProgresoTiempo = document.getElementById("texto-progreso-tiempo");
      if (elTextoProgresoTiempo) elTextoProgresoTiempo.textContent = `${Math.round(porcentajeTiempo)}%`;
      if (tiempoLimite % 10 === 0) {
        import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
          autoguardarProgreso({
            respuestas_usuario: respuestasUsuario,
            marcadas_revision: marcadasRevision,
            marcadas_duda: marcadasDuda,
            indice_actual: indicePreguntaActual,
            tiempo_restante_segundos: tiempoLimite
          });
        });
      }
    }, 1000);
  } else {
    tiempoTranscurridoBase = tiempoTranscurridoReanudado || 0;
    elTexto.innerHTML = `${icono("reloj", 16)} Tiempo: ${formatearTiempo(tiempoTranscurridoBase)}`;
    intervaloTemporizador = setInterval(() => {
      const transcurrido = tiempoTranscurridoActual();
      elTexto.innerHTML = `${icono("reloj", 16)} Tiempo: ${formatearTiempo(transcurrido)}`;
      if (transcurrido % 10 === 0) {
        import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
          autoguardarProgreso({
            respuestas_usuario: respuestasUsuario,
            marcadas_revision: marcadasRevision,
            marcadas_duda: marcadasDuda,
            indice_actual: indicePreguntaActual,
            tiempo_transcurrido_segundos: transcurrido
          });
        });
      }
    }, 1000);
  }
}

document.getElementById("form-generar-test").addEventListener("submit", async function(e) {
  e.preventDefault();
  if (!pruebaElegida) return;
  const prueba = pruebaElegida;
  const numPreguntas = parseInt(document.getElementById("num_preguntas").value) || 25;
  const modoCronometrado = document.getElementById('modo_cronometrado').checked;
  const minutosCronometro = parseInt(document.getElementById('minutos_cronometro').value) || 20;

  document.getElementById("barra-progreso-tiempo").style.display = "none";
  ocultarSelectorPsicotecnico();
  document.getElementById("contenedor-test").style.display = "block";
  document.getElementById("contenedor-test").innerHTML = `
    <div class="carga-generando">
      <p id="mensaje-carga">Obteniendo preguntas...</p>
      <div class="barra-indeterminada"><div class="barra-indeterminada-fill"></div></div>
    </div>
  `;
  const mensajes = [
    "Obteniendo preguntas...",
    "Preparando la prueba...",
    "Cargando figuras...",
    "Ya casi está..."
  ];
  let indiceMensaje = 0;
  const intervalCarga = setInterval(() => {
    indiceMensaje = (indiceMensaje + 1) % mensajes.length;
    const elMensaje = document.getElementById("mensaje-carga");
    if (elMensaje) elMensaje.textContent = mensajes[indiceMensaje];
  }, 2200);
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) { clearInterval(intervalCarga); return; }
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const oposicion = obtenerOposicionActual();
    const res = await fetch("https://oposicion-age.onrender.com" + ENDPOINT_GENERAR, {
      method: "POST",
      headers: {"Content-Type": "application/json", ...authHeaders},
      body: JSON.stringify({ oposicion, prueba, num_preguntas: numPreguntas })
    });
    clearInterval(intervalCarga);
    if (res.status === 403) {
      const datosError = await res.json();
      document.getElementById('contenedor-test').innerHTML = `
        <p>${datosError.error === "Requiere plan superior" ? `Este tipo de test requiere el plan <strong>${datosError.plan_requerido}</strong>.` : "No tienes acceso a esta función."}</p>
        <a class="btn btn-primary" href="/planes/">Ver planes</a>
      `;
      return;
    }
    if (res.status === 429) {
      const datosError = await res.json();
      document.getElementById('contenedor-test').innerHTML = `
        <p class="icono-inline">${icono("arena", 18)} ${datosError.error || "Has alcanzado el límite de uso de esta herramienta por ahora."}</p>
        <a class="btn btn-primary" href="/planes/">Ver planes</a>
      `;
      return;
    }
    const datos = await res.json();
    preguntas = datos.test || [];
    if (preguntas.length === 0) {
      document.getElementById('contenedor-test').innerHTML = `<p>${datos.mensaje || "No se han recibido preguntas."}</p>`;
      return;
    }
    respuestasUsuario = Array(preguntas.length).fill(null);
    marcadasRevision = Array(preguntas.length).fill(false);
    marcadasDuda = Array(preguntas.length).fill(false);
    visitadas = Array(preguntas.length).fill(false);
    indicePreguntaActual = 0;
    oposicionActual = oposicion;
    const favoritasApi = await import("/assets/favoritas.js");
    botonFavoritaHTML = favoritasApi.botonFavoritaHTML;
    activarBotonFavorita = favoritasApi.activarBotonFavorita;
    textosFavoritas = await favoritasApi.cargarTextosFavoritas(oposicion);

    const { generarTestId, guardarContenidoInicial, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
    generarTestId();
    guardarContenidoInicial({
      oposicion, tipo: TIPO_TEST, temas: [],
      contenido: preguntas,
      respuestas_usuario: respuestasUsuario,
      marcadas_revision: marcadasRevision,
      marcadas_duda: marcadasDuda,
      indice_actual: indicePreguntaActual,
      modo_cronometrado: modoCronometrado,
      tiempo_restante_segundos: modoCronometrado ? minutosCronometro * 60 : null,
      tiempo_total_asignado_segundos: modoCronometrado ? minutosCronometro * 60 : null,
      pagina_origen: "/test-psicotecnico/"
    });
    activarGuardadoAlSalir(() => ({
      respuestas_usuario: respuestasUsuario,
      marcadas_revision: marcadasRevision,
      marcadas_duda: marcadasDuda,
      indice_actual: indicePreguntaActual,
      modo_cronometrado: tiempoLimite !== null,
      tiempo_restante_segundos: tiempoLimite,
      tiempo_transcurrido_segundos: tiempoTranscurridoActual()
    }));

    iniciarTemporizador();
    document.getElementById("navegador-preguntas").style.display = "flex";
    mostrarPregunta(indicePreguntaActual);
    import("/assets/onboarding-tour.js").then(({ mostrarTourTest }) => mostrarTourTest());
  } catch (error) {
    clearInterval(intervalCarga);
    const contenedorTest = document.getElementById('contenedor-test');
    contenedorTest.innerHTML = `
      <p>Error al generar el test: ${error.message}</p>
      <button type="button" class="btn btn-primary" id="btn-volver-a-intentar">Volver a intentar</button>
    `;
    document.getElementById('btn-volver-a-intentar').addEventListener('click', () => location.reload());
    console.error(error);
  }
});

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

async function mostrarPregunta(i) {
  // El texto de la pregunta/opciones se escapa antes de inyectarlo en
  // innerHTML (misma función que usa la pantalla de resultados, ver
  // assets/resultados-test.js).
  const { escaparHtml } = await import("/assets/resultados-test.js");
  indicePreguntaActual = i;
  visitadas[i] = true;
  actualizarNavegadorPreguntas();
  const p = preguntas[i];
  let textoPregunta = escaparHtml(p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, ""));
  let html = `<form id="form-pregunta">
    <div class="pregunta-en-negrita">
      <span>${i + 1}. ${textoPregunta}</span>
      <div class="pregunta-acciones-header">
        ${botonFavoritaHTML(textosFavoritas.has(p.pregunta))}
        <button type="button" id="btn-marcar-revision" class="btn-marcar-revision${marcadasRevision[i] ? " activa" : ""} icono-inline" aria-label="Marcar para revisión" title="Marcar esta pregunta para revisarla antes de terminar el test (queda resaltada en el mapa de preguntas)">${icono("marcador", 16)}</button>
        <button type="button" id="btn-marcar-duda" class="btn-marcar-duda${marcadasDuda[i] ? " activa" : ""} icono-inline" aria-label="Marcar como duda" title="Marcar esta pregunta como duda: al terminar el test verás la nota contándola y sin contarla">${icono("pregunta", 16)}</button>
      </div>
    </div>`;
  if (p.imagen) {
    html += `<div class="pregunta-imagen"><img src="${escaparHtml(p.imagen)}" alt="Figura de la pregunta ${i + 1}" loading="lazy"></div>`;
  }
  for (const letra in p.opciones) {
    const opcion = escaparHtml(p.opciones[letra]);
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
  const bloquePregunta = document.querySelector("#form-pregunta .pregunta-en-negrita");
  if (bloquePregunta) {
    bloquePregunta.dataset.respuestaCorrecta = p.respuesta_correcta || "";
    bloquePregunta.dataset.explicacion = p.explicacion || "";
  }
  activarBotonFavorita(document.getElementById("contenedor-test"), p, oposicionActual, textosFavoritas);
  document.getElementById("btn-marcar-revision").addEventListener("click", function() {
    marcadasRevision[i] = !marcadasRevision[i];
    this.classList.toggle("activa", marcadasRevision[i]);
    actualizarNavegadorPreguntas();
    import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
      autoguardarProgreso({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        marcadas_duda: marcadasDuda,
        indice_actual: i
      });
    });
  });
  document.getElementById("btn-marcar-duda").addEventListener("click", function() {
    if (!marcadasDuda[i] && (respuestasUsuario[i] === null || respuestasUsuario[i] === undefined)) {
      Swal.fire({ icon: "info", title: "Responde antes de marcarla", text: "Debes contestar esta pregunta antes de poder marcarla como duda." });
      return;
    }
    marcadasDuda[i] = !marcadasDuda[i];
    this.classList.toggle("activa", marcadasDuda[i]);
    import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
      autoguardarProgreso({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        marcadas_duda: marcadasDuda,
        indice_actual: i
      });
    });
  });
  document.querySelectorAll('input[name="respuesta"]').forEach((radio) => {
    radio.addEventListener("click", function() {
      if (respuestasUsuario[i] === this.value) {
        this.checked = false;
        respuestasUsuario[i] = null;
      } else {
        respuestasUsuario[i] = this.value;
      }
      actualizarNavegadorPreguntas();
    });
  });
  const botonGuardarSalir = document.getElementById("btn-guardar-salir");
  botonGuardarSalir.style.display = "block";
  botonGuardarSalir.disabled = false;
  botonGuardarSalir.innerHTML = `${icono("guardar", 16)} Guardar y salir`;
  botonGuardarSalir.onclick = async function() {
    const boton = this;
    boton.disabled = true;
    boton.textContent = "Guardando…";
    const { guardarProgresoInmediato } = await import("/assets/test-progreso.js");
    await guardarProgresoInmediato({
      respuestas_usuario: respuestasUsuario,
      marcadas_revision: marcadasRevision,
      marcadas_duda: marcadasDuda,
      indice_actual: indicePreguntaActual,
      tiempo_restante_segundos: tiempoLimite,
      tiempo_transcurrido_segundos: tiempoTranscurridoActual()
    });
    window.location.href = "/mis-tests/";
  };
  document.getElementById("btn-finalizar").style.display = "block";
  if (i > 0 && document.getElementById("btn-anterior")) {
    document.getElementById("btn-anterior").addEventListener("click", () => {
      mostrarPregunta(i - 1);
    });
  }
  document.getElementById("form-pregunta").addEventListener("submit", function(e) {
    e.preventDefault();
    const seleccion = document.querySelector('input[name="respuesta"]:checked');
    const respuestaSeleccionada = seleccion ? seleccion.value : null;
    respuestasUsuario[i] = respuestaSeleccionada;
    import("/assets/test-progreso.js").then(({ autoguardarProgreso }) => {
      autoguardarProgreso({
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        marcadas_duda: marcadasDuda,
        indice_actual: i + 1 < preguntas.length ? i + 1 : i,
        tiempo_restante_segundos: tiempoLimite,
        tiempo_transcurrido_segundos: tiempoTranscurridoActual()
      });
    });
    if (i + 1 < preguntas.length) {
      mostrarPregunta(i + 1);
    } else {
      const sinContestar = respuestasUsuario.filter(r => r === null).length;
      const numDudasSinResolver = marcadasDuda.filter(Boolean).length;
      const avisos = [];
      if (sinContestar > 0) avisos.push(`has dejado ${sinContestar} pregunta${sinContestar > 1 ? 's' : ''} sin contestar`);
      if (numDudasSinResolver > 0) avisos.push(`has marcado ${numDudasSinResolver} pregunta${numDudasSinResolver > 1 ? 's' : ''} como duda${numDudasSinResolver > 1 ? 's' : ''}`);
      let mensaje = avisos.length
        ? avisos.join(' y ').replace(/^./, (c) => c.toUpperCase()) + '.'
        : '¿Quieres finalizar el test y ver los resultados?';
      Swal.fire({
        icon: 'question',
        title: '¿Deseas finalizar el test?',
        text: mensaje,
        showCancelButton: true,
        confirmButtonText: 'Sí, corregir',
        cancelButtonText: 'Seguir revisando',
      }).then((result) => {
        if (result.isConfirmed) {
          mostrarResultados();
        }
      });
    }
  });
}

let ultimasEstadisticas = null;

async function mostrarResultados() {
  clearInterval(intervaloTemporizador);
  if (tiempoLimite !== null) clearInterval(intervaloCronometro);
  document.getElementById("temporizador").style.display = "none";
  document.getElementById("barra-progreso-tiempo").style.display = "none";
  document.getElementById("navegador-preguntas").style.display = "none";
  document.getElementById("contenedor-test").innerHTML = "";
  document.getElementById("contenedor-test").style.display = "none";
  document.getElementById("btn-finalizar").style.display = "none";
  document.getElementById("btn-guardar-salir").style.display = "none";
  const cont = document.getElementById("contenedor-resultados");
  cont.style.display = "block";

  const { renderizarResultadosTest } = await import("/assets/resultados-test.js");
  ultimasEstadisticas = renderizarResultadosTest({
    contenedor: cont,
    preguntas,
    respuestasUsuario,
    marcadasDuda
  });
  aciertos = ultimasEstadisticas.aciertos;
  fallos = ultimasEstadisticas.fallos;
  sinResponder = ultimasEstadisticas.sinResponder;
  porcentaje = ultimasEstadisticas.porcentaje;

  document.getElementById("btn-descargar-pdf").style.display = "block";
  guardarTestAutomaticamente();
}

document.addEventListener("DOMContentLoaded", function() {
  const btnFinalizar = document.getElementById("btn-finalizar");
  if (!btnFinalizar) return;
  btnFinalizar.addEventListener("click", () => {
    const sinContestar = respuestasUsuario.filter(r => r === null).length;
    const numDudasSinResolver = marcadasDuda.filter(Boolean).length;
    const avisos = [];
    if (sinContestar > 0) avisos.push(`has dejado ${sinContestar} pregunta${sinContestar > 1 ? 's' : ''} sin contestar`);
    if (numDudasSinResolver > 0) avisos.push(`has marcado ${numDudasSinResolver} pregunta${numDudasSinResolver > 1 ? 's' : ''} como duda${numDudasSinResolver > 1 ? 's' : ''}`);
    let mensaje = avisos.length
      ? avisos.join(' y ').replace(/^./, (c) => c.toUpperCase()) + '.'
      : '¿Quieres finalizar el test y ver los resultados?';
    Swal.fire({
      icon: 'question',
      title: '¿Deseas finalizar el test?',
      text: mensaje,
      showCancelButton: true,
      confirmButtonText: 'Sí, corregir',
      cancelButtonText: 'Seguir revisando',
    }).then((result) => {
      if (result.isConfirmed) {
        mostrarResultados();
      }
    });
  });
});

document.getElementById("btn-descargar-pdf").addEventListener("click", async function() {
  const { descargarResultadosPDF } = await import("/assets/resultados-test.js");
  descargarResultadosPDF({
    preguntas,
    respuestasUsuario,
    stats: ultimasEstadisticas,
    titulo: "Resultados del Test Psicotécnico"
  });
});

// Reanuda un test guardado "en_progreso" (llegado desde "Mis Tests" con
// ?resume=<id>) exactamente donde se dejó -- igual que en /test-oficial/.
async function reanudarTest(resumeId) {
  const { usarTestId, cargarTestEnProgreso, activarGuardadoAlSalir } = await import("/assets/test-progreso.js");
  const guardado = await cargarTestEnProgreso(resumeId);
  if (!guardado || !guardado.contenido || !guardado.contenido.length) {
    Swal.fire({
      icon: 'error',
      title: 'No se pudo reanudar',
      text: 'No se ha encontrado ese test guardado.',
      confirmButtonText: 'Entendido'
    });
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
  marcadasDuda = Array.isArray(guardado.marcadas_duda) && guardado.marcadas_duda.length === preguntas.length
    ? guardado.marcadas_duda
    : Array(preguntas.length).fill(false);
  indicePreguntaActual = guardado.indice_actual || 0;
  visitadas = Array(preguntas.length).fill(false);
  for (let k = 0; k <= indicePreguntaActual && k < visitadas.length; k++) visitadas[k] = true;
  const { obtenerOposicionActual } = await import("/assets/oposicion.js");
  oposicionActual = guardado.oposicion || obtenerOposicionActual();
  const favoritasApi = await import("/assets/favoritas.js");
  botonFavoritaHTML = favoritasApi.botonFavoritaHTML;
  activarBotonFavorita = favoritasApi.activarBotonFavorita;
  textosFavoritas = await favoritasApi.cargarTextosFavoritas(oposicionActual);

  ocultarSelectorPsicotecnico();
  document.getElementById("contenedor-test").style.display = "block";

  if (guardado.modo_cronometrado) {
    document.getElementById('modo_cronometrado').checked = true;
    tiempoTotalAsignado = guardado.tiempo_total_asignado_segundos || guardado.tiempo_restante_segundos || 0;
    iniciarTemporizador(guardado.tiempo_restante_segundos ?? tiempoTotalAsignado);
  } else {
    document.getElementById('modo_cronometrado').checked = false;
    iniciarTemporizador(null, guardado.tiempo_transcurrido_segundos || 0);
  }
  document.getElementById("navegador-preguntas").style.display = "flex";
  mostrarPregunta(indicePreguntaActual);
  activarGuardadoAlSalir(() => ({
    respuestas_usuario: respuestasUsuario,
    marcadas_revision: marcadasRevision,
    marcadas_duda: marcadasDuda,
    indice_actual: indicePreguntaActual,
    modo_cronometrado: tiempoLimite !== null,
    tiempo_restante_segundos: tiempoLimite,
    tiempo_transcurrido_segundos: tiempoTranscurridoActual()
  }));
}

window.addEventListener("load", async () => {
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("basico"))) {
    marcarContenidoListo();
    return;
  }
  const { idDesdeUrlResume } = await import("/assets/test-progreso.js");
  const resumeId = idDesdeUrlResume();
  if (resumeId) {
    await reanudarTest(resumeId);
  }
  marcarContenidoListo();
});
