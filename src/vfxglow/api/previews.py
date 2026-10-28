"""Vista previa rápida del editor: ~3 s alrededor del cabezal con el motor real, sin crear versión.

Cada vista previa es una tarea de la cola (api/tasks.py, tipo "preview", la de más prioridad) que
dibuja un trabajador: en la API con su propio hilo (un render largo no la bloquea ni ella a él) o
en `vexora-worker`. Su estado es el documento de la tarea (cola → "rendering", hecha → "ready",
fallida → "failed"); el MP4, un archivo del almacén (`previews/<trabajo>/<id>.mp4`). Así cualquier
instancia de la API responde el sondeo.

- Una pendiente por usuario: si llega otra mientras la anterior sigue en cola (sin empezar), la
  anterior se descarta. Y una dibujándose por usuario aunque haya varios trabajadores.
- Caché por clave: el id es el hash de (trabajo, cambios, tramo, tamaño): pedir lo mismo no
  vuelve a dibujar.
- Cuota diaria por usuario (las de caché no cuentan): un documento por persona en `preview_quota`.
- Se borran a la hora y al borrar el trabajo.

El Estudio la reutiliza (mode="studio"): ~3 s con el estilo elegido sobre el video de una subida ya
analizada, antes de crear el trabajo. Misma cola, mismo "uno pendiente por usuario" y misma cuota
diaria; `job_id` guarda entonces el id de la subida.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from vfxglow import telemetry
from vfxglow.api import tasks
from vfxglow.api.jobs import JobStore, TaskHandler

log = logging.getLogger("vfxglow.api")

TTL_S = 3600
# Lado largo máximo de la vista previa: el motor ya dibuja a ese tamaño (las coordenadas son
# relativas al cuadro y se ve igual). Medido en 5 s dibujados de un video de 720x1280: 31 s a
# tamaño completo, 10 s a 640 y 7 s a 480.
MAX_SIDE = 640
HALF_S = 1.5
STUDIO_S = 3.0  # duración de la vista previa del Estudio
STUDIO_SIDE = 480  # la del Estudio se ve en una tarjeta pequeña
# Con la preferencia "rápida" (Configuración › Preferencias): menos píxeles, menos espera.
QUICK_MAX_SIDE = 480
QUICK_STUDIO_SIDE = 360
DAY_S = 24 * 3600
QUOTA = "preview_quota"
# Cada cuánto, como mucho, se barren las vistas previas viejas en cada proceso.
SWEEP_EVERY_S = 60.0
REPLACED = "Reemplazada por una vista previa más reciente."
FAILED = "No pudimos generar la vista previa. Inténtalo de nuevo o aplica los cambios."


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
    kind: str = "editor"  # "editor" | "studio"
    studio: dict | None = None  # studio: video_path, style y opciones del Pipeline
    max_side: int = MAX_SIDE
    finished: float = 0.0
    frames: int = 0
    path: Path | None = None
    created: float = field(default_factory=time.time)


_STATUS = {"queued": "rendering", "running": "rendering", "done": "ready", "failed": "failed"}


def sides_for(quality: str) -> tuple[int, int]:
    """(lado largo de la vista previa del editor, el de la del Estudio) según `preview_quality`."""
    return (QUICK_MAX_SIDE, QUICK_STUDIO_SIDE) if quality == "rapida" else (MAX_SIDE, STUDIO_SIDE)


def window_for(at: float, fps: float, frames: int) -> tuple[int, int]:
    """Los fotogramas [at-1,5 s, at+1,5 s] recortados al video."""
    a = max(int(round((at - HALF_S) * fps)), 0)
    b = min(int(round((at + HALF_S) * fps)) - 1, frames - 1)
    return a, max(b, a)


def busiest_window(brief, seconds: float = STUDIO_S) -> tuple[int, int]:
    """Los `seconds` s más activos: donde más pesa la línea de atención (los miembros y el objeto
    pesan más que la cabeza o el torso quietos); sin atención, donde más eventos hay; sin nada,
    el centro del video."""
    fps = brief.video.fps or 30.0
    frames = brief.video.frame_count
    length = max(int(round(seconds * fps)), 1)
    if frames <= length:
        return 0, max(frames - 1, 0)
    score = [0.0] * (frames + 1)  # diferencias: peso por fotograma

    def add(start: int, end: int, weight: float) -> None:
        a, b = max(start, 0), min(end, frames - 1)
        if b >= a:
            score[a] += weight
            score[b + 1] -= weight

    if brief.attention:
        for span in brief.attention:
            add(span.start_frame, span.end_frame, (0.2 if span.primary in ("head", "torso") else 1.0) + (0.5 if span.secondary else 0.0))
        tie = 0.01
    else:
        tie = 1.0
    for event in brief.events:
        add(event.start_frame, event.end_frame, tie)
    per_frame, running = [], 0.0
    for value in score[:frames]:
        running += value
        per_frame.append(running)
    total = sum(per_frame[:length])
    best, start = total, 0
    for i in range(1, frames - length + 1):
        total += per_frame[i + length - 1] - per_frame[i - 1]
        if total > best + 1e-9:
            best, start = total, i
    if best <= 1e-9:
        start = (frames - length) // 2
    return start, start + length - 1


class PreviewStore:
    """Las vistas previas: encolar, consultar y (en el trabajador) dibujar. Sin estado en memoria:
    todo sale del almacén, así que dos instancias de la API ven lo mismo."""

    def __init__(self, jobs: JobStore) -> None:
        self.jobs = jobs
        self.docs = jobs.docs
        self.root = jobs.root / "previews"
        self.root.mkdir(parents=True, exist_ok=True)
        self._swept = float("-inf")
        jobs.register(tasks.PREVIEW, TaskHandler(self._run_task, error=FAILED))
        jobs.sweepers["previews"] = lambda now: self._sweep(now, force=True)

    # ----- cuota -----

    def renders_today(self, uid: str, now: float | None = None) -> int:
        """Vistas previas dibujadas por `uid` en las últimas 24 h (las de caché no cuentan)."""
        now = now or time.time()
        doc = self.docs.get(QUOTA, uid) or {}
        return sum(now - float(t) < DAY_S for t in doc.get("times", []))

    def note_render(self, uid: str) -> None:
        """Cuenta un dibujo más en la cuota diaria de `uid` (las capas del editor valen como una vista previa)."""
        now = time.time()

        def add(current: dict | None) -> dict:
            times = [t for t in (current or {}).get("times", []) if now - float(t) < DAY_S]
            return {"id": uid, "times": [*times, now]}

        self.docs.transact(QUOTA, uid, add)

    # ----- consulta -----

    def _item(self, doc: dict | None) -> Preview | None:
        if doc is None or doc.get("kind") != tasks.PREVIEW:
            return None
        payload = doc.get("payload") or {}
        return Preview(
            id=doc["id"],
            job_id=doc["ref"],
            uid=doc.get("owner") or "",
            edits=payload.get("edits") or [],
            window=tuple(payload.get("window") or (0, 0)),
            fps=float(payload.get("fps") or 30.0),
            status=_STATUS.get(doc.get("status"), "failed"),
            error=doc.get("error"),
            started=doc.get("status") != "queued",
            kind=payload.get("mode", "editor"),
            studio=payload.get("studio"),
            max_side=int(payload.get("max_side") or MAX_SIDE),
            finished=float(doc.get("finished") or 0.0),
            frames=int((doc.get("result") or {}).get("frames") or 0),
            path=self.root / doc["ref"] / f"{doc['id']}.mp4",
            created=float(doc.get("created") or 0.0),
        )

    def _expired(self, item: Preview, now: float) -> bool:
        return bool(item.finished and now - item.finished > TTL_S) or (item.status == "failed" and now - item.created > TTL_S)

    def get(self, job_id: str, preview_id: str) -> Preview | None:
        self._sweep()
        item = self._item(self.docs.get(tasks.TASKS, preview_id))
        if item is None or item.job_id != job_id or self._expired(item, time.time()):
            return None
        return item

    def url_path(self, item: Preview) -> Path | None:
        """La ruta del MP4 si está lista (en este disco o en el almacén; la API la sirve con `_send`)."""
        return item.path if item.status == "ready" and item.path is not None and self.jobs.has(item.path) else None

    # ----- pedido -----

    def submit(self, job_id: str, uid: str, edits: list[dict], window: tuple[int, int], fps: float, check_quota=None, max_side: int = MAX_SIDE) -> tuple[Preview, bool]:
        """Encola la vista previa (o devuelve la ya hecha o en curso). `check_quota(hoy)` se llama
        solo si hay que dibujar. Devuelve (vista previa, desde_caché)."""
        key = hashlib.sha256(json.dumps([job_id, edits, list(window), max_side], sort_keys=True).encode()).hexdigest()[:16]
        payload = {"mode": "editor", "edits": edits, "window": list(window), "fps": fps, "max_side": max_side}
        return self._submit(key, job_id, uid, payload, check_quota)

    def submit_studio(self, upload_id: str, uid: str, studio: dict, window: tuple[int, int], fps: float, max_side: int, check_quota=None) -> tuple[Preview, bool]:
        """Como `submit`, para el Estudio: `studio` = video_path, run_dir, style y opciones. Lo
        mismo (subida, estilo, opciones y tramo) no se vuelve a dibujar. Devuelve (vista previa, desde_caché)."""
        key = hashlib.sha256(json.dumps(["studio", upload_id, studio, list(window), max_side], sort_keys=True).encode()).hexdigest()[:16]
        payload = {"mode": "studio", "studio": studio, "window": list(window), "fps": fps, "max_side": max_side}
        return self._submit(key, upload_id, uid, payload, check_quota)

    def _submit(self, key: str, ref: str, uid: str, payload: dict, check_quota) -> tuple[Preview, bool]:
        self._sweep()
        now = time.time()
        current = self._item(self.docs.get(tasks.TASKS, key))
        if current is not None and current.job_id == ref and not self._expired(current, now):
            if current.status == "rendering" or self.url_path(current) is not None:
                return current, True
        if check_quota is not None:
            check_quota(self.renders_today(uid))
        # Una sola pendiente por usuario: las que aún no empezaron se descartan.
        for other in self.docs.query(tasks.TASKS, where={"kind": tasks.PREVIEW, "owner": uid, "status": "queued"}):
            if other["id"] == key:
                continue
            self.docs.update(tasks.TASKS, other["id"], {"status": "failed", "error": REPLACED, "finished": now}, when={"status": "queued", "worker": None})
        doc = self.jobs.enqueue_task(tasks.new_task(key, tasks.PREVIEW, uid, ref, payload, now))
        self.note_render(uid)
        item = self._item(doc)
        assert item is not None
        return item, False

    # ----- trabajo (en un trabajador) -----

    def _run_task(self, doc: dict, flag) -> dict:
        item = self._item(doc)
        assert item is not None
        began = time.time()
        try:
            with telemetry.span("preview.render", job_id=item.job_id, window=list(item.window), kind=item.kind):
                frames = self._draw(item)
            assert item.path is not None
            self.jobs.publish(item.path)  # la API (quizá otra máquina) lo sirve desde el almacén
        except ValueError as error:  # un cambio imposible que solo se vio al compilar (p. ej. un efecto nuevo)
            return {"status": "failed", "error": str(error)}
        except Exception as error:  # el detalle va al registro; la persona ve un mensaje claro
            log.exception("Vista previa %s falló", item.id)
            telemetry.event("preview.failed", level=logging.ERROR, job_id=item.job_id, preview_kind=item.kind, error={"kind": type(error).__name__, "message": telemetry.redact(str(error))[:500]})
            return {"status": "failed", "error": FAILED}
        telemetry.event("preview.finished", job_id=item.job_id, duration_ms=round((time.time() - began) * 1000), frames=frames, cache_hit=False, kind=item.kind)
        return {"status": "done", "result": {"frames": frames}}

    def _draw_studio(self, item: Preview) -> int:
        from vfxglow.engine.engine import load_events

        assert item.studio is not None and item.path is not None
        studio = item.studio
        video = self.jobs.local(studio["video_path"])  # en otra máquina, se trae del almacén
        if not video.exists():
            raise ValueError("El video de la subida ya no está.")
        kwargs = {"catalog": studio["style"], "season": studio.get("season"), "take": 0}
        if studio.get("fire_style") or studio.get("bolt_style"):
            kwargs.update(fire_style=studio.get("fire_style"), bolt_style=studio.get("bolt_style"))
        if studio.get("wardrobe"):
            kwargs["wardrobe"] = studio["wardrobe"]
        if studio.get("prop"):
            kwargs["prop"] = studio["prop"]
        if studio.get("watermark"):
            kwargs["watermark"] = True
        # El análisis es el de la subida (config por defecto), aunque el catálogo pida más (`needs`).
        pipeline = self.jobs.pipeline(video, restore=True, analysis_key=studio.get("analysis_key"), **kwargs)
        # Sin escribir guion ni manifiesto en runs/: ese análisis lo comparte el trabajo real.
        # Baile y Espadas (`needs`): la gorra o las hojas se buscan solo en el tramo que se dibuja.
        extras = pipeline.window_extras(item.window)
        if extras is not None:
            brief, tracks, events = extras
            script = pipeline.direct_in_memory(brief)
        else:
            tracks = None
            script = pipeline.direct_in_memory()
            events = load_events(pipeline.run_dir / "analysis" / "events.jsonl")
        item.path.parent.mkdir(parents=True, exist_ok=True)
        return pipeline.render_preview(script, item.path, item.window, events=events, max_side=item.max_side, tracks=tracks)

    def _draw(self, item: Preview) -> int:
        if item.kind == "studio":
            return self._draw_studio(item)
        from vfxglow.analysis.schema import MotionEvent
        from vfxglow.director.edits import Edit, Moment, apply_edits, assign_tracks
        from vfxglow.director.schema import EffectScript

        job = self.jobs.get(item.job_id)
        if job is None:
            raise ValueError("La versión ya no existe.")
        pipeline = self.jobs.pipeline(self.jobs.local(job.video_path), restore=True, analysis_key=job.analysis_key, **self.jobs._pipeline_kwargs(job))
        script = EffectScript.model_validate_json(self.jobs.read_artifact(job.id, "script"))
        moments = [Moment.model_validate(m) for m in json.loads(self.jobs.read_artifact(job.id, "moments"))]
        events = [MotionEvent.model_validate(e) for e in json.loads(self.jobs.read_artifact(job.id, "events"))]
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
        return pipeline.render_preview(new, item.path, item.window, events=events, max_side=item.max_side)

    # ----- limpieza -----

    def _sweep(self, now: float | None = None, force: bool = False) -> None:
        """Borra las vistas previas de más de una hora (documento y MP4). Como mucho cada
        SWEEP_EVERY_S por proceso (los trabajadores también lo llaman)."""
        now = now or time.time()
        if not force and now - self._swept < SWEEP_EVERY_S:
            return
        self._swept = now
        for doc in self.docs.query(tasks.TASKS, where={"kind": tasks.PREVIEW}):
            item = self._item(doc)
            if item is None or tasks.pending(doc) or not self._expired(item, now):
                continue
            self.docs.delete(tasks.TASKS, item.id)
            if item.path is not None:
                item.path.unlink(missing_ok=True)
                key = self.jobs.key(item.path)
                if key and not self.jobs.blobs.local:
                    self.jobs.blobs.delete(key)

    def forget_job(self, job_id: str) -> None:
        """Las vistas previas de un trabajo o una subida que se borra."""
        self.jobs.forget_tasks(job_id)
