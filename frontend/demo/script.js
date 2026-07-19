import { BACKEND_URL } from "/assets/firebase-config.js";
import { icono } from "/assets/icons.js";

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

function escapeHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

const contCargando = document.getElementById("demo-cargando");
const contError = document.getElementById("demo-error");
const contJuego = document.getElementById("demo-juego");
const contFinal = document.getElementById("demo-final");
const progresoTexto = document.getElementById("demo-progreso-texto");
const progresoRelleno = document.getElementById("demo-progreso-relleno");
const preguntaTexto = document.getElementById("demo-pregunta-texto");
const opcionesCont = document.getElementById("demo-opciones");
const feedbackCont = document.getElementById("demo-feedback");
const btnSiguiente = document.getElementById("demo-btn-siguiente");
const selectorOposicion = document.getElementById("demo-oposicion");

let preguntas = [];
let indiceActual = 0;
let aciertos = 0;

function mostrar(elemento) {
  [contCargando, contError, contJuego, contFinal].forEach((el) => { el.style.display = "none"; });
  elemento.style.display = "block";
}

async function cargarPreguntas() {
  mostrar(contCargando);
  indiceActual = 0;
  aciertos = 0;
  try {
    const res = await fetch(`${BACKEND_URL}/demo/test-oficial?oposicion=${selectorOposicion.value}`);
    const datos = await res.json();
    if (!res.ok || !(datos.test || []).length) {
      throw new Error("Todavía no hay preguntas oficiales cargadas para esta oposición.");
    }
    preguntas = datos.test;
    mostrarPregunta();
  } catch (error) {
    contError.textContent = error.message || "No se pudieron cargar las preguntas. Inténtalo de nuevo en unos segundos.";
    mostrar(contError);
  }
}

function mostrarPregunta() {
  const pregunta = preguntas[indiceActual];
  progresoTexto.textContent = `Pregunta ${indiceActual + 1} de ${preguntas.length}`;
  progresoRelleno.style.width = `${(indiceActual / preguntas.length) * 100}%`;
  preguntaTexto.textContent = pregunta.pregunta;
  feedbackCont.style.display = "none";
  btnSiguiente.style.display = "none";

  opcionesCont.innerHTML = Object.entries(pregunta.opciones).map(([letra, texto]) => `
    <button type="button" class="demo-opcion" data-letra="${escapeHtml(letra)}">
      <span class="demo-opcion-letra">${escapeHtml(letra)}.</span>
      <span>${escapeHtml(texto)}</span>
    </button>`).join("");

  opcionesCont.querySelectorAll(".demo-opcion").forEach((boton) => {
    boton.addEventListener("click", () => responder(boton.dataset.letra));
  });
  mostrar(contJuego);
}

function responder(letraElegida) {
  const pregunta = preguntas[indiceActual];
  const correcta = pregunta.respuesta_correcta;
  const acierto = letraElegida === correcta;
  if (acierto) aciertos += 1;

  opcionesCont.querySelectorAll(".demo-opcion").forEach((boton) => {
    boton.disabled = true;
    if (boton.dataset.letra === correcta) boton.classList.add("correcta");
    else if (boton.dataset.letra === letraElegida) boton.classList.add("incorrecta");
  });

  feedbackCont.className = `demo-feedback ${acierto ? "acierto" : "fallo"}`;
  feedbackCont.innerHTML = `
    <span class="demo-feedback-titulo">${acierto ? "¡Correcto!" : `Incorrecto — la respuesta era la ${escapeHtml(correcta)}`}</span>
    ${escapeHtml(pregunta.explicacion || "")}`;
  feedbackCont.style.display = "block";

  progresoRelleno.style.width = `${((indiceActual + 1) / preguntas.length) * 100}%`;
  btnSiguiente.style.display = "block";
  btnSiguiente.textContent = indiceActual + 1 < preguntas.length ? "Siguiente pregunta" : "Ver mi resultado";
}

btnSiguiente.addEventListener("click", () => {
  indiceActual += 1;
  if (indiceActual < preguntas.length) {
    mostrarPregunta();
  } else {
    mostrarFinal();
  }
});

function mostrarFinal() {
  const titulo = document.getElementById("demo-final-titulo");
  const nota = document.getElementById("demo-final-nota");
  nota.textContent = `${aciertos} de ${preguntas.length} aciertos`;
  titulo.textContent = aciertos === preguntas.length ? "¡Pleno! ¿Vamos a por el resto del temario?" : "¡Has terminado!";
  mostrar(contFinal);
}

document.getElementById("demo-btn-repetir").addEventListener("click", cargarPreguntas);
selectorOposicion.addEventListener("change", cargarPreguntas);

cargarPreguntas();
