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

const MENSAJES_RACHA = [
  { minimo: 0, texto: "Empieza hoy tu racha: haz un test o repasa algo para arrancar." },
  { minimo: 1, texto: "¡Buen comienzo! Vuelve mañana para no perder la racha." },
  { minimo: 3, texto: "Llevas varios días seguidos, ¡vas genial!" },
  { minimo: 7, texto: "¡Una semana entera estudiando! Imparable." },
  { minimo: 14, texto: "Dos semanas de constancia. Tu esfuerzo se nota." },
  { minimo: 30, texto: "¡Un mes seguido! Nivel opositor de verdad." },
  { minimo: 60, texto: "Una racha así solo la consigue quien de verdad se lo toma en serio." }
];

function mensajeParaRacha(dias) {
  let elegido = MENSAJES_RACHA[0];
  for (const m of MENSAJES_RACHA) {
    if (dias >= m.minimo) elegido = m;
  }
  return elegido.texto;
}

async function cargarRacha() {
  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/mi-racha`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return;
    const { racha_actual, racha_maxima } = await res.json();
    document.getElementById("racha-numero").textContent = racha_actual;
    document.getElementById("racha-plural").textContent = racha_actual === 1 ? "" : "s";
    document.getElementById("racha-mensaje").textContent = mensajeParaRacha(racha_actual);
    document.getElementById("racha-icono").textContent = racha_actual > 0 ? "🔥" : "💤";
    if (racha_maxima > racha_actual) {
      const elMaxima = document.getElementById("racha-maxima");
      elMaxima.textContent = `Tu mejor racha: ${racha_maxima} día${racha_maxima === 1 ? "" : "s"}`;
      elMaxima.style.display = "block";
    }
  } catch (e) {
    console.error("Error cargando racha:", e);
  }
}

async function iniciar() {
  const usuario = await esperarUsuario();
  if (!usuario) {
    window.location.href = "/login/?next=/mi-cuenta/";
    return;
  }

  document.getElementById("cuenta-email").textContent = usuario.email || "";
  document.getElementById("cuenta-avatar").textContent = (usuario.email || "?").trim().charAt(0).toUpperCase();

  cargarRacha();

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

iniciar();
