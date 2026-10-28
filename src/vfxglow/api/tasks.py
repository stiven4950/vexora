"""Tareas cortas en la misma cola que los trabajos: análisis de subidas, vistas previas y capas.

Antes cada una era un hilo de la API con su estado en memoria, así que la API no podía tener más
de una instancia. Ahora son documentos de la colección `tasks` que toman los trabajadores
(api/workqueue.py) igual que los trabajos: con turno, latido, reintento y prioridad. El estado y
los resultados viven en el almacén (documentos y archivos); la API solo encola y lee.

Un documento de tarea:

    {id, kind, owner, ref, payload, status: queued|running|done|failed, priority,
     worker, lease_until, attempts, cancel_requested, created, started, finished,
     error, error_code, result}

- `kind`: "preview" (editor y Estudio), "upload" (sondeo y análisis de una subida) o "layers"
  (mosaico de la vista en vivo).
- `ref`: el trabajo o la subida al que pertenece (para borrarlas con él).
- `id`: lo elige quien la crea y sirve de caché: la vista previa usa el hash de lo que se dibuja,
  las capas `l_<trabajo>` y la subida su propio id.

Prioridad (más alto, antes; los trabajos van con 0): las vistas previas (unos segundos, alguien
mira la pantalla esperando) antes que el análisis de una subida (la persona elige estilo mientras
tanto y el trabajo lo reutiliza), este antes que las capas (opcionales, ~0,1 s por fotograma) y
todas antes que los trabajos (minutos; la persona ya sabe que espera).
"""

from __future__ import annotations

import time
from typing import Any

TASKS = "tasks"
PREVIEW, UPLOAD, LAYERS = "preview", "upload", "layers"
KINDS = (PREVIEW, UPLOAD, LAYERS)
PRIORITY = {PREVIEW: 30, UPLOAD: 20, LAYERS: 10}


def new_task(task_id: str, kind: str, owner: str | None, ref: str, payload: dict[str, Any] | None = None, now: float | None = None) -> dict[str, Any]:
    """Un documento de tarea en cola (todos los campos presentes: Firestore filtra `worker == None`
    solo si el campo existe)."""
    return {
        "id": task_id,
        "kind": kind,
        "owner": owner,
        "ref": ref,
        "payload": payload or {},
        "status": "queued",
        "priority": PRIORITY[kind],
        "worker": None,
        "lease_until": None,
        "attempts": 0,
        "cancel_requested": False,
        "created": now if now is not None else time.time(),
        "started": None,
        "finished": None,
        "error": None,
        "error_code": None,
        "result": {},
    }


def pending(doc: dict | None) -> bool:
    """En cola o procesándose."""
    return doc is not None and doc.get("status") in ("queued", "running")
