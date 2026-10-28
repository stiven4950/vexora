"""Trabajadores de la cola en un proceso aparte de la API (Cloud Run, o una terminal en local).

    vexora-worker                    # o: python -m vfxglow.worker
    VEXORA_WORKERS=2 vexora-worker   # dos trabajos a la vez en este proceso

Toman trabajos y tareas (análisis de subidas, vistas previas, capas; api/tasks.py) del mismo
almacén que la API (VEXORA_STORE, VEXORA_BLOBS; ver docs/despliegue_cloud_run.md). Con este
proceso en marcha, la API va con VEXORA_INPROCESS_WORKERS=0 para no competir por la CPU.

- VEXORA_WORKER_KINDS=preview,upload  limita qué toma (job, preview, upload, layers); sin valor, todo.
- VEXORA_WORKER_IDLE_EXIT_S=60  sale (código 0) tras 60 s sin nada que tomar: para correr como
  Cloud Run Job que la API lanza al encolar (api/wakeup.py) y no pagar un trabajador ocioso. Solo
  sale entre vuelta y vuelta, nunca con un turno en la mano.

Si existe PORT (Cloud Run lo pone en un servicio), responde 200 en ese puerto: un servicio de
Cloud Run que no escucha no arranca. Con SIGTERM deja de tomar trabajos; el que esté en curso, si
no alcanza a terminar, vuelve a la cola cuando vence su turno (api/workqueue.py).
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from vfxglow import telemetry

WORKERS_ENV = "VEXORA_WORKERS"
KINDS_ENV = "VEXORA_WORKER_KINDS"

log = logging.getLogger("vfxglow.worker")


def _health(port: int, workers: list) -> None:
    """Un HTTP mínimo para Cloud Run: 200 mientras quede algún trabajador vivo."""

    class Health(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (nombre de http.server)
            alive = sum(worker.is_alive() for worker in workers)
            body = json.dumps({"ok": alive > 0, "workers": alive}).encode()
            self.send_response(200 if alive else 503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:  # sin una línea por sondeo
            return

    server = ThreadingHTTPServer(("0.0.0.0", port), Health)
    threading.Thread(target=server.serve_forever, daemon=True, name="vexora-health").start()


def kinds_from_env() -> tuple[str, ...] | None:
    """Qué toma este proceso (VEXORA_WORKER_KINDS); None = todo."""
    raw = [kind.strip() for kind in os.environ.get(KINDS_ENV, "").split(",") if kind.strip()]
    return tuple(raw) or None


def open_store(root: Path, count: int, kinds: tuple[str, ...] | None = None, idle_exit_s: float | None = None):
    """El almacén de un proceso trabajador con todo lo que sabe hacer registrado: trabajos y las
    tareas de subidas, vistas previas y capas (sin hilos propios por tipo: lo toman `count`
    trabajadores por prioridad)."""
    from vfxglow.api.jobs import JobStore
    from vfxglow.api.layers import LayerStore
    from vfxglow.api.previews import PreviewStore
    from vfxglow.api.uploads import UploadStore, catalog_names

    store = JobStore(root / "api_data", root / "configs" / "default.yaml", workers=count, worker_kinds=kinds, lanes=False, idle_exit_s=idle_exit_s)
    UploadStore(store, lambda: catalog_names(root))
    PreviewStore(store)
    LayerStore(store)
    store.wake_all()
    return store


def main() -> None:
    from vfxglow.api.workqueue import idle_exit_seconds
    from vfxglow.cli import load_env_file

    root = Path(os.environ.get("VFXGLOW_ROOT", Path.cwd()))
    load_env_file(root / ".env")
    telemetry.setup("vexora-worker", root / "logs")
    count = max(int(os.environ.get(WORKERS_ENV, "1") or 1), 1)
    idle = idle_exit_seconds()
    store = open_store(root, count, kinds_from_env(), idle)
    if os.environ.get("PORT"):
        _health(int(os.environ["PORT"]), store.workers)
    signal.signal(signal.SIGTERM, lambda *_: store.close())
    signal.signal(signal.SIGINT, lambda *_: store.close())
    telemetry.event("worker.started", workers=count, store=type(store.docs).__name__, blobs=type(store.blobs).__name__, idle_exit_s=idle)
    # Hasta que pidan parar o (con VEXORA_WORKER_IDLE_EXIT_S) todos salgan por inactividad.
    while not store.stop.wait(1.0) and any(worker.is_alive() for worker in store.workers):
        pass
    store.close()
    for worker in store.workers:
        worker.join(timeout=8)  # Cloud Run da ~10 s tras SIGTERM
    idle_exit = all(getattr(worker, "idle_exited", False) for worker in store.workers)
    telemetry.event("worker.stopped", workers=count, reason="idle" if idle_exit else "signal")


if __name__ == "__main__":
    main()
