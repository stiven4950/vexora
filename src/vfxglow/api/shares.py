"""Enlaces públicos y revocables a un video terminado: colección `shares`.

El documento se llama como su token (url-safe, 192 bits al azar: no se adivina). Quien tiene el
enlace ve el video sin iniciar sesión hasta que el dueño lo revoca; revocar es inmediato porque
cada petición pública lee el documento. Cuando se borra el trabajo o la cuenta, sus enlaces se borran.
"""

from __future__ import annotations

import secrets
import time
from typing import Any

from vfxglow.store.docs import DocStore

COLLECTION = "shares"


def active(docs: DocStore, job_id: str) -> dict[str, Any] | None:
    found = [s for s in docs.query(COLLECTION, where={"job_id": job_id, "revoked_at": None}, order_by=[("created", True)])]
    return found[0] if found else None


def create(docs: DocStore, job_id: str, uid: str) -> dict[str, Any]:
    """El enlace activo del trabajo, o uno nuevo si no hay."""
    existing = active(docs, job_id)
    if existing is not None:
        return existing
    token = secrets.token_urlsafe(24)
    item = {"id": token, "token": token, "job_id": job_id, "uid": uid, "created": time.time(), "revoked_at": None, "views": 0}
    docs.set(COLLECTION, token, item)
    return item


def revoke(docs: DocStore, job_id: str) -> bool:
    """Revoca el enlace activo. Devuelve si había uno."""
    item = active(docs, job_id)
    if item is None:
        return False
    return docs.update(COLLECTION, item["id"], {"revoked_at": time.time()}, when={"revoked_at": None})


def lookup(docs: DocStore, token: str) -> dict[str, Any] | None:
    """El enlace si existe y no está revocado."""
    item = docs.get(COLLECTION, token) if token and len(token) <= 128 else None
    return item if item is not None and item.get("revoked_at") is None else None


def count_view(docs: DocStore, token: str) -> None:
    docs.transact(COLLECTION, token, lambda c: {**c, "views": int(c.get("views", 0)) + 1} if c is not None and c.get("revoked_at") is None else None)


def erase_job(docs: DocStore, job_id: str) -> int:
    items = docs.query(COLLECTION, where={"job_id": job_id})
    for item in items:
        docs.delete(COLLECTION, item["id"])
    return len(items)


def erase_user(docs: DocStore, uid: str) -> int:
    items = docs.query(COLLECTION, where={"uid": uid})
    for item in items:
        docs.delete(COLLECTION, item["id"])
    return len(items)
