"""Subidas: el video se analiza en cuanto la persona lo elige, mientras escoge estilo.

Dos formas de recibir el video:

- **Directa** (la que usa la web): `start_direct` crea la subida en estado `uploading` y devuelve
  a dónde mandar el archivo. Con GCS, una URL firmada de PUT al bucket (`uploads/<id>/<nombre>`,
  tipo y tamaño atados a la firma, vence en URL_TTL_S): el video nunca pasa por la API, que en
  Cloud Run tiene un tope de 32 MiB por petición (y Firebase Hosting, 60 s). Con archivos locales,
  una URL de la propia API (`PUT /api/uploads/{id}/file?k=...`), así en local se usa igual.
  Después, `complete` comprueba que el archivo llegó y su tamaño real y lo pone en la cola.
- **Por la API** (multipart, la de siempre; la usan las pruebas y clientes viejos): `create`
  guarda el video, lo sondea y lo pone en la cola.

El sondeo (ffprobe: duración y tamaño de imagen) y el análisis son una **tarea** de la cola
(api/tasks.py, tipo "upload") que hace un trabajador: la API no espera. Si el video no cabe en los
límites, la subida queda `failed` con un mensaje claro y su archivo se borra. Con archivos
locales el sondeo se hace ya al completar (el archivo está en este disco y tarda ~0,1 s).

Al terminar queda `ready` con una recomendación de estilo (director/recommend.py). Al crear el
trabajo con `upload_id`, el análisis ya está en la caché (la de runs/ o la compartida del almacén,
store/analysis_cache.py) o en curso: el candado del análisis hace esperar al trabajo.

Reutilizan este análisis todos los catálogos salvo los que cambian la config de análisis con sus
`needs` (baile: props; espadas_*: blades): esos analizan de nuevo.

Estado en el almacén de documentos (store/: api_data/uploads.json por defecto, o Firestore). Las
subidas sin usar caducan a las 24 h; las que se quedaron en `uploading` (la persona cerró la
pestaña), a UPLOADING_TTL_S. En el bucket, una regla de ciclo de vida sobre `uploads/` (borrar a
1 día) recoge lo que se escape (docs/despliegue_cloud_run.md).
"""

from __future__ import annotations

import logging
import mimetypes
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from vfxglow import telemetry
from vfxglow.api import tasks
from vfxglow.api.auth import upload_key
from vfxglow.api.jobs import COLLECTION as JOBS
from vfxglow.api.jobs import ERRORS, JobStore, TaskHandler, UploadTooLarge, _copy_limited, classify, safe_name
from vfxglow.analysis.quality import QualityWarning
from vfxglow.director.recommend import Recommendation, recommend
from vfxglow.store.analysis_cache import video_prefix
from vfxglow.store.docs import DELETE

log = logging.getLogger("vfxglow.api")

UploadStatus = Literal["uploading", "analyzing", "ready", "failed", "used"]
TTL_S = 24 * 3600
# Una subida directa que no se completó en este tiempo se da por abandonada.
UPLOADING_TTL_S = 3600
# Cuánto vale la URL firmada para subir (la subida tiene que empezar antes; puede terminar después).
URL_TTL_S = 900
MAX_ANALYZING = 3
COLLECTION = "uploads"
# Los fallos que dejan la subida sin archivo: no sirve para crear un trabajo.
WITHOUT_VIDEO = ("invalid_video", "too_large", "upload_missing")


class UploadNotFound(Exception):
    """La subida no existe, venció o es de otra persona."""


class UploadUsed(Exception):
    """La subida ya se usó en un trabajo."""


class UploadNotReady(Exception):
    """La subida directa aún no termina de subirse (o falló y ya no tiene video)."""


class UploadMissing(Exception):
    """Se pidió completar una subida directa pero el archivo no llegó."""


class TooManyAnalyzing(Exception):
    """La persona ya tiene el máximo de videos subiéndose o analizándose."""


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
    # Subida directa: lo que declaró el navegador (tipo y bytes) y el tope que se le firmó.
    content_type: str | None = None
    expected_bytes: int | None = None
    max_bytes: int | None = None
    # Entrada de la caché del análisis compartida (store/analysis_cache.py).
    analysis_key: str | None = None


def content_type_for(filename: str, declared: str | None) -> str:
    """El tipo con que se sube: el que dijo el navegador si es de video; si no, por la extensión."""
    if declared and declared.lower().startswith("video/"):
        return declared.lower()
    guessed = mimetypes.guess_type(filename)[0]
    return guessed if guessed and guessed.startswith("video/") else "application/octet-stream"


