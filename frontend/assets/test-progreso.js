// Guardado automático y reanudación de tests en curso -- módulo compartido
// por test-generator, repetir-test, preguntas-falladas y
// subida-pdf-generar-test para que cerrar la pestaña a media pregunta no
// pierda el progreso: el test se autoguarda mientras se hace (marcado
// "en_progreso" en Firestore, bajo el mismo test_id en toda su vida) y puede
// retomarse exactamente donde se dejó desde "Mis Tests".
import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

let testIdActual = null;
let temporizadorDebounce = null;

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
  testIdActual = null;
}

async function enviarAutosave(payload, keepalive) {
  const token = await idToken();
  if (!token) return;
  try {
    await fetch(`${BACKEND_URL}/autosave-test`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify(payload),
      keepalive
    });
  } catch (e) {
    console.error("No se pudo autoguardar el progreso del test:", e);
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
    if (!res.ok) return null;
    const datos = await res.json();
    testIdActual = testId;
    return datos.test;
  } catch (e) {
    console.error("No se pudo cargar el test en progreso:", e);
    return null;
  }
}

// El id del test a reanudar viaja como ?resume=<id> en la URL de la propia
// página del test (test-generator, repetir-test...).
export function idDesdeUrlResume() {
  return new URLSearchParams(window.location.search).get("resume");
}
