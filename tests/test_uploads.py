"""Subidas: análisis al elegir el video, recomendación de estilo, uso en un trabajo y caducidad."""

from __future__ import annotations

import hashlib
import io
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vfxglow.analysis.schema import MotionBrief, MotionEvent, VideoMeta  # noqa: E402
from vfxglow.api import auth, limits, server  # noqa: E402
from vfxglow.api.jobs import JobStore  # noqa: E402
from vfxglow.director.recommend import recommend  # noqa: E402

USERS = {"ana": ("uid-ana", "ana@example.com", True), "beto": ("uid-beto", "beto@example.com", True)}
AVAILABLE = ["avatar", "fuego", "rayo", "baile", "pelea", "espadas_fuego"]


def make_brief(events: list[tuple[str, str]] | None = None, **fields) -> MotionBrief:
    """Un brief mínimo hecho a mano: eventos como (nombre, objetivo)."""
    video = VideoMeta(path="v.mp4", fps=30.0, width=720, height=1280, frame_count=300, duration_s=10.0)
    rows = [MotionEvent(name=n, target=t, start_frame=i * 10, end_frame=i * 10 + 5, confidence=0.9) for i, (n, t) in enumerate(events or [])]
    return MotionBrief(video=video, person_id="person_0", anchors=[], limbs=[], events=rows, summary="", **fields)


class FakePipeline:
    """Pipeline de mentira: la carpeta de análisis sale del nombre y del contenido del video (como
    el real), analizar escribe un brief solo si no está en caché, y el candado es el verdadero."""

    analyses = 0
    events: list[tuple[str, str]] = [("person_contact", "person_0:right_wrist"), ("fast_swing", "person_1:left_wrist")]
    gate: threading.Event | None = None
    fail = False

    def __init__(self, config, video: Path, **kwargs) -> None:
        self.kwargs = kwargs
        digest = hashlib.sha256(video.read_bytes()).hexdigest()[:8]
        self.run_dir = video.parent.parent.parent / "runs" / f"{video.stem}-{digest}"
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def analyze(self) -> None:
        from vfxglow import telemetry
        from vfxglow.pipeline import analysis_lock

        with analysis_lock(self.run_dir):
            brief = self.run_dir / "analysis" / "motion_brief.json"
            if brief.exists():
                telemetry.annotate(cache_hit=True)
                return
            if FakePipeline.gate is not None:
                FakePipeline.gate.wait(5)
            if FakePipeline.fail:
                raise RuntimeError("falló en /Users/alguien/x")
            FakePipeline.analyses += 1
            brief.parent.mkdir(parents=True, exist_ok=True)
            brief.write_text(make_brief(FakePipeline.events).model_dump_json())

    def _ensure_derived(self, brief_path: Path) -> None:
        pass

    def run(self) -> Path:
        self.analyze()
        out = self.run_dir / "output" / "pelea.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"video")
        return out


def fake_probe(path: Path) -> limits.VideoInfo:
    return limits.VideoInfo(duration_s=9.4, width=720, height=1280, fps=30.0, codec="h264")


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakePipeline.analyses, FakePipeline.gate, FakePipeline.fail = 0, None, False
    FakePipeline.events = [("person_contact", "person_0:right_wrist"), ("fast_swing", "person_1:left_wrist")]


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    monkeypatch.setattr(limits, "probe_video", fake_probe)
    monkeypatch.setenv("VEXORA_AUTH", "on")
    monkeypatch.setenv("VEXORA_MAX_ACTIVE_JOBS", "10")

    def fake_verify(token: str) -> auth.User:
        uid, email, verified = USERS[token]
        return auth.User(uid=uid, email=email, email_verified=verified)

    monkeypatch.setattr(auth, "verify", fake_verify)
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", server.CONFIG))
    monkeypatch.setattr(server, "upload_store", None)
    return TestClient(server.app)


def as_(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def post_upload(client: TestClient, token: str = "ana", content: bytes = b"\x00" * 64, name: str = "clip.mp4"):
    return client.post("/api/uploads", files={"video": (name, io.BytesIO(content), "video/mp4")}, headers=as_(token))


def wait_upload(client: TestClient, upload_id: str, token: str = "ana", want: str = "analyzing") -> dict:
    for _ in range(200):
        body = client.get(f"/api/uploads/{upload_id}", headers=as_(token)).json()
        if body["status"] != want:
            return body
        time.sleep(0.02)
    raise AssertionError("la subida no cambió de estado")


def wait_job(client: TestClient, job_id: str, token: str = "ana") -> dict:
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}", headers=as_(token)).json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.02)
    raise AssertionError("el trabajo no terminó")


