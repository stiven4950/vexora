"""DocStore sobre Firestore (VEXORA_STORE=firestore), para la API y los trabajadores en Cloud Run.

Las librerías de Google se importan aquí dentro y solo al usarlo: la instalación por defecto no
las necesita (extra `[cloud]` en pyproject). Las credenciales salen de
GOOGLE_APPLICATION_CREDENTIALS en local o de la cuenta de servicio del servicio en Cloud Run; el
proyecto, de VEXORA_FIREBASE_PROJECT.

Notas de Firestore que el resto del código respeta:
- Un filtro `campo == None` solo encuentra documentos que tienen el campo guardado como null:
  los trabajos siempre se guardan completos (Job.model_dump), así que lo tienen.
- Filtro de igualdad + orden en otro campo pide un índice compuesto (firestore.indexes.json).
"""

from __future__ import annotations

import copy
import os
from typing import Any

from vfxglow.store.docs import DELETE, Change, Doc, DocStore, Order

PROJECT_ENV = "VEXORA_FIREBASE_PROJECT"
# Prefijo de las colecciones (p. ej. "staging_"): varios entornos en el mismo proyecto.
PREFIX_ENV = "VEXORA_FIRESTORE_PREFIX"


def _not_found(error: Exception) -> bool:
    return getattr(error, "code", None) == 404 or type(error).__name__ == "NotFound"


class FirestoreDocStore(DocStore):
    remote = True

    def __init__(self, client: Any = None, transactional: Any = None, field_filter: Any = None, prefix: str | None = None) -> None:
        """`client`, `transactional` y `field_filter` se pueden inyectar (las pruebas usan un
        cliente falso); sin ellos, los de google-cloud-firestore."""
        if client is None:
            from google.cloud import firestore

            client = firestore.Client(project=os.environ.get(PROJECT_ENV) or None)
        if transactional is None:
            from google.cloud.firestore import transactional
        if field_filter is None:
            from google.cloud.firestore_v1.base_query import FieldFilter as field_filter
        self.client = client
        self.prefix = os.environ.get(PREFIX_ENV, "") if prefix is None else prefix
        self._transactional = transactional
        self._field_filter = field_filter

    def _doc(self, collection: str, doc_id: str) -> Any:
        return self.client.collection(self.prefix + collection).document(doc_id)

    def get(self, collection: str, doc_id: str) -> Doc | None:
        snap = self._doc(collection, doc_id).get()
        return snap.to_dict() if snap.exists else None

    def set(self, collection: str, doc_id: str, data: Doc) -> None:
        self._doc(collection, doc_id).set(copy.deepcopy(data))

    def delete(self, collection: str, doc_id: str) -> None:
        self._doc(collection, doc_id).delete()

    def query(self, collection: str, where: dict[str, Any] | None = None, order_by: Order = (), limit: int | None = None) -> list[Doc]:
        query = self.client.collection(self.prefix + collection)
        for field, value in (where or {}).items():
            query = query.where(filter=self._field_filter(field, "==", value))
        for field, descending in order_by:
            query = query.order_by(field, direction="DESCENDING" if descending else "ASCENDING")
        if limit is not None:
            query = query.limit(limit)
        return [snap.to_dict() for snap in query.stream()]

    def update(self, collection: str, doc_id: str, fields: Doc, when: dict[str, Any] | None = None) -> bool:
        """Sin condición, una sola escritura (merge de campos de primer nivel); con condición, transacción."""
        if when is not None:
            return super().update(collection, doc_id, fields, when)
        try:
            self._doc(collection, doc_id).update(copy.deepcopy(fields))
        except Exception as error:  # el documento ya no existe (p. ej. se borró el trabajo)
            if _not_found(error):
                return False
            raise
        return True

    def transact(self, collection: str, doc_id: str, change: Change) -> Any:
        ref = self._doc(collection, doc_id)

        def attempt(transaction: Any) -> Any:
            snap = ref.get(transaction=transaction)
            result = change(snap.to_dict() if snap.exists else None)
            if result is DELETE:
                transaction.delete(ref)
            elif result is not None:
                transaction.set(ref, copy.deepcopy(result))
            return result

        return self._transactional(attempt)(self.client.transaction())
