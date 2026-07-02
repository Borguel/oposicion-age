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

async function iniciar() {
  const usuario = await esperarUsuario();
  if (!usuario) {
    window.location.href = "/login/?next=/mi-cuenta/";
    return;
  }

  document.getElementById("cuenta-email").textContent = usuario.email || "";

  const { plan, subscription_status } = await obtenerPlan(true);
  document.getElementById("cuenta-plan-nombre").textContent = plan;
  const estadoTexto = subscription_status ? ESTADOS_LEGIBLES[subscription_status] || subscription_status : "";
  document.getElementById("cuenta-plan-estado").textContent = estadoTexto ? `Suscripción ${estadoTexto}` : "";

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

document.getElementById("btn-logout").addEventListener("click", async () => {
  await signOut();
  window.location.href = "/";
});

iniciar();
