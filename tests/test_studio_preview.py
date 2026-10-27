"""Vista previa del Estudio: ~3 s con efectos reales sobre una subida ya analizada, antes del trabajo."""

from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vfxglow.analysis.schema import AttentionSpan, MotionBrief, MotionEvent, VideoMeta  # noqa: E402
from vfxglow.api import auth, limits, server  # noqa: E402
from vfxglow.api.jobs import JobStore  # noqa: E402
from vfxglow.api.previews import busiest_window  # noqa: E402

USERS = {"ana": ("uid-ana", "ana@example.com", True), "beto": ("uid-beto", "beto@example.com", True)}


def brief_of(frames: int = 300, **fields) -> MotionBrief:
    video = VideoMeta(path="v.mp4", fps=30.0, width=720, height=1280, frame_count=frames, duration_s=frames / 30)
    return MotionBrief(video=video, person_id="person_0", anchors=[], limbs=[], events=fields.pop("events", []), summary="", **fields)


def event(start: int, end: int) -> MotionEvent:
    return MotionEvent(name="fast_swing", target="person_0:right_wrist", start_frame=start, end_frame=end, confidence=0.9)


class FakePipeline:
    """Pipeline de mentira: analiza escribiendo un brief y dirige/dibuja solo en memoria."""

    renders: list[dict] = []
    scripts_written = 0
    gate = None

    def __init__(self, config, video: Path, **kwargs) -> None:
        self.kwargs = kwargs
        digest = hashlib.sha256(video.read_bytes()).hexdigest()[:8]
        self.run_dir = video.parent.parent.parent / "runs" / f"{video.stem}-{digest}"
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self) -> None:
        brief = self.run_dir / "analysis" / "motion_brief.json"
        brief.parent.mkdir(parents=True, exist_ok=True)
        brief.write_text(brief_of(events=[event(150, 200)]).model_dump_json())

    def _ensure_derived(self, brief_path: Path) -> None:
        pass

    def direct_in_memory(self, brief=None):
        return "guion con extras" if brief is not None else "guion"

    def window_extras(self, window):
        if self.kwargs.get("catalog") not in ("baile", "espadas_neon", "espadas_fuego"):
            return None
        return brief_of(), {}, []

    def render_preview(self, script, dest, window, events=None, max_side=None, tracks=None) -> int:
        if FakePipeline.gate is not None:
            FakePipeline.gate.wait(5)
        FakePipeline.renders.append({"kwargs": self.kwargs, "window": window, "max_side": max_side, "script": script})
        dest.write_bytes(b"vista")
        return window[1] - window[0] + 1


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakePipeline.renders, FakePipeline.gate = [], None


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    monkeypatch.setattr(limits, "probe_video", lambda path: limits.VideoInfo(duration_s=10.0, width=720, height=1280, fps=30.0, codec="h264"))
    monkeypatch.setenv("VEXORA_AUTH", "on")

    def fake_verify(token: str) -> auth.User:
        uid, email, verified = USERS[token]
        return auth.User(uid=uid, email=email, email_verified=verified)

    monkeypatch.setattr(auth, "verify", fake_verify)
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", server.CONFIG))
    monkeypatch.setattr(server, "upload_store", None)
    monkeypatch.setattr(server, "_previews", None)
    return TestClient(server.app)


