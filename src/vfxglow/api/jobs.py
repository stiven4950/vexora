"""Cola de trabajos de edición para la API.

Un trabajo = un video + un estilo (catálogo o preset) + una semilla. Se procesan de uno en uno
en un hilo aparte (el análisis ya usa todos los núcleos). El progreso se deduce de los mensajes
de log del pipeline, que ya informan cada etapa; así el motor no necesita saber de la API.

Estado en api_data/jobs.json; videos subidos en api_data/uploads/<id>/.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import shutil
import statistics
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from vfxglow import telemetry

log = logging.getLogger("vfxglow.api")

Status = Literal["queued", "running", "done", "failed"]
Stage = Literal["queued", "analyze", "direct", "render", "done"]

# Peso de cada etapa en la barra de progreso (el análisis domina el tiempo).
_ANALYZE, _DIRECT = 0.55, 0.05
LOG_LINES = 80
# Segundos de proceso por segundo de video medidos en api_data (mediana de 85 trabajos): un video
# nuevo (análisis + render) y una "otra versión" (análisis en caché). Hasta tener historial propio.
DEFAULT_RATIO = {"first": 20.0, "version": 11.0}
MIN_SAMPLES = 3


class Job(BaseModel):
    id: str
    created: float
    filename: str
    video_path: str
    style_kind: Literal["catalog", "preset"]
    style: str
    seed: int | None = None
    # Sin semilla: versión automática (0 = la mejor; cada "otra versión" pide la siguiente).
    take: int = 0
    # Temporada encima del estilo (configs/seasons.yaml), o ninguna.
    season: str | None = None
    # Estilos de fuego y de rayo que eligió el cliente (director/looks.py), o los del catálogo.
    fire_style: str | None = None
    bolt_style: str | None = None
    status: Status = "queued"
    stage: Stage = "queued"
    progress: float = 0.0
    message: str = "En cola"
    log: list[str] = Field(default_factory=list)
    run_dir: str | None = None
    output: str | None = None
    error: str | None = None
    started: float | None = None
    finished: float | None = None
    parent: str | None = None
    # uid de Firebase del dueño. Los trabajos de antes de las cuentas no tienen: son del usuario
    # local (VEXORA_AUTH=off) hasta que alguien los adopte (JobStore.adopt).
    owner: str | None = None
    # Vestuario por persona que eligió el usuario ({"*": "vestido", "person_1": "chaqueta"}).
    wardrobe: dict[str, str] = Field(default_factory=dict)
    # Análisis profundo (director/deep.py): opcional y de pago; por defecto, el económico.
    deep: bool = False
    # Traza que une la petición, el trabajo, sus etapas y sus llamadas a IA (telemetry.py).
    trace_id: str = Field(default_factory=telemetry.new_trace_id)
    # Si falló: el tipo de fallo (ERRORS); `error` lleva el mensaje para la persona.
    error_code: str | None = None
    # Resumen medido del trabajo: espera en cola, duración por etapa, tokens y costo de IA.
    metrics: dict = Field(default_factory=dict)
    # Duración del video subido: con ella y el historial se estima cuánto tardará (JobStore.estimate).
    video_seconds: float | None = None
    # Ficha del video subido (la muestran Mis proyectos y la pantalla de proceso).
    video_width: int | None = None
    video_height: int | None = None
    video_bytes: int | None = None
    # Lo que fue pasando ("Video recibido", "Inicio del procesamiento", cada etapa), para la
    # actividad reciente de la pantalla de proceso. Hora en segundos epoch.
    activity: list[dict] = Field(default_factory=list)
    # Editor de efectos (director/edits.py): una versión editada parte de `base` (otra versión) y
    # le aplica `edits`. Vacío en las versiones normales.
    edits: list[dict] = Field(default_factory=list)
    base: str | None = None
    # Nombre del proyecto que pone la persona; sin él, el del archivo. Es de todo el proyecto
    # (el video y sus versiones): JobStore.rename lo pone en todos.
    title: str | None = None


# Cómo se llama cada etapa en la actividad reciente.
STAGE_LABELS = {
    "analyze": "Análisis de movimiento",
    "direct": "Selección de estilo y coreografía",
    "deep": "Análisis profundo con IA",
    "compose": "Renderizado de efectos",
    "finalize": "Compresión y almacenamiento",
}
ACTIVITY_LINES = 12

# Fallos, en palabras de quien usa la web. El detalle técnico va solo al registro del servidor.
ERRORS = {
    "interrupted": "El servidor se reinició mientras procesaba tu video. Reintenta.",
    "ai_busy": "El servicio de IA del análisis profundo está saturado. Reintenta en unos minutos o usa el análisis económico.",
    "ai_failed": "El análisis profundo no dio un resultado utilizable. Reintenta o usa el análisis económico.",
    "analysis_failed": "No pudimos seguir el movimiento en este video. Prueba con un plano donde se vea el cuerpo entero.",
    "render_failed": "Algo falló al dibujar los efectos. Reintenta; si vuelve a pasar, prueba otro estilo.",
    "internal": "Algo falló al revelar tu video. Reintenta; si vuelve a pasar, escríbenos.",
}


def classify(error: BaseException, stage: str | None) -> str:
    """El tipo de fallo según la etapa donde ocurrió (telemetry.span la anota)."""
    if stage == "deep":
        busy = type(error).__name__ == "Saturated" or any(f"respondió {code}" in str(error) for code in (429, 503))
        return "ai_busy" if busy else "ai_failed"
    if stage == "analyze":
        return "analysis_failed"
    if stage in ("render", "refine", "compose"):
        return "render_failed"
    return "internal"


class JobBusy(Exception):
    """El trabajo está procesándose: borrarlo ahora rompería el revelado en curso."""


class NotRetryable(Exception):
    """Solo se reintenta un trabajo que falló."""


class UploadTooLarge(Exception):
    """El video subido pasa del máximo permitido."""


def _copy_limited(data, target: Path, max_bytes: int | None, chunk: int = 1024 * 1024) -> None:
    """Copia el flujo subido a `target`, cortando en cuanto pasa de `max_bytes`."""
    written = 0
    with target.open("wb") as out:
        while block := data.read(chunk):
            written += len(block)
            if max_bytes is not None and written > max_bytes:
                raise UploadTooLarge(target.name)
            out.write(block)


class _Progress(logging.Handler):
    """Traduce los mensajes del pipeline a etapa y porcentaje del trabajo en curso."""

    _COUNT = re.compile(r"(Analizados|Compuestos) (\d+)/(\d+)")

    def __init__(self, store: JobStore, job_id: str) -> None:
        super().__init__(logging.INFO)
        self.store, self.job_id = store, job_id

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("vfxglow"):
            return
        text = record.getMessage()
        update: dict = {}
        match = self._COUNT.search(text)
        if match:
            done, total = int(match.group(2)), max(int(match.group(3)), 1)
            if match.group(1) == "Analizados":
                update = {"stage": "analyze", "progress": _ANALYZE * done / total, "message": f"Analizando movimiento · {done}/{total}"}
            else:
                start = _ANALYZE + _DIRECT
                update = {"stage": "render", "progress": start + (1 - start) * done / total, "message": f"Renderizando efectos · {done}/{total}"}
        elif text.startswith("Analizando") or "Análisis en caché" in text:
            update = {"stage": "analyze", "message": "Analizando movimiento" if text.startswith("Analizando") else "Análisis en caché"}
            if "caché" in text:
                update["progress"] = _ANALYZE
        elif text.startswith("Escribiendo overlay"):
            update = {"message": "Preparando análisis"}
        elif text.startswith("Análisis profundo"):
            update = {"stage": "direct", "message": "Análisis profundo con IA (puede tardar unos minutos)"}
        elif text.startswith("Guion"):
            update = {"stage": "direct", "progress": _ANALYZE + _DIRECT, "message": "Coreografía lista"}
        elif text.startswith("Componiendo") or text.startswith("Renderizando"):
            update = {"stage": "render", "message": "Renderizando efectos"}
        self.store.append_log(self.job_id, text, update)


LOCAL_OWNER = "local"


def _owner(job: Job) -> str:
    return job.owner or LOCAL_OWNER


def owns(job: Job, uid: str) -> bool:
    return _owner(job) == uid


class JobStore:
    def __init__(self, root: Path, config: Path) -> None:
        self.root = root
        self.config = config
        self.uploads = root / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        # El MP4 de cada trabajo, aparte: en runs/ varias versiones (y usuarios) comparten carpeta.
        self.outputs = root / "outputs"
        self.outputs.mkdir(parents=True, exist_ok=True)
        self._path = root / "jobs.json"
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        if self._path.exists():
            for raw in json.loads(self._path.read_text(encoding="utf-8")):
                job = Job.model_validate(raw)
                if job.status in ("queued", "running"):
                    # El servidor se reinició a mitad: el trabajo no terminó.
                    job.status, job.error_code, job.message = "failed", "interrupted", "Interrumpido"
                    job.error = ERRORS["interrupted"]
                self._jobs[job.id] = job
        self._queue: queue.Queue[str] = queue.Queue()
        # Un evento por trabajo en curso: pedir parar es ponerlo (telemetry.checkpoint lo lee).
        self._cancel: dict[str, threading.Event] = {}
        threading.Thread(target=self._worker, daemon=True, name="vfxglow-jobs").start()

    # ----- consulta -----

    def list(self, owner: str | None = None) -> list[Job]:
        """Los trabajos de `owner` (todos si es None), del más nuevo al más viejo."""
        with self._lock:
            mine = [job for job in self._jobs.values() if owner is None or _owner(job) == owner]
            return sorted(mine, key=lambda job: job.created, reverse=True)

    def estimate(self, job: Job) -> float | None:
        """Segundos que tardará el trabajo: la mediana de lo que tardaron los terminados del mismo
        estilo y tipo (primer video o versión, con o sin análisis profundo) por segundo de video, o
        los valores medidos en api_data cuando aún no hay tres. Un rango, no una promesa."""
        if not job.video_seconds:
            return None
        with self._lock:
            ratios = [
                other.metrics["total_ms"] / 1000 / other.video_seconds
                for other in self._jobs.values()
                if other.status == "done"
                and other.video_seconds
                and other.metrics.get("total_ms")
                and (other.style, bool(other.parent), other.deep) == (job.style, bool(job.parent), job.deep)
            ]
        ratio = statistics.median(ratios) if len(ratios) >= MIN_SAMPLES else (DEFAULT_RATIO["version"] if job.parent else DEFAULT_RATIO["first"])
        return round(job.video_seconds * ratio)

    def queue_ahead(self, job: Job) -> int:
        """Cuántos trabajos van antes (hay un solo trabajador): el que se procesa y los que
        llegaron antes. Solo el número, nunca de quién."""
        with self._lock:
            return sum(
                other.id != job.id and (other.status == "running" or (other.status == "queued" and other.created < job.created))
                for other in self._jobs.values()
            )

    def rename(self, job_id: str, title: str) -> Job | None:
        """El nombre del proyecto: se pone en el video y en todas sus versiones. Vacío = el del archivo."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            root = job.parent or job.id
            for other in self._jobs.values():
                if (other.parent or other.id) == root:
                    other.title = title or None
            self._save()
            return job.model_copy(deep=True)

    def adopt(self, owner: str) -> int:
        """Los trabajos sin dueño (de antes de las cuentas) pasan a `owner`. Devuelve cuántos."""
        with self._lock:
            orphans = [job for job in self._jobs.values() if job.owner is None]
            for job in orphans:
                job.owner = owner
            if orphans:
                self._save()
            return len(orphans)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    # ----- altas -----

    def create(
        self,
        filename: str,
        data,
        style_kind: str,
        style: str,
        seed: int | None,
        season: str | None = None,
        owner: str | None = None,
        wardrobe: dict[str, str] | None = None,
        deep: bool = False,
        fire_style: str | None = None,
        bolt_style: str | None = None,
        max_bytes: int | None = None,
        check: Callable[[Path], object] | None = None,
    ) -> Job:
        """Guarda el video y encola el trabajo. `max_bytes` corta la copia aunque el cliente no
        haya dicho el tamaño (UploadTooLarge); `check` valida el archivo guardado antes de
        encolarlo. Si algo falla, no queda nada en disco."""
        job_id = uuid.uuid4().hex[:10]
        folder = self.uploads / job_id
        folder.mkdir(parents=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "video.mp4"
        target = folder / safe
        try:
            _copy_limited(data, target, max_bytes)
            info = check(target) if check is not None else None
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        job = Job(
            id=job_id,
            created=time.time(),
            filename=filename,
            video_path=str(target),
            style_kind=style_kind,
            style=style,
            seed=seed,
            season=season,
            owner=owner,
            wardrobe=wardrobe or {},
            deep=deep,
            fire_style=fire_style,
            bolt_style=bolt_style,
            video_seconds=getattr(info, "duration_s", None),
            video_width=getattr(info, "width", None),
            video_height=getattr(info, "height", None),
            video_bytes=target.stat().st_size,
        )
        job.activity = [{"at": job.created, "text": "Video recibido", "detail": f"{filename} ({target.stat().st_size / 1e6:.1f} MB)"}]
        telemetry.event(
            "upload.received",
            job_id=job.id,
            trace_id=job.trace_id,
            usr={"id": telemetry.user_ref(owner)},
            bytes=target.stat().st_size,
            extension=target.suffix.lower(),
            video=info.model_dump() if isinstance(info, BaseModel) else None,
        )
        return self._enqueue(job)

    def retry(self, job_id: str) -> Job:
        """Vuelve a encolar un trabajo que falló, con lo mismo que pidió (y su misma traza)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "failed":
                raise NotRetryable(job_id)
            job.status, job.stage, job.progress, job.message = "queued", "queued", 0.0, "En cola"
            job.error = job.error_code = None
            job.log, job.started, job.finished, job.metrics = [], None, None, {}
            self._save()
            snapshot = job.model_copy(deep=True)
        self._queue.put(job_id)
        telemetry.event("job.retried", job_id=job_id, trace_id=snapshot.trace_id)
        return snapshot

    def variation(self, parent: Job, style_kind: str, style: str, seed: int | None, season: str | None = None, wardrobe: dict[str, str] | None = None, deep: bool | None = None, fire_style: str | None = None, bolt_style: str | None = None) -> Job:
        """Mismo video, otro estilo u otra versión: el análisis queda en caché y es rápido.

        Sin semilla, "otra versión" del mismo estilo es la siguiente del ranking (la mejor que no
        se haya hecho todavía para ese video); con otro estilo, se empieza por la mejor."""
        root = parent.parent or parent.id
        wear = parent.wardrobe if wardrobe is None else wardrobe
        deep = parent.deep if deep is None else deep
        fire_style = parent.fire_style if fire_style is None else (fire_style or None)
        bolt_style = parent.bolt_style if bolt_style is None else (bolt_style or None)
        take = 0
        if seed is None:
            with self._lock:
                done = [j.take for j in self._jobs.values() if (j.parent or j.id) == root and j.style == style and j.style_kind == style_kind and j.seed is None and j.season == season and j.wardrobe == wear and j.fire_style == fire_style and j.bolt_style == bolt_style]
            take = max(done) + 1 if done else 0
        return self._enqueue(
            Job(
                id=uuid.uuid4().hex[:10],
                created=time.time(),
                filename=parent.filename,
                video_path=parent.video_path,
                style_kind=style_kind,
                style=style,
                seed=seed,
                take=take,
                season=season,
                wardrobe=wear,
                deep=deep,
                fire_style=fire_style,
                bolt_style=bolt_style,
                parent=root,
                owner=parent.owner,
                video_seconds=parent.video_seconds,
                video_width=parent.video_width,
                video_height=parent.video_height,
                video_bytes=parent.video_bytes,
                title=parent.title,
            )
        )

    def delete(self, job_id: str) -> bool:
        """Borra el trabajo y todo lo suyo: su MP4, sus miniaturas y, si ningún otro trabajo los
        usa, el video subido y la carpeta del análisis en runs/ (pistas, overlay, guiones, lectura
        de la IA). JobBusy si se está procesando."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status == "running":
                raise JobBusy(job_id)
        return self._remove(job_id)

    def cancel(self, job_id: str) -> str:
        """Cancelar: en cola, se borra ya; en curso, se pide parar y el proceso se corta en su
        próximo punto de control (cada pocos fotogramas) y se borra solo. Devuelve "removed",
        "stopping" o "none" si ya no hay nada que cancelar."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return "none"
            if job.status == "running":
                self._cancel.setdefault(job_id, threading.Event()).set()
                return "stopping"
            if job.status != "queued":
                return "none"
        self._remove(job_id)
        return "removed"

    def _remove(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                return False
            video_shared = any(other.video_path == job.video_path for other in self._jobs.values())
            run_shared = any(other.run_dir == job.run_dir for other in self._jobs.values())
            self._save()
        (self.outputs / f"{job_id}.mp4").unlink(missing_ok=True)
        for leftover in self.outputs.glob(f"{job_id}.*"):
            leftover.unlink(missing_ok=True)  # guion, momentos, gestos y tira de fotogramas del editor
        folder = Path(job.video_path).parent
        if video_shared:
            for cache in folder.glob(f"thumb-{job_id}-*.jpg"):
                cache.unlink(missing_ok=True)
        else:
            shutil.rmtree(folder, ignore_errors=True)
        if job.run_dir and not run_shared and self._removable(Path(job.run_dir)):
            shutil.rmtree(job.run_dir, ignore_errors=True)
        telemetry.event("job.deleted", job_id=job_id, trace_id=job.trace_id, run_deleted=bool(job.run_dir and not run_shared))
        return True

    def _removable(self, run_dir: Path) -> bool:
        """Solo se borra una carpeta de análisis dentro de runs/ o de api_data/, nunca otra ruta."""
        from vfxglow.config import load_config

        runs = Path(load_config(self.config).paths.runs_dir)
        runs = runs if runs.is_absolute() else Path.cwd() / runs
        target = run_dir.resolve()
        return any(target != root.resolve() and target.is_relative_to(root.resolve()) for root in (runs, self.root))

    # ----- actualización -----

    def append_log(self, job_id: str, line: str, update: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.log = (job.log + [line])[-LOG_LINES:]
            for key, value in update.items():
                setattr(job, key, value)
            if "progress" in update:
                job.progress = max(min(job.progress, 1.0), 0.0)

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:  # se canceló y se borró mientras tanto
                return
            for key, value in fields.items():
                setattr(job, key, value)
            self._save()

    def _enqueue(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            depth = sum(other.status == "queued" for other in self._jobs.values())
            self._save()
        self._queue.put(job.id)
        telemetry.event(
            "job.queued",
            job_id=job.id,
            parent_job_id=job.parent,
            trace_id=job.trace_id,
            usr={"id": telemetry.user_ref(job.owner)},
            style=job.style,
            style_kind=job.style_kind,
            take=job.take,
            seed=job.seed,
            season=job.season,
            fire_style=job.fire_style,
            bolt_style=job.bolt_style,
            wardrobe=job.wardrobe or None,
            deep=job.deep,
            queue_depth=depth,
        )
        return job

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps([job.model_dump() for job in self._jobs.values()], ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

    # ----- trabajo -----

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            job = self.get(job_id)
            if job is None:
                continue
            self._run(job)

    def _run(self, job: Job) -> None:
        from vfxglow.pipeline import Pipeline

        handler = _Progress(self, job.id)
        root = logging.getLogger()
        root.addHandler(handler)
        started = time.time()
        self._update(job.id, status="running", stage="analyze", message="Preparando", started=started)
        cancel = self._cancel.setdefault(job.id, threading.Event())
        context = telemetry.job_context(job.id, job.trace_id, on_change=self._stage_changed(job.id), cancel=cancel, usr={"id": telemetry.user_ref(job.owner)}, style=job.style)
        with context as summary:
            summary["queue_wait_ms"] = round((started - job.created) * 1000)
            self._note(job.id, "Inicio del procesamiento", "Se ha iniciado el análisis del video.")
            self._update(job.id, metrics=dict(summary))
            telemetry.event("job.started", queue_wait_ms=summary["queue_wait_ms"], deep=job.deep, take=job.take)
            try:
                kwargs = {"catalog": job.style, "seed": job.seed, "take": job.take} if job.style_kind == "catalog" else {"preset": job.style}
                kwargs["season"] = job.season
                if job.style_kind == "catalog" and (job.fire_style or job.bolt_style):
                    kwargs["fire_style"] = job.fire_style
                    kwargs["bolt_style"] = job.bolt_style
                if job.style_kind == "catalog" and job.wardrobe:
                    kwargs["wardrobe"] = job.wardrobe
                if job.style_kind == "catalog" and job.deep:
                    kwargs["deep"] = True
                pipeline = Pipeline(self.config, Path(job.video_path), **kwargs)
                self._update(job.id, run_dir=str(pipeline.run_dir))
                if job.edits:
                    output = self._edit(job, pipeline)
                else:
                    output = self._keep(job.id, pipeline.run())
                    self._save_artifacts(job.id, pipeline)
                finished = time.time()
                summary["total_ms"] = round((finished - started) * 1000)
                self._update(job.id, status="done", stage="done", progress=1.0, message="Listo", output=str(output), finished=finished, metrics=summary)
                telemetry.event("job.finished", outcome="ok", duration_ms=summary["total_ms"], output_bytes=output.stat().st_size, metrics=summary)
            except telemetry.Cancelled:
                # La persona canceló: no queda nada que mostrar, así que se borra todo.
                telemetry.event("job.cancelled", duration_ms=round((time.time() - started) * 1000))
                self._remove(job.id)
            except Exception as exc:  # el mensaje claro va a la interfaz; el detalle, al registro
                code = classify(exc, summary.get("failed_stage"))
                log.exception("Trabajo %s falló (%s)", job.id, code)
                finished = time.time()
                summary["total_ms"] = round((finished - started) * 1000)
                self._update(job.id, status="failed", message="Falló", error=ERRORS[code], error_code=code, finished=finished, metrics=summary)
                telemetry.event(
                    "job.failed",
                    level=logging.ERROR,
                    outcome="error",
                    duration_ms=summary["total_ms"],
                    error={"code": code, "kind": type(exc).__name__, "message": telemetry.redact(str(exc))[:500]},
                    metrics=summary,
                )
            finally:
                root.removeHandler(handler)
                self._cancel.pop(job.id, None)

    def _note(self, job_id: str, text: str, detail: str = "") -> None:
        """Una línea de la actividad reciente (las últimas ACTIVITY_LINES)."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.activity = [*job.activity, {"at": time.time(), "text": text, "detail": detail}][-ACTIVITY_LINES:]

    def _stage_changed(self, job_id: str) -> Callable[[str, str, dict], None]:
        """Lo que se hace cuando una etapa empieza o termina: la actividad y las métricas en vivo."""

        def changed(kind: str, stage: str, summary: dict) -> None:
            label = STAGE_LABELS.get(stage, stage)
            self._note(job_id, f"{label} ({'en proceso' if kind == 'started' else 'completado'})")
            self._update(job_id, metrics=dict(summary))

        return changed

    # ----- editor de efectos -----

    def artifact(self, job_id: str, kind: str) -> Path:
        """Lo que se guarda de cada versión para editarla: su guion (`script`), sus momentos
        (`moments`) y los gestos con que se dibujó (`events`)."""
        return self.outputs / f"{job_id}.{kind}.json"

    def editable(self, job: Job) -> bool:
        return job.status == "done" and job.style_kind == "catalog" and all(self.artifact(job.id, k).exists() for k in ("script", "moments", "events"))

    def _save_artifacts(self, job_id: str, pipeline) -> None:
        """Guarda el guion, los momentos y los gestos de una versión recién hecha (solo coreografías)."""
        from vfxglow.director.choreography import Choreography
        from vfxglow.director.edits import moments_from
        from vfxglow.director.schema import EffectScript

        scripts = Path(pipeline.run_dir) / "scripts"
        if not (scripts / "choreography.json").exists() or not (scripts / "effect_script.json").exists():
            return
        script = EffectScript.model_validate_json((scripts / "effect_script.json").read_text(encoding="utf-8"))
        choreography = Choreography.model_validate_json((scripts / "choreography.json").read_text(encoding="utf-8"))
        moments = moments_from(script, choreography.decisions)
        events = Path(pipeline.run_dir) / "analysis" / "events.jsonl"
        self.artifact(job_id, "script").write_text(script.model_dump_json(), encoding="utf-8")
        self.artifact(job_id, "moments").write_text(json.dumps([m.model_dump() for m in moments], ensure_ascii=False), encoding="utf-8")
        lines = events.read_text(encoding="utf-8").splitlines() if events.exists() else []
        self.artifact(job_id, "events").write_text(json.dumps([json.loads(line) for line in lines if line.strip()]), encoding="utf-8")

    def edit(self, base: Job, edits: list[dict]) -> Job:
        """Una versión nueva que parte de `base` con los cambios del editor."""
        return self._enqueue(
            base.model_copy(
                update={
                    "id": uuid.uuid4().hex[:10],
                    "created": time.time(),
                    "parent": base.parent or base.id,
                    "base": base.id,
                    "edits": edits,
                    "status": "queued",
                    "stage": "queued",
                    "progress": 0.0,
                    "message": "En cola",
                    "log": [],
                    "error": None,
                    "error_code": None,
                    "started": None,
                    "finished": None,
                    "output": None,
                    "metrics": {},
                    "trace_id": telemetry.new_trace_id(),
                    "activity": [{"at": time.time(), "text": "Cambios del editor recibidos", "detail": f"{len(edits)} cambio(s) sobre la versión anterior"}],
                },
                deep=True,
            )
        )

    def _edit(self, job: Job, pipeline) -> Path:
        """Aplica los cambios al guion de la versión base y dibuja solo el tramo que cambia; el
        resto se copia del video de la base (director/edits.py)."""
        from vfxglow.analysis.schema import MotionEvent
        from vfxglow.director.edits import Edit, Moment, apply_edits, assign_tracks, changed_window
        from vfxglow.director.schema import EffectScript

        base = job.base or ""
        with telemetry.span("direct", provider="editor"):
            script = EffectScript.model_validate_json(self.artifact(base, "script").read_text(encoding="utf-8"))
            moments = [Moment.model_validate(m) for m in json.loads(self.artifact(base, "moments").read_text(encoding="utf-8"))]
            events = [MotionEvent.model_validate(e) for e in json.loads(self.artifact(base, "events").read_text(encoding="utf-8"))]
            meta = pipeline._meta()
            fps, frames = meta.fps or 30.0, meta.frame_count
            tracks = assign_tracks(moments, pipeline.element_of())
            new, new_moments, _styles = apply_edits(
                script,
                moments,
                tracks,
                [Edit.model_validate(e) for e in job.edits],
                events,
                fps,
                frames,
                compile_add=lambda option, action, frame, length, person: pipeline.compile_add(option, action, frame, length, person, script.seed),
                main_track=pipeline.edit_catalog().element or None,
            )
            window = changed_window(script, new, events, frames, fps)
            self.artifact(job.id, "script").write_text(new.model_dump_json(), encoding="utf-8")
            self.artifact(job.id, "moments").write_text(json.dumps([m.model_dump() for m in new_moments], ensure_ascii=False), encoding="utf-8")
            shutil.copy2(self.artifact(base, "events"), self.artifact(job.id, "events"))
        dest = self.outputs / f"{job.id}.mp4"
        base_video = self.outputs / f"{base}.mp4"
        if window is None and base_video.exists():
            # Nada que cambie en pantalla: la versión nueva es la misma imagen.
            return self._keep(job.id, base_video)
        partial = window is not None and window != (0, frames - 1) and base_video.exists()
        with telemetry.span("compose", streamed=True, partial=partial, window=list(window) if window else None):
            pipeline.render_script(new, dest, base_output=base_video if partial else None, window=window if partial else None, events=events)
        summary_window = {"window_frames": (window[1] - window[0] + 1) if window else 0, "total_frames": frames, "partial": partial}
        self._note(job.id, "Tramo redibujado" if partial else "Video redibujado completo", f"{summary_window['window_frames']} de {frames} fotogramas")
        return dest

    def _keep(self, job_id: str, output: Path) -> Path:
        """El MP4 del trabajo en api_data/outputs/<id>.mp4. Enlace duro si se puede (el pipeline
        escribe el siguiente video en un archivo nuevo y lo renombra, así que el enlace conserva
        este); si no, copia."""
        target = self.outputs / f"{job_id}.mp4"
        target.unlink(missing_ok=True)
        try:
            os.link(output, target)
        except OSError:
            shutil.copy2(output, target)
        return target
