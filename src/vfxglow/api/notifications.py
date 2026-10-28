"""Avisos de cada persona (la campana de la barra superior): colección `notifications`.

Los crea el JobStore al terminar o fallar un trabajo (así funciona aunque el trabajador sea otro
proceso) y la API los lista y marca como leídos. Solo se guardan los últimos KEEP por persona.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from vfxglow.api import profiles
from vfxglow.store.docs import DocStore

COLLECTION = "notifications"
KEEP = 50


def notify(docs: DocStore, uid: str, kind: str, title: str, text: str, job_id: str | None = None, pref: str = "processing") -> dict[str, Any] | None:
    """Crea el aviso si la persona quiere ese tipo (`pref`). Devuelve el aviso, o None si no."""
    if not profiles.wants(docs, uid, pref):
        return None
    item = {"id": uuid.uuid4().hex, "uid": uid, "kind": kind, "title": title, "text": text, "job_id": job_id, "created": time.time(), "read": False}
    docs.set(COLLECTION, item["id"], item)
    for old in docs.query(COLLECTION, where={"uid": uid}, order_by=[("created", True)])[KEEP:]:
        docs.delete(COLLECTION, old["id"])
    return item


def listing(docs: DocStore, uid: str) -> tuple[list[dict[str, Any]], int]:
    """Los avisos de `uid` (el más nuevo primero) y cuántos faltan por leer."""
    items = docs.query(COLLECTION, where={"uid": uid}, order_by=[("created", True)], limit=KEEP)
    return items, sum(1 for item in items if not item.get("read"))


def mark_read(docs: DocStore, uid: str, ids: list[str] | None) -> int:
    """Marca como leídos los avisos `ids` de `uid` (todos si `ids` es None). Los ajenos se ignoran."""
    changed = 0
    for item in docs.query(COLLECTION, where={"uid": uid, "read": False}):
        if ids is None or item["id"] in ids:
            changed += int(docs.update(COLLECTION, item["id"], {"read": True}, when={"uid": uid}))
    return changed


def erase(docs: DocStore, uid: str) -> int:
    items = docs.query(COLLECTION, where={"uid": uid})
    for item in items:
        docs.delete(COLLECTION, item["id"])
    return len(items)
