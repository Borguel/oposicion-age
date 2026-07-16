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
  linkWithCredential,
  verifyBeforeUpdateEmail,
  reauthenticateWithCredential,
  updatePassword,
  signOut as firebaseSignOut
} from "https://www.gstatic.com/firebasejs/10.13.0/firebase-auth.js";
import { firebaseConfig, BACKEND_URL } from "/assets/firebase-config.js";
import { inyectarSelectorOposicion, obtenerOposicionActual } from "/assets/oposicion.js";
import { icono } from "/assets/icons.js";
import { iniciarAnalitica, CLAVE_COOKIES_ACEPTADAS } from "/assets/analytics.js";

const app = initializeApp(firebaseConfig);
export const auth = getAuth(app);
const googleProvider = new GoogleAuthProvider();

export function signIn(email, password) {
  return signInWithEmailAndPassword(auth, email, password);
}

export function signUp(email, password) {
  return createUserWithEmailAndPassword(auth, email, password);
}

// Envía (o reenvía) el correo de verificación de dirección. No bloquea el
// uso de la web -- solo se avisa con un banner (ver inyectarBannerVerificacion)
// para que quien se registró con un correo que no controla no quede
// atrapado sin poder confirmar nunca. Lo genera Firebase Admin y lo manda
// por Brevo (ver blueprints/auth_publico.py) en vez de sendEmailVerification
// del SDK de cliente, que llegaba sin marca, en inglés y desde un remitente
// que varios proveedores de correo marcan como spam.
export async function enviarVerificacionEmail() {
  const token = await idToken();
  if (!token) throw new Error("No hay sesión activa.");
  const res = await fetch(`${BACKEND_URL}/enviar-verificacion-email`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!res.ok) throw new Error("No se pudo enviar el correo de verificación.");
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

// Cambia la contraseña directamente (a diferencia del correo, no hace falta
// confirmación por email: Firebase ya exige haberse reautenticado hace poco
// para poder llamar a esto, que es la propia prueba de que eres tú).
export function cambiarContrasena(nuevaContrasena) {
  return updatePassword(auth.currentUser, nuevaContrasena);
}

// Pide al backend el correo de "restablecer contraseña" (lo genera con
// Firebase Admin y lo manda por Brevo -- ver blueprints/auth_publico.py, así
// tiene la misma imagen de marca que el resto de correos transaccionales en
// vez del que manda Firebase por su cuenta). El backend NUNCA dice si el
// correo existe o no (para no filtrar qué correos están registrados), así
// que desde fuera siempre se resuelve igual salvo un fallo de red real.
const PATRON_EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export async function recuperarContrasena(email) {
  if (!PATRON_EMAIL.test(email)) {
    throw { code: "auth/invalid-email" };
  }
  await fetch(`${BACKEND_URL}/recuperar-contrasena`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
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

// ¿Es administrador? Lee el custom claim `admin` del token del usuario
// actual (getIdTokenResult). Solo sirve para MOSTRAR/OCULTAR el enlace al
// panel -- la protección real está en el backend (requiere_admin en cada
// ruta /admin/*). Nunca fiarse solo de esto en el cliente.
export async function esAdmin() {
  const user = await esperarUsuario();
  if (!user) return false;
  try {
    const resultado = await user.getIdTokenResult();
    return resultado.claims.admin === true;
  } catch {
    return false;
  }
}

// Permisos del panel (admin + roles granulares). Devuelve {admin, permisos}.
// El super-admin tiene todos los permisos implícitamente. Igual que esAdmin,
// esto es solo para MOSTRAR/OCULTAR partes del panel; el backend valida.
export async function obtenerPermisos() {
  const PERMISOS = ["temario", "reportes", "usuarios"];
  const user = await esperarUsuario();
  if (!user) return { admin: false, permisos: [] };
  try {
    const { claims } = await user.getIdTokenResult();
    if (claims.admin === true) return { admin: true, permisos: [...PERMISOS] };
    const permisos = Array.isArray(claims.permisos) ? claims.permisos.filter((p) => PERMISOS.includes(p)) : [];
    return { admin: false, permisos };
  } catch {
    return { admin: false, permisos: [] };
  }
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

// Cabecera lista para usar en cualquier fetch() a una ruta protegida del
// backend -- si no hay sesión, redirige a /login/ (con "next" de vuelta a
// la página actual) y devuelve null, para que quien llama solo tenga que
// comprobar "if (!authHeaders) return;". Antes esta misma función estaba
// copiada y pegada en 13 páginas distintas.
export async function obtenerAuthHeaders() {
  const token = await idToken();
  if (!token) {
    window.location.href = "/login/?next=" + encodeURIComponent(window.location.pathname);
    return null;
  }
  return { "Authorization": "Bearer " + token };
}

// ============================================================
// Barra de navegación: se construye entera desde aquí (una sola
// fuente de verdad) en vez de repetir <a> sueltos en cada página.
// ============================================================
const NAV_LINKS = [
  { href: "/", label: "Inicio", match: ["/"] },
  { href: "/zona-opositor/", label: "Zona opositor", match: ["/zona-opositor/"] },
  { href: "/test-generator/", label: "Tests", match: ["/test-generator/", "/test-personalizado/", "/test-oficial/", "/test-inteligente/", "/repetir-test/", "/preguntas-falladas/", "/preguntas-favoritas/", "/mis-tests/"] },
  { href: "/subida-pdf-pagina-principal/", label: "Herramientas IA", match: ["/subida-pdf-"] },
  { href: "/tu-tutor/", label: "Tu Tutor", match: ["/tu-tutor/"] },
  { href: "/estadisticas/", label: "Estadísticas", match: ["/estadisticas/"] },
  { href: "/planes/", label: "Planes", match: ["/planes/"] }
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
  brand.innerHTML = `<img class="age-nav-brand-mark" src="/assets/favicon.svg" alt="" width="28" height="28"><span class="age-nav-brand-text">Domina tu Opo</span>`;

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

  const temaBtn = document.createElement("button");
  temaBtn.type = "button";
  temaBtn.className = "age-tema-btn";
  temaBtn.id = "age-tema-btn";
  const actualizarIconoTema = () => {
    const oscuro = document.documentElement.dataset.theme === "dark";
    temaBtn.innerHTML = icono(oscuro ? "sol" : "luna", 18);
    temaBtn.setAttribute("aria-label", oscuro ? "Activar modo claro" : "Activar modo oscuro");
  };
  actualizarIconoTema();
  temaBtn.addEventListener("click", () => {
    const oscuro = document.documentElement.dataset.theme === "dark";
    if (oscuro) {
      delete document.documentElement.dataset.theme;
      localStorage.setItem("age-theme", "light");
    } else {
      document.documentElement.dataset.theme = "dark";
      localStorage.setItem("age-theme", "dark");
    }
    actualizarIconoTema();
  });
  right.appendChild(temaBtn);

  const burger = document.createElement("button");
  burger.type = "button";
  burger.className = "age-nav-burger";
  burger.setAttribute("aria-label", "Abrir menú");
  burger.setAttribute("aria-expanded", "false");
  burger.innerHTML = icono("menu", 22);
  burger.addEventListener("click", () => {
    const abierto = links.classList.toggle("open");
    burger.setAttribute("aria-expanded", String(abierto));
  });

  inner.appendChild(brand);
  inner.appendChild(links);
  inner.appendChild(right);
  inner.appendChild(burger);
  nav.appendChild(inner);
}

// ============================================================
// Buscador global: filtra en el cliente entre los temas del temario y
// los documentos subidos por el usuario (ambos ya expuestos por rutas
// existentes -- /temas-disponibles y /mis-documentos). Se cargan una
// sola vez por sesión de página y se filtran en memoria en cada tecla,
// sin volver a pedirlos al backend.
let cacheBusquedaGlobal = null;

function escapeHtmlBuscador(texto) {
  const div = document.createElement("div");
  div.textContent = texto == null ? "" : String(texto);
  return div.innerHTML;
}

function normalizarBusqueda(texto) {
  return (texto || "").toString().toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");
}

async function cargarDatosBusquedaGlobal() {
  if (cacheBusquedaGlobal) return cacheBusquedaGlobal;
  const token = await idToken();
  if (!token) return { temas: [], documentos: [] };
  try {
    const oposicion = obtenerOposicionActual();
    const [resTemas, resDocs] = await Promise.all([
      fetch(`${BACKEND_URL}/temas-disponibles?oposicion=${encodeURIComponent(oposicion)}`, { headers: { Authorization: `Bearer ${token}` } }),
      fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } })
    ]);
    const temas = resTemas.ok ? (await resTemas.json()).temas || [] : [];
    const documentos = resDocs.ok ? (await resDocs.json()).documentos || [] : [];
    cacheBusquedaGlobal = { temas, documentos };
  } catch (e) {
    cacheBusquedaGlobal = { temas: [], documentos: [] };
  }
  return cacheBusquedaGlobal;
}

function renderizarResultadosBusqueda(contenedor, query) {
  const q = normalizarBusqueda(query.trim());
  if (!q) {
    contenedor.innerHTML = `<p class="age-buscador-vacio">Escribe para buscar entre tus temas y documentos.</p>`;
    return;
  }
  const { temas, documentos } = cacheBusquedaGlobal || { temas: [], documentos: [] };
  const temasCoinciden = temas.filter((t) => normalizarBusqueda(t.titulo).includes(q)).slice(0, 6);
  const docsCoinciden = documentos.filter((d) => normalizarBusqueda(d.titulo || d.nombre_archivo).includes(q)).slice(0, 6);

  if (temasCoinciden.length === 0 && docsCoinciden.length === 0) {
    contenedor.innerHTML = `<p class="age-buscador-vacio">Sin resultados para "${escapeHtmlBuscador(query)}".</p>`;
    return;
  }

  const bloques = [];
  if (temasCoinciden.length) {
    bloques.push(`
      <div class="age-buscador-grupo">
        <p class="age-buscador-grupo-titulo">Temas</p>
        ${temasCoinciden.map((t) => `<a class="age-buscador-item" href="/test-personalizado/?temas=${encodeURIComponent(t.id)}"><span class="age-buscador-item-tag">Tema</span>${escapeHtmlBuscador(t.titulo)}</a>`).join("")}
      </div>
    `);
  }
  if (docsCoinciden.length) {
    bloques.push(`
      <div class="age-buscador-grupo">
        <p class="age-buscador-grupo-titulo">Documentos</p>
        ${docsCoinciden.map((d) => `<a class="age-buscador-item" href="/mis-documentos/?q=${encodeURIComponent(d.nombre_archivo || d.titulo || "")}"><span class="age-buscador-item-tag">PDF</span>${escapeHtmlBuscador(d.titulo || d.nombre_archivo || "Documento")}</a>`).join("")}
      </div>
    `);
  }
  contenedor.innerHTML = bloques.join("");
}

function construirBusquedaGlobal(user) {
  const right = document.getElementById("age-nav-right");
  if (!right) return;

  let buscador = right.querySelector(".age-buscador");
  if (buscador) buscador.remove();
  if (!user) return;

  buscador = document.createElement("div");
  buscador.className = "age-buscador";
  buscador.innerHTML = `
    <button type="button" class="age-buscador-btn" aria-label="Buscar temas y documentos">${icono("buscar", 18)}</button>
    <div class="age-buscador-panel">
      <input type="search" class="age-buscador-input" placeholder="Buscar temas o documentos…" />
      <div class="age-buscador-resultados"><p class="age-buscador-vacio">Escribe para buscar entre tus temas y documentos.</p></div>
    </div>
  `;
  right.insertBefore(buscador, right.firstChild);

  const input = buscador.querySelector(".age-buscador-input");
  const resultados = buscador.querySelector(".age-buscador-resultados");
  let temporizador = null;

  buscador.querySelector(".age-buscador-btn").addEventListener("click", async (evento) => {
    evento.stopPropagation();
    const abriendo = !buscador.classList.contains("open");
    buscador.classList.toggle("open");
    if (abriendo) {
      input.focus();
      await cargarDatosBusquedaGlobal();
      renderizarResultadosBusqueda(resultados, input.value);
    }
  });

  input.addEventListener("input", () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(() => renderizarResultadosBusqueda(resultados, input.value), 150);
  });
  input.addEventListener("click", (evento) => evento.stopPropagation());

  document.addEventListener("click", () => buscador.classList.remove("open"));
  document.addEventListener("keydown", (evento) => {
    if (evento.key === "Escape") buscador.classList.remove("open");
  });
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
        <span class="age-account-nombre" id="age-account-nombre"></span>
        <span class="age-account-caret">▾</span>
      </button>
      <div class="age-account-menu">
        <a href="/zona-opositor/">${icono("diana")} Zona opositor</a>
        <a href="/mi-cuenta/">${icono("usuario")} Mi cuenta</a>
        <a href="/planes/">${icono("tarjeta")} Planes</a>
        <div class="age-account-menu-divider"></div>
        <button type="button" data-account-logout>${icono("salir")} Cerrar sesión</button>
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

    // El nombre solo se muestra (vía CSS) en pantallas no móviles, junto al
    // avatar con la inicial; en móvil se deja solo la inicial para no comerse
    // espacio. Se pide con obtenerPlan(), que ya cachea en sessionStorage, así
    // que en la mayoría de páginas no supone una llamada nueva al backend.
    import("/assets/plan.js").then(({ obtenerPlan }) => {
      obtenerPlan().then(({ nombre }) => {
        const nombreEl = document.getElementById("age-account-nombre");
        if (nombreEl && nombre) nombreEl.textContent = nombre;
      }).catch(() => {});
    });
  } else {
    const destino = encodeURIComponent(window.location.pathname);
    acc.innerHTML = `<a class="age-btn age-btn-primary" style="padding:9px 18px;font-size:13.5px;" href="/login/?next=${destino}">Iniciar sesión</a>`;
  }
}

