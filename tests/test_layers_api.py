"""Capas por pista de la vista en vivo: generación en segundo plano, URL firmada y borrado con la versión."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vfxglow.api import limits, server  # noqa: E402
from vfxglow.api.jobs import JobStore  # noqa: E402
from vfxglow.api.layers import track_keys  # noqa: E402
from vfxglow.composite.atlas import AtlasLayout, TileRef  # noqa: E402
from vfxglow.director.edits import Moment, Track  # noqa: E402

T = "person_0:right_wrist"
FPS, FRAMES = 30.0, 60


class LayersPipeline:
    """Pipeline de mentira: dirige con un guion mínimo y `render_layers` escribe bytes y devuelve una distribución."""

    fail = False
    calls: list[dict] = []

    def __init__(self, config, video: Path, **kwargs) -> None:
        self.run_dir = video.parent.parent.parent / "runs" / video.parent.name

    def run(self) -> Path:
        scripts, analysis = self.run_dir / "scripts", self.run_dir / "analysis"
        scripts.mkdir(parents=True, exist_ok=True)
        analysis.mkdir(parents=True, exist_ok=True)
        (analysis / "motion_brief.json").write_text("{}")
        effect = {"id": "fast_swing_swoosh_0", "type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"},
                  "triggers": [{"event": "fast_swing", "frames": [10], "targets": [T], "hold": 3, "cooldown": 0}]}
        (scripts / "effect_script.json").write_text(json.dumps({"title": "t", "theme": "pelea", "effects": [effect]}))
        decisions = [{"frame": 10, "second": 10 / FPS, "action": "fast_swing", "target": T, "choice": "swoosh", "until": 16}]
        (scripts / "choreography.json").write_text(json.dumps({"catalog": "pelea", "seed": 1, "decisions": decisions}))
        (analysis / "events.jsonl").write_text(json.dumps({"name": "fast_swing", "target": T, "start_frame": 10, "end_frame": 13, "confidence": 1.0}))
        out = self.run_dir / "output" / "pelea.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"base")
        return out

    def _meta(self):
        return SimpleNamespace(fps=FPS, frame_count=FRAMES)

    def element_of(self):
        return lambda option, action: None

    def render_script(self, script, dest, base_output=None, window=None, events=None):
        dest.write_bytes(b"editado")
        return dest

    def render_layers(self, script, dest, key_of, keys, events=None):
        LayersPipeline.calls.append({"key_of": key_of, "keys": keys})
        if LayersPipeline.fail:
            dest.write_bytes(b"a medias")
            raise RuntimeError("boom /secreto/ruta")
        dest.write_bytes(b"mosaico")
        return AtlasLayout(fps=FPS, frames=FRAMES, width=8, height=8, tile=(2, 2), plate=(0, 0, 4, 4), tracks=[TileRef(key="swoosh", c=(4, 0))])


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    LayersPipeline.fail, LayersPipeline.calls = False, []
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", LayersPipeline)
    monkeypatch.setattr(limits, "probe_video", lambda path: limits.VideoInfo(duration_s=2.0, width=64, height=96, fps=FPS, codec="h264"))
    monkeypatch.setattr(server, "_video_timing", lambda job: (FPS, FRAMES))
    monkeypatch.setenv("VEXORA_AUTH", "off")
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", server.CONFIG))
    return TestClient(server.app)


def _wait_job(client: TestClient, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("el trabajo no terminó")


def _done(client: TestClient) -> dict:
    job = client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()
    return _wait_job(client, job["id"])


def _wait_layers(client: TestClient, job_id: str, want: str = "ready") -> dict:
    for _ in range(300):
        view = client.get(f"/api/jobs/{job_id}/layers").json()
        if view["status"] == want:
            return view
        time.sleep(0.02)
    raise AssertionError(f"las capas no llegaron a {want}: {view}")


def test_track_keys_maps_effects_and_orders_by_covered_frames() -> None:
    moments = [
        Moment(id="m1", frame=0, until=9, action="a", target=T, choice="x", effects=["e1", "e2"]),
        Moment(id="m2", frame=20, until=69, action="a", target=T, choice="y", effects=["e3", "e1"]),
    ]
    tracks = [Track(key="x", label="x", icon="", color="", moments=["m1"], start=0, end=9), Track(key="y", label="y", icon="", color="", moments=["m2"], start=20, end=69)]
    key_of, keys = track_keys(moments, tracks)
    assert key_of == {"e1": "x", "e2": "x", "e3": "y"}
    assert keys == ["y", "x"]


def test_layers_not_editable_is_409(client: TestClient) -> None:
    job = _done(client)
    server.jobs().artifact(job["id"], "moments").unlink()
    assert client.post(f"/api/jobs/{job['id']}/layers").status_code == 409


def test_layers_are_generated_and_served_with_a_signed_url(client: TestClient) -> None:
    job = _done(client)
    assert job["layers_ready"] is False
    assert client.get(f"/api/jobs/{job['id']}/layers").json() == {"status": "none", "url": None, "layout": None, "error": None, "estimate_s": 11}
    assert client.post(f"/api/jobs/{job['id']}/layers").status_code == 202
    view = _wait_layers(client, job["id"])
    assert view["layout"]["frames"] == FRAMES and view["layout"]["tracks"][0]["key"] == "swoosh" and view["error"] is None
    assert view["url"].startswith(f"/api/jobs/{job['id']}/layers.mp4?k=")
    assert LayersPipeline.calls[0]["keys"] == ["swoosh"] and LayersPipeline.calls[0]["key_of"] == {"fast_swing_swoosh_0": "swoosh"}
    # Pedirlas de nuevo no las dibuja otra vez.
    assert client.post(f"/api/jobs/{job['id']}/layers").json()["status"] == "ready"
    assert len(LayersPipeline.calls) == 1
    media = client.get(view["url"])
    assert media.status_code == 200 and media.content == b"mosaico" and media.headers["content-type"] == "video/mp4"
    assert client.get(f"/api/jobs/{job['id']}").json()["layers_ready"] is True


def test_layers_are_deleted_with_the_version(client: TestClient) -> None:
    job = _done(client)
    client.post(f"/api/jobs/{job['id']}/layers")
    _wait_layers(client, job["id"])
    outputs = server.jobs().outputs
    assert (outputs / f"{job['id']}.layers.mp4").exists() and (outputs / f"{job['id']}.layers.json").exists()
    assert client.delete(f"/api/jobs/{job['id']}").status_code in (200, 204)
    assert not (outputs / f"{job['id']}.layers.mp4").exists() and not (outputs / f"{job['id']}.layers.json").exists()


def test_a_failed_generation_reports_a_friendly_error_and_cleans_up(client: TestClient) -> None:
    job = _done(client)
    LayersPipeline.fail = True
    client.post(f"/api/jobs/{job['id']}/layers")
    view = _wait_layers(client, job["id"], "failed")
    assert "secreto" not in view["error"] and view["error"].startswith("No pudimos")
    outputs = server.jobs().outputs
    assert not (outputs / f"{job['id']}.layers.mp4").exists() and not (outputs / f"{job['id']}.layers.json").exists()
    LayersPipeline.fail = False  # se puede reintentar
    client.post(f"/api/jobs/{job['id']}/layers")
    assert _wait_layers(client, job["id"])["status"] == "ready"


def test_layers_of_another_user_are_hidden(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow.api import auth

    monkeypatch.setenv("VEXORA_AUTH", "on")
    users = {"ana": ("uid-ana", "ana@example.com", True), "beto": ("uid-beto", "beto@example.com", True)}

    def fake_verify(token: str) -> auth.User:
        uid, email, verified = users[token]
        return auth.User(uid=uid, email=email, email_verified=verified)

    monkeypatch.setattr(auth, "verify", fake_verify)
    ana, beto = {"Authorization": "Bearer ana"}, {"Authorization": "Bearer beto"}
    job = client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}, headers=ana).json()
    for _ in range(200):
        if client.get(f"/api/jobs/{job['id']}", headers=ana).json()["status"] == "done":
            break
        time.sleep(0.02)
    assert client.post(f"/api/jobs/{job['id']}/layers", headers=beto).status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/layers", headers=beto).status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/layers", headers=ana).status_code == 202
    for _ in range(300):
        view = client.get(f"/api/jobs/{job['id']}/layers", headers=ana).json()
        if view["status"] == "ready":
            break
        time.sleep(0.02)
    assert view["status"] == "ready"
    assert client.get(f"/api/jobs/{job['id']}/layers.mp4").status_code == 404  # sin llave
    assert client.get(f"/api/jobs/{job['id']}/layers.mp4?k=mala").status_code == 404
    assert client.get(view["url"]).content == b"mosaico"
