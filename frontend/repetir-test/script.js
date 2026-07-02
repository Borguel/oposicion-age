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

function iniciarTemporizador() {
  tiempoInicio = Date.now();
  intervaloTemporizador = setInterval(() => {
    const transcurrido = Math.floor((Date.now() - tiempoInicio) / 1000);
    const m = String(Math.floor(transcurrido / 60)).padStart(2, '0');
    const s = String(transcurrido % 60).padStart(2, '0');
    document.getElementById("temporizador").textContent = `⏱ Tiempo: ${m}:${s}`;
  }, 1000);
}

function mostrarPregunta(i) {
  const p = preguntas[i];
  let html = `<form id="form-pregunta"><fieldset>
    <legend><strong>Pregunta ${i + 1} de ${preguntas.length}:</strong> <strong>${p.pregunta}</strong></legend><br>`;

  for (const letra in p.opciones) {
    const opcion = p.opciones[letra];
    const checked = respuestasUsuario[i] === letra ? "checked" : "";
    html += `
      <div style="margin-bottom: 8px;">
        <label style="cursor: pointer;">
          <input type="radio" name="respuesta" value="${letra}" ${checked}>
          ${letra}) ${opcion}
        </label>
      </div>`;
  }

  html += `
    <div class="botones-navegacion-test">
      ${i > 0 ? '<button type="button" id="btn-anterior">⬅️ Anterior</button>' : ''}
      <button type="button" id="btn-desmarcar">❌ Desmarcar</button>
      <button type="submit">Siguiente</button>
    </div>
    <button type="button" id="btn-finalizar">Finalizar Test</button>
  </fieldset></form>`;

  document.getElementById("contenedor-test").innerHTML = html;

  // Botón desmarcar
  document.getElementById("btn-desmarcar").addEventListener("click", () => {
    document.querySelectorAll('input[name="respuesta"]:checked').forEach(el => el.checked = false);
    respuestasUsuario[i] = null;
  });

  // Botón anterior
  if (i > 0) {
    document.getElementById("btn-anterior").addEventListener("click", () => mostrarPregunta(i - 1));
  }

  // Botón finalizar
  document.getElementById("btn-finalizar").addEventListener("click", () => {
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
      if (result.isConfirmed) {
        mostrarResultados();
      }
    });
  });

  // Siguiente
  document.getElementById("form-pregunta").addEventListener("submit", function(e) {
    e.preventDefault();
    const seleccion = document.querySelector('input[name="respuesta"]:checked');
    respuestasUsuario[i] = seleccion ? seleccion.value : null;

    if (i + 1 < preguntas.length) {
      mostrarPregunta(i + 1);
    } else {
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
        if (result.isConfirmed) {
          mostrarResultados();
        }
      });
    }
  });
}

