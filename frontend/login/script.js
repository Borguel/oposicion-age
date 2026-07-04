import { signIn, signUp, signInWithGoogle, idToken, recuperarContrasena, credencialGoogleDesdeError, vincularCredencialGoogle } from "/assets/auth.js";
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

const btnOlvidePassword = document.getElementById("btn-olvide-password");
const modalRecuperar = document.getElementById("modal-recuperar");
const formRecuperar = document.getElementById("form-recuperar");
const btnRecuperarSubmit = document.getElementById("btn-recuperar-submit");
const btnRecuperarCancelar = document.getElementById("btn-recuperar-cancelar");
const recuperarMensajeError = document.getElementById("recuperar-mensaje-error");
const recuperarMensajeOk = document.getElementById("recuperar-mensaje-ok");

const modalVincularGoogle = document.getElementById("modal-vincular-google");
const formVincularGoogle = document.getElementById("form-vincular-google");
const btnVincularSubmit = document.getElementById("btn-vincular-submit");
const btnVincularCancelar = document.getElementById("btn-vincular-cancelar");
const vincularMensajeError = document.getElementById("vincular-mensaje-error");
let emailPendienteVincular = null;
let credencialPendienteVincular = null;

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
  "auth/popup-closed-by-user": "Has cerrado la ventana de Google antes de terminar.",
  "auth/popup-blocked": "Tu navegador ha bloqueado la ventana de Google. Permite las ventanas emergentes para este sitio e inténtalo de nuevo.",
  "auth/cancelled-popup-request": "Ya había una ventana de Google abierta. Inténtalo de nuevo.",
  "auth/unauthorized-domain": "Este dominio no está autorizado para iniciar sesión con Google. Contacta con el soporte de la web.",
  "auth/account-exists-with-different-credential": "Ya existe una cuenta con ese correo usando otro método de acceso (contraseña). Inicia sesión con tu contraseña.",
  "auth/operation-not-allowed": "El inicio de sesión con Google no está disponible ahora mismo. Inténtalo más tarde o usa correo y contraseña.",
  "auth/network-request-failed": "No se pudo conectar. Revisa tu conexión a internet e inténtalo de nuevo."
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
      // Al iniciar sesión con una cuenta de Google ya existente se va
      // directo a "Mi cuenta" en vez de a siguienteDestino(), a petición
      // explícita (a diferencia del login por email/contraseña, que sí
      // respeta a dónde quería volver el usuario).
      window.location.href = "/mi-cuenta/";
    }
  } catch (error) {
    if (error.code === "auth/account-exists-with-different-credential") {
      // Este correo ya tiene cuenta por contraseña: en vez de dejar al
      // usuario atascado con un mensaje sin salida, se le ofrece vincular
      // la credencial de Google pendiente en cuanto confirme su contraseña.
      credencialPendienteVincular = credencialGoogleDesdeError(error);
      emailPendienteVincular = error.customData?.email || "";
      abrirModalVincularGoogle();
    } else {
      mensajeError.textContent = MENSAJES_ERROR[error.code] || "No se pudo continuar con Google. Inténtalo de nuevo.";
      mensajeError.style.display = "block";
    }
  } finally {
    btnGoogle.disabled = false;
  }
});

function abrirModalVincularGoogle() {
  document.getElementById("vincular-password").value = "";
  vincularMensajeError.style.display = "none";
  btnVincularSubmit.disabled = false;
  modalVincularGoogle.style.display = "flex";
}

function cerrarModalVincularGoogle() {
  modalVincularGoogle.style.display = "none";
  credencialPendienteVincular = null;
  emailPendienteVincular = null;
}

btnVincularCancelar.addEventListener("click", cerrarModalVincularGoogle);
modalVincularGoogle.addEventListener("click", (evento) => {
  if (evento.target === modalVincularGoogle) cerrarModalVincularGoogle();
});

formVincularGoogle.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  vincularMensajeError.style.display = "none";
  btnVincularSubmit.disabled = true;

  const password = document.getElementById("vincular-password").value;

  try {
    if (!emailPendienteVincular || !credencialPendienteVincular) {
      throw new Error("No se pudo continuar la vinculación. Vuelve a intentarlo con el botón de Google.");
    }
    const userCredential = await signIn(emailPendienteVincular, password);
    await vincularCredencialGoogle(userCredential.user, credencialPendienteVincular);
    cerrarModalVincularGoogle();
    window.location.href = "/mi-cuenta/";
  } catch (error) {
    vincularMensajeError.textContent = MENSAJES_ERROR[error.code] || error.message || "Contraseña incorrecta. Inténtalo de nuevo.";
    vincularMensajeError.style.display = "block";
    btnVincularSubmit.disabled = false;
  }
});

function abrirModalRecuperar() {
  document.getElementById("recuperar-email").value = document.getElementById("email").value.trim();
  recuperarMensajeError.style.display = "none";
  recuperarMensajeOk.style.display = "none";
  formRecuperar.style.display = "block";
  btnRecuperarSubmit.disabled = false;
  modalRecuperar.style.display = "flex";
}

function cerrarModalRecuperar() {
  modalRecuperar.style.display = "none";
}

btnOlvidePassword.addEventListener("click", abrirModalRecuperar);
btnRecuperarCancelar.addEventListener("click", cerrarModalRecuperar);
modalRecuperar.addEventListener("click", (evento) => {
  if (evento.target === modalRecuperar) cerrarModalRecuperar();
});

formRecuperar.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  recuperarMensajeError.style.display = "none";
  btnRecuperarSubmit.disabled = true;

  const email = document.getElementById("recuperar-email").value.trim();

  try {
    await recuperarContrasena(email);
    formRecuperar.style.display = "none";
    recuperarMensajeOk.style.display = "block";
  } catch (error) {
    if (error.code === "auth/invalid-email") {
      recuperarMensajeError.textContent = MENSAJES_ERROR[error.code];
      recuperarMensajeError.style.display = "block";
      btnRecuperarSubmit.disabled = false;
    } else {
      // Por seguridad, no revelamos si el correo existe o no: cualquier otro
      // error (p. ej. user-not-found) se trata igual que un envío correcto.
      formRecuperar.style.display = "none";
      recuperarMensajeOk.style.display = "block";
    }
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
