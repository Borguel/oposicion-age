import { icono } from "/assets/icons.js";

async function obtenerAuthHeaders() {
  const { obtenerAuthHeaders: fn } = await import("/assets/auth.js");
  return fn();
}

let preguntas = [];
let respuestasUsuario = [];
// Preguntas marcadas con la banderita "revisar más tarde" y preguntas ya
// visitadas en esta sesión (para distinguir en el navegador el gris de "no
// visitada" del rojo de "visitada pero sin responder").
let marcadasRevision = [];
let marcadasDuda = [];
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
let listaTemasGlobal = [];
// Estadísticas del intento ORIGINAL (?repetir=<id>), para comparar contra
// el intento nuevo en la pantalla de resultados -- null si se llegó desde
// "último test"/reanudado, donde no hay un intento anterior concreto con
// el que comparar (aunque el test en sí ya fuera una repetición previa).
let intentoOriginal = null;
// Repetir-test no tiene un formulario propio (arranca directo al cargar la
// página), así que el modo cronometrado no viene de un checkbox en el DOM
// como en test-personalizado -- se pregunta con un diálogo antes de
// empezar un intento NUEVO (ver preguntarModoCronometrado) y se guarda aquí
// para que iniciarTemporizador() sepa qué modo usar.
let modoCronometradoElegido = false;
let minutosElegidos = 60;
let tiempoLimite = null;
let tiempoTotalAsignado = 0;

