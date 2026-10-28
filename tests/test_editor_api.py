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
from vfxglow.api.previews import window_for  # noqa: E402
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
        (self.run_dir / "analysis").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "analysis" / "motion_brief.json").write_text("{}")  # el análisis que deja el pipeline real
        self.direct()
        logging.getLogger("vfxglow").info("Compuestos 60/60 fotogramas")
        out = self.run_dir / "output" / "pelea.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"base")
        return out

    def direct(self) -> None:
        """Escribe el guion, la coreografía y los gestos, como la etapa de dirección real."""
        scripts, analysis = self.run_dir / "scripts", self.run_dir / "analysis"
        scripts.mkdir(parents=True, exist_ok=True)
        analysis.mkdir(parents=True, exist_ok=True)
        always = {"id": "always_0_tramo0", "type": "particles", "target": {"kind": "joint", "id": "nose"}}
        script = {"title": "t", "theme": "pelea", "effects": [always, _effect("fast_swing_swoosh_0", "fast_swing", [10, 40]), _effect("person_contact_llamarada_0", "person_contact", [25])]}
        (scripts / "effect_script.json").write_text(json.dumps(script))
        decisions = [
            {"frame": 10, "second": 10 / FPS, "action": "fast_swing", "target": T, "choice": "swoosh", "until": 16},
            {"frame": 25, "second": 25 / FPS, "action": "person_contact", "target": T, "choice": "llamarada", "until": 31},
            {"frame": 40, "second": 40 / FPS, "action": "fast_swing", "target": T, "choice": "swoosh", "until": 46},
        ]
        (scripts / "choreography.json").write_text(json.dumps({"catalog": "pelea", "seed": 1, "decisions": decisions}))
        events = [{"name": d["action"], "target": T, "start_frame": d["frame"], "end_frame": d["frame"] + 3, "confidence": 1.0} for d in decisions]
        (analysis / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events))

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
    assert set(tracks) == {"always:drop", "swoosh", "llamarada"}  # una pista por efecto, y una por permanente
    assert tracks["swoosh"] == {**tracks["swoosh"], "label": "swoosh", "icon": "sparkles", "element": None, "color": "#22d3ee"}
    permanent = tracks["always:drop"]
    assert (permanent["label"], permanent["icon"], permanent["color"], permanent["element"]) == ("always:drop", "sparkles", "#94a3b8", None)
    assert permanent["moments"] == [{"id": "always@always_0_tramo0", "start": 0.0, "end": 1.97, "choice": "always:drop", "action": "always", "person": None, "note": ""}]
    assert [m["start"] for m in tracks["swoosh"]["moments"]] == [0.33, 1.33] and tracks["swoosh"]["start"] == 0.33
    assert any(o["option"] == "swoosh" and o["action"] == "fast_swing" and o["track"] == "swoosh" and o["element"] is None for o in editor["options"])


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


