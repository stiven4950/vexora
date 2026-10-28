"""Documentos por colección: el estado de la API (trabajos, subidas) detrás de una interfaz pequeña.

La API y los trabajadores comparten el estado a través de un `DocStore`, así pueden ser procesos (o
máquinas) distintos. Tres implementaciones con el mismo contrato (tests/test_store.py):

- `JsonDocStore`: un archivo `<colección>.json` por colección en api_data/ (lo de siempre). Mismo
  formato que antes (una lista de documentos con `id`), así que jobs.json y uploads.json se leen
  sin migrar y una versión anterior del código los sigue leyendo.
- `MemoryDocStore`: en memoria, para las pruebas.
- `FirestoreDocStore` (store/firestore.py): Firestore, para Cloud Run.

Las consultas son las que la API necesita y nada más: filtros de igualdad, orden y límite. Lo
atómico va por `transact`: lee el documento, decide y escribe sin que otro proceso se cuele en
medio (con eso un trabajo lo toma un solo trabajador).
"""

from __future__ import annotations

import copy
import json
import shutil
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

try:  # bloqueo entre procesos del JSON (no existe en Windows: ahí queda solo el de hilos)
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

Doc = dict[str, Any]
# Lo que devuelve un cambio de `transact` para borrar el documento.
DELETE: Any = object()
# Orden: (campo, descendente).
Order = Iterable[tuple[str, bool]]
Change = Callable[[Doc | None], Any]


def matches(doc: Doc, where: dict[str, Any] | None) -> bool:
    """Igualdad campo a campo; un campo que falta vale None (como un null guardado)."""
    return all(doc.get(key) == value for key, value in (where or {}).items())


def sort_docs(docs: list[Doc], order_by: Order) -> list[Doc]:
    """Ordena por varios campos; los None van primero en orden ascendente (como Firestore)."""
    for field, descending in reversed(list(order_by)):
        docs.sort(key=lambda d: (d.get(field) is not None, d.get(field) if d.get(field) is not None else 0), reverse=descending)
    return docs


class DocStore(ABC):
    # True si cada lectura sale del proceso (Firestore): la API consulta con menos frecuencia.
    remote: bool = False

    @abstractmethod
    def get(self, collection: str, doc_id: str) -> Doc | None:
        """El documento, o None si no existe."""

    @abstractmethod
    def set(self, collection: str, doc_id: str, data: Doc) -> None:
        """Crea o reemplaza el documento entero."""

    @abstractmethod
    def delete(self, collection: str, doc_id: str) -> None:
        """Borra el documento (si no existe, no pasa nada)."""

    @abstractmethod
    def query(self, collection: str, where: dict[str, Any] | None = None, order_by: Order = (), limit: int | None = None) -> list[Doc]:
        """Los documentos que cumplen los filtros de igualdad, ordenados y con tope."""

    @abstractmethod
    def transact(self, collection: str, doc_id: str, change: Change) -> Any:
        """Lee el documento (None si no existe), llama a `change` y aplica lo que devuelva de forma
        atómica: un dict lo reemplaza, DELETE lo borra y None no cambia nada. Devuelve lo que
        devolvió `change`. `change` puede llamarse más de una vez (Firestore reintenta si otro
        escribió en medio): no debe tener efectos fuera de su resultado."""

    def update(self, collection: str, doc_id: str, fields: Doc, when: dict[str, Any] | None = None) -> bool:
        """Mezcla `fields` en el documento si existe y cumple `when` (igualdad). Devuelve si escribió."""

        def change(current: Doc | None) -> Doc | None:
            if current is None or not matches(current, when):
                return None
            return {**current, **fields}

        return self.transact(collection, doc_id, change) is not None


