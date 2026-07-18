// Tutorial de bienvenida al primer test: resalta, uno a uno, la estrella
// (favorita), el marcador (revisar en este test), la interrogación (duda,
// no cuenta en la nota final) y el navegador de preguntas -- para quien no
// se haya leído /como-funciona/test-personalizado/. Compartido por las 6
// páginas de test para que se vea igual en todas.
//
// Se muestra una sola vez por navegador (localStorage), y solo hay que
// llamarlo al EMPEZAR un test nuevo, nunca al reanudar uno ya en curso, para
// no interrumpir a quien ya conoce estos botones.
const CLAVE_TOUR_VISTO = "age_tour_test_visto";

const PASOS = [
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

export function mostrarTourTest() {
  if (localStorage.getItem(CLAVE_TOUR_VISTO) === "1") return;
  if (!PASOS.some((paso) => document.querySelector(paso.selector))) return;
  setTimeout(() => iniciarPaso(0), 400);
}

function marcarVisto() {
  localStorage.setItem(CLAVE_TOUR_VISTO, "1");
}

function terminarTour(overlay) {
  document.querySelector(".tour-bocadillo")?.remove();
  document.querySelectorAll(".tour-resaltado").forEach((el) => el.classList.remove("tour-resaltado"));
  overlay?.remove();
  marcarVisto();
}

function iniciarPaso(indice, overlayExistente) {
  while (indice < PASOS.length && !document.querySelector(PASOS[indice].selector)) indice++;
  if (indice >= PASOS.length) {
    terminarTour(overlayExistente);
    return;
  }

  let overlay = overlayExistente;
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.className = "tour-overlay";
    overlay.addEventListener("click", () => terminarTour(overlay));
    document.body.appendChild(overlay);
  }

  const paso = PASOS[indice];
  const elemento = document.querySelector(paso.selector);
  document.querySelectorAll(".tour-resaltado").forEach((el) => el.classList.remove("tour-resaltado"));
  elemento.classList.add("tour-resaltado");
  elemento.scrollIntoView({ block: "center", behavior: "smooth" });

  setTimeout(() => mostrarBocadillo(elemento, paso, indice, overlay), 300);
}

function mostrarBocadillo(elemento, paso, indice, overlay) {
  document.querySelector(".tour-bocadillo")?.remove();

  const quedaAlguno = PASOS.slice(indice + 1).some((p) => document.querySelector(p.selector));
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

  const rect = elemento.getBoundingClientRect();
  const alto = bocadillo.offsetHeight;
  const arriba = window.innerHeight - rect.bottom < alto + 20 && rect.top > alto + 20;
  bocadillo.style.top = arriba ? `${rect.top - alto - 12}px` : `${rect.bottom + 12}px`;
  const izquierda = Math.min(Math.max(rect.left, 12), window.innerWidth - bocadillo.offsetWidth - 12);
  bocadillo.style.left = `${izquierda}px`;

  bocadillo.querySelector(".tour-bocadillo-saltar").addEventListener("click", () => terminarTour(overlay));
  bocadillo.querySelector(".tour-bocadillo-siguiente").addEventListener("click", () => {
    bocadillo.remove();
    iniciarPaso(indice + 1, overlay);
  });
}
