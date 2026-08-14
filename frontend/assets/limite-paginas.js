// Muestra, antes de subir un PDF, cuántas páginas admite el plan actual del
// usuario -- antes esto solo se descubría como error DESPUÉS de subir el
// archivo y esperar a que se analizara. Solo es un aviso informativo (igual
// que el resto de comprobaciones de plan en assets/plan.js): la única
// barrera real la aplica el backend en _resolver_texto_documento.

// Debe coincidir con MAX_PAGINAS_POR_PLAN en limites_uso.py.
// 200 páginas como tope para ambos planes de pago (12/08/2026, decisión
// explícita del usuario: no superar el límite de la competencia).
const MAX_PAGINAS_POR_PLAN = { gratis: 40, basico: 200, premium: 200 };
const NOMBRE_PLAN = { gratis: "Gratis", basico: "Básico", premium: "Premium" };

export async function mostrarLimitePaginas(idElemento = "limite-paginas-nota") {
  const elemento = document.getElementById(idElemento);
  if (!elemento) return;
  try {
    const { obtenerPlan } = await import("/assets/plan.js");
    const { plan } = await obtenerPlan();
    const limite = MAX_PAGINAS_POR_PLAN[plan] ?? MAX_PAGINAS_POR_PLAN.gratis;
    const nombre = NOMBRE_PLAN[plan] ?? "Gratis";
    // Recomendación de documentos más cortos (12/08/2026, a petición del
    // usuario): el límite de arriba es el tope duro que aplica el
    // backend, pero la CALIDAD del análisis (sobre todo en resumen y
    // esquema) es mejor cuanto más corto o más troceado esté el
    // documento -- se avisa de esto en el mismo sitio, no solo del tope.
    elemento.textContent = `Hasta ${limite} páginas con tu plan actual (${nombre}). Los documentos más cortos, o divididos en varias partes, se analizan mejor -- si puedes, evita subir documentos muy largos de una sola vez.`;
    elemento.classList.remove("hidden");
  } catch (e) {
    // Sin sesión iniciada o fallo de red al consultar el plan: no es un
    // dato crítico, simplemente no se muestra el aviso.
  }
}
