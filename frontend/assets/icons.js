// Set mínimo de iconos SVG en línea (trazo, currentColor) para sustituir
// al emoji en la barra de navegación y en Zona opositor -- el emoji
// renderiza distinto según el sistema operativo/navegador, lo que rompía
// la coherencia visual de la marca entre dispositivos. Deliberadamente
// acotado a estos dos sitios (los primeros que ve cualquiera al entrar);
// el resto del sitio sigue con emoji por ahora.
const PATHS = {
  usuario: '<circle cx="12" cy="8" r="3.2"/><path d="M5 20c0-3.5 3-6 7-6s7 2.5 7 6"/>',
  diana: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none"/>',
  tarjeta: '<rect x="3" y="6" width="18" height="13" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="6" y1="14.5" x2="10" y2="14.5"/>',
  salir: '<path d="M9 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h3"/><path d="M15 16l4-4-4-4"/><line x1="19" y1="12" x2="9" y2="12"/>',
  menu: '<line x1="4" y1="7" x2="20" y2="7"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="17" x2="20" y2="17"/>',
  llama: '<path d="M12 2.5c1.2 3-2 4.2-2 7.3a4.2 4.2 0 0 0 8.4 0c0-1.3-.6-2.3-1.2-2.6.6 2.2-1 3.4-2.1 3.4a2.3 2.3 0 0 1-2.3-2.3c0-1.9 1.9-3 1.4-5.4-2 1.2-4.2 3.4-4.2 6.9a5.2 5.2 0 0 0 10.4 0c0-4.3-3-5.7-3.4-9.8-1 1.7-2.1 2.2-3 2.5z"/>',
  luna: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  carpeta: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>',
  edificio: '<path d="M4 21h16M5 21V10M9 21V10M12 21V10M15 21V10M19 21V10M3 10l9-6 9 6"/>',
  lapiz: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>',
  matraz: '<path d="M9 3h6M10 3v6l-5.5 9a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9V3"/><path d="M7.5 15h9"/>',
  destellos: '<path d="M12 3l1.5 4.5L18 9l-4.5 1.5L12 15l-1.5-4.5L6 9l4.5-1.5z"/><path d="M19 14l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>',
  chat: '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>',
  brujula: '<circle cx="12" cy="12" r="9"/><polygon points="15.5,8.5 12.8,12.8 8.5,15.5 11.2,11.2" fill="currentColor" stroke="none"/>',
  grafico: '<line x1="4" y1="20" x2="20" y2="20"/><rect x="6" y="14" width="3" height="6"/><rect x="11" y="10" width="3" height="10"/><rect x="16" y="6" width="3" height="14"/>',
  check: '<path d="M4 12.5l5 5L20 6"/>',
  buscar: '<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.2" y2="16.2"/>',
  trofeo: '<path d="M7 4h10v5a5 5 0 0 1-10 0V4z"/><path d="M7 5H4a3 3 0 0 0 3 4"/><path d="M17 5h3a3 3 0 0 1-3 4"/><path d="M12 14v3"/><path d="M9 20h6"/><path d="M10 17h4v3h-4z"/>'
};

// tamano en px; el resto de atributos vienen ya fijados por el estilo
// común (trazo con currentColor, sin relleno salvo el punto de "diana" y
// el triángulo de "brujula", que sí son currentColor con fill sólido).
export function icono(nombre, tamano = 20) {
  const cuerpo = PATHS[nombre];
  if (!cuerpo) return "";
  return `<svg width="${tamano}" height="${tamano}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${cuerpo}</svg>`;
}