def as_(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def upload(client: TestClient, token: str = "ana", ready: bool = True) -> str:
    body = client.post("/api/uploads", files={"video": ("clip.mp4", io.BytesIO(b"\x00" * 64), "video/mp4")}, headers=as_(token)).json()
    for _ in range(200):
        shown = client.get(f"/api/uploads/{body['id']}", headers=as_(token)).json()
        if shown["status"] != "analyzing" or not ready:
            break
        time.sleep(0.02)
    return body["id"]


def finished(client: TestClient, upload_id: str, preview_id: str, token: str = "ana") -> dict:
    for _ in range(200):
        shown = client.get(f"/api/uploads/{upload_id}/preview/{preview_id}", headers=as_(token)).json()
        if shown["status"] != "rendering":
            return shown
        time.sleep(0.02)
    raise AssertionError("la vista previa no terminó")


def ask(client: TestClient, upload_id: str, token: str = "ana", **body):
    return client.post(f"/api/uploads/{upload_id}/preview", json={"style": "avatar", **body}, headers=as_(token))


def test_creates_polls_and_serves_with_the_signed_key(client: TestClient) -> None:
    uid = upload(client)
    created = ask(client, uid, wardrobe="vestido")
    assert created.status_code == 202, created.text
    shown = finished(client, uid, created.json()["preview_id"])
    assert shown["status"] == "ready" and shown["error"] is None
    # El tramo es de 3 s, alrededor del evento (frames 150-200 de 300).
    assert shown["end"] - shown["start"] == pytest.approx(3.0) and shown["start"] <= 5.0 <= shown["end"]
    call = FakePipeline.renders[-1]
    assert call["kwargs"]["catalog"] == "avatar" and call["kwargs"]["wardrobe"] == {"*": "vestido"} and call["kwargs"]["take"] == 0
    assert call["max_side"] == 480
    assert client.get(shown["url"]).content == b"vista"
    assert client.get(f"/api/uploads/{uid}/preview/{created.json()['preview_id']}.mp4").status_code == 404  # sin llave
    assert client.get(shown["url"][:-1] + ("A" if shown["url"][-1] != "A" else "B")).status_code == 404  # llave alterada


def test_not_ready_and_unknown_styles_are_refused(client: TestClient) -> None:
    uid = upload(client)  # analizada del todo: el hilo ya no puede volver a marcarla lista
    server.uploads()._items[uid].status = "analyzing"
    early = ask(client, uid)
    assert early.status_code == 409 and early.json()["detail"] == "Espera a que termine el análisis."
    server.uploads()._items[uid].status = "ready"
    assert ask(client, uid, style="no-existe").status_code == 422
    assert ask(client, uid, style_kind="preset", style="body_aura").status_code == 422
    assert ask(client, uid, fire_style="no-existe").status_code == 422
    assert ask(client, uid, style="baile", prop="nave").status_code == 422


def test_styles_with_needs_look_for_blades_or_cap_only_in_the_window(client: TestClient) -> None:
    uid = upload(client)
    created = ask(client, uid, style="baile")
    assert created.status_code == 202, created.text
    assert finished(client, uid, created.json()["preview_id"])["status"] == "ready"
    assert FakePipeline.renders[-1]["script"] == "guion con extras"
    ball = ask(client, uid, style="baile", prop="balon")
    assert finished(client, uid, ball.json()["preview_id"])["status"] == "ready"
    assert FakePipeline.renders[-1]["kwargs"]["prop"] == "balon"  # otro objeto: otra vista previa
    plain = ask(client, uid, style="avatar")
    assert finished(client, uid, plain.json()["preview_id"])["status"] == "ready"
    assert FakePipeline.renders[-1]["script"] == "guion"


def test_other_users_get_404(client: TestClient) -> None:
    uid = upload(client)
    created = ask(client, uid).json()
    assert ask(client, uid, token="beto").status_code == 404
    assert client.get(f"/api/uploads/{uid}/preview/{created['preview_id']}", headers=as_("beto")).status_code == 404
    done = finished(client, uid, created["preview_id"])
    assert client.get(done["url"].replace("k=", "k=1.")).status_code == 404


def test_same_request_hits_the_cache_and_other_options_draw_again(client: TestClient) -> None:
    uid = upload(client)
    first = ask(client, uid).json()
    finished(client, uid, first["preview_id"])
    again = ask(client, uid).json()
    assert again["preview_id"] == first["preview_id"] and again["status"] == "ready"
    assert len(FakePipeline.renders) == 1
    other = ask(client, uid, style="fuego").json()
    assert other["preview_id"] != first["preview_id"]
    finished(client, uid, other["preview_id"])
    assert len(FakePipeline.renders) == 2


def test_quota_is_shared_with_the_editor_previews(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEXORA_DAILY_PREVIEWS", "2")
    uid = upload(client)
    for style in ("avatar", "fuego"):
        finished(client, uid, ask(client, uid, style=style).json()["preview_id"])
    refused = ask(client, uid, style="rayo")
    assert refused.status_code == 429 and "vistas previas" in refused.json()["detail"]
    assert ask(client, uid, style="avatar").status_code == 202  # lo ya hecho no cuenta


def test_deleting_the_upload_removes_its_previews(client: TestClient) -> None:
    uid = upload(client)
    done = finished(client, uid, ask(client, uid).json()["preview_id"])
    path = server.previews().root / uid
    assert path.exists()
    assert client.delete(f"/api/uploads/{uid}", headers=as_("ana")).status_code == 204
    assert not path.exists() and client.get(done["url"]).status_code == 404


def test_window_follows_attention_then_events_then_the_center() -> None:
    span = AttentionSpan(person="person_0", start_frame=220, end_frame=290, primary="left_arm")
    still = AttentionSpan(person="person_0", start_frame=0, end_frame=100, primary="head")
    start, end = busiest_window(brief_of(attention=[still, span], events=[event(10, 20)]))
    assert end - start == 89 and start >= 200 and end <= 299  # manda la atención, no el evento suelto
    start, end = busiest_window(brief_of(events=[event(40, 60), event(50, 70)]))
    assert start <= 40 and end >= 70
    assert busiest_window(brief_of()) == (105, 194)  # sin nada: el centro
    assert busiest_window(brief_of(frames=50)) == (0, 49)  # video más corto que la ventana
