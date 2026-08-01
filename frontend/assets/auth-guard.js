// Se incluye en el <head> de toda página que exige sesión, junto con el
// <style> que arranca con "html:not(.auth-listo) body { visibility: hidden }".
// Así el contenido real nunca llega a pintarse para quien no tiene sesión:
// se queda oculto hasta que esperarUsuario() confirma un usuario Y la propia
// página marca su contenido como listo (marcarContenidoListo(), ver
// auth.js) -- se añade la clase "auth-listo" y se revela la página -- o, si
// no hay sesión, se redirige a /login/ sin que el body haya sido visible en
// ningún momento.
import { esperarUsuario, contenidoListo } from "/assets/auth.js";

esperarUsuario().then((user) => {
  if (!user) {
    window.location.replace("/login/?next=" + encodeURIComponent(window.location.pathname + window.location.search));
    return;
  }
  // Límite de 4s por si una página se olvida de llamar a
  // marcarContenidoListo() (p. ej. al añadir una página nueva) -- mejor
  // revelarla con algún placeholder suelto que dejarla oculta para siempre.
  Promise.race([contenidoListo, new Promise((resolve) => setTimeout(resolve, 4000))]).then(() => {
    document.documentElement.classList.add("auth-listo");
  });
});
