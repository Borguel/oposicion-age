// Firebase Authentication (email + contraseña) + construcción dinámica de la
// barra de navegación compartida (.age-nav) y su menú de cuenta. Se importa
// como módulo en cada página del frontend.
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signInWithPopup,
  GoogleAuthProvider,
  EmailAuthProvider,
  getAdditionalUserInfo,
  sendPasswordResetEmail,
  linkWithCredential,
  verifyBeforeUpdateEmail,
  reauthenticateWithCredential,
  signOut as firebaseSignOut
} from "https://www.gstatic.com/firebasejs/10.13.0/firebase-auth.js";
import { firebaseConfig } from "/assets/firebase-config.js";
import { inyectarSelectorOposicion } from "/assets/oposicion.js";

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();

export function signIn(email, password) {
  return signInWithEmailAndPassword(auth, email, password);
}

export function signUp(email, password) {
  return createUserWithEmailAndPassword(auth, email, password);
}

// Inicia sesión (o crea la cuenta la primera vez) con Google. Devuelve
// { user, esNuevo, nombre, apellidos } para poder pedir el resto de datos
// del perfil solo quien entra por primera vez.
export async function signInWithGoogle() {
  const resultado = await signInWithPopup(auth, googleProvider);
  const esNuevo = getAdditionalUserInfo(resultado)?.isNewUser ?? false;
  const nombreCompleto = (resultado.user.displayName || "").trim();
  const partes = nombreCompleto.split(/\s+/).filter(Boolean);
  return {
    user: resultado.user,
    esNuevo,
    nombre: partes[0] || "",
    apellidos: partes.slice(1).join(" ")
  };
}

// Cuando signInWithGoogle() falla con "auth/account-exists-with-different-credential"
// (el correo ya tiene cuenta por contraseña), Firebase adjunta al error la
// credencial de Google pendiente; hay que guardarla para completar la
// vinculación en cuanto el usuario confirme su contraseña con signIn().
export function credencialGoogleDesdeError(error) {
  return GoogleAuthProvider.credentialFromError(error);
}

// Une la credencial de Google pendiente a la cuenta (ya autenticada por
// contraseña) del mismo correo, para que a partir de ahora sirvan los dos
// métodos de acceso en vez de dejar al usuario sin poder usar Google nunca
// con ese correo.
export function vincularCredencialGoogle(user, pendingCredential) {
  return linkWithCredential(user, pendingCredential);
}

// La cuenta tiene contraseña (además de, o en vez de, Google) si Firebase
// tiene un proveedor "password" en providerData -- solo entonces se puede
// reautenticar con contraseña para operaciones sensibles como cambiar el
// correo.
export function tieneProveedorPassword() {
  const user = auth.currentUser;
  return !!user && user.providerData.some((p) => p.providerId === "password");
}

// Reautentica con la contraseña actual (paso previo obligatorio de Firebase
// para operaciones sensibles como cambiar el correo, si hace tiempo que no
// se inició sesión: error "auth/requires-recent-login").
export function reautenticarConPassword(password) {
  const user = auth.currentUser;
  const credencial = EmailAuthProvider.credential(user.email, password);
  return reauthenticateWithCredential(user, credencial);
}

// Pide el cambio de correo: Firebase manda un enlace de verificación a la
// NUEVA dirección y el cambio no se hace efectivo hasta que el usuario lo
// confirma -- así se evita que alguien cambie el correo de una cuenta ajena
// sin acceso real a esa bandeja de entrada.
export function cambiarEmail(nuevoEmail) {
  return verifyBeforeUpdateEmail(auth.currentUser, nuevoEmail);
}

// Envía el correo de "restablecer contraseña" de Firebase. Firebase no dice
// si el correo existe o no (para no filtrar qué correos están registrados),
// así que desde fuera siempre se muestra el mismo mensaje de éxito.
export function recuperarContrasena(email) {
  return sendPasswordResetEmail(auth, email);
}

export function signOut() {
  sessionStorage.clear();
  return firebaseSignOut(auth);
}

