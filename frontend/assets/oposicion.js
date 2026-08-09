// Catálogo de oposiciones soportadas por la web (debe reflejar el mismo
// catálogo que oposiciones.py en el backend) y ayuda para saber/cambiar
// cuál está estudiando el usuario ahora mismo. Se guarda en localStorage
// (no en la cuenta) porque es solo "qué estoy mirando ahora", no depende
// de qué oposiciones tenga contratadas -- eso lo dice /mi-perfil.
import { activarPopover } from "/assets/popover.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

export const OPOSICIONES = [
  { id: "AGE", nombre: "Cuerpo General Administrativo (AGE)", siglas: "AGE" },
  { id: "GACE", nombre: "Cuerpo de Gestión (GACE)", siglas: "GACE" },
  { id: "AUXILIAR", nombre: "Cuerpo General Auxiliar (Auxiliar)", siglas: "Auxiliar" }
];

// Oposiciones dadas de alta pero NO ofrecidas a todo el mundo (grupo
// cerrado, activado a mano por usuario desde el panel admin -- ver
// oposiciones.py, campo "oculta"). Fuera de OPOSICIONES a propósito para
// que el selector público no las muestre ni las anuncie; solo se añaden en
// el selector de quien ya tenga acceso concedido, ver
// _anadirOposicionesOcultasDelUsuario más abajo.
const OPOSICIONES_OCULTAS = [
  { id: "METRO", nombre: "Agente de Movilidad (Metro de Madrid)", siglas: "Metro" }
];

function _porId(id) {
  return OPOSICIONES.find((o) => o.id === id) || OPOSICIONES_OCULTAS.find((o) => o.id === id);
}

const CLAVE = "age_oposicion_actual";

export function obtenerOposicionActual() {
  const guardada = localStorage.getItem(CLAVE);
  return _porId(guardada) ? guardada : OPOSICIONES[0].id;
}

export function establecerOposicionActual(id) {
  if (!_porId(id)) return;
  localStorage.setItem(CLAVE, id);
}

function cambiarOposicionYRecargar(id) {
  establecerOposicionActual(id);
  sessionStorage.clear();
  window.location.reload();
}

// Dibuja (reemplazando lo que hubiera) el popover de escritorio + el
// <select> móvil a partir de la lista de oposiciones dada. Separado de
// inyectarSelectorOposicion para poder llamarlo dos veces: un primer
// pintado inmediato y síncrono con la lista pública, y un repintado
// posterior (solo si hace falta) cuando se sabe si el usuario tiene alguna
// oposición oculta activada -- ver _anadirOposicionesOcultasDelUsuario.
function _pintarSelectorOposicion(lista) {
  const utilidades = document.querySelector(".age-nav-utilidades");
  const drawer = document.querySelector(".age-nav-links");
  const actual = obtenerOposicionActual();

  utilidades?.querySelector(".age-oposicion-popover")?.remove();
  drawer?.querySelector(".age-oposicion-movil")?.remove();

  if (utilidades) {
    const sigla = lista.find((o) => o.id === actual)?.siglas || actual;
    const popover = document.createElement("div");
    popover.className = "age-oposicion-popover";
    popover.innerHTML = `
      <button type="button" class="age-nav-op-btn" data-popover-toggle aria-label="Cambiar de oposición" title="Oposición que estás estudiando">
        <span>${sigla}</span>
        <span class="age-nav-op-caret">▾</span>
      </button>
      <div class="age-popover age-popover-menu" data-popover-panel>
        ${lista.map((o) => `<button type="button" class="age-popover-opcion${o.id === actual ? " age-popover-opcion-actual" : ""}" data-op="${o.id}">${o.nombre}</button>`).join("")}
      </div>
    `;
    popover.querySelectorAll("[data-op]").forEach((btn) => {
      btn.addEventListener("click", () => cambiarOposicionYRecargar(btn.dataset.op));
    });
    activarPopover(popover);
    utilidades.insertBefore(popover, utilidades.firstChild);
  }

  if (drawer) {
    const bloque = document.createElement("div");
    bloque.className = "age-oposicion-movil";
    const select = document.createElement("select");
    select.id = "age-oposicion-movil-select";
    select.setAttribute("data-nav-oposicion", "");
    lista.forEach((o) => {
      const opcion = document.createElement("option");
      opcion.value = o.id;
      opcion.textContent = o.nombre;
      select.appendChild(opcion);
    });
    select.value = actual;
    select.addEventListener("change", () => cambiarOposicionYRecargar(select.value));
    bloque.innerHTML = `<label class="age-oposicion-movil-label" for="age-oposicion-movil-select">Oposición</label>`;
    bloque.appendChild(select);
    drawer.prepend(bloque);
  }
}

