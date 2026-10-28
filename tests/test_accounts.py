"""Cuenta: perfil y ajustes, avisos, borrar la cuenta y enlaces públicos (pipeline simulado)."""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("fastapi")
import cv2  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from test_api import FakePipeline, fake_probe  # noqa: E402
from vfxglow.api import auth, limits, profiles, ratelimit, server  # noqa: E402
from vfxglow.api.jobs import JobStore  # noqa: E402

USERS = {"ana": ("uid-ana", "ana@example.com", True), "beto": ("uid-beto", "beto@example.com", True), "caro": ("uid-caro", "caro@example.com", True)}


def as_(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakePipeline.fail = False
    FakePipeline.block = False


@pytest.fixture(autouse=True)
def _fresh_limits() -> None:
    ratelimit.public.reset()


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    monkeypatch.setattr(limits, "probe_video", fake_probe)
    monkeypatch.setenv("VEXORA_AUTH", "on")
    # Ana y Beto tienen Pro (guardar en la nube y compartir); Caro, sin asignación, queda en Free.
    monkeypatch.setenv("VEXORA_PLAN_GRANTS", "uid-ana:pro,uid-beto:pro")
    logging.getLogger().setLevel(logging.INFO)

    def fake_verify(token: str) -> auth.User:
        uid, email, verified = USERS[token]
        return auth.User(uid=uid, email=email, email_verified=verified, name=token.title())

    monkeypatch.setattr(auth, "verify", fake_verify)
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", server.CONFIG))
    monkeypatch.setattr(server, "upload_store", None)
    monkeypatch.setattr(server, "_previews", None)
    return TestClient(server.app)


def make_job(client: TestClient, who: str = "ana", wait: bool = True, save: bool = True) -> dict:
    """Un video de `who`; terminado y, si su plan lo permite y `save`, guardado en la nube."""
    job = _make_job(client, who, wait)
    if save and job.get("status") == "done":
        saved = client.post(f"/api/jobs/{job['id']}/save", headers=as_(who))
        if saved.status_code == 200:
            return saved.json()
    return job


def _make_job(client: TestClient, who: str = "ana", wait: bool = True) -> dict:
    files = {"video": ("clip.mp4", io.BytesIO(b"\x00" * 64), "video/mp4")}
    job = client.post("/api/jobs", files=files, data={"style": "pelea"}, headers=as_(who)).json()
    if not wait:
        return job
    for _ in range(200):
        shown = client.get(f"/api/jobs/{job['id']}", headers=as_(who)).json()
        if shown["status"] in ("done", "failed"):
            return shown
        time.sleep(0.02)
    raise AssertionError("el trabajo no terminó")


def picture(width: int = 800, height: int = 400, fmt: str = ".png") -> bytes:
    pixels = np.zeros((height, width, 3), np.uint8)
    pixels[:, : width // 2] = (255, 0, 0)
    return cv2.imencode(fmt, pixels)[1].tobytes()


# ----- perfil -----


def test_profile_defaults_come_from_the_token_and_the_plan(client: TestClient) -> None:
    me = client.get("/api/me", headers=as_("ana")).json()
    assert me["email"] == "ana@example.com" and me["display_name"] == "Ana"
    assert me["notifications"] == {"processing": True, "platform": True, "promotions": False}
    assert me["preferences"] == {"language": "es", "preview_quality": "alta", "theme": "oscuro"}
    assert me["username"] is None and me["avatar_url"] is None and me["accepted_terms_at"] is None
    assert me["plan"]["id"] and "CO" in {c["code"] for c in me["countries"]}
    assert client.get("/api/me").status_code == 401


def test_profile_patch_saves_and_validates(client: TestClient) -> None:
    ok = client.patch("/api/me", json={"display_name": " Ana Gómez ", "username": "Ana.G_1", "country": "co", "bio": "Hola", "notifications": {"promotions": True}, "preferences": {"preview_quality": "rapida"}}, headers=as_("ana"))
    assert ok.status_code == 200, ok.text
    me = ok.json()
    assert (me["display_name"], me["username"], me["country"], me["bio"]) == ("Ana Gómez", "ana.g_1", "CO", "Hola")
    assert me["notifications"] == {"processing": True, "platform": True, "promotions": True}
    assert me["preferences"]["preview_quality"] == "rapida" and me["preferences"]["language"] == "es"
    assert client.get("/api/me", headers=as_("ana")).json()["username"] == "ana.g_1"
    bad = [
        {"display_name": "  "}, {"username": "ab"}, {"username": "con espacio"}, {"username": "x" * 31}, {"country": "ZZ"},
        {"bio": "x" * 201}, {"preferences": {"theme": "claro"}}, {"preferences": {"idioma": "es"}}, {"notifications": {"processing": "si"}},
        {"email": "otro@x.com"},
    ]
    for body in bad:
        response = client.patch("/api/me", json=body, headers=as_("ana"))
        assert response.status_code == 422 and isinstance(response.json()["detail"], str), body
    assert client.get("/api/me", headers=as_("ana")).json()["display_name"] == "Ana Gómez"


def test_username_is_unique_and_released_when_changed(client: TestClient) -> None:
    assert client.patch("/api/me", json={"username": "estrella"}, headers=as_("ana")).status_code == 200
    taken = client.patch("/api/me", json={"username": "estrella"}, headers=as_("beto"))
    assert taken.status_code == 409 and "en uso" in taken.json()["detail"]
    assert client.patch("/api/me", json={"username": "estrella"}, headers=as_("ana")).status_code == 200  # el suyo, otra vez
    assert client.patch("/api/me", json={"username": "otra_cosa"}, headers=as_("ana")).status_code == 200
    assert client.patch("/api/me", json={"username": "estrella"}, headers=as_("beto")).status_code == 200  # ya quedó libre
    assert client.patch("/api/me", json={"username": None}, headers=as_("beto")).json()["username"] is None
    assert client.patch("/api/me", json={"username": "estrella"}, headers=as_("ana")).status_code == 200


def test_accepting_the_terms_records_the_version(client: TestClient) -> None:
    me = client.post("/api/me/terms", headers=as_("ana")).json()
    assert me["accepted_terms_at"] and me["terms_current"] and me["terms_version"] == profiles.TERMS_VERSION
    assert client.get("/api/me", headers=as_("beto")).json()["accepted_terms_at"] is None


# ----- foto -----


def test_avatar_is_cropped_square_reencoded_and_served(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/me/avatar", files={"avatar": ("yo.png", io.BytesIO(picture()), "image/png")}, headers=as_("ana"))
    assert response.status_code == 200, response.text
    url = response.json()["avatar_url"]
    assert url and "k=" in url
    stored = tmp_path / "api_data" / "avatars" / "uid-ana.jpg"
    assert stored.exists()
    image = cv2.imread(str(stored))
    assert image.shape[:2] == (512, 512)
    assert stored.read_bytes()[:2] == b"\xff\xd8" and b"Exif" not in stored.read_bytes()[:64]
    served = client.get(url)
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg" and served.content == stored.read_bytes()
    assert client.get("/api/me/avatar.jpg?u=uid-ana").status_code == 404  # sin llave
    assert client.get(url.replace("uid-ana", "uid-beto")).status_code == 404  # la llave es de otra persona
    assert client.get("/api/me", headers=as_("beto")).json()["avatar_url"] is None


def test_avatar_rejects_wrong_type_size_and_garbage(client: TestClient) -> None:
    def send(name: str, data: bytes, mime: str):
        return client.post("/api/me/avatar", files={"avatar": (name, io.BytesIO(data), mime)}, headers=as_("ana"))

    assert send("a.gif", picture(), "image/gif").status_code == 422
    assert send("a.png", picture(), "text/plain").status_code == 422
    assert send("a.png", b"no soy una imagen", "image/png").status_code == 422
    big = send("a.jpg", b"\xff\xd8" + b"\x00" * (2 * 1024 * 1024), "image/jpeg")
    assert big.status_code == 413
    assert client.get("/api/me", headers=as_("ana")).json()["avatar_url"] is None
    assert send("a.webp", picture(300, 600, ".webp"), "image/webp").status_code == 200


def test_avatar_delete_removes_the_file(client: TestClient, tmp_path: Path) -> None:
    client.post("/api/me/avatar", files={"avatar": ("yo.jpg", io.BytesIO(picture(fmt=".jpg")), "image/jpeg")}, headers=as_("ana"))
    assert client.delete("/api/me/avatar", headers=as_("ana")).json()["avatar_url"] is None
    assert not (tmp_path / "api_data" / "avatars" / "uid-ana.jpg").exists()


# ----- calidad de vista previa -----


def test_preview_quality_maps_to_sides() -> None:
    from vfxglow.api.previews import sides_for

    assert sides_for("alta") == (640, 480) and sides_for("rapida") == (480, 360)


@pytest.fixture()
def editor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from test_editor_api import FPS, FRAMES, EditorPipeline

    sides: list[int | None] = []

    def render_preview(self, script, dest, window, events=None, max_side=None):
        sides.append(max_side)
        dest.write_bytes(b"vista")
        return window[1] - window[0] + 1

    monkeypatch.setattr("vfxglow.pipeline.Pipeline", EditorPipeline)
    monkeypatch.setattr(EditorPipeline, "render_preview", render_preview, raising=False)
    monkeypatch.setattr(limits, "probe_video", lambda path: limits.VideoInfo(duration_s=2.0, width=64, height=96, fps=FPS, codec="h264"))
    monkeypatch.setattr(server, "_video_timing", lambda job: (FPS, FRAMES))
    monkeypatch.setenv("VEXORA_AUTH", "off")
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", server.CONFIG))
    monkeypatch.setattr(server, "_previews", None)
    return TestClient(server.app), sides


def test_editor_preview_uses_the_quality_the_user_chose(editor) -> None:
    from test_editor_api import _done, _ready, _style

    client, sides = editor
    job = _done(client)
    shown = _ready(client, job["id"], client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(1)], "at": 1.0}).json()["preview_id"])
    assert shown["status"] == "ready" and sides == [640]
    client.patch("/api/me", json={"preferences": {"preview_quality": "rapida"}})
    shown = _ready(client, job["id"], client.post(f"/api/jobs/{job['id']}/preview", json={"edits": [_style(1)], "at": 1.0}).json()["preview_id"])
    assert shown["status"] == "ready" and sides == [640, 480]  # otro tamaño: no sale de la caché del anterior


