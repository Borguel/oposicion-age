import { idToken, esperarUsuario } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

const mensajeCheckout = document.getElementById("mensaje-checkout");

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

async function marcarPlanActual() {
  const usuario = await esperarUsuario();
  if (!usuario) return;
  const { plan } = await obtenerPlan(true);
  document.querySelectorAll("[data-plan-btn]").forEach((boton) => {
    if (boton.dataset.planBtn === plan) {
      boton.textContent = "Tu plan actual";
      boton.disabled = true;
    }
  });
}

document.querySelectorAll("[data-plan-btn]").forEach((boton) => {
  boton.addEventListener("click", async () => {
    const plan = boton.dataset.planBtn;
    const usuario = await esperarUsuario();
    if (!usuario) {
      window.location.href = "/login/?next=/planes/";
      return;
    }
    if (plan === "gratis") {
      window.location.href = "/";
      return;
    }
    boton.disabled = true;
    boton.textContent = "Redirigiendo a Stripe…";
    try {
      const token = await idToken();
      const res = await fetch(`${BACKEND_URL}/crear-sesion-checkout`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({ plan })
      });
      const datos = await res.json();
      if (!res.ok || !datos.url) {
        throw new Error(datos.error || "No se pudo iniciar el pago");
      }
      window.location.href = datos.url;
    } catch (error) {
      alert(error.message || "No se pudo iniciar el pago. Inténtalo de nuevo.");
      boton.disabled = false;
      boton.textContent = plan === "basico" ? "Elegir Básico" : "Elegir Premium";
    }
  });
});

mostrarMensajeCheckout();
marcarPlanActual();
