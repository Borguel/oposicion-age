import { idToken, esperarUsuario } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { OPOSICIONES, obtenerOposicionActual, establecerOposicionActual, activarOposicion } from "/assets/oposicion.js";
import { icono } from "/assets/icons.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

const mensajeCheckout = document.getElementById("mensaje-checkout");
const selectorOposicion = document.getElementById("selector-oposicion");
const ctaPrueba = document.getElementById("cta-prueba");

const CONFIANZA = [
  { icono: "candado", texto: "Pago cifrado y seguro" },
  { icono: "actualizar", texto: "Cancela cuando quieras" },
  { icono: "rayo", texto: "Acceso inmediato tras el pago" }
];

function renderizarConfianza() {
  const contenedor = document.getElementById("planes-confianza");
  contenedor.innerHTML = CONFIANZA.map((item) => `
    <span class="planes-confianza-item">
      <span class="planes-confianza-icono">${icono(item.icono, 14)}</span>
      <span>${item.texto}</span>
    </span>
  `).join("");
}

function mostrarMensajeCheckout() {
  const params = new URLSearchParams(window.location.search);
  const estado = params.get("checkout");
  if (estado === "success") {
    mensajeCheckout.textContent = "¡Pago completado! Puede tardar unos segundos en activarse tu nuevo plan.";
    mensajeCheckout.className = "mensaje-checkout ok";
    mensajeCheckout.style.display = "block";
  } else if (estado === "cancel") {
    mensajeCheckout.textContent = "Pago cancelado, no se ha realizado ningún cargo.";
    mensajeCheckout.className = "mensaje-checkout error";
    mensajeCheckout.style.display = "block";
  }
}

// El selector de oposición ya NO es un desplegable libre por defecto -- la
// compra queda ligada a la oposición que el usuario tiene en contexto
// (obtenerOposicionActual(), la misma que usa el resto de la web, ver
// assets/oposicion.js), mostrada como texto fijo. El <select> real sigue
// existiendo (oculto) para el caso de quien llega aquí sin haber elegido
// ninguna oposición todavía (o quiere comprar para otra distinta): se
// revela con el enlace "Cambiar" en vez de estar siempre a la vista, que
// era lo que resultaba confuso con las 3 oposiciones sueltas por defecto.
function actualizarEtiquetaOposicion() {
  const actual = OPOSICIONES.find((o) => o.id === selectorOposicion.value);
  document.getElementById("selector-oposicion-actual").textContent = actual ? actual.nombre : selectorOposicion.value;
}

function inicializarSelectorOposicion() {
  OPOSICIONES.forEach((o) => {
    const opcion = document.createElement("option");
    opcion.value = o.id;
    opcion.textContent = o.nombre;
    selectorOposicion.appendChild(opcion);
  });
  const params = new URLSearchParams(window.location.search);
  const oposicionUrl = params.get("oposicion");
  selectorOposicion.value = oposicionUrl && OPOSICIONES.some((o) => o.id === oposicionUrl)
    ? oposicionUrl
    : obtenerOposicionActual();
  actualizarEtiquetaOposicion();
  selectorOposicion.addEventListener("change", () => {
    establecerOposicionActual(selectorOposicion.value);
    actualizarEtiquetaOposicion();
    marcarPlanActual();
  });
  document.getElementById("selector-oposicion-cambiar").addEventListener("click", () => {
    selectorOposicion.style.display = selectorOposicion.style.display === "none" ? "" : "none";
  });
}

function restaurarBotones() {
  document.querySelectorAll("[data-plan-btn]").forEach((boton) => {
    boton.disabled = false;
    boton.textContent = boton.dataset.planBtn === "basico" ? "Elegir Básico" : "Elegir Premium";
  });
}

