"""Subidas: el video se analiza en cuanto la persona lo elige, mientras escoge estilo.

Una subida guarda el video en api_data/uploads/u_<id>/ y lo analiza en un hilo propio (aparte del
trabajador de trabajos). Al terminar queda `ready` con una recomendación de estilo
(director/recommend.py). Al crear el trabajo con `upload_id`, el análisis ya está en la caché de
Pipeline.analyze (mismo hash de video y misma config de análisis) o en curso: el candado por
carpeta de análisis hace esperar al trabajo.

Reutilizan este análisis todos los catálogos salvo los que cambian la config de análisis con sus
`needs` (baile: props; espadas_*: blades): esos analizan de nuevo.

Estado en el almacén de documentos (store/: api_data/uploads.json por defecto, o Firestore). Las
subidas sin usar caducan a las 24 h.
"""

from __future__ import annotations

import logging
import queue
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from vfxglow import telemetry
from vfxglow.api.jobs import COLLECTION as JOBS
from vfxglow.api.jobs import ERRORS, JobStore, _copy_limited, classify, safe_name
from vfxglow.analysis.quality import QualityWarning
from vfxglow.director.recommend import Recommendation, recommend
from vfxglow.store.docs import DELETE

log = logging.getLogger("vfxglow.api")

UploadStatus = Literal["analyzing", "ready", "failed", "used"]
TTL_S = 24 * 3600
MAX_ANALYZING = 3
COLLECTION = "uploads"


class UploadNotFound(Exception):
    """La subida no existe, venció o es de otra persona."""


class UploadUsed(Exception):
    """La subida ya se usó en un trabajo."""


class TooManyAnalyzing(Exception):
    """La persona ya tiene el máximo de videos analizándose."""


class Upload(BaseModel):
    id: str
    owner: str
    created: float
    filename: str
    video_path: str
    status: UploadStatus = "analyzing"
    error: str | None = None
    error_code: str | None = None
    video_seconds: float | None = None
    video_width: int | None = None
    video_height: int | None = None
    video_bytes: int | None = None
    run_dir: str | None = None
    recommendation: list[Recommendation] = Field(default_factory=list)
    warnings: list[QualityWarning] = Field(default_factory=list)


