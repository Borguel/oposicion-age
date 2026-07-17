// Mapa visual del examen: un cuadradito por pregunta que muestra de un
// vistazo su estado (respondida, marcada para revisión, visitada pero sin
// responder, o todavía no visitada) y permite saltar directamente a
// cualquiera, sin tener que ir pregunta a pregunta con Anterior/Siguiente.
// Compartido por las 6 páginas de test para que el comportamiento y el
// aspecto sean idénticos en todas.
//
// Con muchas preguntas (tests de 50-100) la rejilla completa ocupa
// muchísimo espacio vertical, sobre todo en móvil -- a partir de
// UMBRAL_PLEGADO se pliega detrás de un botón-cabecera con un resumen
// compacto (mismo patrón visual/interacción que el "N temas ▾" ya usado en
// las tarjetas de Mis Tests, ver mis-tests/script.js:pillsTemas). El estado
// abierto/cerrado se recuerda por contenedor (persiste entre preguntas,
// ya que esta función se vuelve a llamar en cada navegación).
import { icono } from "/assets/icons.js";

const UMBRAL_PLEGADO = 20;
const estadoExpandido = new WeakMap();

export function renderizarNavegadorPreguntas(contenedor, { total, respuestasUsuario, visitadas, marcadasRevision, indiceActual, onSaltar }) {
  const botones = Array.from({ length: total }, (_, i) => {
    let estado = "np-no-visitada";
    if (marcadasRevision[i]) estado = "np-marcada";
    else if (respuestasUsuario[i] !== null && respuestasUsuario[i] !== undefined) estado = "np-respondida";
    else if (visitadas[i]) estado = "np-visitada";
    const actual = i === indiceActual ? " np-actual" : "";
    return `<button type="button" class="nav-preg ${estado}${actual}" data-indice="${i}" aria-label="Ir a la pregunta ${i + 1}" title="Pregunta ${i + 1}">${i + 1}</button>`;
  }).join("");

  const plegable = total > UMBRAL_PLEGADO;
  contenedor.classList.toggle("navegador-preguntas-plegable", plegable);
  // Cada página fija contenedor.style.display = "flex" en línea al empezar
  // el test (antes de saber cuántas preguntas hay) -- ese estilo en línea
  // pisaría la regla CSS de .navegador-preguntas-plegable, así que aquí se
  // corrige directamente en cada render en vez de tocar las 6 páginas.
  if (contenedor.style.display !== "none") {
    contenedor.style.display = plegable ? "block" : "flex";
  }

  if (!plegable) {
    contenedor.innerHTML = botones;
  } else {
    const respondidas = respuestasUsuario.filter(r => r !== null && r !== undefined).length;
    const abierto = estadoExpandido.get(contenedor) ?? false;
    contenedor.innerHTML = `
      <button type="button" class="navegador-preguntas-toggle${abierto ? " open" : ""}">
        <span style="display:inline-flex;align-items:center;gap:6px;">${icono("brujula", 16)} ${respondidas}/${total} respondidas — pregunta ${indiceActual + 1} actual</span>
        <span class="navegador-preguntas-caret">▾</span>
      </button>
      <div class="navegador-preguntas-grid${abierto ? "" : " hidden"}">${botones}</div>
    `;
    contenedor.querySelector(".navegador-preguntas-toggle").addEventListener("click", (evento) => {
      const nuevoEstado = !estadoExpandido.get(contenedor);
      estadoExpandido.set(contenedor, nuevoEstado);
      contenedor.querySelector(".navegador-preguntas-grid").classList.toggle("hidden", !nuevoEstado);
      evento.currentTarget.classList.toggle("open", nuevoEstado);
    });
  }

  contenedor.querySelectorAll(".nav-preg").forEach((boton) => {
    boton.addEventListener("click", () => onSaltar(parseInt(boton.dataset.indice, 10)));
  });
}
