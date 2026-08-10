"""Control de parada para generaciones en segundo plano (resumen, esquema,
test, tarjetas, bancos adaptativos) -- 10/08/2026, a petición explícita del
usuario: quiere poder detener una generación propia en curso para no gastar
tokens de más mientras hace pruebas.

No existía NINGÚN mecanismo de cancelación en todo el código antes de esto
(confirmado por búsqueda) -- las llamadas a DeepSeek ya en vuelo tampoco son
cancelables de forma segura (ver el comentario largo junto a
_post_deepseek_con_reintentos en deepseek_utils.py). Este módulo NO
interrumpe una llamada HTTP ya en marcha: solo permite que el propio hilo de
fondo, en sus puntos de comprobación naturales (antes de lanzar un fragmento/
lote/ronda nueva), decida parar de lanzar MÁS llamadas y ceder de forma
ordenada -- mismo criterio que ya usan las comprobaciones de tiempo máximo
existentes (_TIEMPO_MAXIMO_GENERACION_SEGUNDOS).

Registro en memoria, no en Firestore: con un único proceso Render
(--workers 1, ver render.yaml) esto basta -- un redeploy se lleva por
delante tanto el registro como los propios hilos de fondo que vigilaba, así
que no hay ningún estado "huérfano" que limpiar entre despliegues."""
import threading

_registro = {}
_lock_registro = threading.Lock()


def _clave(uid, documento_id, herramienta):
    return f"{uid}:{documento_id}:{herramienta}"


def registrar(uid, documento_id, herramienta):
    """Crea (o reinicia, si por lo que sea quedó uno viejo sin desregistrar)
    el evento de parada de esta generación y lo devuelve -- el llamante lo
    pasa hacia abajo como evento_parada para que el propio generador lo
    consulte en sus puntos de comprobación."""
    evento = threading.Event()
    with _lock_registro:
        _registro[_clave(uid, documento_id, herramienta)] = evento
    return evento


def desregistrar(uid, documento_id, herramienta):
    """Se llama SIEMPRE al terminar (con éxito, con error, o porque se pidió
    parar) -- en un bloque finally, igual que limpiar_progreso_generacion en
    documentos_pdf.py, para no dejar entradas colgadas indefinidamente."""
    with _lock_registro:
        _registro.pop(_clave(uid, documento_id, herramienta), None)


def solicitar_parada(uid, documento_id, herramienta):
    """Marca el evento de parada de esta generación, si sigue en curso.
    Devuelve True si había una generación registrada (y se le avisó), False
    si no hay ninguna en marcha para esa clave -- el llamante (la ruta admin)
    lo usa para decidir si responder 200 o 404."""
    with _lock_registro:
        evento = _registro.get(_clave(uid, documento_id, herramienta))
    if evento is None:
        return False
    evento.set()
    return True