// Consulta /oposiciones-disponibles (ya filtrado por el backend: solo
// devuelve las ocultas en las que este usuario tenga una entrada en
// suscripciones, ver blueprints/temario.py) y devuelve las de
// OPOSICIONES_OCULTAS a las que el usuario tiene acceso concedido (normalmente
// ninguna). Exportada para que cualquier página -- no solo el selector de la
// nav -- pueda enterarse de si el usuario actual tiene alguna oposición
// oculta activada (ver zona-opositor/script.js, que también necesita
// pintarla en su propio selector de chips y en "Estás preparando").
export async function obtenerOposicionesOcultasDisponibles(user) {
  if (!user) return [];
  return obtenerOposicionesOcultasConToken(await user.getIdToken());
}

// Misma consulta que obtenerOposicionesOcultasDisponibles, pero para
// páginas que ya tienen un token de sesión a mano (p. ej. estadisticas,
// que ya llama a obtenerAuthHeaders() para sus propias peticiones) y no
// necesitan volver a pedírselo al objeto de usuario de Firebase.
export async function obtenerOposicionesOcultasConToken(token) {
  if (!token || OPOSICIONES_OCULTAS.length === 0) return [];
  try {
    const res = await fetch(`${BACKEND_URL}/oposiciones-disponibles`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return [];
    const datos = await res.json();
    const idsDisponibles = new Set((datos.oposiciones || []).map((o) => o.id));
    return OPOSICIONES_OCULTAS.filter((o) => idsDisponibles.has(o.id));
  } catch (e) {
    // Sin conexión o backend caído: se trata como "sin oposiciones ocultas"
    // -- la próxima carga de página lo reintenta.
    return [];
  }
}

// Fire-and-forget, sin bloquear el primer pintado del selector de la nav --
// igual que el resto de piezas de la nav que dependen de una llamada a la
// API (ver inyectarBannerPrueba en auth.js).
async function _anadirOposicionesOcultasDelUsuario(user) {
  const extra = await obtenerOposicionesOcultasDisponibles(user);
  if (extra.length > 0) _pintarSelectorOposicion([...OPOSICIONES, ...extra]);
}

// Inserta (si no existe ya) el selector de oposición en la barra de
// navegación compartida -- dos versiones, mostradas o no según el
// breakpoint por CSS (no por JS, ya que cambiar de oposición siempre
// recarga la página, así que no hay estado que sincronizar entre las
// dos): un botón con la sigla de la oposición actual + popover dentro de
// .age-nav-utilidades para escritorio (así el usuario ve todo el rato en
// qué oposición está, sin abrir nada -- antes era solo un icono de
// edificio sin texto), y un <select> nativo inline dentro del cajón del
// menú hamburguesa (.age-nav-links) para móvil, más cómodo al tacto que
// un popover anidado dentro de otro cajón. Solo tiene sentido con sesión
// iniciada (sin cuenta no hay temario/tests que cambiar de oposición), así
// que si no hay usuario se quita si ya estuviera puesto. `user` es el
// objeto de usuario de Firebase Auth (o null/undefined sin sesión) -- se
// usa también para pedirle su token y ver si tiene alguna oposición oculta
// activada (ver _anadirOposicionesOcultasDelUsuario).
export function inyectarSelectorOposicion(user) {
  const utilidades = document.querySelector(".age-nav-utilidades");
  const drawer = document.querySelector(".age-nav-links");

  if (!user) {
    utilidades?.querySelector(".age-oposicion-popover")?.remove();
    drawer?.querySelector(".age-oposicion-movil")?.remove();
    return;
  }

  if (!utilidades?.querySelector(".age-oposicion-popover") && !drawer?.querySelector(".age-oposicion-movil")) {
    _pintarSelectorOposicion(OPOSICIONES);
  }
  _anadirOposicionesOcultasDelUsuario(user);
}
