// Demo pública sin registro: reutiliza exactamente el mismo patrón de
// pregunta -> Finalizar (con aviso de preguntas sin contestar) -> resultados
// que usan las páginas de test reales (ver test-oficial/script.js), para que
// quien la prueba vea tal cual lo que se va a encontrar con una cuenta. La
// única diferencia es que no hay temporizador, autoguardado ni marcar
// favorita/duda (todo eso requiere estar logueado), y al final se añade un
// aviso para registrarse.
import { BACKEND_URL } from "/assets/firebase-config.js";
import { icono } from "/assets/icons.js";
import { escaparHtml, renderizarResultadosTest } from "/assets/resultados-test.js";
import { renderizarNavegadorPreguntas } from "/assets/navegador-preguntas.js";

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

const contCargando = document.getElementById("demo-cargando");
const contError = document.getElementById("demo-error");
const contNavegador = document.getElementById("navegador-preguntas");
const contTest = document.getElementById("contenedor-test");
const contResultados = document.getElementById("contenedor-resultados");
const btnDescargarPdf = document.getElementById("btn-descargar-pdf");
const selectorOposicion = document.getElementById("demo-oposicion");

let preguntas = [];
let indicePreguntaActual = 0;
let respuestasUsuario = [];
let visitadas = [];
let ultimasEstadisticas = null;

function mostrarSolo(...elementos) {
  [contCargando, contError, contNavegador, contTest, contResultados, btnDescargarPdf].forEach((el) => {
    el.style.display = "none";
  });
  elementos.forEach((el) => { el.style.display = el === contNavegador ? "flex" : "block"; });
}

async function cargarPreguntas() {
  mostrarSolo(contCargando);
  try {
    const res = await fetch(`${BACKEND_URL}/demo/test-oficial?oposicion=${selectorOposicion.value}`);
    const datos = await res.json();
    if (!res.ok || !(datos.test || []).length) {
      throw new Error("Todavía no hay preguntas oficiales cargadas para esta oposición.");
    }
    preguntas = datos.test;
    respuestasUsuario = new Array(preguntas.length).fill(null);
    visitadas = new Array(preguntas.length).fill(false);
    mostrarPregunta(0);
  } catch (error) {
    contError.textContent = error.message || "No se pudieron cargar las preguntas. Inténtalo de nuevo en unos segundos.";
    mostrarSolo(contError);
  }
}

function actualizarNavegador() {
  renderizarNavegadorPreguntas(contNavegador, {
    total: preguntas.length,
    respuestasUsuario,
    visitadas,
    marcadasRevision: [],
    indiceActual: indicePreguntaActual,
    onSaltar: (idx) => mostrarPregunta(idx),
  });
}

function mostrarPregunta(i) {
  indicePreguntaActual = i;
  visitadas[i] = true;
  mostrarSolo(contNavegador, contTest);
  actualizarNavegador();

  const p = preguntas[i];
  const textoPregunta = escaparHtml(p.pregunta.replace(/^\s*\d+\s*[.)]\s*/, ""));
  let html = `<form id="form-pregunta">
    <div class="pregunta-en-negrita"><span>${i + 1}. ${textoPregunta}</span></div>`;
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
      ${i > 0 ? '<button type="button" id="btn-anterior" class="age-btn age-btn-outline">← Anterior</button>' : ""}
      <button type="submit" class="age-btn age-btn-primary">
        ${i + 1 < preguntas.length ? "Siguiente →" : "Finalizar test"}
      </button>
    </div>
  </form>`;
  contTest.innerHTML = html;
  const bloquePregunta = document.querySelector("#form-pregunta .pregunta-en-negrita");
  if (bloquePregunta) {
    bloquePregunta.dataset.respuestaCorrecta = p.respuesta_correcta || "";
    bloquePregunta.dataset.explicacion = p.explicacion || "";
  }

  if (i > 0) {
    document.getElementById("btn-anterior").addEventListener("click", () => mostrarPregunta(i - 1));
  }
  contTest.querySelectorAll('input[name="respuesta"]').forEach((radio) => {
    radio.addEventListener("click", function () {
      // Un segundo clic sobre la misma opción la desmarca y deja la
      // pregunta en blanco, igual que en el test real.
      if (respuestasUsuario[i] === this.value) {
        this.checked = false;
        respuestasUsuario[i] = null;
      } else {
        respuestasUsuario[i] = this.value;
      }
      actualizarNavegador();
    });
  });
  document.getElementById("form-pregunta").addEventListener("submit", (e) => {
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

function confirmarFinalizar() {
  const sinContestar = respuestasUsuario.filter((r) => r === null).length;
  const mensaje = sinContestar > 0
    ? `Has dejado ${sinContestar} pregunta${sinContestar > 1 ? "s" : ""} sin contestar.`
    : "¿Quieres finalizar el test y ver los resultados?";
  Swal.fire({
    icon: "question",
    title: "¿Deseas finalizar el test?",
    text: mensaje,
    showCancelButton: true,
    confirmButtonText: "Sí, corregir",
    cancelButtonText: "Seguir revisando",
  }).then((resultado) => {
    if (resultado.isConfirmed) mostrarResultados();
  });
}

function mostrarResultados() {
  mostrarSolo(contResultados);

  ultimasEstadisticas = renderizarResultadosTest({
    contenedor: contResultados,
    preguntas,
    respuestasUsuario,
  });

  // El análisis con IA, "Pregúntale a Tu Tutor" y "Reportar error" requieren
  // estar logueado (usan el token de la cuenta) -- no tienen sentido aquí y
  // se quitan en vez de dejar que fallen al pulsarlos.
  contResultados.querySelector(".analisis-ia-bloque")?.remove();
  contResultados.querySelectorAll(".detalle-tutor-btn, .detalle-reportar-btn").forEach((b) => b.remove());

  const cta = document.createElement("div");
  cta.className = "demo-registro-cta";
  cta.innerHTML = `
    <h2>${icono("destellos", 20)} ¿Qué tal ha ido?</h2>
    <p>Esto es solo una muestra de 5 preguntas. Con una cuenta gratis tienes tests ilimitados sobre todo el temario, herramientas de IA para tus propios apuntes y estadísticas de tu progreso — y empiezas con 7 días de Premium sin tarjeta.</p>
    <div class="demo-registro-ctas">
      <a href="/login/?next=/zona-opositor/" class="age-btn age-btn-primary">Crear cuenta gratis</a>
      <a href="/planes/" class="age-btn age-btn-outline">Ver planes</a>
    </div>
    <button type="button" class="demo-btn-link" id="btn-demo-repetir">Probar con otras 5 preguntas</button>
  `;
  contResultados.insertBefore(cta, contResultados.firstChild);
  document.getElementById("btn-demo-repetir").addEventListener("click", cargarPreguntas);

  btnDescargarPdf.style.display = "block";
  btnDescargarPdf.onclick = async () => {
    const { descargarResultadosPDF } = await import("/assets/resultados-test.js");
    descargarResultadosPDF({
      preguntas,
      respuestasUsuario,
      stats: ultimasEstadisticas,
      titulo: "Resultados de la demo - Domina tu Opo",
      nombreArchivo: "demo-domina-tu-opo.pdf",
    });
  };
}

selectorOposicion.addEventListener("change", cargarPreguntas);

cargarPreguntas();
