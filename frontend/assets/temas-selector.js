// Selector de temas agrupado por bloque, compartido por test-generator y
// preguntas-falladas: cada bloque tiene su propio checkbox para marcar
// todos sus temas de golpe (con estado indeterminado si solo hay algunos
// marcados) y se puede plegar/desplegar para no ocupar tanto espacio.
export function renderizarSelectorTemas(contenedor, temas, preseleccionados = new Set()) {
  const bloques = new Map();
  temas.forEach((t) => {
    const bloqueId = t.bloque_id || "sin_bloque";
    const bloqueTitulo = t.bloque_titulo || "Otros temas";
    if (!bloques.has(bloqueId)) bloques.set(bloqueId, { titulo: bloqueTitulo, temas: [] });
    bloques.get(bloqueId).temas.push(t);
  });

  const bloqueIds = Array.from(bloques.keys()).sort();

  contenedor.innerHTML = bloqueIds.map((bloqueId) => {
    const { titulo, temas: temasBloque } = bloques.get(bloqueId);
    const temasHTML = temasBloque.map((t) => `
      <label class="tema-check-label">
        <input type="checkbox" name="tema" value="${t.id}" data-bloque="${bloqueId}" ${preseleccionados.has(t.id) ? "checked" : ""}>
        ${t.titulo}
      </label>
    `).join("");
    return `
      <div class="bloque-grupo">
        <div class="bloque-header">
          <label class="bloque-check-label">
            <input type="checkbox" data-bloque-check="${bloqueId}">
            <strong>${titulo}</strong>
          </label>
          <button type="button" class="bloque-toggle" data-bloque-toggle="${bloqueId}" aria-label="Desplegar o plegar bloque">▾</button>
        </div>
        <div class="bloque-temas" id="bloque-temas-${bloqueId}">${temasHTML}</div>
      </div>
    `;
  }).join("");

  function actualizarEstadoBloque(bloqueId) {
    const checkboxBloque = contenedor.querySelector(`[data-bloque-check="${bloqueId}"]`);
    const temasCheckboxes = Array.from(contenedor.querySelectorAll(`input[name="tema"][data-bloque="${bloqueId}"]`));
    const marcados = temasCheckboxes.filter((c) => c.checked).length;
    checkboxBloque.checked = marcados > 0 && marcados === temasCheckboxes.length;
    checkboxBloque.indeterminate = marcados > 0 && marcados < temasCheckboxes.length;
  }

  bloqueIds.forEach(actualizarEstadoBloque);

  contenedor.querySelectorAll("[data-bloque-check]").forEach((checkboxBloque) => {
    checkboxBloque.addEventListener("change", () => {
      const bloqueId = checkboxBloque.dataset.bloqueCheck;
      contenedor.querySelectorAll(`input[name="tema"][data-bloque="${bloqueId}"]`).forEach((c) => {
        c.checked = checkboxBloque.checked;
      });
      checkboxBloque.indeterminate = false;
    });
  });

  contenedor.querySelectorAll('input[name="tema"]').forEach((checkboxTema) => {
    checkboxTema.addEventListener("change", () => actualizarEstadoBloque(checkboxTema.dataset.bloque));
  });

  contenedor.querySelectorAll("[data-bloque-toggle]").forEach((boton) => {
    boton.addEventListener("click", () => {
      const panel = document.getElementById(`bloque-temas-${boton.dataset.bloqueToggle}`);
      panel.classList.toggle("bloque-temas-cerrado");
      boton.classList.toggle("bloque-toggle-cerrado", panel.classList.contains("bloque-temas-cerrado"));
    });
  });
}