// Aviso no bloqueante para quien todavía no ha confirmado su correo (solo
// aplica a cuentas por contraseña -- una cuenta de Google ya viene con el
// correo verificado por el propio proveedor). Se puede cerrar y no vuelve a
// salir en lo que dure la pestaña, para no ser pesado en cada página.
const CLAVE_BANNER_VERIFICACION_CERRADO = "age_banner_verificacion_cerrado";

function inyectarBannerVerificacion(user) {
  const existente = document.querySelector(".age-verificacion-banner");
  if (existente) existente.remove();

  if (!user || user.emailVerified) return;
  if (!user.providerData.some((p) => p.providerId === "password")) return;
  if (sessionStorage.getItem(CLAVE_BANNER_VERIFICACION_CERRADO) === "1") return;

  const banner = document.createElement("div");
  banner.className = "age-verificacion-banner";
  banner.innerHTML = `
    <p>📧 Confirma tu correo electrónico (<strong>${user.email}</strong>) para proteger tu cuenta. Revisa tu bandeja de entrada (y la carpeta de spam).</p>
    <div class="age-verificacion-banner-acciones">
      <button type="button" class="age-btn age-btn-outline" id="age-verificacion-reenviar">Reenviar correo</button>
      <button type="button" class="age-verificacion-banner-cerrar" id="age-verificacion-cerrar" aria-label="Cerrar aviso">✕</button>
    </div>
    <p class="age-verificacion-banner-error" id="age-verificacion-error" style="display:none;">No se pudo enviar el correo. Inténtalo de nuevo en unos segundos.</p>
  `;
  document.body.prepend(banner);

  document.getElementById("age-verificacion-reenviar").addEventListener("click", async (evento) => {
    const boton = evento.currentTarget;
    const mensajeError = document.getElementById("age-verificacion-error");
    mensajeError.style.display = "none";
    boton.disabled = true;
    boton.textContent = "Enviando…";
    try {
      await enviarVerificacionEmail();
      boton.textContent = "Correo enviado";
    } catch (e) {
      boton.textContent = "Reenviar correo";
      boton.disabled = false;
      mensajeError.style.display = "block";
    }
  });
  document.getElementById("age-verificacion-cerrar").addEventListener("click", () => {
    sessionStorage.setItem(CLAVE_BANNER_VERIFICACION_CERRADO, "1");
    banner.remove();
  });
}

