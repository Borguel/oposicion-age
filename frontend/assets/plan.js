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
import { auth, idToken, esperarUsuario } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { obtenerOposicionActual } from "/assets/oposicion.js";
import { icono } from "/assets/icons.js";

const ORDEN_PLANES = { gratis: 0, basico: 1, premium: 2 };

// Incluye el uid en la clave: sessionStorage sobrevive a la navegación entre
// páginas dentro de la misma pestaña, así que sin esto una caché que
// quedara sin limpiar de una sesión anterior (p. ej. tras cambiar de cuenta
// sin pasar por "Cerrar sesión") se serviría tal cual para la cuenta nueva,
// sin ninguna comprobación de a quién pertenece.
function claveCache(oposicion) {
  const uid = auth.currentUser?.uid || "anonimo";
  return `age_plan_cache_${uid}_${oposicion}`;
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
  // forzarRefresco=true: esto decide si se bloquea la página entera, así
  // que no puede fiarse de una respuesta cacheada de antes de un cambio de
  // plan/prueba (pagar, o un fix de backend). Cuesta una petición extra a
  // /mi-perfil por carga de página, asumible frente al riesgo de bloquear
  // (o dejar pasar) con datos desfasados.
  const perfil = await obtenerPlan(true, oposicion);
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
  // "gratis" con prueba_fin todavía sin fijar (null, no una fecha ya
  // pasada) es un registro por email+contraseña que aún no ha confirmado
  // su correo -- la prueba de 7 días arranca en cuanto lo confirme (ver
  // auth_utils.requiere_login), así que el mensaje debe ser "confirma tu
  // correo", no "tu prueba ha terminado" (sonaría a que la perdió).
  const pruebaPendienteDeVerificar = sinNingunPlan && !perfil.prueba_fin;
  // Alguien que YA paga por otra oposición (perfil.tiene_plan_de_pago) no
  // ha "perdido ninguna prueba" al mirar una oposición que sencillamente
  // todavía no ha contratado -- decirle "tu prueba ha terminado" (pensado
  // para quien nunca ha pagado nada) sonaría a que se le acabó algo que en
  // realidad nunca llegó a empezar aquí. Ver tiene_plan_de_pago_activo en
  // planes.py.
  const yaEsClienteDeOtraOposicion = sinNingunPlan && !pruebaPendienteDeVerificar && perfil.tiene_plan_de_pago;
  const titulo = pruebaPendienteDeVerificar
    ? "Confirma tu correo para empezar tu prueba gratuita"
    : yaEsClienteDeOtraOposicion
      ? "Añade esta oposición a tu plan"
      : sinNingunPlan
        ? "Tu prueba gratuita ha terminado"
        : `Esta herramienta requiere el plan ${nombrePlan}`;
  const cuerpo = pruebaPendienteDeVerificar
    ? "En cuanto confirmes tu correo electrónico se activarán tus 7 días de prueba con acceso Premium. Revisa tu bandeja de entrada (y la carpeta de spam), o pide que te lo reenviemos."
    : yaEsClienteDeOtraOposicion
      ? "Ya tienes un plan activo en Domina tu Opo, pero todavía no incluye esta oposición. Añádela desde Planes para acceder a esta herramienta aquí también."
      : sinNingunPlan
        ? "Elige un plan para seguir usando Domina tu Opo. Tu progreso y tus datos siguen a salvo, y podrás retomarlo en cuanto te suscribas."
        : `Tu plan actual (${NOMBRE_PLAN[perfil.plan] || perfil.plan}) no incluye esta herramienta.`;
  const botones = pruebaPendienteDeVerificar
    ? `<button type="button" class="age-btn age-btn-primary" id="age-bloqueo-reenviar">Reenviar correo de confirmación</button>
       <a class="age-btn age-btn-outline" href="/zona-opositor/">Volver a Zona Opositor</a>`
    : `<a class="age-btn age-btn-primary" href="/planes/">Ver planes</a>
       <a class="age-btn age-btn-outline" href="/zona-opositor/">Volver a Zona Opositor</a>`;

  const overlay = document.createElement("div");
  overlay.className = "age-bloqueo-overlay";
  overlay.innerHTML = `
    <div class="age-bloqueo-card">
      <div class="age-bloqueo-icono">${icono("candado", 32)}</div>
      <h1>${titulo}</h1>
      <p>${cuerpo}</p>
      <div class="age-bloqueo-botones">
        ${botones}
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  if (pruebaPendienteDeVerificar) {
    const boton = document.getElementById("age-bloqueo-reenviar");
    boton.addEventListener("click", async () => {
      boton.disabled = true;
      boton.textContent = "Enviando…";
      try {
        // Import perezoso (no en el import estático de arriba): así una
        // página que sustituya /assets/auth.js por un stub mínimo en
        // pruebas (sin este export en concreto) no rompe el resto de
        // plan.js -- el mismo motivo por el que auth.js ya importa
        // plan.js de forma perezosa en su propio banner de prueba.
        const { enviarVerificacionEmail } = await import("/assets/auth.js");
        await enviarVerificacionEmail();
        boton.textContent = "Correo enviado";
      } catch {
        boton.textContent = "Reenviar correo de confirmación";
        boton.disabled = false;
      }
    });
  }
}
