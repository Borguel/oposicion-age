import { auth, idToken, esperarUsuario, signOut } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { OPOSICIONES } from "/assets/oposicion.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";
import { fijarTexto } from "/assets/dom.js";

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
      accionesHtml = sub.cancelar_al_final_periodo
        ? `<div class="cuenta-oposicion-baja-info">
             <span class="cuenta-oposicion-baja-texto">Se cancelará el ${formatearFecha(sub.current_period_end)}</span>
             <button type="button" class="cuenta-btn-link" data-accion="reactivar" data-oposicion="${op.id}">Reactivar suscripción</button>
           </div>`
        : `<div class="cuenta-oposicion-baja-info">
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
}

let oposicionParaCancelar = null;
const modalCancelar = document.getElementById("modal-cancelar-suscripcion");
const listaMotivos = document.getElementById("cancelar-motivos-lista");
const campoComentario = document.getElementById("cancelar-comentario");
const btnConfirmarCancelar = document.getElementById("btn-confirmar-cancelar");
const cancelarMensajeError = document.getElementById("cancelar-mensaje-error");

function abrirModalCancelar(oposicionId) {
  oposicionParaCancelar = oposicionId;
  listaMotivos.querySelectorAll('input[name="motivo-baja"]').forEach((r) => (r.checked = false));
  campoComentario.value = "";
  btnConfirmarCancelar.disabled = true;
  cancelarMensajeError.style.display = "none";
  btnConfirmarCancelar.textContent = "Cancelar mi suscripción";
  modalCancelar.style.display = "flex";
}

listaMotivos.addEventListener("change", () => {
  btnConfirmarCancelar.disabled = !listaMotivos.querySelector('input[name="motivo-baja"]:checked');
});

document.getElementById("btn-seguir-con-plan").addEventListener("click", () => {
  modalCancelar.style.display = "none";
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

  const { nombre, apellidos, telefono, direccion, suscripciones } = await obtenerPlan(true);
  suscripcionesActuales = suscripciones || {};
  renderizarOposiciones();

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
    boton.textContent = "⬇️ Descargar mis datos";
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

document.getElementById("btn-eliminar-cuenta").addEventListener("click", () => {
  campoConfirmar.value = "";
  btnConfirmarEliminar.disabled = true;
  eliminarMensajeError.style.display = "none";
  modalEliminar.style.display = "flex";
});

document.getElementById("btn-cancelar-eliminar").addEventListener("click", () => {
  modalEliminar.style.display = "none";
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

iniciar();