// Páginas a las que solo se llega pinchando algo dentro de Zona Opositor
// (generar test, herramientas IA, mis tests...) -- en todas ellas se ofrece
// un enlace directo de vuelta, para no depender de la navegación principal
// (colapsada tras el menú hamburguesa en móvil).
const PAGINAS_CON_VOLVER_ZONA_OPOSITOR = [
  "/test-generator/", "/test-personalizado/", "/test-oficial/", "/test-inteligente/",
  "/repetir-test/", "/preguntas-falladas/", "/preguntas-favoritas/",
  "/mis-tests/", "/mis-documentos/",
  "/subida-pdf-",
  "/tu-tutor/",
  "/estadisticas/",
  "/ranking/",
  "/mi-cuenta/"
];

function inyectarVolverZonaOpositor(user) {
  const right = document.getElementById("age-nav-right");
  if (!right) return;
  const existente = right.querySelector(".age-volver-zona-btn");
  if (existente) existente.remove();
  if (!user) return;

  const ruta = window.location.pathname;
  if (!PAGINAS_CON_VOLVER_ZONA_OPOSITOR.some((prefijo) => ruta.startsWith(prefijo))) return;

  const enlace = document.createElement("a");
  enlace.className = "age-volver-zona-btn";
  enlace.href = "/zona-opositor/";
  enlace.setAttribute("aria-label", "Volver a Zona opositor");
  enlace.title = "Volver a Zona opositor";
  enlace.innerHTML = icono("atras", 18);
  right.insertBefore(enlace, right.firstChild);
}

