"""Prueba de humo contra Firestore y Firebase Storage de verdad. No corre en la suite normal.

    VEXORA_LIVE_TESTS=1 GOOGLE_APPLICATION_CREDENTIALS=/ruta/llave.json \\
    VEXORA_FIREBASE_PROJECT=vexora-dev VEXORA_BUCKET=vexora-dev.firebasestorage.app \\
    .venv/bin/python -m pytest -q tests/test_cloud_live.py

Todo va en un espacio aparte (colecciones `_smoke_<azar>_*` y objetos `_smoke_<azar>/...`) y se
borra al final, pase lo que pase.
"""

from __future__ import annotations

import os
import ssl
import time
import urllib.request
import uuid
from pathlib import Path

import certifi
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("VEXORA_LIVE_TESTS") != "1", reason="solo con VEXORA_LIVE_TESTS=1 (toca la nube)")


@pytest.fixture()
def tag() -> str:
    return f"_smoke_{uuid.uuid4().hex[:8]}"


@pytest.fixture()
def docs(tag: str):
    from vfxglow.store.firestore import FirestoreDocStore

    store = FirestoreDocStore(prefix=f"{tag}_")
    yield store
    for doc in store.query("jobs"):
        store.delete("jobs", doc["id"])


def test_firestore_documents_queries_and_the_claim_transaction(docs) -> None:
    from vfxglow.api import workqueue

    now = time.time()
    for job_id, priority, created in (("a", 0, now - 3), ("b", 5, now - 1), ("c", 0, now - 5)):
        docs.set("jobs", job_id, {"id": job_id, "status": "queued", "worker": None, "priority": priority, "created": created, "attempts": 0})
    assert docs.get("jobs", "a")["priority"] == 0
    assert docs.update("jobs", "a", {"note": "x"}) and docs.get("jobs", "a")["note"] == "x"
    assert docs.update("jobs", "nada", {"note": "x"}) is False
    assert {d["id"] for d in docs.query("jobs", where={"status": "queued", "worker": None})} == {"a", "b", "c"}
    # Compare-and-set en transacción (no necesita índice): el segundo intento ve que ya lo tomaron.
    take = lambda worker: lambda cur: {**cur, "worker": worker} if cur and cur.get("worker") is None else None  # noqa: E731
    assert docs.transact("jobs", "a", take("w1"))["worker"] == "w1"
    assert docs.transact("jobs", "a", take("w2")) is None and docs.get("jobs", "a")["worker"] == "w1"
    assert docs.update("jobs", "a", {"worker": None}, when={"worker": "w1"})
    try:
        order = [d["id"] for d in docs.query("jobs", where={"status": "queued", "worker": None}, order_by=[("priority", True), ("created", False)])]
    except Exception as error:  # FailedPrecondition: falta el índice compuesto
        pytest.skip(f"Falta el índice compuesto de la cola (firestore.indexes.json): {str(error)[:300]}")
    assert order == ["b", "c", "a"]
    first = workqueue.claim(docs, "w1", now, 60)
    second = workqueue.claim(docs, "w2", now, 60)
    assert (first["id"], first["worker"], first["attempts"]) == ("b", "w1", 1) and second["id"] == "c"
    assert workqueue.heartbeat(docs, "b", "w1", now + 10, 60) and not workqueue.heartbeat(docs, "b", "w2", now + 10, 60)
    assert sorted(workqueue.reap(docs, now + 1000, {"status": "failed"})) == [("b", "requeued"), ("c", "requeued")]
    assert docs.get("jobs", "b")["status"] == "queued" and docs.get("jobs", "b")["worker"] is None


def test_storage_put_exists_signed_url_and_delete(tag: str, tmp_path: Path) -> None:
    from vfxglow.store.blobs import GcsBlobStore

    blobs = GcsBlobStore()
    source = tmp_path / "hola.txt"
    source.write_text("hola vexora")
    key = f"{tag}/outputs/hola.txt"
    try:
        blobs.put(key, source)
        assert blobs.exists(key)
        target = tmp_path / "copia.txt"
        assert blobs.fetch(key, target) and target.read_text() == "hola vexora"
        url = blobs.signed_url(key, ttl_s=120, media_type="text/plain")
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(url, timeout=30, context=context) as response:  # noqa: S310 (URL firmada de GCS)
            assert response.read() == b"hola vexora"
    finally:
        blobs.delete_prefix(f"{tag}/")
    assert not GcsBlobStore().exists(key)