function formatearMinSeg(segundos) {
  const m = String(Math.floor(segundos / 60)).padStart(2, '0');
  const s = String(segundos % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function tiempoTranscurridoActual() {
  if (tiempoLimite !== null) return tiempoTotalAsignado - tiempoLimite;
  return tiempoTranscurridoBase + Math.floor((Date.now() - tiempoInicio) / 1000);
}

// Antes de empezar un intento NUEVO (no al reanudar uno ya guardado), deja
// elegir si este repaso se hace contrarreloj -- mismo caso de uso real que
// los demás tipos de test: simular otra vez condiciones de examen.
async function preguntarModoCronometrado() {
  const confirmacion = await Swal.fire({
    icon: 'question',
    title: '¿Cronometrar este intento?',
    text: 'Puedes repetir el test con un límite de tiempo, igual que en un examen real.',
    showCancelButton: true,
    confirmButtonText: 'Sí, cronometrar',
    cancelButtonText: 'No, sin límite de tiempo'
  });
  if (!confirmacion.isConfirmed) return { cronometrado: false, minutos: 60 };
  const { value: minutos } = await Swal.fire({
    title: 'Tiempo disponible',
    input: 'number',
    inputLabel: 'Minutos para completar el test',
    inputValue: 60,
    inputAttributes: { min: 1 },
    confirmButtonText: 'Empezar',
    inputValidator: (valor) => (!valor || valor <= 0) ? 'Introduce un número de minutos válido' : undefined
  });
  return { cronometrado: true, minutos: parseInt(minutos) || 60 };
}

// tiempoRestanteReanudado/tiempoTranscurridoReanudado: al reanudar un test
// guardado (mismo patrón que test-personalizado) para que el cronómetro/
// contador siga desde donde se dejó en vez de reiniciarse.
function iniciarTemporizador(tiempoRestanteReanudado, tiempoTranscurridoReanudado) {
  tiempoInicio = Date.now();
  const elTemporizador = document.getElementById("temporizador");
  const elTexto = document.getElementById("temporizador-texto");
  elTemporizador.style.display = "flex";
  document.getElementById("btn-toggle-temporizador").onclick = () => elTemporizador.classList.toggle("temporizador-oculto");

  if (modoCronometradoElegido) {
    if (tiempoRestanteReanudado == null) {
      tiempoLimite = minutosElegidos * 60;
      tiempoTotalAsignado = tiempoLimite;
    } else {
      tiempoLimite = tiempoRestanteReanudado;
      // tiempoTotalAsignado ya lo fija quien llama (restaurado del guardado)
    }
    document.getElementById("barra-progreso-tiempo").style.display = "block";
    elTexto.innerHTML = `${icono("reloj", 16)} Tiempo restante: <span class="pulse">${formatearMinSeg(tiempoLimite)}</span>`;
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
        }).then(() => mostrarResultados());
        return;
      }
      elTexto.innerHTML = `${icono("reloj", 16)} Tiempo restante: <span class="pulse">${formatearMinSeg(tiempoLimite)}</span>`;
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
    elTexto.innerHTML = `${icono("reloj", 16)} Tiempo: ${formatearMinSeg(tiempoTranscurridoBase)}`;
    intervaloTemporizador = setInterval(() => {
      const transcurrido = tiempoTranscurridoActual();
      elTexto.innerHTML = `${icono("reloj", 16)} Tiempo: ${formatearMinSeg(transcurrido)}`;
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

function confirmarFinalizar() {
  const sinContestar = respuestasUsuario.filter(r => r === null).length;
  const numDudasSinResolver = marcadasDuda.filter(Boolean).length;
  const avisos = [];
  if (sinContestar > 0) avisos.push(`has dejado ${sinContestar} pregunta${sinContestar > 1 ? 's' : ''} sin contestar`);
  if (numDudasSinResolver > 0) avisos.push(`has marcado ${numDudasSinResolver} pregunta${numDudasSinResolver > 1 ? 's' : ''} como duda${numDudasSinResolver > 1 ? 's' : ''}`);
  const mensaje = avisos.length
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

async function mostrarPregunta(i) {
  // El texto de la pregunta/opciones viene generado por IA -- se escapa
  // antes de inyectarlo en innerHTML (mismo motivo y misma función que ya
  // usa la pantalla de resultados, ver assets/resultados-test.js).
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

  document.getElementById("btn-marcar-revision").addEventListener("click", function () {
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
  botonGuardarSalir.innerHTML = `${icono("guardar", 16)} Guardar y salir`;
  botonGuardarSalir.onclick = async function () {
    const boton = this;
    boton.disabled = true;
    boton.textContent = "Guardando…";
    const { guardarProgresoInmediato } = await import("/assets/test-progreso.js");
    await guardarProgresoInmediato({
      respuestas_usuario: respuestasUsuario,
      marcadas_revision: marcadasRevision,
      marcadas_duda: marcadasDuda,
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
        marcadas_duda: marcadasDuda,
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

// Bloque "comparar intentos": se inserta al principio de los resultados
// (renderizarResultadosTest ya rellena el resto de #contenedor-resultados,
// así que esto se antepone con insertAdjacentHTML en vez de tocar el
// módulo compartido, que no sabe nada de intentos anteriores).
function generarComparacionIntentosHTML(original, nuevo) {
  const deltaAciertos = nuevo.aciertos - original.aciertos;
  let mensaje;
  let clase;
  if (deltaAciertos > 0) {
    mensaje = `¡Has mejorado! ${deltaAciertos} acierto${deltaAciertos !== 1 ? "s" : ""} más que la vez anterior.`;
    clase = "comparacion-mejora";
  } else if (deltaAciertos < 0) {
    mensaje = `${Math.abs(deltaAciertos)} acierto${Math.abs(deltaAciertos) !== 1 ? "s" : ""} menos que la vez anterior.`;
    clase = "comparacion-empeora";
  } else {
    mensaje = "Mismos aciertos que en tu intento anterior.";
    clase = "comparacion-igual";
  }
  return `
    <div class="comparacion-intentos ${clase}">
      <div class="comparacion-intentos-titulo icono-inline">${icono("repetir", 18)} Comparado con tu intento anterior</div>
      <div class="comparacion-intentos-fila">
        <span class="comparacion-intentos-etiqueta">Aciertos</span>
        <span class="comparacion-intentos-valores">${original.aciertos} → <strong>${nuevo.aciertos}</strong></span>
      </div>
      <div class="comparacion-intentos-fila">
        <span class="comparacion-intentos-etiqueta">Fallos</span>
        <span class="comparacion-intentos-valores">${original.fallos} → <strong>${nuevo.fallos}</strong></span>
      </div>
      <div class="comparacion-intentos-mensaje">${mensaje}</div>
    </div>`;
}

async function mostrarResultados() {
  clearInterval(intervaloTemporizador);
  document.getElementById("temporizador").style.display = "none";
  document.getElementById("barra-progreso-tiempo").style.display = "none";
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
    listaTemas: listaTemasGlobal,
    marcadasDuda
  });

  if (intentoOriginal && intentoOriginal.aciertos !== null) {
    cont.insertAdjacentHTML("afterbegin", generarComparacionIntentosHTML(intentoOriginal, ultimasEstadisticas));
  }

  document.getElementById("btn-descargar-pdf").style.display = "block";

  const segundosTotales = tiempoTranscurridoActual();
  const { testIdEnCurso, limpiarSeguimiento } = await import("/assets/test-progreso.js");
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const res = await fetch("https://oposicion-age.onrender.com/guardar-test", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({
        contenido: preguntas,
        respuestas: respuestasUsuario,
        metadatos: { tiempo: segundosTotales, tipo: "repetido", temas: [] },
        oposicion: obtenerOposicionActual(),
        test_id: testIdEnCurso(),
        marcadas_duda: marcadasDuda
      })
    });
    const datos = await res.json();
    if (!res.ok) {
      const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
      mostrarErrorGlobal(datos.error || "No se pudo guardar el resultado de tu test. Tus respuestas de esta pantalla siguen visibles, pero no han quedado guardadas en Mis Tests.");
    } else {
      limpiarSeguimiento();
    }
  } catch (err) {
    console.error("❌ Error al guardar test:", err);
    const { mostrarErrorGlobal } = await import("/assets/notificaciones.js");
    mostrarErrorGlobal("No se pudo guardar el resultado de tu test. Tus respuestas de esta pantalla siguen visibles, pero no han quedado guardadas en Mis Tests.");
  }
}

// Solo para pintar el desglose por tema en la pantalla de resultados
// (renderizarResultadosTest) -- no se usa aquí ningún selector de temas
// visible, a diferencia de test-personalizado.
async function cargarListaTemas(oposicion) {
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    const res = await fetch(`https://oposicion-age.onrender.com/temas-disponibles?oposicion=${encodeURIComponent(oposicion)}`, { headers: authHeaders });
    const datos = await res.json();
    listaTemasGlobal = datos.temas || [];
  } catch (e) {
    console.error("No se pudieron cargar los temas para el desglose de resultados:", e);
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
  const { protegerPagina } = await import("/assets/plan.js");
  if (!(await protegerPagina("basico"))) return;
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
      marcadasDuda = Array.isArray(guardado.marcadas_duda) && guardado.marcadas_duda.length === preguntas.length
        ? guardado.marcadas_duda
        : Array(preguntas.length).fill(false);
      indicePreguntaActual = guardado.indice_actual || 0;
      // No se guarda un historial de "visitadas" -- se asume que se llegó
      // hasta indice_actual avanzando en orden.
      visitadas = Array(preguntas.length).fill(false);
      for (let k = 0; k <= indicePreguntaActual && k < visitadas.length; k++) visitadas[k] = true;
      const { obtenerOposicionActual: obtenerOposicionResume } = await import("/assets/oposicion.js");
      oposicionActual = guardado.oposicion || obtenerOposicionResume();
      cargarListaTemas(oposicionActual);
      const favoritasApiResume = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApiResume.botonFavoritaHTML;
      activarBotonFavorita = favoritasApiResume.activarBotonFavorita;
      textosFavoritas = await favoritasApiResume.cargarTextosFavoritas(oposicionActual);
      modoCronometradoElegido = !!guardado.modo_cronometrado;
      if (modoCronometradoElegido) {
        tiempoTotalAsignado = guardado.tiempo_total_asignado_segundos || guardado.tiempo_restante_segundos || 0;
        iniciarTemporizador(guardado.tiempo_restante_segundos ?? tiempoTotalAsignado);
      } else {
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
      marcadasDuda = Array(preguntas.length).fill(false);
      visitadas = Array(preguntas.length).fill(false);
      intentoOriginal = {
        aciertos: datosRepetir.test.aciertos ?? null,
        fallos: datosRepetir.test.fallos ?? null,
        blancos: datosRepetir.test.blancos ?? null,
        fecha: datosRepetir.test.fecha ?? null
      };
      const { obtenerOposicionActual } = await import("/assets/oposicion.js");
      const oposicion = obtenerOposicionActual();
      oposicionActual = oposicion;
      cargarListaTemas(oposicion);
      const favoritasApiRepetir = await import("/assets/favoritas.js");
      botonFavoritaHTML = favoritasApiRepetir.botonFavoritaHTML;
      activarBotonFavorita = favoritasApiRepetir.activarBotonFavorita;
      textosFavoritas = await favoritasApiRepetir.cargarTextosFavoritas(oposicion);
      const eleccionCronometro = await preguntarModoCronometrado();
      modoCronometradoElegido = eleccionCronometro.cronometrado;
      minutosElegidos = eleccionCronometro.minutos;
      generarTestId();
      guardarContenidoInicial({
        oposicion, tipo: "repetido", temas: [],
        contenido: preguntas,
        respuestas_usuario: respuestasUsuario,
        marcadas_revision: marcadasRevision,
        marcadas_duda: marcadasDuda,
        indice_actual: 0,
        modo_cronometrado: modoCronometradoElegido,
        tiempo_restante_segundos: modoCronometradoElegido ? minutosElegidos * 60 : null,
        tiempo_total_asignado_segundos: modoCronometradoElegido ? minutosElegidos * 60 : null,
        pagina_origen: "/repetir-test/"
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
      mostrarPregunta(0);
      import("/assets/onboarding-tour.js").then(({ mostrarTourTest }) => mostrarTourTest());
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
    marcadasDuda = Array(preguntas.length).fill(false);
    visitadas = Array(preguntas.length).fill(false);
    oposicionActual = oposicion;
    cargarListaTemas(oposicion);
    const favoritasApiUltimo = await import("/assets/favoritas.js");
    botonFavoritaHTML = favoritasApiUltimo.botonFavoritaHTML;
    activarBotonFavorita = favoritasApiUltimo.activarBotonFavorita;
    textosFavoritas = await favoritasApiUltimo.cargarTextosFavoritas(oposicion);
    const eleccionCronometro = await preguntarModoCronometrado();
    modoCronometradoElegido = eleccionCronometro.cronometrado;
    minutosElegidos = eleccionCronometro.minutos;
    generarTestId();
    guardarContenidoInicial({
      oposicion, tipo: "repetido", temas: [],
      contenido: preguntas,
      respuestas_usuario: respuestasUsuario,
      marcadas_revision: marcadasRevision,
      marcadas_duda: marcadasDuda,
      indice_actual: 0,
      modo_cronometrado: modoCronometradoElegido,
      tiempo_restante_segundos: modoCronometradoElegido ? minutosElegidos * 60 : null,
      tiempo_total_asignado_segundos: modoCronometradoElegido ? minutosElegidos * 60 : null,
      pagina_origen: "/repetir-test/"
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
    mostrarPregunta(0);
    import("/assets/onboarding-tour.js").then(({ mostrarTourTest }) => mostrarTourTest());
  } catch (err) {
    console.error("Error:", err);
    document.getElementById("contenedor-test").innerHTML = "<p>Error al cargar el test.</p>";
  }
});