def test_editor_options_carry_their_element(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _done(client)
    catalog = SimpleNamespace(
        element="",
        reactions=[SimpleNamespace(action="fast_swing", options=[SimpleNamespace(name="swoosh", element="agua", effects=[1]), SimpleNamespace(name="chispas", element=None, effects=[1]), SimpleNamespace(name="vacia", element="", effects=[])])],
    )
    monkeypatch.setattr(server, "_editor_catalog", lambda job: catalog)
    options = {o["option"]: o for o in client.get(f"/api/jobs/{job['id']}/editor").json()["options"]}
    assert options["swoosh"] == {"option": "swoosh", "action": "fast_swing", "track": "swoosh", "element": "agua"}
    assert options["chispas"]["element"] is None and "vacia" not in options


def test_removing_the_permanent_track_and_moving_it_through_the_api(client: TestClient) -> None:
    job = _done(client)
    moved = client.post(f"/api/jobs/{job['id']}/edit", json={"edits": [{"op": "move", "moment": "always@always_0_tramo0", "start": 0.5, "end": 1.0}]})
    assert moved.status_code == 422 and "dura todo el video" in moved.json()["detail"]
    off = client.post(f"/api/jobs/{job['id']}/edit", json={"edits": [{"op": "track_off", "track": "always:drop"}]})
    edited = _wait(client, off.json()["id"])
    assert edited["status"] == "done", edited["error"]
    assert "always:drop" not in {t["key"] for t in client.get(f"/api/jobs/{edited['id']}/editor").json()["tracks"]}


def _legacy(client: TestClient) -> dict:
    """Una versión hecha antes del editor: terminada, pero sin sus artefactos."""
    job = _done(client)
    for kind in ("script", "moments", "events"):
        server.store.artifact(job["id"], kind).unlink()
    return job


def test_a_finished_version_without_artifacts_is_preparable_and_prepare_edit_makes_it_editable(client: TestClient) -> None:
    done = _done(client)
    assert done["preparable"] is False and done["editable"] is True
    job = _legacy(client)
    shown = client.get(f"/api/jobs/{job['id']}").json()
    assert shown["preparable"] is True and shown["editable"] is False
    prepared = client.post(f"/api/jobs/{job['id']}/prepare-edit")
    assert prepared.status_code == 200
    body = prepared.json()
    assert body["editable"] is True and body["preparable"] is False and body["status"] == "done"
    assert json.loads(server.store.artifact(job["id"], "prepared").read_text()) == {"prepared": True}
    assert {t["key"] for t in client.get(f"/api/jobs/{job['id']}/editor").json()["tracks"]} == {"always:drop", "swoosh", "llamarada"}


def test_prepare_edit_is_refused_without_analysis_or_when_it_does_not_apply(client: TestClient) -> None:
    job = _legacy(client)
    brief = Path(EditorPipeline(None, Path(job["video_path"])).run_dir) / "analysis" / "motion_brief.json"
    brief.unlink()
    missing = client.post(f"/api/jobs/{job['id']}/prepare-edit")
    assert missing.status_code == 409 and "Ya no está el análisis" in missing.json()["detail"]
    assert client.get(f"/api/jobs/{job['id']}").json()["editable"] is False
    editable = _done(client)
    again = client.post(f"/api/jobs/{editable['id']}/prepare-edit")
    assert again.status_code == 409 and "ya se puede editar" in again.json()["detail"]
    assert client.post("/api/jobs/nada/prepare-edit").status_code == 404
    preset = client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style_kind": "preset", "style": "body_aura"})
    assert preset.status_code in (200, 201), preset.text
    shown = _wait(client, preset.json()["id"])
    assert shown["status"] == "done" and shown["preparable"] is False
    refused = client.post(f"/api/jobs/{shown['id']}/prepare-edit")
    assert refused.status_code == 409 and "catálogo" in refused.json()["detail"]


def test_editing_a_prepared_version_redraws_the_whole_video(client: TestClient) -> None:
    job = _legacy(client)
    assert client.post(f"/api/jobs/{job['id']}/prepare-edit").status_code == 200
    last = next(t for t in client.get(f"/api/jobs/{job['id']}/editor").json()["tracks"] if t["key"] == "swoosh")["moments"][-1]
    edited = _wait(client, client.post(f"/api/jobs/{job['id']}/edit", json={"edits": [{"op": "remove", "moment": last["id"]}]}).json()["id"])
    assert edited["status"] == "done", edited["error"]
    render = EditorPipeline.renders[-1]
    assert render["partial"] is False  # el guion regenerado puede no coincidir con el video: se redibuja entero
    # La versión que sale de ahí sí es una base normal: su siguiente edición vuelve a ser parcial.
    assert not server.store.artifact(edited["id"], "prepared").exists()
    nxt = _wait(client, client.post(f"/api/jobs/{edited['id']}/edit", json={"edits": [{"op": "remove", "moment": next(t for t in client.get(f"/api/jobs/{edited['id']}/editor").json()["tracks"] if t["key"] == "swoosh")["moments"][0]["id"]}]}).json()["id"])
    assert nxt["status"] == "done" and EditorPipeline.renders[-1]["partial"] is True


# ----- vista previa rápida -----


@pytest.fixture(autouse=True)
def fake_preview(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    calls: list[dict] = []

    def render_preview(self, script, dest, window, events=None, max_side=None):
        calls.append({"window": window, "effects": [e.id for e in script.effects]})
        dest.write_bytes(b"vista")
        return window[1] - window[0] + 1

    monkeypatch.setattr(EditorPipeline, "render_preview", render_preview, raising=False)
    return calls


def _remove(client: TestClient, job: dict) -> dict:
    moments = next(t for t in client.get(f"/api/jobs/{job['id']}/editor").json()["tracks"] if t["key"] == "swoosh")["moments"]
    return {"op": "remove", "moment": moments[-1]["id"]}


def _style(i: int) -> dict:
    """Un cambio distinto por `i` (el video de prueba dura 2 s: la ventana es siempre la misma)."""
    return {"op": "style", "track": "llamarada", "intensity": 1.0 + i / 10}


def _ready(client: TestClient, job_id: str, preview_id: str) -> dict:
    for _ in range(200):
        shown = client.get(f"/api/jobs/{job_id}/preview/{preview_id}").json()
        if shown["status"] != "rendering":
            return shown
        time.sleep(0.02)
    raise AssertionError("la vista previa no terminó")


def test_window_is_three_seconds_clipped_to_the_video() -> None:
    assert window_for(5.0, 30.0, 900) == (105, 194)
    assert window_for(0.2, 30.0, 900) == (0, 50)
    assert window_for(29.9, 30.0, 900) == (852, 899)


def test_preview_renders_only_the_window_serves_it_and_creates_no_version(client: TestClient, fake_preview: list[dict]) -> None:
    job = _done(client)
    before = len(client.get("/api/jobs").json())
    created = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_remove(client, job)], "at": 1.0})
    assert created.status_code == 202 and created.json()["status"] in ("rendering", "ready")
    shown = _ready(client, job["id"], created.json()["preview_id"])
    assert shown["status"] == "ready" and shown["error"] is None
    assert shown["start"] == 0.0 and shown["end"] == pytest.approx(2.0, abs=0.05)  # el video de prueba dura 2 s
    assert client.get(shown["url"]).content == b"vista"
    assert fake_preview[-1]["window"] == (0, FRAMES - 1)
    assert len(client.get("/api/jobs").json()) == before  # no hay versión nueva
    assert not EditorPipeline.renders  # y no pasó por render_script


