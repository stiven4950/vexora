"""Autenticación de la API: sesión de Google con Firebase Auth (docs/plan_cuentas_y_nube.md, fase 1).

- Las peticiones llevan `Authorization: Bearer <ID token de Firebase>`. El token se verifica con
  `firebase-admin` contra el proyecto `VEXORA_FIREBASE_PROJECT` (firma, caducidad y audiencia); no
  hace falta la cuenta de servicio para esto.
- Los videos, las miniaturas y el progreso (SSE) se piden desde `<video>`, `<img>` y
  `EventSource`, que no mandan cabeceras. Para esos, la API entrega URLs con una llave corta
  (`?k=`), firmada con `VEXORA_SECRET`, ligada al trabajo y al usuario, que caduca en MEDIA_TTL_S.
  El token de Google nunca va en una URL.
- `VEXORA_AUTH=off` desactiva la verificación (usuario fijo LOCAL_UID) para desarrollo y pruebas.
  El servidor se niega a arrancar así si no escucha solo en la máquina local.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from functools import lru_cache

from fastapi import Header, HTTPException
from pydantic import BaseModel

AUTH_ENV = "VEXORA_AUTH"
PROJECT_ENV = "VEXORA_FIREBASE_PROJECT"
SECRET_ENV = "VEXORA_SECRET"
LOCAL_UID = "local"
MEDIA_TTL_S = 6 * 3600


class User(BaseModel):
    uid: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None


def auth_enabled() -> bool:
    return os.environ.get(AUTH_ENV, "on").strip().lower() not in ("off", "0", "false", "no")


@lru_cache(maxsize=1)
def _firebase():
    import firebase_admin

    project = os.environ.get(PROJECT_ENV)
    if not project:
        raise RuntimeError(f"Falta {PROJECT_ENV} (el ID del proyecto de Firebase, p. ej. vexora-dev)")
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": project})


def verify(token: str) -> User:
    from firebase_admin import auth

    try:
        claims = auth.verify_id_token(token, app=_firebase(), clock_skew_seconds=10)
    except Exception as error:  # firma, caducidad, proyecto equivocado...
        raise HTTPException(401, "Sesión no válida o vencida. Vuelve a entrar.") from error
    return User(uid=claims["uid"], email=claims.get("email"), name=claims.get("name"), picture=claims.get("picture"))


def current_user(authorization: str | None = Header(default=None)) -> User:
    """Dependencia de FastAPI: el usuario de la sesión, o 401."""
    if not auth_enabled():
        return User(uid=LOCAL_UID, name="Local")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Inicia sesión para continuar.")
    return verify(authorization.split(" ", 1)[1].strip())


# ----- llaves cortas para los archivos -----


@lru_cache(maxsize=1)
def _secret() -> bytes:
    # Sin VEXORA_SECRET, una al azar por proceso: al reiniciar, las URLs viejas dejan de valer
    # (la web las vuelve a pedir).
    return (os.environ.get(SECRET_ENV) or secrets.token_hex(32)).encode()


def _sign(job_id: str, uid: str, expires: int) -> str:
    digest = hmac.new(_secret(), f"{job_id}:{uid}:{expires}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:18]).decode().rstrip("=")


def media_key(job_id: str, uid: str, now: float | None = None) -> str:
    expires = int((now or time.time()) + MEDIA_TTL_S)
    return f"{expires}.{_sign(job_id, uid, expires)}"


def media_owner(job_id: str, key: str | None, owner: str | None) -> None:
    """La llave `key` abre los archivos de `job_id` para su dueño `owner`; si no, 404."""
    if not auth_enabled():
        return
    try:
        expires_text, signature = (key or "").split(".", 1)
        expires = int(expires_text)
    except ValueError as error:
        raise HTTPException(404, "Trabajo no encontrado") from error
    if expires < time.time() or not owner or not hmac.compare_digest(signature, _sign(job_id, owner, expires)):
        raise HTTPException(404, "Trabajo no encontrado")


def check_bind(host: str) -> None:
    """Sin autenticación solo se puede escuchar en la máquina local."""
    if not auth_enabled() and host not in ("127.0.0.1", "localhost", "::1"):
        raise SystemExit(f"{AUTH_ENV}=off solo se permite con el servidor en 127.0.0.1, no en {host}.")
