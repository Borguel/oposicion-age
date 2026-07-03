// Catálogo de oposiciones soportadas por la web (debe reflejar el mismo
// catálogo que oposiciones.py en el backend) y ayuda para saber/cambiar
// cuál está estudiando el usuario ahora mismo. Se guarda en localStorage
// (no en la cuenta) porque es solo "qué estoy mirando ahora", no depende
// de qué oposiciones tenga contratadas -- eso lo dice /mi-perfil.
export const OPOSICIONES = [
  { id: "AGE", nombre: "Cuerpo General Administrativo (AGE)" },
  { id: "GACE", nombre: "Cuerpo de Gestión (GACE)" }
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

// Inserta (si no existe ya) un selector de oposición en la barra de
// navegación compartida (.age-nav). Al cambiarlo se recarga la página para
// que temas/tests/chat se actualicen con la oposición nueva.
export function inyectarSelectorOposicion() {
  const nav = document.querySelector(".age-nav");
  if (!nav || nav.querySelector("[data-nav-oposicion]")) return;

  const select = document.createElement("select");
  select.setAttribute("data-nav-oposicion", "");
  select.title = "Oposición que estás estudiando";
  OPOSICIONES.forEach((o) => {
    const opcion = document.createElement("option");
    opcion.value = o.id;
    opcion.textContent = o.nombre;
    select.appendChild(opcion);
  });
  select.value = obtenerOposicionActual();
  select.addEventListener("change", () => {
    establecerOposicionActual(select.value);
    sessionStorage.clear();
    window.location.reload();
  });
  nav.appendChild(select);
}
