import { auth, idToken, esperarUsuario, marcarContenidoListo, signOut } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { OPOSICIONES } from "/assets/oposicion.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";
import { fijarTexto } from "/assets/dom.js";
import { icono } from "/assets/icons.js";
import { activarAccesibilidadModal } from "/assets/modal-accesible.js";

document.querySelectorAll("[data-icon]").forEach((el) => {
  el.innerHTML = icono(el.dataset.icon, Number(el.dataset.iconSize || 24));
});

const ESTADOS_LEGIBLES = {
  active: "activa",
  trialing: "en periodo de prueba",
  past_due: "pago pendiente",
  canceled: "cancelada",
  incomplete: "pago incompleto",
  incomplete_expired: "pago incompleto (caducado)",
  unpaid: "impagada"
};

const PILL_PLAN = { gratis: "age-pill", basico: "age-pill age-pill-primary", premium: "age-pill age-pill-success" };

// Datos de suscripciones ya cargados, para poder re-pintar las filas tras
// cancelar/reactivar sin tener que volver a pedir todo el perfil al backend.
let suscripcionesActuales = {};

// Bug real (23/08/2026): el checkout de Stripe redirige tras pagar a
// /mi-cuenta/?checkout=success (ver success_url en
// blueprints/pagos.py:crear_sesion_checkout), pero el aviso de "¡Pago
// completado!" solo se pintaba en /planes/ -- el usuario aterrizaba aquí
// sin ningún mensaje que confirmara que el pago se había procesado. Solo
// se comprueba "success": cancel_url apunta a /planes/, así que ?checkout=
// cancel nunca llega a esta página.
function mostrarMensajeCheckout() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("checkout") !== "success") return;
  const elemento = document.getElementById("mensaje-checkout");
  if (!elemento) return;
  elemento.textContent = "¡Pago completado! Puede tardar unos segundos en activarse tu nuevo plan.";
  elemento.className = "mensaje-checkout ok";
  elemento.style.display = "block";
}

function formatearFecha(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" });
}

