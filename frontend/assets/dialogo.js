// Modales propios de confirmación/texto, con el diseño de la web, para
// sustituir a confirm()/prompt() nativos del navegador (desentonaban con el
// resto del sitio -- diálogo genérico del sistema operativo). Mismo patrón
// ya probado en frontend/mis-documentos/script.js, pero construyendo su
// propio DOM en tiempo de ejecución en vez de depender de un markup fijo en
// cada página: este módulo lo importan páginas distintas (mis-tests,
// resultados-test, admin) que no tienen ese HTML de por sí.
import { activarAccesibilidadModal } from "/assets/modal-accesible.js";
import { icono } from "/assets/icons.js";

let el = null;

function construir() {
  if (el) return el;
  const envoltorio = document.createElement("div");
  envoltorio.innerHTML = `
    <div class="age-dialogo-overlay hidden" id="age-dialogo-confirmar">
      <div class="age-card age-dialogo-card" tabindex="-1">
        <div class="age-dialogo-cabecera">
          <h3 id="age-dialogo-confirmar-titulo">Confirmar</h3>
          <button type="button" class="age-dialogo-cerrar" id="age-dialogo-confirmar-cerrar" aria-label="Cerrar">${icono("cruz", 16)}</button>
        </div>
        <p id="age-dialogo-confirmar-mensaje" class="age-dialogo-mensaje"></p>
        <div class="age-dialogo-acciones">
          <button type="button" class="age-btn age-btn-outline" id="age-dialogo-confirmar-cancelar">Cancelar</button>
          <button type="button" class="age-btn age-btn-primary" id="age-dialogo-confirmar-aceptar">Confirmar</button>
        </div>
      </div>
    </div>
    <div class="age-dialogo-overlay hidden" id="age-dialogo-prompt">
      <div class="age-card age-dialogo-card" tabindex="-1">
        <div class="age-dialogo-cabecera">
          <h3 id="age-dialogo-prompt-titulo">Título</h3>
          <button type="button" class="age-dialogo-cerrar" id="age-dialogo-prompt-cerrar" aria-label="Cerrar">${icono("cruz", 16)}</button>
        </div>
        <form id="age-dialogo-prompt-formulario">
          <label class="age-dialogo-prompt-label" id="age-dialogo-prompt-label" for="age-dialogo-prompt-input"></label>
          <input type="text" id="age-dialogo-prompt-input" class="age-dialogo-prompt-input" maxlength="400" />
          <div class="age-dialogo-acciones">
            <button type="button" class="age-btn age-btn-outline" id="age-dialogo-prompt-cancelar">Cancelar</button>
            <button type="submit" class="age-btn age-btn-primary" id="age-dialogo-prompt-aceptar">Guardar</button>
          </div>
        </form>
      </div>
    </div>
  `;
  document.body.append(...envoltorio.children);

  el = {
    confirmar: document.getElementById("age-dialogo-confirmar"),
    prompt: document.getElementById("age-dialogo-prompt"),
  };
  el.a11yConfirmar = activarAccesibilidadModal(el.confirmar, document.getElementById("age-dialogo-confirmar-cerrar"));
  el.a11yPrompt = activarAccesibilidadModal(el.prompt, document.getElementById("age-dialogo-prompt-cerrar"));
  return el;
}

export function mostrarConfirmacion({ titulo = "Confirmar", mensaje, textoAceptar = "Confirmar", peligro = false }) {
  const { confirmar: overlay, a11yConfirmar: a11y } = construir();
  return new Promise((resolve) => {
    const btnAceptar = document.getElementById("age-dialogo-confirmar-aceptar");
    const btnCancelar = document.getElementById("age-dialogo-confirmar-cancelar");
    const btnCerrar = document.getElementById("age-dialogo-confirmar-cerrar");

    document.getElementById("age-dialogo-confirmar-titulo").textContent = titulo;
    document.getElementById("age-dialogo-confirmar-mensaje").textContent = mensaje;
    btnAceptar.textContent = textoAceptar;
    btnAceptar.classList.toggle("age-btn-danger", peligro);
    btnAceptar.classList.toggle("age-btn-primary", !peligro);

    const terminar = (resultado) => {
      overlay.classList.add("hidden");
      a11y.alCerrar();
      btnAceptar.removeEventListener("click", onAceptar);
      btnCancelar.removeEventListener("click", onCancelar);
      btnCerrar.removeEventListener("click", onCancelar);
      overlay.removeEventListener("click", onOverlay);
      resolve(resultado);
    };
    const onAceptar = () => terminar(true);
    const onCancelar = () => terminar(false);
    const onOverlay = (evento) => { if (evento.target === overlay) terminar(false); };

    btnAceptar.addEventListener("click", onAceptar);
    btnCancelar.addEventListener("click", onCancelar);
    btnCerrar.addEventListener("click", onCancelar);
    overlay.addEventListener("click", onOverlay);
    overlay.classList.remove("hidden");
    a11y.alAbrir();
  });
}

export function mostrarPrompt({ titulo, label, valorInicial = "", placeholder = "", textoAceptar = "Guardar" }) {
  const { prompt: overlay, a11yPrompt: a11y } = construir();
  return new Promise((resolve) => {
    const formulario = document.getElementById("age-dialogo-prompt-formulario");
    const input = document.getElementById("age-dialogo-prompt-input");
    const btnCancelar = document.getElementById("age-dialogo-prompt-cancelar");
    const btnCerrar = document.getElementById("age-dialogo-prompt-cerrar");

    document.getElementById("age-dialogo-prompt-titulo").textContent = titulo;
    document.getElementById("age-dialogo-prompt-label").textContent = label;
    document.getElementById("age-dialogo-prompt-aceptar").textContent = textoAceptar;
    input.value = valorInicial;
    input.placeholder = placeholder;

    const terminar = (resultado) => {
      overlay.classList.add("hidden");
      a11y.alCerrar();
      formulario.removeEventListener("submit", onSubmit);
      btnCancelar.removeEventListener("click", onCancelar);
      btnCerrar.removeEventListener("click", onCancelar);
      overlay.removeEventListener("click", onOverlay);
      resolve(resultado);
    };
    const onSubmit = (evento) => { evento.preventDefault(); terminar(input.value); };
    const onCancelar = () => terminar(null);
    const onOverlay = (evento) => { if (evento.target === overlay) terminar(null); };

    formulario.addEventListener("submit", onSubmit);
    btnCancelar.addEventListener("click", onCancelar);
    btnCerrar.addEventListener("click", onCancelar);
    overlay.addEventListener("click", onOverlay);
    overlay.classList.remove("hidden");
    a11y.alAbrir();
    input.focus();
    input.select();
  });
}
