import { signIn, signUp, signInWithGoogle, idToken, recuperarContrasena, credencialGoogleDesdeError, vincularCredencialGoogle, enviarVerificacionEmail } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { activarAccesibilidadModal } from "/assets/modal-accesible.js";

const tabLogin = document.getElementById("tab-login");
const tabSignup = document.getElementById("tab-signup");
const form = document.getElementById("form-auth");
const btnSubmit = document.getElementById("btn-submit");
const mensajeError = document.getElementById("mensaje-error");
const btnGoogle = document.getElementById("btn-google");
const bloqueTerminos = document.getElementById("bloque-terminos");
const checkTerminos = document.getElementById("check-terminos");
const bloqueNombreApellidos = document.getElementById("bloque-nombre-apellidos");
const inputNombre = document.getElementById("nombre");
const inputApellidos = document.getElementById("apellidos");
const bloqueRepetirPassword = document.getElementById("bloque-repetir-password");
const inputRepetirPassword = document.getElementById("repetir-password");
const avisoPrueba = document.getElementById("aviso-prueba");

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
const a11yModalVincular = activarAccesibilidadModal(modalVincularGoogle, btnVincularCancelar);
const a11yModalRecuperar = activarAccesibilidadModal(modalRecuperar, btnRecuperarCancelar);

let modo = "login";

function cambiarModo(nuevoModo) {
  modo = nuevoModo;
  const esAlta = modo === "signup";
  tabLogin.classList.toggle("active", modo === "login");
  tabSignup.classList.toggle("active", esAlta);
  btnSubmit.textContent = modo === "login" ? "Iniciar sesión" : "Crear cuenta";
  mensajeError.style.display = "none";

  // Nombre, apellidos y repetir contraseña solo se piden al dar de alta una
  // cuenta nueva (en "Iniciar sesión" no aplican). display:none NO exime a
  // un campo required de la validación nativa del navegador (willValidate
  // sigue siendo true), así que hay que quitar también el atributo required
  // o el formulario de login queda bloqueado en silencio sin mostrar error.
  bloqueNombreApellidos.style.display = esAlta ? "block" : "none";
  bloqueRepetirPassword.style.display = esAlta ? "block" : "none";
  inputNombre.required = esAlta;
  inputApellidos.required = esAlta;
  inputRepetirPassword.required = esAlta;
  inputNombre.value = "";
  inputApellidos.value = "";
  inputRepetirPassword.value = "";

  // "¿Olvidaste tu contraseña?" solo tiene sentido si ya existe una cuenta.
  btnOlvidePassword.style.display = esAlta ? "none" : "block";

  // La aceptación de Términos y Política de Privacidad solo aplica al alta
  // de una cuenta nueva (obligatorio por ley) -- al volver a "Iniciar
  // sesión" se oculta y se resetea, para no arrastrar un estado confuso si
  // el usuario cambia de pestaña.
  bloqueTerminos.style.display = esAlta ? "block" : "none";
  checkTerminos.checked = false;
  avisoPrueba.style.display = esAlta ? "block" : "none";
}

tabLogin.addEventListener("click", () => cambiarModo("login"));
tabSignup.addEventListener("click", () => cambiarModo("signup"));

// Sincroniza el estado inicial (sobre todo el atributo required de los
// campos de alta, que si no quedan bloqueando el login en silencio).
cambiarModo("login");

function siguienteDestino() {
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next");
  // Solo se acepta una ruta relativa dentro del propio sitio: "next" viene
  // de la URL (controlable por quien comparta el enlace), así que aceptar
  // una URL absoluta o protocol-relative ("//dominio-ajeno.com") permitiría
  // usar nuestro propio dominio de confianza para redirigir tras el login a
  // un sitio de phishing externo (open redirect).
  if (next && next.startsWith("/") && !next.startsWith("//")) return next;
  return "/zona-opositor/";
}

