// Cuenta atrás hasta la fecha de examen configurada por el usuario
// (GET/POST /fecha-examen). Compartido por Zona Opositor y Estadísticas --
// ambas páginas incluyen el mismo bloque de marcado (mismos IDs) para que
// baste con llamar a inicializarCuentaAtras() en cada una, en vez de tener
// la misma lógica duplicada dos veces.
import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { obtenerOposicionActual } from "/assets/oposicion.js";
import { mostrarErrorGlobal } from "/assets/notificaciones.js";

export function formatearCuentaAtras(fechaISO) {
  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);
  const fechaExamen = new Date(`${fechaISO}T00:00:00`);
  const dias = Math.round((fechaExamen - hoy) / 86400000);
  if (dias > 1) return { numero: `${dias} días`, mensaje: "para tu examen" };
  if (dias === 1) return { numero: "Mañana", mensaje: "es tu examen. ¡Mucho ánimo!" };
  if (dias === 0) return { numero: "¡Hoy!", mensaje: "es el día de tu examen. ¡A por ello!" };
  return { numero: "Ya pasó", mensaje: "la fecha que configuraste" };
}

// Requiere que la página incluya el bloque con estos IDs: cuenta-atras-numero,
// cuenta-atras-mensaje, cuenta-atras-boton, cuenta-atras-form,
// cuenta-atras-input, cuenta-atras-quitar (ver zona-opositor/index.html).
//
// Zona Opositor puede llamar a esta función más de una vez en la misma
// carga de página (al cambiar de oposición con el selector, sin recargar)
// -- boton y form (input/quitar viven DENTRO de form, así que se clonan
// con él) se sustituyen por su propio clon antes de nada para que cada
// llamada parta de nodos sin listeners previos; si no, una segunda
// llamada dejaría dos listeners activos (el de la oposición anterior y el
// de la nueva) sobre los mismos botones, disparando ambos a la vez en
// cada clic.
export async function inicializarCuentaAtras() {
  const numeroEl = document.getElementById("cuenta-atras-numero");
  const mensajeEl = document.getElementById("cuenta-atras-mensaje");
  let boton = document.getElementById("cuenta-atras-boton");
  let form = document.getElementById("cuenta-atras-form");
  if (!numeroEl || !mensajeEl || !boton || !form) return;

  boton.replaceWith((boton = boton.cloneNode(true)));
  form.replaceWith((form = form.cloneNode(true)));
  const input = form.querySelector("#cuenta-atras-input");
  const quitar = form.querySelector("#cuenta-atras-quitar");
  if (!input || !quitar) return;

  const token = await idToken();
  const oposicion = obtenerOposicionActual();

  const pintar = (fecha) => {
    if (fecha) {
      const { numero, mensaje } = formatearCuentaAtras(fecha);
      numeroEl.textContent = numero;
      mensajeEl.textContent = mensaje;
      boton.textContent = "Cambiar fecha";
      quitar.style.display = "";
    } else {
      numeroEl.textContent = "—";
      mensajeEl.textContent = "Configura la fecha de tu examen para ver la cuenta atrás.";
      boton.textContent = "Configurar";
      quitar.style.display = "none";
    }
  };

  let fechaActual = null;
  try {
    const res = await fetch(`${BACKEND_URL}/fecha-examen?oposicion=${encodeURIComponent(oposicion)}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      const datos = await res.json();
      fechaActual = datos.fecha_examen || null;
    }
  } catch (e) {
    console.error("Error cargando fecha de examen:", e);
  }
  pintar(fechaActual);

  boton.addEventListener("click", () => {
    input.value = fechaActual || "";
    form.style.display = form.style.display === "none" ? "flex" : "none";
  });

  form.addEventListener("submit", async (evento) => {
    evento.preventDefault();
    try {
      await fetch(`${BACKEND_URL}/fecha-examen?oposicion=${encodeURIComponent(oposicion)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ fecha_examen: input.value })
      });
      fechaActual = input.value;
      pintar(fechaActual);
      form.style.display = "none";
    } catch (e) {
      console.error("Error guardando fecha de examen:", e);
      mostrarErrorGlobal("No se pudo guardar la fecha del examen. Inténtalo de nuevo.");
    }
  });

  quitar.addEventListener("click", async () => {
    try {
      await fetch(`${BACKEND_URL}/fecha-examen?oposicion=${encodeURIComponent(oposicion)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ fecha_examen: "" })
      });
      fechaActual = null;
      pintar(fechaActual);
      form.style.display = "none";
    } catch (e) {
      console.error("Error quitando fecha de examen:", e);
      mostrarErrorGlobal("No se pudo quitar la fecha del examen. Inténtalo de nuevo.");
    }
  });
}
