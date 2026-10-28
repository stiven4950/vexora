"""Capas por pista para la vista en vivo del editor: un MP4 en mosaico por versión (composite/atlas.py).

Una tarea de la cola (api/tasks.py, tipo "layers", id `l_<versión>`) que hace un trabajador: en la
API con su propio hilo, o en `vexora-worker`. Dibuja la versión entera a baja resolución (~0,1 s
por fotograma). El resultado vive junto a los demás archivos de la versión
(`outputs/<id>.layers.mp4` y `.layers.json`), así que se borra con ella. "Lista" = ambos archivos
en disco o en el almacén de archivos (store/blobs.py); el JSON se escribe y publica al final, así
que sin él el MP4 a medias no cuenta. "Dibujándose" y "falló" salen del documento de la tarea:
cualquier instancia de la API lo ve.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from vfxglow import telemetry
from vfxglow.api import tasks
from vfxglow.api.jobs import Job, JobStore, TaskHandler

log = logging.getLogger("vfxglow.api")

# Segundos por fotograma que se espera que tarde el dibujo (medido) y fijo de arranque.
SECONDS_PER_FRAME = 0.1
STARTUP_S = 5
FAILED = "No pudimos preparar la vista en vivo. Inténtalo de nuevo."


def estimate_seconds(frames: int) -> int:
    return round(frames * SECONDS_PER_FRAME + STARTUP_S)


def track_keys(moments, tracks) -> tuple[dict[str, str], list[str]]:
    """(efecto → pista del editor, pistas de más a menos fotogramas cubiertos). Un efecto de
    varios momentos se queda con la primera pista que lo nombra."""
    by_moment = {m.id: m for m in moments}
    key_of: dict[str, str] = {}
    span: dict[str, int] = {}
    for track in tracks:
        span[track.key] = sum(by_moment[m].until - by_moment[m].frame + 1 for m in track.moments if m in by_moment)
        for moment_id in track.moments:
            moment = by_moment.get(moment_id)
            for effect_id in moment.effects if moment else []:
                key_of.setdefault(effect_id, track.key)
    return key_of, sorted(span, key=lambda k: -span[k])


class LayerStore:
    def __init__(self, jobs: JobStore) -> None:
        self.jobs = jobs
        self.docs = jobs.docs
        jobs.register(tasks.LAYERS, TaskHandler(self._run_task, error=FAILED))

    @staticmethod
    def task_id(job_id: str) -> str:
        return f"l_{job_id}"

    # ----- consulta -----

    def video_path(self, job_id: str) -> Path:
        return self.jobs.outputs / f"{job_id}.layers.mp4"

    def layout_path(self, job_id: str) -> Path:
        return self.jobs.outputs / f"{job_id}.layers.json"

    def ready(self, job_id: str) -> bool:
        return self.jobs.has(self.video_path(job_id)) and self.jobs.has(self.layout_path(job_id))

    def status(self, job_id: str) -> tuple[str, str | None]:
        """("none" | "rendering" | "ready" | "failed", error)."""
        doc = self.docs.get(tasks.TASKS, self.task_id(job_id))
        if tasks.pending(doc):
            return "rendering", None
        if self.ready(job_id):
            return "ready", None
        if doc is not None and doc.get("status") == "failed":
            return "failed", doc.get("error") or FAILED
        return "none", None

    def layout(self, job_id: str) -> dict | None:
        try:
            return json.loads(self.jobs.local(self.layout_path(job_id)).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # ----- pedido -----

    def submit(self, job: Job, check_quota=None, on_queued=None) -> str:
        """Encola la generación. Devuelve el estado. ValueError si la versión no se puede editar."""
        if not self.jobs.editable(job):
            raise ValueError("Esta versión no se puede editar.")
        if tasks.pending(self.docs.get(tasks.TASKS, self.task_id(job.id))):
            return "rendering"
        if self.ready(job.id):
            return "ready"
        if check_quota is not None:
            check_quota()
        created: dict = {}

        def put(current: dict | None) -> dict | None:
            created.clear()
            if tasks.pending(current):
                return None  # otra petición (quizá otra instancia) ya la encoló
            created["doc"] = tasks.new_task(self.task_id(job.id), tasks.LAYERS, job.owner, job.id)
            return created["doc"]

        self.docs.transact(tasks.TASKS, self.task_id(job.id), put)
        if "doc" not in created:
            return "rendering"
        if on_queued is not None:
            on_queued()
        self.jobs.enqueue_task(created["doc"])
        return "rendering"

    # ----- trabajo (en un trabajador) -----

    def _run_task(self, doc: dict, flag) -> dict:
        job_id = doc["ref"]
        began = time.time()
        frames = tracks = 0
        try:
            with telemetry.span("layers.render", job_id=job_id):
                telemetry.event("layers.started", job_id=job_id)
                frames, tracks = self._draw(job_id)
        except ValueError as error:
            self._discard(job_id)
            return {"status": "failed", "error": str(error)}
        except Exception as error:  # el detalle va al registro; la persona ve un mensaje claro
            log.exception("Capas de %s fallaron", job_id)
            self._discard(job_id)
            telemetry.event("layers.failed", level=logging.ERROR, job_id=job_id, error={"kind": type(error).__name__, "message": telemetry.redact(str(error))[:500]})
            return {"status": "failed", "error": FAILED}
        telemetry.event("layers.finished", job_id=job_id, duration_ms=round((time.time() - began) * 1000), frames=frames, tracks=tracks)
        return {"status": "done", "result": {"frames": frames, "tracks": tracks}}

    def _discard(self, job_id: str) -> None:
        for path in (self.video_path(job_id), self.layout_path(job_id)):
            path.unlink(missing_ok=True)
            path.with_name(path.name + ".tmp").unlink(missing_ok=True)
            key = self.jobs.key(path)
            if key and not self.jobs.blobs.local:
                self.jobs.blobs.delete(key)

    def _draw(self, job_id: str) -> tuple[int, int]:
        from vfxglow.analysis.schema import MotionEvent
        from vfxglow.director.edits import Moment, assign_tracks
        from vfxglow.director.schema import EffectScript

        job = self.jobs.get(job_id)
        if job is None:
            raise ValueError("La versión ya no existe.")
        pipeline = self.jobs.pipeline(self.jobs.local(job.video_path), restore=True, analysis_key=job.analysis_key, **self.jobs._pipeline_kwargs(job))
        script = EffectScript.model_validate_json(self.jobs.read_artifact(job.id, "script"))
        moments = [Moment.model_validate(m) for m in json.loads(self.jobs.read_artifact(job.id, "moments"))]
        events = [MotionEvent.model_validate(e) for e in json.loads(self.jobs.read_artifact(job.id, "events"))]
        tracks = assign_tracks(moments, pipeline.element_of())
        key_of, keys = track_keys(moments, tracks)
        mp4 = self.video_path(job.id)
        mp4.unlink(missing_ok=True)
        self.layout_path(job.id).unlink(missing_ok=True)
        layout = pipeline.render_layers(script, mp4, key_of, keys, events=events)
        # El JSON va al final y de forma atómica: con él, la capa está lista.
        tmp = self.layout_path(job.id).with_name(self.layout_path(job.id).name + ".tmp")
        tmp.write_text(layout.model_dump_json(), encoding="utf-8")
        tmp.replace(self.layout_path(job.id))
        self.jobs.publish(mp4)
        self.jobs.publish(self.layout_path(job.id))
        return layout.frames, len(layout.tracks)
