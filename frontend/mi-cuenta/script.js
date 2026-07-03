import { auth, idToken, esperarUsuario, signOut } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

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

  const { plan, subscription_status, nombre, apellidos, telefono, direccion } = await obtenerPlan(true);
  document.getElementById("cuenta-plan-nombre").textContent = plan;
  const estadoTexto = subscription_status ? ESTADOS_LEGIBLES[subscription_status] || subscription_status : "";
  document.getElementById("cuenta-plan-estado").textContent = estadoTexto ? `Suscripción ${estadoTexto}` : "";

  document.getElementById("datos-nombre").value = nombre || "";
  document.getElementById("datos-apellidos").value = apellidos || "";
  document.getElementById("datos-telefono").value = telefono || "";
  document.getElementById("datos-direccion").value = direccion || "";

  const btnPortal = document.getElementById("btn-portal");
  if (plan === "gratis") {
    btnPortal.textContent = "Sin suscripción activa";
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
    sessionStorage.removeItem("age_plan_cache");
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
