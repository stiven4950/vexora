"""Cola de trabajos con varios trabajadores que comparten el almacén de documentos (store/).

Antes había un solo hilo y una cola en memoria. Ahora la cola son los propios documentos de
trabajo con estos campos (api/jobs.py, Job):

- `priority`: más alto, antes (hoy 0 para todos; `priority_for` es el gancho para darlo por el
  plan del dueño en configs/plans.yaml).
- `worker` y `lease_until`: quién lo procesa y hasta cuándo vale su turno. El trabajador lo
  renueva mientras trabaja (`Lease`); si muere, el turno vence y otro lo recupera (`reap`).
- `attempts`: cuántas veces se tomó. Tras MAX_ATTEMPTS turnos vencidos, falla como
  "interrupted" en vez de volver a la cola (un video que tumba al trabajador no lo tumba siempre).
- `cancel_requested`: la API pide parar; el trabajador lo ve en sus puntos de control (`StopFlag`).

Tomar un trabajo es una transacción (`claim`): de los primeros en la cola (prioridad y luego
antigüedad), el primero que siga libre al leerlo dentro de la transacción. Dos trabajadores nunca
toman el mismo.

Un trabajador puede ser un hilo de la API (VEXORA_INPROCESS_WORKERS, por defecto 1) o un proceso
aparte (`vexora-worker`, vfxglow/worker.py).

Además de los trabajos, la misma maquinaria (tomar, turno, latido, reintento) mueve las **tareas**
cortas de la colección `tasks` (api/tasks.py): análisis de subidas, vistas previas y capas. Todas
las funciones de abajo reciben la colección. Un trabajador acepta ciertos tipos (`kinds`): los de
la API, solo los suyos; los de `vexora-worker`, todos.

Para no pagar trabajadores ociosos: cada trabajador deja su latido en la colección `workers`
(`alive_workers` dice cuántos hay) y, con VEXORA_WORKER_IDLE_EXIT_S, sale tras ese tiempo sin
nada que tomar (nunca con un turno en la mano: solo sale entre vuelta y vuelta). La API lo
despierta al encolar (api/wakeup.py).
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from vfxglow.store.docs import Doc, DocStore

if TYPE_CHECKING:
    from vfxglow.api.jobs import JobStore

log = logging.getLogger("vfxglow.api")

COLLECTION = "jobs"
# Latido de cada trabajador vivo: {id, kinds, seen}. Lo lee la API para saber si hay alguien.
WORKERS = "workers"
# Cada cuánto escribe su latido un trabajador y cuánto vale (más de dos latidos perdidos = muerto).
BEAT_EVERY_S = 30.0
ALIVE_S = 90.0
MAX_ATTEMPTS = 3
LEASE_ENV = "VEXORA_LEASE_S"
POLL_ENV = "VEXORA_QUEUE_POLL_S"
IDLE_EXIT_ENV = "VEXORA_WORKER_IDLE_EXIT_S"
DEFAULT_LEASE_S = 60.0
# Cuántos candidatos se prueban por vuelta: si otro trabajador gana el primero, se intenta el siguiente.
SCAN = 5
# Cada cuánto se mira en el almacén si pidieron cancelar (el punto de control corre cada pocos fotogramas).
CANCEL_CHECK_S = 1.0


def _number(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def lease_seconds() -> float:
    return max(_number(LEASE_ENV, DEFAULT_LEASE_S), 1.0)


def poll_seconds(remote: bool) -> float:
    """Cada cuánto busca trabajo un trabajador sin nada que hacer. En local es barato; en
    Firestore cada consulta cuesta una lectura, así que se espera más."""
    return max(_number(POLL_ENV, 5.0 if remote else 1.0), 0.05)


def priority_for(owner: str | None) -> int:
    """Prioridad de un trabajo nuevo según su dueño. Hoy todos 0 (no hay suscripciones); el día
    que las haya, se lee el plan del dueño (api/plans.py, configs/plans.yaml)."""
    return 0


def new_worker_id(index: int = 0) -> str:
    """Único entre máquinas y reinicios: máquina, proceso, un azar corto y el número del hilo."""
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}-{index}"


# ----- operaciones sobre el almacén -----


def claim(
    docs: DocStore,
    worker_id: str,
    now: float,
    lease_s: float,
    collection: str = COLLECTION,
    where: dict[str, Any] | None = None,
    accept: Callable[[Doc], bool] | None = None,
) -> Doc | None:
    """Toma el siguiente en cola (más prioridad, luego el más viejo) o None si no hay. `where`
    filtra además por igualdad (p. ej. el tipo de tarea) y `accept` descarta candidatos (p. ej.
    una vista previa de alguien que ya tiene otra dibujándose)."""
    candidates = docs.query(collection, where={"status": "queued", "worker": None, **(where or {})}, order_by=[("priority", True), ("created", False)], limit=SCAN)
    for candidate in candidates:
        if accept is not None and not accept(candidate):
            continue

        def take(current: Doc | None) -> Doc | None:
            if current is None or current.get("status") != "queued" or current.get("worker") is not None:
                return None  # otro trabajador lo tomó (o se canceló) entre la consulta y ahora
            return {
                **current,
                "status": "running",
                "worker": worker_id,
                "lease_until": now + lease_s,
                "attempts": int(current.get("attempts") or 0) + 1,
                "cancel_requested": False,
            }

        taken = docs.transact(collection, candidate["id"], take)
        if taken is not None:
            return taken
    return None


def heartbeat(docs: DocStore, job_id: str, worker_id: str, now: float, lease_s: float, collection: str = COLLECTION) -> bool:
    """Alarga el turno. False si el trabajo ya no es de este trabajador (se recuperó o se borró)."""
    return docs.update(collection, job_id, {"lease_until": now + lease_s}, when={"status": "running", "worker": worker_id})


def _job_requeued(current: Doc, now: float) -> Doc:
    """Lo que se le pone a un trabajo que vuelve a la cola (su pantalla de proceso lo cuenta)."""
    note = {"at": now, "text": "De vuelta en la cola", "detail": "El proceso anterior se detuvo; se reintenta automáticamente."}
    return {"stage": "queued", "progress": 0.0, "message": "En cola", "started": None, "activity": [*(current.get("activity") or []), note][-12:]}


def reap(
    docs: DocStore,
    now: float,
    failed: Doc | Callable[[Doc], Doc],
    collection: str = COLLECTION,
    requeued: Callable[[Doc, float], Doc] | None = _job_requeued,
) -> list[tuple[str, str]]:
    """Los que se quedaron sin trabajador (dejó de renovar el turno): vuelven a la cola, o fallan
    con `failed` (o lo que devuelva `failed(doc)`) si ya se intentaron MAX_ATTEMPTS veces o se
    había pedido cancelarlos. Devuelve (id, "requeued" | "failed")."""
    outcomes: list[tuple[str, str]] = []
    for doc in docs.query(collection, where={"status": "running"}):
        lease = doc.get("lease_until")
        if lease is None or lease > now:
            continue  # vigente, o de un trabajador sin turnos (las pruebas lo ponen a mano)
        verdict: dict[str, str] = {}

        def expire(current: Doc | None) -> Doc | None:
            if current is None or current.get("status") != "running" or current.get("lease_until") is None or current["lease_until"] > now:
                return None
            released = {**current, "worker": None, "lease_until": None}
            if int(current.get("attempts") or 0) < MAX_ATTEMPTS and not current.get("cancel_requested"):
                verdict["outcome"] = "requeued"
                return {**released, "status": "queued", **(requeued(current, now) if requeued is not None else {})}
            verdict["outcome"] = "failed"
            return {**released, **(failed(current) if callable(failed) else failed), "finished": now}

        if docs.transact(collection, doc["id"], expire) is not None:
            outcomes.append((doc["id"], verdict["outcome"]))
    return outcomes


# ----- durante el proceso de un trabajo -----


class StopFlag:
    """Lo que lee telemetry.checkpoint(): ¿hay que parar este trabajo?

    Se pone desde el mismo proceso (la API con trabajador en hilo) o se descubre en el almacén,
    como mucho una vez por CANCEL_CHECK_S: `cancel_requested` (la persona canceló) o que el
    trabajo ya no sea de este trabajador (`lost`: su turno venció y otro lo tomó; no hay que
    borrar nada, solo dejar de trabajar)."""

    def __init__(self, docs: DocStore, job_id: str, worker_id: str, local: threading.Event | None = None, clock: Callable[[], float] = time.time, collection: str = COLLECTION) -> None:
        self.docs, self.job_id, self.worker_id, self.collection = docs, job_id, worker_id, collection
        self.local = local or threading.Event()
        self.clock = clock
        self.lost = False
        self._checked = float("-inf")

    def lose(self) -> None:
        self.lost = True
        self.local.set()

    def is_set(self) -> bool:
        if self.local.is_set():
            return True
        now = self.clock()
        if now - self._checked < CANCEL_CHECK_S:
            return False
        self._checked = now
        doc = self.docs.get(self.collection, self.job_id)
        if doc is None or doc.get("worker") != self.worker_id or doc.get("status") != "running":
            self.lose()
        elif doc.get("cancel_requested"):
            self.local.set()
        return self.local.is_set()


class Lease:
    """Renueva el turno de un trabajo cada tercio de su duración, en un hilo, mientras se procesa."""

    def __init__(self, docs: DocStore, job_id: str, worker_id: str, lease_s: float, flag: StopFlag, clock: Callable[[], float] = time.time, collection: str = COLLECTION) -> None:
        self.docs, self.job_id, self.worker_id, self.lease_s = docs, job_id, worker_id, lease_s
        self.collection = collection
        self.flag, self.clock = flag, clock
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"vexora-lease-{job_id}")

    def __enter__(self) -> Lease:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.wait(self.lease_s / 3):
            try:
                if not heartbeat(self.docs, self.job_id, self.worker_id, self.clock(), self.lease_s, self.collection):
                    log.warning("Trabajo %s: el turno ya no es de %s; se deja de procesar", self.job_id, self.worker_id)
                    self.flag.lose()
                    return
            except Exception:  # un fallo de red no mata el trabajo: se reintenta en la siguiente vuelta
                log.exception("Trabajo %s: no se pudo renovar el turno", self.job_id)


def beat(docs: DocStore, worker_id: str, kinds: tuple[str, ...] | None, now: float) -> None:
    """El latido de un trabajador vivo (lo lee `alive_workers`)."""
    docs.set(WORKERS, worker_id, {"id": worker_id, "kinds": list(kinds) if kinds is not None else ["*"], "seen": now})


def alive_workers(docs: DocStore, now: float) -> int:
    """Cuántos trabajadores dieron latido hace menos de ALIVE_S (en cualquier máquina)."""
    return sum(float(doc.get("seen") or 0) > now - ALIVE_S for doc in docs.query(WORKERS))


def idle_exit_seconds() -> float | None:
    """VEXORA_WORKER_IDLE_EXIT_S: tras cuántos segundos sin nada que tomar sale `vexora-worker`.
    Sin valor (o 0), nunca."""
    value = _number(IDLE_EXIT_ENV, 0.0)
    return value if value > 0 else None


class Worker(threading.Thread):
    """Un trabajador: recupera turnos vencidos, toma un trabajo o una tarea, lo procesa y vuelve a
    empezar. Sin nada que hacer, espera `poll_s` o a que la API de este mismo proceso avise que
    encoló algo. `kinds`: qué toma ("job" y tipos de tarea); None = todo lo que este proceso sabe
    hacer. Con `idle_exit_s`, termina tras ese tiempo sin nada que tomar (solo entre vueltas: nunca
    con un turno en la mano)."""

    def __init__(
        self,
        store: JobStore,
        worker_id: str | None = None,
        poll_s: float | None = None,
        stop: threading.Event | None = None,
        kinds: tuple[str, ...] | None = None,
        idle_exit_s: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.store = store
        self.worker_id = worker_id or new_worker_id()
        super().__init__(daemon=True, name=f"vfxglow-jobs-{self.worker_id}")
        self.poll_s = poll_s if poll_s is not None else poll_seconds(store.docs.remote)
        self.stop = stop or threading.Event()
        self.kinds = kinds
        self.idle_exit_s = idle_exit_s
        self.clock = clock or time.time
        self.wake = store.waiter() if hasattr(store, "waiter") else threading.Event()
        self.idle_exited = False
        self._beat_at = float("-inf")

    def run(self) -> None:
        last_busy = self.clock()
        try:
            while not self.stop.is_set():
                self._beat()
                try:
                    busy = self.step()
                except Exception:  # p. ej. Firestore no responde: se reintenta en la siguiente vuelta
                    log.exception("Trabajador %s: fallo al buscar trabajo", self.worker_id)
                    busy = False
                if busy:
                    last_busy = self.clock()
                    continue
                if self.idle_exit_s is not None and self.clock() - last_busy >= self.idle_exit_s:
                    self.idle_exited = True
                    log.info("Trabajador %s: %.0f s sin trabajo, sale", self.worker_id, self.idle_exit_s)
                    return
                self.store.wait_for_work(self.poll_s, self.wake)
        finally:
            self._forget()

    def _beat(self) -> None:
        now = self.clock()
        if now - self._beat_at < BEAT_EVERY_S:
            return
        self._beat_at = now
        try:
            beat(self.store.docs, self.worker_id, self.kinds, time.time())
        except Exception:  # el latido es informativo: un fallo no detiene al trabajador
            log.exception("Trabajador %s: no se pudo escribir el latido", self.worker_id)

    def _forget(self) -> None:
        try:
            self.store.docs.delete(WORKERS, self.worker_id)
        except Exception:
            log.exception("Trabajador %s: no se pudo borrar el latido", self.worker_id)

    def step(self) -> bool:
        """Una vuelta: devuelve si procesó algo. Las pruebas la llaman sin hilo."""
        self.store.reap_expired()
        doc = self.store.claim(self.worker_id, self.kinds)
        if doc is None:
            return False
        self.store.process(doc, self.worker_id)
        return True


def run_workers(store: Any, count: int, stop: threading.Event, kinds: tuple[str, ...] | None = None, idle_exit_s: float | None = None) -> list[Worker]:
    """Arranca `count` trabajadores sobre `store` (comparten `stop`)."""
    workers = [Worker(store, new_worker_id(i), stop=stop, kinds=kinds, idle_exit_s=idle_exit_s) for i in range(count)]
    for worker in workers:
        worker.start()
    return workers
