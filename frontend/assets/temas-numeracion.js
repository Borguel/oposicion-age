// Numeración de bloques (romanos) y temas (arábigos) compartida por el
// selector de temas y la página de estadísticas, para que "Tema 3" del
// bloque II sea siempre el mismo tema en cualquier parte de la web.
const ROMANOS = [
  [1000, "M"], [900, "CM"], [500, "D"], [400, "CD"],
  [100, "C"], [90, "XC"], [50, "L"], [40, "XL"],
  [10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]
];

export function numeroRomano(n) {
  let resto = n;
  let resultado = "";
  for (const [valor, simbolo] of ROMANOS) {
    while (resto >= valor) {
      resultado += simbolo;
      resto -= valor;
    }
  }
  return resultado;
}

export function agruparTemasPorBloque(temas) {
  const bloques = new Map();
  temas.forEach((t) => {
    const bloqueId = t.bloque_id || "sin_bloque";
    const bloqueTitulo = t.bloque_titulo || "Otros temas";
    if (!bloques.has(bloqueId)) bloques.set(bloqueId, { titulo: bloqueTitulo, temas: [] });
    bloques.get(bloqueId).temas.push(t);
  });

  const bloqueIds = Array.from(bloques.keys()).sort();

  return bloqueIds.map((bloqueId, indiceBloque) => ({
    bloqueId,
    numeroRomano: numeroRomano(indiceBloque + 1),
    titulo: bloques.get(bloqueId).titulo,
    temas: bloques.get(bloqueId).temas.map((t, indiceTema) => ({ ...t, numeroTema: indiceTema + 1 }))
  }));
}
