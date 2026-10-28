"""Borrar una cuenta entera: trabajos, subidas, enlaces, avisos, foto y perfil.

Cada trabajo se borra por el mismo camino que "Eliminar" en Mis proyectos (`JobStore.delete`):
su MP4, miniaturas, vistas previas, capas, artefactos del editor, archivos del almacén y la
carpeta del análisis si ningún otro trabajo la usa. Los que se están procesando se cancelan
primero. Es idempotente: repetirlo solo devuelve ceros.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from vfxglow import telemetry
from vfxglow.api import notifications, profiles, shares
from vfxglow.api.jobs import COLLECTION as JOBS
from vfxglow.api.jobs import JobBusy, JobStore
from vfxglow.api.uploads import COLLECTION as UPLOADS
from vfxglow.api.uploads import UploadNotFound, UploadStore

CONFIRM_WORD = "ELIMINAR"
# Cuánto se espera a que un trabajo cancelado en curso se corte en su siguiente punto de control.
STOP_WAIT_S = 20.0


def delete_account(
    jobs: JobStore,
    uploads: UploadStore,
    uid: str,
    forget_previews: Callable[[str], None] = lambda _id: None,
    wait_s: float = STOP_WAIT_S,
) -> dict[str, int]:
    """Borra todo lo de `uid` y devuelve el resumen. `pending` cuenta los trabajos en curso que no
    alcanzaron a cortarse: ya tienen la orden de parar y se borran solos al hacerlo."""
    docs = jobs.docs
    mine = [job.id for job in jobs.list(uid)]
    share_count = len(docs.query(shares.COLLECTION, where={"uid": uid}))  # borrar los trabajos borra sus enlaces
    for job_id in mine:
        jobs.cancel(job_id)  # en cola se borra ya; en curso se pide parar
    deadline = time.monotonic() + wait_s
    pending = 0
    for job_id in mine:
        while True:
            try:
                jobs.delete(job_id)  # False si el cancelar ya lo borró
                break
            except JobBusy:
                if time.monotonic() >= deadline:
                    pending += 1
                    break
                time.sleep(0.1)
        forget_previews(job_id)
    removed_jobs = len(mine) - pending

    upload_ids = [doc["id"] for doc in docs.query(UPLOADS, where={"owner": uid})]
    for upload_id in upload_ids:
        try:
            uploads.delete(upload_id, uid)
        except UploadNotFound:
            pass
        forget_previews(upload_id)

    summary = {
        "jobs": removed_jobs,
        "pending": pending,
        "uploads": len(upload_ids),
        "shares": share_count + shares.erase_user(docs, uid),
        "notifications": notifications.erase(docs, uid),
        "avatar": int(_erase_avatar(jobs, uid)),
        "profile": int(profiles.erase(docs, uid)),
    }
    telemetry.event("user.deleted", usr={"id": telemetry.user_ref(uid)}, **summary)
    return summary


def _erase_avatar(jobs: JobStore, uid: str) -> bool:
    key = profiles.avatar_key(uid)
    present = jobs.blobs.exists(key)
    jobs.blobs.delete(key)
    return present