class MemoryDocStore(DocStore):
    """En memoria y con un candado: para pruebas (varios "procesos" pueden compartir una instancia)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, Doc]] = {}

    def get(self, collection: str, doc_id: str) -> Doc | None:
        with self._lock:
            doc = self._data.get(collection, {}).get(doc_id)
            return copy.deepcopy(doc) if doc is not None else None

    def set(self, collection: str, doc_id: str, data: Doc) -> None:
        with self._lock:
            self._data.setdefault(collection, {})[doc_id] = copy.deepcopy(data)

    def delete(self, collection: str, doc_id: str) -> None:
        with self._lock:
            self._data.get(collection, {}).pop(doc_id, None)

    def query(self, collection: str, where: dict[str, Any] | None = None, order_by: Order = (), limit: int | None = None) -> list[Doc]:
        with self._lock:
            found = [copy.deepcopy(d) for d in self._data.get(collection, {}).values() if matches(d, where)]
        found = sort_docs(found, order_by)
        return found[:limit] if limit is not None else found

    def transact(self, collection: str, doc_id: str, change: Change) -> Any:
        with self._lock:
            result = change(self.get(collection, doc_id))
            if result is DELETE:
                self.delete(collection, doc_id)
            elif result is not None:
                self.set(collection, doc_id, result)
            return result


# Un candado por carpeta en todo el proceso: dos JsonDocStore sobre la misma carpeta (la API y
# las subidas, o un almacén nuevo en las pruebas) no se pisan.
_folder_locks: dict[Path, threading.RLock] = {}
_folder_locks_guard = threading.Lock()


def _folder_lock(folder: Path) -> threading.RLock:
    with _folder_locks_guard:
        return _folder_locks.setdefault(folder.resolve(), threading.RLock())


class JsonDocStore(DocStore):
    """Una colección = un archivo JSON (lista de documentos) en `root`, como jobs.json siempre.

    Cada operación toma el candado de la carpeta (hilos) y un flock sobre `.store.lock`
    (procesos de la misma máquina: la API y `vexora-worker` en local). Si otro proceso escribió el
    archivo, se vuelve a leer antes de seguir. La escritura es atómica (archivo temporal y
    rename). La primera vez que este código abre un archivo que ya existía, deja una copia
    `<colección>.json.pre-store.bak` al lado: si algo saliera mal, los trabajos están ahí.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = _folder_lock(root)
        self._cache: dict[str, tuple[tuple | None, dict[str, Doc]]] = {}

    # ----- archivo -----

    def _path(self, collection: str) -> Path:
        return self.root / f"{collection}.json"

    @staticmethod
    def _stamp(path: Path) -> tuple | None:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        return (stat.st_ino, stat.st_mtime_ns, stat.st_size)

    def _load(self, collection: str) -> dict[str, Doc]:
        """Los documentos de la colección, releídos si el archivo cambió desde la última vez."""
        path = self._path(collection)
        stamp = self._stamp(path)
        cached = self._cache.get(collection)
        if cached is not None and cached[0] == stamp:
            return cached[1]
        docs: dict[str, Doc] = {}
        if stamp is not None:
            self._backup(path)
            # Un archivo dañado se deja como está y se avisa: nunca se reescribe encima.
            raw = json.loads(path.read_text(encoding="utf-8"))
            items = raw.values() if isinstance(raw, dict) else raw
            for item in items:
                docs[str(item["id"])] = item
        self._cache[collection] = (stamp, docs)
        return docs

    def _backup(self, path: Path) -> None:
        backup = path.with_name(path.name + ".pre-store.bak")
        if not backup.exists():
            shutil.copy2(path, backup)

    def _write(self, collection: str, docs: dict[str, Doc]) -> None:
        path = self._path(collection)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(docs.values()), ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        self._cache[collection] = (self._stamp(path), docs)

    class _Locked:
        """El candado de hilos y, si hay fcntl, el de procesos."""

        def __init__(self, store: JsonDocStore) -> None:
            self.store = store
            self.handle = None

        def __enter__(self) -> None:
            self.store._lock.acquire()
            if fcntl is not None:
                self.handle = (self.store.root / ".store.lock").open("a")
                fcntl.flock(self.handle, fcntl.LOCK_EX)

        def __exit__(self, *exc: object) -> None:
            if self.handle is not None:
                fcntl.flock(self.handle, fcntl.LOCK_UN)
                self.handle.close()
            self.store._lock.release()

    # ----- contrato -----

    def get(self, collection: str, doc_id: str) -> Doc | None:
        with self._Locked(self):
            doc = self._load(collection).get(doc_id)
            return copy.deepcopy(doc) if doc is not None else None

    def set(self, collection: str, doc_id: str, data: Doc) -> None:
        with self._Locked(self):
            docs = dict(self._load(collection))
            docs[doc_id] = copy.deepcopy(data)
            self._write(collection, docs)

    def delete(self, collection: str, doc_id: str) -> None:
        with self._Locked(self):
            docs = self._load(collection)
            if doc_id in docs:
                docs = dict(docs)
                del docs[doc_id]
                self._write(collection, docs)

    def query(self, collection: str, where: dict[str, Any] | None = None, order_by: Order = (), limit: int | None = None) -> list[Doc]:
        with self._Locked(self):
            found = [copy.deepcopy(d) for d in self._load(collection).values() if matches(d, where)]
        found = sort_docs(found, order_by)
        return found[:limit] if limit is not None else found

    def transact(self, collection: str, doc_id: str, change: Change) -> Any:
        with self._Locked(self):
            docs = self._load(collection)
            current = docs.get(doc_id)
            result = change(copy.deepcopy(current) if current is not None else None)
            if result is DELETE:
                if doc_id in docs:
                    docs = dict(docs)
                    del docs[doc_id]
                    self._write(collection, docs)
            elif result is not None:
                docs = dict(docs)
                docs[doc_id] = copy.deepcopy(result)
                self._write(collection, docs)
            return result

