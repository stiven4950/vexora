"""La API lista para varias instancias en Cloud Run: subidas directas al almacén, tareas en la cola
(subidas, vistas previas, capas) que hacen trabajadores de otros "procesos", la caché del análisis
compartida, despertar al Cloud Run Job de trabajadores y su salida por inactividad.

Un "proceso" es su propio JobStore sobre el almacén compartido (documentos en memoria y un bucket
de mentira, tests/cloud_fakes.py); "otra máquina" = se borra la copia local del archivo."""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from cloud_fakes import FakeBucket, remove_local  # noqa: E402
from test_uploads import AVAILABLE, USERS, FakePipeline, as_, make_brief, wait_job, wait_upload  # noqa: E402
from vfxglow.analysis.schema import FrameRecord  # noqa: E402
from vfxglow.api import auth, limits, server, tasks, wakeup, workqueue  # noqa: E402
from vfxglow.api.jobs import JobStore, TaskHandler  # noqa: E402
from vfxglow.api.uploads import UploadStore  # noqa: E402
from vfxglow.store import GcsBlobStore, LocalBlobStore, MemoryDocStore  # noqa: E402
from vfxglow.store.analysis_cache import AnalysisCache, cache_id, complete  # noqa: E402

CONFIG = server.CONFIG
VIDEO = b"\x00" * 64


def fake_probe(path: Path) -> limits.VideoInfo:
    fake_probe.calls += 1
    return limits.VideoInfo(duration_s=9.4, width=720, height=1280, fps=30.0, codec="h264")


fake_probe.calls = 0


class SharedPipeline(FakePipeline):
    """Como el de test_uploads, pero su análisis usa la caché compartida igual que el real: con el
    candado entre máquinas, trae lo publicado si existe y si no analiza y publica."""

    analyses = 0

    def __init__(self, config, video: Path, **kwargs) -> None:
        super().__init__(config, video, **kwargs)
        self.sha = hashlib.sha256(video.read_bytes()).hexdigest()
        self.shared = None
        self.analysis_id = None

    def analyze(self) -> None:
        from vfxglow.pipeline import analysis_lock

        key = "clave-de-prueba-" + "0" * 40
        self.analysis_id = cache_id(self.sha, key)
        with analysis_lock(self.run_dir):
            if complete(self.run_dir):
                return
            if self.shared is not None and self.shared.restore(self.run_dir, self.analysis_id):
                return
            SharedPipeline.analyses += 1
            folder = self.run_dir / "analysis"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "header.json").write_text("{}")
            (folder / "motion_brief.json").write_text(make_brief([("fast_swing", "person_0:right_wrist")]).model_dump_json())
            (folder / "tracks.jsonl").write_text("\n".join(FrameRecord(frame=i, time_s=i / 30).model_dump_json() for i in range(30)) + "\n")
            (folder / "events.jsonl").write_text("")
            (folder / "debug_overlay.mp4").write_bytes(b"depuracion")
            if self.shared is not None:
                self.shared.publish(self.run_dir, self.analysis_id, key, self.sha)

    def direct_in_memory(self, brief=None):
        return "guion"

    def window_extras(self, window):
        return None

    def render_preview(self, script, dest, window, events=None, max_side=None, tracks=None) -> int:
        dest.write_bytes(b"vista")
        return window[1] - window[0] + 1


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    FakePipeline.analyses, FakePipeline.gate, FakePipeline.fail = 0, None, False
    SharedPipeline.analyses = 0
    fake_probe.calls = 0
    monkeypatch.setattr(limits, "probe_video", fake_probe)
    monkeypatch.setattr(workqueue, "CANCEL_CHECK_S", 0.01)
    monkeypatch.setenv("VEXORA_AUTH", "on")
    monkeypatch.setenv("VEXORA_MAX_ACTIVE_JOBS", "10")

    def fake_verify(token: str) -> auth.User:
        uid, email, verified = USERS[token]
        return auth.User(uid=uid, email=email, email_verified=verified)

    monkeypatch.setattr(auth, "verify", fake_verify)
    monkeypatch.setattr(server, "upload_store", None)
    monkeypatch.setattr(server, "_previews", None)
    monkeypatch.setattr(server, "_layers", None)


