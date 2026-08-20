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

// Cuota mensual de documentos NUEVOS SUBIDOS (banco_pdf_mensual, ver
// limites_uso.py) -- ANTES de esto, la única forma de enterarse era subir
// el PDF, esperar al análisis y recibir un 429 (20/08/2026, auditoría UX:
// el aviso de mis-documentos/ no sirve de nada si el usuario nunca pasa
// por esa página antes de generar). Reutiliza /mis-documentos porque ya
// devuelve la cuota calculada -- no hay un endpoint más ligero solo para
// esto, y estas herramientas ya son Premium, igual que esa ruta.
export async function mostrarCuotaDocumentosMes(idElemento = "cuota-documentos-mes-nota") {
  const elemento = document.getElementById(idElemento);
  if (!elemento) return;
  try {
    const [{ idToken }, { BACKEND_URL }] = await Promise.all([
      import("/assets/auth.js"),
      import("/assets/firebase-config.js"),
    ]);
    const token = await idToken();
    if (!token) return;
    const res = await fetch(`${BACKEND_URL}/mis-documentos`, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return;
    const { cuota_documentos_mes: cuota } = await res.json();
    const usados = cuota?.usados ?? 0;
    const limite = cuota?.limite ?? 0;
    if (!limite || limite <= 0) return;
    elemento.textContent = `${usados} de ${limite} documentos nuevos subidos este mes.`;
    elemento.classList.toggle("limite-paginas-nota-alerta", usados / limite >= 0.8);
    elemento.classList.remove("hidden");
  } catch (e) {
    // Sin sesión iniciada o fallo de red: no es un dato crítico, el 429
    // del backend al subir sigue siendo la barrera real.
  }
}