class UploadStore:
    """Las subidas. El estado vive en el almacén de documentos (colección "uploads"); el análisis,
    en un hilo de este proceso (la API). Ver docs/despliegue_cloud_run.md: por eso, en la nube, la
    API corre en una sola instancia por ahora."""

    def __init__(self, jobs: JobStore, available: Callable[[], list[str]]) -> None:
        self.jobs = jobs
        self.available = available  # nombres de los catálogos que lista /api/styles
        self.root = jobs.root / "uploads"
        self.root.mkdir(parents=True, exist_ok=True)
        self.docs = jobs.docs
        for doc in self.docs.query(COLLECTION, where={"status": "analyzing"}):
            # El servidor se reinició a mitad del análisis: no terminó.
            self.docs.update(COLLECTION, doc["id"], {"status": "failed", "error_code": "interrupted", "error": ERRORS["interrupted"]}, when={"status": "analyzing"})
        self._queue: queue.Queue[str] = queue.Queue()
        self._current: str | None = None  # la subida que el hilo está analizando
        self.expire()
        threading.Thread(target=self._worker, daemon=True, name="vfxglow-uploads").start()

    # ----- consulta -----

    def get(self, upload_id: str, owner: str) -> Upload:
        item = self.peek(upload_id)
        if item is None or item.owner != owner:
            raise UploadNotFound(upload_id)
        return item

    def peek(self, upload_id: str) -> Upload | None:
        """La subida sin comprobar dueño (los archivos con llave firmada lo comprueban aparte)."""
        doc = self.docs.get(COLLECTION, upload_id)
        return Upload.model_validate(doc) if doc is not None else None

    def _all(self, **where) -> list[Upload]:
        return [Upload.model_validate(doc) for doc in self.docs.query(COLLECTION, where=where or None)]

    # ----- altas y bajas -----

    def create(self, filename: str, data, owner: str, max_bytes: int | None, check: Callable[[Path], object]) -> Upload:
        """Guarda el video, lo valida y lo pone en la cola de análisis. Si algo falla no queda nada en disco."""
        self.expire()
        if len(self._all(owner=owner, status="analyzing")) >= MAX_ANALYZING:
            raise TooManyAnalyzing(owner)
        upload_id = "u_" + uuid.uuid4().hex[:10]
        folder = self.root / upload_id
        folder.mkdir(parents=True)
        target = folder / safe_name(filename)
        try:
            _copy_limited(data, target, max_bytes)
            info = check(target)
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        item = Upload(
            id=upload_id,
            owner=owner,
            created=time.time(),
            filename=filename,
            video_path=str(target),
            video_seconds=getattr(info, "duration_s", None),
            video_width=getattr(info, "width", None),
            video_height=getattr(info, "height", None),
            video_bytes=target.stat().st_size,
        )
        self.docs.set(COLLECTION, item.id, item.model_dump())
        telemetry.event("upload.received", upload_id=item.id, usr={"id": telemetry.user_ref(owner)}, bytes=item.video_bytes, extension=target.suffix.lower())
        self._queue.put(item.id)
        return item

    def delete(self, upload_id: str, owner: str) -> None:
        """Borra el archivo (y el análisis si nadie más lo usa). Si se está analizando, el hilo lo ignora al terminar."""
        found: dict = {}

        def drop(current: dict | None):
            found.clear()
            if current is None or current.get("owner") != owner:
                return None
            found["item"] = current
            return DELETE

        self.docs.transact(COLLECTION, upload_id, drop)
        if "item" not in found:
            raise UploadNotFound(upload_id)
        item = Upload.model_validate(found["item"])
        if item.status != "used":
            self._discard(item)

    def claim(self, upload_id: str, owner: str) -> tuple[Upload, str]:
        """Reserva la subida para un trabajo: queda `used` (no caduca ni se reutiliza). Devuelve
        la subida y su estado anterior, por si hay que devolverla (`release`). Es una transacción:
        dos trabajos no se llevan la misma subida."""
        found: dict = {}

        def take(current: dict | None):
            found.clear()
            if current is None or current.get("owner") != owner:
                return None
            found["previous"] = current["status"]
            if current["status"] == "used":
                return None
            return {**current, "status": "used"}

        taken = self.docs.transact(COLLECTION, upload_id, take)
        if "previous" not in found:
            raise UploadNotFound(upload_id)
        if taken is None:
            raise UploadUsed(upload_id)
        return Upload.model_validate(taken), found["previous"]

    def release(self, upload_id: str, previous: str) -> None:
        """El trabajo no se pudo crear: la subida vuelve a estar disponible."""
        self.docs.update(COLLECTION, upload_id, {"status": previous}, when={"status": "used"})

    def finish_used(self, item: Upload) -> None:
        """El trabajo ya tiene su archivo: la carpeta de la subida sobra, salvo que aún se esté
        analizando (el hilo la borra al terminar)."""
        if self._busy(item.id):
            return
        shutil.rmtree(Path(item.video_path).parent, ignore_errors=True)

    # ----- caducidad -----

    def expire(self, now: float | None = None) -> int:
        """Borra las subidas sin usar de más de 24 h y los registros de las usadas. Devuelve cuántas."""
        now = now or time.time()
        old = [item for item in self._all() if now - item.created > TTL_S]
        for item in old:
            self.docs.delete(COLLECTION, item.id)
        for item in old:
            if item.status != "used":
                self._discard(item)
        return len(old)

    def _discard(self, item: Upload) -> None:
        shutil.rmtree(Path(item.video_path).parent, ignore_errors=True)
        self._drop_run(item.run_dir)

    def _drop_run(self, run_dir: str | None) -> None:
        """La carpeta del análisis solo se borra si ningún trabajo ni otra subida la usa."""
        if not run_dir:
            return
        shared = bool(self.docs.query(COLLECTION, where={"run_dir": run_dir}, limit=1))
        used_by_job = bool(self.docs.query(JOBS, where={"run_dir": run_dir}, limit=1))
        if not shared and not used_by_job and self.jobs._removable(Path(run_dir)):
            shutil.rmtree(run_dir, ignore_errors=True)

    def _busy(self, upload_id: str) -> bool:
        return self._current == upload_id

    # ----- análisis -----

    def _worker(self) -> None:
        while True:
            upload_id = self._queue.get()
            self._current = upload_id
            try:
                self._analyze(upload_id)
            except Exception:  # un fallo de una subida no debe matar el hilo
                log.exception("Subida %s: fallo inesperado", upload_id)
            finally:
                self._current = None

    def _analyze(self, upload_id: str) -> None:
        from vfxglow.analysis.quality import quality_warnings
        from vfxglow.analysis.schema import MotionBrief
        from vfxglow.engine.engine import load_tracks
        from vfxglow.io.store import read_model
        from vfxglow.pipeline import Pipeline

        item = self.peek(upload_id)
        if item is None or item.status != "analyzing":  # se borró o se usó antes de empezar
            return
        started = time.perf_counter()
        run_dir: str | None = None
        cache_hit = False
        try:
            with telemetry.span("upload.analyze", upload_id=upload_id):
                attributes = telemetry.current_span()
                # Sin catálogo: la config de análisis es la de por defecto, la que reutilizan los trabajos.
                pipeline = Pipeline(self.jobs.config, Path(item.video_path))
                run_dir = str(pipeline.run_dir)
                self._set(upload_id, run_dir=run_dir)
                pipeline.analyze()
                brief_path = Path(pipeline.run_dir) / "analysis" / "motion_brief.json"
                pipeline._ensure_derived(brief_path)
                cache_hit = bool(attributes.get("cache_hit"))
                brief = read_model(brief_path, MotionBrief)
                recommendations = recommend(brief, self.available())
                tracks_path = brief_path.with_name("tracks.jsonl")
                try:  # los avisos son un extra: si fallan o faltan las pistas, la subida sigue lista
                    warnings = quality_warnings(brief, load_tracks(tracks_path)) if tracks_path.exists() else []
                except Exception:
                    log.exception("Subida %s: no se pudieron calcular los avisos", upload_id)
                    warnings = []
            outcome: dict = {"status": "ready", "recommendation": recommendations, "warnings": warnings}
        except Exception as exc:
            code = classify(exc, "analyze")
            log.exception("Subida %s falló (%s)", upload_id, code)
            outcome = {"status": "failed", "error": ERRORS[code], "error_code": code}
            telemetry.event("upload.failed", level=logging.ERROR, upload_id=upload_id, usr={"id": telemetry.user_ref(item.owner)}, error={"code": code, "kind": type(exc).__name__, "message": telemetry.redact(str(exc))[:500]})
        duration = round((time.perf_counter() - started) * 1000)
        stored = {
            **outcome,
            "recommendation": [r.model_dump() for r in outcome.get("recommendation", [])],
            "warnings": [w.model_dump() for w in outcome.get("warnings", [])],
        }
        seen: dict = {}

        def finish(current: dict | None) -> dict | None:
            seen["status"] = current.get("status") if current is not None else None
            # `used` conserva su estado: el trabajo ya se llevó el video.
            if current is None or current.get("status") != "analyzing":
                return None
            return {**current, **stored}

        self.docs.transact(COLLECTION, upload_id, finish)
        gone = seen["status"] is None
        used = seen["status"] == "used"
        if outcome["status"] == "ready":
            first = outcome["recommendation"][0].style if outcome["recommendation"] else None
            telemetry.event("upload.analyzed", upload_id=upload_id, usr={"id": telemetry.user_ref(item.owner)}, duration_ms=duration, cache_hit=cache_hit, style=first, warnings=[w.code for w in outcome["warnings"]])
        if gone:
            self._discard(item.model_copy(update={"run_dir": run_dir}))
        elif used:
            shutil.rmtree(Path(item.video_path).parent, ignore_errors=True)

    def _set(self, upload_id: str, **fields) -> None:
        self.docs.update(COLLECTION, upload_id, fields)
