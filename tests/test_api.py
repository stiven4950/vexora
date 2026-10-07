"""API: estilos, ciclo de vida de un trabajo, progreso y variaciones (pipeline simulado)."""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vfxglow.api import server  # noqa: E402
from vfxglow.api.jobs import JobStore  # noqa: E402


class FakePipeline:
    def __init__(self, config, video: Path, **kwargs) -> None:
        self.kwargs = kwargs
        self.run_dir = video.parent / "run"

    def run(self) -> Path:
        log = logging.getLogger("vfxglow.analysis")
        log.info("Analizando %s en cpu", "x")
        log.info("Analizados 25/50 fotogramas")
        logging.getLogger("vfxglow").info("Guion pelea con 3 efectos")
        logging.getLogger("vfxglow").info("Compuestos 50/50 fotogramas")
        if self.kwargs.get("catalog") == "roto":
            raise RuntimeError("falló a propósito")
        out = self.run_dir / "output" / "pelea.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 64)
        return out


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    logging.getLogger().setLevel(logging.INFO)
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", server.CONFIG))
    return TestClient(server.app)


def _wait(client: TestClient, job_id: str) -> dict:
    for _ in range(100):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("el trabajo no terminó")


def test_styles_list_catalogs_and_presets(client: TestClient) -> None:
    styles = client.get("/api/styles").json()
    names = {(s["kind"], s["name"]) for s in styles}
    assert ("catalog", "pelea") in names and ("preset", "face_neon") in names
    pelea = next(s for s in styles if s["name"] == "pelea")
    assert pelea["description"] and len(pelea["palette"]) >= 2 and "fast_swing" in pelea["actions"]


def test_job_lifecycle_progress_output_and_variation(client: TestClient) -> None:
    response = client.post("/api/jobs", files={"video": ("mi clip.mp4", io.BytesIO(b"fake"), "video/mp4")}, data={"style": "pelea", "seed": "7"})
    assert response.status_code == 201
    job = _wait(client, response.json()["id"])
    assert job["status"] == "done" and job["progress"] == 1.0 and job["output_url"]
    assert any("Analizados 25/50" in line for line in job["log"])
    assert client.get(job["output_url"]).content == b"\x00" * 64
    assert "attachment" in client.get(job["output_url"] + "?download=true").headers["content-disposition"]
    variation = client.post(f"/api/jobs/{job['id']}/variations", json={"style": "pelea", "seed": 9}).json()
    assert variation["parent"] == job["id"] and variation["seed"] == 9
    assert _wait(client, variation["id"])["status"] == "done"
    assert len(client.get("/api/jobs").json()) == 2
    assert client.delete(f"/api/jobs/{variation['id']}").status_code == 204


def test_rejects_bad_input_and_reports_failures(client: TestClient) -> None:
    bad_type = client.post("/api/jobs", files={"video": ("a.txt", io.BytesIO(b"x"), "text/plain")}, data={"style": "pelea"})
    assert bad_type.status_code == 415
    bad_style = client.post("/api/jobs", files={"video": ("a.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "no_existe"})
    assert bad_style.status_code == 422
    assert client.get("/api/jobs/nada").status_code == 404
