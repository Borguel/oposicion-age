import { icono } from "/assets/icons.js";

// Barra de progreso "conversadora": combina un relleno que nunca se queda
// parado en seco (avanza mediante un techo que solo sube -- por eventos SSE
// reales o, si de momento no llega ninguno, muy despacio con el tiempo) con
// un carrusel de mensajes propios de la fase actual, para que el usuario
// note que se sigue trabajando en su documento aunque el backend tarde en
// mandar el siguiente evento real (p. ej. una generación de un único
// lote/fragmento, donde solo hay UN evento de progreso real y llega justo
// al final).
export function crearProgresoConversador({ elBarra, elTextoBarra, elTexto, elIcono, etapasLeyendo, etapasGenerando, etapasFusionando }) {
  let etapasActuales = etapasLeyendo;
  let indiceEtapa = 0;
  // Techo confirmado por eventos SSE reales (nunca baja). El techo
  // EFECTIVO en cada instante es el mayor entre este y el que marca el
  // reloj (techoPorTiempo) -- así, aunque no llegue ningún evento real
  // todavía (p. ej. mientras se genera/verifica la primera pregunta), la
  // barra sigue subiendo sola en vez de quedarse parada esperando.
  let techoReal = 0;
  let mostrado = 0;
  const inicio = Date.now();

  function techoPorTiempo() {
    const segundos = (Date.now() - inicio) / 1000;
    // Sube deprisa al principio y se acerca a 90 sin llegar nunca del
    // todo -- deja los últimos puntos para cuando llegue el evento real
    // que confirma que ya casi ha terminado, o el "fin" que la remata al
    // 100%. Constante de tiempo de ~9s: a los 9s ronda el 57%, a los 20s
    // el 80%, a los 35s el 88%.
    return 90 * (1 - Math.exp(-segundos / 9));
  }

  function pintarBarra() {
    if (elBarra) elBarra.style.width = `${mostrado.toFixed(1)}%`;
    if (elTextoBarra) elTextoBarra.textContent = `${Math.round(mostrado)}%`;
  }
  function pintarEtapa() {
    const etapa = etapasActuales[indiceEtapa % etapasActuales.length];
    if (elTexto) elTexto.textContent = etapa.mensaje;
    if (elIcono) elIcono.innerHTML = icono(etapa.icono, 32);
  }
  pintarEtapa();
  pintarBarra();

  const intervaloBarra = setInterval(() => {
    const techo = Math.max(techoReal, techoPorTiempo());
    if (mostrado < techo) {
      mostrado = Math.min(techo, mostrado + Math.max(0.3, (techo - mostrado) * 0.2));
      pintarBarra();
    }
  }, 250);

  const intervaloEtapas = setInterval(() => {
    indiceEtapa++;
    pintarEtapa();
  }, 2200);

  function cambiarFase(etapas) {
    if (!etapas || etapasActuales === etapas) return;
    etapasActuales = etapas;
    indiceEtapa = 0;
    pintarEtapa();
  }

  return {
    // Se llama con cada evento SSE de tipo "progreso". mensajeExacto (p. ej.
    // "Generando y verificando pregunta 2 de 10…") se muestra un instante y
    // luego el carrusel de la fase retoma sus mensajes genéricos.
    avanzar(evento, mensajeExacto) {
      const porcentajeReal = evento.total ? Math.round((evento.completadas / evento.total) * 100) : techoReal;
      techoReal = Math.max(techoReal, Math.min(97, porcentajeReal));
      cambiarFase(evento.fase === "fusionando" ? etapasFusionando : etapasGenerando);
      if (mensajeExacto && elTexto) elTexto.textContent = mensajeExacto;
    },
    completar() {
      techoReal = 100;
      mostrado = 100;
      pintarBarra();
    },
    detener() {
      clearInterval(intervaloBarra);
      clearInterval(intervaloEtapas);
    },
  };
}
