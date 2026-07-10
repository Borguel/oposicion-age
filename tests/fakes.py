"""Doble ligero en memoria de la API de Firestore que usa este proyecto
(collection/document/get/set/update/delete/where/stream), para poder
probar rutas y lógica de negocio sin depender de un proyecto real de
Firebase ni de red. Cubre solo el subconjunto de la API que se usa aquí --
no pretende ser un sustituto completo de google-cloud-firestore."""
from google.cloud.firestore_v1.transforms import ArrayUnion, ArrayRemove, Increment, Sentinel


def _resolver_valor(actual, valor):
    """Aplica los "sentinel" de Firestore (ArrayUnion/ArrayRemove/Increment)
    igual que lo haría el servidor real, en vez de guardar el objeto tal
    cual -- si no, cualquier código que dependa de ellos (como el catálogo
    de carpetas) vería el sentinel en vez del valor final al releerlo."""
    if isinstance(valor, ArrayUnion):
        lista = list(actual) if isinstance(actual, list) else []
        for v in valor._values:
            if v not in lista:
                lista.append(v)
        return lista
    if isinstance(valor, ArrayRemove):
        lista = list(actual) if isinstance(actual, list) else []
        return [v for v in lista if v not in valor._values]
    if isinstance(valor, Increment):
        return (actual or 0) + valor._value
    return valor


def _cumple_filtro(datos, filtro):
    campo, operador, valor = filtro
    actual = datos.get(campo)
    if operador == "==":
        return actual == valor
    raise NotImplementedError(f"Operador de filtro no soportado en el fake: {operador}")


class FakeDocumentSnapshot:
    def __init__(self, doc_id, datos, store=None, path=None):
        self.id = doc_id
        self._datos = datos
        self.exists = datos is not None
        self._store = store
        self._path = path

    def to_dict(self):
        return dict(self._datos) if self._datos is not None else None

    def __getitem__(self, clave):
        return self._datos[clave]

    @property
    def reference(self):
        return FakeDocumentRef(self._store, self._path)


class FakeDocumentRef:
    def __init__(self, store, path):
        self._store = store
        self._path = path

    @property
    def id(self):
        return self._path[-1]

    @property
    def path(self):
        return "/".join(self._path)

    def get(self, transaction=None):
        # transaction se acepta (y se ignora) solo para que la misma
        # llamada `ref.get(transaction=transaction)` del código de
        # producción funcione igual contra este fake que contra el
        # cliente real -- ver FakeTransaction más abajo.
        return FakeDocumentSnapshot(self._path[-1], self._store.get(self._path), self._store, self._path)

    def set(self, datos, merge=False):
        if merge and self._path in self._store:
            existente = dict(self._store[self._path])
            existente.update(datos)
            self._store[self._path] = existente
        else:
            self._store[self._path] = dict(datos)

    def update(self, datos):
        # Firestore trata una clave con puntos ("a.b.c") como una ruta a un
        # campo anidado, sin pisar el resto de "a" -- no como una clave
        # literal con puntos en el nombre. Se replica aquí porque
        # limites_uso.py depende justo de este comportamiento.
        existente = dict(self._store.get(self._path) or {})
        for clave, valor in datos.items():
            partes = clave.split(".")
            cursor = existente
            for parte in partes[:-1]:
                cursor = cursor.setdefault(parte, {})
            if isinstance(valor, Sentinel):
                cursor.pop(partes[-1], None)
            else:
                cursor[partes[-1]] = _resolver_valor(cursor.get(partes[-1]), valor)
        self._store[self._path] = existente

    def delete(self):
        self._store.pop(self._path, None)

    def collection(self, nombre):
        return FakeCollectionRef(self._store, self._path + (nombre,))


class FakeCollectionRef:
    def __init__(self, store, path, filtros=None, limite=None):
        self._store = store
        self._path = path
        self._filtros = filtros or []
        self._limite = limite

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = f"auto_{sum(1 for p in self._store if p[:-1] == self._path)}"
        return FakeDocumentRef(self._store, self._path + (doc_id,))

    def where(self, campo, operador, valor):
        return FakeCollectionRef(self._store, self._path, self._filtros + [(campo, operador, valor)], self._limite)

    def limit(self, n):
        return FakeCollectionRef(self._store, self._path, self._filtros, n)

    def stream(self):
        largo = len(self._path)
        vistos = 0
        for path, datos in list(self._store.items()):
            if self._limite is not None and vistos >= self._limite:
                break
            if len(path) == largo + 1 and path[:largo] == self._path:
                if all(_cumple_filtro(datos, f) for f in self._filtros):
                    vistos += 1
                    yield FakeDocumentSnapshot(path[-1], datos, self._store, path)

    def count(self):
        return FakeAggregationQuery(self)


