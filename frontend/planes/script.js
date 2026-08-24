import { idToken, esperarUsuario } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { OPOSICIONES, establecerOposicionActual, activarOposicion } from "/assets/oposicion.js";
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

// Bug real (23/08/2026): el banner de promoción (assets/auth.js) anuncia
// el descuento en toda la web, incluida esta propia página, pero las
// tarjetas de precio de aquí seguían mostrando siempre el precio íntegro
// -- el descuento solo se veía ya dentro del checkout de Stripe, después
// de pulsar "Elegir plan". Reutiliza el mismo data-precio-base ya escrito
// en el HTML (el precio de fábrica de cada tarjeta) para calcular el
// precio final a partir de descuento_pct, sin duplicar el precio en JS.
async function aplicarDescuentoVisual() {
  let promo;
  try {
    const resp = await fetch(`${BACKEND_URL}/promocion-activa`);
    if (!resp.ok) return;
    promo = await resp.json();
  } catch (e) { return; }
  if (!promo.activo || !promo.plan || !promo.descuento_pct) return;
  const elemento = document.getElementById(`plan-precio-${promo.plan}`);
  if (!elemento) return;
  const precioBase = parseFloat(elemento.dataset.precioBase);
  if (!precioBase) return;
  const precioFinal = (precioBase * (1 - promo.descuento_pct / 100)).toFixed(2).replace(".", ",");
  const precioBaseTexto = precioBase.toFixed(2).replace(".", ",");
  elemento.innerHTML = `<span class="plan-precio-original">${precioBaseTexto} €</span>${precioFinal} €<span class="plan-precio-periodo">/mes</span>`;
  if (promo.duracion_texto) {
    const duracion = document.createElement("span");
    duracion.className = "plan-precio-duracion";
    duracion.textContent = promo.duracion_texto;
    elemento.appendChild(duracion);
  }
  // Mismo precio con descuento en la tabla comparativa de abajo -- sin
  // tachado ahí (la celda ya es compacta), solo el precio real.
  const celdaTabla = document.getElementById(`tabla-precio-${promo.plan}`);
  if (celdaTabla) celdaTabla.textContent = `${precioFinal} €/mes`;
}

// El selector de oposición NO viene preseleccionado por defecto (17/08/2026,
// a petición explícita del usuario: "que no venga seleccionada ninguna
// oposición... si le da a suscribirse que le salga un aviso de que tiene
// que elegirla primero") -- a diferencia del resto de la web, /planes ya no
// asume la oposición "actual" (obtenerOposicionActual()) como punto de
// partida, precisamente porque aquí se decide en qué oposición gastar
// dinero de verdad, y no conviene que quede implícito. Mientras no hay
// ninguna elegida se muestra el <select> directamente, con una opción
// vacía de partida; en cuanto se elige una, se colapsa al texto fijo +
// enlace "Cambiar" de siempre.
function actualizarEtiquetaOposicion() {
  const valor = selectorOposicion.value;
  const textoFijo = document.getElementById("selector-oposicion-actual");
  const botonCambiar = document.getElementById("selector-oposicion-cambiar");
  if (!valor) {
    textoFijo.textContent = "";
    textoFijo.style.display = "none";
    botonCambiar.style.display = "none";
    selectorOposicion.style.display = "";
    return;
  }
  const actual = OPOSICIONES.find((o) => o.id === valor);
  textoFijo.textContent = actual ? actual.nombre : valor;
  textoFijo.style.display = "";
  botonCambiar.style.display = "";
  selectorOposicion.style.display = "none";
}

function inicializarSelectorOposicion() {
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Selecciona tu oposición";
  placeholder.disabled = true;
  selectorOposicion.appendChild(placeholder);
  OPOSICIONES.forEach((o) => {
    const opcion = document.createElement("option");
    opcion.value = o.id;
    opcion.textContent = o.nombre;
    selectorOposicion.appendChild(opcion);
  });
  // Solo se respeta un ?oposicion= explícito en la URL (p. ej. un enlace
  // "Mejorar de plan" desde Zona Opositor, que sí sabe para cuál) -- nunca
  // obtenerOposicionActual() como relleno automático.
  const params = new URLSearchParams(window.location.search);
  const oposicionUrl = params.get("oposicion");
  selectorOposicion.value = oposicionUrl && OPOSICIONES.some((o) => o.id === oposicionUrl) ? oposicionUrl : "";
  actualizarEtiquetaOposicion();
  selectorOposicion.addEventListener("change", () => {
    if (selectorOposicion.value) establecerOposicionActual(selectorOposicion.value);
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
  if (!oposicion) {
    // Sin oposición elegida todavía no se puede saber ni el plan actual ni
    // la prueba gratuita de NINGUNA en concreto -- se oculta el aviso
    // hasta que se elija (el aviso real llega al pulsar "Elegir
    // Básico/Premium", ver más abajo).
    mostrarCtaPrueba("ninguno");
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
    } else if (perfil.plan !== "gratis") {
      // Ya paga un plan distinto en esta oposición: pulsar el otro botón
      // sustituye esa suscripción por una nueva (ver /crear-sesion-checkout
      // y el webhook checkout.session.completed, que cancela la anterior en
      // cuanto la nueva queda confirmada) -- el texto debe dejar claro que
      // es un CAMBIO de plan, no una alta nueva independiente.
      boton.textContent = `Cambiar a ${boton.dataset.planBtn === "basico" ? "Básico" : "Premium"}`;
    }
  });
}

document.querySelectorAll("[data-plan-btn]").forEach((boton) => {
  boton.addEventListener("click", async () => {
    const plan = boton.dataset.planBtn;
    const oposicion = selectorOposicion.value;
    if (!oposicion) {
      mostrarErrorGlobal("Elige primero la oposición para la que quieres estudiar.");
      selectorOposicion.style.display = "";
      selectorOposicion.focus();
      return;
    }
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
      // marcarPlanActual() en vez de un texto fijo -- si esto era un cambio
      // de plan (no una alta nueva) el botón debe volver a "Cambiar a X",
      // no a "Elegir X" como si nunca hubiera tenido ningún plan.
      await marcarPlanActual();
    }
  });
});

renderizarConfianza();
inicializarSelectorOposicion();
mostrarMensajeCheckout();
marcarPlanActual();
aplicarDescuentoVisual();
