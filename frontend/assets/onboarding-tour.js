// Motor genérico de tours de "spotlight" (resalta un elemento real de la
// página con un halo y muestra un bocadillo explicativo al lado, paso a
// paso). Dos usos concretos hoy, cada uno con su propia clave de
// localStorage para no repetirse ni interferir entre sí:
//
// 1. mostrarTourTest(): tutorial de bienvenida al primer test -- estrella
//    (favorita), marcador (revisar en este test), interrogación (duda) y
//    el navegador de preguntas. Compartido por las 6 páginas de test.
// 2. mostrarTourZonaOpositor(): tour de primeros pasos en Zona Opositor la
//    primera vez que se entra -- generar test, herramientas IA, tu tutor
//    y estadísticas.
import { auth } from "/assets/auth.js";

// La clave de localStorage se namespacea por uid (no solo por navegador):
// sin esto, dos cuentas distintas probadas en el mismo navegador (algo
// habitual al probar la web con varios usuarios de prueba) comparten el
// mismo "ya visto" y la segunda cuenta nunca ve el tour aunque sea su
// primera vez de verdad.
function claveParaUsuario(clave) {
  return auth.currentUser ? `${clave}_${auth.currentUser.uid}` : clave;
}

function iniciarTourGenerico(pasos, claveBase) {
  const clave = claveParaUsuario(claveBase);
  if (localStorage.getItem(clave) === "1") return;
  if (!pasos.some((paso) => document.querySelector(paso.selector))) return;
  setTimeout(() => iniciarPaso(pasos, clave, 0), 400);
}

function marcarVisto(clave) {
  localStorage.setItem(clave, "1");
}

// Mientras el tour está abierto, la página sigue cargando datos en segundo
// plano (racha, test en progreso, avisos...) que pueden insertar tarjetas
// nuevas por encima del elemento señalado. Este observador detecta esos
// cambios de tamaño y vuelve a centrar/recolocar el paso actual, para que
// el bocadillo no se quede apuntando a un hueco vacío.
let observadorTour = null;

function detenerObservadorTour() {
  observadorTour?.disconnect();
  observadorTour = null;
}

// El bocadillo es position:fixed (coordenadas de viewport, no de página) a
// propósito -- así no hay que recalcularlo en cada frame de scroll, un solo
// reposicionamiento basta. Pero si el usuario hace scroll manual (típico en
// móvil, arrastrando la página antes de leer el paso), el elemento resaltado
// cambia de posición en el viewport y el bocadillo, al no escuchar el
// scroll, se queda "flotando" donde se calculó la última vez -- de ahí el
// efecto de quedarse fijo arriba a la izquierda sin seguir a la página.
let elementoActivoTour = null;

function onScrollTour() {
  const bocadillo = document.querySelector(".tour-bocadillo");
  if (bocadillo && elementoActivoTour && document.body.contains(elementoActivoTour)) {
    posicionarBocadillo(bocadillo, elementoActivoTour);
  }
}

function detenerListenerScrollTour() {
  window.removeEventListener("scroll", onScrollTour, true);
  elementoActivoTour = null;
}

function terminarTour(clave, overlay) {
  detenerObservadorTour();
  detenerListenerScrollTour();
  document.querySelector(".tour-bocadillo")?.remove();
  document.querySelectorAll(".tour-resaltado").forEach((el) => el.classList.remove("tour-resaltado"));
  overlay?.remove();
  marcarVisto(clave);
}

function iniciarPaso(pasos, clave, indice, overlayExistente) {
  while (indice < pasos.length && !document.querySelector(pasos[indice].selector)) indice++;
  if (indice >= pasos.length) {
    terminarTour(clave, overlayExistente);
    return;
  }

  let overlay = overlayExistente;
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "tour-overlay";
    overlay.addEventListener("click", () => terminarTour(clave, overlay));
    document.body.appendChild(overlay);
  }

  const paso = pasos[indice];
  const elemento = document.querySelector(paso.selector);
  document.querySelectorAll(".tour-resaltado").forEach((el) => el.classList.remove("tour-resaltado"));
  elemento.classList.add("tour-resaltado");
  elemento.scrollIntoView({ block: "center", behavior: "smooth" });

  detenerObservadorTour();
  observadorTour = new ResizeObserver(() => {
    if (!document.body.contains(elemento)) return;
    elemento.scrollIntoView({ block: "center", behavior: "smooth" });
    const bocadillo = document.querySelector(".tour-bocadillo");
    if (bocadillo) setTimeout(() => posicionarBocadillo(bocadillo, elemento), 300);
  });
  observadorTour.observe(document.body);

  detenerListenerScrollTour();
  elementoActivoTour = elemento;
  window.addEventListener("scroll", onScrollTour, true);

  setTimeout(() => mostrarBocadillo(pasos, clave, elemento, paso, indice, overlay), 300);
}

