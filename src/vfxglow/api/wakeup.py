"""Despertar a los trabajadores bajo demanda (Cloud Run Job), para no pagar uno siempre encendido.

Con VEXORA_WORKER_JOB (`projects/<p>/locations/<r>/jobs/<nombre>`), cada vez que la API encola
algo (trabajo o tarea) mira si hay trabajadores vivos (latido en la colección `workers`,
api/workqueue.py). Si no hay suficientes, lanza una ejecución del Cloud Run Job `vexora-worker`,
que procesa la cola y sale solo tras VEXORA_WORKER_IDLE_EXIT_S sin trabajo.

Sin estampidas: el documento `system/worker_wake` guarda cuándo se lanzó cada ejecución reciente.
Se decide en una transacción: una ejecución lanzada hace menos de WINDOW_S cuenta como un
trabajador que está arrancando (el arranque en frío tarda ~30-60 s), así que diez trabajos
seguidos lanzan una sola. VEXORA_WORKER_MAX_PARALLEL (por defecto 1) permite varias a la vez si la
cola es profunda: tantas como elementos en cola, hasta ese tope.

Un fallo al lanzar nunca falla la petición de la persona: se registra y queda la telemetría
`worker.wake_failed`. El trabajo sigue en la cola y lo toma la siguiente ejecución.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from vfxglow import telemetry
from vfxglow.api import workqueue
from vfxglow.api.tasks import TASKS
from vfxglow.store.docs import DocStore

log = logging.getLogger("vfxglow.api")

JOB_ENV = "VEXORA_WORKER_JOB"
MAX_PARALLEL_ENV = "VEXORA_WORKER_MAX_PARALLEL"
SYSTEM = "system"
WAKE_DOC = "worker_wake"
# Cuánto cuenta una ejecución recién lanzada como "arrancando" (no se lanza otra en su lugar).
WINDOW_S = 60.0


def _job_name() -> str:
    return os.environ.get(JOB_ENV, "").strip()


def max_parallel() -> int:
    try:
        return max(int(os.environ.get(MAX_PARALLEL_ENV, "1") or 1), 1)
    except ValueError:
        return 1


def _cloud_run_client() -> Any:
    from google.cloud import run_v2

    return run_v2.JobsClient()


class Waker:
    """Decide si hay que lanzar ejecuciones del Job y las lanza. `client_factory` y `clock` se
    inyectan en las pruebas (un cliente falso con `run_job(name=...)`)."""

    def __init__(self, docs: DocStore, client_factory: Callable[[], Any] = _cloud_run_client, clock: Callable[[], float] = time.time, job_name: str | None = None) -> None:
        self.docs, self.clock = docs, clock
        self._factory = client_factory
        self._client: Any = None
        self._job = job_name
        self._lock = threading.Lock()

    @property
    def job(self) -> str:
        return self._job if self._job is not None else _job_name()

    @property
    def enabled(self) -> bool:
        return bool(self.job)

    def _depth(self) -> int:
        """Cuánto espera en la cola (trabajos y tareas)."""
        return len(self.docs.query(workqueue.COLLECTION, where={"status": "queued"})) + len(self.docs.query(TASKS, where={"status": "queued"}))

    def poke(self) -> int:
        """Lanza las ejecuciones que hagan falta. Devuelve cuántas lanzó (0 si no hacía falta, si no
        está configurado o si falló)."""
        if not self.enabled:
            return 0
        try:
            now = self.clock()
            alive = workqueue.alive_workers(self.docs, now)
            limit = max_parallel()
            if alive >= limit:
                return 0
            wanted = min(limit, max(self._depth(), 1)) - alive
            if wanted <= 0:
                return 0
            granted: dict[str, int] = {}

            def reserve(current: dict | None) -> dict | None:
                recent = [t for t in (current or {}).get("launched", []) if now - float(t) < WINDOW_S]
                count = max(wanted - len(recent), 0)
                granted["count"] = count
                if count == 0:
                    return None
                return {"id": WAKE_DOC, "launched": [*recent, *([now] * count)], "last": now}

            self.docs.transact(SYSTEM, WAKE_DOC, reserve)
            count = granted.get("count", 0)
            for _ in range(count):
                self._run()
            if count:
                telemetry.event("worker.woken", executions=count, alive=alive)
            return count
        except Exception as error:  # nunca rompe la petición que encoló
            log.exception("No se pudo despertar a los trabajadores (%s)", self.job)
            telemetry.event("worker.wake_failed", level=logging.WARNING, error={"kind": type(error).__name__, "message": telemetry.redact(str(error))[:300]})
            return 0

    def _run(self) -> None:
        with self._lock:
            if self._client is None:
                self._client = self._factory()
            client = self._client
        # No se espera a la operación: la ejecución arranca sola y toma la cola.
        client.run_job(name=self.job)

    def poke_later(self) -> None:
        """Como `poke`, en un hilo: la petición que encoló no espera a la API de Cloud Run."""
        if self.enabled:
            threading.Thread(target=self.poke, daemon=True, name="vexora-wake").start()
