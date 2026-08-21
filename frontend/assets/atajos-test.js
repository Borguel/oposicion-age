// Atajos de teclado durante un test: 1-9 elige la opción en esa posición,
// flecha derecha/izquierda avanza/retrocede -- un mismo test se repite
// pregunta tras pregunta muchas veces por sesión, así que depender solo
// del ratón/dedo es fricción real para quien lo usa a diario (20/08/2026,
// auditoría UX). Un solo módulo compartido en vez de repetir la lógica en
// cada script.js: todas las páginas de test renderizan el mismo
// #form-pregunta / input[name="respuesta"] / #btn-anterior (ver el
// comentario de test-oficial/script.js).

function esElementoEditable(el) {
  if (!el) return false;
  if (el.isContentEditable) return true;
  const tag = el.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag === "INPUT") {
    const tiposSinTexto = ["radio", "checkbox", "button", "submit", "reset"];
    return !tiposSinTexto.includes(el.type);
  }
  return false;
}

export function activarAtajosTeclado() {
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    // No pisar el teclado de un campo de texto real, ni el de un diálogo
    // de SweetAlert2 abierto (confirmaciones, avisos de límite...).
    if (esElementoEditable(document.activeElement)) return;
    if (document.querySelector(".swal2-container")) return;

    const formulario = document.getElementById("form-pregunta");
    if (!formulario) return;

    if (e.key >= "1" && e.key <= "9") {
      const opciones = formulario.querySelectorAll('input[name="respuesta"]');
      const opcion = opciones[Number(e.key) - 1];
      if (opcion) {
        opcion.click();
        e.preventDefault();
      }
      return;
    }

    if (e.key === "ArrowRight") {
      const botonSiguiente = formulario.querySelector('button[type="submit"]');
      if (botonSiguiente) {
        botonSiguiente.click();
        e.preventDefault();
      }
      return;
    }

    if (e.key === "ArrowLeft") {
      const botonAnterior = document.getElementById("btn-anterior");
      if (botonAnterior) {
        botonAnterior.click();
        e.preventDefault();
      }
    }
  });
}
