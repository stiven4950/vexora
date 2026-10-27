"""API del editor de efectos: pistas de una versión, cambios que crean otra y tira de fotogramas."""

from __future__ import annotations

import io
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vfxglow.api import limits, server  # noqa: E402
from vfxglow.api.jobs import JobStore  # noqa: E402
from vfxglow.director.schema import Effect  # noqa: E402

T = "person_0:right_wrist"
FPS, FRAMES = 30.0, 60  # el video de prueba: 2 s


def _effect(effect_id: str, action: str, frames: list[int]) -> dict:
    return {"id": effect_id, "type": "swoosh", "target": {"kind": "joint", "id": "right_wrist"},
            "triggers": [{"event": action, "frames": frames, "targets": [T] * len(frames), "hold": 3, "cooldown": 0}]}


class EditorPipeline:
    """Pipeline de mentira con lo que el editor necesita: guion, coreografía y gestos guardados,
    y un render que deja escrito qué tramo dibujó."""

    renders: list[dict] = []

    def __init__(self, config, video: Path, **kwargs) -> None:
        self.kwargs = kwargs
        self.run_dir = video.parent.parent.parent / "runs" / video.parent.name

    def run(self) -> Path:
        scripts, analysis = self.run_dir / "scripts", self.run_dir / "analysis"
        scripts.mkdir(parents=True, exist_ok=True)
        analysis.mkdir(parents=True, exist_ok=True)
        script = {"title": "t", "theme": "pelea", "effects": [_effect("fast_swing_swoosh_0", "fast_swing", [10, 40]), _effect("person_contact_llamarada_0", "person_contact", [25])]}
        (scripts / "effect_script.json").write_text(json.dumps(script))
        decisions = [
            {"frame": 10, "second": 10 / FPS, "action": "fast_swing", "target": T, "choice": "swoosh", "until": 16},
            {"frame": 25, "second": 25 / FPS, "action": "person_contact", "target": T, "choice": "llamarada", "until": 31},
            {"frame": 40, "second": 40 / FPS, "action": "fast_swing", "target": T, "choice": "swoosh", "until": 46},
        ]
        (scripts / "choreography.json").write_text(json.dumps({"catalog": "pelea", "seed": 1, "decisions": decisions}))
        events = [{"name": d["action"], "target": T, "start_frame": d["frame"], "end_frame": d["frame"] + 3, "confidence": 1.0} for d in decisions]
        (analysis / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))
        logging.getLogger("vfxglow").info("Compuestos 60/60 fotogramas")
        out = self.run_dir / "output" / "pelea.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"base")
        return out

    def _meta(self):
        return SimpleNamespace(fps=FPS, frame_count=FRAMES)

    def element_of(self):
        return lambda option, action: None

    def edit_catalog(self):
        return SimpleNamespace(element="")  # pelea: sin elemento

    def compile_add(self, option, action, frame, length, person, seed):
        from vfxglow.analysis.schema import MotionEvent

        effect = Effect.model_validate(_effect(f"{action}_{option}_0_fijado_0", action or "fast_swing", [frame]))
        event = MotionEvent(name=action or "fast_swing", target=T, start_frame=frame, end_frame=frame + length, confidence=1.0)
        return [effect], [event], option, action or "fast_swing"

    def render_script(self, script, dest, base_output=None, window=None, events=None):
        EditorPipeline.renders.append({"window": window, "partial": base_output is not None, "effects": [e.id for e in script.effects]})
        dest.write_bytes(b"editado")
        return dest


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    EditorPipeline.renders = []
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", EditorPipeline)
    monkeypatch.setattr(limits, "probe_video", lambda path: limits.VideoInfo(duration_s=2.0, width=64, height=96, fps=FPS, codec="h264"))
    monkeypatch.setattr(server, "_video_timing", lambda job: (FPS, FRAMES))
    monkeypatch.setenv("VEXORA_AUTH", "off")
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", server.CONFIG))
    return TestClient(server.app)


def _wait(client: TestClient, job_id: str) -> dict:
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("el trabajo no terminó")


def _done(client: TestClient) -> dict:
    job = client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()
    return _wait(client, job["id"])


