// Configuración pública del proyecto de Firebase (segura de publicar: no es
// un secreto, es la que identifica el proyecto ante los SDKs de cliente).
// Sustituye estos valores por los de tu proyecto: Firebase console →
// Configuración del proyecto → General → "Tus apps" → app web.
export const firebaseConfig = {
  apiKey: "TU_API_KEY",
  authDomain: "TU_PROYECTO.firebaseapp.com",
  projectId: "TU_PROYECTO",
  storageBucket: "TU_PROYECTO.appspot.com",
  messagingSenderId: "TU_SENDER_ID",
  appId: "TU_APP_ID"
};

// URL del backend Flask (servicio "oposicion-age" en Render).
export const BACKEND_URL = "https://oposicion-age.onrender.com";