// Antes había una única tarjeta "Estás en tu prueba gratuita" / "Tu prueba
// ha terminado" a nivel de CUENTA (resumen_prueba_cuenta: "en prueba" si
// CUALQUIER oposición sigue en prueba). Con más de una oposición activada
// eso escondía casos reales: si AGE seguía en prueba pero GACE ya estaba
// bloqueada por no haber pagado, la tarjeta solo hablaba de AGE ("te
// quedan 3 días") y GACE se veía en la lista de abajo exactamente igual
// que una oposición nunca activada (pastilla gris "gratis", sin aviso ni
// botón) -- no había forma de enterarse de que esa oposición necesitaba un
// plan. Se sustituye por el aviso propio de CADA fila en
// renderizarOposiciones, que sí conoce el estado real de esa oposición
// concreta.
function renderizarOposiciones() {
  const contenedorOposiciones = document.getElementById("cuenta-oposiciones");
  contenedorOposiciones.innerHTML = "";
  let algunaDePago = false;
  OPOSICIONES.forEach((op) => {
    const sub = suscripcionesActuales[op.id] || {};
    const activada = Object.keys(sub).length > 0;
    const plan = sub.plan || "gratis";
    if (plan !== "gratis") algunaDePago = true;
    const estadoTexto = sub.subscription_status ? ESTADOS_LEGIBLES[sub.subscription_status] || sub.subscription_status : "";

    let pillClase = "age-pill";
    let pillTexto = plan;
    let accionesHtml = "";

    if (plan !== "gratis") {
      pillClase = PILL_PLAN[plan] || "age-pill";
      const fechaRenovacion = sub.current_period_end ? formatearFecha(sub.current_period_end) : "";
      if (sub.subscription_status === "past_due") {
        // Bug real (24/08/2026): Stripe ya marca aquí que el último cobro
        // falló (tarjeta caducada, fondos insuficientes...), y el dato
        // llegaba hasta "Suscripción pago pendiente" en la etiqueta de
        // estado -- pero la fila seguía mostrando la próxima renovación
        // como si nada, sin ningún botón que llevara directamente a
        // arreglarlo. Solo existía el botón genérico de arriba
        // ("Gestionar facturación"), que no deja claro que ESTA
        // oposición concreta tiene un problema real. Reutiliza el mismo
        // portal de Stripe (/crear-sesion-portal) que ese botón, desde
        // un aviso explícito en la propia fila.
        accionesHtml = `<div class="cuenta-oposicion-baja-info cuenta-oposicion-baja-info-aviso">
             <span class="cuenta-oposicion-baja-texto">No hemos podido cobrar tu último pago. Actualiza tu método de pago para no perder el acceso a este plan.</span>
             <button type="button" class="age-btn age-btn-primary" data-accion="actualizar-pago" data-oposicion="${op.id}">Actualizar método de pago</button>
           </div>`;
      } else {
        accionesHtml = sub.cancelar_al_final_periodo
          ? `<div class="cuenta-oposicion-baja-info cuenta-oposicion-baja-info-aviso">
               <span class="cuenta-oposicion-baja-texto">
                 ${fechaRenovacion
                   ? `Tendrás acceso hasta el <strong>${fechaRenovacion}</strong>. Si no reactivas antes de esa fecha, perderás el acceso a este plan.`
                   : "Tu suscripción se cancelará al final del periodo ya pagado."}
               </span>
               <button type="button" class="age-btn age-btn-primary cuenta-btn-reactivar" data-accion="reactivar" data-oposicion="${op.id}">Reactivar suscripción</button>
             </div>`
          : `<div class="cuenta-oposicion-baja-info">
               <span class="cuenta-oposicion-baja-texto">${fechaRenovacion ? `Próxima renovación: <strong>${fechaRenovacion}</strong>` : ""}</span>
               <button type="button" class="cuenta-btn-link cuenta-btn-link-danger" data-accion="cancelar" data-oposicion="${op.id}">Cancelar suscripción</button>
             </div>`;
      }
    } else if (!activada) {
      pillTexto = "sin activar";
      accionesHtml = `<div class="cuenta-oposicion-baja-info">
        <span class="cuenta-oposicion-baja-texto">Todavía no la has empezado.</span>
        <a href="/zona-opositor/" class="age-btn age-btn-outline">Empezar prueba gratis</a>
      </div>`;
    } else if (!sub.prueba_fin) {
      // Activada pero con el correo todavía sin confirmar: la prueba
      // arranca en cuanto lo confirme (ver activar_oposicion_usuario en
      // registro_progreso_usuario.py) -- no puede haber "terminado" algo
      // que nunca llegó a empezar.
      pillTexto = "pendiente";
      accionesHtml = `<div class="cuenta-oposicion-baja-info">
        <span class="cuenta-oposicion-baja-texto">Confirma tu correo electrónico para activar tu prueba gratuita de 7 días.</span>
      </div>`;
    } else if (new Date(sub.prueba_fin) > new Date()) {
      pillClase = "age-pill age-pill-primary";
      pillTexto = "prueba";
      const dias = Math.max(0, Math.ceil((new Date(sub.prueba_fin) - new Date()) / (1000 * 60 * 60 * 24)));
      accionesHtml = `<div class="cuenta-oposicion-baja-info cuenta-oposicion-baja-info-aviso">
        <span class="cuenta-oposicion-baja-texto">Te ${dias === 1 ? "queda 1 día" : `quedan ${dias} días`} de prueba gratuita, hasta el ${formatearFecha(sub.prueba_fin)}.</span>
        <a href="/planes/" class="age-btn age-btn-outline">Ver planes</a>
      </div>`;
    } else {
      // Prueba terminada: dos motivos muy distintos pueden llevar aquí --
      // nunca se llegó a pagar, o SÍ fue cliente de pago y la suscripción
      // se canceló o dejó de cobrarse. stripe_subscription_id solo se
      // guarda al completar un checkout real y ningún flujo lo borra
      // después, así que su presencia distingue de forma fiable ambos
      // casos (mismo criterio que assets/plan.js y assets/auth.js).
      pillClase = "age-pill age-pill-danger";
      pillTexto = "bloqueada";
      const texto = sub.stripe_subscription_id
        ? "Tu suscripción a esta oposición se canceló o dejó de cobrarse. Suscríbete de nuevo para recuperar el acceso."
        : `Tu prueba gratuita terminó el ${formatearFecha(sub.prueba_fin)}. Elige un plan para volver a acceder a esta oposición.`;
      accionesHtml = `<div class="cuenta-oposicion-baja-info cuenta-oposicion-baja-info-aviso">
        <span class="cuenta-oposicion-baja-texto">${texto}</span>
        <a href="/planes/" class="age-btn age-btn-primary">Ver planes</a>
      </div>`;
    }

    const fila = document.createElement("div");
    fila.className = "cuenta-oposicion-fila";
    fila.innerHTML = `
      <div class="cuenta-oposicion-fila-top">
        <div class="cuenta-oposicion-info">
          <span class="cuenta-oposicion-nombre">${op.nombre}</span>
          ${estadoTexto ? `<span class="cuenta-oposicion-estado">Suscripción ${estadoTexto}</span>` : ""}
        </div>
        <span class="${pillClase}">${pillTexto}</span>
      </div>
      ${accionesHtml}
    `;
    contenedorOposiciones.appendChild(fila);
  });

  const btnPortal = document.getElementById("btn-portal");
  btnPortal.disabled = !algunaDePago;
  btnPortal.textContent = algunaDePago ? "Gestionar facturación y suscripciones" : "Sin suscripciones activas";
  return algunaDePago;
}

