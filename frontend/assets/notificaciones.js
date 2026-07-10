// Notificación de error compartida: usa SweetAlert2 si la página que
// llama ya lo tiene cargado (más pulido, con icono y título), y cae a un
// alert() nativo si no -- así una página no necesita cargar Swal solo
// para poder avisar de un error. Sustituye a los alert() nativos sueltos
// que había repartidos por 6 páginas distintas, cada uno con su propio
// mensaje de fallback.
//
// No se usa (a propósito) en los sitios que muestran error.message en
// crudo al usuario sin traducir -- eso requiere un diccionario de
// mensajes pensado para cada caso, que queda fuera de esta limpieza.
export function mostrarErrorGlobal(mensaje) {
  if (typeof window.Swal !== "undefined" && window.Swal.fire) {
    window.Swal.fire({ icon: "error", title: "Ha ocurrido un error", text: mensaje });
  } else {
    alert(mensaje);
  }
}
