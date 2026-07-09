import { onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.13.0/firebase-auth.js";

// Analítica de producto (PostHog), autoalojada para no depender de sus
// dominios en la CSP y para no ser bloqueada por bloqueadores de anuncios
// que sí reconocen posthog.com. El bundle en /assets/posthog-array.js es
// una copia sin modificar de dist/array.js del paquete npm "posthog-js"
// (la versión "lite": autocaptura + pageviews, sin grabación de sesión ni
// encuestas).
//
// Solo empieza a capturar si el usuario ya aceptó el aviso de cookies
// (misma clave que usa el banner de auth.js) -- nunca antes.
//
// Para activarla de verdad: rellena POSTHOG_API_KEY y POSTHOG_HOST con los
// datos del proyecto de PostHog (Project Settings -> Project API Key).
// Mientras POSTHOG_API_KEY esté vacío, este módulo no hace nada.
const POSTHOG_API_KEY = "";
const POSTHOG_HOST = "https://eu.i.posthog.com";

export const CLAVE_COOKIES_ACEPTADAS = "age_cookies_aceptadas";
const EVENTO_COOKIES_ACEPTADAS = "age-cookies-aceptadas";

let cargando = false;

function cargarPostHog(auth) {
  if (cargando || (window.posthog && window.posthog.__loaded)) return;
  cargando = true;

  const script = document.createElement("script");
  script.src = "/assets/posthog-array.js";
  script.async = true;
  script.onload = () => {
    if (!window.posthog) return;
    window.posthog.init(POSTHOG_API_KEY, {
      api_host: POSTHOG_HOST,
      person_profiles: "identified_only",
      capture_pageview: true,
      autocapture: true
    });
    const usuario = auth.currentUser;
    if (usuario) window.posthog.identify(usuario.uid, { email: usuario.email });
  };
  document.head.appendChild(script);
}

// auth: instancia de Firebase Auth ya inicializada (la exporta auth.js), se
// reutiliza aquí en vez de volver a inicializar Firebase para evitar
// duplicar configuración.
export function iniciarAnalitica(auth) {
  if (!POSTHOG_API_KEY) return;

  if (localStorage.getItem(CLAVE_COOKIES_ACEPTADAS) === "1") {
    cargarPostHog(auth);
  } else {
    window.addEventListener(EVENTO_COOKIES_ACEPTADAS, () => cargarPostHog(auth), { once: true });
  }

  onAuthStateChanged(auth, (usuario) => {
    if (!window.posthog || !window.posthog.__loaded) return;
    if (usuario) {
      window.posthog.identify(usuario.uid, { email: usuario.email });
    } else {
      window.posthog.reset();
    }
  });
}