// Devuelve una promesa que se resuelve con "valorSiTarda" si "promesa" no
// se ha resuelto pasados "ms" milisegundos. Evita que la web se quede
// colgada sin explicación si Firebase (o la red) tarda demasiado.
function conLimiteDeTiempo(promesa, ms, valorSiTarda) {
  return Promise.race([
    promesa,
    new Promise((resolve) => setTimeout(() => resolve(valorSiTarda), ms))
  ]);
}

// Espera a que Firebase resuelva el estado inicial de sesión (evita
// redirecciones prematuras a /login/ mientras el SDK todavía está
// comprobando si hay una sesión guardada).
export function esperarUsuario() {
  if (auth.currentUser) return Promise.resolve(auth.currentUser);
  const promesa = new Promise((resolve) => {
    const quitar = onAuthStateChanged(auth, (user) => {
      quitar();
      resolve(user);
    });
  });
  return conLimiteDeTiempo(promesa, 8000, null);
}

// Token que hay que mandar como "Authorization: Bearer <token>" en cada
// fetch() a una ruta protegida del backend. Devuelve null si no hay sesión.
// Espera primero a que Firebase confirme la sesión guardada (si entras
// directamente a una página, sin esto auth.currentUser podía estar
// todavía sin resolver y te mandaba a /login/ aunque sí tuvieras sesión).
export async function idToken() {
  const user = await esperarUsuario();
  if (!user) return null;
  return conLimiteDeTiempo(user.getIdToken(), 8000, null);
}

// ============================================================
// Barra de navegación: se construye entera desde aquí (una sola
// fuente de verdad) en vez de repetir <a> sueltos en cada página.
// ============================================================
const NAV_LINKS = [
  { href: "/", label: "Inicio", match: ["/"] },
  { href: "/zona-opositor/", label: "Zona opositor", match: ["/zona-opositor/"] },
  { href: "/test-generator/", label: "Tests", match: ["/test-generator/", "/repetir-test/", "/preguntas-falladas/", "/mis-tests/"] },
  { href: "/subida-pdf-pagina-principal/", label: "Herramientas IA", match: ["/subida-pdf-"] },
  { href: "/chat-ai/", label: "Chat IA", match: ["/chat-ai/"] },
  { href: "/asistente/", label: "Asistente", match: ["/asistente/"] },
  { href: "/estadisticas/", label: "Estadísticas", match: ["/estadisticas/"] }
];

function esEnlaceActivo(match, ruta) {
  return match.some((prefijo) => (prefijo === "/" ? ruta === "/" : ruta.startsWith(prefijo)));
}

function construirEsqueletoNav() {
  const nav = document.querySelector(".age-nav");
  if (!nav || nav.dataset.built) return;
  nav.dataset.built = "1";
  nav.innerHTML = "";

  const inner = document.createElement("div");
  inner.className = "age-nav-inner";

  const brand = document.createElement("a");
  brand.className = "age-nav-brand";
  brand.href = "/";
  brand.innerHTML = `<span class="age-nav-brand-mark">✓</span><span class="age-nav-brand-text">Oposición AGE</span>`;

  const links = document.createElement("div");
  links.className = "age-nav-links";
  const ruta = window.location.pathname;
  NAV_LINKS.forEach(({ href, label, match }) => {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = label;
    if (esEnlaceActivo(match, ruta)) a.classList.add("age-nav-active");
    links.appendChild(a);
  });

  const right = document.createElement("div");
  right.className = "age-nav-right";
  right.id = "age-nav-right";

  const burger = document.createElement("button");
  burger.type = "button";
  burger.className = "age-nav-burger";
  burger.setAttribute("aria-label", "Abrir menú");
  burger.textContent = "☰";
  burger.addEventListener("click", () => links.classList.toggle("open"));

  inner.appendChild(brand);
  inner.appendChild(links);
  inner.appendChild(right);
  inner.appendChild(burger);
  nav.appendChild(inner);
}

