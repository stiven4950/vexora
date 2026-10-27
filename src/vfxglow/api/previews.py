"""Vista previa rápida del editor: ~3 s alrededor del cabezal con el motor real, sin crear versión.

Un hilo aparte del de los trabajos (un render largo no la bloquea ni ella a él). Un render a la vez
por usuario: si llega otro mientras el anterior sigue en cola, el anterior se descarta. El
resultado se guarda por hash de (trabajo, cambios, tramo): pedir lo mismo no vuelve a dibujar.
Los MP4 viven en api_data/previews/<trabajo>/ y se borran a la hora y al borrar el trabajo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import shutil
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from vfxglow import telemetry
from vfxglow.api.jobs import JobStore

log = logging.getLogger("vfxglow.api")

TTL_S = 3600
# Lado largo máximo del MP4 de la vista previa (la imagen se dibuja entera; solo se reescala al escribir).
MAX_SIDE = 1280
HALF_S = 1.5
DAY_S = 24 * 3600


@dataclass
class Preview:
    id: str
    job_id: str
    uid: str
    edits: list[dict]
    window: tuple[int, int]
    fps: float
    status: str = "rendering"
    error: str | None = None
    started: bool = False
    finished: float = 0.0
    frames: int = 0
    path: Path | None = None
    created: float = field(default_factory=time.time)


def window_for(at: float, fps: float, frames: int) -> tuple[int, int]:
    """Los fotogramas [at-1,5 s, at+1,5 s] recortados al video."""
    a = max(int(round((at - HALF_S) * fps)), 0)
    b = min(int(round((at + HALF_S) * fps)) - 1, frames - 1)
    return a, max(b, a)


class PreviewStore:
    def __init__(self, jobs: JobStore) -> None:
        self.jobs = jobs
        self.root = jobs.root / "previews"
        shutil.rmtree(self.root, ignore_errors=True)  # lo que quedó de otra ejecución ya no está en memoria
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._items: dict[str, Preview] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._renders: dict[str, deque[float]] = {}
        threading.Thread(target=self._worker, daemon=True, name="vfxglow-previews").start()

    # ----- cuota -----

    def renders_today(self, uid: str, now: float | None = None) -> int:
        """Vistas previas dibujadas por `uid` en las últimas 24 h (las de caché no cuentan)."""
        now = now or time.time()
        with self._lock:
            times = self._renders.get(uid, deque())
            while times and now - times[0] >= DAY_S:
                times.popleft()
            return len(times)

    # ----- consulta -----

    def get(self, job_id: str, preview_id: str) -> Preview | None:
        self._sweep()
        with self._lock:
            item = self._items.get(preview_id)
            return item if item is not None and item.job_id == job_id else None

    def url_path(self, item: Preview) -> Path | None:
        return item.path if item.status == "ready" and item.path is not None and item.path.exists() else None

    # ----- pedido -----

    def submit(self, job_id: str, uid: str, edits: list[dict], window: tuple[int, int], fps: float, check_quota=None) -> tuple[Preview, bool]:
        """Encola la vista previa (o devuelve la ya hecha o en curso). `check_quota(hoy)` se llama
        solo si hay que dibujar. Devuelve (vista previa, desde_caché)."""
        self._sweep()
        key = hashlib.sha256(json.dumps([job_id, edits, list(window)], sort_keys=True).encode()).hexdigest()[:16]
        with self._lock:
            item = self._items.get(key)
            if item is not None and (item.status == "rendering" or self.url_path(item) is not None):
                return item, True
        if check_quota is not None:
            check_quota(self.renders_today(uid))
        with self._lock:
            # Un solo pendiente por usuario: los que aún no empezaron se descartan.
            for other in self._items.values():
                if other.uid == uid and other.status == "rendering" and not other.started and other.id != key:
                    other.status, other.error, other.finished = "failed", "Reemplazada por una vista previa más reciente.", time.time()
            item = Preview(id=key, job_id=job_id, uid=uid, edits=edits, window=window, fps=fps, path=self.root / job_id / f"{key}.mp4")
            self._items[key] = item
            self._renders.setdefault(uid, deque()).append(time.time())
        self._queue.put(key)
        return item, False

    # ----- trabajo -----

    def _worker(self) -> None:
        while True:
            key = self._queue.get()
            with self._lock:
                item = self._items.get(key)
                if item is None or item.status != "rendering" or item.started:
                    continue
                item.started = True
            self._render(item)

    def _render(self, item: Preview) -> None:
        began = time.time()
        frames = 0
        try:
            with telemetry.span("preview.render", job_id=item.job_id, window=list(item.window)):
                frames = self._draw(item)
            item.frames, item.status = frames, "ready"
        except ValueError as error:  # un cambio imposible que solo se vio al compilar (p. ej. un efecto nuevo)
            item.status, item.error = "failed", str(error)
        except Exception as error:  # el detalle va al registro; la persona ve un mensaje claro
            log.exception("Vista previa %s falló", item.id)
            item.status, item.error = "failed", "No pudimos generar la vista previa. Inténtalo de nuevo o aplica los cambios."
            telemetry.event("preview.failed", level=logging.ERROR, job_id=item.job_id, error={"kind": type(error).__name__, "message": telemetry.redact(str(error))[:500]})
        item.finished = time.time()
        if item.status == "ready":
            telemetry.event("preview.finished", job_id=item.job_id, duration_ms=round((item.finished - began) * 1000), frames=frames, cache_hit=False)

    def _draw(self, item: Preview) -> int:
        from vfxglow.analysis.schema import MotionEvent
        from vfxglow.director.edits import Edit, Moment, apply_edits, assign_tracks
        from vfxglow.director.schema import EffectScript
        from vfxglow.pipeline import Pipeline

        job = self.jobs.get(item.job_id)
        if job is None:
            raise ValueError("La versión ya no existe.")
        pipeline = Pipeline(self.jobs.config, Path(job.video_path), **self.jobs._pipeline_kwargs(job))
        script = EffectScript.model_validate_json(self.jobs.artifact(job.id, "script").read_text(encoding="utf-8"))
        moments = [Moment.model_validate(m) for m in json.loads(self.jobs.artifact(job.id, "moments").read_text(encoding="utf-8"))]
        events = [MotionEvent.model_validate(e) for e in json.loads(self.jobs.artifact(job.id, "events").read_text(encoding="utf-8"))]
        meta = pipeline._meta()
        fps, total = meta.fps or 30.0, meta.frame_count
        tracks = assign_tracks(moments, pipeline.element_of())
        new, _moments, _styles = apply_edits(
            script,
            moments,
            tracks,
            [Edit.model_validate(e) for e in item.edits],
            events,
            fps,
            total,
            compile_add=lambda option, action, frame, length, person: pipeline.compile_add(option, action, frame, length, person, script.seed),
        )
        assert item.path is not None
        item.path.parent.mkdir(parents=True, exist_ok=True)
        return pipeline.render_preview(new, item.path, item.window, events=events, max_side=MAX_SIDE)

    # ----- limpieza -----

    def _sweep(self) -> None:
        """Borra las vistas previas de más de una hora y las de trabajos que ya no existen."""
        now = time.time()
        with self._lock:
            gone = [k for k, p in self._items.items() if (p.finished and now - p.finished > TTL_S) or (p.status == "failed" and now - p.created > TTL_S)]
            for key in gone:
                path = self._items.pop(key).path
                if path is not None:
                    path.unlink(missing_ok=True)

    def forget_job(self, job_id: str) -> None:
        with self._lock:
            for key in [k for k, p in self._items.items() if p.job_id == job_id]:
                del self._items[key]
        shutil.rmtree(self.root / job_id, ignore_errors=True)