class FakeAggregationResult:
    """Imita el objeto que devuelve una aggregation query real de
    Firestore (`query.count().get()` -> `[[AggregationResult]]`, con
    `.value` como único atributo que usa este proyecto)."""

    def __init__(self, value):
        self.value = value


class FakeAggregationQuery:
    def __init__(self, origen):
        self._origen = origen

    def get(self):
        total = sum(1 for _ in self._origen.stream())
        return [[FakeAggregationResult(total)]]


class FakeCollectionGroupRef:
    """Simplificación de una collection_group query real: encuentra
    documentos por el nombre de su colección sin importar bajo qué padre
    estén, a diferencia de FakeCollectionRef (que exige un prefijo de ruta
    exacto). Solo cubre lo que usa este proyecto: where + count/stream."""

    def __init__(self, store, nombre, filtros=None):
        self._store = store
        self._nombre = nombre
        self._filtros = filtros or []

    def where(self, campo, operador, valor):
        return FakeCollectionGroupRef(self._store, self._nombre, self._filtros + [(campo, operador, valor)])

    def count(self):
        return FakeAggregationQuery(self)

    def stream(self):
        for path, datos in list(self._store.items()):
            if len(path) >= 2 and path[-2] == self._nombre:
                if all(_cumple_filtro(datos, f) for f in self._filtros):
                    yield FakeDocumentSnapshot(path[-1], datos, self._store, path)


class FakeTransaction:
    """Transacción simulada. El SDK real de Firestore usa
    @firestore.transactional (que exige métodos internos como _begin/
    _commit/_rollback de un google.cloud.firestore_v1.transaction.Transaction
    de verdad) para dar atomicidad frente a otra petición concurrente --
    algo que no existe en este fake de un solo hilo, donde los tests se
    ejecutan siempre en secuencia, nunca en paralelo. Por eso el código de
    producción que necesite una transacción real pasa por
    utils.ejecutar_en_transaccion, que con el cliente real delega en
    @firestore.transactional y con este fake simplemente llama a la
    función directamente: no hace falta simular aislamiento/rollback para
    que el resultado sea correcto en un test secuencial, esa garantía
    frente a concurrencia real la da el servidor de Firestore, no el
    fake. Aun así, expone la misma superficie mínima (get/set/update/
    delete) que una Transaction real, delegando en el propio
    FakeDocumentRef, para que el código de producción no tenga que
    distinguir entre una y otra."""

    def get(self, ref):
        return ref.get()

    def set(self, ref, datos, merge=False):
        ref.set(datos, merge=merge)

    def update(self, ref, datos):
        ref.update(datos)

    def delete(self, ref):
        ref.delete()


class FakeFirestore:
    """Sustituye a firestore.client(): db.collection("x") es el único punto
    de entrada real que usa el resto del código."""

    def __init__(self):
        self._store = {}

    def collection(self, nombre):
        return FakeCollectionRef(self._store, (nombre,))

    def collection_group(self, nombre):
        return FakeCollectionGroupRef(self._store, nombre)

    def get_all(self, refs):
        # A diferencia del cliente real (que no garantiza que el orden de
        # las instantáneas devueltas coincida con el de "refs" -- hay que
        # emparejarlas por su .path/.reference, no por posición), este
        # fake sí puede devolverlas en el mismo orden sin que eso oculte
        # ningún bug: es un detalle de red del servidor real que aquí no
        # existe, y el código de producción que llama a get_all ya empareja
        # por referencia, así que da igual el orden que se use aquí.
        return [ref.get() for ref in refs]

    def transaction(self):
        return FakeTransaction()

    def reset(self):
        self._store.clear()

    def sembrar(self, path, datos):
        """Atajo para dejar un documento ya creado antes de una prueba.
        `path` es una tupla, p. ej. ("usuarios", uid, "tests", test_id)."""
        self._store[tuple(path)] = dict(datos)

    def leer(self, path):
        return self._store.get(tuple(path))
