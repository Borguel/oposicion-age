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
import { activarPopover } from "/assets/popover.js";

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
  { href: "/test-generator/", label: "Tests", match: ["/test-generator/", "/test-personalizado/", "/test-oficial/", "/repetir-test/", "/preguntas-falladas/", "/preguntas-favoritas/", "/mis-tests/"] },
  { href: "/subida-pdf-pagina-principal/", label: "Herramientas IA", match: ["/subida-pdf-"] },
  { href: "/tu-tutor/", label: "Tu Tutor", match: ["/tu-tutor/"] },
  { href: "/estadisticas/", label: "Estadísticas", match: ["/estadisticas/"] },
  { href: "/planes/", label: "Planes", match: ["/planes/"] },
  { href: "/oposiciones/", label: "Oposiciones", match: ["/oposiciones/", "/oposicion-administrativo-estado-c1/", "/oposicion-gace/", "/oposicion-auxiliar-administrativo-estado/"] },
  { href: "/como-funciona/", label: "Cómo funciona", match: ["/como-funciona/"] }
];

function esEnlaceActivo(match, ruta) {
  return match.some((prefijo) => (prefijo === "/" ? ruta === "/" : ruta.startsWith(prefijo)));
}

// Construye el esqueleto de la nav una sola vez (guardado por
// nav.dataset.built). El resto de funciones (selector de oposición,
// buscador, cuenta) se reconstruyen en cada onAuthStateChanged y se
// insertan DENTRO de piezas de este esqueleto (.age-nav-utilidades,
// .age-nav-links) que persisten entre esas reconstrucciones.
//
// En escritorio, buscador + oposición + modo oscuro viven agrupados en
// el "pill" .age-nav-utilidades, separado del avatar de cuenta. En móvil
// ese grupo se oculta entero y sus piezas (más el selector de oposición
// y una fila de modo oscuro) se pintan en su lugar dentro del cajón que
// abre el menú hamburguesa (.age-nav-links) -- ver inyectarSelectorOposicion
// y construirBusquedaGlobal para la parte que insertan ellas mismas.
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
  brand.setAttribute("aria-label", "Domina tu Opo - Inicio");
  brand.innerHTML = `<img class="age-nav-brand-mark" src="/assets/favicon.svg" alt="" width="28" height="28"><span class="age-nav-brand-text">Domina tu Opo</span>`;

  const links = document.createElement("div");
  links.className = "age-nav-links";

  // Marcador de posición donde el buscador/oposición móviles se insertan
  // por delante (drawer.prepend en inyectarSelectorOposicion/
  // construirBusquedaGlobal) -- se oculta solo si queda como primer hijo
  // (es decir, si no hay sesión y no hay nada que anteponer).
  const separadorUtilidadesMovil = document.createElement("hr");
  separadorUtilidadesMovil.className = "age-nav-links-separador";
  links.appendChild(separadorUtilidadesMovil);

  const ruta = window.location.pathname;
  NAV_LINKS.forEach(({ href, label, match }) => {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = label;
    if (esEnlaceActivo(match, ruta)) a.classList.add("age-nav-active");
    links.appendChild(a);
  });

  const separadorTemaMovil = document.createElement("hr");
  separadorTemaMovil.className = "age-nav-links-separador";
  links.appendChild(separadorTemaMovil);

  const temaBtnMovil = document.createElement("button");
  temaBtnMovil.type = "button";
  temaBtnMovil.className = "age-tema-movil";
  links.appendChild(temaBtnMovil);

  const right = document.createElement("div");
  right.className = "age-nav-right";
  right.id = "age-nav-right";

  const utilidades = document.createElement("div");
  utilidades.className = "age-nav-utilidades";
  right.appendChild(utilidades);

  const temaBtn = document.createElement("button");
  temaBtn.type = "button";
  temaBtn.className = "age-nav-icon-btn age-tema-btn";
  temaBtn.id = "age-tema-btn";
  utilidades.appendChild(temaBtn);

  const actualizarIconoTema = () => {
    const oscuro = document.documentElement.dataset.theme === "dark";
    temaBtn.innerHTML = icono(oscuro ? "sol" : "luna", 18);
    temaBtn.setAttribute("aria-label", oscuro ? "Activar modo claro" : "Activar modo oscuro");
    temaBtnMovil.innerHTML = `${icono(oscuro ? "sol" : "luna", 18)}<span>${oscuro ? "Modo claro" : "Modo oscuro"}</span>`;
  };
  actualizarIconoTema();
  const alternarTema = () => {
    const oscuro = document.documentElement.dataset.theme === "dark";
    if (oscuro) {
      delete document.documentElement.dataset.theme;
      localStorage.setItem("age-theme", "light");
    } else {
      document.documentElement.dataset.theme = "dark";
      localStorage.setItem("age-theme", "dark");
    }
    actualizarIconoTema();
  };
  temaBtn.addEventListener("click", alternarTema);
  temaBtnMovil.addEventListener("click", alternarTema);

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