// Aviso de prueba gratuita, con dos variantes según si hay sesión:
// "invitado" (crear cuenta) es la de siempre; "activar" es nueva -- el
// usuario ya tiene cuenta pero todavía no ha activado ESTA oposición
// concreta (ver perfil.oposicion_activada en registro_progreso_usuario.py),
// así que en vez de mandarlo directo a pagar se le ofrece primero su
// prueba gratuita de 7 días para ella (POST /activar-oposicion), igual que
// habría tenido si la hubiera elegido desde Zona opositor.
function mostrarCtaPrueba(modo, nombreOposicion) {
  if (modo === "ninguno") {
    ctaPrueba.style.display = "none";
    return;
  }
  ctaPrueba.style.display = "flex";
  if (modo === "invitado") {
    ctaPrueba.innerHTML = `
      <div class="cta-prueba-texto">
        <strong>Empieza gratis: 7 días de Premium sin tarjeta.</strong>
        <span>Crea tu cuenta y accede de inmediato a todas las herramientas. Sin compromiso.</span>
      </div>
      <a class="btn-plan btn-plan-primary" href="/login/?next=/planes/">Crear cuenta gratis</a>
    `;
    return;
  }
  ctaPrueba.innerHTML = `
    <div class="cta-prueba-texto">
      <strong>Empieza gratis: 7 días de Premium en ${nombreOposicion}, sin tarjeta.</strong>
      <span>Prueba todas las herramientas antes de elegir un plan. Sin compromiso.</span>
    </div>
    <button type="button" class="btn-plan btn-plan-primary" id="cta-prueba-activar">Empezar prueba gratis</button>
  `;
  document.getElementById("cta-prueba-activar").addEventListener("click", async (evento) => {
    const boton = evento.currentTarget;
    boton.disabled = true;
    boton.textContent = "Activando…";
    try {
      const token = await idToken();
      await activarOposicion(token, selectorOposicion.value);
      await marcarPlanActual();
    } catch (error) {
      mostrarErrorGlobal(error.message || "No se pudo activar la prueba gratuita.");
      boton.disabled = false;
      boton.textContent = "Empezar prueba gratis";
    }
  });
}

async function marcarPlanActual() {
  restaurarBotones();
  const usuario = await esperarUsuario();
  const oposicion = selectorOposicion.value;
  if (!usuario) {
    mostrarCtaPrueba("invitado");
    return;
  }
  establecerOposicionActual(oposicion);
  const perfil = await obtenerPlan(true, oposicion);
  const nombreOposicion = (OPOSICIONES.find((o) => o.id === oposicion) || {}).nombre || oposicion;
  mostrarCtaPrueba(perfil.oposicion_activada ? "ninguno" : "activar", nombreOposicion);
  document.querySelectorAll("[data-plan-btn]").forEach((boton) => {
    if (boton.dataset.planBtn === perfil.plan) {
      boton.textContent = "Tu plan actual";
      boton.disabled = true;
    }
  });
}

document.querySelectorAll("[data-plan-btn]").forEach((boton) => {
  boton.addEventListener("click", async () => {
    const plan = boton.dataset.planBtn;
    const oposicion = selectorOposicion.value;
    const usuario = await esperarUsuario();
    if (!usuario) {
      window.location.href = "/login/?next=/planes/";
      return;
    }
    boton.disabled = true;
    boton.textContent = "Redirigiendo al pago seguro…";
    try {
      const token = await idToken();
      const res = await fetch(`${BACKEND_URL}/crear-sesion-checkout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ plan, oposicion })
      });
      const datos = await res.json();
      if (!res.ok || !datos.url) {
        throw new Error(datos.error || "No se pudo iniciar el pago");
      }
      window.location.href = datos.url;
    } catch (error) {
      mostrarErrorGlobal(error.message || "No se pudo iniciar el pago. Inténtalo de nuevo.");
      boton.disabled = false;
      boton.textContent = plan === "basico" ? "Elegir Básico" : "Elegir Premium";
    }
  });
});

renderizarConfianza();
inicializarSelectorOposicion();
mostrarMensajeCheckout();
marcarPlanActual();
