"""API: estilos, ciclo de vida de un trabajo, progreso y variaciones (pipeline simulado)."""

from __future__ import annotations

import io
import logging
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vfxglow import telemetry  # noqa: E402
from vfxglow.api import limits, server  # noqa: E402
from vfxglow.api.jobs import JobStore  # noqa: E402


class FakePipeline:
    """Pipeline de mentira. Como el de verdad, escribe el video en un archivo aparte y lo
    renombra, y el mismo video (aunque sea otra versión) comparte carpeta de análisis y salida."""

    fail = False

    def __init__(self, config, video: Path, **kwargs) -> None:
        self.kwargs = kwargs
        self.run_dir = video.parent.parent.parent / "runs" / video.parent.name

    def run(self) -> Path:
        log = logging.getLogger("vfxglow.analysis")
        with telemetry.span("analyze"):
            log.info("Analizando %s en cpu", "/Users/alguien/videos/x.mp4")
            log.info("Analizados 25/50 fotogramas")
            if FakePipeline.fail:
                raise RuntimeError("falló a propósito en /Users/alguien/runs/x")
        logging.getLogger("vfxglow").info("Guion pelea con 3 efectos")
        logging.getLogger("vfxglow").info("Compuestos 50/50 fotogramas")
        out = self.run_dir / "output" / "pelea.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_name("pelea.partial.mp4")
        partial.write_bytes(f"toma={self.kwargs.get('take', 0)} semilla={self.kwargs.get('seed')}".encode())
        partial.replace(out)
        return out


def fake_probe(path: Path) -> limits.VideoInfo:
    return limits.VideoInfo(duration_s=10.0, width=720, height=1280, fps=30.0, codec="h264")


@pytest.fixture(autouse=True)
def _reset_fake_pipeline() -> None:
    FakePipeline.fail = False


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    monkeypatch.setattr(limits, "probe_video", fake_probe)
    monkeypatch.setenv("VEXORA_AUTH", "off")
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
    # La consola es solo para ver el proceso en vivo: un trabajo terminado no la expone.
    assert job["log"] == [] and job["metrics"]["stages"]["analyze"] >= 0 and "queue_wait_ms" in job["metrics"]
    assert client.get(job["output_url"]).content == b"toma=0 semilla=7"
    assert "attachment" in client.get(job["output_url"] + "&download=true").headers["content-disposition"]
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


