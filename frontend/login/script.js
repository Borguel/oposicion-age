import { signIn, signUp, idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

const tabLogin = document.getElementById("tab-login");
const tabSignup = document.getElementById("tab-signup");
const form = document.getElementById("form-auth");
const btnSubmit = document.getElementById("btn-submit");
const mensajeError = document.getElementById("mensaje-error");

let modo = "login";

function cambiarModo(nuevoModo) {
  modo = nuevoModo;
  tabLogin.classList.toggle("active", modo === "login");
  tabSignup.classList.toggle("active", modo === "signup");
  btnSubmit.textContent = modo === "login" ? "Iniciar sesión" : "Crear cuenta";
  mensajeError.style.display = "none";
}

tabLogin.addEventListener("click", () => cambiarModo("login"));
tabSignup.addEventListener("click", () => cambiarModo("signup"));

function siguienteDestino() {
  const params = new URLSearchParams(window.location.search);
  return params.get("next") || "/";
}

const MENSAJES_ERROR = {
  "auth/invalid-email": "El correo electrónico no es válido.",
  "auth/user-not-found": "No existe ninguna cuenta con ese correo.",
  "auth/wrong-password": "Contraseña incorrecta.",
  "auth/invalid-credential": "Correo o contraseña incorrectos.",
  "auth/email-already-in-use": "Ya existe una cuenta con ese correo.",
  "auth/weak-password": "La contraseña debe tener al menos 6 caracteres."
};

form.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  mensajeError.style.display = "none";
  btnSubmit.disabled = true;

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    if (modo === "login") {
      await signIn(email, password);
    } else {
      await signUp(email, password);
      const token = await idToken();
      await fetch(`${BACKEND_URL}/registrar-usuario`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({})
      });
    }
    window.location.href = siguienteDestino();
  } catch (error) {
    mensajeError.textContent = MENSAJES_ERROR[error.code] || "No se pudo completar la operación. Inténtalo de nuevo.";
    mensajeError.style.display = "block";
    btnSubmit.disabled = false;
  }
});