def test_same_edits_and_window_hit_the_cache(client: TestClient, fake_preview: list[dict]) -> None:
    job = _done(client)
    body = {"edits": [_remove(client, job)], "at": 1.0}
    first = client.post(f"/api/jobs/{job['id']}/preview", json=body).json()
    _ready(client, job["id"], first["preview_id"])
    again = client.post(f"/api/jobs/{job['id']}/preview", json=body).json()
    assert again["preview_id"] == first["preview_id"] and again["status"] == "ready"
    assert len(fake_preview) == 1
    other = client.post(f"/api/jobs/{job['id']}/preview", json={**body, "edits": [{"op": "track_off", "track": "llamarada"}]}).json()
    assert other["preview_id"] != first["preview_id"]
    _ready(client, job["id"], other["preview_id"])
    assert len(fake_preview) == 2


def test_impossible_edits_are_422_and_other_users_get_404(client: TestClient) -> None:
    job = _done(client)
    bad = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [{"op": "remove", "moment": "no-existe"}], "at": 1.0})
    assert bad.status_code == 422 and "No existe el momento" in bad.json()["detail"]
    assert client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [], "at": 1.0}).status_code == 422
    assert client.post("/api/jobs/nada/preview", json={"edits": [{"op": "volar"}], "at": 1.0}).status_code == 404
    ok = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_remove(client, job)], "at": 1.0}).json()
    _ready(client, job["id"], ok["preview_id"])
    server.store._update(job["id"], owner="otra-persona")
    assert client.get(f"/api/jobs/{job['id']}/preview/{ok['preview_id']}").status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(1)], "at": 1.0}).status_code == 404


def test_daily_cap_answers_429(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _done(client)
    monkeypatch.setattr(limits, "auth_enabled", lambda: True)
    monkeypatch.setenv(limits.DAILY_PREVIEWS_ENV, "2")
    for i in (1, 2):
        response = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(i)], "at": 1.0})
        assert response.status_code == 202
        _ready(client, job["id"], response.json()["preview_id"])
    cached = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(2)], "at": 1.0})
    assert cached.status_code == 202  # lo ya dibujado no gasta cuota
    full = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(3)], "at": 1.0})
    assert full.status_code == 429 and "vistas previas" in full.json()["detail"]


def test_a_newer_request_discards_the_pending_one_of_the_same_user(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    job = _done(client)
    import threading

    gate = threading.Event()

    def slow(self, script, dest, window, events=None, max_side=None):
        gate.wait(5)
        dest.write_bytes(b"vista")
        return 1

    monkeypatch.setattr(EditorPipeline, "render_preview", slow, raising=False)
    running = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(1)], "at": 1.0}).json()
    time.sleep(0.2)  # el primero ya está dibujando
    pending = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(2)], "at": 1.0}).json()
    newest = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(3)], "at": 1.0}).json()
    gate.set()
    assert _ready(client, job["id"], running["preview_id"])["status"] == "ready"
    assert _ready(client, job["id"], newest["preview_id"])["status"] == "ready"
    dropped = client.get(f"/api/jobs/{job['id']}/preview/{pending['preview_id']}").json()
    assert dropped["status"] == "failed" and "más reciente" in dropped["error"]


def test_deleting_the_version_removes_its_previews(client: TestClient) -> None:
    job = _done(client)
    shown = client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_remove(client, job)], "at": 1.0}).json()
    _ready(client, job["id"], shown["preview_id"])
    assert (server.previews().root / job["id"]).exists()
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert not (server.previews().root / job["id"]).exists()