let oposicionParaCancelar = null;
const modalCancelar = document.getElementById("modal-cancelar-suscripcion");
const listaMotivos = document.getElementById("cancelar-motivos-lista");
const campoComentario = document.getElementById("cancelar-comentario");
const btnConfirmarCancelar = document.getElementById("btn-confirmar-cancelar");
const cancelarMensajeError = document.getElementById("cancelar-mensaje-error");
const a11yModalCancelar = activarAccesibilidadModal(modalCancelar, document.getElementById("btn-seguir-con-plan"));

function abrirModalCancelar(oposicionId) {
  oposicionParaCancelar = oposicionId;
  listaMotivos.querySelectorAll('input[name="motivo-baja"]').forEach((r) => (r.checked = false));
  campoComentario.value = "";
  btnConfirmarCancelar.disabled = true;
  cancelarMensajeError.style.display = "none";
  btnConfirmarCancelar.textContent = "Cancelar mi suscripción";
  modalCancelar.style.display = "flex";
  a11yModalCancelar.alAbrir();
}

listaMotivos.addEventListener("change", () => {
  btnConfirmarCancelar.disabled = !listaMotivos.querySelector('input[name="motivo-baja"]:checked');
});

document.getElementById("btn-seguir-con-plan").addEventListener("click", () => {
  modalCancelar.style.display = "none";
  a11yModalCancelar.alCerrar();
});

