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


def today() -> str:
    """El día (UTC) con que se cuentan las vistas diarias de un enlace."""
    return time.strftime("%Y-%m-%d", time.gmtime())


def over_daily(item: dict[str, Any], cap: int | None) -> bool:
    """Si el enlace ya llegó hoy a su tope de vistas (`cap` del plan del dueño; None = sin tope)."""
    return cap is not None and item.get("day") == today() and int(item.get("views_today", 0)) >= cap


def count_view(docs: DocStore, token: str, cap: int | None = None) -> str:
    """Cuenta una visita. Devuelve "ok", "over" si ya llegó al tope de hoy (no se cuenta) o "reached"
    si esta fue la que llegó al tope y aún no se había avisado al dueño hoy (se avisa una vez al día)."""
    outcome = {"result": "over"}
    day = today()

    def bump(current: dict | None):
        if current is None or current.get("revoked_at") is not None:
            return None
        views_today = int(current.get("views_today", 0)) if current.get("day") == day else 0
        if cap is not None and views_today >= cap:
            return None
        views_today += 1
        reached = cap is not None and views_today >= cap and current.get("limit_notified") != day
        outcome["result"] = "reached" if reached else "ok"
        changes = {"views": int(current.get("views", 0)) + 1, "day": day, "views_today": views_today}
        if reached:
            changes["limit_notified"] = day
        return {**current, **changes}

    docs.transact(COLLECTION, token, bump)
    return outcome["result"]


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
