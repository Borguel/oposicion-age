// Ayuda a pintar la interfaz según el plan del usuario (Gratis/Básico/Premium)
// PARA LA OPOSICIÓN QUE TENGA SELECCIONADA (cada oposición tiene su propio
// plan/suscripción independiente).
//
// IMPORTANTE: esto es solo para la experiencia de usuario (mostrar avisos de
// "esto requiere el plan X"). NO es una barrera de seguridad real: este es un
// sitio estático, cualquiera puede ver el código fuente o llamar al backend
// directamente saltándose esta comprobación. La única protección real son
// los decoradores @requiere_plan del backend (ver auth_utils.py).
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

// Redirige a /login/ si no hay sesión, o muestra un aviso de "requiere plan
// X" si el usuario no tiene el nivel suficiente EN LA OPOSICIÓN SELECCIONADA.
// Devuelve true si la página puede usarse con normalidad.
export async function requierePlanEnPagina(planMinimo, oposicion = obtenerOposicionActual()) {
  const usuario = await esperarUsuario();
  if (!usuario) {
    window.location.href = `/login/?next=${encodeURIComponent(window.location.pathname)}`;
    return false;
  }
  const { plan } = await obtenerPlan(false, oposicion);
  if (!planCubre(plan, planMinimo)) {
    mostrarAvisoUpgrade(planMinimo, plan);
    return false;
  }
  return true;
}

export function mostrarAvisoUpgrade(planMinimo, planActual) {
  const aviso = document.createElement("div");
  aviso.style.cssText =
    "margin:16px;padding:16px 20px;border-radius:14px;background:#fff4e5;" +
    "border:1px solid #ffa633;text-align:center;font-family:var(--age-font, sans-serif);";
  aviso.innerHTML =
    `Esta herramienta requiere el plan <strong>${planMinimo}</strong> ` +
    `(tu plan actual: ${planActual}). ` +
    `<a href="/planes/" style="color:#ff8c00;font-weight:600;">Ver planes →</a>`;
  document.body.prepend(aviso);
}
