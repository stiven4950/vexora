"""Subidas: el video se analiza en cuanto la persona lo elige, mientras escoge estilo.

Una subida guarda el video en api_data/uploads/u_<id>/ y lo analiza en un hilo propio (aparte del
trabajador de trabajos). Al terminar queda `ready` con una recomendación de estilo
(director/recommend.py). Al crear el trabajo con `upload_id`, el análisis ya está en la caché de
Pipeline.analyze (mismo hash de video y misma config de análisis) o en curso: el candado por
carpeta de análisis hace esperar al trabajo.

Reutilizan este análisis todos los catálogos salvo los que cambian la config de análisis con sus
`needs` (baile: props; espadas_*: blades): esos analizan de nuevo.

Estado en api_data/uploads.json. Las subidas sin usar caducan a las 24 h.
"""

from __future__ import annotations

import json
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
from vfxglow.api.jobs import ERRORS, JobStore, _copy_limited, classify, safe_name
from vfxglow.analysis.quality import QualityWarning
from vfxglow.director.recommend import Recommendation, recommend

log = logging.getLogger("vfxglow.api")

UploadStatus = Literal["analyzing", "ready", "failed", "used"]
TTL_S = 24 * 3600
MAX_ANALYZING = 3


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
    def __init__(self, jobs: JobStore, available: Callable[[], list[str]]) -> None:
        self.jobs = jobs
        self.available = available  # nombres de los catálogos que lista /api/styles
        self.root = jobs.root / "uploads"
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = jobs.root / "uploads.json"
        self._lock = threading.Lock()
        self._items: dict[str, Upload] = {}
        if self._path.exists():
            for raw in json.loads(self._path.read_text(encoding="utf-8")):
                item = Upload.model_validate(raw)
                if item.status == "analyzing":
                    item.status, item.error_code, item.error = "failed", "interrupted", ERRORS["interrupted"]
                self._items[item.id] = item
        self._queue: queue.Queue[str] = queue.Queue()
        self._current: str | None = None  # la subida que el hilo está analizando
        self.expire()
        threading.Thread(target=self._worker, daemon=True, name="vfxglow-uploads").start()

    # ----- consulta -----

    def get(self, upload_id: str, owner: str) -> Upload:
        with self._lock:
            item = self._items.get(upload_id)
            if item is None or item.owner != owner:
                raise UploadNotFound(upload_id)
            return item.model_copy(deep=True)

    def peek(self, upload_id: str) -> Upload | None:
        """La subida sin comprobar dueño (los archivos con llave firmada lo comprueban aparte)."""
        with self._lock:
            item = self._items.get(upload_id)
            return item.model_copy(deep=True) if item is not None else None

    # ----- altas y bajas -----

    def create(self, filename: str, data, owner: str, max_bytes: int | None, check: Callable[[Path], object]) -> Upload:
        """Guarda el video, lo valida y lo pone en la cola de análisis. Si algo falla no queda nada en disco."""
        self.expire()
        with self._lock:
            if sum(i.owner == owner and i.status == "analyzing" for i in self._items.values()) >= MAX_ANALYZING:
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
        with self._lock:
            self._items[item.id] = item
            self._save()
        telemetry.event("upload.received", upload_id=item.id, usr={"id": telemetry.user_ref(owner)}, bytes=item.video_bytes, extension=target.suffix.lower())
        self._queue.put(item.id)
        return item.model_copy(deep=True)

    def delete(self, upload_id: str, owner: str) -> None:
        """Borra el archivo (y el análisis si nadie más lo usa). Si se está analizando, el hilo lo ignora al terminar."""
        with self._lock:
            item = self._items.get(upload_id)
            if item is None or item.owner != owner:
                raise UploadNotFound(upload_id)
            del self._items[upload_id]
            self._save()
        if item.status != "used":
            self._discard(item)

    def claim(self, upload_id: str, owner: str) -> tuple[Upload, str]:
        """Reserva la subida para un trabajo: queda `used` (no caduca ni se reutiliza). Devuelve
        la subida y su estado anterior, por si hay que devolverla (`release`)."""
        with self._lock:
            item = self._items.get(upload_id)
            if item is None or item.owner != owner:
                raise UploadNotFound(upload_id)
            if item.status == "used":
                raise UploadUsed(upload_id)
            previous = item.status
            item.status = "used"
            self._save()
            return item.model_copy(deep=True), previous

    def release(self, upload_id: str, previous: str) -> None:
        """El trabajo no se pudo crear: la subida vuelve a estar disponible."""
        with self._lock:
            item = self._items.get(upload_id)
            if item is not None and item.status == "used":
                item.status = previous  # type: ignore[assignment]
                self._save()

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
        with self._lock:
            old = [i for i in self._items.values() if now - i.created > TTL_S]
            for item in old:
                del self._items[item.id]
            if old:
                self._save()
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
        with self._lock:
            shared = any(i.run_dir == run_dir for i in self._items.values())
        if not shared and not any(j.run_dir == run_dir for j in self.jobs.list()) and self.jobs._removable(Path(run_dir)):
            shutil.rmtree(run_dir, ignore_errors=True)

    def _busy(self, upload_id: str) -> bool:
        return self._current == upload_id

    # ----- análisis -----

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps([i.model_dump() for i in self._items.values()], ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._path)

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

        with self._lock:
            item = self._items.get(upload_id)
            if item is None or item.status != "analyzing":  # se borró o se usó antes de empezar
                return
            item = item.model_copy(deep=True)
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
        with self._lock:
            current = self._items.get(upload_id)
            # `used` conserva su estado: el trabajo ya se llevó el video.
            if current is not None and current.status == "analyzing":
                for key, value in outcome.items():
                    setattr(current, key, value)
                self._save()
            gone = current is None
            used = current is not None and current.status == "used"
        if outcome["status"] == "ready":
            first = outcome["recommendation"][0].style if outcome["recommendation"] else None
            telemetry.event("upload.analyzed", upload_id=upload_id, usr={"id": telemetry.user_ref(item.owner)}, duration_ms=duration, cache_hit=cache_hit, style=first, warnings=[w.code for w in outcome["warnings"]])
        if gone:
            self._discard(item.model_copy(update={"run_dir": run_dir}))
        elif used:
            shutil.rmtree(Path(item.video_path).parent, ignore_errors=True)

    def _set(self, upload_id: str, **fields) -> None:
        with self._lock:
            item = self._items.get(upload_id)
            if item is not None:
                for key, value in fields.items():
                    setattr(item, key, value)
                self._save()
