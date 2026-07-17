// Guardado automático y reanudación de tests en curso -- módulo compartido
// por test-generator, repetir-test, preguntas-falladas y
// subida-pdf-generar-test para que cerrar la pestaña a media pregunta no
// pierda el progreso: el test se autoguarda mientras se hace (marcado
// "en_progreso" en Firestore, bajo el mismo test_id en toda su vida) y puede
// retomarse exactamente donde se dejó desde "Mis Tests".
import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";
import { icono } from "/assets/icons.js";

let testIdActual = null;
let temporizadorDebounce = null;
let temporizadorDebounceContenido = null;

// Modo offline resiliente: red de seguridad local ante cortes de conexión
// mientras se hace un test. NO sustituye el autoguardado real en Firestore
// (que sigue siendo la fuente de verdad para "Mis Tests"/reanudar desde
// otro dispositivo) -- solo evita perder el progreso de ESTA pestaña si el
// autoguardado falla por falta de red, guardando una copia combinada en
// localStorage y reintentando el envío en cuanto vuelve la conexión.
const PREFIJO_OFFLINE = "age_test_offline_";

function claveOffline(testId) {
  return `${PREFIJO_OFFLINE}${testId}`;
}

// Igual que hace el backend (test_ref.set(campos, merge=True)): cada
// autoguardado solo trae los campos que cambian (p. ej. autoguardarProgreso
// nunca manda "contenido"), así que la copia local se combina con la
// anterior en vez de sobrescribirla entera -- si no, un autoguardado
// parcial posterior borraría el "contenido" ya guardado por el primero.
function guardarCopiaLocal(payload) {
  try {
    const clave = claveOffline(payload.test_id);
    const previo = JSON.parse(localStorage.getItem(clave) || "null") || {};
    localStorage.setItem(clave, JSON.stringify({ ...previo, ...payload }));
  } catch (e) {
    // localStorage lleno o inaccesible (privado/incógnito estricto): la
    // copia local es solo una red de seguridad extra, no algo crítico.
  }
}

function leerCopiaLocal(testId) {
  try {
    return JSON.parse(localStorage.getItem(claveOffline(testId)) || "null");
  } catch (e) {
    return null;
  }
}

function borrarCopiaLocal(testId) {
  try {
    localStorage.removeItem(claveOffline(testId));
  } catch (e) {
    // ignorar
  }
}

let payloadPendienteReintento = null;
let reintentoArmado = false;
let bannerOffline = null;

function mostrarBannerOffline() {
  if (!bannerOffline) {
    bannerOffline = document.createElement("div");
    bannerOffline.id = "age-banner-offline";
    bannerOffline.innerHTML = `${icono("alerta", 16)} Sin conexión: tu progreso se está guardando en este dispositivo y se sincronizará al volver a tener internet.`;
    Object.assign(bannerOffline.style, {
      position: "fixed", bottom: "0", left: "0", right: "0", zIndex: "9999",
      background: "#b8790a", color: "#fff", textAlign: "center",
      padding: "10px 16px", fontSize: "0.9rem", fontFamily: "inherit",
      display: "flex", alignItems: "center", justifyContent: "center", gap: "8px"
    });
    document.body.appendChild(bannerOffline);
  }
  bannerOffline.style.display = "flex";
}

function ocultarBannerOffline() {
  if (bannerOffline) bannerOffline.style.display = "none";
}

// Se activa la primera vez que hace falta (primer autoguardado de un test
// en curso) para no añadir listeners globales en páginas que no están
// haciendo ningún test.
function armarDeteccionOffline() {
  if (reintentoArmado) return;
  reintentoArmado = true;
  if (!navigator.onLine) mostrarBannerOffline();
  window.addEventListener("offline", mostrarBannerOffline);
  window.addEventListener("online", async () => {
    ocultarBannerOffline();
    if (!payloadPendienteReintento) return;
    const payload = payloadPendienteReintento;
    payloadPendienteReintento = null;
    await enviarAutosave(payload, false);
  });
}

// Nuevo test: genera un id de sesión (UUID) que se usará como nombre de
// documento en Firestore durante todo el test, tanto para los autoguardados
// como para el guardado final -- así terminar el test es simplemente
// sobrescribir el mismo documento, sin dejar un borrador duplicado.
export function generarTestId() {
  testIdActual = crypto.randomUUID();
  return testIdActual;
}

// Al reanudar un test ya empezado, se reutiliza su test_id en vez de generar
// uno nuevo.
export function usarTestId(id) {
  testIdActual = id;
}

export function testIdEnCurso() {
  return testIdActual;
}

export function limpiarSeguimiento() {
  clearTimeout(temporizadorDebounce);
  clearTimeout(temporizadorDebounceContenido);
  if (testIdActual) borrarCopiaLocal(testIdActual);
  testIdActual = null;
}

