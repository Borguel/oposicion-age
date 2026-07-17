// Comportamiento común de abrir/cerrar para los popovers de la nav
// (buscador, oposición, cuenta): clic en el botón alterna, clic fuera o
// Escape cierra, y solo uno permanece abierto a la vez. El listener global
// en document se instala UNA sola vez para toda la vida de la página
// (instalarCierreGlobal es idempotente) en vez de que cada popover añada el
// suyo cada vez que auth.js reconstruye la nav en cada onAuthStateChanged
// -- así se cierra por consulta en vivo del DOM en vez de guardar
// referencias, que quedarían colgando cuando la nav se reconstruye.
let instalado = false;

function cerrarAbiertos(elementoClic) {
  document.querySelectorAll(".age-popover-root.open").forEach((raiz) => {
    if (elementoClic && raiz.contains(elementoClic)) return;
    raiz.classList.remove("open");
    raiz.querySelector("[data-popover-toggle]")?.setAttribute("aria-expanded", "false");
  });
}

function instalarCierreGlobal() {
  if (instalado) return;
  instalado = true;
  document.addEventListener("click", (evento) => cerrarAbiertos(evento.target));
  document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape") cerrarAbiertos(null);
  });
}

// raiz: contenedor position:relative que ya tiene dentro un
// [data-popover-toggle] (el botón) y un [data-popover-panel] (el panel).
// onAbrir: opcional, para focus/carga perezosa al abrir.
export function activarPopover(raiz, { onAbrir } = {}) {
  instalarCierreGlobal();
  raiz.classList.add("age-popover-root");
  const boton = raiz.querySelector("[data-popover-toggle]");
  const panel = raiz.querySelector("[data-popover-panel]");
  if (!boton || !panel) return;
  boton.setAttribute("aria-expanded", "false");
  boton.addEventListener("click", (evento) => {
    evento.stopPropagation();
    const abriendo = !raiz.classList.contains("open");
    cerrarAbiertos(null);
    raiz.classList.toggle("open", abriendo);
    boton.setAttribute("aria-expanded", String(abriendo));
    if (abriendo) onAbrir?.();
  });
  panel.addEventListener("click", (evento) => evento.stopPropagation());
}
