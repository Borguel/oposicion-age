// Catálogo de oposiciones soportadas por la web (debe reflejar el mismo
// catálogo que oposiciones.py en el backend) y ayuda para saber/cambiar
// cuál está estudiando el usuario ahora mismo. Se guarda en localStorage
// (no en la cuenta) porque es solo "qué estoy mirando ahora", no depende
// de qué oposiciones tenga contratadas -- eso lo dice /mi-perfil.
export const OPOSICIONES = [
  { id: "AGE", nombre: "Cuerpo General Administrativo (AGE)", siglas: "AGE" },
  { id: "GACE", nombre: "Cuerpo de Gestión (GACE)", siglas: "GACE" }
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
// navegación compartida (dentro de #age-nav-right si existe, o en .age-nav
// como fallback). Al cambiarlo se recarga la página para que temas/tests/
// chat se actualicen con la oposición nueva.
export function inyectarSelectorOposicion() {
  const contenedor = document.getElementById("age-nav-right") || document.querySelector(".age-nav");
  if (!contenedor || contenedor.querySelector("[data-nav-oposicion]")) return;

  const select = document.createElement("select");
  select.setAttribute("data-nav-oposicion", "");
  select.title = "Oposición que estás estudiando";
  OPOSICIONES.forEach((o) => {
    const opcion = document.createElement("option");
    opcion.value = o.id;
    // Siglas cortas en el menú (con el nombre completo en el "title" del
    // <option>) para que no se corte en pantallas de móvil estrechas.
    opcion.textContent = o.siglas || o.nombre;
    opcion.title = o.nombre;
    select.appendChild(opcion);
  });
  select.value = obtenerOposicionActual();
  select.addEventListener("change", () => {
    establecerOposicionActual(select.value);
    sessionStorage.clear();
    window.location.reload();
  });
  contenedor.insertBefore(select, contenedor.firstChild);
}
