// Momento de autor del hero de la home (ver el comentario en index.html
// junto a .hero-escena): de un montón de "hojas" sueltas a una pregunta de
// test resuelta, dramatizando la promesa del propio H1 ("sin perderte
// entre apuntes") en vez de decorar la carga con un fade genérico. Vive en
// su propio fichero (no en el <script type="module"> inline de index.html)
// porque solo se usa aquí -- no tiene sentido cargar anime.js en el resto
// de páginas del sitio.
import anime from "/assets/vendor/anime.esm.js";

const escena = document.querySelector(".hero-escena");
if (escena) {
  const hojas = escena.querySelectorAll(".hero-hoja");
  const pregunta = escena.querySelector("#hero-pregunta");
  const opcionCorrecta = escena.querySelector("#hero-opcion-correcta");
  const check = escena.querySelector(".hero-check path");

  // Dibuja el check por su longitud real de trazo (stroke-dashoffset) en
  // vez de un valor fijo a ojo, para que el trazo se recorra entero sin
  // importar el path exacto que use el icono.
  const longitudCheck = check.getTotalLength();
  check.style.strokeDasharray = longitudCheck;

  const vaAResolverAlInstante = () => {
    anime.set(hojas, { opacity: 0 });
    anime.set(pregunta, { opacity: 1, scale: 1 });
    anime.set(check, { strokeDashoffset: 0 });
    opcionCorrecta.classList.add("correcta");
  };

  // Quien prefiere menos movimiento llega igual al desenlace (la opción ya
  // marcada como correcta), solo que sin la coreografía.
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    vaAResolverAlInstante();
  } else {
    anime.set(hojas, {
      opacity: 1,
      rotate: (el, i) => [-9, 7, -3][i],
      translateX: (el, i) => [-14, 12, 2][i],
      translateY: (el, i) => [8, -6, 12][i],
    });
    anime.set(pregunta, { opacity: 0, scale: 0.92 });
    anime.set(check, { strokeDashoffset: longitudCheck });

    anime
      .timeline({ easing: "cubicBezier(0.16, 1, 0.3, 1)" })
      // Las 3 hojas se quedan quietas un instante (el "montón disperso" se
      // registra antes de empezar a recomponerse) y luego se alinean.
      .add({
        targets: hojas,
        rotate: 0,
        translateX: 0,
        translateY: 0,
        duration: 550,
        delay: anime.stagger(70, { start: 300 }),
      })
      .add({
        targets: hojas,
        opacity: 0,
        scale: 0.94,
        duration: 260,
        easing: "easeInQuad",
      }, "-=150")
      .add({
        targets: pregunta,
        opacity: 1,
        scale: 1,
        duration: 420,
      }, "-=90")
      .add({
        targets: check,
        strokeDashoffset: 0,
        duration: 380,
        easing: "easeOutQuad",
        begin: () => opcionCorrecta.classList.add("correcta"),
      }, "+=200");
  }
}
