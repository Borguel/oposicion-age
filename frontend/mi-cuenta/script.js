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

const formDatos = document.getElementById("form-datos");
const datosMensaje = document.getElementById("datos-mensaje");
const btnGuardarDatos = document.getElementById("btn-guardar-datos");

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

  document.getElementById("datos-nombre").value = nombre || "";
  document.getElementById("datos-apellidos").value = apellidos || "";
  document.getElementById("datos-telefono").value = telefono || "";
  document.getElementById("datos-direccion").value = direccion || "";

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

formDatos.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  datosMensaje.style.display = "none";
  btnGuardarDatos.disabled = true;
  btnGuardarDatos.textContent = "Guardando…";

  const nombre = document.getElementById("datos-nombre").value.trim();
  const apellidos = document.getElementById("datos-apellidos").value.trim();
  const telefono = document.getElementById("datos-telefono").value.trim();
  const direccion = document.getElementById("datos-direccion").value.trim();

  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/registrar-usuario`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ nombre, apellidos, telefono, direccion })
    });
    if (!res.ok) throw new Error("No se pudieron guardar los cambios");
    sessionStorage.clear();
    datosMensaje.textContent = "Datos guardados correctamente.";
    datosMensaje.className = "datos-mensaje ok";
    datosMensaje.style.display = "block";
  } catch (error) {
    datosMensaje.textContent = error.message || "No se pudieron guardar los cambios.";
    datosMensaje.className = "datos-mensaje error";
    datosMensaje.style.display = "block";
  } finally {
    btnGuardarDatos.disabled = false;
    btnGuardarDatos.textContent = "Guardar cambios";
  }
});

document.getElementById("btn-logout").addEventListener("click", async () => {
  await signOut();
  window.location.href = "/";
});

iniciar();
