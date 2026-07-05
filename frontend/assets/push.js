// Activar/desactivar notificaciones push del navegador para el aviso de
// racha en riesgo (el cron del backend las manda; aquí solo se gestiona el
// permiso y la suscripción). Requiere que el service worker ya esté
// registrado (auth.js lo hace en cuanto carga cualquier página).
import { idToken } from "/assets/auth.js";
import { BACKEND_URL } from "/assets/firebase-config.js";

function base64UrlAClaveBytes(base64Url) {
  const relleno = "=".repeat((4 - (base64Url.length % 4)) % 4);
  const base64 = (base64Url + relleno).replace(/-/g, "+").replace(/_/g, "/");
  const binario = atob(base64);
  return Uint8Array.from([...binario].map((c) => c.charCodeAt(0)));
}

export async function pushDisponibleEnNavegador() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export async function pushConfiguradoEnServidor() {
  try {
    const res = await fetch(`${BACKEND_URL}/notificaciones-push/clave-publica`);
    const { disponible } = await res.json();
    return !!disponible;
  } catch (e) {
    return false;
  }
}

export async function notificacionesActivas() {
  if (!(await pushDisponibleEnNavegador())) return false;
  const registro = await navigator.serviceWorker.ready;
  const suscripcion = await registro.pushManager.getSubscription();
  return !!suscripcion;
}

export async function activarNotificaciones() {
  if (!(await pushDisponibleEnNavegador())) {
    throw new Error("Tu navegador no admite notificaciones push.");
  }
  const permiso = await Notification.requestPermission();
  if (permiso !== "granted") {
    throw new Error("No se concedió permiso para las notificaciones.");
  }

  const token = await idToken();
  if (!token) throw new Error("Debes iniciar sesión.");

  const resClave = await fetch(`${BACKEND_URL}/notificaciones-push/clave-publica`);
  const { clave_publica, disponible } = await resClave.json();
  if (!disponible || !clave_publica) {
    throw new Error("Las notificaciones aún no están configuradas en el servidor.");
  }

  const registro = await navigator.serviceWorker.ready;
  const suscripcion = await registro.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: base64UrlAClaveBytes(clave_publica),
  });

  await fetch(`${BACKEND_URL}/notificaciones-push/suscribir`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(suscripcion.toJSON()),
  });
}

export async function desactivarNotificaciones() {
  const registro = await navigator.serviceWorker.ready;
  const suscripcion = await registro.pushManager.getSubscription();
  if (!suscripcion) return;
  const endpoint = suscripcion.endpoint;
  await suscripcion.unsubscribe();

  const token = await idToken();
  if (!token) return;
  await fetch(`${BACKEND_URL}/notificaciones-push/desuscribir`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ endpoint }),
  });
}