const MARCADOR_RESULTADOS_VACIO = `<p class="age-buscador-vacio">Escribe para buscar entre tus temas y documentos.</p>`;

// Pinta dos versiones (escritorio: icono + popover dentro de
// .age-nav-utilidades; móvil: input inline al principio del cajón del
// menú hamburguesa) que comparten la misma carga de datos y el mismo
// renderizado de resultados -- solo cambia cómo/cuándo se abren, ya que
// no hace falta sincronizar estado entre ellas (cada una filtra en
// memoria de forma independiente sobre el mismo caché).
function construirBusquedaGlobal(user) {
  const utilidades = document.querySelector(".age-nav-utilidades");
  const drawer = document.querySelector(".age-nav-links");

  utilidades?.querySelector(".age-buscador")?.remove();
  drawer?.querySelector(".age-buscador-movil")?.remove();
  if (!user) return;

  if (utilidades) {
    const buscador = document.createElement("div");
    buscador.className = "age-buscador";
    buscador.innerHTML = `
      <button type="button" class="age-nav-icon-btn" data-popover-toggle aria-label="Buscar temas y documentos">${icono("buscar", 18)}</button>
      <div class="age-popover age-buscador-panel" data-popover-panel>
        <input type="search" class="age-buscador-input" placeholder="Buscar temas o documentos…" />
        <div class="age-buscador-resultados">${MARCADOR_RESULTADOS_VACIO}</div>
      </div>
    `;
    utilidades.insertBefore(buscador, utilidades.firstChild);

    const input = buscador.querySelector(".age-buscador-input");
    const resultados = buscador.querySelector(".age-buscador-resultados");
    let temporizador = null;
    input.addEventListener("input", () => {
      clearTimeout(temporizador);
      temporizador = setTimeout(() => renderizarResultadosBusqueda(resultados, input.value), 150);
    });
    activarPopover(buscador, {
      onAbrir: async () => {
        input.focus();
        await cargarDatosBusquedaGlobal();
        renderizarResultadosBusqueda(resultados, input.value);
      },
    });
  }

  if (drawer) {
    const bloque = document.createElement("div");
    bloque.className = "age-buscador-movil";
    bloque.innerHTML = `
      <input type="search" class="age-buscador-input" placeholder="Buscar temas o documentos…" />
      <div class="age-buscador-resultados">${MARCADOR_RESULTADOS_VACIO}</div>
    `;
    drawer.prepend(bloque);

    const inputMovil = bloque.querySelector(".age-buscador-input");
    const resultadosMovil = bloque.querySelector(".age-buscador-resultados");
    let temporizadorMovil = null;
    let cargado = false;
    inputMovil.addEventListener("focus", async () => {
      if (cargado) return;
      cargado = true;
      await cargarDatosBusquedaGlobal();
      renderizarResultadosBusqueda(resultadosMovil, inputMovil.value);
    });
    inputMovil.addEventListener("input", () => {
      clearTimeout(temporizadorMovil);
      temporizadorMovil = setTimeout(() => renderizarResultadosBusqueda(resultadosMovil, inputMovil.value), 150);
    });
  }
}

