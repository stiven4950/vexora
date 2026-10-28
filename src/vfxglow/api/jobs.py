"""Cola de trabajos de edición para la API.

Un trabajo = un video + un estilo (catálogo o preset) + una semilla. Los procesan trabajadores
(api/workqueue.py): por defecto un hilo de la API (el análisis ya usa todos los núcleos); en la
nube, procesos aparte (`vexora-worker`) que comparten el almacén. El progreso se deduce de los
mensajes de log del pipeline, que ya informan cada etapa; así el motor no necesita saber de la API.

Estado en el almacén de documentos (store/: api_data/jobs.json por defecto, o Firestore); videos
subidos en api_data/uploads/<id>/ y salidas en api_data/outputs/, publicados en el almacén de
archivos (store/blobs.py) para que la API los sirva aunque el trabajador esté en otra máquina.
"""

from __future__ import annotations

import json
import logging
import os
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
from vfxglow.api import notifications, shares, tasks, workqueue
from vfxglow.store.analysis_cache import AnalysisCache, video_prefix
from vfxglow.store.blobs import BlobStore
from vfxglow.store.docs import DELETE, DocStore

log = logging.getLogger("vfxglow.api")

COLLECTION = workqueue.COLLECTION
# Trabajadores en hilos de la API: 1 por defecto (como siempre); 0 = la API solo encola y sirve.
INPROCESS_ENV = "VEXORA_INPROCESS_WORKERS"
# Cada cuánto, como mucho, se escribe el avance de un trabajo en el almacén.
PROGRESS_EVERY_S = 1.0

Status = Literal["queued", "running", "done", "failed"]
Stage = Literal["queued", "analyze", "direct", "render", "done"]

# Peso de cada etapa en la barra de progreso (el análisis domina el tiempo).
_ANALYZE, _DIRECT = 0.55, 0.05
LOG_LINES = 80
# Segundos de proceso por segundo de video medidos en api_data (mediana de 85 trabajos): un video
# nuevo (análisis + render) y una "otra versión" (análisis en caché). Hasta tener historial propio.
DEFAULT_RATIO = {"first": 20.0, "version": 11.0}
MIN_SAMPLES = 3


DAY_S = 24 * 3600
# Cada cuánto, como mucho, se buscan videos vencidos (al listar o al buscar trabajo).
EXPIRE_EVERY_S = 600

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
    # Objeto protagonista de los estilos que siguen uno (director/prop_choices.py); sin él, el del catálogo.
    prop: str | None = None
    # Lleva la marca de agua de Vexora (la pide el plan del dueño al crearlo; configs/plans.yaml).
    watermark: bool = False
    # Guardado en la nube por su dueño (solo con planes que lo permiten): no vence.
    saved: bool = False
    # Sin guardar, el video terminado se borra a esta hora (configs/plans.yaml, unsaved_days). None:
    # no vence (guardado, o hecho antes de esta regla).
    keep_until: float | None = None
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
    # Cola (api/workqueue.py): más prioridad va antes; `worker` y `lease_until` dicen quién lo
    # procesa y hasta cuándo vale su turno; `attempts`, cuántas veces se tomó; `cancel_requested`,
    # que la persona pidió parar (el trabajador lo ve aunque esté en otro proceso).
    priority: int = 0
    worker: str | None = None
    lease_until: float | None = None
    attempts: int = 0
    cancel_requested: bool = False
    # Entrada de la caché del análisis compartida (store/analysis_cache.py) con que se hizo: la API
    # la trae del almacén para /people aunque el análisis se hiciera en otra máquina.
    analysis_key: str | None = None
    # El video vino de una subida directa que aún no se había sondeado (duración, tamaño): el
    # trabajador lo sondea antes de procesarlo y falla con un mensaje claro si no cabe.
    probe: bool = False


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
    # Subidas directas al almacén (api/uploads.py): lo que se comprueba al terminar de subir.
    "invalid_video": "No pudimos leer el video. Expórtalo de nuevo en MP4 (H.264) y vuelve a subirlo.",
    "too_large": "El video supera el tamaño máximo permitido.",
    "upload_missing": "No recibimos el video completo. Vuelve a subirlo.",
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


class _Refused(Exception):
    """El trabajo no se procesa: su video no pasa el sondeo (código de ERRORS y mensaje claro)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def safe_name(filename: str) -> str:
    """El nombre del archivo guardado en disco (sin rutas ni caracteres raros)."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", Path(filename).name) or "video.mp4"


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


def _interrupted() -> dict:
    """Los campos de un trabajo que no terminó porque su proceso se detuvo."""
    return {"status": "failed", "error_code": "interrupted", "message": "Interrumpido", "error": ERRORS["interrupted"], "lease_until": None}


def _queue_reset(priority: int) -> dict:
    """Los campos de cola de un trabajo que entra (o vuelve) a la cola."""
    return {"priority": priority, "worker": None, "lease_until": None, "attempts": 0, "cancel_requested": False}


def _task_interrupted(_doc: dict) -> dict:
    """Una tarea cuyo trabajador murió MAX_ATTEMPTS veces."""
    return {"status": "failed", "error_code": "interrupted", "error": ERRORS["interrupted"], "lease_until": None}


class _Wake:
    """Avisa a todos los trabajadores de este proceso que hay algo nuevo en la cola (cada uno
    espera en su propio evento: con uno compartido, el primero que despierta se lo comería)."""

    def __init__(self) -> None:
        self._events: list[threading.Event] = []
        self._lock = threading.Lock()

    def add(self) -> threading.Event:
        event = threading.Event()
        with self._lock:
            self._events.append(event)
        return event

    def set(self) -> None:
        with self._lock:
            events = list(self._events)
        for event in events:
            event.set()


class TaskHandler:
    """Cómo se procesa un tipo de tarea en este proceso. `run(doc, flag)` devuelve los campos
    finales ({"status": "done"|"failed", ...}); `failed(doc)` se llama si la tarea falla sin
    trabajador (turnos vencidos); `error` es el mensaje si `run` lanza algo inesperado."""

    def __init__(self, run: Callable[[dict, workqueue.StopFlag], dict], failed: Callable[[dict], None] | None = None, error: str = ERRORS["internal"]) -> None:
        self.run, self.failed, self.error = run, failed, error