btnConfirmarCancelar.addEventListener("click", async () => {
  const motivoElegido = listaMotivos.querySelector('input[name="motivo-baja"]:checked');
  if (!motivoElegido || !oposicionParaCancelar) return;
  btnConfirmarCancelar.disabled = true;
  btnConfirmarCancelar.textContent = "Cancelando…";
  cancelarMensajeError.style.display = "none";
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/cancelar-suscripcion`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ oposicion: oposicionParaCancelar, motivo: motivoElegido.value, comentario: campoComentario.value })
    });
    const datos = await res.json();
    if (!res.ok) throw new Error(datos.error || "No se pudo cancelar la suscripción.");
    suscripcionesActuales[oposicionParaCancelar] = {
      ...(suscripcionesActuales[oposicionParaCancelar] || {}),
      cancelar_al_final_periodo: true,
      current_period_end: datos.current_period_end
    };
    renderizarOposiciones();
    modalCancelar.style.display = "none";
    a11yModalCancelar.alCerrar();
  } catch (error) {
    cancelarMensajeError.textContent = error.message || "No se pudo cancelar la suscripción.";
    cancelarMensajeError.style.display = "block";
    btnConfirmarCancelar.disabled = false;
    btnConfirmarCancelar.textContent = "Cancelar mi suscripción";
  }
});

document.getElementById("cuenta-oposiciones").addEventListener("click", async (evento) => {
  const boton = evento.target.closest("button[data-accion]");
  if (!boton) return;
  const oposicionId = boton.dataset.oposicion;
  if (boton.dataset.accion === "cancelar") {
    abrirModalCancelar(oposicionId);
    return;
  }
  if (boton.dataset.accion === "actualizar-pago") {
    boton.disabled = true;
    boton.textContent = "Redirigiendo…";
    try {
      const token = await idToken();
      const res = await fetch(`${BACKEND_URL}/crear-sesion-portal`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` }
      });
      const datos = await res.json();
      if (!res.ok || !datos.url) throw new Error(datos.error || "No se pudo abrir la gestión de la suscripción");
      window.location.href = datos.url;
    } catch (error) {
      mostrarErrorGlobal(error.message || "No se pudo abrir la gestión de la suscripción.");
      boton.disabled = false;
      boton.textContent = "Actualizar método de pago";
    }
    return;
  }
  if (boton.dataset.accion === "reactivar") {
    boton.disabled = true;
    boton.textContent = "Reactivando…";
    try {
      const token = await idToken();
      const res = await fetch(`${BACKEND_URL}/reactivar-suscripcion`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ oposicion: oposicionId })
      });
      const datos = await res.json();
      if (!res.ok) throw new Error(datos.error || "No se pudo reactivar la suscripción.");
      suscripcionesActuales[oposicionId] = { ...(suscripcionesActuales[oposicionId] || {}), cancelar_al_final_periodo: false };
      renderizarOposiciones();
    } catch (error) {
      mostrarErrorGlobal(error.message || "No se pudo reactivar la suscripción.");
      boton.disabled = false;
      boton.textContent = "Reactivar suscripción";
    }
  }
});

