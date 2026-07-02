// Firebase Authentication (email + contraseña) + inyección del enlace de
// cuenta/login en la barra de navegación compartida (.age-nav). Se importa
// como módulo en cada página del frontend.
import { initializeApp } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut as firebaseSignOut
} from "https://www.gstatic.com/firebasejs/10.13.0/firebase-auth.js";
import { firebaseConfig } from "/assets/firebase-config.js";

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);

export function signIn(email, password) {
  return signInWithEmailAndPassword(auth, email, password);
}

export function signUp(email, password) {
  return createUserWithEmailAndPassword(auth, email, password);
}

export function signOut() {
  sessionStorage.removeItem("age_plan_cache");
  return firebaseSignOut(auth);
}

// Token que hay que mandar como "Authorization: Bearer <token>" en cada
// fetch() a una ruta protegida del backend. Devuelve null si no hay sesión.
export async function idToken() {
  return auth.currentUser ? await auth.currentUser.getIdToken() : null;
}

// Espera a que Firebase resuelva el estado inicial de sesión (evita
// redirecciones prematuras a /login/ mientras el SDK todavía está
// comprobando si hay una sesión guardada).
export function esperarUsuario() {
  return new Promise((resolve) => {
    const quitar = onAuthStateChanged(auth, (user) => {
      quitar();
      resolve(user);
    });
  });
}

function inyectarNav(user) {
  const nav = document.querySelector(".age-nav");
  if (!nav) return;

  let enlacePlanes = nav.querySelector("[data-nav-planes]");
  if (!enlacePlanes) {
    enlacePlanes = document.createElement("a");
    enlacePlanes.href = "/planes/";
    enlacePlanes.textContent = "💳 Planes";
    enlacePlanes.setAttribute("data-nav-planes", "");
    nav.appendChild(enlacePlanes);
  }

  let enlaceCuenta = nav.querySelector("[data-nav-cuenta]");
  if (!enlaceCuenta) {
    enlaceCuenta = document.createElement("a");
    enlaceCuenta.setAttribute("data-nav-cuenta", "");
    nav.appendChild(enlaceCuenta);
  }

  if (user) {
    enlaceCuenta.href = "/mi-cuenta/";
    enlaceCuenta.textContent = "👤 Mi cuenta";
  } else {
    const destino = encodeURIComponent(window.location.pathname);
    enlaceCuenta.href = `/login/?next=${destino}`;
    enlaceCuenta.textContent = "🔑 Iniciar sesión";
  }
}

onAuthStateChanged(auth, inyectarNav);
