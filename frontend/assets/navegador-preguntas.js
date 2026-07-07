// Mapa visual del examen: un cuadradito por pregunta que muestra de un
// vistazo su estado (respondida, marcada para revisión, visitada pero sin
// responder, o todavía no visitada) y permite saltar directamente a
// cualquiera, sin tener que ir pregunta a pregunta con Anterior/Siguiente.
// Compartido por las 6 páginas de test para que el comportamiento y el
// aspecto sean idénticos en todas.
export function renderizarNavegadorPreguntas(contenedor, { total, respuestasUsuario, visitadas, marcadasRevision, indiceActual, onSaltar }) {
  contenedor.innerHTML = Array.from({ length: total }, (_, i) => {
    let estado = "np-no-visitada";
    if (marcadasRevision[i]) estado = "np-marcada";
    else if (respuestasUsuario[i] !== null && respuestasUsuario[i] !== undefined) estado = "np-respondida";
    else if (visitadas[i]) estado = "np-visitada";
    const actual = i === indiceActual ? " np-actual" : "";
    return `<button type="button" class="nav-preg ${estado}${actual}" data-indice="${i}" aria-label="Ir a la pregunta ${i + 1}" title="Pregunta ${i + 1}">${i + 1}</button>`;
  }).join("");
  contenedor.querySelectorAll(".nav-preg").forEach((boton) => {
    boton.addEventListener("click", () => onSaltar(parseInt(boton.dataset.indice, 10)));
  });
}
