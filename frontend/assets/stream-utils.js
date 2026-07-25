// Compartido por todas las páginas que leen una respuesta en streaming
// (Server-Sent Events) de la IA: Tu Tutor, Test Personalizado y las 4
// herramientas de PDF (resumen, esquema, tarjetas, test). Si no llega
// NINGÚN evento nuevo en este tiempo, se asume que la conexión se quedó
// colgada del lado del cliente -- visto en Safari/iOS, donde a veces el
// lector del stream nunca resuelve aunque el servidor ya haya terminado y
// cerrado la respuesta (confirmado comparando con los logs del backend: la
// petición ya había devuelto 200 mientras la pantalla seguía congelada en
// el último evento de progreso). Sin esto, quien lo sufre se queda mirando
// una barra de progreso parada para siempre, sin ningún error ni forma de
// reintentar salvo recargar a ciegas.
export const TIMEOUT_SIN_EVENTOS_STREAM_MS = 60000;

export function leerStreamConTimeout(lector, ms = TIMEOUT_SIN_EVENTOS_STREAM_MS) {
  return Promise.race([
    lector.read(),
    new Promise((_resolve, reject) => setTimeout(
      () => reject(new Error("El servidor está tardando demasiado en responder. Vuelve a intentarlo.")),
      ms
    )),
  ]);
}