# ----- API -----


def test_an_upload_is_analyzed_and_gets_a_recommendation(client: TestClient) -> None:
    response = post_upload(client)
    assert response.status_code == 201
    first = response.json()
    assert first["id"].startswith("u_") and first["status"] == "analyzing" and first["recommendation"] is None
    done = wait_upload(client, first["id"])
    assert done["status"] == "ready" and done["error"] is None
    assert set(done) == {"id", "status", "filename", "created", "video_seconds", "video_width", "video_height", "video_bytes", "error", "recommendation"}
    assert (done["video_seconds"], done["video_width"], done["video_height"], done["video_bytes"]) == (9.4, 720, 1280, 64)
    rec = done["recommendation"]
    assert rec["style"] == "pelea" and "combate" in rec["reason"]
    assert [a["style"] for a in rec["alternatives"]] == ["avatar"] and set(rec["alternatives"][0]) == {"style", "reason"}


def test_a_failed_analysis_says_what_happened_without_internals(client: TestClient) -> None:
    FakePipeline.fail = True
    body = wait_upload(client, post_upload(client).json()["id"])
    assert body["status"] == "failed" and "cuerpo entero" in body["error"] and "alguien" not in body["error"]
    assert body["recommendation"] is None


def test_another_user_gets_a_404(client: TestClient) -> None:
    upload_id = post_upload(client, "ana").json()["id"]
    assert client.get(f"/api/uploads/{upload_id}", headers=as_("beto")).status_code == 404
    assert client.delete(f"/api/uploads/{upload_id}", headers=as_("beto")).status_code == 404
    assert client.get("/api/uploads/u_nope", headers=as_("ana")).status_code == 404
    assert client.get(f"/api/uploads/{upload_id}").status_code == 401


def test_at_most_three_uploads_analyzing_per_user(client: TestClient) -> None:
    FakePipeline.gate = threading.Event()
    ids = [post_upload(client, "ana", content=bytes([i]) * 8).json()["id"] for i in range(3)]
    fourth = post_upload(client, "ana", content=b"4" * 8)
    assert fourth.status_code == 429 and "analizándose" in fourth.json()["detail"]
    assert not any(p.name != "u_" and p.is_dir() and p.name not in ids for p in (server.uploads().root).iterdir())  # el rechazado no deja nada
    assert post_upload(client, "beto", content=b"5" * 8).status_code == 201  # el límite es por persona
    FakePipeline.gate.set()
    wait_upload(client, ids[-1])
    for upload_id in ids:
        wait_upload(client, upload_id)
    assert post_upload(client, "ana", content=b"6" * 8).status_code == 201


def test_delete_removes_the_file_and_the_analysis(client: TestClient) -> None:
    body = wait_upload(client, (created := post_upload(client).json())["id"])
    assert body["status"] == "ready"
    folder = server.uploads().root / created["id"]
    run_dir = server.jobs().root / "runs"
    assert folder.exists() and any(run_dir.iterdir())
    assert client.delete(f"/api/uploads/{created['id']}", headers=as_("ana")).status_code == 204
    assert not folder.exists() and not any(run_dir.iterdir())
    assert client.get(f"/api/uploads/{created['id']}", headers=as_("ana")).status_code == 404


def test_deleting_while_analyzing_is_ignored_by_the_thread(client: TestClient) -> None:
    FakePipeline.gate = threading.Event()
    upload_id = post_upload(client).json()["id"]
    assert client.delete(f"/api/uploads/{upload_id}", headers=as_("ana")).status_code == 204
    FakePipeline.gate.set()
    time.sleep(0.3)
    assert client.get(f"/api/uploads/{upload_id}", headers=as_("ana")).status_code == 404
    assert not (server.uploads().root / upload_id).exists()


def test_a_job_uses_the_upload_and_its_analysis(client: TestClient) -> None:
    upload_id = post_upload(client).json()["id"]
    assert wait_upload(client, upload_id)["status"] == "ready"
    response = client.post("/api/jobs", data={"style": "pelea", "upload_id": upload_id}, headers=as_("ana"))
    assert response.status_code == 201, response.text
    job = response.json()
    assert job["filename"] == "clip.mp4" and job["video_seconds"] == 9.4 and job["video_bytes"] == 64
    assert wait_job(client, job["id"])["status"] == "done"
    assert FakePipeline.analyses == 1  # el trabajo reutilizó el análisis de la subida
    video = Path(server.jobs().get(job["id"]).video_path)
    assert video.parent.name == job["id"] and video.read_bytes() == b"\x00" * 64
    assert not (server.uploads().root / upload_id).exists()
    assert client.get(f"/api/uploads/{upload_id}", headers=as_("ana")).json()["status"] == "used"
    again = client.post("/api/jobs", data={"style": "pelea", "upload_id": upload_id}, headers=as_("ana"))
    assert again.status_code == 409


