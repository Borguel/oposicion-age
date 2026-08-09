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
// que el selector público no las muestre ni las anuncie; solo entran en el
// selector de quien ya tenga acceso concedido, ver
// obtenerOposicionesVisiblesDelUsuario más abajo.
const OPOSICIONES_OCULTAS = [
  { id: "METRO", nombre: "Agente de Movilidad (Metro de Madrid)", siglas: "Metro" }
];

const CATALOGO_COMPLETO = [...OPOSICIONES, ...OPOSICIONES_OCULTAS];

function _porId(id) {
  return CATALOGO_COMPLETO.find((o) => o.id === id);
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
// <select> móvil a partir de la lista de oposiciones dada -- ver
// _refrescarSelectorConOposicionesDelUsuario, que la llama en cuanto se
// conoce la lista real de oposiciones visibles para este usuario.
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

// Consulta /oposiciones-disponibles -- ya filtrado por el backend (ver
// blueprints/temario.py:_oposiciones_visibles_para_la_peticion) a solo las
// oposiciones que este usuario puede ver: las públicas que ya ha activado
// él mismo (o el catálogo público completo si todavía no ha activado
// ninguna, para poder elegir la primera) más cualquier oposición oculta
// (p. ej. METRO) que se le haya concedido a mano desde el panel admin.
//
// Devuelve `null` si la consulta falla (sin red, backend caído...) -- para
// que cada llamador pueda distinguir "no se pudo saber" (mejor no tocar lo
// que ya hubiera pintado, o caer al catálogo público como red de
// seguridad) de "se sabe con certeza que no tiene ninguna" (array vacío:
// cuenta nueva sin ninguna oposición activada todavía, ver
// zona-opositor/script.js, que en ese caso ofrece elegir la primera en vez
// de pintar un selector vacío).
export async function obtenerOposicionesVisiblesDelUsuario(user) {
  if (!user) return null;
  return obtenerOposicionesVisiblesConToken(await user.getIdToken());
}

// Misma consulta que obtenerOposicionesVisiblesDelUsuario, pero para
// páginas que ya tienen un token de sesión a mano (p. ej. estadisticas,
// que ya llama a obtenerAuthHeaders() para sus propias peticiones) y no
// necesitan volver a pedírselo al objeto de usuario de Firebase.
export async function obtenerOposicionesVisiblesConToken(token) {
  if (!token) return null;
  try {
    const res = await fetch(`${BACKEND_URL}/oposiciones-disponibles`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return null;
    const datos = await res.json();
    const idsVisibles = new Set((datos.oposiciones || []).map((o) => o.id));
    return CATALOGO_COMPLETO.filter((o) => idsVisibles.has(o.id));
  } catch (e) {
    return null;
  }
}

// POST /activar-oposicion: autoservicio, el propio usuario elige "quiero
// estudiar esta oposición" (ver zona-opositor/script.js) y eso arranca su
// prueba gratuita de 7 días PARA ESA OPOSICIÓN CONCRETA (ver
// registro_progreso_usuario.activar_oposicion_usuario). Lanza si el
// backend rechaza la petición -- el llamador decide cómo mostrarlo.
export async function activarOposicion(token, oposicionId) {
  const res = await fetch(`${BACKEND_URL}/activar-oposicion`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ oposicion: oposicionId })
  });
  if (!res.ok) {
    const datos = await res.json().catch(() => ({}));
    throw new Error(datos.error || "No se pudo activar la oposición.");
  }
}

// Fire-and-forget, sin bloquear el primer pintado de la nav -- igual que el
// resto de piezas que dependen de una llamada a la API (ver
// inyectarBannerPrueba en auth.js). Repinta el selector con la lista
// AUTORITATIVA del backend (no la añade a OPOSICIONES: desde que cada
// oposición pública también hay que activarla, ya no se puede asumir que
// las 3 públicas sean siempre visibles) -- solo si de verdad hace falta
// corregir el pintado optimista de más abajo, para no repintar (y
// reordenar dentro del cajón móvil, ver inyectarSelectorOposicion) sin
// necesidad.
async function _corregirSelectorConOposicionesDelUsuario(user, listaOptimista) {
  const lista = await obtenerOposicionesVisiblesDelUsuario(user);
  // null (fallo de red): se deja el pintado optimista tal cual -- mejor
  // eso que vaciarlo por un fallo transitorio.
  if (lista === null) return;
  // []: cuenta sin ninguna oposición activada todavía -- no hay nada entre
  // lo que cambiar, así que no tiene sentido pintar un selector vacío; el
  // propio usuario elige su primera oposición desde Zona opositor. Se dejа
  // el pintado optimista (mostraba el catálogo público) tal cual: no hay
  // nada mejor que ofrecer aquí mismo.
  if (lista.length === 0) return;
  const mismosIds = lista.length === listaOptimista.length && lista.every((o, i) => o.id === listaOptimista[i]?.id);
  if (!mismosIds) _pintarSelectorOposicion(lista);
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
// objeto de usuario de Firebase Auth (o null/undefined sin sesión).
//
// Se pinta primero de forma optimista con el catálogo público completo
// (síncrono, sin esperar a ninguna petición -- IMPORTANTE: esto también
// mantiene el orden relativo con el resto de piezas que se insertan por
// delante del cajón móvil vía prepend(), ver construirBusquedaGlobal en
// auth.js, que se llama justo después de esta función) y se corrige en
// cuanto se conoce la lista real de oposiciones activadas por el usuario
// (_corregirSelectorConOposicionesDelUsuario) -- puede ser una oposición
// oculta concedida a mano, o (más frecuente ahora) solo un subconjunto de
// las públicas si no las ha activado todas.
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
  _corregirSelectorConOposicionesDelUsuario(user, OPOSICIONES);
}
