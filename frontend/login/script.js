import { signIn, signUp, signInWithGoogle, idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

const tabLogin = document.getElementById("tab-login");
const tabSignup = document.getElementById("tab-signup");
const form = document.getElementById("form-auth");
const btnSubmit = document.getElementById("btn-submit");
const mensajeError = document.getElementById("mensaje-error");
const btnGoogle = document.getElementById("btn-google");

const pasoCuenta = document.getElementById("paso-cuenta");
const pasoPerfil = document.getElementById("paso-perfil");
const formPerfil = document.getElementById("form-perfil");
const btnPerfilSubmit = document.getElementById("btn-perfil-submit");
const perfilMensajeError = document.getElementById("perfil-mensaje-error");

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

async function enviarPerfilVacio() {
  const token = await idToken();
  await fetch(`${BACKEND_URL}/registrar-usuario`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({})
  });
}

function mostrarPasoPerfil(nombre = "", apellidos = "") {
  document.getElementById("perfil-nombre").value = nombre;
  document.getElementById("perfil-apellidos").value = apellidos;
  pasoCuenta.style.display = "none";
  pasoPerfil.style.display = "block";
}

const MENSAJES_ERROR = {
  "auth/invalid-email": "El correo electrónico no es válido.",
  "auth/user-not-found": "No existe ninguna cuenta con ese correo.",
  "auth/wrong-password": "Contraseña incorrecta.",
  "auth/invalid-credential": "Correo o contraseña incorrectos.",
  "auth/email-already-in-use": "Ya existe una cuenta con ese correo.",
  "auth/weak-password": "La contraseña debe tener al menos 6 caracteres.",
  "auth/popup-closed-by-user": "Has cerrado la ventana de Google antes de terminar."
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
      window.location.href = siguienteDestino();
    } else {
      await signUp(email, password);
      await enviarPerfilVacio();
      mostrarPasoPerfil();
    }
  } catch (error) {
    mensajeError.textContent = MENSAJES_ERROR[error.code] || "No se pudo completar la operación. Inténtalo de nuevo.";
    mensajeError.style.display = "block";
  } finally {
    btnSubmit.disabled = false;
  }
});

btnGoogle.addEventListener("click", async () => {
  btnGoogle.disabled = true;
  mensajeError.style.display = "none";
  try {
    const { esNuevo, nombre, apellidos } = await signInWithGoogle();
    if (esNuevo) {
      await enviarPerfilVacio();
      mostrarPasoPerfil(nombre, apellidos);
    } else {
      window.location.href = siguienteDestino();
    }
  } catch (error) {
    mensajeError.textContent = MENSAJES_ERROR[error.code] || "No se pudo continuar con Google. Inténtalo de nuevo.";
    mensajeError.style.display = "block";
  } finally {
    btnGoogle.disabled = false;
  }
});

formPerfil.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  perfilMensajeError.style.display = "none";
  btnPerfilSubmit.disabled = true;

  const nombre = document.getElementById("perfil-nombre").value.trim();
  const apellidos = document.getElementById("perfil-apellidos").value.trim();
  const telefono = document.getElementById("perfil-telefono").value.trim();
  const direccion = document.getElementById("perfil-direccion").value.trim();

  try {
    const token = await idToken();
    const res = await fetch(`${BACKEND_URL}/registrar-usuario`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ nombre, apellidos, telefono, direccion })
    });
    if (!res.ok) throw new Error("No se pudo guardar tu perfil");
    window.location.href = siguienteDestino();
  } catch (error) {
    perfilMensajeError.textContent = error.message || "No se pudo guardar tu perfil. Inténtalo de nuevo.";
    perfilMensajeError.style.display = "block";
    btnPerfilSubmit.disabled = false;
  }
});
