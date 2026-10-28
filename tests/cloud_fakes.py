"""Firestore y Cloud Storage de mentira para probar store/firestore.py y store/blobs.py sin red.

Imitan solo lo que usa el código: documentos con get/set/update/delete, consultas con where
(FieldFilter), order_by, limit y stream, transacciones con el decorador `transactional`, y un
bucket con blob(...).upload_from_filename/download_to_filename/exists/delete/generate_signed_url,
get_blob (con `size`) y copy_blob. `FakeBucket.put_signed` imita al navegador que sube con la URL
firmada de PUT: comprueba el tipo y el tope de tamaño que la firma exige.
"""

from __future__ import annotations

import copy
import shutil
import threading
from pathlib import Path


class NotFound(Exception):
    code = 404


# ----- Firestore -----


def field_filter(field: str, op: str, value: object) -> tuple:
    assert op == "=="
    return (field, value)


class _Snap:
    def __init__(self, data: dict | None) -> None:
        self.exists = data is not None
        self._data = copy.deepcopy(data)

    def to_dict(self) -> dict | None:
        return copy.deepcopy(self._data)


class _Ref:
    def __init__(self, client: FakeFirestore, collection: str, doc_id: str) -> None:
        self.client, self.collection, self.id = client, collection, doc_id

    def get(self, transaction: object = None) -> _Snap:
        with self.client.lock:
            return _Snap(self.client.data.setdefault(self.collection, {}).get(self.id))

    def set(self, data: dict) -> None:
        with self.client.lock:
            self.client.data.setdefault(self.collection, {})[self.id] = copy.deepcopy(data)

    def update(self, fields: dict) -> None:
        with self.client.lock:
            docs = self.client.data.setdefault(self.collection, {})
            if self.id not in docs:
                raise NotFound(self.id)
            docs[self.id].update(copy.deepcopy(fields))

    def delete(self) -> None:
        with self.client.lock:
            self.client.data.setdefault(self.collection, {}).pop(self.id, None)


class _Query:
    def __init__(self, client: FakeFirestore, collection: str, filters=(), orders=(), cap=None) -> None:
        self.client, self.collection = client, collection
        self.filters, self.orders, self.cap = list(filters), list(orders), cap

    def document(self, doc_id: str) -> _Ref:
        return _Ref(self.client, self.collection, doc_id)

    def where(self, filter: tuple) -> _Query:  # noqa: A002 (mismo nombre que la librería)
        return _Query(self.client, self.collection, [*self.filters, filter], self.orders, self.cap)

    def order_by(self, field: str, direction: str = "ASCENDING") -> _Query:
        assert direction in ("ASCENDING", "DESCENDING")
        return _Query(self.client, self.collection, self.filters, [*self.orders, (field, direction == "DESCENDING")], self.cap)

    def limit(self, n: int) -> _Query:
        return _Query(self.client, self.collection, self.filters, self.orders, n)

    def stream(self):
        self.client.queries.append((self.collection, list(self.filters), list(self.orders)))
        with self.client.lock:
            # Como Firestore: un campo que falta no es igual a None.
            docs = [copy.deepcopy(d) for d in self.client.data.get(self.collection, {}).values() if all(k in d and d[k] == v for k, v in self.filters)]
        for field, descending in reversed(self.orders):
            docs.sort(key=lambda d: (d.get(field) is not None, d.get(field) or 0), reverse=descending)
        for doc in docs[: self.cap] if self.cap is not None else docs:
            yield _Snap(doc)


class _Transaction:
    def __init__(self, client: FakeFirestore) -> None:
        self.client = client
        self.writes: list = []

    def set(self, ref: _Ref, data: dict) -> None:
        self.writes.append(("set", ref, data))

    def delete(self, ref: _Ref) -> None:
        self.writes.append(("delete", ref, None))


class FakeFirestore:
    def __init__(self) -> None:
        # RLock: la transacción de mentira lee y escribe con el candado tomado (atómica).
        self.lock = threading.RLock()
        self.data: dict[str, dict[str, dict]] = {}
        self.queries: list = []

    def collection(self, name: str) -> _Query:
        return _Query(self, name)

    def transaction(self) -> _Transaction:
        return _Transaction(self)


def transactional(fn):
    """Como google.cloud.firestore.transactional: corre `fn(tx)` y confirma sus escrituras."""

    def run(transaction: _Transaction):
        with transaction.client.lock:
            result = fn(transaction)
            for kind, ref, data in transaction.writes:
                ref.set(data) if kind == "set" else ref.delete()
            return result

    return run


# ----- Cloud Storage -----


class _Blob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self.bucket, self.name = bucket, name

    @property
    def size(self) -> int | None:
        data = self.bucket.objects.get(self.name)
        return len(data) if data is not None else None

    def upload_from_filename(self, filename: str, content_type: str | None = None) -> None:
        self.bucket.objects[self.name] = Path(filename).read_bytes()
        self.bucket.calls.append(("upload", self.name, content_type))

    def download_to_filename(self, filename: str) -> None:
        self.bucket.calls.append(("download", self.name))
        if self.name not in self.bucket.objects:
            raise NotFound(self.name)
        Path(filename).write_bytes(self.bucket.objects[self.name])

    def exists(self) -> bool:
        self.bucket.calls.append(("exists", self.name))
        return self.name in self.bucket.objects

    def delete(self) -> None:
        if self.name not in self.bucket.objects:
            raise NotFound(self.name)
        del self.bucket.objects[self.name]

    def generate_signed_url(self, **kwargs) -> str:
        self.bucket.signed.append((self.name, kwargs))
        return f"https://storage.example/{self.name}?firma=1&metodo={kwargs.get('method', 'GET')}"


class FakeBucket:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.calls: list = []
        self.signed: list = []

    def blob(self, name: str) -> _Blob:
        return _Blob(self, name)

    def list_blobs(self, prefix: str = ""):
        return [_Blob(self, name) for name in list(self.objects) if name.startswith(prefix)]

    def get_blob(self, name: str) -> _Blob | None:
        self.calls.append(("get", name))
        return _Blob(self, name) if name in self.objects else None

    def copy_blob(self, blob: _Blob, destination_bucket: FakeBucket, new_name: str) -> _Blob:
        if blob.name not in self.objects:
            raise NotFound(blob.name)
        destination_bucket.objects[new_name] = self.objects[blob.name]
        self.calls.append(("copy", blob.name, new_name))
        return _Blob(destination_bucket, new_name)

    def put_signed(self, url: str, data: bytes, headers: dict[str, str]) -> int:
        """El navegador sube con la URL firmada: 403 si el tipo no es el firmado, 400 si pasa del tope."""
        name = url.split("https://storage.example/", 1)[1].split("?", 1)[0]
        signed = next(kwargs for key, kwargs in reversed(self.signed) if key == name and kwargs.get("method") == "PUT")
        if headers.get("Content-Type") != signed.get("content_type"):
            return 403
        for header, value in (signed.get("headers") or {}).items():
            if headers.get(header) != value:
                return 403
        low, high = (int(x) for x in signed["headers"]["x-goog-content-length-range"].split(","))
        if not low <= len(data) <= high:
            return 400
        self.objects[name] = data
        return 200


def remove_local(path: Path) -> None:
    """Simula otra máquina: el archivo no está en este disco."""
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