function posicionarBocadillo(bocadillo, elemento) {
  const rect = elemento.getBoundingClientRect();
  const alto = bocadillo.offsetHeight;
  const arriba = window.innerHeight - rect.bottom < alto + 20 && rect.top > alto + 20;
  bocadillo.style.top = arriba ? `${rect.top - alto - 12}px` : `${rect.bottom + 12}px`;
  const izquierda = Math.min(Math.max(rect.left, 12), window.innerWidth - bocadillo.offsetWidth - 12);
  bocadillo.style.left = `${izquierda}px`;
}

function mostrarBocadillo(pasos, clave, elemento, paso, indice, overlay) {
  document.querySelector(".tour-bocadillo")?.remove();

  const quedaAlguno = pasos.slice(indice + 1).some((p) => document.querySelector(p.selector));
  const bocadillo = document.createElement("div");
  bocadillo.className = "tour-bocadillo";
  bocadillo.innerHTML = `
    <div class="tour-bocadillo-titulo">${paso.titulo}</div>
    <p class="tour-bocadillo-texto">${paso.texto}</p>
    <div class="tour-bocadillo-acciones">
      <button type="button" class="tour-bocadillo-saltar">Saltar</button>
      <button type="button" class="tour-bocadillo-siguiente">${quedaAlguno ? "Siguiente" : "Entendido"}</button>
    </div>
  `;
  document.body.appendChild(bocadillo);
  posicionarBocadillo(bocadillo, elemento);

  bocadillo.querySelector(".tour-bocadillo-saltar").addEventListener("click", () => terminarTour(clave, overlay));
  bocadillo.querySelector(".tour-bocadillo-siguiente").addEventListener("click", () => {
    bocadillo.remove();
    iniciarPaso(pasos, clave, indice + 1, overlay);
  });
}

// ---------- Tour 1: bienvenida al primer test ----------
const CLAVE_TOUR_TEST_VISTO = "age_tour_test_visto";

const PASOS_TEST = [
  {
    selector: ".btn-favorita",
    titulo: "Favorita",
    texto: "Guarda la pregunta en \"Preguntas favoritas\" para repasarla más adelante, aunque el test ya haya terminado."
  },
  {
    selector: "#btn-marcar-revision",
    titulo: "Marcador",
    texto: "Resalta la pregunta solo en este test, para volver a ella antes de terminar."
  },
  {
    selector: "#btn-marcar-duda",
    titulo: "Duda",
    texto: "Marca la pregunta como duda: al terminar el test verás la nota contándola y sin contarla, para valorar si te compensa arriesgar."
  },
  {
    selector: "#navegador-preguntas",
    titulo: "Saltar entre preguntas",
    texto: "Aquí ves el estado de cada pregunta y puedes ir directamente a cualquiera, sin pasar por las anteriores."
  }
];

// Se muestra una sola vez por navegador (localStorage), y solo hay que
// llamarlo al EMPEZAR un test nuevo, nunca al reanudar uno ya en curso, para
// no interrumpir a quien ya conoce estos botones.
export function mostrarTourTest() {
  iniciarTourGenerico(PASOS_TEST, CLAVE_TOUR_TEST_VISTO);
}

// ---------- Tour 2: primeros pasos en Zona Opositor ----------
const CLAVE_TOUR_ZONA_VISTO = "age_tour_zona_visto";

const PASOS_ZONA = [
  {
    selector: 'a[href="/test-generator/"]',
    titulo: "Genera tu primer test",
    texto: "Aquí creas un test personalizado con IA sobre los temas que elijas, o uno oficial con preguntas de exámenes reales."
  },
  {
    selector: 'a[href="/subida-pdf-pagina-principal/"]',
    titulo: "Tus propios apuntes",
    texto: "Si tienes tus PDF, aquí genera resúmenes, esquemas, tarjetas de memoria y tests a partir de ellos."
  },
  {
    selector: 'a[href="/tu-tutor/"]',
    titulo: "Tu Tutor",
    texto: "Resuelve al momento cualquier duda sobre el temario o el proceso selectivo, charlando como con un profesor particular."
  },
  {
    selector: 'a[href="/estadisticas/"]',
    titulo: "Tu progreso",
    texto: "Según vayas haciendo tests, aquí verás tu nota media y qué temas te cuestan más, para saber qué repasar."
  }
];

// Se muestra una sola vez por navegador, la primera vez que se entra en
// Zona Opositor -- complementa (no sustituye) al checklist de onboarding
// ya existente en la propia página.
export function mostrarTourZonaOpositor() {
  iniciarTourGenerico(PASOS_ZONA, CLAVE_TOUR_ZONA_VISTO);
}
