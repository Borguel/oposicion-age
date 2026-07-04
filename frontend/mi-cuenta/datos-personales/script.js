import { idToken, esperarUsuario, cambiarEmail, tieneProveedorPassword, reautenticarConPassword } from "/assets/auth.js";
import { obtenerPlan } from "/assets/plan.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

let usuarioActual = null;

function mostrarMensaje(texto, tipo) {
  const el = document.getElementById("datos-mensaje");
  el.textContent = texto;
  el.className = `datos-mensaje ${tipo}`;
  el.style.display = "block";
}

// Muestra el modal de contraseña y resuelve la promesa cuando la
// reautenticación se completa (o la rechaza si el usuario cancela), para
// que intentarCambiarEmail() pueda esperar antes de reintentar.
function pedirPassword() {
  return new Promise((resolve, reject) => {
    const modal = document.getElementById("modal-reautenticar");
    const form = document.getElementById("form-reautenticar");
    const input = document.getElementById("reautenticar-password");
    const errorEl = document.getElementById("reautenticar-mensaje-error");
    const btnCancelar = document.getElementById("btn-reautenticar-cancelar");

    errorEl.style.display = "none";
    input.value = "";
    modal.style.display = "flex";

    function limpiar() {
      modal.style.display = "none";
      form.removeEventListener("submit", onSubmit);
      btnCancelar.removeEventListener("click", onCancelar);
    }

    async function onSubmit(evento) {
      evento.preventDefault();
      try {
        await reautenticarConPassword(input.value);
        limpiar();
        resolve();
      } catch (e) {
        errorEl.textContent = "Contraseña incorrecta. Inténtalo de nuevo.";
        errorEl.style.display = "block";
      }
    }

    function onCancelar() {
      limpiar();
      reject(new Error("Cambio de correo cancelado."));
    }

    form.addEventListener("submit", onSubmit);
    btnCancelar.addEventListener("click", onCancelar);
  });
}

async function intentarCambiarEmail(nuevoEmail) {
  try {
    await cambiarEmail(nuevoEmail);
  } catch (error) {
    if (error.code === "auth/requires-recent-login") {
      if (!tieneProveedorPassword()) {
        throw new Error("Para cambiar el correo con una cuenta de Google, cierra sesión, vuelve a entrar con Google y vuelve a intentarlo.");
      }
      await pedirPassword();
      await cambiarEmail(nuevoEmail);
    } else if (error.code === "auth/email-already-in-use") {
      throw new Error("Ese correo electrónico ya está en uso por otra cuenta.");
    } else if (error.code === "auth/invalid-email") {
      throw new Error("El correo electrónico no es válido.");
    } else {
      throw new Error("No se pudo cambiar el correo electrónico. Inténtalo más tarde.");
    }
  }
}

async function guardarDatosBasicos(datos) {
  const token = await idToken();
  const res = await fetch(`${BACKEND_URL}/registrar-usuario`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(datos)
  });
  if (!res.ok) throw new Error("No se pudieron guardar los datos. Inténtalo de nuevo.");
}

async function iniciar() {
  usuarioActual = await esperarUsuario();
  if (!usuarioActual) {
    window.location.href = "/login/?next=/mi-cuenta/datos-personales/";
    return;
  }

  const { nombre, apellidos, telefono, direccion } = await obtenerPlan(true);
  document.getElementById("campo-nombre").value = nombre || "";
  document.getElementById("campo-apellidos").value = apellidos || "";
  document.getElementById("campo-telefono").value = telefono || "";
  document.getElementById("campo-direccion").value = direccion || "";
  document.getElementById("campo-email").value = usuarioActual.email || "";

  document.getElementById("form-datos").addEventListener("submit", async (evento) => {
    evento.preventDefault();
    const btn = document.getElementById("btn-guardar");
    btn.disabled = true;
    btn.textContent = "Guardando…";

    const nuevoEmail = document.getElementById("campo-email").value.trim();
    const emailCambio = Boolean(nuevoEmail) && nuevoEmail !== usuarioActual.email;

    try {
      if (emailCambio) {
        await intentarCambiarEmail(nuevoEmail);
      }
      await guardarDatosBasicos({
        nombre: document.getElementById("campo-nombre").value.trim(),
        apellidos: document.getElementById("campo-apellidos").value.trim(),
        telefono: document.getElementById("campo-telefono").value.trim(),
        direccion: document.getElementById("campo-direccion").value.trim()
      });
      mostrarMensaje(
        emailCambio
          ? "Datos guardados. Revisa tu nuevo correo para confirmar el cambio de dirección."
          : "Datos guardados correctamente.",
        "ok"
      );
    } catch (error) {
      mostrarMensaje(error.message || "No se pudo completar la operación.", "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Guardar cambios";
    }
  });
}

iniciar();