// Enlace "Panel Admin" en la barra de navegación, visible solo si el
// usuario tiene el claim admin. Se añade de forma asíncrona (esAdmin lee el
// token) y es puramente cosmético: el backend rechaza igualmente a quien no
// sea admin aunque manipule el DOM para que aparezca el enlace.
async function inyectarEnlaceAdmin(user) {
  const links = document.querySelector(".age-nav-links");
  if (!links) return;
  const existente = links.querySelector("[data-admin-link]");
  if (existente) existente.remove();
  if (!user) return;
  const { admin, permisos } = await obtenerPermisos();
  if (!admin && permisos.length === 0) return;

  const enlace = document.createElement("a");
  enlace.href = "/admin/";
  enlace.textContent = admin ? "Panel Admin" : "Panel equipo";
  enlace.dataset.adminLink = "1";
  if (window.location.pathname.startsWith("/admin/")) enlace.classList.add("age-nav-active");
  links.appendChild(enlace);
}

function inyectarNav(user) {
  construirEsqueletoNav();
  inyectarSelectorOposicion(!!user);
  construirBusquedaGlobal(user);
  construirMenuCuenta(user);
  inyectarBannerVerificacion(user);
  inyectarVolverZonaOpositor(user);
  inyectarEnlaceAdmin(user);
  inyectarBannerGlobal();
  inyectarWidgetTutor(user);
}

