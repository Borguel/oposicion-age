// Marcar/desmarcar preguntas como favoritas para repasarlas más tarde,
// desde cualquier página que muestre preguntas de test. Comparte el mismo
// patrón simple de fetch + Authorization que el resto de módulos de /assets.
import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

export async function marcarFavorita(pregunta, oposicion) {
  const token = await idToken();
  if (!token) return;
  await fetch(`${BACKEND_URL}/marcar-favorita?oposicion=${encodeURIComponent(oposicion)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ pregunta })
  });
}

export async function desmarcarFavorita(textoPregunta, oposicion) {
  const token = await idToken();
  if (!token) return;
  await fetch(`${BACKEND_URL}/desmarcar-favorita?oposicion=${encodeURIComponent(oposicion)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ pregunta: textoPregunta })
  });
}

export async function cargarTextosFavoritas(oposicion) {
  try {
    const token = await idToken();
    if (!token) return new Set();
    const res = await fetch(`${BACKEND_URL}/preguntas-favoritas?oposicion=${encodeURIComponent(oposicion)}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) return new Set();
    const { favoritas } = await res.json();
    return new Set((favoritas || []).map((f) => f.pregunta));
  } catch (e) {
    return new Set();
  }
}

// Botón de estrella reutilizable + su listener, para no repetir este HTML
// en cada una de las páginas que muestran preguntas de test.
export function botonFavoritaHTML(marcada) {
  return `<button type="button" class="btn-favorita${marcada ? " activa" : ""}" data-favorita aria-label="Marcar pregunta como favorita" title="Marcar para repasar más tarde">${marcada ? "★" : "☆"}</button>`;
}

export function activarBotonFavorita(contenedor, pregunta, oposicion, textosFavoritas) {
  const boton = contenedor.querySelector("[data-favorita]");
  if (!boton) return;
  boton.addEventListener("click", async () => {
    const marcada = boton.classList.contains("activa");
    boton.disabled = true;
    if (marcada) {
      await desmarcarFavorita(pregunta.pregunta, oposicion);
      textosFavoritas.delete(pregunta.pregunta);
      boton.classList.remove("activa");
      boton.textContent = "☆";
    } else {
      await marcarFavorita(pregunta, oposicion);
      textosFavoritas.add(pregunta.pregunta);
      boton.classList.add("activa");
      boton.textContent = "★";
    }
    boton.disabled = false;
  });
}
