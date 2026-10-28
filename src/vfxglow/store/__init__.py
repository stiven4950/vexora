"""Dónde vive el estado persistente: documentos (store/docs.py) y archivos (store/blobs.py).

Se elige por entorno; sin variables, todo queda como siempre (JSON y archivos en api_data/):

- VEXORA_STORE=json|firestore   (por defecto json)
- VEXORA_BLOBS=local|gcs        (por defecto local; gcs pide VEXORA_BUCKET)
"""

from __future__ import annotations

import os
from pathlib import Path

from vfxglow.store.blobs import BlobStore, GcsBlobStore, LocalBlobStore
from vfxglow.store.docs import DELETE, DocStore, JsonDocStore, MemoryDocStore

STORE_ENV = "VEXORA_STORE"
BLOBS_ENV = "VEXORA_BLOBS"

__all__ = ["DELETE", "BlobStore", "DocStore", "GcsBlobStore", "JsonDocStore", "LocalBlobStore", "MemoryDocStore", "open_blobs", "open_docs"]


def open_docs(root: Path) -> DocStore:
    kind = os.environ.get(STORE_ENV, "json").strip().lower() or "json"
    if kind == "json":
        return JsonDocStore(root)
    if kind == "firestore":
        from vfxglow.store.firestore import FirestoreDocStore

        return FirestoreDocStore()
    raise ValueError(f"{STORE_ENV} desconocido: {kind} (usa json o firestore)")


def open_blobs(root: Path) -> BlobStore:
    kind = os.environ.get(BLOBS_ENV, "local").strip().lower() or "local"
    if kind == "local":
        return LocalBlobStore(root)
    if kind == "gcs":
        return GcsBlobStore()
    raise ValueError(f"{BLOBS_ENV} desconocido: {kind} (usa local o gcs)")
