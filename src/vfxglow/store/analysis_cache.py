"""Caché del análisis compartida entre máquinas: la carpeta `analysis/` de runs/ en el almacén de archivos.

El análisis de un video (pose, pistas, gestos) es lo más caro de todo. Cada máquina lo guarda en su
runs/<video>-<hash>/, pero en la nube cada trabajador (o la API) es otra máquina: sin esto, un
trabajador "frío" vuelve a analizar lo que otro ya analizó, y la API no tiene las pistas para
/people ni el brief para la vista previa del Estudio.

- Clave: `<sha256 del video[:16]>-<clave de la etapa analyze[:24]>` (`cache_id`). La clave de la
  etapa ya incluye la config de análisis y la huella del código (Pipeline._analysis_key): otra
  config u otro código es otra entrada.
- En el almacén: `analysis/<sha16>/<clave24>/<archivo>` y, al final, `index.json` con la lista de
  archivos y la clave completa. Sin `index.json` la entrada no existe: publicar es atómico para
  quien lee (nunca ve un análisis a medias).
- Se publica todo lo de `analysis/` salvo lo que solo sirve para depurar o para volver a analizar
  (`debug_overlay.mp4`, `scene_cache/`).
- Entre procesos, un candado con turno en el almacén de documentos (colección `analysis_locks`):
  dos trabajadores no analizan el mismo video a la vez; el segundo espera y trae lo que publicó el
  primero. Si el dueño del candado muere, su turno vence y otro lo toma.

Con archivos locales (VEXORA_BLOBS=local) todo esto no hace nada: runs/ ya es el mismo disco.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from vfxglow.store.blobs import BlobStore
from vfxglow.store.docs import DELETE, DocStore

log = logging.getLogger("vfxglow.store")

PREFIX = "analysis"
INDEX = "index.json"
LOCKS = "analysis_locks"
# Lo que no se publica: depuración y la caché de preguntas de escena (solo sirve al analizar).
SKIP_FILES = {"debug_overlay.mp4"}
SKIP_DIRS = {"scene_cache"}
# Lo mínimo para dar por bueno un análisis en disco.
REQUIRED = ("header.json", "tracks.jsonl", "motion_brief.json")
LOCK_LEASE_S = 120.0


def cache_id(video_sha256: str, stage_key: str) -> str:
    return f"{video_sha256[:16]}-{stage_key[:24]}"


def prefix_of(entry: str) -> str:
    sha, _, key = entry.partition("-")
    if not sha or not key or "/" in entry:
        raise ValueError(f"Entrada de caché no válida: {entry!r}")
    return f"{PREFIX}/{sha}/{key}/"


def video_prefix(entry: str) -> str:
    """Todo lo publicado de un video (cualquier config): para borrarlo con el último trabajo que lo usa."""
    return f"{PREFIX}/{entry.partition('-')[0]}/"


def complete(run_dir: Path) -> bool:
    """Si runs/<video>/analysis tiene lo mínimo para dirigir y dibujar."""
    folder = Path(run_dir) / "analysis"
    return all((folder / name).exists() for name in REQUIRED)


class AnalysisCache:
    """Publica y trae la carpeta `analysis/`. `active` es False con archivos locales."""

    def __init__(self, docs: DocStore, blobs: BlobStore, clock: Callable[[], float] = time.time, lease_s: float = LOCK_LEASE_S, poll_s: float | None = None) -> None:
        self.docs, self.blobs, self.clock = docs, blobs, clock
        self.lease_s = lease_s
        self.poll_s = poll_s if poll_s is not None else (2.0 if docs.remote else 0.5)

    @property
    def active(self) -> bool:
        return not self.blobs.local

    # ----- publicar y traer -----

    def has(self, entry: str) -> bool:
        return self.active and bool(entry) and self.blobs.exists(prefix_of(entry) + INDEX)

    def publish(self, run_dir: Path, entry: str, stage_key: str, video_sha256: str) -> None:
        """Sube `analysis/` y al final el índice. Un fallo aquí no rompe el trabajo que analizó:
        solo significa que otra máquina tendrá que analizar de nuevo."""
        if not self.active:
            return
        folder = Path(run_dir) / "analysis"
        files = sorted(
            path.relative_to(folder).as_posix()
            for path in folder.rglob("*")
            if path.is_file() and path.name not in SKIP_FILES and not (set(path.relative_to(folder).parts[:-1]) & SKIP_DIRS) and not path.name.endswith((".tmp", ".part"))
        )
        base = prefix_of(entry)
        try:
            for name in files:
                self.blobs.put(base + name, folder / name)
            with tempfile.TemporaryDirectory() as tmp:
                index = Path(tmp) / INDEX
                index.write_text(json.dumps({"key": stage_key, "video_sha256": video_sha256, "files": files, "created": time.time()}), encoding="utf-8")
                self.blobs.put(base + INDEX, index)
        except Exception:
            log.exception("No se pudo publicar el análisis %s", entry)
            return
        log.info("Análisis publicado en el almacén (%d archivos)", len(files))

    def restore(self, run_dir: Path, entry: str | None) -> bool:
        """Trae la entrada a runs/<video>/analysis y anota la etapa en el manifiesto (así
        Pipeline.analyze la ve en caché). Devuelve si la trajo. No toma el candado de la carpeta:
        quien llama ya lo tiene (Pipeline.analyze) o usa `ensure`."""
        if not self.active or not entry:
            return False
        from vfxglow.io.store import Manifest, load_manifest, save_manifest

        run_dir = Path(run_dir)
        base = prefix_of(entry)
        staging = run_dir / f".restore-{uuid.uuid4().hex[:8]}"
        try:
            if not self.blobs.fetch(base + INDEX, staging / INDEX):
                return False
            index = json.loads((staging / INDEX).read_text(encoding="utf-8"))
            for name in index["files"]:
                if not self.blobs.fetch(base + name, staging / "analysis" / name):
                    log.warning("Análisis %s incompleto en el almacén (falta %s)", entry, name)
                    return False
            target = run_dir / "analysis"
            for name in index["files"]:
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                (staging / "analysis" / name).replace(dest)  # cada archivo, de golpe
            manifest_path = run_dir / "manifest.json"
            manifest = load_manifest(manifest_path) or Manifest(video_path="", video_sha256=index["video_sha256"], device="cpu")
            manifest.stages["analyze"] = index["key"]
            manifest.inputs["analyze"] = {"source": "almacén compartido", "entry": entry}
            save_manifest(manifest_path, manifest)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        log.info("Análisis traído del almacén compartido (%d archivos)", len(index["files"]))
        return True

    def ensure(self, run_dir: str | Path | None, entry: str | None) -> bool:
        """Para quien lee el análisis fuera de Pipeline (la API): lo deja en disco si falta.
        Devuelve si está."""
        if not run_dir:
            return False
        run_dir = Path(run_dir)
        if complete(run_dir):
            return True
        if not self.active or not entry:
            return False
        from vfxglow.pipeline import analysis_lock

        with analysis_lock(run_dir):
            if complete(run_dir):
                return True
            run_dir.mkdir(parents=True, exist_ok=True)
            return self.restore(run_dir, entry)

    # ----- candado entre procesos -----

    @contextmanager
    def lock(self, entry: str) -> Iterator[None]:
        """Un solo analizador por entrada entre todas las máquinas. Espera mientras otro lo tenga
        (o hasta que su turno venza) y lo renueva mientras dura el análisis."""
        if not self.active:
            yield
            return
        holder = uuid.uuid4().hex
        while not self._acquire(entry, holder):
            time.sleep(self.poll_s)
        stop = threading.Event()

        def renew() -> None:
            while not stop.wait(self.lease_s / 3):
                try:
                    self.docs.update(LOCKS, entry, {"until": self.clock() + self.lease_s}, when={"holder": holder})
                except Exception:  # un fallo de red: se reintenta en la siguiente vuelta
                    log.exception("No se pudo renovar el candado del análisis %s", entry)

        thread = threading.Thread(target=renew, daemon=True, name=f"vexora-analysis-lock-{entry[:8]}")
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=5)
            self.docs.transact(LOCKS, entry, lambda current: DELETE if current is not None and current.get("holder") == holder else None)

    def _acquire(self, entry: str, holder: str) -> bool:
        now = self.clock()

        def take(current: dict | None) -> dict | None:
            if current is not None and current.get("holder") != holder and float(current.get("until") or 0) > now:
                return None
            return {"id": entry, "holder": holder, "until": now + self.lease_s}

        return self.docs.transact(LOCKS, entry, take) is not None