def test_a_job_waits_for_an_upload_still_being_analyzed(client: TestClient) -> None:
    FakePipeline.gate = threading.Event()
    upload_id = post_upload(client).json()["id"]
    job = client.post("/api/jobs", data={"style": "pelea", "upload_id": upload_id}, headers=as_("ana")).json()
    FakePipeline.gate.set()
    assert wait_job(client, job["id"])["status"] == "done"
    assert FakePipeline.analyses == 1
    time.sleep(0.2)
    assert client.get(f"/api/uploads/{upload_id}", headers=as_("ana")).json()["status"] == "used"
    assert not (server.uploads().root / upload_id).exists()


def test_a_job_needs_exactly_a_video_or_an_upload(client: TestClient) -> None:
    upload_id = wait_upload(client, post_upload(client).json()["id"])["id"]
    video = {"video": ("clip.mp4", io.BytesIO(b"\x00" * 8), "video/mp4")}
    neither = client.post("/api/jobs", data={"style": "pelea"}, headers=as_("ana"))
    both = client.post("/api/jobs", files=video, data={"style": "pelea", "upload_id": upload_id}, headers=as_("ana"))
    for response in (neither, both):
        assert response.status_code == 422 and response.json()["detail"] == "Envía el video o una subida."
    # Un fallo de validación no gasta la subida.
    assert client.post("/api/jobs", data={"style": "nope", "upload_id": upload_id}, headers=as_("ana")).status_code == 422
    assert client.get(f"/api/uploads/{upload_id}", headers=as_("ana")).json()["status"] == "ready"
    assert client.post("/api/jobs", files=video, data={"style": "pelea"}, headers=as_("ana")).status_code == 201  # el camino de siempre


def test_an_upload_of_someone_else_or_expired_is_404(client: TestClient) -> None:
    upload_id = wait_upload(client, post_upload(client, "ana").json()["id"])["id"]
    other = client.post("/api/jobs", data={"style": "pelea", "upload_id": upload_id}, headers=as_("beto"))
    assert other.status_code == 404 and other.json()["detail"] == "La subida ya no existe: vuelve a cargar el video."
    assert client.post("/api/jobs", data={"style": "pelea", "upload_id": "u_nada"}, headers=as_("ana")).status_code == 404


def test_unused_uploads_expire_after_a_day_but_shared_analyses_survive(client: TestClient) -> None:
    store = server.uploads()
    old = wait_upload(client, post_upload(client, "ana", content=b"a" * 8).json()["id"])["id"]
    used = wait_upload(client, post_upload(client, "ana", content=b"a" * 8, name="otro.mp4").json()["id"])["id"]
    fresh = wait_upload(client, post_upload(client, "ana", content=b"b" * 8).json()["id"])["id"]
    job = client.post("/api/jobs", data={"style": "pelea", "upload_id": used}, headers=as_("ana")).json()
    assert wait_job(client, job["id"])["status"] == "done"
    for item in store._items.values():
        if item.id in (old, used):
            item.created -= 25 * 3600
    assert store.expire() == 2
    assert client.get(f"/api/uploads/{old}", headers=as_("ana")).status_code == 404
    assert not (store.root / old).exists()
    assert client.get(f"/api/uploads/{fresh}", headers=as_("ana")).json()["status"] == "ready"
    assert Path(server.jobs().get(job["id"]).video_path).exists()  # el trabajo conserva su video y su análisis
    assert Path(server.jobs().get(job["id"]).run_dir).exists()


def test_expiry_runs_on_create_and_on_start(client: TestClient, tmp_path: Path) -> None:
    store = server.uploads()
    old = wait_upload(client, post_upload(client).json()["id"])["id"]
    store._items[old].created -= 25 * 3600
    post_upload(client, content=b"z" * 8)  # al crear otra, la vencida se borra
    assert old not in store._items and not (store.root / old).exists()
    stale = wait_upload(client, post_upload(client, content=b"y" * 8).json()["id"])["id"]
    store._items[stale].created -= 25 * 3600
    store._save()
    from vfxglow.api.uploads import UploadStore

    assert stale not in UploadStore(server.jobs(), lambda: AVAILABLE)._items  # al arrancar


