// Catálogo de oposiciones soportadas por la web (debe reflejar el mismo
// catálogo que oposiciones.py en el backend) y ayuda para saber/cambiar
// cuál está estudiando el usuario ahora mismo. Se guarda en localStorage
// (no en la cuenta) porque es solo "qué estoy mirando ahora", no depende
// de qué oposiciones tenga contratadas -- eso lo dice /mi-perfil.
import { icono } from "/assets/icons.js";
import { activarPopover } from "/assets/popover.js";

export const OPOSICIONES = [
  { id: "AGE", nombre: "Cuerpo General Administrativo (AGE)", siglas: "AGE" },
  { id: "GACE", nombre: "Cuerpo de Gestión (GACE)", siglas: "GACE" },
  { id: "AUXILIAR", nombre: "Cuerpo General Auxiliar (Auxiliar)", siglas: "Auxiliar" }
];

const CLAVE = "age_oposicion_actual";

export function obtenerOposicionActual() {
  const guardada = localStorage.getItem(CLAVE);
  return OPOSICIONES.some((o) => o.id === guardada) ? guardada : OPOSICIONES[0].id;
}

export function establecerOposicionActual(id) {
  if (!OPOSICIONES.some((o) => o.id === id)) return;
  localStorage.setItem(CLAVE, id);
}

function cambiarOposicionYRecargar(id) {
  establecerOposicionActual(id);
  sessionStorage.clear();
  window.location.reload();
}

// Inserta (si no existe ya) el selector de oposición en la barra de
// navegación compartida -- dos versiones, mostradas o no según el
// breakpoint por CSS (no por JS, ya que cambiar de oposición siempre
// recarga la página, así que no hay estado que sincronizar entre las
// dos): un botón-icono con popover dentro de .age-nav-utilidades para
// escritorio (mismo lenguaje visual que el buscador y la cuenta), y un
// <select> nativo inline dentro del cajón del menú hamburguesa
// (.age-nav-links) para móvil, más cómodo al tacto que un popover
// anidado dentro de otro cajón. Solo tiene sentido con sesión iniciada
// (sin cuenta no hay temario/tests que cambiar de oposición), así que si
// no hay usuario se quita si ya estuviera puesto.
export function inyectarSelectorOposicion(haySesion) {
  const utilidades = document.querySelector(".age-nav-utilidades");
  const drawer = document.querySelector(".age-nav-links");

  if (!haySesion) {
    utilidades?.querySelector(".age-oposicion-popover")?.remove();
    drawer?.querySelector(".age-oposicion-movil")?.remove();
    return;
  }

  const actual = obtenerOposicionActual();

  if (utilidades && !utilidades.querySelector(".age-oposicion-popover")) {
    const popover = document.createElement("div");
    popover.className = "age-oposicion-popover";
    popover.innerHTML = `
      <button type="button" class="age-nav-icon-btn" data-popover-toggle aria-label="Cambiar de oposición" title="Oposición que estás estudiando">${icono("edificio", 18)}</button>
      <div class="age-popover age-popover-menu" data-popover-panel>
        ${OPOSICIONES.map((o) => `<button type="button" class="age-popover-opcion${o.id === actual ? " age-popover-opcion-actual" : ""}" data-op="${o.id}">${o.nombre}</button>`).join("")}
      </div>
    `;
    popover.querySelectorAll("[data-op]").forEach((btn) => {
      btn.addEventListener("click", () => cambiarOposicionYRecargar(btn.dataset.op));
    });
    activarPopover(popover);
    utilidades.insertBefore(popover, utilidades.firstChild);
  }

  if (drawer && !drawer.querySelector(".age-oposicion-movil")) {
    const bloque = document.createElement("div");
    bloque.className = "age-oposicion-movil";
    const select = document.createElement("select");
    select.setAttribute("data-nav-oposicion", "");
    OPOSICIONES.forEach((o) => {
      const opcion = document.createElement("option");
      opcion.value = o.id;
      opcion.textContent = o.nombre;
      select.appendChild(opcion);
    });
    select.value = actual;
    select.addEventListener("change", () => cambiarOposicionYRecargar(select.value));
    bloque.innerHTML = `<label class="age-oposicion-movil-label">Oposición</label>`;
    bloque.appendChild(select);
    drawer.prepend(bloque);
  }
}