def test_a_finished_choreography_opens_in_the_editor_with_its_tracks(client: TestClient) -> None:
    job = _done(client)
    assert job["editable"] is True
    editor = client.get(f"/api/jobs/{job['id']}/editor").json()
    assert editor["duration"] == 2.0 and editor["frames"] == FRAMES
    tracks = {t["key"]: t for t in editor["tracks"]}
    assert set(tracks) == {"swoosh", "llamarada"}  # pelea no tiene elementos: una pista por efecto
    assert [m["start"] for m in tracks["swoosh"]["moments"]] == [0.33, 1.33] and tracks["swoosh"]["start"] == 0.33
    assert any(o["option"] == "swoosh" and o["action"] == "fast_swing" for o in editor["options"])


def test_applying_changes_creates_a_new_version_that_only_redraws_what_changed(client: TestClient) -> None:
    job = _done(client)
    editor = client.get(f"/api/jobs/{job['id']}/editor").json()
    last = next(t for t in editor["tracks"] if t["key"] == "swoosh")["moments"][-1]
    response = client.post(f"/api/jobs/{job['id']}/edit", json={"edits": [{"op": "remove", "moment": last["id"]}]})
    assert response.status_code == 201
    edited = _wait(client, response.json()["id"])
    assert edited["status"] == "done", edited["error"]
    assert edited["base"] == job["id"] and edited["parent"] == job["id"] and edited["editable"]
    render = EditorPipeline.renders[-1]
    assert render["partial"] is True and render["window"][0] == 40  # solo el tramo del momento quitado
    assert client.get(edited["output_url"]).content == b"editado"
    # La versión nueva tiene un momento menos; la base sigue igual.
    swoosh = next(t for t in client.get(f"/api/jobs/{edited['id']}/editor").json()["tracks"] if t["key"] == "swoosh")
    assert len(swoosh["moments"]) == 1
    assert len(next(t for t in client.get(f"/api/jobs/{job['id']}/editor").json()["tracks"] if t["key"] == "swoosh")["moments"]) == 2


def test_moving_adding_and_styling_reach_the_new_script(client: TestClient) -> None:
    job = _done(client)
    editor = client.get(f"/api/jobs/{job['id']}/editor").json()
    first = next(t for t in editor["tracks"] if t["key"] == "swoosh")["moments"][0]
    edits = [
        {"op": "move", "moment": first["id"], "start": 0.6, "end": 0.9},
        {"op": "style", "track": "llamarada", "intensity": 1.6, "color": "#ff3300"},
        {"op": "add", "option": "estrellas", "action": "person_contact", "start": 1.6, "end": 1.9, "track": "llamarada"},
    ]
    edited = _wait(client, client.post(f"/api/jobs/{job['id']}/edit", json={"edits": edits}).json()["id"])
    assert edited["status"] == "done", edited["error"]
    script = json.loads((server.store.artifact(edited["id"], "script")).read_text())
    ids = {e["id"]: e for e in script["effects"]}
    assert "fast_swing_swoosh_0~m1" in ids and ids["fast_swing_swoosh_0~m1"]["triggers"][0]["frames"] == [18]
    assert ids["person_contact_llamarada_0"]["style"]["intensity"] == pytest.approx(1.6)
    assert any(effect_id.startswith("ed") and "estrellas" in effect_id for effect_id in ids)


def test_impossible_or_foreign_edits_are_refused(client: TestClient) -> None:
    job = _done(client)
    bad = client.post(f"/api/jobs/{job['id']}/edit", json={"edits": [{"op": "remove", "moment": "no-existe"}]})
    assert bad.status_code == 422 and "No existe el momento" in bad.json()["detail"]
    assert client.post(f"/api/jobs/{job['id']}/edit", json={"edits": []}).status_code == 422
    assert client.post(f"/api/jobs/{job['id']}/edit", json={"edits": [{"op": "volar"}]}).status_code == 422
    assert client.get("/api/jobs/nada/editor").status_code == 404


def test_a_job_without_its_saved_script_is_not_editable(client: TestClient) -> None:
    job = _done(client)
    server.store.artifact(job["id"], "script").unlink()
    assert client.get(f"/api/jobs/{job['id']}").json()["editable"] is False
    assert client.get(f"/api/jobs/{job['id']}/editor").status_code == 409


def test_deleting_a_version_removes_its_editor_files(client: TestClient) -> None:
    job = _done(client)
    assert server.store.artifact(job["id"], "script").exists()
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert not list(server.store.outputs.glob(f"{job['id']}.*"))