async function iniciar() {
  const usuario = await esperarUsuario();
  if (!usuario) {
    window.location.href = "/login/?next=/mi-cuenta/";
    return;
  }

  mostrarMensajeCheckout();
  fijarTexto("cuenta-email", usuario.email || "");
  fijarTexto("cuenta-avatar", (usuario.email || "?").trim().charAt(0).toUpperCase());

  const { nombre, apellidos, telefono, direccion, suscripciones } = await obtenerPlan(true);
  suscripcionesActuales = suscripciones || {};
  renderizarOposiciones();

  fijarTexto("resumen-nombre", nombre || "—");
  fijarTexto("resumen-apellidos", apellidos || "—");
  fijarTexto("resumen-telefono", telefono || "—");
  fijarTexto("resumen-email", usuario.email || "—");
  fijarTexto("resumen-direccion", direccion || "—");
  marcarContenidoListo();

  const btnPortal = document.getElementById("btn-portal");
  btnPortal.addEventListener("click", async () => {
    btnPortal.disabled = true;
    btnPortal.textContent = "Redirigiendo…";
    try {
      const token = await idToken();
      const res = await fetch(`${BACKEND_URL}/crear-sesion-portal`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` }
      });
      const datos = await res.json();
      if (!res.ok || !datos.url) {
        throw new Error(datos.error || "No se pudo abrir la gestión de la suscripción");
      }
      window.location.href = datos.url;
    } catch (error) {
      mostrarErrorGlobal(error.message);
      btnPortal.disabled = false;
      // Solo se llega aquí con el botón habilitado (algunaDePago), así que
      // este es siempre el texto correcto al que volver (ver
      // renderizarOposiciones), no un texto distinto inventado aquí.
      btnPortal.textContent = "Gestionar facturación y suscripciones";
    }
  });
}

document.getElementById("btn-logout").addEventListener("click", async () => {
  await signOut();
  window.location.href = "/";
});

document.getElementById("btn-exportar-datos").addEventListener("click", async (evento) => {
  const boton = evento.currentTarget;
  boton.disabled = true;
  boton.textContent = "Preparando descarga…";
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mi-cuenta/exportar-datos`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error("No se pudieron exportar tus datos.");
    const datos = await res.json();
    const blob = new Blob([JSON.stringify(datos, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement("a");
    enlace.href = url;
    enlace.download = "mis-datos-oposicion-age.json";
    enlace.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    mostrarErrorGlobal(error.message || "No se pudieron exportar tus datos.");
  } finally {
    boton.disabled = false;
    boton.innerHTML = `${icono("descargar", 16)} Descargar mis datos`;
  }
});

// Eliminar cuenta: exige escribir "ELIMINAR" a propósito -- es una acción
// destructiva e irreversible (borra Firestore y la cuenta de Firebase Auth,
// y cancela cualquier suscripción de Stripe activa), así que no basta con
// un solo clic.
const modalEliminar = document.getElementById("modal-eliminar-cuenta");
const campoConfirmar = document.getElementById("campo-confirmar-eliminar");
const btnConfirmarEliminar = document.getElementById("btn-confirmar-eliminar");
const eliminarMensajeError = document.getElementById("eliminar-mensaje-error");
const a11yModalEliminar = activarAccesibilidadModal(modalEliminar, document.getElementById("btn-cancelar-eliminar"));

document.getElementById("btn-eliminar-cuenta").addEventListener("click", () => {
  campoConfirmar.value = "";
  btnConfirmarEliminar.disabled = true;
  eliminarMensajeError.style.display = "none";
  modalEliminar.style.display = "flex";
  a11yModalEliminar.alAbrir();
});

document.getElementById("btn-cancelar-eliminar").addEventListener("click", () => {
  modalEliminar.style.display = "none";
  a11yModalEliminar.alCerrar();
});

campoConfirmar.addEventListener("input", () => {
  btnConfirmarEliminar.disabled = campoConfirmar.value.trim() !== "ELIMINAR";
});

btnConfirmarEliminar.addEventListener("click", async () => {
  btnConfirmarEliminar.disabled = true;
  btnConfirmarEliminar.textContent = "Eliminando…";
  eliminarMensajeError.style.display = "none";
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mi-cuenta`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error("No se pudo eliminar tu cuenta. Inténtalo de nuevo.");
    await signOut();
    window.location.href = "/";
  } catch (error) {
    eliminarMensajeError.textContent = error.message || "No se pudo eliminar tu cuenta. Inténtalo de nuevo.";
    eliminarMensajeError.style.display = "block";
    btnConfirmarEliminar.disabled = false;
    btnConfirmarEliminar.textContent = "Eliminar mi cuenta para siempre";
  }
});

const btnContacto = document.getElementById("btn-enviar-contacto");
const campoContacto = document.getElementById("contacto-mensaje");
const feedbackContacto = document.getElementById("contacto-mensaje-feedback");

btnContacto.addEventListener("click", async () => {
  const mensaje = campoContacto.value.trim();
  feedbackContacto.style.display = "none";
  if (!mensaje) {
    feedbackContacto.className = "datos-mensaje error";
    feedbackContacto.textContent = "Escribe tu consulta antes de enviarla.";
    feedbackContacto.style.display = "block";
    return;
  }
  btnContacto.disabled = true;
  btnContacto.textContent = "Enviando…";
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mi-cuenta/contactar`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ mensaje })
    });
    const datos = await res.json();
    if (!res.ok) throw new Error(datos.error || "No se pudo enviar tu mensaje.");
    feedbackContacto.className = "datos-mensaje ok";
    feedbackContacto.textContent = datos.mensaje || "Mensaje enviado.";
    feedbackContacto.style.display = "block";
    campoContacto.value = "";
  } catch (error) {
    feedbackContacto.className = "datos-mensaje error";
    feedbackContacto.textContent = error.message || "No se pudo enviar tu mensaje.";
    feedbackContacto.style.display = "block";
  } finally {
    btnContacto.disabled = false;
    btnContacto.textContent = "Enviar mensaje";
  }
});

iniciar();