def test_versions_without_dice(client: TestClient) -> None:
    """Sin semilla: el trabajo usa la mejor coreografía y cada "otra versión" pide la siguiente."""
    job = _wait(client, client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"fake"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
    assert job["seed"] is None and job["take"] == 0
    second = client.post(f"/api/jobs/{job['id']}/variations", json={"style": "pelea"}).json()
    third = client.post(f"/api/jobs/{second['id']}/variations", json={"style": "pelea"}).json()
    assert (second["take"], third["take"]) == (1, 2)
    assert second["parent"] == third["parent"] == job["id"]
    other_style = client.post(f"/api/jobs/{job['id']}/variations", json={"style": "baile_neon"}).json()
    assert other_style["take"] == 0  # otro estilo: se empieza por la mejor


def test_seasons_listed_and_used_by_jobs(client: TestClient) -> None:
    listed = client.get("/api/seasons").json()
    assert {"halloween", "navidad"} <= {s["id"] for s in listed}
    assert sum(s["suggested"] for s in listed) <= 1
    job = client.post("/api/jobs", files={"video": ("c.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea", "season": "halloween"}).json()
    assert job["season"] == "halloween"
    bad = client.post("/api/jobs", files={"video": ("c.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea", "season": "marte"})
    assert bad.status_code == 422


def test_fire_and_bolt_looks_listed_and_passed_to_the_pipeline(client: TestClient) -> None:
    looks = client.get("/api/looks").json()
    assert {"clasico", "azul", "pixel"} <= {x["id"] for x in looks["fuego"]}
    assert {"cian", "violeta"} <= {x["id"] for x in looks["rayo"]}
    response = client.post("/api/jobs", files={"video": ("c.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "avatar", "fire_style": "azul", "bolt_style": "violeta"})
    job = _wait(client, response.json()["id"])
    assert (job["fire_style"], job["bolt_style"]) == ("azul", "violeta")
    variation = client.post(f"/api/jobs/{job['id']}/variations", json={"style": "avatar", "fire_style": "pixel"}).json()
    assert (variation["fire_style"], variation["bolt_style"]) == ("pixel", "violeta")  # el rayo, el del origen
    bad = client.post("/api/jobs", files={"video": ("c.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "avatar", "fire_style": "lava"})
    assert bad.status_code == 422


# ----- cuentas (Firebase Auth) -----

USERS = {
    "token-ana": ("uid-ana", "ana@example.com", True),
    "token-beto": ("uid-beto", "beto@example.com", True),
    # Alguien que registró con contraseña el correo de Ana sin poder verificarlo.
    "token-impostor": ("uid-impostor", "ana@example.com", False),
}


@pytest.fixture()
def secure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """API con autenticación: dos usuarios de mentira en lugar de verificar con Google."""
    from vfxglow.api import auth

    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    monkeypatch.setattr(limits, "probe_video", fake_probe)
    monkeypatch.setenv("VEXORA_AUTH", "on")

    def fake_verify(token: str) -> auth.User:
        if token not in USERS:
            from fastapi import HTTPException

            raise HTTPException(401, "Sesión no válida")
        uid, email, verified = USERS[token]
        return auth.User(uid=uid, email=email, email_verified=verified)

    monkeypatch.setattr(auth, "verify", fake_verify)
    monkeypatch.setattr(server, "store", JobStore(tmp_path / "api_data", server.CONFIG))
    return TestClient(server.app)


def _as(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload(client: TestClient, token: str) -> dict:
    files = {"video": ("clip.mp4", io.BytesIO(b"\x00" * 128), "video/mp4")}
    response = client.post("/api/jobs", files=files, data={"style": "pelea"}, headers=_as(token))
    assert response.status_code == 201, response.text
    return response.json()


def test_without_a_session_the_api_asks_to_sign_in(secure: TestClient) -> None:
    assert secure.get("/api/jobs").status_code == 401
    assert secure.get("/api/jobs", headers=_as("token-falso")).status_code == 401
    assert secure.get("/api/styles").status_code == 200  # el catálogo de estilos es público
    assert secure.get("/api/me", headers=_as("token-ana")).json()["email"] == "ana@example.com"


def test_each_user_sees_only_their_own_jobs(secure: TestClient) -> None:
    ana = _upload(secure, "token-ana")
    beto = _upload(secure, "token-beto")
    assert [j["id"] for j in secure.get("/api/jobs", headers=_as("token-ana")).json()] == [ana["id"]]
    assert [j["id"] for j in secure.get("/api/jobs", headers=_as("token-beto")).json()] == [beto["id"]]
    # El trabajo de otro no existe para ti: ni verlo, ni variarlo, ni borrarlo.
    assert secure.get(f"/api/jobs/{ana['id']}", headers=_as("token-beto")).status_code == 404
    assert secure.post(f"/api/jobs/{ana['id']}/variations", json={"style": "pelea"}, headers=_as("token-beto")).status_code == 404
    assert secure.delete(f"/api/jobs/{ana['id']}", headers=_as("token-beto")).status_code == 404
    assert "owner" not in secure.get(f"/api/jobs/{ana['id']}", headers=_as("token-ana")).json() or secure.get(f"/api/jobs/{ana['id']}", headers=_as("token-ana")).json()["owner"] is None


def test_files_open_with_the_short_key_only(secure: TestClient) -> None:
    ana = _upload(secure, "token-ana")
    beto = _upload(secure, "token-beto")
    assert secure.get(ana["original_url"]).status_code == 200
    assert secure.get(f"/api/jobs/{ana['id']}/original").status_code == 404
    # La llave de un trabajo no abre otro.
    other = beto["original_url"].replace(beto["id"], ana["id"])
    assert secure.get(other).status_code == 404


def test_a_variation_belongs_to_the_owner_of_the_video(secure: TestClient) -> None:
    ana = _upload(secure, "token-ana")
    variation = secure.post(f"/api/jobs/{ana['id']}/variations", json={"style": "pelea"}, headers=_as("token-ana")).json()
    assert {j["id"] for j in secure.get("/api/jobs", headers=_as("token-ana")).json()} == {ana["id"], variation["id"]}
    assert secure.get("/api/jobs", headers=_as("token-beto")).json() == []


def test_jobs_from_before_accounts_are_adopted_by_the_legacy_owner(secure: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    store = server.store
    legacy = store.create("viejo.mp4", io.BytesIO(b"\x00" * 64), "catalog", "pelea", None)
    assert legacy.owner is None
    assert secure.get("/api/jobs", headers=_as("token-beto")).json() == []
    monkeypatch.setenv("VEXORA_LEGACY_OWNER", "ana@example.com")
    # Con el correo sin verificar no se adopta nada, aunque coincida.
    assert secure.get("/api/jobs", headers=_as("token-impostor")).json() == []
    assert [j["id"] for j in secure.get("/api/jobs", headers=_as("token-ana")).json()] == [legacy.id]
    assert secure.get("/api/jobs", headers=_as("token-beto")).json() == []


def test_without_auth_the_server_only_listens_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow.api.auth import check_bind

    monkeypatch.setenv("VEXORA_AUTH", "off")
    check_bind("127.0.0.1")
    with pytest.raises(SystemExit):
        check_bind("0.0.0.0")


def test_wardrobe_is_chosen_by_the_user_and_kept_in_versions(client: TestClient) -> None:
    files = {"video": ("clip.mp4", io.BytesIO(b"\x00" * 128), "video/mp4")}
    job = client.post("/api/jobs", files=files, data={"style": "pelea", "wardrobe": '{"*": "vestido"}'}).json()
    assert job["wardrobe"] == {"*": "vestido"}
    same = client.post(f"/api/jobs/{job['id']}/variations", json={"style": "pelea"}).json()
    assert same["wardrobe"] == {"*": "vestido"}
    per_person = client.post(f"/api/jobs/{job['id']}/variations", json={"style": "pelea", "wardrobe": {"person_0": "chaqueta", "person_1": "vestido"}}).json()
    assert per_person["wardrobe"] == {"person_0": "chaqueta", "person_1": "vestido"}
    bad = client.post(f"/api/jobs/{job['id']}/variations", json={"style": "pelea", "wardrobe": {"person_0": "armadura"}})
    assert bad.status_code == 422


def test_avatar_presets_are_one_catalog() -> None:
    from vfxglow.api.server import styles
    from vfxglow.config import PRESET_ALIASES

    listed = {(s.kind, s.name) for s in styles()}
    assert ("catalog", "avatar") in listed
    assert not any(name in PRESET_ALIASES for _kind, name in listed)
    assert PRESET_ALIASES["avatar_fire"] == PRESET_ALIASES["avatar_storm"] == "avatar"


# ----- Fase 0: versiones, fallos, borrado, cuotas y trazabilidad -----


def test_each_version_keeps_its_own_video(client: TestClient) -> None:
    """"Otra versión" no pisa el MP4 de la anterior aunque compartan carpeta en runs/."""
    first = _wait(client, client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
    second = _wait(client, client.post(f"/api/jobs/{first['id']}/variations", json={"style": "pelea"}).json()["id"])
    assert client.get(second["output_url"]).content == b"toma=1 semilla=None"
    assert client.get(first["output_url"]).content == b"toma=0 semilla=None"


def test_a_failure_says_what_happened_without_internals_and_can_be_retried(client: TestClient) -> None:
    FakePipeline.fail = True
    job = _wait(client, client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
    assert job["status"] == "failed" and job["error_code"] == "analysis_failed"
    assert "cuerpo entero" in job["error"]
    assert "a propósito" not in str(job) and "/Users/" not in str(job)
    FakePipeline.fail = False
    retried = client.post(f"/api/jobs/{job['id']}/retry")
    assert retried.status_code == 200 and retried.json()["id"] == job["id"]
    done = _wait(client, job["id"])
    assert done["status"] == "done" and done["error"] is None and done["trace_id"] == job["trace_id"]
    assert client.post(f"/api/jobs/{job['id']}/retry").status_code == 409  # solo lo que falló


def test_the_live_console_hides_server_paths(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    store = server.store
    job = store.create("clip.mp4", io.BytesIO(b"x"), "catalog", "pelea", None)
    _wait(client, job.id)
    store._update(job.id, status="running", log=["Analizando /Users/alguien/videos/x.mp4 en cpu"])
    assert client.get(f"/api/jobs/{job.id}").json()["log"] == ["Analizando x.mp4 en cpu"]


def test_delete_removes_the_video_the_analysis_and_the_output(client: TestClient) -> None:
    job = _wait(client, client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
    stored = server.store.get(job["id"])
    paths = [Path(stored.run_dir), Path(stored.output), Path(stored.video_path)]
    assert all(path.exists() for path in paths)
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 204
    assert not any(path.exists() for path in paths)


def test_a_shared_analysis_survives_until_its_last_version_is_deleted(client: TestClient) -> None:
    first = _wait(client, client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
    second = _wait(client, client.post(f"/api/jobs/{first['id']}/variations", json={"style": "pelea"}).json()["id"])
    run_dir = Path(server.store.get(first["id"]).run_dir)
    assert client.delete(f"/api/jobs/{first['id']}").status_code == 204
    assert run_dir.exists() and client.get(second["output_url"]).status_code == 200
    assert client.delete(f"/api/jobs/{second['id']}").status_code == 204
    assert not run_dir.exists()


def test_a_job_in_progress_cannot_be_deleted(client: TestClient) -> None:
    job = _wait(client, client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
    server.store._update(job["id"], status="running")
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 409


def test_an_upload_is_cut_at_the_size_limit_without_leftovers(client: TestClient) -> None:
    from vfxglow.api.jobs import UploadTooLarge

    store = server.store
    with pytest.raises(UploadTooLarge):
        store.create("grande.mp4", io.BytesIO(b"\x00" * 100), "catalog", "pelea", None, max_bytes=10)
    assert list(store.uploads.iterdir()) == []


def test_daily_and_active_quotas(secure: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VEXORA_DAILY_JOBS", "1")
    _upload(secure, "token-ana")
    files = {"video": ("clip.mp4", io.BytesIO(b"\x00" * 128), "video/mp4")}
    again = secure.post("/api/jobs", files=files, data={"style": "pelea"}, headers=_as("token-ana"))
    assert again.status_code == 429 and "por hoy" in again.json()["detail"]
    _upload(secure, "token-beto")  # la cuota es de cada uno


def test_deep_analysis_only_for_allowed_accounts_and_with_a_daily_limit(secure: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def deep_upload(token: str):
        files = {"video": ("clip.mp4", io.BytesIO(b"\x00" * 128), "video/mp4")}
        return secure.post("/api/jobs", files=files, data={"style": "baile", "deep": "true"}, headers=_as(token))

    assert deep_upload("token-ana").status_code == 429  # nadie, si VEXORA_DEEP_ALLOW está vacío
    monkeypatch.setenv("VEXORA_DEEP_ALLOW", "ana@example.com")
    monkeypatch.setenv("VEXORA_DAILY_DEEP", "1")
    monkeypatch.setenv("VEXORA_MAX_ACTIVE_JOBS", "10")
    assert deep_upload("token-ana").status_code == 201
    assert deep_upload("token-ana").status_code == 429
    assert deep_upload("token-beto").status_code == 429


def test_video_files_are_checked_before_they_are_queued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import imageio_ffmpeg
    import numpy as np
    from fastapi import HTTPException

    clip = tmp_path / "clip.mp4"
    writer = imageio_ffmpeg.write_frames(str(clip), (64, 96), fps=10)
    writer.send(None)
    for _ in range(20):
        writer.send(np.zeros((96, 64, 3), dtype=np.uint8).tobytes())
    writer.close()
    info = limits.probe_video(clip)
    assert (info.width, info.height) == (64, 96) and 1.5 <= info.duration_s <= 2.5
    monkeypatch.setenv("VEXORA_MAX_VIDEO_SECONDS", "1")
    with pytest.raises(HTTPException) as too_long:
        limits.probe_video(clip)
    assert too_long.value.status_code == 422
    fake = tmp_path / "falso.mp4"
    fake.write_bytes(b"\x00" * 128)
    with pytest.raises(HTTPException):
        limits.probe_video(fake)


def test_every_request_is_traced_without_media_keys_and_has_security_headers(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    job = _wait(client, client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="vexora.events"):
        response = client.get(job["thumbnail_url"].replace("thumbnail", "original"))
    assert response.headers["X-Content-Type-Options"] == "nosniff" and response.headers["Referrer-Policy"] == "no-referrer"
    traced = [r.vexora for r in caplog.records if getattr(r, "vexora", {}).get("event") == "http.request"]
    assert traced and traced[-1]["http"]["route"] == "/api/jobs/{job_id}/original"
    assert "k=" not in str(traced)


def test_api_docs_are_not_served_in_production(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/openapi.json").status_code == 200
    monkeypatch.setenv("VEXORA_ENV", "prod")
    assert client.get("/openapi.json").status_code == 404 and client.get("/docs").status_code == 404


# ----- Fase 1: tiempo estimado, cola y límites visibles -----


def test_estimate_uses_measured_defaults_then_the_history_of_the_same_style(client: TestClient) -> None:
    store = server.store
    job = _wait(client, client.post("/api/jobs", files={"video": ("c.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
    assert store.get(job["id"]).video_seconds == 10.0
    fresh = store.get(job["id"])
    assert store.estimate(fresh) == 200  # 10 s × 20 s/s, sin historial propio todavía
    assert store.estimate(fresh.model_copy(update={"parent": "otro"})) == 110  # una versión: 11 s/s
    for _ in range(3):  # tres trabajos terminados del mismo estilo tardaron 5 s/s
        done = _wait(client, client.post("/api/jobs", files={"video": ("c.mp4", io.BytesIO(b"x"), "video/mp4")}, data={"style": "pelea"}).json()["id"])
        store._update(done["id"], metrics={"total_ms": 50_000})
    assert store.estimate(store.get(done["id"])) == 50
    assert store.estimate(fresh.model_copy(update={"video_seconds": None})) is None


def test_queue_position_counts_only_what_goes_before(client: TestClient) -> None:
    store = server.store
    first = store.create("a.mp4", io.BytesIO(b"x"), "catalog", "pelea", None)
    _wait(client, first.id)
    store._update(first.id, status="running")
    waiting = store.create("b.mp4", io.BytesIO(b"x"), "catalog", "pelea", None)
    later = store.create("c.mp4", io.BytesIO(b"x"), "catalog", "pelea", None)
    # Que el trabajador de fondo termine antes de forzar los estados: si no, pisa lo que pongo aquí.
    _wait(client, waiting.id)
    _wait(client, later.id)
    store._update(waiting.id, status="queued")
    store._update(later.id, status="queued", created=waiting.created + 1)
    view = client.get(f"/api/jobs/{later.id}").json()
    assert view["queue_ahead"] == 2 and view["estimate_s"] is None  # sin duración (create sin check)
    assert client.get(f"/api/jobs/{first.id}").json()["queue_ahead"] == 0


def test_limits_tell_the_web_what_it_can_warn_about(secure: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert secure.get("/api/limits").status_code == 401
    monkeypatch.setenv("VEXORA_MAX_VIDEO_SECONDS", "90")
    ana = secure.get("/api/limits", headers=_as("token-ana")).json()
    assert ana["max_video_seconds"] == 90 and ana["max_upload_mb"] == 500 and ana["deep_allowed"] is False
    monkeypatch.setenv("VEXORA_DEEP_ALLOW", "ana@example.com")
    assert secure.get("/api/limits", headers=_as("token-ana")).json()["deep_allowed"] is True
    assert secure.get("/api/limits", headers=_as("token-beto")).json()["deep_allowed"] is False


# ----- Mis proyectos: ficha del video, nombre del proyecto y etiquetas -----


def test_the_video_card_the_tags_and_the_project_name(client: TestClient) -> None:
    first = _wait(client, client.post("/api/jobs", files={"video": ("clip.mp4", io.BytesIO(b"x" * 300), "video/mp4")}, data={"style": "avatar", "season": "halloween"}).json()["id"])
    assert (first["video_width"], first["video_height"], first["video_bytes"]) == (720, 1280, 300)
    assert "avatar" in first["tags"] and "halloween" in first["tags"] and first["title"] is None
    second = _wait(client, client.post(f"/api/jobs/{first['id']}/variations", json={"style": "avatar"}).json()["id"])
    assert second["video_height"] == 1280  # la versión hereda la ficha del video
    renamed = client.patch(f"/api/jobs/{second['id']}", json={"title": "  Poderes de Avatar  "})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Poderes de Avatar"
    assert client.get(f"/api/jobs/{first['id']}").json()["title"] == "Poderes de Avatar"  # es del proyecto
    client.patch(f"/api/jobs/{first['id']}", json={"title": " "})
    assert client.get(f"/api/jobs/{second['id']}").json()["title"] is None  # vacío: vuelve al nombre del archivo
    assert client.patch("/api/jobs/nada", json={"title": "x"}).status_code == 404


def test_only_the_owner_renames_a_project(secure: TestClient) -> None:
    ana = _upload(secure, "token-ana")
    assert secure.patch(f"/api/jobs/{ana['id']}", json={"title": "mío"}, headers=_as("token-beto")).status_code == 404
    assert secure.patch(f"/api/jobs/{ana['id']}", json={"title": "mío"}, headers=_as("token-ana")).status_code == 200