def test_uploads_still_analyzing_at_restart_are_marked_failed(client: TestClient) -> None:
    FakePipeline.gate = threading.Event()
    upload_id = post_upload(client).json()["id"]
    from vfxglow.api.uploads import UploadStore

    reborn = UploadStore(server.jobs(), lambda: AVAILABLE)
    FakePipeline.gate.set()
    item = reborn._items[upload_id]
    assert item.status == "failed" and item.error_code == "interrupted"


# ----- recomendación -----


def test_two_people_in_contact_get_pelea_first() -> None:
    brief = make_brief([("person_contact", "person_0:right_wrist"), ("fist_clash", "person_1:left_wrist")])
    picks = recommend(brief, AVAILABLE)
    assert [p.style for p in picks] == ["pelea", "avatar"] and "combate" in picks[0].reason


def test_two_people_without_hits_get_baile() -> None:
    brief = make_brief([("step", "person_0:mid_hip"), ("step", "person_1:mid_hip")])
    assert [p.style for p in recommend(brief, AVAILABLE)][:2] == ["baile", "avatar"]


def test_a_couple_dancing_most_of_the_video_gets_baile_even_with_contact() -> None:
    from vfxglow.analysis.schema import DuetSpan

    duet = [DuetSpan(start_frame=0, end_frame=290, mode="unison", leader="person_0", partner="person_1")]
    brief = make_brief([("person_contact", "person_0:right_wrist"), ("fist_clash", "person_1:left_wrist")], duet=duet)
    assert [p.style for p in recommend(brief, AVAILABLE)] == ["baile", "pelea", "avatar"]


def test_blades_recommend_espadas_and_no_blades_never_do() -> None:
    assert recommend(make_brief([("blade_swing", "person_0:right_wrist")]), AVAILABLE)[0].style == "espadas_fuego"
    assert recommend(make_brief(objects=["knife"]), AVAILABLE)[0].style == "espadas_fuego"
    assert all(p.style != "espadas_fuego" for p in recommend(make_brief([("fast_swing", "person_0:right_wrist")] * 6), AVAILABLE))


def test_one_person_with_flips_gets_an_elemental_then_avatar() -> None:
    picks = recommend(make_brief([("flip", "person_0:mid_hip")]), AVAILABLE)
    assert [p.style for p in picks] == ["fuego", "rayo", "avatar"] and "voltereta" in picks[0].reason


def test_default_is_avatar_and_only_available_styles_come_back() -> None:
    assert [p.style for p in recommend(make_brief(), AVAILABLE)] == ["avatar"]
    assert [p.style for p in recommend(make_brief([("person_contact", "person_0:x"), ("step", "person_1:y")]), ["baile", "fuego"])] == []
    assert [p.style for p in recommend(make_brief([("flip", "person_0:mid_hip")]), ["rayo", "avatar"])] == ["rayo", "avatar"]


def test_never_more_than_three() -> None:
    brief = make_brief([("person_contact", "person_0:x"), ("blade_swing", "person_1:y")], objects=["sword"])
    assert len(recommend(brief, AVAILABLE)) == 3


# ----- candado -----


def test_the_lock_is_one_per_analysis_folder(tmp_path: Path) -> None:
    from vfxglow.pipeline import analysis_lock

    assert analysis_lock(tmp_path / "a") is analysis_lock(tmp_path / "a" / ".." / "a")
    assert analysis_lock(tmp_path / "a") is not analysis_lock(tmp_path / "b")


def test_a_second_pipeline_waits_and_then_finds_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow import pipeline as pl
    from vfxglow.config import load_config
    from vfxglow.io.store import Manifest

    started: list[str] = []

    def slow_analysis(video, run_dir, config, device) -> None:
        started.append(video.name)
        time.sleep(0.3)
        (run_dir / "analysis").mkdir(parents=True, exist_ok=True)
        (run_dir / "analysis" / "tracks.jsonl").write_text("{}")

    monkeypatch.setattr(pl, "analyze_video", slow_analysis)
    config = load_config(server.CONFIG)

    def make() -> pl.Pipeline:
        p = pl.Pipeline.__new__(pl.Pipeline)
        p.config, p.force, p.video, p.device = config, False, Path("v.mp4"), "cpu"
        p.run_dir, p.manifest_path = tmp_path / "run", tmp_path / "run" / "manifest.json"
        p.run_dir.mkdir(exist_ok=True)
        p.manifest = Manifest(video_path="v.mp4", video_sha256="abc", device="cpu")  # cada uno cargó su manifiesto antes
        return p

    first, second = make(), make()
    threads = [threading.Thread(target=p.analyze) for p in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert started == ["v.mp4"]  # se analizó una sola vez