class JobStore:
    """Los trabajos: altas, consultas y el proceso de cada uno.

    La fuente de verdad es el almacén de documentos (`docs`, colección "jobs"), así que varios
    procesos lo comparten: la API encola y lee; los trabajadores (hilos de este proceso o
    `vexora-worker`) toman, procesan y escriben el avance. Los archivos que produce un trabajo se
    publican en `blobs` para que la API los sirva aunque esté en otra máquina.
    """

    def __init__(
        self,
        root: Path,
        config: Path,
        docs: DocStore | None = None,
        blobs: BlobStore | None = None,
        workers: int | None = None,
        clock: Callable[[], float] = time.time,
        lease_s: float | None = None,
        worker_kinds: tuple[str, ...] | None = ("job",),
        lanes: bool = True,
        idle_exit_s: float | None = None,
    ) -> None:
        """`workers`: trabajadores en hilos de este proceso, que toman `worker_kinds` (en la API,
        solo trabajos; `vexora-worker` pasa None = todo). Con `lanes`, cada tipo de tarea que se
        registre (`register`) tiene además su propio hilo, como antes las subidas, las vistas
        previas y las capas: una vista previa no espera detrás de un render largo."""
        from vfxglow.api.wakeup import Waker
        from vfxglow.store import open_blobs, open_docs

        self.root = root
        self.config = config
        self._last_expire = 0.0  # último barrido de videos vencidos (expire)
        self.uploads = root / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        # El MP4 de cada trabajo, aparte: en runs/ varias versiones (y usuarios) comparten carpeta.
        self.outputs = root / "outputs"
        self.outputs.mkdir(parents=True, exist_ok=True)
        self.docs = docs if docs is not None else open_docs(root)
        self.blobs = blobs if blobs is not None else open_blobs(root)
        self.clock = clock
        self.lease_s = lease_s or workqueue.lease_seconds()
        # Gancho: prioridad de un trabajo nuevo según su dueño (workqueue.priority_for).
        self.priority_of: Callable[[str | None], int] = workqueue.priority_for
        self._lock = threading.RLock()
        self._flush_lock = threading.Lock()
        # Un evento por trabajo en curso en este proceso: cancelar desde la misma API lo pone y el
        # punto de control lo ve al instante (desde otro proceso se ve en el almacén).
        self._cancel: dict[str, threading.Event] = {}
        # Avance del trabajo en curso aún sin escribir (se escribe como mucho cada PROGRESS_EVERY_S).
        self._pending: dict[str, dict] = {}
        self._flushed: dict[str, float] = {}
        self._reaped = float("-inf")
        self._ratios: dict[tuple, tuple[float, list[float]]] = {}
        self._wake = _Wake()
        self._default_wait = self._wake.add()
        # Tareas que este proceso sabe hacer (las registran UploadStore, PreviewStore y LayerStore).
        self.handlers: dict[str, TaskHandler] = {}
        # Barridos periódicos de otros almacenes (subidas vencidas, vistas previas viejas).
        self.sweepers: dict[str, Callable[[float], object]] = {}
        # Caché del análisis compartida entre máquinas (no hace nada con archivos locales).
        self.analysis = AnalysisCache(self.docs, self.blobs)
        # Despierta al Cloud Run Job de trabajadores al encolar (VEXORA_WORKER_JOB; si no, nada).
        self.waker = Waker(self.docs)
        self._recover()
        count = workers if workers is not None else int(os.environ.get(INPROCESS_ENV, "1") or 0)
        self.inprocess = count
        self.use_lanes = lanes and count > 0
        self.lanes: list[workqueue.Worker] = []
        self.stop = threading.Event()
        self.workers = workqueue.run_workers(self, count, self.stop, kinds=worker_kinds, idle_exit_s=idle_exit_s)

    @property
    def poll_s(self) -> float:
        """Cada cuánto relee el progreso un cliente en vivo (SSE): en Firestore cada lectura cuesta."""
        return 1.0 if self.docs.remote else 0.5

    def _recover(self) -> None:
        """Al arrancar: un trabajo "running" sin turno es de antes de la cola compartida (o de un
        hilo de este mismo servidor, que ya no existe): no terminó. Los que tienen turno los
        recupera `reap_expired` cuando vence, por si su trabajador sigue vivo en otro proceso."""
        for doc in self.docs.query(COLLECTION, where={"status": "running"}):
            if doc.get("lease_until") is None:
                self.docs.update(COLLECTION, doc["id"], {**_interrupted(), "worker": None}, when={"status": "running", "lease_until": None})

    # ----- documentos -----

    def _load(self, doc: dict | None) -> Job | None:
        return Job.model_validate(doc) if doc is not None else None

    def _all(self, **where) -> list[Job]:
        return [Job.model_validate(doc) for doc in self.docs.query(COLLECTION, where=where or None)]

    def _family(self, root: str) -> list[Job]:
        """El video `root` y todas sus versiones."""
        family = self._all(parent=root)
        first = self.get(root)
        return [first, *family] if first is not None else family

    # ----- consulta -----

    # ----- vencimiento de lo que no se guarda en la nube -----

    def unsaved_seconds(self) -> float:
        """Cuánto dura un video terminado sin guardar en la nube (configs/plans.yaml, unsaved_days)."""
        from vfxglow.api.plans import catalog

        return catalog(Path(self.config).resolve().parent / "plans.yaml").unsaved_days * DAY_S

    def set_saved(self, job_id: str, saved: bool) -> Job | None:
        """Guarda el video en la nube (no vence) o lo quita (vuelve a vencer en unsaved_days desde
        ahora y su enlace público deja de funcionar). None si no existe o no está terminado."""
        keep = None if saved else time.time() + self.unsaved_seconds()

        def change(current: dict | None):
            if current is None or current.get("status") != "done":
                return None
            return {**current, "saved": saved, "keep_until": keep}

        updated = self.docs.transact(COLLECTION, job_id, change)
        if not saved:
            shares.revoke(self.docs, job_id)
        return self._load(updated) if updated else None

    def expire(self, now: float | None = None) -> int:
        """Borra los videos terminados que vencieron sin guardarse en la nube. Se llama al listar y
        al buscar trabajo, como mucho cada EXPIRE_EVERY_S por proceso. Devuelve cuántos borró."""
        now = now or time.time()
        if now - self._last_expire < EXPIRE_EVERY_S:
            return 0
        self._last_expire = now
        for sweep in list(self.sweepers.values()):
            try:
                sweep(now)
            except Exception:  # un barrido que falla no detiene la cola
                log.exception("Falló un barrido periódico")
        gone = 0
        for job in self._all(status="done"):
            if job.saved or job.keep_until is None or job.keep_until > now:
                continue
            try:
                if self.delete(job.id):
                    gone += 1
                    telemetry.event("job.expired", job_id=job.id, usr={"id": telemetry.user_ref(job.owner)})
            except JobBusy:
                continue
        return gone

    def list(self, owner: str | None = None) -> list[Job]:
        """Los trabajos de `owner` (todos si es None), del más nuevo al más viejo."""
        self.expire()
        if owner is None or owner == LOCAL_OWNER:
            mine = [job for job in self._all() if owner is None or _owner(job) == owner]
        else:
            mine = self._all(owner=owner)
        return sorted(mine, key=lambda job: job.created, reverse=True)

    def estimate(self, job: Job) -> float | None:
        """Segundos que tardará el trabajo: la mediana de lo que tardaron los terminados del mismo
        estilo y tipo (primer video o versión, con o sin análisis profundo) por segundo de video, o
        los valores medidos en api_data cuando aún no hay tres. Un rango, no una promesa."""
        if not job.video_seconds:
            return None
        ratios = self._ratios_for(job.style, bool(job.parent), job.deep)
        ratio = statistics.median(ratios) if len(ratios) >= MIN_SAMPLES else (DEFAULT_RATIO["version"] if job.parent else DEFAULT_RATIO["first"])
        return round(job.video_seconds * ratio)

    def _ratios_for(self, style: str, version: bool, deep: bool) -> list[float]:
        """Segundos de proceso por segundo de video de los terminados parecidos. En Firestore se
        recuerdan un minuto: el progreso en vivo pide la estimación cada segundo."""
        key = (style, version, deep)
        cached = self._ratios.get(key)
        if self.docs.remote and cached is not None and self.clock() - cached[0] < 60:
            return cached[1]
        ratios = [
            other.metrics["total_ms"] / 1000 / other.video_seconds
            for other in self._all(status="done", style=style)
            if other.video_seconds and other.metrics.get("total_ms") and (bool(other.parent), other.deep) == (version, deep)
        ]
        self._ratios[key] = (self.clock(), ratios)
        return ratios

    def queue_ahead(self, job: Job) -> int:
        """Cuántos trabajos van antes: los que se procesan y los que llegaron antes con la misma
        prioridad o más. Solo el número, nunca de quién."""
        running = [other for other in self._all(status="running") if other.id != job.id]
        waiting = [other for other in self._all(status="queued") if other.id != job.id and (other.priority, -other.created) > (job.priority, -job.created)]
        return len(running) + len(waiting)

    def rename(self, job_id: str, title: str) -> Job | None:
        """El nombre del proyecto: se pone en el video y en todas sus versiones. Vacío = el del archivo."""
        job = self.get(job_id)
        if job is None:
            return None
        for other in self._family(job.parent or job.id):
            self.docs.update(COLLECTION, other.id, {"title": title or None})
        return self.get(job_id)

    def adopt(self, owner: str) -> int:
        """Los trabajos sin dueño (de antes de las cuentas) pasan a `owner`. Devuelve cuántos."""
        orphans = self._all(owner=None)
        for job in orphans:
            self.docs.update(COLLECTION, job.id, {"owner": owner}, when={"owner": None})
        return len(orphans)

    def get(self, job_id: str) -> Job | None:
        return self._load(self.docs.get(COLLECTION, job_id))

    # ----- archivos (store/blobs.py) -----

    def key(self, path: str | Path) -> str | None:
        """La clave de un archivo de api_data/ en el almacén de archivos; None si está fuera."""
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return None

    def publish(self, path: str | Path) -> None:
        """Publica un archivo recién escrito en api_data/ (con archivos locales, no hace nada)."""
        key = self.key(path)
        if key is not None and not self.blobs.local:
            self.blobs.put(key, Path(path))

    def local(self, path: str | Path) -> Path:
        """La ruta local del archivo, trayéndolo del almacén si en esta máquina no está."""
        target = Path(path)
        if not target.exists() and not self.blobs.local:
            key = self.key(target)
            if key is not None:
                self.blobs.fetch(key, target)
        return target

    def has(self, path: str | Path) -> bool:
        """Si el archivo existe aquí o en el almacén."""
        if Path(path).exists():
            return True
        key = self.key(path)
        return key is not None and not self.blobs.local and self.blobs.exists(key)

    def signed_url(self, path: str | Path, filename: str | None = None, media_type: str | None = None) -> str | None:
        """Una URL temporal del almacén para un archivo que no está en esta máquina (None en local)."""
        key = self.key(path)
        if key is None or self.blobs.local or not self.blobs.exists(key):
            return None
        return self.blobs.signed_url(key, filename=filename, media_type=media_type)

    def _forget_files(self, prefix: str) -> None:
        if not self.blobs.local:
            self.blobs.delete_prefix(prefix)

    # ----- análisis compartido (store/analysis_cache.py) -----

    def pipeline(self, video: Path, restore: bool = False, analysis_key: str | None = None, **kwargs):
        """Un Pipeline con la caché del análisis compartida. Con `restore`, deja en disco el
        análisis que otra máquina publicó (la entrada `analysis_key` si se conoce, o la que
        corresponde a la config del Pipeline), para lo que lo lee sin analizar."""
        from vfxglow.pipeline import Pipeline

        pipeline = Pipeline(self.config, video, **kwargs)
        if self.analysis.active:
            pipeline.shared = self.analysis
            if restore:
                if not self.analysis.ensure(pipeline.run_dir, analysis_key) and hasattr(pipeline, "restore_analysis"):
                    pipeline.restore_analysis()
        return pipeline

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
        prop: str | None = None,
        watermark: bool = False,
        max_bytes: int | None = None,
        check: Callable[[Path], object] | None = None,
        source: Path | None = None,
        info: object | None = None,
        source_bytes: int | None = None,
    ) -> Job:
        """Guarda el video y encola el trabajo. `max_bytes` corta la copia aunque el cliente no
        haya dicho el tamaño (UploadTooLarge); `check` valida el archivo guardado antes de
        encolarlo. Si algo falla, no queda nada en disco. Con `source` (el video de una subida,
        con su `info` si ya se sondeó) no se copia ningún flujo: se enlaza el archivo, o, si
        solo está en el almacén (subida directa al bucket), se copia dentro del almacén."""
        job_id = uuid.uuid4().hex[:10]
        folder = self.uploads / job_id
        folder.mkdir(parents=True)
        safe = safe_name(filename)
        target = folder / safe
        remote_copy = source is not None and not Path(source).exists() and not self.blobs.local
        try:
            if remote_copy:
                source_key, target_key = self.key(source), self.key(target)
                if source_key is None or target_key is None:
                    raise FileNotFoundError(source)
                self.blobs.copy(source_key, target_key)
            elif source is not None:
                try:
                    os.link(source, target)  # la subida conserva su archivo hasta que acabe su análisis
                except OSError:
                    shutil.copy2(source, target)
            else:
                _copy_limited(data, target, max_bytes)
                info = check(target) if check is not None else None
            if not remote_copy:
                self.publish(target)  # el trabajador puede estar en otra máquina
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            if remote_copy and (key := self.key(folder)):
                self._forget_files(key + "/")
            raise
        size = target.stat().st_size if target.exists() else int(source_bytes or 0)
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
            prop=prop,
            watermark=watermark,
            video_seconds=getattr(info, "duration_s", None),
            video_width=getattr(info, "width", None),
            video_height=getattr(info, "height", None),
            video_bytes=size,
            probe=source is not None and info is None,
        )
        job.activity = [{"at": job.created, "text": "Video recibido", "detail": f"{filename} ({size / 1e6:.1f} MB)"}]
        if source is None:  # con una subida, `upload.received` ya se emitió al recibirla
            telemetry.event(
                "upload.received",
                job_id=job.id,
                trace_id=job.trace_id,
                usr={"id": telemetry.user_ref(owner)},
                bytes=size,
                extension=target.suffix.lower(),
                video=info.model_dump() if isinstance(info, BaseModel) else None,
            )
        return self._enqueue(job)

    def retry(self, job_id: str) -> Job:
        """Vuelve a encolar un trabajo que falló, con lo mismo que pidió (y su misma traza)."""

        def again(current: dict | None) -> dict | None:
            if current is None or current.get("status") != "failed":
                return None
            return {
                **current,
                **_queue_reset(self.priority_of(current.get("owner"))),
                "status": "queued", "stage": "queued", "progress": 0.0, "message": "En cola",
                "error": None, "error_code": None, "log": [], "started": None, "finished": None, "metrics": {},
            }

        snapshot = self._load(self.docs.transact(COLLECTION, job_id, again))
        if snapshot is None:
            raise NotRetryable(job_id)
        self._wake.set()
        telemetry.event("job.retried", job_id=job_id, trace_id=snapshot.trace_id)
        return snapshot

    def variation(
        self,
        parent: Job,
        style_kind: str,
        style: str,
        seed: int | None,
        season: str | None = None,
        wardrobe: dict[str, str] | None = None,
        deep: bool | None = None,
        fire_style: str | None = None,
        bolt_style: str | None = None,
        prop: str | None = None,
        watermark: bool | None = None,
    ) -> Job:
        """Mismo video, otro estilo u otra versión: el análisis queda en caché y es rápido.

        Sin semilla, "otra versión" del mismo estilo es la siguiente del ranking (la mejor que no
        se haya hecho todavía para ese video); con otro estilo, se empieza por la mejor."""
        root = parent.parent or parent.id
        wear = parent.wardrobe if wardrobe is None else wardrobe
        deep = parent.deep if deep is None else deep
        fire_style = parent.fire_style if fire_style is None else (fire_style or None)
        bolt_style = parent.bolt_style if bolt_style is None else (bolt_style or None)
        prop = parent.prop if prop is None else (prop or None)
        take = 0
        if seed is None:
            done = [j.take for j in self._family(root) if j.style == style and j.style_kind == style_kind and j.seed is None and j.season == season and j.wardrobe == wear and j.fire_style == fire_style and j.bolt_style == bolt_style and j.prop == prop]
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
                prop=prop,
                watermark=parent.watermark if watermark is None else watermark,
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
        outcome: dict = {}

        def drop(current: dict | None):
            outcome.clear()
            if current is None:
                return None
            if current.get("status") == "running":
                outcome["busy"] = True
                return None
            outcome["job"] = current
            return DELETE

        self.docs.transact(COLLECTION, job_id, drop)
        if outcome.get("busy"):
            raise JobBusy(job_id)
        if "job" not in outcome:
            return False
        self._cleanup(Job.model_validate(outcome["job"]))
        return True

    def cancel(self, job_id: str) -> str:
        """Cancelar: en cola, se borra ya; en curso, se pide parar y el proceso se corta en su
        próximo punto de control (cada pocos fotogramas) y se borra solo. Devuelve "removed",
        "stopping" o "none" si ya no hay nada que cancelar. Es una transacción: si un trabajador
        lo toma justo ahora, se le pide parar en vez de borrarlo debajo de él."""
        outcome: dict = {}

        def stop(current: dict | None):
            outcome.clear()
            if current is None or current.get("status") not in ("queued", "running"):
                outcome["result"] = "none"
                return None
            if current["status"] == "running":
                outcome["result"] = "stopping"
                return {**current, "cancel_requested": True}
            outcome["result"], outcome["job"] = "removed", current
            return DELETE

        self.docs.transact(COLLECTION, job_id, stop)
        if outcome["result"] == "stopping":
            with self._lock:
                event = self._cancel.get(job_id)
            if event is not None:
                event.set()
        elif outcome["result"] == "removed":
            self._cleanup(Job.model_validate(outcome["job"]))
        return outcome["result"]

    def _remove(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None:
            return False
        self.docs.delete(COLLECTION, job_id)
        self._cleanup(job)
        return True

    def _cleanup(self, job: Job) -> None:
        """Los archivos de un trabajo ya borrado del almacén (el video y el análisis, si nadie más los usa)."""
        job_id = job.id
        video_shared = bool(self.docs.query(COLLECTION, where={"video_path": job.video_path}, limit=1))
        run_shared = bool(self.docs.query(COLLECTION, where={"run_dir": job.run_dir}, limit=1))
        (self.outputs / f"{job_id}.mp4").unlink(missing_ok=True)
        for leftover in self.outputs.glob(f"{job_id}.*"):
            leftover.unlink(missing_ok=True)  # guion, momentos, gestos y tira de fotogramas del editor
        self._forget_files(f"outputs/{job_id}.")
        shares.erase_job(self.docs, job_id)  # sus enlaces públicos dejan de existir con él
        self.forget_tasks(job_id)  # sus vistas previas y sus capas
        folder = Path(job.video_path).parent
        if video_shared:
            for cache in folder.glob(f"thumb-{job_id}-*.jpg"):
                cache.unlink(missing_ok=True)
        else:
            shutil.rmtree(folder, ignore_errors=True)
            key = self.key(folder)
            if key:
                self._forget_files(key + "/")
        if job.run_dir and not run_shared and self._removable(Path(job.run_dir)):
            shutil.rmtree(job.run_dir, ignore_errors=True)
        if job.analysis_key and not run_shared and not self.docs.query(COLLECTION, where={"analysis_key": job.analysis_key}, limit=1):
            self._forget_files(video_prefix(job.analysis_key))  # el análisis publicado de ese video
        telemetry.event("job.deleted", job_id=job_id, trace_id=job.trace_id, run_deleted=bool(job.run_dir and not run_shared))

    def _removable(self, run_dir: Path) -> bool:
        """Solo se borra una carpeta de análisis dentro de runs/ o de api_data/, nunca otra ruta."""
        from vfxglow.config import load_config

        runs = Path(load_config(self.config).paths.runs_dir)
        runs = runs if runs.is_absolute() else Path.cwd() / runs
        target = run_dir.resolve()
        return any(target != root.resolve() and target.is_relative_to(root.resolve()) for root in (runs, self.root))

    # ----- actualización -----

    def append_log(self, job_id: str, line: str, update: dict) -> None:
        """Una línea del pipeline y lo que dice del avance. Se juntan y se escriben como mucho una
        vez por PROGRESS_EVERY_S: la API (quizá otro proceso) lee el avance del almacén."""
        with self._lock:
            pending = self._pending.setdefault(job_id, {"log": [], "fields": {}})
            pending["log"].append(line)
            pending["fields"].update(update)
            wait = PROGRESS_EVERY_S - (self.clock() - self._flushed.get(job_id, float("-inf")))
            # Si no toca todavía, se deja programado: la última línea no espera a la siguiente.
            later = wait > 0 and not pending.get("scheduled")
            if later:
                pending["scheduled"] = True
        if wait <= 0:
            self._flush(job_id)
        elif later:
            timer = threading.Timer(wait, self._flush, args=(job_id,))
            timer.daemon = True
            timer.start()

    def _flush(self, job_id: str) -> None:
        """Escribe el avance pendiente del trabajo (si hay)."""
        with self._flush_lock:
            with self._lock:
                pending = self._pending.pop(job_id, None)
                if pending:
                    self._flushed[job_id] = self.clock()
            if not pending:
                return

            def merge(current: dict | None) -> dict | None:
                if current is None:  # se canceló y se borró mientras tanto
                    return None
                merged = {**current, **pending["fields"], "log": ([*(current.get("log") or []), *pending["log"]])[-LOG_LINES:]}
                if "progress" in pending["fields"]:
                    merged["progress"] = max(min(float(merged["progress"]), 1.0), 0.0)
                return merged

            self.docs.transact(COLLECTION, job_id, merge)

    def _update(self, job_id: str, when: dict | None = None, **fields) -> bool:
        """Escribe campos del trabajo (antes, el avance pendiente). Con `when`, solo si el documento
        lo cumple (p. ej. que siga siendo de este trabajador). Devuelve si escribió."""
        self._flush(job_id)
        return self.docs.update(COLLECTION, job_id, fields, when=when)

    def _enqueue(self, job: Job) -> Job:
        job = job.model_copy(update=_queue_reset(self.priority_of(job.owner)))
        self.docs.set(COLLECTION, job.id, job.model_dump())
        depth = len(self.docs.query(COLLECTION, where={"status": "queued"}))
        self._wake.set()
        self.waker.poke_later()
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
            prop=job.prop,
            priority=job.priority,
            queue_depth=depth,
        )
        return job

    # ----- cola (api/workqueue.py) -----

    def wake_all(self) -> None:
        """Despierta a los trabajadores de este proceso (p. ej. tras registrar tipos de tarea)."""
        self._wake.set()

    def waiter(self) -> threading.Event:
        """El evento con que este proceso despierta a un trabajador suyo."""
        return self._wake.add()

    def wait_for_work(self, timeout: float, event: threading.Event | None = None) -> None:
        """Un trabajador sin nada que hacer espera `timeout` o a que este proceso encole algo."""
        event = event or self._default_wait
        if event.wait(timeout):
            event.clear()

    def close(self) -> None:
        """Los trabajadores de este almacén dejan de tomar trabajos (el que está en curso termina)."""
        self.stop.set()
        self._wake.set()

    def register(self, kind: str, handler: TaskHandler) -> None:
        """Este proceso sabe hacer las tareas `kind`. En la API (con trabajadores en hilos), arranca
        también un hilo propio para ese tipo, una sola vez aunque se registre de nuevo."""
        first = kind not in self.handlers
        self.handlers[kind] = handler
        if first and self.use_lanes:
            lane = workqueue.Worker(self, workqueue.new_worker_id(len(self.lanes) + 100), stop=self.stop, kinds=(kind,))
            lane.name = f"vfxglow-{kind}-{lane.worker_id}"
            self.lanes.append(lane)
            lane.start()
        self._wake.set()

    def claim(self, worker_id: str, kinds: tuple[str, ...] | None = None) -> dict | None:
        """Lo siguiente para un trabajador que toma `kinds` (None = todo lo que este proceso sabe
        hacer): primero las tareas (todas tienen más prioridad que los trabajos), luego trabajos."""
        now = self.clock()
        wanted = [kind for kind in (kinds if kinds is not None else ("job", *self.handlers)) if kind == "job" or kind in self.handlers]
        task_kinds = [kind for kind in wanted if kind != "job"]
        if task_kinds:
            where = {"kind": task_kinds[0]} if len(task_kinds) == 1 else None
            doc = workqueue.claim(self.docs, worker_id, now, self.lease_s, collection=tasks.TASKS, where=where, accept=lambda d: self._accept_task(d, task_kinds))
            if doc is not None:
                return doc
        if "job" in wanted:
            return workqueue.claim(self.docs, worker_id, now, self.lease_s)
        return None

    def _accept_task(self, doc: dict, kinds: list[str]) -> bool:
        """Una tarea que este trabajador sabe hacer. De las vistas previas, una a la vez por
        persona aunque haya varios trabajadores (la siguiente espera a que termine la suya)."""
        if doc.get("kind") not in kinds:
            return False
        if doc.get("kind") == tasks.PREVIEW and doc.get("owner"):
            return not self.docs.query(tasks.TASKS, where={"kind": tasks.PREVIEW, "owner": doc["owner"], "status": "running"}, limit=1)
        return True

    def enqueue_task(self, doc: dict) -> dict:
        """Pone una tarea en la cola (reemplaza la que tuviera ese id) y avisa a los trabajadores."""
        self.docs.set(tasks.TASKS, doc["id"], doc)
        self._wake.set()
        self.waker.poke_later()
        return doc

    def forget_tasks(self, ref: str) -> None:
        """Las tareas de un trabajo o una subida que se borra, con sus vistas previas."""
        for doc in self.docs.query(tasks.TASKS, where={"ref": ref}):
            if doc.get("kind") != tasks.UPLOAD:
                self.docs.delete(tasks.TASKS, doc["id"])
        shutil.rmtree(self.root / "previews" / ref, ignore_errors=True)
        self._forget_files(f"previews/{ref}/")

    def _process_task(self, doc: dict, worker_id: str) -> None:
        """Procesa una tarea ya tomada por `worker_id`, renovando su turno mientras dura."""
        task_id, kind = doc["id"], doc["kind"]
        handler = self.handlers[kind]
        mine = {"worker": worker_id, "status": "running"}
        flag = workqueue.StopFlag(self.docs, task_id, worker_id, clock=self.clock, collection=tasks.TASKS)
        self.docs.update(tasks.TASKS, task_id, {"started": time.time()}, when=mine)
        try:
            with workqueue.Lease(self.docs, task_id, worker_id, self.lease_s, flag, clock=self.clock, collection=tasks.TASKS):
                outcome = handler.run(doc, flag) or {}
        except Exception as error:  # el detalle va al registro; quien espera ve un mensaje claro
            log.exception("Tarea %s (%s) falló", task_id, kind)
            telemetry.event("task.failed", level=logging.ERROR, task_id=task_id, kind=kind, error={"kind": type(error).__name__, "message": telemetry.redact(str(error))[:500]})
            outcome = {"status": "failed", "error": handler.error, "error_code": "internal"}
        if flag.lost:
            return  # su turno pasó a otro trabajador: la termina él
        final = {"status": "done", **outcome, "finished": time.time(), "lease_until": None}
        self.docs.update(tasks.TASKS, task_id, final, when=mine)

    def reap_expired(self) -> list[tuple[str, str]]:
        """Recupera los trabajos de trabajadores que dejaron de renovar su turno (cada medio turno)."""
        self.expire()  # los trabajadores también barren lo vencido (la API puede no listar en horas)
        now = self.clock()
        with self._lock:
            if now - self._reaped < self.lease_s / 2:
                return []
            self._reaped = now
        outcomes = workqueue.reap(self.docs, now, _interrupted())
        for job_id, outcome in outcomes:
            log.warning("Trabajo %s: su trabajador dejó de responder (%s)", job_id, outcome)
            telemetry.event("job.lease_expired", level=logging.WARNING, job_id=job_id, outcome=outcome)
        task_outcomes = workqueue.reap(self.docs, now, _task_interrupted, collection=tasks.TASKS, requeued=None)
        for task_id, outcome in task_outcomes:
            log.warning("Tarea %s: su trabajador dejó de responder (%s)", task_id, outcome)
            telemetry.event("task.lease_expired", level=logging.WARNING, task_id=task_id, outcome=outcome)
            doc = self.docs.get(tasks.TASKS, task_id) if outcome == "failed" else None
            handler = self.handlers.get(doc.get("kind")) if doc else None
            if handler is not None and handler.failed is not None:
                handler.failed(doc)
        outcomes = [*outcomes, *task_outcomes]
        if any(outcome == "requeued" for _, outcome in outcomes):
            self._wake.set()
        return outcomes

    def process(self, doc: dict, worker_id: str) -> None:
        """Procesa un trabajo (o una tarea) ya tomado por `worker_id`, renovando su turno mientras dura."""
        if doc.get("kind") in self.handlers and "style_kind" not in doc:
            self._process_task(doc, worker_id)
            return
        job = Job.model_validate(doc)
        event = threading.Event()
        with self._lock:
            self._cancel[job.id] = event
        flag = workqueue.StopFlag(self.docs, job.id, worker_id, local=event, clock=self.clock)
        try:
            with workqueue.Lease(self.docs, job.id, worker_id, self.lease_s, flag, clock=self.clock):
                self._run(job, worker_id, flag)
        finally:
            with self._lock:
                self._cancel.pop(job.id, None)
                self._pending.pop(job.id, None)
                self._flushed.pop(job.id, None)

    # ----- trabajo -----

    def _run(self, job: Job, worker_id: str, flag: workqueue.StopFlag) -> None:
        mine = {"worker": worker_id}
        handler = _Progress(self, job.id)
        root = logging.getLogger()
        root.addHandler(handler)
        started = time.time()
        self._update(job.id, when=mine, status="running", stage="analyze", message="Preparando", started=started)
        context = telemetry.job_context(job.id, job.trace_id, on_change=self._stage_changed(job.id), cancel=flag, usr={"id": telemetry.user_ref(job.owner)}, style=job.style)
        with context as summary:
            summary["queue_wait_ms"] = round((started - job.created) * 1000)
            self._note(job.id, "Inicio del procesamiento", "Se ha iniciado el análisis del video.")
            self._update(job.id, metrics=dict(summary))
            telemetry.event("job.started", queue_wait_ms=summary["queue_wait_ms"], deep=job.deep, take=job.take, attempt=job.attempts)
            try:
                video = self.local(job.video_path)  # en otra máquina, se trae del almacén
                if job.probe:
                    self._probe(job, video)
                pipeline = self.pipeline(video, restore=bool(job.edits), analysis_key=job.analysis_key, **self._pipeline_kwargs(job))
                self._update(job.id, run_dir=str(pipeline.run_dir))
                if job.edits:
                    output = self._edit(job, pipeline)
                else:
                    output = self._keep(job.id, pipeline.run())
                    self._save_artifacts(job.id, pipeline)
                    self._save_choreography(job, pipeline)
                finished = time.time()
                summary["total_ms"] = round((finished - started) * 1000)
                done = dict(status="done", stage="done", progress=1.0, message="Listo", output=str(output), finished=finished, metrics=summary, lease_until=None)
                done["analysis_key"] = getattr(pipeline, "analysis_id", None) or job.analysis_key
                if not job.saved:
                    done["keep_until"] = finished + self.unsaved_seconds()
                if self._update(job.id, when=mine, **done):
                    telemetry.event("job.finished", outcome="ok", duration_ms=summary["total_ms"], output_bytes=output.stat().st_size, metrics=summary)
                    self._notify(job, "job_done", "Tu video está listo", "{name} terminó de procesarse.")
            except _Refused as refused:  # el video no cabe en los límites (subida directa sin sondear)
                finished = time.time()
                summary["total_ms"] = round((finished - started) * 1000)
                if self._update(job.id, when=mine, status="failed", message="Falló", error=refused.message, error_code=refused.code, finished=finished, metrics=summary, lease_until=None):
                    self._notify(job, "job_failed", "No pudimos terminar tu video", "{name} no se pudo procesar. Revisa el video y vuelve a intentarlo.")
                telemetry.event("job.failed", level=logging.WARNING, outcome="refused", error={"code": refused.code})
            except telemetry.Cancelled:
                if flag.lost:  # el turno pasó a otro trabajador: el trabajo sigue, solo que no aquí
                    telemetry.event("job.abandoned", level=logging.WARNING, duration_ms=round((time.time() - started) * 1000))
                    return
                # La persona canceló: no queda nada que mostrar, así que se borra todo.
                telemetry.event("job.cancelled", duration_ms=round((time.time() - started) * 1000))
                self._remove(job.id)
            except Exception as exc:  # el mensaje claro va a la interfaz; el detalle, al registro
                code = classify(exc, summary.get("failed_stage"))
                log.exception("Trabajo %s falló (%s)", job.id, code)
                finished = time.time()
                summary["total_ms"] = round((finished - started) * 1000)
                if self._update(job.id, when=mine, status="failed", message="Falló", error=ERRORS[code], error_code=code, finished=finished, metrics=summary, lease_until=None):
                    self._notify(job, "job_failed", "No pudimos terminar tu video", "{name} falló al procesarse. Puedes reintentarlo.")
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

    def _probe(self, job: Job, video: Path) -> None:
        """Sondea un video de subida directa que nadie había sondeado: si no cabe en los límites,
        el trabajo falla con el mensaje del sondeo (no se analiza un video de dos horas)."""
        from fastapi import HTTPException

        from vfxglow.api import limits

        try:
            info = limits.probe_video(video)
        except HTTPException as error:
            raise _Refused("invalid_video", str(error.detail)) from error
        self._update(job.id, probe=False, video_seconds=info.duration_s, video_width=info.width, video_height=info.height)

    def _save_choreography(self, job: Job, pipeline) -> None:
        """La coreografía con que se hizo esta versión (para /choreography), junto a sus demás
        archivos: así la API la lee del almacén aunque runs/ esté en otra máquina."""
        path = Path(pipeline.run_dir) / "scripts" / f"{job.style}.choreography.json"
        if path.exists():
            self._write_artifact(job.id, "choreography", path.read_text(encoding="utf-8"))

    def _notify(self, job: Job, kind: str, title: str, text: str) -> None:
        """El aviso de la campana (si su dueño lo quiere). Va aquí, en el trabajador, para que
        exista aunque la API sea otro proceso; un fallo del aviso nunca afecta al trabajo."""
        try:
            name = job.title or Path(job.filename).stem or "Tu video"
            notifications.notify(self.docs, _owner(job), kind, title, text.format(name=name), job_id=job.id)
        except Exception:
            log.exception("Trabajo %s: no se pudo crear el aviso", job.id)

    @staticmethod
    def _pipeline_kwargs(job: Job) -> dict:
        """Con lo que se crea el Pipeline de un trabajo (al procesarlo y al prepararlo para editar)."""
        kwargs = {"catalog": job.style, "seed": job.seed, "take": job.take} if job.style_kind == "catalog" else {"preset": job.style}
        kwargs["season"] = job.season
        if job.style_kind == "catalog" and (job.fire_style or job.bolt_style):
            kwargs["fire_style"] = job.fire_style
            kwargs["bolt_style"] = job.bolt_style
        if job.style_kind == "catalog" and job.wardrobe:
            kwargs["wardrobe"] = job.wardrobe
        if job.style_kind == "catalog" and job.deep:
            kwargs["deep"] = True
        if job.style_kind == "catalog" and job.prop:
            kwargs["prop"] = job.prop
        if job.watermark:
            kwargs["watermark"] = True
        return kwargs

    def _note(self, job_id: str, text: str, detail: str = "") -> None:
        """Una línea de la actividad reciente (las últimas ACTIVITY_LINES)."""
        line = {"at": time.time(), "text": text, "detail": detail}

        def add(current: dict | None) -> dict | None:
            if current is None:
                return None
            return {**current, "activity": [*(current.get("activity") or []), line][-ACTIVITY_LINES:]}

        self.docs.transact(COLLECTION, job_id, add)

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

    def read_artifact(self, job_id: str, kind: str) -> str:
        """El contenido de un artefacto (traído del almacén si esta máquina no lo tiene)."""
        return self.local(self.artifact(job_id, kind)).read_text(encoding="utf-8")

    def _write_artifact(self, job_id: str, kind: str, text: str) -> None:
        path = self.artifact(job_id, kind)
        path.write_text(text, encoding="utf-8")
        self.publish(path)

    def editable(self, job: Job) -> bool:
        return job.status == "done" and job.style_kind == "catalog" and all(self.has(self.artifact(job.id, k)) for k in ("script", "moments", "events"))

    def preparable(self, job: Job) -> bool:
        """Una versión terminada de catálogo hecha antes del editor: sin sus artefactos."""
        return job.status == "done" and job.style_kind == "catalog" and not self.editable(job)

    def prepare(self, job: Job) -> Job:
        """Deja editable una versión hecha antes del editor: vuelve a dirigir (sin analizar ni
        dibujar) con el análisis que quedó en disco y guarda sus artefactos. Se marca como
        `prepared`: el guion regenerado puede no coincidir al píxel con su video."""
        if not self.preparable(job):
            raise ValueError("Esta versión no necesita prepararse para editar.")
        pipeline = self.pipeline(self.local(job.video_path), restore=True, analysis_key=job.analysis_key, **self._pipeline_kwargs(job))
        if not (Path(pipeline.run_dir) / "analysis" / "motion_brief.json").exists():
            raise ValueError("Ya no está el análisis de este video: crea otra versión para editarla.")
        pipeline.direct()
        self._save_artifacts(job.id, pipeline)
        if not self.editable(job):
            raise ValueError("No se pudo regenerar el guion de esta versión: crea otra versión para editarla.")
        self._write_artifact(job.id, "prepared", json.dumps({"prepared": True}))
        return self.get(job.id) or job

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
        moments = moments_from(script, choreography.decisions, pipeline._meta().frame_count)
        events = Path(pipeline.run_dir) / "analysis" / "events.jsonl"
        self._write_artifact(job_id, "script", script.model_dump_json())
        self._write_artifact(job_id, "moments", json.dumps([m.model_dump() for m in moments], ensure_ascii=False))
        lines = events.read_text(encoding="utf-8").splitlines() if events.exists() else []
        self._write_artifact(job_id, "events", json.dumps([json.loads(line) for line in lines if line.strip()]))

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
                    # La versión nueva no hereda la nube de la base: se guarda (o vence) por su cuenta.
                    "saved": False,
                    "keep_until": None,
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
            script = EffectScript.model_validate_json(self.read_artifact(base, "script"))
            moments = [Moment.model_validate(m) for m in json.loads(self.read_artifact(base, "moments"))]
            events_text = self.read_artifact(base, "events")
            events = [MotionEvent.model_validate(e) for e in json.loads(events_text)]
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
            )
            window = changed_window(script, new, events, frames, fps)
            self._write_artifact(job.id, "script", new.model_dump_json())
            self._write_artifact(job.id, "moments", json.dumps([m.model_dump() for m in new_moments], ensure_ascii=False))
            self._write_artifact(job.id, "events", events_text)
        dest = self.outputs / f"{job.id}.mp4"
        base_video = self.local(self.outputs / f"{base}.mp4")
        if window is None and base_video.exists():
            # Nada que cambie en pantalla: la versión nueva es la misma imagen.
            return self._keep(job.id, base_video)
        # Una base preparada (api_data: "prepared") tiene un guion regenerado después de dibujar su
        # video: puede no coincidir al píxel, así que copiar de ese video dejaría costuras. Se redibuja entero.
        prepared = self.has(self.artifact(base, "prepared"))
        partial = window is not None and window != (0, frames - 1) and base_video.exists() and not prepared
        with telemetry.span("compose", streamed=True, partial=partial, window=list(window) if window else None):
            pipeline.render_script(new, dest, base_output=base_video if partial else None, window=window if partial else None, events=events)
        summary_window = {"window_frames": (window[1] - window[0] + 1) if window else 0, "total_frames": frames, "partial": partial}
        self._note(job.id, "Tramo redibujado" if partial else "Video redibujado completo", f"{summary_window['window_frames']} de {frames} fotogramas")
        self.publish(dest)
        return dest

    def _keep(self, job_id: str, output: Path) -> Path:
        """El MP4 del trabajo en api_data/outputs/<id>.mp4. Enlace duro si se puede (el pipeline
        escribe el siguiente video en un archivo nuevo y lo renombra, así que el enlace conserva
        este); si no, copia. Se publica en el almacén para que la API lo sirva."""
        target = self.outputs / f"{job_id}.mp4"
        target.unlink(missing_ok=True)
        try:
            os.link(output, target)
        except OSError:
            shutil.copy2(output, target)
        self.publish(target)
        return target