async function guardarPerfilBasico(nombre, apellidos) {
  const token = await idToken();
  await fetch(`${BACKEND_URL}/registrar-usuario`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ nombre, apellidos })
  });
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
  "auth/network-request-failed": "No se pudo conectar. Revisa tu conexión a internet e inténtalo de nuevo.",
  "auth/carga-fallida": "No se pudo cargar el sistema de acceso. Revisa tu conexión, desactiva bloqueadores de anuncios o extensiones de privacidad para este sitio y recarga la página."
};

form.addEventListener("submit", async (evento) => {
  evento.preventDefault();
  mensajeError.style.display = "none";

  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const nombre = inputNombre.value.trim();
  const apellidos = inputApellidos.value.trim();

  if (modo === "signup") {
    if (password !== inputRepetirPassword.value) {
      mensajeError.textContent = "Las contraseñas no coinciden.";
      mensajeError.style.display = "block";
      return;
    }
    if (!checkTerminos.checked) {
      mensajeError.textContent = "Debes aceptar los Términos y condiciones y la Política de Privacidad para crear una cuenta.";
      mensajeError.style.display = "block";
      return;
    }
  }

  btnSubmit.disabled = true;

  try {
    if (modo === "login") {
      await signIn(email, password);
      window.location.href = siguienteDestino();
    } else {
      await signUp(email, password);
      // Mejor esfuerzo: si falla el envío del correo de verificación no se
      // bloquea el alta -- el banner de auth.js ya ofrece reenviarlo luego.
      // AWAIT (11/08/2026, bug real: "no le ha llegado el correo de
      // verificación" -- esta llamada NO se esperaba, así que la
      // navegación de más abajo (window.location.href) podía cortarla a
      // mitad si guardarPerfilBasico terminaba antes: la petición al
      // backend (que a su vez genera el enlace en Firebase y llama a
      // Brevo) quedaba abortada por el propio cambio de página antes de
      // completarse, sin que hubiera ningún error visible.
      await enviarVerificacionEmail().catch(() => {});
      await guardarPerfilBasico(nombre, apellidos);
      // Igual que en el alta con Google: teléfono y dirección no son
      // imprescindibles para usar la web, y ya se pueden añadir después,
      // opcionalmente, desde Mi Cuenta -- pedirlos aquí solo añade fricción
      // justo antes de que el usuario pueda probar la herramienta.
      window.location.href = siguienteDestino();
    }
  } catch (error) {
    mensajeError.textContent = MENSAJES_ERROR[error.code] || "No se pudo completar la operación. Inténtalo de nuevo.";
    mensajeError.style.display = "block";
  } finally {
    btnSubmit.disabled = false;
  }
});

btnGoogle.addEventListener("click", async () => {
  mensajeError.style.display = "none";

  if (modo === "signup" && !checkTerminos.checked) {
    mensajeError.textContent = "Debes aceptar los Términos y condiciones y la Política de Privacidad para crear una cuenta.";
    mensajeError.style.display = "block";
    return;
  }

  btnGoogle.disabled = true;
  try {
    const { esNuevo, nombre, apellidos } = await signInWithGoogle();
    if (esNuevo) {
      // Google ya nos da nombre y apellidos; el resto de datos opcionales
      // (teléfono, dirección) se pueden añadir más tarde desde Mi Cuenta.
      await guardarPerfilBasico(nombre, apellidos);
    }
    // Al iniciar sesión con Google se va directo a "Zona opositor" en vez
    // de a siguienteDestino(), a petición explícita (a diferencia del login
    // por email/contraseña, que sí respeta a dónde quería volver el usuario).
    window.location.href = "/zona-opositor/";
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
  a11yModalVincular.alAbrir();
}

function cerrarModalVincularGoogle() {
  modalVincularGoogle.style.display = "none";
  credencialPendienteVincular = null;
  emailPendienteVincular = null;
  a11yModalVincular.alCerrar();
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
    window.location.href = "/zona-opositor/";
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
  a11yModalRecuperar.alAbrir();
}

function cerrarModalRecuperar() {
  modalRecuperar.style.display = "none";
  a11yModalRecuperar.alCerrar();
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
