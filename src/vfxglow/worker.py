"""Trabajadores de la cola en un proceso aparte de la API (Cloud Run, o una terminal en local).

    vexora-worker                    # o: python -m vfxglow.worker
    VEXORA_WORKERS=2 vexora-worker   # dos trabajos a la vez en este proceso

Toman trabajos del mismo almacén que la API (VEXORA_STORE, VEXORA_BLOBS; ver
docs/despliegue_cloud_run.md). Con este proceso en marcha, la API va con
VEXORA_INPROCESS_WORKERS=0 para no competir por la CPU.

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


def main() -> None:
    from vfxglow.api.jobs import JobStore
    from vfxglow.cli import load_env_file

    root = Path(os.environ.get("VFXGLOW_ROOT", Path.cwd()))
    load_env_file(root / ".env")
    telemetry.setup("vexora-worker", root / "logs")
    count = max(int(os.environ.get(WORKERS_ENV, "1") or 1), 1)
    store = JobStore(root / "api_data", root / "configs" / "default.yaml", workers=count)
    if os.environ.get("PORT"):
        _health(int(os.environ["PORT"]), store.workers)
    signal.signal(signal.SIGTERM, lambda *_: store.close())
    signal.signal(signal.SIGINT, lambda *_: store.close())
    telemetry.event("worker.started", workers=count, store=type(store.docs).__name__, blobs=type(store.blobs).__name__)
    store.stop.wait()
    for worker in store.workers:
        worker.join(timeout=8)  # Cloud Run da ~10 s tras SIGTERM
    telemetry.event("worker.stopped", workers=count)


if __name__ == "__main__":
    main()
