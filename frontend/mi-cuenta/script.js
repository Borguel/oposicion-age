import { auth, idToken, esperarUsuario, signOut } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { OPOSICIONES } from "/assets/oposicion.js";

const ESTADOS_LEGIBLES = {
  active: "activa",
  trialing: "en periodo de prueba",
  past_due: "pago pendiente",
  canceled: "cancelada",
  incomplete: "pago incompleto",
  incomplete_expired: "pago incompleto (caducado)",
  unpaid: "impagada"
};

async function iniciar() {
  const usuario = await esperarUsuario();
  if (!usuario) {
    window.location.href = "/login/?next=/mi-cuenta/";
    return;
  }

  document.getElementById("cuenta-email").textContent = usuario.email || "";
  document.getElementById("cuenta-avatar").textContent = (usuario.email || "?").trim().charAt(0).toUpperCase();

  const { nombre, apellidos, telefono, direccion, suscripciones } = await obtenerPlan(true);

  const PILL_PLAN = { gratis: "age-pill", basico: "age-pill age-pill-primary", premium: "age-pill age-pill-success" };

  const contenedorOposiciones = document.getElementById("cuenta-oposiciones");
  contenedorOposiciones.innerHTML = "";
  let algunaDePago = false;
  OPOSICIONES.forEach((op) => {
    const sub = (suscripciones || {})[op.id] || {};
    const plan = sub.plan || "gratis";
    if (plan !== "gratis") algunaDePago = true;
    const estadoTexto = sub.subscription_status ? ESTADOS_LEGIBLES[sub.subscription_status] || sub.subscription_status : "";
    const fila = document.createElement("div");
    fila.className = "cuenta-oposicion-fila";
    fila.innerHTML = `
      <div class="cuenta-oposicion-info">
        <span class="cuenta-oposicion-nombre">${op.nombre}</span>
        ${estadoTexto ? `<span class="cuenta-oposicion-estado">Suscripción ${estadoTexto}</span>` : ""}
      </div>
      <span class="${PILL_PLAN[plan] || "age-pill"}">${plan}</span>
    `;
    contenedorOposiciones.appendChild(fila);
  });

  document.getElementById("resumen-nombre").textContent = nombre || "—";
  document.getElementById("resumen-apellidos").textContent = apellidos || "—";
  document.getElementById("resumen-telefono").textContent = telefono || "—";
  document.getElementById("resumen-email").textContent = usuario.email || "—";
  document.getElementById("resumen-direccion").textContent = direccion || "—";

  const btnPortal = document.getElementById("btn-portal");
  if (!algunaDePago) {
    btnPortal.textContent = "Sin suscripciones activas";
    btnPortal.disabled = true;
  }
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
      alert(error.message);
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
    alert(error.message || "No se pudieron exportar tus datos.");
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