def catalog_names(root: Path) -> list[str]:
    """Los catálogos que se pueden recomendar (los mismos que lista /api/styles), para un
    trabajador que no tiene la API cargada."""
    from vfxglow.director.choreography import load_catalog

    return [load_catalog(path).name for path in sorted((root / "configs" / "catalogs").glob("*.yaml")) if not path.name.startswith("_")]


class UploadStore:
    """Las subidas. El estado vive en el almacén de documentos (colección "uploads"); el sondeo y
    el análisis, en la cola de tareas (los hace un trabajador, en este u otro proceso)."""

    def __init__(self, jobs: JobStore, available: Callable[[], list[str]]) -> None:
        self.jobs = jobs
        self.available = available  # nombres de los catálogos que lista /api/styles
        self.root = jobs.root / "uploads"
        self.root.mkdir(parents=True, exist_ok=True)
        self.docs = jobs.docs
        self.blobs = jobs.blobs
        for doc in self.docs.query(COLLECTION, where={"status": "analyzing"}):
            # Analizando sin tarea en la cola: de una versión anterior (el hilo de la API que la
            # analizaba ya no existe). Las que tienen tarea las recupera la cola si su trabajador muere.
            if self.docs.get(tasks.TASKS, doc["id"]) is None:
                self.docs.update(COLLECTION, doc["id"], {"status": "failed", "error_code": "interrupted", "error": ERRORS["interrupted"]}, when={"status": "analyzing"})
        self.expire()
        jobs.register(tasks.UPLOAD, TaskHandler(self._run_task, failed=self._task_failed, error=ERRORS["analysis_failed"]))
        jobs.sweepers["uploads"] = self.expire

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

    def _check_room(self, owner: str) -> None:
        busy = len(self._all(owner=owner, status="analyzing")) + len(self._all(owner=owner, status="uploading"))
        if busy >= MAX_ANALYZING:
            raise TooManyAnalyzing(owner)

    # ----- altas y bajas -----

    def create(self, filename: str, data, owner: str, max_bytes: int | None, check: Callable[[Path], object]) -> Upload:
        """Por la API: guarda el video, lo valida y lo pone en la cola de análisis. Si algo falla
        no queda nada en disco."""
        self.expire()
        self._check_room(owner)
        upload_id = "u_" + uuid.uuid4().hex[:10]
        folder = self.root / upload_id
        folder.mkdir(parents=True)
        target = folder / safe_name(filename)
        try:
            _copy_limited(data, target, max_bytes)
            info = check(target)
            self.jobs.publish(target)  # el trabajador que lo analiza puede estar en otra máquina
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
            max_bytes=max_bytes,
        )
        self.docs.set(COLLECTION, item.id, item.model_dump())
        telemetry.event("upload.received", upload_id=item.id, usr={"id": telemetry.user_ref(owner)}, bytes=item.video_bytes, extension=target.suffix.lower())
        self._enqueue(item)
        return item

    def start_direct(self, filename: str, size: int, content_type: str | None, owner: str, max_bytes: int) -> tuple[Upload, dict]:
        """Subida directa: crea la subida (`uploading`) y devuelve (subida, destino). Quien llama
        ya validó el tipo y el tamaño declarados."""
        self.expire()
        self._check_room(owner)
        upload_id = "u_" + uuid.uuid4().hex[:10]
        item = Upload(
            id=upload_id,
            owner=owner,
            created=time.time(),
            filename=filename,
            video_path=str(self.root / upload_id / safe_name(filename)),
            status="uploading",
            content_type=content_type_for(filename, content_type),
            expected_bytes=int(size),
            max_bytes=int(max_bytes),
        )
        self.docs.set(COLLECTION, item.id, item.model_dump())
        telemetry.event("upload.started", upload_id=item.id, usr={"id": telemetry.user_ref(owner)}, bytes=item.expected_bytes, direct=not self.blobs.local)
        return item, self.target(item)

    def target(self, item: Upload) -> dict:
        """A dónde y cómo subir el archivo: método, URL, cabeceras exactas y cuándo vence."""
        content_type = item.content_type or "application/octet-stream"
        limit = min(item.expected_bytes or 0, item.max_bytes or item.expected_bytes or 0)
        key = self.jobs.key(item.video_path) or ""
        signed = self.blobs.signed_upload_url(key, content_type, limit, ttl_s=URL_TTL_S)
        if signed is not None:
            url, headers = signed
        else:
            url, headers = f"/api/uploads/{item.id}/file?k={upload_key(item.id, item.owner, URL_TTL_S)}", {"Content-Type": content_type}
        return {"method": "PUT", "url": url, "headers": headers, "expires": time.time() + URL_TTL_S}

    def complete(self, upload_id: str, owner: str, check: Callable[[Path], object]) -> Upload:
        """La subida directa terminó: comprueba que el archivo está y su tamaño real, y lo pone en
        la cola. Con archivos locales lo sondea ya (`check` puede lanzar el 422 del sondeo); con
        el bucket, el sondeo lo hace el trabajador (bajar el video puede tardar más que lo que
        dura una petición). Si algo falla, la subida queda `failed` y el archivo se borra."""
        item = self.get(upload_id, owner)
        if item.status != "uploading":
            return item  # ya completada (un reintento del navegador)
        key = self.jobs.key(item.video_path) or ""
        size = self.blobs.size(key)
        if size is None:
            self._fail(item, "upload_missing")
            raise UploadMissing(upload_id)
        if size > min(item.max_bytes or size, item.expected_bytes or size):
            self._fail(item, "too_large")
            raise UploadTooLarge(upload_id)
        fields: dict = {"status": "analyzing", "video_bytes": size}
        if self.blobs.local:
            try:
                info = check(Path(item.video_path))
            except Exception as error:
                self._fail(item, "invalid_video", getattr(error, "detail", None))
                raise
            fields.update(video_seconds=getattr(info, "duration_s", None), video_width=getattr(info, "width", None), video_height=getattr(info, "height", None))
        moved = self.docs.update(COLLECTION, upload_id, fields, when={"status": "uploading"})
        current = self.peek(upload_id)
        if current is None:
            raise UploadNotFound(upload_id)
        if moved:
            telemetry.event("upload.received", upload_id=upload_id, usr={"id": telemetry.user_ref(owner)}, bytes=size, extension=Path(item.video_path).suffix.lower(), direct=True)
            self._enqueue(current)
        return current

    def _enqueue(self, item: Upload) -> None:
        self.jobs.enqueue_task(tasks.new_task(item.id, tasks.UPLOAD, item.owner, item.id))

    def _fail(self, item: Upload, code: str, message: str | None = None) -> None:
        """La subida queda fallida (con el mensaje para la persona) y sin archivo."""
        self.docs.update(COLLECTION, item.id, {"status": "failed", "error_code": code, "error": message or ERRORS[code]})
        self._remove_files(item)
        telemetry.event("upload.failed", level=logging.WARNING, upload_id=item.id, usr={"id": telemetry.user_ref(item.owner)}, error={"code": code})

    def delete(self, upload_id: str, owner: str) -> None:
        """Borra el archivo (y el análisis si nadie más lo usa). Si se está analizando, la tarea lo ignora al terminar."""
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
        # Su tarea, si aún no empezó, sobra.
        self.docs.transact(tasks.TASKS, upload_id, lambda current: DELETE if current is not None and current.get("status") == "queued" else None)
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
            found["current"] = current
            if current["status"] in ("used", "uploading") or (current["status"] == "failed" and current.get("error_code") in WITHOUT_VIDEO):
                return None
            return {**current, "status": "used"}

        taken = self.docs.transact(COLLECTION, upload_id, take)
        if "previous" not in found:
            raise UploadNotFound(upload_id)
        if taken is None:
            if found["previous"] == "used":
                raise UploadUsed(upload_id)
            raise UploadNotReady(found["current"].get("error") or "La subida aún no termina: espera a que se cargue el video.")
        return Upload.model_validate(taken), found["previous"]

    def release(self, upload_id: str, previous: str) -> None:
        """El trabajo no se pudo crear: la subida vuelve a estar disponible."""
        self.docs.update(COLLECTION, upload_id, {"status": previous}, when={"status": "used"})

    def finish_used(self, item: Upload, previous: str) -> None:
        """El trabajo ya tiene su archivo: el de la subida sobra, salvo que su análisis siga en la
        cola o en curso (la tarea lo borra al terminar)."""
        if previous == "analyzing":
            return
        self._remove_files(item)

    # ----- caducidad -----

    def expire(self, now: float | None = None) -> int:
        """Borra las subidas sin usar de más de 24 h, las directas abandonadas (`uploading` de más
        de UPLOADING_TTL_S) y los registros de las usadas. Devuelve cuántas."""
        now = now or time.time()
        old = [item for item in self._all() if now - item.created > TTL_S or (item.status == "uploading" and now - item.created > UPLOADING_TTL_S)]
        for item in old:
            self.docs.delete(COLLECTION, item.id)
        for item in old:
            if item.status != "used":
                self._discard(item)
        return len(old)

    def _remove_files(self, item: Upload) -> None:
        """El video de la subida: en este disco y en el almacén."""
        folder = Path(item.video_path).parent
        shutil.rmtree(folder, ignore_errors=True)
        key = self.jobs.key(folder)
        if key and not self.blobs.local:
            self.blobs.delete_prefix(key + "/")

    def _discard(self, item: Upload) -> None:
        self._remove_files(item)
        self._drop_run(item.run_dir, item.analysis_key)

    def _drop_run(self, run_dir: str | None, analysis_key: str | None = None) -> None:
        """La carpeta del análisis (y lo publicado de él) solo se borra si ningún trabajo ni otra subida la usa."""
        if not run_dir:
            return
        shared = bool(self.docs.query(COLLECTION, where={"run_dir": run_dir}, limit=1))
        used_by_job = bool(self.docs.query(JOBS, where={"run_dir": run_dir}, limit=1))
        if shared or used_by_job:
            return
        if self.jobs._removable(Path(run_dir)):
            shutil.rmtree(run_dir, ignore_errors=True)
        if analysis_key and not self.blobs.local:
            self.blobs.delete_prefix(video_prefix(analysis_key))

    # ----- tarea de la cola (la hace un trabajador) -----

    def _task_failed(self, doc: dict) -> None:
        """Su trabajador murió MAX_ATTEMPTS veces: la subida no terminó."""
        self.docs.update(COLLECTION, doc["ref"], {"status": "failed", "error_code": "interrupted", "error": ERRORS["interrupted"]}, when={"status": "analyzing"})

    def _run_task(self, doc: dict, flag) -> dict:
        upload_id = doc["ref"]
        item = self.peek(upload_id)
        if item is None:
            return {"status": "done"}
        if item.status == "used":
            self._remove_files(item)  # el trabajo se llevó el video antes de empezar el análisis
            return {"status": "done"}
        if item.status != "analyzing":
            return {"status": "done"}
        if item.video_seconds is None:
            refused = self._probe(item)
            if refused is not None:
                return {"status": "failed", "error_code": refused}
            item = self.peek(upload_id)
            if item is None or item.status != "analyzing":
                return {"status": "done"}
        self._analyze(item)
        return {"status": "done"}

    def _probe(self, item: Upload) -> str | None:
        """Sondea una subida directa en el trabajador. Devuelve el código del fallo, o None si cabe."""
        from fastapi import HTTPException

        from vfxglow.api import limits

        video = self.jobs.local(item.video_path)  # se trae del bucket
        if not video.exists():
            self._fail(item, "upload_missing")
            return "upload_missing"
        size = video.stat().st_size
        if item.max_bytes and size > item.max_bytes:
            self._fail(item, "too_large")
            return "too_large"
        try:
            info = limits.probe_video(video)
        except HTTPException as error:
            self._fail(item, "invalid_video", str(error.detail))
            return "invalid_video"
        self.docs.update(
            COLLECTION, item.id, {"video_seconds": info.duration_s, "video_width": info.width, "video_height": info.height, "video_bytes": size}, when={"status": "analyzing"}
        )
        return None

    def _analyze(self, item: Upload) -> None:
        from vfxglow.analysis.quality import quality_warnings
        from vfxglow.analysis.schema import MotionBrief
        from vfxglow.engine.engine import load_tracks
        from vfxglow.io.store import read_model

        upload_id = item.id
        started = time.perf_counter()
        run_dir: str | None = None
        analysis_key: str | None = None
        cache_hit = False
        try:
            with telemetry.span("upload.analyze", upload_id=upload_id):
                attributes = telemetry.current_span()
                # Sin catálogo: la config de análisis es la de por defecto, la que reutilizan los trabajos.
                pipeline = self.jobs.pipeline(self.jobs.local(item.video_path))
                run_dir = str(pipeline.run_dir)
                self._set(upload_id, run_dir=run_dir)
                pipeline.analyze()
                analysis_key = getattr(pipeline, "analysis_id", None)
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
            "analysis_key": analysis_key,
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
            self._discard(item.model_copy(update={"run_dir": run_dir, "analysis_key": analysis_key}))
        elif used:
            self._remove_files(item)

    def _set(self, upload_id: str, **fields) -> None:
        self.docs.update(COLLECTION, upload_id, fields)