async function mostrarResultados() {
  clearInterval(intervaloTemporizador);
  document.getElementById("contenedor-test").innerHTML = "";
  const cont = document.getElementById("contenedor-resultados");
  cont.style.display = "block";

  let aciertos = 0;
  let html = "<ol style='padding-left:15px;'>";
  preguntas.forEach((p, i) => {
    const correcta = p.respuesta_correcta;
    const seleccion = respuestasUsuario[i];
    const explicacion = p.explicacion || "Sin explicación.";
    let clase = "resultado-pregunta";
    if (seleccion === correcta) clase = "resultado-pregunta";
    else if (seleccion === null) clase = "resultado-blanco";
    else clase = "resultado-fallo";

    html += `<li class="${clase}" style="margin-bottom:18px;list-style: decimal inside;">
      <div style="font-weight:bold;margin-bottom:7px;">${i + 1}. ${p.pregunta}</div>`;
    for (const letra in p.opciones) {
      let tipoResp = "";
      if (letra === correcta) tipoResp = `<span class="respuesta-correcta" style="background:#c0f2d0;padding:3px 7px;border-radius:5px;border:1px solid #66cc7b;color:#21892f;font-weight:500;">✅ ${letra}) ${p.opciones[letra]}</span>`;
      else if (letra === seleccion && seleccion !== correcta)
        tipoResp = `<span class="respuesta-usuario" style="background:#ffd5d5;padding:3px 7px;border-radius:5px;border:1px solid #e96565;color:#a60d15;font-weight:500;">❌ ${letra}) ${p.opciones[letra]}</span>`;
      else
        tipoResp = `<span>${letra}) ${p.opciones[letra]}</span>`;
      html += `<div style="margin-bottom:3px;display:inline-block;">${tipoResp}</div><br>`;
    }
    html += `<details><summary style="margin-top:8px;">📘 Explicación</summary><p>${explicacion}</p></details></li>`;
    if (seleccion === correcta) aciertos++;
  });

  const fallos = respuestasUsuario.filter((r, idx) => r !== null && r !== preguntas[idx].respuesta_correcta).length;
  const sinResponder = respuestasUsuario.filter(r => r === null).length;
  const segundosTotales = Math.floor((Date.now() - tiempoInicio) / 1000);

  html += "</ol>";

  const porcentaje = ((aciertos / preguntas.length) * 100).toFixed(1);
  const nota = (aciertos * 1 - fallos * 0.33).toFixed(2);
  const notaEquivalente = ((nota / preguntas.length) * 70).toFixed(2);

  html = `
    <div style='background:#f4f4f4;padding:20px;border-radius:12px;margin-bottom:20px;max-width:850px;margin:auto;'>
      <h3>📊 Resumen del Test</h3>
      <p><strong>Total:</strong> ${preguntas.length}</p>
      <p style='color:green;'><strong>✅ Aciertos:</strong> ${aciertos}</p>
      <p style='color:red;'><strong>❌ Fallos:</strong> ${fallos}</p>
      <p style='color:gray;'><strong>⏸ En blanco:</strong> ${sinResponder}</p>
      <p><strong>🎯 Porcentaje:</strong> ${porcentaje}%</p>
      <p><strong>📘 Nota simulada:</strong> ${nota} / ${preguntas.length}<br><strong>📏 Nota equivalente AGE:</strong> ${notaEquivalente} / 70</p>
      <div style='background:#ddd;border-radius:10px;overflow:hidden;margin-top:10px;'>
        <div style='width:${porcentaje}%;background:linear-gradient(to right,#4caf50,#81c784);padding:6px 10px;color:white;'>${porcentaje}%</div>
      </div>
    </div>
    <div style="max-width:850px;margin:auto;">${html}</div>
  `;

  cont.innerHTML = html;

  // guardar test en Firestore
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    await fetch("https://oposicion-age.onrender.com/guardar-test", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify({
        contenido: preguntas,
        respuestas: respuestasUsuario,
        metadatos: {
          tiempo: segundosTotales,
          tipo: "repetido",
          temas: []
        }
      })
    });
    console.log("✅ Test guardado como repetido");
  } catch (err) {
    console.error("❌ Error al guardar test:", err);
  }
}


// Carga el último test al cargar la página
window.addEventListener("load", async () => {
  try {
    const authHeaders = await obtenerAuthHeaders();
    if (!authHeaders) return;
    const res = await fetch("https://oposicion-age.onrender.com/ultimo-test", { headers: authHeaders });
    const datos = await res.json();

    if (!datos.test || datos.test.length === 0) {
      document.getElementById("contenedor-test").innerHTML = "<p>No se ha encontrado ningún test anterior.</p>";
      return;
    }

    preguntas = datos.test;
    respuestasUsuario = Array(preguntas.length).fill(null);
    indicePreguntaActual = 0;
    iniciarTemporizador();
    mostrarPregunta(indicePreguntaActual);
  } catch (err) {
    console.error("Error:", err);
    document.getElementById("contenedor-test").innerHTML = "<p>Error al cargar el test.</p>";
  }
});