// Centro de notificaciones in-app: avisos derivados de datos que ya se
// piden en otras páginas (prueba a punto de terminar, suscripción con baja
// programada, preguntas falladas pendientes de repasar), sin depender del
// permiso de notificaciones push del navegador (que además solo cubre la
// racha, ver /tareas/recordatorios-racha). Nada de esto es una colección
// nueva en Firestore -- es solo una lectura distinta de perfiles/cupos ya
// existentes, calculada de nuevo en cada carga de página.
async function calcularNotificaciones() {
  const notis = [];
  try {
    const { obtenerPlan } = await import("/assets/plan.js");
    const perfil = await obtenerPlan();
    if (perfil.prueba_activa && perfil.prueba_fin) {
      const dias = Math.ceil((new Date(perfil.prueba_fin) - new Date()) / (1000 * 60 * 60 * 24));
      if (dias <= 2) {
        notis.push({
          iconoNombre: "reloj",
          texto: dias <= 0 ? "Tu prueba gratuita termina hoy." : `Tu prueba gratuita termina en ${dias} día${dias === 1 ? "" : "s"}.`,
          href: "/planes/",
        });
      }
    }
    for (const [op, sub] of Object.entries(perfil.suscripciones || {})) {
      if (sub && sub.cancelar_al_final_periodo && sub.current_period_end) {
        const fecha = new Date(sub.current_period_end).toLocaleDateString("es-ES", { day: "numeric", month: "long" });
        notis.push({
          iconoNombre: "salir",
          texto: `Tu plan en ${op} se cancela el ${fecha}.`,
          href: "/mi-cuenta/",
        });
      }
    }
  } catch (e) { /* sin perfil disponible: se omiten estos avisos, no rompe el resto */ }

  try {
    const token = await idToken();
    const oposicion = obtenerOposicionActual();
    const res = await fetch(`${BACKEND_URL}/preguntas-pendientes-repaso?oposicion=${encodeURIComponent(oposicion)}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (res.ok) {
      const { total_pendientes } = await res.json();
      if (total_pendientes) {
        const plural = total_pendientes === 1 ? "" : "s";
        notis.push({
          iconoNombre: "estrella",
          texto: `Tienes ${total_pendientes} pregunta${plural} fallada${plural} sin repasar.`,
          href: "/repasar-preguntas/",
        });
      }
    }
  } catch (e) { /* igual: se omite este aviso concreto si falla */ }

  return notis;
}

function renderizarNotificaciones(lista, notis) {
  if (!notis.length) {
    lista.innerHTML = `<p class="age-buscador-vacio">No tienes avisos pendientes.</p>`;
    return;
  }
  lista.innerHTML = notis.map((n) => `
    <a class="age-notificaciones-item" href="${n.href}">
      <span class="age-notificaciones-item-icono">${icono(n.iconoNombre, 17)}</span>
      <span>${escapeHtmlBuscador(n.texto)}</span>
    </a>
  `).join("");
}

function construirNotificaciones(user) {
  const utilidades = document.querySelector(".age-nav-utilidades");
  utilidades?.querySelector(".age-notificaciones")?.remove();
  if (!utilidades || !user) return;

  const cont = document.createElement("div");
  cont.className = "age-notificaciones";
  cont.innerHTML = `
    <button type="button" class="age-nav-icon-btn" data-popover-toggle aria-label="Notificaciones">${icono("campana", 18)}<span class="age-notificaciones-badge" hidden></span></button>
    <div class="age-popover age-notificaciones-panel" data-popover-panel>
      <div class="age-notificaciones-lista"><p class="age-buscador-vacio">Cargando…</p></div>
    </div>
  `;
  utilidades.appendChild(cont);

  const badge = cont.querySelector(".age-notificaciones-badge");
  const lista = cont.querySelector(".age-notificaciones-lista");
  const promesaNotis = calcularNotificaciones().then((notis) => {
    if (notis.length) {
      badge.hidden = false;
      badge.textContent = String(notis.length);
    }
    return notis;
  }).catch(() => []);

  activarPopover(cont, {
    onAbrir: async () => renderizarNotificaciones(lista, await promesaNotis),
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
      <button type="button" class="age-account-btn" data-popover-toggle>
        <span class="age-account-avatar">${inicial}</span>
        <span class="age-account-nombre" id="age-account-nombre"></span>
        <span class="age-account-caret">▾</span>
      </button>
      <div class="age-popover age-account-menu" data-popover-panel>
        <a href="/zona-opositor/">${icono("diana")} Zona opositor</a>
        <a href="/mi-cuenta/">${icono("usuario")} Mi cuenta</a>
        <a href="/planes/">${icono("tarjeta")} Planes</a>
        <div class="age-account-menu-divider"></div>
        <button type="button" data-account-logout>${icono("salir")} Cerrar sesión</button>
      </div>
    `;
    activarPopover(acc);
    acc.querySelector("[data-account-logout]").addEventListener("click", async () => {
      await signOut();
      window.location.href = "/";
    });

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
    <p>${icono("correo", 16)} Confirma tu correo electrónico (<strong>${user.email}</strong>) para proteger tu cuenta. Revisa tu bandeja de entrada (y la carpeta de spam).</p>
    <div class="age-verificacion-banner-acciones">
      <button type="button" class="age-btn age-btn-outline" id="age-verificacion-reenviar">Reenviar correo</button>
      <button type="button" class="age-verificacion-banner-cerrar" id="age-verificacion-cerrar" aria-label="Cerrar aviso">${icono("cruz", 15)}</button>
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

// Aviso de cuenta atrás de la prueba gratuita de 7 días (mientras está
// activa) o de bloqueo total (si terminó sin contratar ningún plan) --
// mismo patrón que inyectarBannerVerificacion/inyectarBannerGlobal. Se
// importa plan.js de forma perezosa (como el widget de Tu Tutor) para no
// crear una dependencia estática circular con este propio módulo (plan.js
// ya importa idToken/esperarUsuario de aquí).
const CLAVE_BANNER_PRUEBA_CERRADO = "age_banner_prueba_cerrado";

async function inyectarBannerPrueba(user) {
  const existente = document.querySelector(".age-banner-prueba");
  if (existente) existente.remove();
  if (!user) return;

  // forzarRefresco=true a propósito: este aviso decide si se bloquea al
  // usuario en toda la web, así que nunca debe fiarse de una respuesta
  // guardada en sessionStorage de antes de un cambio de plan/prueba (p.ej.
  // justo después de pagar, o de un fix de backend como el bypass de
  // administrador) -- solo se pinta una vez por carga de página, así que
  // el coste de la petición extra a /mi-perfil es asumible.
  const { obtenerPlan } = await import("/assets/plan.js");
  const perfil = await obtenerPlan(true);

  const banner = document.createElement("div");
  banner.className = "age-banner-prueba";

  if (perfil.plan === "gratis") {
    // Prueba terminada y sin ningún plan de pago: aviso fijo, no se puede
    // cerrar -- refuerza en toda la web el bloqueo que ya aplican las
    // páginas de herramientas por su cuenta (ver assets/plan.js).
    banner.classList.add("age-banner-prueba-bloqueado");
    banner.innerHTML = `
      <p>Tu prueba gratuita ha terminado. Elige un plan para seguir usando Domina tu Opo.</p>
      <a class="age-btn age-btn-primary" href="/planes/">Ver planes</a>
    `;
    document.body.prepend(banner);
    return;
  }

  if (!perfil.prueba_activa || !perfil.prueba_fin) return;
  if (sessionStorage.getItem(CLAVE_BANNER_PRUEBA_CERRADO) === "1") return;

  const diasRestantes = Math.max(0, Math.ceil((new Date(perfil.prueba_fin) - new Date()) / 86400000));
  const texto = diasRestantes === 0
    ? "Tu prueba gratuita termina hoy."
    : `Te quedan ${diasRestantes} día${diasRestantes === 1 ? "" : "s"} de prueba gratuita del plan Premium.`;

  banner.innerHTML = `
    <p>${icono("regalo", 16)} ${texto}</p>
    <div class="age-banner-prueba-acciones">
      <a class="age-btn age-btn-outline" href="/planes/">Ver planes</a>
      <button type="button" class="age-verificacion-banner-cerrar" id="age-prueba-cerrar" aria-label="Cerrar aviso">${icono("cruz", 15)}</button>
    </div>
  `;
  document.body.prepend(banner);
  document.getElementById("age-prueba-cerrar").addEventListener("click", () => {
    sessionStorage.setItem(CLAVE_BANNER_PRUEBA_CERRADO, "1");
    banner.remove();
  });
}

// Aviso de promoción/descuento temporal, configurable desde el panel de
// administración (ver blueprints/admin.py + promociones.py). A diferencia
// de inyectarBannerPrueba (que solo aplica con sesión), este se muestra
// también a quien navega sin haber iniciado sesión -- es publicidad, no un
// aviso de cuenta -- y se oculta por completo a quien, con sesión, ya tenga
// el plan de la promoción activo (pagado o en prueba: planCubre no
// distingue, igual que el resto del gating de plan.js).
const CLAVE_BANNER_PROMO_CERRADO = "age_banner_promo_cerrado";
let _promoIntervalo = null;

function formatearCuentaAtrasPromo(msRestantes) {
  const totalSeg = Math.max(0, Math.floor(msRestantes / 1000));
  const d = Math.floor(totalSeg / 86400);
  const h = Math.floor((totalSeg % 86400) / 3600);
  const m = Math.floor((totalSeg % 3600) / 60);
  const s = totalSeg % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return [[d, "d"], [h, "h"], [m, "m"], [s, "s"]]
    .map(([valor, unidad]) => `<span class="age-banner-promo-chip">${pad(valor)}${unidad}</span>`)
    .join('<span class="age-banner-promo-sep">:</span>');
}

async function inyectarBannerPromocion(user) {
  const existente = document.querySelector(".age-banner-promo");
  if (existente) existente.remove();
  if (_promoIntervalo) { clearInterval(_promoIntervalo); _promoIntervalo = null; }
  if (sessionStorage.getItem(CLAVE_BANNER_PROMO_CERRADO) === "1") return;

  let promo;
  try {
    const resp = await fetch(`${BACKEND_URL}/promocion-activa`);
    if (!resp.ok) return;
    promo = await resp.json();
  } catch (e) { return; }
  if (!promo.activo) return;

  if (user) {
    const [{ obtenerPlan, planCubre }] = await Promise.all([import("/assets/plan.js")]);
    const perfil = await obtenerPlan();
    if (planCubre(perfil.plan, promo.plan)) return; // ya tiene este plan (o uno mejor): no le sale nada
  }

  const nombrePlan = promo.plan === "premium" ? "Premium" : "Básico";
  const mensaje = promo.mensaje
    || `${promo.descuento_pct}% de descuento en el plan ${nombrePlan}${promo.duracion_texto ? " durante " + promo.duracion_texto : ""}`;

  const banner = document.createElement("div");
  banner.className = "age-banner-promo";
  banner.setAttribute("role", "status");
  banner.innerHTML = `
    <span class="age-banner-promo-texto">${icono("destellos", 16)} <strong>${escapeHtmlBuscador(mensaje)}</strong></span>
    <span class="age-banner-promo-cuenta" id="age-promo-cuenta" aria-hidden="true"></span>
    <div class="age-banner-promo-acciones">
      <a class="age-btn age-btn-primary" href="/planes/">Ver planes</a>
      <button type="button" class="age-banner-promo-cerrar" id="age-promo-cerrar" aria-label="Cerrar aviso">${icono("cruz", 15)}</button>
    </div>
  `;
  document.body.prepend(banner);

  document.getElementById("age-promo-cerrar").addEventListener("click", () => {
    sessionStorage.setItem(CLAVE_BANNER_PROMO_CERRADO, "1");
    if (_promoIntervalo) clearInterval(_promoIntervalo);
    banner.remove();
  });

  if (promo.fecha_fin) {
    const cuentaEl = document.getElementById("age-promo-cuenta");
    const fin = new Date(promo.fecha_fin).getTime();
    const actualizar = () => {
      const restante = fin - Date.now();
      if (restante <= 0) {
        clearInterval(_promoIntervalo);
        _promoIntervalo = null;
        banner.remove();
        return;
      }
      cuentaEl.innerHTML = formatearCuentaAtrasPromo(restante);
    };
    actualizar();
    _promoIntervalo = setInterval(actualizar, 1000);
  }
}

// Páginas a las que solo se llega pinchando algo dentro de Zona Opositor
// (generar test, herramientas IA, mis tests...) -- en todas ellas se ofrece
// un enlace directo de vuelta, para no depender de la navegación principal
// (colapsada tras el menú hamburguesa en móvil).
const PAGINAS_CON_VOLVER_ZONA_OPOSITOR = [
  "/test-generator/", "/test-personalizado/", "/test-oficial/",
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
  enlace.className = "age-nav-icon-btn age-volver-zona-btn";
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
  construirNotificaciones(user);
  construirMenuCuenta(user);
  inyectarBannerVerificacion(user);
  inyectarBannerPrueba(user);
  inyectarVolverZonaOpositor(user);
  inyectarEnlaceAdmin(user);
  inyectarBannerGlobal();
  inyectarBannerPromocion(user);
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
  "/test-generator/", "/test-personalizado/", "/test-oficial/",
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
    <a href="/aviso-legal/">Aviso legal</a>
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
