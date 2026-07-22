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
  let techo = 8;
  let mostrado = 0;

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
    if (mostrado < techo) {
      mostrado = Math.min(techo, mostrado + Math.max(0.15, (techo - mostrado) * 0.06));
      pintarBarra();
    } else if (techo < 90) {
      techo = Math.min(90, techo + 0.4);
    }
  }, 200);

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
    // "Generando preguntas (lote 2 de 3)…") se muestra un instante y luego
    // el carrusel de la fase retoma sus mensajes genéricos.
    avanzar(evento, mensajeExacto) {
      const porcentajeReal = evento.total ? Math.round((evento.completadas / evento.total) * 100) : techo;
      techo = Math.max(techo, Math.min(96, porcentajeReal));
      cambiarFase(evento.fase === "fusionando" ? etapasFusionando : etapasGenerando);
      if (mensajeExacto && elTexto) elTexto.textContent = mensajeExacto;
    },
    completar() {
      techo = 100;
      mostrado = 100;
      pintarBarra();
    },
    detener() {
      clearInterval(intervaloBarra);
      clearInterval(intervaloEtapas);
    },
  };
}