// Páginas de estudio en las que aparece la burbuja flotante de Tu Tutor
// (abajo a la derecha) para poder preguntarle sin salir de la página. Se
// excluye a propósito la propia /tu-tutor/ (ahí ya está el chat a pantalla
// completa) y cualquier página fuera de esta lista (home, login, admin,
// legales, planes...). El widget se importa de forma perezosa: solo se
// descarga su código en las páginas donde de verdad se usa.
const PAGINAS_CON_WIDGET_TUTOR = [
  "/zona-opositor/",
  "/test-generator/", "/test-personalizado/", "/test-oficial/", "/test-inteligente/",
  "/repetir-test/", "/preguntas-falladas/", "/preguntas-favoritas/", "/mis-tests/",
  "/subida-pdf-", "/mis-documentos/", "/estadisticas/",
];

function inyectarWidgetTutor(user) {
  if (!user) return;
  const ruta = window.location.pathname;
  if (ruta.startsWith("/tu-tutor/")) return; // ya es el chat completo
  if (!PAGINAS_CON_WIDGET_TUTOR.some((prefijo) => ruta.startsWith(prefijo))) return;
  import("/assets/tutor-widget.js")
    .then(({ montarWidgetTutor }) => montarWidgetTutor())
    .catch(() => { /* si no carga, la página sigue funcionando igual */ });
}

// Aviso global configurable desde el panel de administración. Lectura
// pública (sin token). Se muestra una sola vez por carga, arriba del todo.
async function inyectarBannerGlobal() {
  if (document.querySelector(".age-banner-global")) return;
  try {
    const resp = await fetch(`${BACKEND_URL}/banner-global`);
    if (!resp.ok) return;
    const b = await resp.json();
    if (!b.activo || !b.texto) return;
    const barra = document.createElement("div");
    barra.className = `age-banner-global age-banner-${b.tipo || "info"}`;
    barra.setAttribute("role", "status");
    barra.textContent = b.texto;
    document.body.insertBefore(barra, document.body.firstChild);
  } catch (e) { /* si falla, no pasa nada: la web sigue igual */ }
}

function inyectarFooter() {
  if (document.querySelector(".age-footer")) return;
  const footer = document.createElement("footer");
  footer.className = "age-footer";
  const anio = new Date().getFullYear();
  footer.innerHTML = `
    <span>© ${anio} Domina tu Opo</span>
    <a href="/terminos/">Términos y condiciones</a>
    <a href="/privacidad/">Privacidad</a>
    <a href="/cookies/">Cookies</a>
  `;
  document.body.appendChild(footer);
}

function inyectarBannerCookies() {
  if (localStorage.getItem(CLAVE_COOKIES_ACEPTADAS) === "1") return;
  if (document.querySelector(".age-cookies-banner")) return;

  const banner = document.createElement("div");
  banner.className = "age-cookies-banner";
  banner.innerHTML = `
    <p>
      Usamos almacenamiento técnico necesario para que puedas iniciar sesión y usar la web
      (por ejemplo, para recordar tu sesión y la oposición que estás estudiando), y analítica
      propia para entender el uso de la web y mejorarla. No usamos cookies de publicidad.
      Más información en nuestra <a href="/cookies/">Política de Cookies</a>.
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
    window.dispatchEvent(new Event("age-cookies-aceptadas"));
  });
}

onAuthStateChanged(auth, inyectarNav);
inyectarFooter();
inyectarBannerCookies();
iniciarAnalitica(auth);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
