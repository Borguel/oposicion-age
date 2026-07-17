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
  trofeo: '<path d="M7 4h10v5a5 5 0 0 1-10 0V4z"/><path d="M7 5H4a3 3 0 0 0 3 4"/><path d="M17 5h3a3 3 0 0 1-3 4"/><path d="M12 14v3"/><path d="M9 20h6"/><path d="M10 17h4v3h-4z"/>',
  sol: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.5M12 19v2.5M4.5 12H2M22 12h-2.5M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8"/>',
  luna: '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  candado: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  actualizar: '<path d="M20 11a8 8 0 0 0-14.6-4.6M4 13a8 8 0 0 0 14.6 4.6"/><path d="M5 3v4h4"/><path d="M19 21v-4h-4"/>',
  rayo: '<path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z"/>',
  atras: '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',

  // Ampliación del set: sustituyen a los emoji sueltos que había por toda la
  // web (dashboard, estadísticas, avisos, tests...) para que todo comparta
  // el mismo lenguaje visual de trazo fino en vez de mezclarse con el estilo
  // de emoji de cada sistema operativo.
  documento: '<path d="M6 2h9l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><path d="M15 2v5h5"/>',
  libro: '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>',
  libros: '<path d="M4 4h6v16H4z"/><path d="M13 5.3l4.9-1 2.1 14.8-4.9 1z"/>',
  reloj: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.5 2"/>',
  arena: '<path d="M6 3h12v4l-4 5 4 5v4H6v-4l4-5-4-5z"/>',
  cruz: '<line x1="6" y1="6" x2="18" y2="18"/><line x1="18" y1="6" x2="6" y2="18"/>',
  alerta: '<path d="M12 3l10 17.5H2z"/><line x1="12" y1="9.5" x2="12" y2="14"/><circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none"/>',
  guardar: '<path d="M5 4h11l3 3v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"/><path d="M8 4v6h8V4"/><path d="M8 21v-7h8v7"/>',
  marcador: '<path d="M6 3h12v18l-6-4-6 4z"/>',
  robot: '<rect x="4" y="8" width="16" height="11" rx="2"/><circle cx="9" cy="13.5" r="1.1" fill="currentColor" stroke="none"/><circle cx="15" cy="13.5" r="1.1" fill="currentColor" stroke="none"/><line x1="12" y1="8" x2="12" y2="4"/><circle cx="12" cy="3" r="1"/><line x1="2" y1="13" x2="2" y2="16"/><line x1="22" y1="13" x2="22" y2="16"/>',
  fuego: '<path d="M12 2c-1.2 3-4 4.3-4 8.2a4 4 0 0 0 8 0c0-1.3-.5-2.1-1-2.9.4 2-.9 3.7-2.2 3.7-1.4 0-2.1-1.2-2.1-2.5 0-2 1.3-2.8 1.3-6.5z"/><path d="M8.3 14.2a3.7 3.7 0 0 0 7.4 0c0-1.7-.9-2.7-1.7-3.6"/>',
  cerebro: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="8" r="1" fill="currentColor" stroke="none"/><circle cx="8" cy="13.2" r="1" fill="currentColor" stroke="none"/><circle cx="16" cy="13.2" r="1" fill="currentColor" stroke="none"/><circle cx="12" cy="17" r="1" fill="currentColor" stroke="none"/><line x1="12" y1="8" x2="8" y2="13.2"/><line x1="12" y1="8" x2="16" y2="13.2"/><line x1="8" y1="13.2" x2="12" y2="17"/><line x1="16" y1="13.2" x2="12" y2="17"/><line x1="8" y1="13.2" x2="16" y2="13.2"/>',
  subir: '<line x1="12" y1="20" x2="12" y2="6"/><polyline points="6 12 12 6 18 12"/>',
  descargar: '<line x1="12" y1="4" x2="12" y2="17"/><polyline points="6 11 12 17 18 11"/><line x1="5" y1="21" x2="19" y2="21"/>',
  repetir: '<path d="M4 12a8 8 0 0 1 14-5.3"/><polyline points="17 3 17 7 13 7"/><path d="M20 12a8 8 0 0 1-14 5.3"/><polyline points="7 21 7 17 11 17"/>',
  esquema: '<line x1="4" y1="5" x2="20" y2="5"/><line x1="7" y1="10.3" x2="20" y2="10.3"/><line x1="7" y1="15.7" x2="20" y2="15.7"/><line x1="4" y1="21" x2="20" y2="21"/>',
  estrella: '<polygon points="12 2.5 15 9.3 22 9.8 16.6 14.2 18.5 21 12 17 5.5 21 7.4 14.2 2 9.8 9 9.3"/>',
  ojo: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
  papelera: '<path d="M5 7h14M9 7V4h6v3M7 7l1 13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1l1-13"/>',
  lista: '<line x1="8" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="20" y2="12"/><line x1="8" y1="18" x2="20" y2="18"/><circle cx="4" cy="6" r="1" fill="currentColor" stroke="none"/><circle cx="4" cy="12" r="1" fill="currentColor" stroke="none"/><circle cx="4" cy="18" r="1" fill="currentColor" stroke="none"/>',
  usuarios: '<circle cx="8" cy="8" r="3"/><path d="M2 20c0-3.2 2.6-5.7 6-5.7s6 2.5 6 5.7"/><circle cx="17" cy="9" r="2.6"/><path d="M14.7 14.4c2.6.5 4.3 2.6 4.3 5.6"/>',
  bandera: '<line x1="5" y1="3" x2="5" y2="21"/><path d="M5 4h13l-3 4 3 4H5"/>',
  graduacion: '<path d="M2 9l10-5 10 5-10 5-10-5z"/><path d="M6 11.3v4.8c0 1.6 2.9 3 6 3s6-1.4 6-3v-4.8"/><line x1="22" y1="9" x2="22" y2="15.5"/>',
  regalo: '<rect x="4" y="9" width="16" height="11" rx="1"/><line x1="4" y1="13" x2="20" y2="13"/><line x1="12" y1="9" x2="12" y2="20"/><path d="M12 9C10.5 5.5 6.5 5.5 6.5 8S9 9 12 9zM12 9c1.5-3.5 5.5-3.5 5.5-1S15 9 12 9z"/>',
  herramienta: '<path d="M14.7 6.3a4 4 0 0 1-5.4 5.4L4.7 16.3a1.8 1.8 0 0 0 2.5 2.5l4.6-4.6a4 4 0 0 1 5.4-5.4l-2.7 2.7-2-2z"/>',
  corona: '<path d="M3 8.5l4 2.7L12 4l5 7.2 4-2.7-1.7 9.5H4.7z"/><line x1="4.7" y1="19" x2="19.3" y2="19"/>',
  prohibido: '<circle cx="12" cy="12" r="9"/><line x1="5.7" y1="18.3" x2="18.3" y2="5.7"/>',
  mas: '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
  reproducir: '<polygon points="7 4 20 12 7 20"/>',
  campana: '<path d="M12 3a5 5 0 0 0-5 5v3.3c0 1-.4 2-1.2 2.8L5 15h14l-.8-.9a4 4 0 0 1-1.2-2.8V8a5 5 0 0 0-5-5z"/><path d="M10 18a2 2 0 0 0 4 0"/>',
  campanaOff: '<path d="M8 5.3A5 5 0 0 1 17 8v3.3c0 .6.1 1.1.4 1.6M12 3a2 2 0 0 1 1.7 1"/><path d="M18.8 14.1c-.5-.7-.8-1.6-.8-2.8V8a5 5 0 0 0-.4-2M5 15h9M15 15l1 .9-.8.9H5"/><line x1="10" y1="18" x2="14" y2="18"/><line x1="3" y1="3" x2="21" y2="21"/>',
  calendario: '<rect x="3" y="5" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="8" y1="3" x2="8" y2="7"/><line x1="16" y1="3" x2="16" y2="7"/>',
  bombilla: '<line x1="9.5" y1="18" x2="14.5" y2="18"/><line x1="10.3" y1="21" x2="13.7" y2="21"/><path d="M12 3a6 6 0 0 0-3.6 10.8c.6.5 1.1 1.2 1.1 2V16h5v-.2c0-.8.5-1.5 1.1-2A6 6 0 0 0 12 3z"/>',
  pregunta: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1.1 1-1.1 1.8v.4"/><circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none"/>',
  ajustes: '<line x1="4" y1="6" x2="20" y2="6"/><circle cx="9" cy="6" r="2"/><line x1="4" y1="12" x2="20" y2="12"/><circle cx="15" cy="12" r="2"/><line x1="4" y1="18" x2="20" y2="18"/><circle cx="7" cy="18" r="2"/>',
  historial: '<path d="M3.5 3v5h5"/><path d="M3.9 13.5a8.5 8.5 0 1 0 2.4-6.7L3.5 9"/><path d="M12 8v5l3 2"/>',
  pulso: '<path d="M3 12h4l2-7 4 14 2-7h6"/>',
  informacion: '<circle cx="12" cy="12" r="9"/><line x1="12" y1="11" x2="12" y2="16.5"/><circle cx="12" cy="7.5" r="0.6" fill="currentColor" stroke="none"/>',
  euro: '<path d="M17.5 6.8A6.5 6.5 0 1 0 17.5 17.2"/><line x1="4" y1="10" x2="14.5" y2="10"/><line x1="4" y1="14" x2="13.5" y2="14"/>',
  escudo: '<path d="M12 3l7 3v6c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V6z"/>',
  llave: '<circle cx="7" cy="15" r="4"/><line x1="10" y1="12" x2="20" y2="2"/><line x1="16" y1="6" x2="19" y2="9"/><line x1="13" y1="9" x2="15.5" y2="11.5"/>',
  correo: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 6.5l9 6.5 9-6.5"/>',
  megafono: '<path d="M3 10v4h3l6 4V6l-6 4z"/><path d="M15.3 9a4 4 0 0 1 0 6"/><path d="M18.2 6.3a8 8 0 0 1 0 11.4"/>',
  medalla: '<circle cx="12" cy="15" r="5"/><polyline points="7.2 3 9.6 10.2 12 8.3 14.4 10.2 16.8 3"/>',
  mano: '<path d="M7.2 11.5V5.8a1.4 1.4 0 0 1 2.8 0v5"/><path d="M10 10.8V4.5a1.4 1.4 0 0 1 2.8 0v6.7"/><path d="M12.8 11.2V6.5a1.4 1.4 0 0 1 2.8 0v6.5"/><path d="M15.6 13V9.6a1.4 1.4 0 0 1 2.8 0v5c0 3.7-2.4 6.7-6.1 6.7h-.9a5.3 5.3 0 0 1-4.6-2.6L5 15.6c-.5-.8-.2-1.6.5-2 .7-.4 1.4-.1 1.9.5l1.3 1.7"/>',
  pausa: '<rect x="7" y="5" width="3.2" height="14" rx="1"/><rect x="13.8" y="5" width="3.2" height="14" rx="1"/>'
};

// tamano en px; el resto de atributos vienen ya fijados por el estilo
// común (trazo con currentColor, sin relleno salvo el punto de "diana" y
// el triángulo de "brujula", que sí son currentColor con fill sólido).
export function icono(nombre, tamano = 20) {
  const cuerpo = PATHS[nombre];
  if (!cuerpo) return "";
  return `<svg width="${tamano}" height="${tamano}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${cuerpo}</svg>`;
}
