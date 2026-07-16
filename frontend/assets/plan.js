// Ayuda a pintar la interfaz según el plan del usuario (Básico/Premium, o
// "gratis" como valor interno para "sin acceso": prueba terminada y sin
// pagar) PARA LA OPOSICIÓN QUE TENGA SELECCIONADA (cada oposición tiene su
// propio plan/suscripción independiente). El backend resuelve la prueba
// gratuita de 7 días automáticamente (ver planes.py) -- "premium" aquí
// puede significar plan pagado O prueba activa, el frontend no distingue.
//
// IMPORTANTE: esto es solo para la experiencia de usuario (bloquear la
// página a pantalla completa si no hay acceso). NO es una barrera de
// seguridad real: este es un sitio estático, cualquiera puede ver el
// código fuente o llamar al backend directamente saltándose esta
// comprobación. La única protección real son los decoradores
// @requiere_plan del backend (ver auth_utils.py).
import { idToken, esperarUsuario } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { obtenerOposicionActual } from "/assets/oposicion.js";

const ORDEN_PLANES = { gratis: 0, basico: 1, premium: 2 };

function claveCache(oposicion) {
  return `age_plan_cache_${oposicion}`;
}

export async function obtenerPlan(forzarRefresco = false, oposicion = obtenerOposicionActual()) {
  const clave = claveCache(oposicion);
  if (!forzarRefresco) {
    const cache = sessionStorage.getItem(clave);
    if (cache) return JSON.parse(cache);
  }
  const token = await idToken();
  if (!token) return { plan: "anonimo", subscription_status: null };
  try {
    const res = await fetch(`${BACKEND_URL}/mi-perfil?oposicion=${encodeURIComponent(oposicion)}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return { plan: "gratis", subscription_status: null };
    const datos = await res.json();
    sessionStorage.setItem(clave, JSON.stringify(datos));
    return datos;
  } catch (e) {
    return { plan: "gratis", subscription_status: null };
  }
}

export function planCubre(planUsuario, planRequerido) {
  return (ORDEN_PLANES[planUsuario] ?? 0) >= (ORDEN_PLANES[planRequerido] ?? 0);
}

const NOMBRE_PLAN = { basico: "Básico", premium: "Premium" };

// Redirige a /login/ si no hay sesión, o bloquea la página a pantalla
// completa si el usuario no tiene el nivel suficiente EN LA OPOSICIÓN
// SELECCIONADA (prueba terminada sin pagar, o un plan que no incluye esta
// herramienta). Cada página gateada debe llamar a esto ANTES de pintar
// nada de su contenido: `if (!(await protegerPagina("basico"))) return;`.
// Devuelve true si la página puede usarse con normalidad.
export async function protegerPagina(planMinimo, oposicion = obtenerOposicionActual()) {
  const usuario = await esperarUsuario();
  if (!usuario) {
    window.location.href = `/login/?next=${encodeURIComponent(window.location.pathname)}`;
    return false;
  }
  const perfil = await obtenerPlan(false, oposicion);
  if (!planCubre(perfil.plan, planMinimo)) {
    mostrarPantallaBloqueo(planMinimo, perfil);
    return false;
  }
  return true;
}

// Overlay a pantalla completa (no un aviso pequeño): cubre cualquier
// contenido que la página ya hubiera empezado a pintar, para que un
// usuario sin acceso no vea ni un instante la herramienta.
export function mostrarPantallaBloqueo(planMinimo, perfil) {
  if (document.querySelector(".age-bloqueo-overlay")) return;
  const nombrePlan = NOMBRE_PLAN[planMinimo] || planMinimo;
  const sinNingunPlan = perfil.plan === "gratis";
  const titulo = sinNingunPlan ? "Tu prueba gratuita ha terminado" : `Esta herramienta requiere el plan ${nombrePlan}`;
  const cuerpo = sinNingunPlan
    ? "Elige un plan para seguir usando Domina tu Opo. Tu progreso y tus datos siguen a salvo, y podrás retomarlo en cuanto te suscribas."
    : `Tu plan actual (${NOMBRE_PLAN[perfil.plan] || perfil.plan}) no incluye esta herramienta.`;

  const overlay = document.createElement("div");
  overlay.className = "age-bloqueo-overlay";
  overlay.innerHTML = `
    <div class="age-bloqueo-card">
      <div class="age-bloqueo-icono">🔒</div>
      <h1>${titulo}</h1>
      <p>${cuerpo}</p>
      <div class="age-bloqueo-botones">
        <a class="age-btn age-btn-primary" href="/planes/">Ver planes</a>
        <a class="age-btn age-btn-outline" href="/zona-opositor/">Volver a Zona Opositor</a>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
}
