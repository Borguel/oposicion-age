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
// Proyecto en US Cloud (PostHog no permite migrar de región un proyecto ya
// creado en US a EU; ver frontend/cookies/index.html para el aviso legal
// correspondiente a esta región).
const POSTHOG_API_KEY = "phc_zyxhPxbzZ5n9FEdDvTPuS6UF2DK9HCGhRHwHvnciyyAC";
const POSTHOG_HOST = "https://us.i.posthog.com";

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

// auth: instancia de Firebase Auth ya inicializada (la exporta auth.js).
// onAuthStateChanged: la misma función del SDK que ya cargó auth.js -- este
// módulo no importa firebase-auth.js por su cuenta a propósito: auth.js lo
// importa a SU VEZ de forma estática desde aquí arriba, así que si
// analytics.js tuviera su propia dependencia dura del SDK, un fallo de red
// al cargarlo volvería a tirar abajo auth.js entero (el mismo problema que
// se acaba de arreglar ahí).
export function iniciarAnalitica(auth, onAuthStateChanged) {
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