def test_studio_preview_uses_the_quality_the_user_chose(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import test_studio_preview as studio

    monkeypatch.setattr("vfxglow.pipeline.Pipeline", studio.FakePipeline)
    studio.FakePipeline.renders, studio.FakePipeline.gate = [], None
    monkeypatch.setitem(studio.USERS, "ana", USERS["ana"])
    upload_id = studio.upload(client, "ana")
    client.patch("/api/me", json={"preferences": {"preview_quality": "rapida"}}, headers=as_("ana"))
    created = studio.ask(client, upload_id, "ana")
    assert studio.finished(client, upload_id, created.json()["preview_id"], "ana")["status"] == "ready"
    assert studio.FakePipeline.renders[-1]["max_side"] == 360


# ----- avisos -----


def test_a_finished_job_creates_a_notification_only_its_owner_sees(client: TestClient) -> None:
    job = make_job(client, "ana")
    ana = client.get("/api/notifications", headers=as_("ana")).json()
    assert ana["unread"] == 1 and ana["items"][0]["kind"] == "job_done" and ana["items"][0]["job_id"] == job["id"] and not ana["items"][0]["read"]
    assert "clip" in ana["items"][0]["text"]
    assert client.get("/api/notifications", headers=as_("beto")).json() == {"items": [], "unread": 0}
    assert set(ana["items"][0]) == {"id", "kind", "title", "text", "job_id", "created", "read"}  # sin el uid


def test_a_failed_job_notifies_and_the_processing_pref_is_respected(client: TestClient) -> None:
    FakePipeline.fail = True
    make_job(client, "ana")
    assert client.get("/api/notifications", headers=as_("ana")).json()["items"][0]["kind"] == "job_failed"
    FakePipeline.fail = False
    client.patch("/api/me", json={"notifications": {"processing": False}}, headers=as_("ana"))
    make_job(client, "ana")
    assert len(client.get("/api/notifications", headers=as_("ana")).json()["items"]) == 1  # el de ahora no se creó


def test_mark_read_by_ids_all_and_never_someone_elses(client: TestClient) -> None:
    first, second = make_job(client, "ana"), make_job(client, "ana")
    make_job(client, "beto")
    items = client.get("/api/notifications", headers=as_("ana")).json()["items"]
    assert [i["job_id"] for i in items] == [second["id"], first["id"]]  # el más nuevo primero
    beto_item = client.get("/api/notifications", headers=as_("beto")).json()["items"][0]
    after = client.post("/api/notifications/read", json={"ids": [items[0]["id"], beto_item["id"]]}, headers=as_("ana")).json()
    assert after["unread"] == 1
    assert client.get("/api/notifications", headers=as_("beto")).json()["unread"] == 1  # el de Beto sigue sin leer
    assert client.post("/api/notifications/read", json={"all": True}, headers=as_("ana")).json()["unread"] == 0
    assert client.post("/api/notifications/read", json={}, headers=as_("ana")).status_code == 422


def test_only_the_last_notifications_are_kept(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow.api import notifications

    docs = server.jobs().docs
    for i in range(notifications.KEEP + 5):
        notifications.notify(docs, "uid-ana", "job_done", f"t{i}", "x")
        time.sleep(0.001)
    items = client.get("/api/notifications", headers=as_("ana")).json()["items"]
    assert len(items) == notifications.KEEP and items[0]["title"] == f"t{notifications.KEEP + 4}"
    assert len(docs.query("notifications", where={"uid": "uid-ana"})) == notifications.KEEP


# ----- borrar la cuenta -----


def delete_account(client: TestClient, who: str, confirm: str | None = "ELIMINAR"):
    return client.request("DELETE", "/api/me", json={"confirm": confirm} if confirm is not None else None, headers=as_(who))


def test_deleting_the_account_requires_the_confirmation_word(client: TestClient) -> None:
    job = make_job(client, "ana")
    assert delete_account(client, "ana", "eliminar").status_code == 422
    assert delete_account(client, "ana", "").status_code == 422
    assert delete_account(client, "ana", None).status_code == 422
    assert client.get(f"/api/jobs/{job['id']}", headers=as_("ana")).status_code == 200


def test_deleting_the_account_removes_everything_of_that_user_and_nothing_else(client: TestClient, tmp_path: Path) -> None:
    root = tmp_path / "api_data"
    docs = server.jobs().docs
    ana_job, ana_second = make_job(client, "ana"), make_job(client, "ana")
    beto_job = make_job(client, "beto")
    client.patch("/api/me", json={"username": "ana_x", "bio": "hola"}, headers=as_("ana"))
    client.patch("/api/me", json={"username": "beto_x"}, headers=as_("beto"))
    client.post("/api/me/avatar", files={"avatar": ("a.png", io.BytesIO(picture()), "image/png")}, headers=as_("ana"))
    client.post("/api/me/avatar", files={"avatar": ("a.png", io.BytesIO(picture()), "image/png")}, headers=as_("beto"))
    client.post(f"/api/jobs/{ana_job['id']}/share", headers=as_("ana"))
    beto_share = client.post(f"/api/jobs/{beto_job['id']}/share", headers=as_("beto")).json()
    upload = client.post("/api/uploads", files={"video": ("u.mp4", io.BytesIO(b"\x00" * 64), "video/mp4")}, headers=as_("ana")).json()
    assert (root / "outputs" / f"{ana_job['id']}.mp4").exists()

    summary = delete_account(client, "ana").json()
    assert summary["jobs"] == 2 and summary["uploads"] == 1 and summary["shares"] == 1 and summary["notifications"] == 2 and summary["avatar"] == 1 and summary["profile"] == 1
    assert client.get("/api/jobs", headers=as_("ana")).json() == []
    for job in (ana_job, ana_second):
        assert not (root / "outputs" / f"{job['id']}.mp4").exists() and not (root / "uploads" / job["id"]).exists()
    assert docs.query("jobs", where={"owner": "uid-ana"}) == [] and docs.query("uploads", where={"owner": "uid-ana"}) == []
    assert docs.query("notifications", where={"uid": "uid-ana"}) == [] and docs.query("shares", where={"uid": "uid-ana"}) == []
    assert docs.get("users", "uid-ana") is None and docs.get("usernames", "ana_x") is None
    assert not (root / "avatars" / "uid-ana.jpg").exists()
    assert upload["id"] not in {d["id"] for d in docs.query("uploads")}

    # Lo de Beto, intacto.
    assert [j["id"] for j in client.get("/api/jobs", headers=as_("beto")).json()] == [beto_job["id"]]
    assert (root / "outputs" / f"{beto_job['id']}.mp4").exists() and (root / "avatars" / "uid-beto.jpg").exists()
    assert client.get("/api/me", headers=as_("beto")).json()["username"] == "beto_x"
    assert client.get(f"/api/public/{beto_share['token']}").status_code == 200
    assert len(client.get("/api/notifications", headers=as_("beto")).json()["items"]) == 1
    assert client.patch("/api/me", json={"username": "ana_x"}, headers=as_("beto")).status_code == 200  # el nombre quedó libre

    # Idempotente.
    again = delete_account(client, "ana").json()
    assert again["jobs"] == again["uploads"] == again["shares"] == again["notifications"] == again["profile"] == 0


def test_deleting_the_account_cancels_running_and_queued_jobs(client: TestClient) -> None:
    FakePipeline.block = True
    running = make_job(client, "ana", wait=False)
    for _ in range(200):
        if client.get(f"/api/jobs/{running['id']}", headers=as_("ana")).json()["status"] == "running":
            break
        time.sleep(0.02)
    queued = make_job(client, "ana", wait=False)
    summary = delete_account(client, "ana").json()
    assert summary["jobs"] == 2 and summary["pending"] == 0
    assert client.get("/api/jobs", headers=as_("ana")).json() == []
    assert server.jobs().get(queued["id"]) is None and server.jobs().get(running["id"]) is None


def test_delete_account_emits_a_hashed_telemetry_event(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow import telemetry

    events = []
    monkeypatch.setattr(telemetry, "event", lambda name, **fields: events.append((name, fields)))
    delete_account(client, "ana")
    name, fields = next(e for e in events if e[0] == "user.deleted")
    assert fields["usr"]["id"].startswith("sha256:") and "uid-ana" not in str(fields)


# ----- enlaces públicos -----


def test_share_create_is_idempotent_and_needs_a_finished_job_of_yours(client: TestClient) -> None:
    job = make_job(client, "ana")
    first = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana"))
    assert first.status_code == 200 and len(first.json()["token"]) >= 32 and first.json()["path"] == f"/v/{first.json()['token']}"
    assert client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"] == first.json()["token"]
    assert client.get(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"] == first.json()["token"]
    # Ajeno: no existe para Beto; ni verlo, ni crearlo, ni revocarlo.
    for call in (client.get, client.post, client.delete):
        assert call(f"/api/jobs/{job['id']}/share", headers=as_("beto")).status_code == 404
    assert client.get(f"/api/public/{first.json()['token']}").status_code == 200  # sigue activo
    FakePipeline.fail = True
    failed = make_job(client, "ana")
    assert client.post(f"/api/jobs/{failed['id']}/share", headers=as_("ana")).status_code == 409


def test_public_endpoints_work_without_login_and_count_views(client: TestClient) -> None:
    job = make_job(client, "ana")
    client.patch(f"/api/jobs/{job['id']}", json={"title": "Mi baile"}, headers=as_("ana"))
    token = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"]
    page = client.get(f"/api/public/{token}")  # sin cabecera de sesión
    assert page.status_code == 200
    body = page.json()
    assert body["title"] == "Mi baile" and body["style_title"] and body["video_url"] == f"/api/public/{token}/video.mp4" and body["created"]
    assert set(body) == {"title", "style_title", "duration", "created", "video_url"}  # sin uid ni rutas
    assert page.headers["referrer-policy"] == "no-referrer" and "noindex" in page.headers["x-robots-tag"]
    video = client.get(body["video_url"])
    assert video.status_code == 200 and video.headers["content-type"] == "video/mp4" and video.content
    assert "noindex" in video.headers["x-robots-tag"]
    assert client.get(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["views"] == 1  # el video no cuenta como visita
    client.get(f"/api/public/{token}")
    assert client.get(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["views"] == 2


def test_revoking_stops_the_link_at_once_and_a_new_one_differs(client: TestClient) -> None:
    job = make_job(client, "ana")
    token = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"]
    assert client.delete(f"/api/jobs/{job['id']}/share", headers=as_("ana")).status_code == 204
    gone = client.get(f"/api/public/{token}")
    unknown = client.get("/api/public/no-existe-este-token")
    assert gone.status_code == unknown.status_code == 404 and gone.json() == unknown.json()  # sin pistas de cuál es cuál
    assert "noindex" in gone.headers["x-robots-tag"]
    assert client.get(f"/api/public/{token}/video.mp4").status_code == 404
    assert client.get(f"/api/jobs/{job['id']}/share", headers=as_("ana")).status_code == 404
    assert client.delete(f"/api/jobs/{job['id']}/share", headers=as_("ana")).status_code == 204  # idempotente
    assert client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"] != token


def test_deleting_the_job_deletes_its_share(client: TestClient) -> None:
    job = make_job(client, "ana")
    token = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"]
    assert client.delete(f"/api/jobs/{job['id']}", headers=as_("ana")).status_code == 204
    assert client.get(f"/api/public/{token}").status_code == 404
    assert server.jobs().docs.query("shares", where={"job_id": job["id"]}) == []


# ----- guardar en la nube y vencimiento -----


def test_free_plan_can_only_download_and_paid_plans_save_and_share(client: TestClient) -> None:
    job = make_job(client, "caro")  # Free: el guardado se intenta y no ocurre
    assert job["status"] == "done" and not job["saved"]
    assert job["keep_until"] == pytest.approx(job["finished"] + 7 * 24 * 3600, abs=5)
    assert client.post(f"/api/jobs/{job['id']}/save", headers=as_("caro")).status_code == 403
    assert client.post(f"/api/jobs/{job['id']}/share", headers=as_("caro")).status_code == 403
    assert client.get(f"/api/jobs/{job['id']}", headers=as_("caro")).json()["output_url"]  # descargar sí
    me = client.get("/api/me", headers=as_("caro")).json()["plan"]
    assert me["id"] == "free" and not me["cloud_save"] and not me["share"] and me["unsaved_days"] == 7
    assert client.get("/api/me", headers=as_("ana")).json()["plan"]["cloud_save"]


def test_sharing_needs_the_video_saved_and_unsaving_revokes_the_link(client: TestClient) -> None:
    job = make_job(client, "ana", save=False)
    assert client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).status_code == 409  # sin guardar
    saved = client.post(f"/api/jobs/{job['id']}/save", headers=as_("ana")).json()
    assert saved["saved"] and saved["keep_until"] is None
    token = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"]
    unsaved = client.delete(f"/api/jobs/{job['id']}/save", headers=as_("ana")).json()
    assert not unsaved["saved"] and unsaved["keep_until"] > time.time() + 6 * 24 * 3600
    assert client.get(f"/api/public/{token}").status_code == 404


def test_expired_unsaved_videos_are_deleted_but_saved_and_older_ones_stay(client: TestClient) -> None:
    store = server.jobs()
    unsaved = make_job(client, "ana", save=False)
    saved = make_job(client, "ana")
    legacy = make_job(client, "ana", save=False)
    store.docs.update("jobs", legacy["id"], {"keep_until": None})  # hecho antes de la regla: no vence
    store._last_expire = 0.0
    assert store.expire(now=time.time() + 8 * 24 * 3600) == 1
    left = {job.id for job in store.list("uid-ana")}
    assert unsaved["id"] not in left and {saved["id"], legacy["id"]} <= left


# ----- límites de las páginas públicas -----


def test_public_page_and_video_have_per_ip_limits_with_retry_after(client: TestClient) -> None:
    job = make_job(client, "ana")
    token = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"]
    page, video = ratelimit.PAGE_LIMIT[0], ratelimit.VIDEO_LIMIT[0]
    assert all(client.get(f"/api/public/{token}").status_code == 200 for _ in range(page))
    over = client.get(f"/api/public/{token}")
    assert over.status_code == 429 and over.headers["retry-after"] == "60"
    # El video tiene su propio cupo: la página llena no impide verlo.
    assert all(client.get(f"/api/public/{token}/video.mp4").status_code == 200 for _ in range(video))
    assert client.get(f"/api/public/{token}/video.mp4").status_code == 429


def test_many_unknown_links_block_that_ip_for_a_while(client: TestClient) -> None:
    job = make_job(client, "ana")
    token = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"]
    misses = ratelimit.MISS_LIMIT[0]
    for i in range(misses + 1):
        assert client.get(f"/api/public/inventado{i}").status_code == 404
    blocked = client.get(f"/api/public/{token}")  # ni siquiera un enlace válido, mientras dure
    assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 800


def test_client_ip_trusts_only_the_configured_proxies(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ratelimit.client_ip("1.1.1.1, 2.2.2.2", "9.9.9.9") == "9.9.9.9"  # sin proxies: la conexión
    monkeypatch.setenv(ratelimit.PROXY_HOPS_ENV, "1")
    assert ratelimit.client_ip("1.1.1.1, 2.2.2.2", "9.9.9.9") == "2.2.2.2"  # la que agregó Cloud Run
    assert ratelimit.client_ip(None, "9.9.9.9") == "9.9.9.9"


def test_daily_view_cap_per_link_notifies_the_owner_once(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "_daily_cap", lambda item: 2)
    job = make_job(client, "ana")
    token = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"]
    assert [client.get(f"/api/public/{token}").status_code for _ in range(3)] == [200, 200, 429]
    capped = client.get(f"/api/public/{token}")
    assert capped.json()["detail"] == server.DAILY_CAP
    assert client.get(f"/api/public/{token}/video.mp4").status_code == 429
    notes = [n for n in client.get("/api/notifications", headers=as_("ana")).json()["items"] if n["kind"] == "share_limit"]
    assert len(notes) == 1


def test_links_stop_working_when_the_owner_no_longer_has_a_sharing_plan(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    job = make_job(client, "ana")
    token = client.post(f"/api/jobs/{job['id']}/share", headers=as_("ana")).json()["token"]
    monkeypatch.setenv("VEXORA_PLAN_GRANTS", "uid-beto:pro")  # Ana vuelve a Free
    assert client.get(f"/api/public/{token}").status_code == 404

