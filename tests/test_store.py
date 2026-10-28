"""Almacén de documentos y de archivos (store/): el mismo contrato en memoria, JSON y Firestore
(cliente de mentira), la lectura del jobs.json/uploads.json de siempre y los archivos local/GCS."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from cloud_fakes import FakeBucket, FakeFirestore, field_filter, transactional
from vfxglow.store import DELETE, GcsBlobStore, JsonDocStore, LocalBlobStore, MemoryDocStore, open_blobs, open_docs
from vfxglow.store.firestore import FirestoreDocStore

CONFIG = Path(__file__).resolve().parents[1] / "configs" / "default.yaml"


@pytest.fixture(params=["memory", "json", "firestore"])
def docs(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "memory":
        return MemoryDocStore()
    if request.param == "json":
        return JsonDocStore(tmp_path / "data")
    return FirestoreDocStore(client=FakeFirestore(), transactional=transactional, field_filter=field_filter)


# ----- contrato de DocStore -----


def test_get_set_update_delete(docs) -> None:
    assert docs.get("jobs", "a") is None
    docs.set("jobs", "a", {"id": "a", "status": "queued", "n": 1, "nested": {"x": [1, 2]}})
    got = docs.get("jobs", "a")
    assert got == {"id": "a", "status": "queued", "n": 1, "nested": {"x": [1, 2]}}
    got["n"] = 99  # lo devuelto es una copia
    assert docs.get("jobs", "a")["n"] == 1
    assert docs.update("jobs", "a", {"n": 2}) is True
    assert docs.get("jobs", "a")["status"] == "queued" and docs.get("jobs", "a")["n"] == 2
    assert docs.update("jobs", "nada", {"n": 2}) is False
    docs.delete("jobs", "a")
    docs.delete("jobs", "a")  # borrar dos veces no falla
    assert docs.get("jobs", "a") is None


def test_update_with_a_precondition(docs) -> None:
    docs.set("jobs", "a", {"id": "a", "worker": "w1", "lease_until": 10})
    assert docs.update("jobs", "a", {"lease_until": 20}, when={"worker": "w2"}) is False
    assert docs.update("jobs", "a", {"lease_until": 20}, when={"worker": "w1"}) is True
    assert docs.get("jobs", "a")["lease_until"] == 20


def test_query_filters_orders_and_limits(docs) -> None:
    rows = [("a", "queued", 0, 3.0), ("b", "queued", 5, 4.0), ("c", "done", 9, 1.0), ("d", "queued", 0, 1.0), ("e", "queued", 5, 2.0)]
    for doc_id, status, priority, created in rows:
        docs.set("jobs", doc_id, {"id": doc_id, "status": status, "priority": priority, "created": created, "worker": None})
    queued = docs.query("jobs", where={"status": "queued", "worker": None}, order_by=[("priority", True), ("created", False)])
    assert [d["id"] for d in queued] == ["e", "b", "d", "a"]
    assert [d["id"] for d in docs.query("jobs", where={"status": "queued"}, order_by=[("priority", True), ("created", False)], limit=2)] == ["e", "b"]
    assert {d["id"] for d in docs.query("jobs")} == {"a", "b", "c", "d", "e"}
    assert docs.query("otra") == []


def test_transact_replaces_deletes_or_leaves_alone(docs) -> None:
    docs.set("jobs", "a", {"id": "a", "n": 1})
    assert docs.transact("jobs", "a", lambda cur: {**cur, "n": cur["n"] + 1})["n"] == 2
    assert docs.transact("jobs", "a", lambda cur: None) is None
    assert docs.get("jobs", "a")["n"] == 2
    assert docs.transact("jobs", "nuevo", lambda cur: {"id": "nuevo"} if cur is None else None) == {"id": "nuevo"}
    assert docs.transact("jobs", "a", lambda cur: DELETE) is DELETE
    assert docs.get("jobs", "a") is None


def test_transactions_do_not_lose_concurrent_increments(docs) -> None:
    docs.set("jobs", "a", {"id": "a", "n": 0})

    def bump() -> None:
        for _ in range(25):
            docs.transact("jobs", "a", lambda cur: {**cur, "n": cur["n"] + 1})

    threads = [threading.Thread(target=bump) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert docs.get("jobs", "a")["n"] == 100


def test_firestore_only_matches_null_when_the_field_is_stored() -> None:
    """Por eso los trabajos se guardan completos (con `worker: null`): la cola filtra por él."""
    store = FirestoreDocStore(client=FakeFirestore(), transactional=transactional, field_filter=field_filter)
    store.set("jobs", "a", {"id": "a", "worker": None})
    store.set("jobs", "b", {"id": "b"})
    assert [d["id"] for d in store.query("jobs", where={"worker": None})] == ["a"]


# ----- JSON: el formato de siempre -----


def _legacy_job(job_id: str, status: str, created: float) -> dict:
    """Un trabajo como lo escribía la versión anterior (sin campos de cola)."""
    return {
        "id": job_id, "created": created, "filename": "clip.mp4", "video_path": f"/x/uploads/{job_id}/clip.mp4",
        "style_kind": "catalog", "style": "pelea", "seed": None, "take": 0, "status": status, "stage": "done",
        "progress": 1.0, "message": "Listo", "log": [], "owner": None, "metrics": {"total_ms": 1000}, "activity": [],
    }


def test_the_existing_json_files_are_read_as_they_are_and_backed_up(tmp_path: Path) -> None:
    from vfxglow.api.jobs import JobStore
    from vfxglow.api.uploads import UploadStore

    root = tmp_path / "api_data"
    root.mkdir()
    legacy = [_legacy_job("j1", "done", 1.0), _legacy_job("j2", "failed", 2.0), _legacy_job("j3", "running", 3.0), _legacy_job("j4", "queued", 4.0)]
    (root / "jobs.json").write_text(json.dumps(legacy), encoding="utf-8")
    original = (root / "jobs.json").read_bytes()
    upload = {"id": "u_1", "owner": "local", "created": 9e12, "filename": "a.mp4", "video_path": str(root / "uploads/u_1/a.mp4"), "status": "analyzing"}
    (root / "uploads.json").write_text(json.dumps([upload]), encoding="utf-8")

    store = JobStore(root, CONFIG, workers=0)
    jobs = {job.id: job for job in store.list()}
    assert set(jobs) == {"j1", "j2", "j3", "j4"}  # ninguno se pierde
    assert jobs["j1"].status == "done" and jobs["j1"].metrics == {"total_ms": 1000} and jobs["j1"].attempts == 0
    assert jobs["j3"].status == "failed" and jobs["j3"].error_code == "interrupted"  # quedó a medias al reiniciar
    assert jobs["j4"].status == "queued"  # la cola ahora es persistente: se procesará
    assert (root / "jobs.json.pre-store.bak").read_bytes() == original
    saved = json.loads((root / "jobs.json").read_text(encoding="utf-8"))
    assert isinstance(saved, list) and [d["id"] for d in saved] == ["j1", "j2", "j3", "j4"]  # mismo formato y orden

    uploads = UploadStore(store, lambda: ["pelea"])
    assert uploads.peek("u_1").status == "failed" and uploads.peek("u_1").error_code == "interrupted"
    assert (root / "uploads.json.pre-store.bak").exists()


def test_the_real_jobs_file_loads_without_losing_a_job(tmp_path: Path) -> None:
    """Con el jobs.json de esta máquina (si existe): todos los trabajos se leen como Job."""
    from vfxglow.api.jobs import Job

    real = Path(__file__).resolve().parents[1] / "api_data" / "jobs.json"
    if not real.exists():
        pytest.skip("sin api_data/jobs.json local")
    copy = tmp_path / "jobs.json"
    copy.write_bytes(real.read_bytes())
    raw = json.loads(copy.read_text(encoding="utf-8"))
    loaded = [Job.model_validate(doc) for doc in JsonDocStore(tmp_path).query("jobs")]
    assert sorted(job.id for job in loaded) == sorted(doc["id"] for doc in raw)


def test_a_damaged_json_file_is_never_overwritten(tmp_path: Path) -> None:
    (tmp_path / "jobs.json").write_text("[{roto", encoding="utf-8")
    store = JsonDocStore(tmp_path)
    with pytest.raises(ValueError):
        store.set("jobs", "a", {"id": "a"})
    assert (tmp_path / "jobs.json").read_text(encoding="utf-8") == "[{roto"


def test_two_json_stores_on_the_same_folder_see_each_other(tmp_path: Path) -> None:
    """Como la API y `vexora-worker` en la misma máquina: lo que uno escribe, el otro lo relee."""
    first, second = JsonDocStore(tmp_path), JsonDocStore(tmp_path)
    first.set("jobs", "a", {"id": "a", "n": 1})
    assert second.get("jobs", "a") == {"id": "a", "n": 1}
    second.update("jobs", "a", {"n": 2})
    assert first.get("jobs", "a")["n"] == 2


def test_backends_are_chosen_by_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VEXORA_STORE", raising=False)
    monkeypatch.delenv("VEXORA_BLOBS", raising=False)
    assert isinstance(open_docs(tmp_path), JsonDocStore) and isinstance(open_blobs(tmp_path), LocalBlobStore)
    monkeypatch.setenv("VEXORA_STORE", "otra")
    with pytest.raises(ValueError):
        open_docs(tmp_path)
    monkeypatch.setenv("VEXORA_BLOBS", "gcs")
    monkeypatch.delenv("VEXORA_BUCKET", raising=False)
    with pytest.raises((RuntimeError, ImportError)):
        open_blobs(tmp_path)


# ----- archivos -----


def test_local_blobs_keep_the_same_paths(tmp_path: Path) -> None:
    blobs = LocalBlobStore(tmp_path)
    out = tmp_path / "outputs" / "abc.mp4"
    out.parent.mkdir()
    out.write_bytes(b"video")
    blobs.put("outputs/abc.mp4", out)  # el mismo archivo: no hace nada
    assert out.read_bytes() == b"video" and blobs.exists("outputs/abc.mp4")
    assert blobs.fetch("outputs/abc.mp4", out) is True
    other = tmp_path / "copia.mp4"
    assert blobs.fetch("outputs/abc.mp4", other) and other.read_bytes() == b"video"
    (tmp_path / "outputs" / "abc.script.json").write_text("{}")
    (tmp_path / "outputs" / "abcd.mp4").write_text("otro")
    blobs.delete_prefix("outputs/abc.")
    assert not blobs.exists("outputs/abc.mp4") and not blobs.exists("outputs/abc.script.json") and blobs.exists("outputs/abcd.mp4")
    (tmp_path / "uploads" / "x").mkdir(parents=True)
    (tmp_path / "uploads" / "x" / "v.mp4").write_text("v")
    blobs.delete_prefix("uploads/x/")
    assert not (tmp_path / "uploads" / "x").exists()
    assert blobs.fetch("outputs/nada.mp4", tmp_path / "n.mp4") is False and blobs.signed_url("outputs/abcd.mp4") is None
    with pytest.raises(ValueError):
        blobs.path("../fuera.txt")


def test_gcs_blobs_upload_download_cache_and_sign(tmp_path: Path) -> None:
    bucket = FakeBucket()
    now = [100.0]
    blobs = GcsBlobStore(bucket=bucket, signing=lambda: {"service_account_email": "sa@x", "access_token": "t"}, clock=lambda: now[0])
    source = tmp_path / "a.mp4"
    source.write_bytes(b"hola")
    blobs.put("outputs/a.mp4", source)
    assert bucket.objects["outputs/a.mp4"] == b"hola" and ("upload", "outputs/a.mp4", "video/mp4") in bucket.calls
    target = tmp_path / "otra" / "a.mp4"
    assert blobs.fetch("outputs/a.mp4", target) and target.read_bytes() == b"hola"
    assert blobs.fetch("outputs/nada.mp4", tmp_path / "nada.mp4") is False and not (tmp_path / "nada.mp4").exists()
    # Lo que existe se recuerda; lo que no, solo unos segundos (el trabajador puede subirlo ya).
    bucket.calls.clear()
    assert blobs.exists("outputs/a.mp4") and blobs.exists("outputs/a.mp4") and bucket.calls == []
    assert not blobs.exists("outputs/b.mp4")
    bucket.objects["outputs/b.mp4"] = b"b"
    assert not blobs.exists("outputs/b.mp4")
    now[0] += 11
    assert blobs.exists("outputs/b.mp4")
    url = blobs.signed_url("outputs/a.mp4", ttl_s=60, filename="mi video.mp4", media_type="video/mp4")
    name, kwargs = bucket.signed[-1]
    assert url.startswith("https://") and name == "outputs/a.mp4"
    assert kwargs["version"] == "v4" and kwargs["expiration"].total_seconds() == 60 and kwargs["service_account_email"] == "sa@x"
    assert kwargs["response_disposition"] == 'attachment; filename="mi video.mp4"'
    bucket.objects["outputs/a.script.json"] = b"{}"
    blobs.delete_prefix("outputs/a.")
    assert set(bucket.objects) == {"outputs/b.mp4"} and not blobs.exists("outputs/a.mp4")
    blobs.delete("outputs/nada.mp4")  # borrar lo que no está no falla
