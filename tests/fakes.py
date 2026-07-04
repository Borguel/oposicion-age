"""Doble ligero en memoria de la API de Firestore que usa este proyecto
(collection/document/get/set/update/delete/where/stream), para poder
probar rutas y lógica de negocio sin depender de un proyecto real de
Firebase ni de red. Cubre solo el subconjunto de la API que se usa aquí --
no pretende ser un sustituto completo de google-cloud-firestore."""


def _cumple_filtro(datos, filtro):
    campo, operador, valor = filtro
    actual = datos.get(campo)
    if operador == "==":
        return actual == valor
    raise NotImplementedError(f"Operador de filtro no soportado en el fake: {operador}")


class FakeDocumentSnapshot:
    def __init__(self, doc_id, datos):
        self.id = doc_id
        self._datos = datos
        self.exists = datos is not None

    def to_dict(self):
        return dict(self._datos) if self._datos is not None else None

    def __getitem__(self, clave):
        return self._datos[clave]


class FakeDocumentRef:
    def __init__(self, store, path):
        self._store = store
        self._path = path

    @property
    def id(self):
        return self._path[-1]

    def get(self):
        return FakeDocumentSnapshot(self._path[-1], self._store.get(self._path))

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
            cursor[partes[-1]] = valor
        self._store[self._path] = existente

    def delete(self):
        self._store.pop(self._path, None)

    def collection(self, nombre):
        return FakeCollectionRef(self._store, self._path + (nombre,))


class FakeCollectionRef:
    def __init__(self, store, path, filtros=None):
        self._store = store
        self._path = path
        self._filtros = filtros or []

    def document(self, doc_id=None):
        if doc_id is None:
            doc_id = f"auto_{sum(1 for p in self._store if p[:-1] == self._path)}"
        return FakeDocumentRef(self._store, self._path + (doc_id,))

    def where(self, campo, operador, valor):
        return FakeCollectionRef(self._store, self._path, self._filtros + [(campo, operador, valor)])

    def stream(self):
        largo = len(self._path)
        for path, datos in list(self._store.items()):
            if len(path) == largo + 1 and path[:largo] == self._path:
                if all(_cumple_filtro(datos, f) for f in self._filtros):
                    yield FakeDocumentSnapshot(path[-1], datos)


class FakeFirestore:
    """Sustituye a firestore.client(): db.collection("x") es el único punto
    de entrada real que usa el resto del código."""

    def __init__(self):
        self._store = {}

    def collection(self, nombre):
        return FakeCollectionRef(self._store, (nombre,))

    def reset(self):
        self._store.clear()

    def sembrar(self, path, datos):
        """Atajo para dejar un documento ya creado antes de una prueba.
        `path` es una tupla, p. ej. ("usuarios", uid, "tests", test_id)."""
        self._store[tuple(path)] = dict(datos)

    def leer(self, path):
        return self._store.get(tuple(path))
