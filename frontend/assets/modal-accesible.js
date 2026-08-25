// Foco/teclado accesible para los modales propios del sitio (los que
// sustituyeron a confirm()/prompt() nativos): atrapa el Tab dentro del
// modal mientras está abierto, cierra con Escape, y devuelve el foco al
// elemento que lo abrió al cerrarse -- sin esto, alguien que navega con
// teclado pierde el foco en un elemento que ha quedado detrás, invisible
// tras el modal.
//
// Extraído de frontend/mi-cuenta/script.js (25/08/2026, auditoría de
// accesibilidad): el mismo patrón ya existía ahí y en frontend/admin/
// script.js, pero cada modal nuevo (login, mis-documentos...) lo estaba
// reimplementando o, más a menudo, no lo tenía en absoluto.
//
// El propio contenedor del modal necesita un elemento con tabindex="-1"
// (normalmente la tarjeta/caja visible) para poder recibir el foco inicial
// al abrirse sin ser en sí un control interactivo.
export function activarAccesibilidadModal(modal, botonCerrarSeguro) {
  let elementoPrevio = null;
  // getComputedStyle en vez de leer modal.style.display directamente: los
  // modales de login/mi-cuenta se abren con style.display = "flex"/"none",
  // pero los de mis-documentos usan classList.toggle("hidden") (que aplica
  // display:none por CSS) -- el estilo computado detecta ambos por igual.
  function estaAbierto() {
    return getComputedStyle(modal).display !== "none";
  }
  function focables() {
    return Array.from(
      modal.querySelectorAll(
        'input, select, textarea, button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
      ),
    );
  }
  document.addEventListener("keydown", (e) => {
    if (!estaAbierto()) return;
    if (e.key === "Escape") {
      botonCerrarSeguro.click();
      return;
    }
    if (e.key !== "Tab") return;
    const els = focables();
    if (!els.length) return;
    const primero = els[0];
    const ultimo = els[els.length - 1];
    if (e.shiftKey && document.activeElement === primero) {
      e.preventDefault();
      ultimo.focus();
    } else if (!e.shiftKey && document.activeElement === ultimo) {
      e.preventDefault();
      primero.focus();
    }
  });
  return {
    alAbrir() {
      elementoPrevio = document.activeElement;
      modal.querySelector('[tabindex="-1"]')?.focus();
    },
    alCerrar() {
      elementoPrevio?.focus();
      elementoPrevio = null;
    },
  };
}
