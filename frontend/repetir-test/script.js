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
let tiempoInicio;
let intervaloTemporizador;
let ultimasEstadisticas = null;

function iniciarTemporizador() {
  tiempoInicio = Date.now();
  document.getElementById("temporizador").style.display = "block";
  document.getElementById("temporizador").textContent = `⏱ Tiempo: 00:00`;
  intervaloTemporizador = setInterval(() => {
    const transcurrido = Math.floor((Date.now() - tiempoInicio) / 1000);
    const m = String(Math.floor(transcurrido / 60)).padStart(2, '0');
    const s = String(transcurrido % 60).padStart(2, '0');
    document.getElementById("temporizador").textContent = `⏱ Tiempo: ${m}:${s}`;
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
  const p = preguntas[i];
  let textoPregunta = p.pregunta.replace(/^\s*\d+\s*[\.\)]\s*/, "");
  let html = `<form id="form-pregunta">
    <div class="pregunta-en-negrita">${i + 1}. ${textoPregunta}</div>`;

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
    </div>
    <button type="submit" class="age-btn age-btn-primary age-btn-block" style="margin-top:12px;">
      ${i + 1 < preguntas.length ? 'Siguiente →' : 'Finalizar test'}
    </button>
    <button type="button" id="btn-finalizar" class="btn btn-danger btn-block" style="margin-top:10px;">Finalizar Test</button>
  </form>`;

  document.getElementById("contenedor-test").innerHTML = html;

  document.getElementById("btn-desmarcar").addEventListener("click", () => {
    document.querySelectorAll('input[name="respuesta"]:checked').forEach(el => el.checked = false);
    respuestasUsuario[i] = null;
  });

  if (i > 0) {
    document.getElementById("btn-anterior").addEventListener("click", () => mostrarPregunta(i - 1));
  }

  document.getElementById("btn-finalizar").addEventListener("click", confirmarFinalizar);

  document.getElementById("form-pregunta").addEventListener("submit", function (e) {
    e.preventDefault();
    const seleccion = document.querySelector('input[name="respuesta"]:checked');
    respuestasUsuario[i] = seleccion ? seleccion.value : null;

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

  const segundosTotales = Math.floor((Date.now() - tiempoInicio) / 1000);
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
        oposicion: obtenerOposicionActual()
      })
    });
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

// Carga el último test al cargar la página
window.addEventListener("load", async () => {
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    const { obtenerOposicionActual } = await import("/assets/oposicion.js");
    const res = await fetch(`https://oposicion-age.onrender.com/ultimo-test?oposicion=${encodeURIComponent(obtenerOposicionActual())}`, { headers: authHeaders });
    const datos = await res.json();

    if (!datos.test || datos.test.length === 0) {
      document.getElementById("contenedor-test").innerHTML = "<p>No se ha encontrado ningún test anterior.</p>";
      return;
    }

    preguntas = datos.test;
    respuestasUsuario = Array(preguntas.length).fill(null);
    iniciarTemporizador();
    mostrarPregunta(0);
  } catch (err) {
    console.error("Error:", err);
    document.getElementById("contenedor-test").innerHTML = "<p>Error al cargar el test.</p>";
  }
});
