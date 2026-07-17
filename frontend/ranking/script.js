import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { icono } from "/assets/icons.js";

function escaparHtml(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

function renderizarFormularioUnirse(contenedor, token, aliasPrevio) {
  contenedor.innerHTML = `
    <h3>Apúntate a la clasificación</h3>
    <p>Elige un alias (nunca tu nombre real). Podrás cambiarlo o salir de la clasificación cuando quieras.</p>
    <form id="ranking-form-alias" class="ranking-form-alias">
      <input type="text" id="ranking-alias-input" placeholder="Tu alias (3-20 caracteres)" value="${escaparHtml(aliasPrevio || "")}" minlength="3" maxlength="20" required />
      <button type="submit" class="age-btn age-btn-primary">Unirme</button>
    </form>
    <p class="ranking-error" id="ranking-error" style="display:none;"></p>
  `;
  contenedor.querySelector("#ranking-form-alias").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const alias = contenedor.querySelector("#ranking-alias-input").value.trim();
    const errorEl = contenedor.querySelector("#ranking-error");
    errorEl.style.display = "none";
    try {
      const res = await fetch(`${BACKEND_URL}/ranking/unirse`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ alias })
      });
      const datos = await res.json();
      if (!res.ok) throw new Error(datos.error || "No se pudo completar la operación.");
      await iniciar();
    } catch (e) {
      errorEl.textContent = e.message || "No se pudo completar la operación.";
      errorEl.style.display = "block";
    }
  });
}

function renderizarParticipando(contenedor, token, alias) {
  contenedor.innerHTML = `
    <h3>Estás participando como <strong>${escaparHtml(alias)}</strong></h3>
    <p>Nadie ve tu nombre real ni tu correo: solo este alias y tu racha actual.</p>
    <div class="ranking-participacion-acciones">
      <button type="button" class="age-btn age-btn-outline" id="ranking-cambiar-alias">Cambiar alias</button>
      <button type="button" class="age-btn age-btn-outline" id="ranking-salir">Salir de la clasificación</button>
    </div>
  `;
  contenedor.querySelector("#ranking-cambiar-alias").addEventListener("click", () => {
    renderizarFormularioUnirse(contenedor, token, alias);
  });
  contenedor.querySelector("#ranking-salir").addEventListener("click", async () => {
    await fetch(`${BACKEND_URL}/ranking/salir`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` }
    });
    await iniciar();
  });
}

function renderizarLista(datos) {
  const contenedor = document.getElementById("ranking-lista");
  document.getElementById("ranking-total-participantes").textContent =
    datos.total_participantes > 0 ? `${datos.total_participantes} apuntados` : "";

  if (datos.ranking.length === 0) {
    contenedor.innerHTML = `<p class="ranking-vacio">Todavía no hay nadie apuntado. ¡Sé el primero!</p>`;
    return;
  }

  contenedor.innerHTML = `
    <ol class="ranking-filas">
      ${datos.ranking.map((p, i) => `
        <li class="ranking-fila${p.tu ? " ranking-fila-tu" : ""}">
          <span class="ranking-fila-puesto">${i + 1}</span>
          <span class="ranking-fila-alias">${escaparHtml(p.alias)}${p.tu ? " (tú)" : ""}</span>
          <span class="ranking-fila-racha">${icono("fuego", 16)} ${p.racha_actual}</span>
        </li>
      `).join("")}
    </ol>
    ${datos.tu_posicion && datos.tu_posicion > datos.ranking.length ? `<p class="ranking-tu-posicion">Tu posición: #${datos.tu_posicion} con ${datos.tu_racha} día${datos.tu_racha === 1 ? "" : "s"} de racha.</p>` : ""}
  `;
}

async function iniciar() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=/ranking/";
    return;
  }

  const contenedorParticipacion = document.getElementById("ranking-participacion");
  try {
    const [resEstado, resRanking] = await Promise.all([
      fetch(`${BACKEND_URL}/ranking/mi-estado`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${BACKEND_URL}/ranking`, { headers: { Authorization: `Bearer ${token}` } })
    ]);
    const estado = await resEstado.json();
    const ranking = await resRanking.json();

    if (estado.participa) {
      renderizarParticipando(contenedorParticipacion, token, estado.alias);
    } else {
      renderizarFormularioUnirse(contenedorParticipacion, token, estado.alias);
    }
    renderizarLista(ranking);
  } catch (e) {
    contenedorParticipacion.innerHTML = `<p>No se pudo cargar la clasificación.</p>`;
    console.error("Error cargando la clasificación:", e);
  }
}

iniciar();
