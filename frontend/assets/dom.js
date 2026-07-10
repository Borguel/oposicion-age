// Pequeñas ayudas para leer/escribir el DOM sin que un id que ya no
// existe (renombrado o quitado del HTML en un cambio posterior) rompa el
// resto del script en silencio -- document.getElementById(id).textContent
// lanza TypeError si el elemento no existe, y una sola línea así puede
// tirar abajo el resto de una función entera. Se usan solo en los puntos
// de mayor tráfico/riesgo (ya hubo un caso real: el crash de "Esquemas
// generados" en Estadísticas), no en todos los accesos al DOM del sitio.
export function fijarTexto(id, valor) {
  const el = document.getElementById(id);
  if (el) el.textContent = valor;
}

export function fijarHTML(id, valor) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = valor;
}

export function fijarValor(id, valor) {
  const el = document.getElementById(id);
  if (el) el.value = valor;
}