async function enviarAutosave(payload, keepalive) {
  guardarCopiaLocal(payload);
  armarDeteccionOffline();
  const token = await idToken();
  if (!token) return;
  try {
    const res = await fetch(`${BACKEND_URL}/autosave-test`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload),
      keepalive
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    payloadPendienteReintento = null;
  } catch (e) {
    console.error("No se pudo autoguardar el progreso del test (se reintentará al recuperar conexión):", e);
    payloadPendienteReintento = payload;
  }
}

// Se llama UNA vez, justo después de tener ya las preguntas (recién
// generadas o recién restauradas), con el array completo de preguntas y los
// metadatos fijos del test (oposición, tipo, temas...). Va sin debounce y a
// propósito por separado de autoguardarProgreso(): si fuera debounced, una
// respuesta rápida del usuario justo después de empezar podría cancelar
// este envío inicial antes de que saliera, perdiendo el contenido guardado.
export function guardarContenidoInicial(datos) {
  if (!testIdActual) return Promise.resolve();
  return enviarAutosave({ test_id: testIdActual, ...datos }, false);
}

// Igual que guardarContenidoInicial (manda el snapshot completo, incluido
// "contenido"), pero para cuando el test personalizado empieza a jugarse
// con las primeras preguntas mientras el resto se sigue generando en
// segundo plano (test-personalizado, N>10): cada pregunta nueva que llega
// llama a esto para que el documento de reanudación crezca con ellas. Va
// con su propio debounce (variable de timer separada de
// autoguardarProgreso) para que una ráfaga de preguntas casi simultáneas
// colapse en un único guardado sin pisar el debounce de las respuestas del
// usuario. El backend (/autosave-test) sobrescribe el documento entero
// cuando "contenido" viene informado, así que el llamante debe mandar
// siempre el snapshot COMPLETO (metadatos fijos + estado variable), nunca
// solo el array de preguntas.
export function actualizarContenidoEnCurso(datosCompletos) {
  if (!testIdActual) return;
  clearTimeout(temporizadorDebounceContenido);
  temporizadorDebounceContenido = setTimeout(() => {
    enviarAutosave({ test_id: testIdActual, ...datosCompletos }, false);
  }, 2000);
}

// Progreso posterior (respuesta marcada, navegación entre preguntas, tick
// del cronómetro): debounced (~1.5s) para no machacar el backend en cada
// tecla, nunca manda "contenido" de nuevo.
export function autoguardarProgreso(datosParciales) {
  if (!testIdActual) return;
  clearTimeout(temporizadorDebounce);
  temporizadorDebounce = setTimeout(() => {
    enviarAutosave({ test_id: testIdActual, ...datosParciales }, false);
  }, 1500);
}

// Guardado inmediato (sin debounce) para el botón "Guardar y salir": el
// usuario pide explícitamente irse, así que se espera a que la petición
// termine antes de navegar fuera de la página, en vez de fiarse del
// guardado automático en segundo plano.
export async function guardarProgresoInmediato(datosParciales) {
  if (!testIdActual) return;
  clearTimeout(temporizadorDebounce);
  await enviarAutosave({ test_id: testIdActual, ...datosParciales }, false);
}

// Guardado best-effort al ocultarse/cerrarse la pestaña. Se usa
// fetch(...,{keepalive:true}) en vez de navigator.sendBeacon porque
// sendBeacon no permite mandar cabeceras, y toda la app autentica con
// "Authorization: Bearer <token>".
export function activarGuardadoAlSalir(obtenerEstadoActual) {
  const guardarYa = () => {
    if (!testIdActual) return;
    clearTimeout(temporizadorDebounce);
    const estado = obtenerEstadoActual();
    if (!estado) return;
    enviarAutosave({ test_id: testIdActual, ...estado }, true);
  };
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") guardarYa();
  });
  window.addEventListener("pagehide", guardarYa);
}

// Recupera un test "en_progreso" (o ya finalizado) completo por su id, para
// reanudarlo o repetirlo. Fija testIdActual para que los autoguardados
// siguientes sigan escribiendo en el mismo documento.
export async function cargarTestEnProgreso(testId) {
  const token = await idToken();
  if (!token) return null;
  try {
    const res = await fetch(`${BACKEND_URL}/mi-test/${testId}`, {
      headers: { Authorization: `Bearer ${token}` }
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const datos = await res.json();
    testIdActual = testId;
    return datos.test;
  } catch (e) {
    // Sin conexión (u otro fallo de red) para traer el test desde el
    // servidor: si esta misma pestaña ya tenía una copia local de ESE test
    // (guardada por enviarAutosave más arriba), se reanuda desde ahí en vez
    // de dejar al usuario sin nada -- solo cubre "seguir en esta pestaña",
    // no reanudar desde otro dispositivo, que sigue necesitando red.
    console.error("No se pudo cargar el test en progreso desde el servidor, usando copia local si existe:", e);
    testIdActual = testId;
    armarDeteccionOffline();
    return leerCopiaLocal(testId);
  }
}

// El id del test a reanudar viaja como ?resume=<id> en la URL de la propia
// página del test (test-generator, repetir-test...).
export function idDesdeUrlResume() {
  return new URLSearchParams(window.location.search).get("resume");
}
