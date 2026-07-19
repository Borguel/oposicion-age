import { auth, idToken, esperarUsuario, signOut } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { OPOSICIONES } from "/assets/oposicion.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";
import { fijarTexto } from "/assets/dom.js";
import { icono } from "/assets/icons.js";

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

function formatearFecha(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" });
}

function renderizarEstadoPrueba(pruebaActiva, pruebaFin, algunaDePago) {
  const contenedor = document.getElementById("cuenta-prueba");
  if (!pruebaFin || (!pruebaActiva && algunaDePago)) {
    contenedor.style.display = "none";
    return;
  }
  const fin = new Date(pruebaFin);
  const diasRestantes = Math.ceil((fin - new Date()) / (1000 * 60 * 60 * 24));
  contenedor.style.display = "block";
  if (pruebaActiva) {
    contenedor.className = "age-card cuenta-prueba cuenta-prueba-activa";
    contenedor.innerHTML = `
      <div class="cuenta-prueba-texto">
        <strong>Estás en tu prueba gratuita Premium</strong>
        <p>Te ${diasRestantes === 1 ? "queda 1 día" : `quedan ${diasRestantes} días`}, hasta el ${formatearFecha(pruebaFin)}. Elige un plan antes de que termine para no perder el acceso.</p>
      </div>
      <a href="/planes/" class="age-btn age-btn-primary">Ver planes</a>
    `;
  } else {
    contenedor.className = "age-card cuenta-prueba cuenta-prueba-terminada";
    contenedor.innerHTML = `
      <div class="cuenta-prueba-texto">
        <strong>Tu prueba gratuita ha terminado</strong>
        <p>Terminó el ${formatearFecha(pruebaFin)}. Elige un plan para seguir usando Domina tu Opo; tus datos y tests ya hechos siguen a salvo.</p>
      </div>
      <a href="/planes/" class="age-btn age-btn-primary">Ver planes</a>
    `;
  }
}

function renderizarOposiciones() {
  const contenedorOposiciones = document.getElementById("cuenta-oposiciones");
  contenedorOposiciones.innerHTML = "";
  let algunaDePago = false;
  OPOSICIONES.forEach((op) => {
    const sub = suscripcionesActuales[op.id] || {};
    const plan = sub.plan || "gratis";
    if (plan !== "gratis") algunaDePago = true;
    const estadoTexto = sub.subscription_status ? ESTADOS_LEGIBLES[sub.subscription_status] || sub.subscription_status : "";

    let accionesHtml = "";
    if (plan !== "gratis") {
      const fechaRenovacion = sub.current_period_end ? formatearFecha(sub.current_period_end) : "";
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

    const fila = document.createElement("div");
    fila.className = "cuenta-oposicion-fila";
    fila.innerHTML = `
      <div class="cuenta-oposicion-fila-top">
        <div class="cuenta-oposicion-info">
          <span class="cuenta-oposicion-nombre">${op.nombre}</span>
          ${estadoTexto ? `<span class="cuenta-oposicion-estado">Suscripción ${estadoTexto}</span>` : ""}
        </div>
        <span class="${PILL_PLAN[plan] || "age-pill"}">${plan}</span>
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

// Accesibilidad compartida por los modales de esta página (cancelar
// suscripción / eliminar cuenta): Escape cierra (con el botón "seguro" que
// se le indique), el foco no se escapa del modal mientras está abierto
// (Tab/Shift+Tab), y al cerrarlo el foco vuelve a donde estaba antes de
// abrirlo -- igual que ya hace el modal genérico del panel de admin.
function activarAccesibilidadModal(modal, botonCerrarSeguro) {
  let elementoPrevio = null;
  function estaAbierto() { return modal.style.display !== "none" && modal.style.display !== ""; }
  function focables() {
    return Array.from(modal.querySelectorAll('input, select, textarea, button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'));
  }
  document.addEventListener("keydown", (e) => {
    if (!estaAbierto()) return;
    if (e.key === "Escape") { botonCerrarSeguro.click(); return; }
    if (e.key !== "Tab") return;
    const els = focables();
    if (!els.length) return;
    const primero = els[0];
    const ultimo = els[els.length - 1];
    if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
    else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
  });
  return {
    alAbrir() { elementoPrevio = document.activeElement; modal.querySelector('[tabindex="-1"]')?.focus(); },
    alCerrar() { elementoPrevio?.focus(); elementoPrevio = null; },
  };
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

  fijarTexto("cuenta-email", usuario.email || "");
  fijarTexto("cuenta-avatar", (usuario.email || "?").trim().charAt(0).toUpperCase());

  const { nombre, apellidos, telefono, direccion, suscripciones, prueba_activa, prueba_fin } = await obtenerPlan(true);
  suscripcionesActuales = suscripciones || {};
  const algunaDePago = renderizarOposiciones();
  renderizarEstadoPrueba(prueba_activa, prueba_fin, algunaDePago);

  fijarTexto("resumen-nombre", nombre || "—");
  fijarTexto("resumen-apellidos", apellidos || "—");
  fijarTexto("resumen-telefono", telefono || "—");
  fijarTexto("resumen-email", usuario.email || "—");
  fijarTexto("resumen-direccion", direccion || "—");

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
      btnPortal.textContent = "Gestionar suscripción";
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
