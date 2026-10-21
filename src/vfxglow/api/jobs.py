"""Cola de trabajos de edición para la API.

Un trabajo = un video + un estilo (catálogo o preset) + una semilla. Se procesan de uno en uno
en un hilo aparte (el análisis ya usa todos los núcleos). El progreso se deduce de los mensajes
de log del pipeline, que ya informan cada etapa; así el motor no necesita saber de la API.

Estado en api_data/jobs.json; videos subidos en api_data/uploads/<id>/.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger("vfxglow.api")

Status = Literal["queued", "running", "done", "failed"]
Stage = Literal["queued", "analyze", "direct", "render", "done"]

# Peso de cada etapa en la barra de progreso (el análisis domina el tiempo).
_ANALYZE, _DIRECT = 0.55, 0.05
LOG_LINES = 80


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
        self._path = root / "jobs.json"
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        if self._path.exists():
            for raw in json.loads(self._path.read_text(encoding="utf-8")):
                job = Job.model_validate(raw)
                if job.status in ("queued", "running"):
                    # El servidor se reinició a mitad: el trabajo no terminó.
                    job.status, job.error, job.message = "failed", "Interrumpido al reiniciar el servidor", "Interrumpido"
                self._jobs[job.id] = job
        self._queue: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._worker, daemon=True, name="vfxglow-jobs").start()

    # ----- consulta -----

    def list(self, owner: str | None = None) -> list[Job]:
        """Los trabajos de `owner` (todos si es None), del más nuevo al más viejo."""
        with self._lock:
            mine = [job for job in self._jobs.values() if owner is None or _owner(job) == owner]
            return sorted(mine, key=lambda job: job.created, reverse=True)

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

    def create(self, filename: str, data, style_kind: str, style: str, seed: int | None, season: str | None = None, owner: str | None = None, wardrobe: dict[str, str] | None = None, deep: bool = False, fire_style: str | None = None, bolt_style: str | None = None) -> Job:
        job_id = uuid.uuid4().hex[:10]
        folder = self.uploads / job_id
        folder.mkdir(parents=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "video.mp4"
        target = folder / safe
        with target.open("wb") as out:
            shutil.copyfileobj(data, out)
        return self._enqueue(Job(id=job_id, created=time.time(), filename=filename, video_path=str(target), style_kind=style_kind, style=style, seed=seed, season=season, owner=owner, wardrobe=wardrobe or {}, deep=deep, fire_style=fire_style, bolt_style=bolt_style))

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
            )
        )

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                return False
            shared = any(other.video_path == job.video_path for other in self._jobs.values())
            self._save()
        if not shared:
            shutil.rmtree(Path(job.video_path).parent, ignore_errors=True)
        return True

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
            job = self._jobs[job_id]
            for key, value in fields.items():
                setattr(job, key, value)
            self._save()

    def _enqueue(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._save()
        self._queue.put(job.id)
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
        self._update(job.id, status="running", stage="analyze", message="Preparando", started=time.time())
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
            output = pipeline.run()
            self._update(job.id, status="done", stage="done", progress=1.0, message="Listo", output=str(output), finished=time.time())
        except Exception as exc:  # el error se muestra en la interfaz; el servidor sigue
            log.exception("Trabajo %s falló", job.id)
            self._update(job.id, status="failed", message="Falló", error=f"{type(exc).__name__}: {exc}", finished=time.time())
        finally:
            root.removeHandler(handler)
