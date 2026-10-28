"""Cola con varios trabajadores (api/workqueue.py): cada trabajo una sola vez, prioridad, turnos
vencidos, cancelar y ver el avance desde otro "proceso" (otro JobStore sobre el mismo almacén) y
los archivos que produce un trabajador en otra máquina (almacén de archivos GCS de mentira)."""

from __future__ import annotations

import io
import logging
import threading
import time
from collections import Counter
from pathlib import Path

import pytest

from cloud_fakes import FakeBucket, remove_local
from vfxglow import telemetry
from vfxglow.api import workqueue
from vfxglow.api.jobs import JobStore
from vfxglow.store import GcsBlobStore, MemoryDocStore

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "default.yaml"


class FakePipeline:
    """Registra qué video procesa; `gate` (si hay) lo detiene con puntos de control hasta que se abre."""

    processed: Counter = Counter()
    gate: threading.Event | None = None
    lock = threading.Lock()

    def __init__(self, config, video: Path, **kwargs) -> None:
        self.video = Path(video)
        self.run_dir = self.video.parent.parent.parent / "runs" / self.video.parent.name

    def run(self) -> Path:
        with FakePipeline.lock:
            FakePipeline.processed[self.video.parent.name] += 1
        log = logging.getLogger("vfxglow.analysis")
        with telemetry.span("analyze"):
            log.info("Analizados 25/50 fotogramas")
            for _ in range(1000 if FakePipeline.gate is not None else 0):
                telemetry.checkpoint()
                if FakePipeline.gate.wait(0.01):
                    break
        out = self.run_dir / "output" / "out.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"editado:" + self.video.read_bytes())
        return out


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _fake_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    monkeypatch.setattr(workqueue, "CANCEL_CHECK_S", 0.01)
    logging.getLogger().setLevel(logging.INFO)
    FakePipeline.processed = Counter()
    FakePipeline.gate = None


def _store(tmp_path: Path, docs, **kwargs) -> JobStore:
    """Un "proceso": su propio JobStore (sin trabajadores propios) sobre el almacén compartido."""
    return JobStore(tmp_path / "api_data", CONFIG, docs=docs, workers=0, **kwargs)


def _create(store: JobStore, name: str = "clip.mp4"):
    return store.create(name, io.BytesIO(name.encode()), "catalog", "pelea", None)


