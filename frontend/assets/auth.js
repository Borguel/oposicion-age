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
  getAdditionalUserInfo,
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
  { href: "/test-generator/", label: "Tests", match: ["/test-generator/", "/repetir-test/", "/preguntas-falladas/"] },
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
        <a href="/mi-cuenta/">👤 Mi cuenta</a>
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
  `;
  document.body.appendChild(footer);
}

onAuthStateChanged(auth, inyectarNav);
inyectarFooter();
