// Configuración pública del proyecto de Firebase (segura de publicar: no es
// un secreto, es la que identifica el proyecto ante los SDKs de cliente).
// Sustituye estos valores por los de tu proyecto: Firebase console →
// Configuración del proyecto → General → "Tus apps" → app web.
export const firebaseConfig = {
  apiKey: "AIzaSyCaNQn-w5AYy-jeI5Ue1AYFAn6amFZQG5w",
  authDomain: "app-oposicion.firebaseapp.com",
  projectId: "app-oposicion",
  storageBucket: "app-oposicion.firebasestorage.app",
  messagingSenderId: "432501857547",
  appId: "1:432501857547:web:f8e886fd901857f144160e"
};

// URL del backend Flask (servicio "oposicion-age" en Render).
export const BACKEND_URL = "https://oposicion-age.onrender.com";

// Site key de reCAPTCHA v3 para Firebase App Check (assets/auth.js) --
// pública igual que firebaseConfig.apiKey: identifica el sitio ante
// reCAPTCHA, no autentica nada por sí sola. La clave secreta correspondiente
// no vive en el frontend ni en el repo, la valida Firebase por su cuenta.
export const RECAPTCHA_SITE_KEY = "6LdAK2EtAAAAAGTjnotYrHjCtUkhFWdUk-ql5G25";
