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
    assert any("Analizados 25/50" in line for line in job["log"])
    assert client.get(job["output_url"]).content == b"\x00" * 64
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


# ----- cuentas (Firebase Auth) -----

USERS = {"token-ana": ("uid-ana", "ana@example.com"), "token-beto": ("uid-beto", "beto@example.com")}


@pytest.fixture()
def secure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """API con autenticación: dos usuarios de mentira en lugar de verificar con Google."""
    from vfxglow.api import auth

    monkeypatch.setattr("vfxglow.pipeline.Pipeline", FakePipeline)
    monkeypatch.setenv("VEXORA_AUTH", "on")

    def fake_verify(token: str) -> auth.User:
        if token not in USERS:
            from fastapi import HTTPException

            raise HTTPException(401, "Sesión no válida")
        uid, email = USERS[token]
        return auth.User(uid=uid, email=email)

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
    assert [j["id"] for j in secure.get("/api/jobs", headers=_as("token-ana")).json()] == [legacy.id]
    assert secure.get("/api/jobs", headers=_as("token-beto")).json() == []


def test_without_auth_the_server_only_listens_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    from vfxglow.api.auth import check_bind

    monkeypatch.setenv("VEXORA_AUTH", "off")
    check_bind("127.0.0.1")
    with pytest.raises(SystemExit):
        check_bind("0.0.0.0")