def _until(condition, seconds: float = 10.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("no pasó a tiempo")


def test_two_workers_never_process_the_same_job(tmp_path: Path) -> None:
    docs = MemoryDocStore()
    api, first, second = _store(tmp_path, docs), _store(tmp_path, docs), _store(tmp_path, docs)
    jobs = [_create(api, f"v{i}.mp4") for i in range(12)]
    stop = threading.Event()
    workers = [workqueue.Worker(first, "w1", poll_s=0.01, stop=stop), workqueue.Worker(second, "w2", poll_s=0.01, stop=stop)]
    for worker in workers:
        worker.start()
    try:
        _until(lambda: all(api.get(job.id).status == "done" for job in jobs))
    finally:
        stop.set()
    assert FakePipeline.processed == Counter({job.id: 1 for job in jobs})
    assert {api.get(job.id).worker for job in jobs} <= {"w1", "w2"} and all(api.get(job.id).attempts == 1 for job in jobs)
    assert all(api.get(job.id).lease_until is None for job in jobs)


def test_higher_priority_first_then_the_oldest(tmp_path: Path) -> None:
    store = _store(tmp_path, MemoryDocStore())
    a, b, c = _create(store, "a.mp4"), _create(store, "b.mp4"), _create(store, "c.mp4")
    store._update(a.id, created=1.0)
    store._update(b.id, created=2.0, priority=5)
    store._update(c.id, created=0.5)
    worker = workqueue.Worker(store, "w1")
    order = []
    while worker.step():
        order.append(next(job.id for job in store.list() if job.status == "done" and job.id not in order))
    assert order == [b.id, c.id, a.id]
    assert workqueue.priority_for("cualquiera") == 0  # gancho para el plan del dueño


def test_queue_position_respects_priority(tmp_path: Path) -> None:
    store = _store(tmp_path, MemoryDocStore())
    a, b = _create(store, "a.mp4"), _create(store, "b.mp4")
    store._update(b.id, priority=5)
    assert store.queue_ahead(store.get(a.id)) == 1 and store.queue_ahead(store.get(b.id)) == 0


def test_an_expired_lease_is_requeued_and_fails_after_three_attempts(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, MemoryDocStore(), clock=clock, lease_s=30)
    job = _create(store)
    for attempt in (1, 2, 3):
        claimed = store.claim(f"muerto-{attempt}")  # un trabajador que toma el trabajo y muere
        assert claimed["id"] == job.id and claimed["attempts"] == attempt and claimed["status"] == "running"
        assert store.claim("otro") is None  # nadie más lo toma mientras su turno vale
        clock.now += 10
        assert store.reap_expired() == []  # aún vigente
        clock.now += 31
        expected = "requeued" if attempt < 3 else "failed"
        assert store.reap_expired() == [(job.id, expected)]
    failed = store.get(job.id)
    assert failed.status == "failed" and failed.error_code == "interrupted" and failed.worker is None
    assert "De vuelta en la cola" in [line["text"] for line in failed.activity]
    retried = store.retry(job.id)  # reintentar a mano empieza la cuenta de nuevo
    assert retried.status == "queued" and retried.attempts == 0


def test_a_live_worker_keeps_its_lease(tmp_path: Path) -> None:
    clock = Clock()
    store = _store(tmp_path, MemoryDocStore(), clock=clock, lease_s=30)
    job = _create(store)
    store.claim("vivo")
    clock.now += 25
    assert workqueue.heartbeat(store.docs, job.id, "vivo", clock.now, 30) is True
    clock.now += 25
    assert store.reap_expired() == [] and store.get(job.id).worker == "vivo"
    assert workqueue.heartbeat(store.docs, job.id, "impostor", clock.now, 30) is False


def test_cancel_from_another_process_stops_the_worker_and_removes_the_job(tmp_path: Path) -> None:
    docs = MemoryDocStore()
    api, worker_side = _store(tmp_path, docs), _store(tmp_path, docs)
    FakePipeline.gate = threading.Event()
    job = _create(api)
    folder = Path(job.video_path).parent
    worker = threading.Thread(target=workqueue.Worker(worker_side, "w1").step)
    worker.start()
    _until(lambda: api.get(job.id).metrics.get("current") == "analyze")
    assert api.cancel(job.id) == "stopping"  # otro JobStore: no comparte el evento en memoria
    worker.join(timeout=10)
    assert not worker.is_alive() and api.get(job.id) is None and not folder.exists()


def test_progress_is_visible_to_another_process_while_it_runs(tmp_path: Path) -> None:
    docs = MemoryDocStore()
    api, worker_side = _store(tmp_path, docs), _store(tmp_path, docs)
    FakePipeline.gate = threading.Event()
    job = _create(api)
    worker = threading.Thread(target=workqueue.Worker(worker_side, "w1").step)
    worker.start()
    try:
        _until(lambda: api.get(job.id).progress > 0)
        live = api.get(job.id)
        assert live.status == "running" and live.stage == "analyze" and "Analizados 25/50 fotogramas" in live.log
        assert live.message == "Analizando movimiento · 25/50" and live.worker == "w1"
    finally:
        FakePipeline.gate.set()
        worker.join(timeout=10)
    assert api.get(job.id).status == "done"


def test_a_worker_that_lost_its_lease_stops_without_touching_the_job(tmp_path: Path) -> None:
    docs = MemoryDocStore()
    store = _store(tmp_path, docs)
    FakePipeline.gate = threading.Event()
    job = _create(store)
    worker = threading.Thread(target=workqueue.Worker(store, "lento").step)
    worker.start()
    _until(lambda: store.get(job.id).metrics.get("current") == "analyze")
    docs.update("jobs", job.id, {"worker": "nuevo"})  # su turno venció y otro lo tomó
    worker.join(timeout=10)
    kept = store.get(job.id)
    assert not worker.is_alive() and kept is not None and kept.worker == "nuevo" and kept.status == "running"
    assert Path(kept.video_path).exists()  # no borró nada del otro


def test_startup_recovery_only_touches_running_jobs_without_a_lease(tmp_path: Path) -> None:
    docs = MemoryDocStore()
    store = _store(tmp_path, docs)
    orphan, leased = _create(store, "a.mp4"), _create(store, "b.mp4")
    docs.update("jobs", orphan.id, {"status": "running"})
    docs.update("jobs", leased.id, {"status": "running", "worker": "vivo", "lease_until": time.time() + 60})
    _store(tmp_path, docs)  # otro proceso que arranca
    assert store.get(orphan.id).status == "failed" and store.get(orphan.id).error_code == "interrupted"
    assert store.get(leased.id).status == "running" and store.get(leased.id).worker == "vivo"


def test_in_process_worker_by_default_and_none_with_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VEXORA_INPROCESS_WORKERS", raising=False)
    default = JobStore(tmp_path / "a", CONFIG, docs=MemoryDocStore())
    assert len(default.workers) == 1
    job = _create(default)
    _until(lambda: default.get(job.id).status == "done")
    default.close()
    monkeypatch.setenv("VEXORA_INPROCESS_WORKERS", "0")
    api_only = JobStore(tmp_path / "b", CONFIG, docs=MemoryDocStore())
    assert api_only.workers == []


def test_outputs_from_a_worker_on_another_machine_reach_the_api(tmp_path: Path) -> None:
    """La API y el trabajador solo comparten el almacén: el video sube al bucket al crearse, el
    trabajador lo trae, publica su salida, y la API la sirve con una URL firmada."""
    docs, bucket = MemoryDocStore(), FakeBucket()

    def machine() -> JobStore:
        return _store(tmp_path, docs, blobs=GcsBlobStore(bucket=bucket, signing=lambda: {}))

    api = machine()
    job = _create(api)
    assert bucket.objects[f"uploads/{job.id}/clip.mp4"] == b"clip.mp4"
    remove_local(Path(job.video_path).parent)  # el trabajador no tiene el video en su disco
    assert workqueue.Worker(machine(), "remoto").step()
    done = api.get(job.id)
    assert done.status == "done" and bucket.objects[f"outputs/{job.id}.mp4"] == b"editado:clip.mp4"
    remove_local(Path(done.output))  # la API (otra máquina) no tiene la salida
    assert api.has(done.output) and api.signed_url(done.output, media_type="video/mp4").startswith("https://")
    assert api.delete(job.id) and not any(key.startswith((f"outputs/{job.id}.", f"uploads/{job.id}/")) for key in bucket.objects)


def test_the_api_redirects_to_the_bucket_when_the_file_is_elsewhere(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vfxglow.api import limits, server

    monkeypatch.setenv("VEXORA_AUTH", "off")
    monkeypatch.setattr(limits, "probe_video", lambda path: limits.VideoInfo(duration_s=5.0, width=720, height=1280, fps=30.0, codec="h264"))
    docs, bucket = MemoryDocStore(), FakeBucket()
    api = JobStore(tmp_path / "api_data", CONFIG, docs=docs, blobs=GcsBlobStore(bucket=bucket, signing=lambda: {}), workers=0)
    monkeypatch.setattr(server, "store", api)
    client = TestClient(server.app)
    created = client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()
    assert created["status"] == "queued" and created["worker"] is None
    assert workqueue.Worker(_store(tmp_path, docs, blobs=GcsBlobStore(bucket=bucket, signing=lambda: {})), "remoto").step()
    remove_local(Path(api.get(created["id"]).output))
    job = client.get(f"/api/jobs/{created['id']}").json()
    response = client.get(job["output_url"] + "&download=true", follow_redirects=False)
    assert response.status_code == 307 and response.headers["location"].startswith("https://storage.example/outputs/")
    assert bucket.signed[-1][1]["response_disposition"].startswith("attachment")