def _until(condition, seconds: float = 10.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("no pasó a tiempo")


def _start(client: TestClient, name: str = "clip.mp4", size: int = len(VIDEO), content_type: str | None = "video/mp4", token: str = "ana"):
    return client.post("/api/uploads", json={"filename": name, "size": size, "content_type": content_type}, headers=as_(token))


# ----- subida directa con archivos locales (la API recibe el PUT) -----


@pytest.fixture()
def local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", CONFIG))
    return TestClient(server.app)


def test_local_direct_upload_puts_to_the_api_completes_and_feeds_a_job(local: TestClient) -> None:
    started = _start(local)
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["status"] == "uploading" and body["upload"]["method"] == "PUT"
    target = body["upload"]
    assert target["url"].startswith(f"/api/uploads/{body['id']}/file?k=") and target["headers"] == {"Content-Type": "video/mp4"}
    # La URL abre sin sesión (la lleva la llave); sin llave o con otra, no.
    assert local.put(target["url"].split("?")[0], content=VIDEO).status_code == 404
    assert local.put(target["url"] + "x", content=VIDEO).status_code == 404
    assert local.put(target["url"], content=VIDEO, headers=target["headers"]).status_code == 204
    done = local.post(f"/api/uploads/{body['id']}/complete", headers=as_("ana"))
    assert done.status_code == 200 and done.json()["status"] == "analyzing" and done.json()["video_seconds"] == 9.4
    assert local.post(f"/api/uploads/{body['id']}/complete", headers=as_("ana")).json()["status"] in ("analyzing", "ready")  # repetir no rompe
    assert wait_upload(local, body["id"])["status"] == "ready"
    job = local.post("/api/jobs", data={"style": "pelea", "upload_id": body["id"]}, headers=as_("ana")).json()
    assert wait_job(local, job["id"])["status"] == "done" and FakePipeline.analyses == 1


def test_declared_size_and_type_are_checked_before_issuing_a_url(local: TestClient) -> None:
    big = _start(local, size=server.MAX_UPLOAD_BYTES + 1)
    assert big.status_code == 413
    assert _start(local, name="clip.avi").status_code == 415
    assert _start(local, size=0).status_code == 422
    assert local.post("/api/uploads", json={"filename": "clip.mp4"}, headers=as_("ana")).status_code == 422
    assert server.jobs().docs.query("uploads") == []  # nada creado


def test_a_put_bigger_than_declared_is_cut_and_a_missing_file_fails_the_upload(local: TestClient) -> None:
    body = _start(local, size=10).json()
    assert local.put(body["upload"]["url"], content=VIDEO, headers=body["upload"]["headers"]).status_code == 413
    assert not Path(server.uploads().peek(body["id"]).video_path).exists()
    missing = local.post(f"/api/uploads/{body['id']}/complete", headers=as_("ana"))
    assert missing.status_code == 409
    shown = local.get(f"/api/uploads/{body['id']}", headers=as_("ana")).json()
    assert shown["status"] == "failed" and "No recibimos" in shown["error"]
    # Sin video, no sirve para un trabajo.
    refused = local.post("/api/jobs", data={"style": "pelea", "upload_id": body["id"]}, headers=as_("ana"))
    assert refused.status_code == 409


def test_an_unreadable_video_fails_at_complete_and_its_file_is_deleted(local: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(path: Path):
        raise HTTPException(422, "El video dura 999 s y el máximo es 180 s. Recórtalo y vuelve a subirlo.")

    monkeypatch.setattr(limits, "probe_video", refuse)
    body = _start(local).json()
    local.put(body["upload"]["url"], content=VIDEO, headers=body["upload"]["headers"])
    response = local.post(f"/api/uploads/{body['id']}/complete", headers=as_("ana"))
    assert response.status_code == 422 and "999 s" in response.json()["detail"]
    shown = local.get(f"/api/uploads/{body['id']}", headers=as_("ana")).json()
    assert shown["status"] == "failed" and "999 s" in shown["error"]
    assert not Path(server.uploads().peek(body["id"]).video_path).exists()


def test_a_job_cannot_use_an_upload_still_uploading(local: TestClient) -> None:
    body = _start(local).json()
    response = local.post("/api/jobs", data={"style": "pelea", "upload_id": body["id"]}, headers=as_("ana"))
    assert response.status_code == 409 and "espera" in response.json()["detail"]
    assert local.get(f"/api/uploads/{body['id']}", headers=as_("ana")).json()["status"] == "uploading"


# ----- subida directa al bucket (GCS de mentira) y tareas en otra máquina -----


@pytest.fixture()
def cloud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """La API (sin trabajadores propios) y una fábrica de "máquinas" trabajadoras, todas sobre los
    mismos documentos y el mismo bucket."""
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", SharedPipeline)
    docs, bucket = MemoryDocStore(), FakeBucket()

    def machine(**kwargs) -> JobStore:
        return JobStore(tmp_path / "api_data", CONFIG, docs=docs, blobs=GcsBlobStore(bucket=bucket, signing=lambda: {}), workers=0, **kwargs)

    def worker() -> JobStore:
        from vfxglow.api.layers import LayerStore
        from vfxglow.api.previews import PreviewStore

        store = machine(worker_kinds=None, lanes=False)
        UploadStore(store, lambda: AVAILABLE)
        PreviewStore(store)
        LayerStore(store)
        return store

    api = machine()
    monkeypatch.setattr(server, "store", api)
    return TestClient(server.app), api, worker, bucket, tmp_path


def test_gcs_direct_upload_signs_a_put_with_type_and_size_and_a_worker_probes_and_analyzes(cloud) -> None:
    client, api, worker, bucket, root = cloud
    body = _start(client, content_type="video/quicktime", name="toma.mov").json()
    target = body["upload"]
    key = f"uploads/{body['id']}/toma.mov"
    assert target["url"].startswith(f"https://storage.example/{key}") and target["method"] == "PUT"
    signed = bucket.signed[-1][1]
    assert signed["method"] == "PUT" and signed["content_type"] == "video/quicktime" and signed["version"] == "v4"
    assert signed["headers"] == {"x-goog-content-length-range": f"0,{len(VIDEO)}"} and signed["expiration"].total_seconds() <= 900
    assert target["headers"] == {"Content-Type": "video/quicktime", "x-goog-content-length-range": f"0,{len(VIDEO)}"}
    # El navegador: otro tipo o más bytes, el bucket lo rechaza; lo firmado, entra.
    assert bucket.put_signed(target["url"], VIDEO, {**target["headers"], "Content-Type": "video/mp4"}) == 403
    assert bucket.put_signed(target["url"], VIDEO + b"x", target["headers"]) == 400
    assert bucket.put_signed(target["url"], VIDEO, target["headers"]) == 200
    done = client.post(f"/api/uploads/{body['id']}/complete", headers=as_("ana")).json()
    assert done["status"] == "analyzing" and done["video_seconds"] is None and done["video_bytes"] == len(VIDEO)
    assert fake_probe.calls == 0  # la API no baja el video para sondearlo: lo hace el trabajador
    assert api.docs.get(tasks.TASKS, body["id"])["status"] == "queued"
    assert workqueue.Worker(worker(), "remoto").step()
    shown = client.get(f"/api/uploads/{body['id']}", headers=as_("ana")).json()
    assert shown["status"] == "ready" and shown["video_seconds"] == 9.4 and fake_probe.calls == 1
    # El trabajo copia el video dentro del bucket (la API no lo tiene) y la subida suelta el suyo.
    remove_local(root / "api_data" / "uploads" / body["id"])
    job = client.post("/api/jobs", data={"style": "pelea", "upload_id": body["id"]}, headers=as_("ana")).json()
    assert bucket.objects[f"uploads/{job['id']}/toma.mov"] == VIDEO and key not in bucket.objects
    assert ("copy", key, f"uploads/{job['id']}/toma.mov") in bucket.calls
    assert api.get(job["id"]).probe is False and job["video_seconds"] == 9.4


def test_gcs_complete_checks_the_real_size_and_existence(cloud) -> None:
    client, api, worker, bucket, root = cloud
    missing = _start(client).json()
    assert client.post(f"/api/uploads/{missing['id']}/complete", headers=as_("ana")).status_code == 409
    assert client.get(f"/api/uploads/{missing['id']}", headers=as_("ana")).json()["status"] == "failed"
    big = _start(client, size=8).json()
    bucket.objects[f"uploads/{big['id']}/clip.mp4"] = VIDEO  # más de lo declarado (sin pasar por la firma)
    assert client.post(f"/api/uploads/{big['id']}/complete", headers=as_("ana")).status_code == 413
    assert f"uploads/{big['id']}/clip.mp4" not in bucket.objects
    assert client.get(f"/api/uploads/{big['id']}", headers=as_("ana")).json()["status"] == "failed"


def test_a_worker_probe_that_fails_marks_the_upload_failed_and_deletes_the_object(cloud, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api, worker, bucket, root = cloud
    body = _start(client).json()
    bucket.put_signed(body["upload"]["url"], VIDEO, body["upload"]["headers"])
    client.post(f"/api/uploads/{body['id']}/complete", headers=as_("ana"))
    remove_local(root / "api_data" / "uploads") if (root / "api_data" / "uploads").exists() else None

    def refuse(path: Path):
        raise HTTPException(422, "No pudimos leer el video. Expórtalo de nuevo en MP4 (H.264) y vuelve a subirlo.")

    monkeypatch.setattr(limits, "probe_video", refuse)
    assert workqueue.Worker(worker(), "remoto").step()
    shown = client.get(f"/api/uploads/{body['id']}", headers=as_("ana")).json()
    assert shown["status"] == "failed" and "No pudimos leer" in shown["error"]
    assert not any(k.startswith(f"uploads/{body['id']}/") for k in bucket.objects)
    assert api.docs.get(tasks.TASKS, body["id"])["status"] == "failed"
    assert SharedPipeline.analyses == 0


def test_a_job_from_an_unprobed_upload_is_probed_by_its_worker(cloud, monkeypatch: pytest.MonkeyPatch) -> None:
    client, api, worker, bucket, root = cloud
    body = _start(client).json()
    bucket.put_signed(body["upload"]["url"], VIDEO, body["upload"]["headers"])
    client.post(f"/api/uploads/{body['id']}/complete", headers=as_("ana"))
    job = client.post("/api/jobs", data={"style": "pelea", "upload_id": body["id"]}, headers=as_("ana")).json()
    assert api.get(job["id"]).probe is True

    def refuse(path: Path):
        raise HTTPException(422, "El video dura 999 s y el máximo es 180 s. Recórtalo y vuelve a subirlo.")

    monkeypatch.setattr(limits, "probe_video", refuse)
    side = worker()
    while workqueue.Worker(side, "remoto").step():
        pass
    failed = api.get(job["id"])
    assert failed.status == "failed" and failed.error_code == "invalid_video" and "999 s" in failed.error


def test_abandoned_direct_uploads_are_cleaned(cloud) -> None:
    client, api, worker, bucket, root = cloud
    body = _start(client).json()
    bucket.put_signed(body["upload"]["url"], VIDEO, body["upload"]["headers"])  # subió, pero nunca completó
    fresh = _start(client, name="otro.mp4").json()
    store = server.uploads()
    store._set(body["id"], created=time.time() - 2 * 3600)
    assert store.expire() == 1
    assert store.peek(body["id"]) is None and not any(k.startswith(f"uploads/{body['id']}/") for k in bucket.objects)
    assert store.peek(fresh["id"]).status == "uploading"


# ----- caché del análisis compartida -----


def test_studio_preview_and_people_read_the_analysis_from_the_bucket(cloud) -> None:
    """La subida se analiza en un trabajador; la API (otra máquina, sin runs/) trae el brief del
    bucket para la vista previa del Estudio y las pistas para /people. Un trabajador frío no vuelve
    a analizar: trae lo publicado."""
    client, api, worker, bucket, root = cloud
    upload_id = client.post("/api/uploads", files={"video": ("clip.mp4", io.BytesIO(VIDEO), "video/mp4")}, headers=as_("ana")).json()["id"]
    assert bucket.objects[f"uploads/{upload_id}/clip.mp4"] == VIDEO  # publicado para el trabajador
    assert workqueue.Worker(worker(), "w1").step()
    item = server.uploads().peek(upload_id)
    assert item.status == "ready" and item.analysis_key and SharedPipeline.analyses == 1
    published = [k for k in bucket.objects if k.startswith("analysis/")]
    assert any(k.endswith("/index.json") for k in published) and any(k.endswith("/tracks.jsonl") for k in published)
    assert not any(k.endswith("debug_overlay.mp4") for k in published)
    _drop_runs(root)  # la API es otra máquina
    created = client.post(f"/api/uploads/{upload_id}/preview", json={"style": "avatar"}, headers=as_("ana"))
    assert created.status_code == 202, created.text
    assert (Path(item.run_dir) / "analysis" / "motion_brief.json").exists()
    _drop_runs(root)
    assert workqueue.Worker(worker(), "w2").step()  # la vista previa, en un trabajador frío
    preview = client.get(f"/api/uploads/{upload_id}/preview/{created.json()['preview_id']}", headers=as_("ana")).json()
    assert preview["status"] == "ready"
    remove_local(root / "api_data" / "previews")
    media = client.get(preview["url"], follow_redirects=False)
    assert media.status_code == 307 and media.headers["location"].startswith("https://storage.example/previews/")
    # El trabajo, en otro trabajador frío: no vuelve a analizar.
    job = client.post("/api/jobs", data={"style": "pelea", "upload_id": upload_id}, headers=as_("ana")).json()
    _drop_runs(root)
    assert workqueue.Worker(worker(), "w3").step()
    done = api.get(job["id"])
    assert done.status == "done" and done.analysis_key == item.analysis_key and SharedPipeline.analyses == 1
    _drop_runs(root)
    people = client.get(f"/api/jobs/{job['id']}/people", headers=as_("ana"))
    assert people.status_code == 200 and (Path(done.run_dir) / "analysis" / "tracks.jsonl").exists()


def _drop_runs(root: Path) -> None:
    """Otra máquina: sin la carpeta runs/ (la del Pipeline de mentira cuelga de api_data/)."""
    for runs in (root / "runs", root / "api_data" / "runs"):
        if runs.exists():
            remove_local(runs)


def _real_pipeline(tmp: Path, sha: str, shared):
    from vfxglow import pipeline as pl
    from vfxglow.config import load_config
    from vfxglow.io.store import Manifest

    p = pl.Pipeline.__new__(pl.Pipeline)
    p.config, p.force, p.video, p.device = load_config(CONFIG), False, Path("v.mp4"), "cpu"
    p.run_dir, p.manifest_path = tmp / "run", tmp / "run" / "manifest.json"
    p.run_dir.mkdir(parents=True, exist_ok=True)
    p.manifest = Manifest(video_path="v.mp4", video_sha256=sha, device="cpu")
    p.shared, p.analysis_id = shared, None
    return p


def test_the_real_pipeline_publishes_once_and_a_cold_machine_restores(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow import pipeline as pl
    from vfxglow.io.store import load_manifest

    analyzed: list[str] = []

    def fake_analysis(video, run_dir, config, device) -> None:
        analyzed.append(str(run_dir))
        time.sleep(0.2)
        folder = run_dir / "analysis"
        (folder / "scene_cache").mkdir(parents=True, exist_ok=True)
        for name in ("header.json", "motion_brief.json", "events.jsonl", "appearance.json"):
            (folder / name).write_text(name)
        (folder / "tracks.jsonl").write_text("pistas")
        (folder / "debug_overlay.mp4").write_bytes(b"x")
        (folder / "scene_cache" / "q.json").write_text("{}")

    monkeypatch.setattr(pl, "analyze_video", fake_analysis)
    docs, bucket = MemoryDocStore(), FakeBucket()
    shared = AnalysisCache(docs, GcsBlobStore(bucket=bucket, signing=lambda: {}), poll_s=0.01)
    sha = "ab" * 32
    # Dos máquinas a la vez con el mismo video: una analiza, la otra espera el candado y trae.
    first, second = _real_pipeline(tmp_path / "a", sha, shared), _real_pipeline(tmp_path / "b", sha, shared)
    threads = [threading.Thread(target=p.analyze) for p in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert len(analyzed) == 1
    for p in (first, second):
        assert (p.run_dir / "analysis" / "tracks.jsonl").read_text() == "pistas"
        assert load_manifest(p.manifest_path).stages["analyze"] == p._analysis_key()
        assert p.analysis_id == cache_id(sha, p._analysis_key())
    names = {k.rsplit("/", 1)[-1] for k in bucket.objects}
    assert {"index.json", "tracks.jsonl", "header.json", "appearance.json"} <= names and not {"debug_overlay.mp4", "q.json"} & names
    assert docs.query("analysis_locks") == []  # el candado se suelta
    # Una tercera, fría y más tarde: restore_analysis sin analizar.
    third = _real_pipeline(tmp_path / "c", sha, shared)
    assert third.restore_analysis() and len(analyzed) == 1
    # Sin almacén compartido (archivos locales), nada se publica ni se trae.
    assert AnalysisCache(docs, LocalBlobStore(tmp_path)).active is False


def test_an_analysis_lock_whose_holder_died_is_taken_over(tmp_path: Path) -> None:
    docs = MemoryDocStore()
    now = [1000.0]
    shared = AnalysisCache(docs, GcsBlobStore(bucket=FakeBucket(), signing=lambda: {}), clock=lambda: now[0], lease_s=30, poll_s=0.01)
    docs.set("analysis_locks", "e-1", {"id": "e-1", "holder": "muerto", "until": now[0] + 30})
    entered = threading.Event()

    def take() -> None:
        with shared.lock("e-1"):
            entered.set()

    thread = threading.Thread(target=take)
    thread.start()
    time.sleep(0.1)
    assert not entered.is_set()  # su turno sigue vigente
    now[0] += 31
    thread.join(5)
    assert entered.is_set()


# ----- tareas en trabajadores de otros procesos -----


def test_preview_tasks_one_running_per_user_across_workers(tmp_path: Path) -> None:
    docs = MemoryDocStore()
    gate, seen = threading.Event(), []

    def worker_store() -> JobStore:
        store = JobStore(tmp_path / "api_data", CONFIG, docs=docs, workers=0, worker_kinds=None, lanes=False)

        def run(doc, flag):
            seen.append(doc["id"])
            gate.wait(5)
            return {"status": "done"}

        store.register(tasks.PREVIEW, TaskHandler(run))
        return store

    api = JobStore(tmp_path / "api_data", CONFIG, docs=docs, workers=0)
    for task_id, owner, created in (("ana-1", "ana", 1.0), ("ana-2", "ana", 2.0), ("beto-1", "beto", 3.0)):
        api.enqueue_task({**tasks.new_task(task_id, tasks.PREVIEW, owner, "j1"), "created": created})
    first, second = worker_store(), worker_store()
    busy = threading.Thread(target=workqueue.Worker(first, "w1").step)
    busy.start()
    _until(lambda: seen == ["ana-1"])
    assert second.claim("w2")["id"] == "beto-1"  # la segunda de ana espera a la primera
    assert second.claim("w3") is None
    gate.set()
    busy.join(5)
    assert second.claim("w2")["id"] == "ana-2"


def test_a_task_whose_worker_dies_is_retried_then_fails_the_upload(tmp_path: Path) -> None:
    class Clock:
        now = 1_000.0

        def __call__(self) -> float:
            return self.now

    clock = Clock()
    store = JobStore(tmp_path / "api_data", CONFIG, docs=MemoryDocStore(), workers=0, clock=clock, lease_s=30)
    uploads = UploadStore(store, lambda: AVAILABLE)
    item = uploads.create("clip.mp4", io.BytesIO(VIDEO), "ana", None, fake_probe)
    for attempt in (1, 2, 3):
        claimed = store.claim(f"muerto-{attempt}", (tasks.UPLOAD,))
        assert claimed["id"] == item.id and claimed["attempts"] == attempt
        clock.now += 31
        expected = "requeued" if attempt < 3 else "failed"
        assert store.reap_expired() == [(item.id, expected)]
        assert uploads.peek(item.id).status == ("analyzing" if attempt < 3 else "failed")
    assert uploads.peek(item.id).error_code == "interrupted"


def test_layers_are_drawn_by_a_worker_in_another_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_layers_api import FPS, FRAMES, LayersPipeline

    from vfxglow.api.layers import LayerStore

    LayersPipeline.fail, LayersPipeline.calls = False, []
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", LayersPipeline)
    monkeypatch.setattr(server, "_video_timing", lambda job: (FPS, FRAMES))
    monkeypatch.setenv("VEXORA_AUTH", "off")
    docs = MemoryDocStore()
    api = JobStore(tmp_path / "api_data", CONFIG, docs=docs, workers=0)
    monkeypatch.setattr(server, "store", api)
    side = JobStore(tmp_path / "api_data", CONFIG, docs=docs, workers=0, worker_kinds=None, lanes=False)
    LayerStore(side)
    client = TestClient(server.app)
    job = client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()
    assert workqueue.Worker(side, "w").step() and api.get(job["id"]).status == "done"
    assert client.post(f"/api/jobs/{job['id']}/layers").json()["status"] == "rendering"
    assert client.post(f"/api/jobs/{job['id']}/layers").json()["status"] == "rendering"  # no se encola dos veces
    assert len(docs.query(tasks.TASKS, where={"kind": tasks.LAYERS})) == 1
    assert workqueue.Worker(side, "w").step()
    view = client.get(f"/api/jobs/{job['id']}/layers").json()
    assert view["status"] == "ready" and view["layout"]["frames"] == FRAMES and len(LayersPipeline.calls) == 1


# ----- despertar al Cloud Run Job y salir por inactividad -----


class FakeJobs:
    """El cliente de Cloud Run (run_v2.JobsClient) de mentira."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.fail = fail

    def run_job(self, name: str):
        if self.fail:
            raise RuntimeError("permiso denegado")
        self.calls.append(name)
        return object()


JOB_NAME = "projects/p/locations/us-central1/jobs/vexora-worker"


def _queued(docs, n: int = 1) -> None:
    for i in range(n):
        docs.set("jobs", f"j{i}", {"id": f"j{i}", "status": "queued", "worker": None, "priority": 0, "created": float(i)})


def test_the_waker_triggers_once_when_idle_and_not_when_a_worker_is_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(wakeup.MAX_PARALLEL_ENV, raising=False)
    docs, jobs, now = MemoryDocStore(), FakeJobs(), [10_000.0]
    waker = wakeup.Waker(docs, lambda: jobs, clock=lambda: now[0], job_name=JOB_NAME)
    _queued(docs)
    assert waker.poke() == 1 and jobs.calls == [JOB_NAME]
    assert waker.poke() == 0  # dentro de la ventana: la ejecución está arrancando
    now[0] += wakeup.WINDOW_S + 1
    workqueue.beat(docs, "vivo", None, now[0])
    assert waker.poke() == 0  # hay un trabajador vivo
    now[0] += workqueue.ALIVE_S + 1
    assert waker.poke() == 1 and len(jobs.calls) == 2  # su latido venció
    assert wakeup.Waker(docs, lambda: jobs, job_name="").poke() == 0  # sin VEXORA_WORKER_JOB, nada


def test_the_waker_scales_with_the_queue_up_to_the_max_and_never_breaks_the_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(wakeup.MAX_PARALLEL_ENV, "3")
    docs, jobs, now = MemoryDocStore(), FakeJobs(), [10_000.0]
    _queued(docs, 5)
    waker = wakeup.Waker(docs, lambda: jobs, clock=lambda: now[0], job_name=JOB_NAME)
    assert waker.poke() == 3 and waker.poke() == 0
    broken = wakeup.Waker(MemoryDocStore(), lambda: FakeJobs(fail=True), job_name=JOB_NAME)
    _queued(broken.docs)
    assert broken.poke() == 0  # el fallo queda en el registro, no en la petición


def test_enqueueing_a_job_wakes_the_cloud_run_job(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    docs, jobs = MemoryDocStore(), FakeJobs()
    store = JobStore(tmp_path / "api_data", CONFIG, docs=docs, workers=0)
    store.waker = wakeup.Waker(docs, lambda: jobs, job_name=JOB_NAME)
    store.create("clip.mp4", io.BytesIO(VIDEO), "catalog", "pelea", None)
    _until(lambda: jobs.calls == [JOB_NAME])
    store.enqueue_task(tasks.new_task("t1", tasks.LAYERS, "ana", "j"))
    time.sleep(0.2)
    assert jobs.calls == [JOB_NAME]  # el segundo encolado, dentro de la ventana, no lanza otra


def test_idle_worker_exits_after_the_configured_time_and_never_with_a_lease(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_queue import FakePipeline as GatedPipeline

    monkeypatch.setattr("vfxglow.pipeline.Pipeline", GatedPipeline)
    GatedPipeline.gate = threading.Event()
    docs = MemoryDocStore()
    store = JobStore(tmp_path / "api_data", CONFIG, docs=docs, workers=0)
    job = store.create("clip.mp4", io.BytesIO(VIDEO), "catalog", "pelea", None)
    ticks = [0.0]

    def clock() -> float:  # cada consulta adelanta 25 s: sin trabajo, sale enseguida
        ticks[0] += 25.0
        return ticks[0]

    worker = workqueue.Worker(store, "w-idle", poll_s=0.001, idle_exit_s=60, clock=clock)
    worker.start()
    _until(lambda: store.get(job.id).status == "running")
    assert workqueue.alive_workers(docs, time.time()) == 1  # su latido
    time.sleep(0.3)
    assert worker.is_alive()  # procesando: el reloj avanza, pero no sale con el turno en la mano
    GatedPipeline.gate.set()
    worker.join(5)
    assert not worker.is_alive() and worker.idle_exited
    done = store.get(job.id)
    assert done.status == "done" and done.lease_until is None
    assert workqueue.alive_workers(docs, time.time()) == 0  # borró su latido al salir
    GatedPipeline.gate = None


def test_a_worker_process_registers_every_task_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow import worker

    monkeypatch.setenv("VEXORA_WORKER_KINDS", "preview, upload")
    assert worker.kinds_from_env() == ("preview", "upload")
    (tmp_path / "configs").symlink_to(CONFIG.parent)
    store = worker.open_store(tmp_path, count=0)
    assert set(store.handlers) == {tasks.PREVIEW, tasks.UPLOAD, tasks.LAYERS} and store.lanes == []
    assert json.loads(json.dumps(tasks.new_task("x", tasks.UPLOAD, "a", "x")))["priority"] == tasks.PRIORITY[tasks.UPLOAD]