function construirMenuCuenta(user) {
  const right = document.getElementById("age-nav-right");
  if (!right) return;

  let acc = right.querySelector(".age-account");
  if (acc) acc.remove();
  acc = document.createElement("div");
  acc.className = "age-account";
  right.appendChild(acc);

  if (user) {
    const inicial = (user.email || "?").trim().charAt(0).toUpperCase();
    acc.innerHTML = `
      <button type="button" class="age-account-btn" data-account-toggle>
        <span class="age-account-avatar">${inicial}</span>
        <span class="age-account-caret">▾</span>
      </button>
      <div class="age-account-menu">
        <a href="/zona-opositor/">🎯 Zona opositor</a>
        <a href="/mi-cuenta/">⚙️ Mi cuenta</a>
        <a href="/planes/">💳 Planes</a>
        <div class="age-account-menu-divider"></div>
        <button type="button" data-account-logout>🚪 Cerrar sesión</button>
      </div>
    `;
    acc.querySelector("[data-account-toggle]").addEventListener("click", (evento) => {
      evento.stopPropagation();
      acc.classList.toggle("open");
    });
    acc.querySelector("[data-account-logout]").addEventListener("click", async () => {
      await signOut();
      window.location.href = "/";
    });
    document.addEventListener("click", () => acc.classList.remove("open"));
  } else {
    const destino = encodeURIComponent(window.location.pathname);
    acc.innerHTML = `<a class="age-btn age-btn-primary" style="padding:9px 18px;font-size:13.5px;" href="/login/?next=${destino}">Iniciar sesión</a>`;
  }
}

function inyectarNav(user) {
  construirEsqueletoNav();
  inyectarSelectorOposicion();
  construirMenuCuenta(user);
}

function inyectarFooter() {
  if (document.querySelector(".age-footer")) return;
  const footer = document.createElement("footer");
  footer.className = "age-footer";
  const anio = new Date().getFullYear();
  footer.innerHTML = `
    <span>© ${anio} Oposición AGE</span>
    <a href="/terminos/">Términos y condiciones</a>
    <a href="/privacidad/">Privacidad</a>
    <a href="/cookies/">Cookies</a>
  `;
  document.body.appendChild(footer);
}

const CLAVE_COOKIES_ACEPTADAS = "age_cookies_aceptadas";

function inyectarBannerCookies() {
  if (localStorage.getItem(CLAVE_COOKIES_ACEPTADAS) === "1") return;
  if (document.querySelector(".age-cookies-banner")) return;

  const banner = document.createElement("div");
  banner.className = "age-cookies-banner";
  banner.innerHTML = `
    <p>
      Usamos almacenamiento técnico necesario para que puedas iniciar sesión y usar la web
      (por ejemplo, para recordar tu sesión y la oposición que estás estudiando). No usamos cookies
      de publicidad. Más información en nuestra <a href="/cookies/">Política de Cookies</a>.
    </p>
    <button type="button" class="age-btn age-btn-primary" id="age-cookies-aceptar">Aceptar</button>
  `;
  document.body.appendChild(banner);

  // El aviso es fixed en la parte inferior: reserva justo su alto real como
  // padding para que no tape botones que ya estuvieran anclados abajo (p.
  // ej. "Finalizar test"). Se mide en vez de usar un valor fijo porque el
  // texto puede ocupar 1, 2 o 3 líneas según el ancho de pantalla. También
  // se expone como variable CSS para páginas con su propio layout a pantalla
  // completa (chat, asistente), que necesitan restarla de su propio alto en
  // vez de depender del padding del body.
  const ajustarEspacio = () => {
    const alto = `${banner.offsetHeight}px`;
    document.body.style.paddingBottom = alto;
    document.documentElement.style.setProperty("--age-cookie-banner-height", alto);
  };
  ajustarEspacio();
  window.addEventListener("resize", ajustarEspacio);

  document.getElementById("age-cookies-aceptar").addEventListener("click", () => {
    localStorage.setItem(CLAVE_COOKIES_ACEPTADAS, "1");
    banner.remove();
    document.body.style.paddingBottom = "";
    document.documentElement.style.setProperty("--age-cookie-banner-height", "0px");
    window.removeEventListener("resize", ajustarEspacio);
  });
}

onAuthStateChanged(auth, inyectarNav);
inyectarFooter();
inyectarBannerCookies();
