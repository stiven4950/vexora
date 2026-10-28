"""Perfil y ajustes de cada persona: colección `users` (por uid de Firebase) y `usernames`.

El perfil vive en el almacén de documentos (store/), nunca en un archivo suelto. Lo que viene del
token (correo, y el nombre o la foto de Google como respaldo) no se guarda aquí: la API lo lee de
la sesión. El nombre de usuario es único: `usernames/<nombre>` apunta a su dueño y se reclama con
una transacción, así dos personas no se llevan el mismo aunque pidan a la vez (ni en Firestore).
La foto va al almacén de archivos como `avatars/<uid>.jpg` (ver `avatar_key`).
"""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from vfxglow.store.docs import DELETE, DocStore

USERS = "users"
USERNAMES = "usernames"

# Versión vigente de los términos y la política de privacidad (web/src/legal): al cambiarlos, se
# sube y la persona vuelve a aceptarlos.
TERMS_VERSION = "2026-10"

USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,30}$")
NAME_MAX = 60
BIO_MAX = 200
AVATAR_MAX_BYTES = 2 * 1024 * 1024
AVATAR_SIDE = 512

# Países que se pueden elegir (ISO 3166-1 alfa-2): Colombia y Latinoamérica, España y Estados Unidos.
COUNTRIES: dict[str, str] = {
    "CO": "Colombia", "AR": "Argentina", "BO": "Bolivia", "BR": "Brasil", "CL": "Chile", "CR": "Costa Rica",
    "CU": "Cuba", "DO": "República Dominicana", "EC": "Ecuador", "SV": "El Salvador", "GT": "Guatemala",
    "HN": "Honduras", "MX": "México", "NI": "Nicaragua", "PA": "Panamá", "PY": "Paraguay", "PE": "Perú",
    "PR": "Puerto Rico", "UY": "Uruguay", "VE": "Venezuela", "ES": "España", "US": "Estados Unidos",
}

NOTIFICATION_KEYS = ("processing", "platform", "promotions")
DEFAULT_NOTIFICATIONS = {"processing": True, "platform": True, "promotions": False}
LANGUAGES = ("es",)
PREVIEW_QUALITIES = ("alta", "rapida")
THEMES = ("oscuro",)
DEFAULT_PREFERENCES = {"language": "es", "preview_quality": "alta", "theme": "oscuro"}


class ProfileError(ValueError):
    """Un dato del perfil no es válido; el mensaje (en español) llega a la persona (422)."""


class UsernameTaken(ProfileError):
    pass


def avatar_key(uid: str) -> str:
    """La clave del archivo de la foto. Los uid de Firebase son alfanuméricos; cualquier otra cosa
    se convierte en un hash para que la clave nunca salga de avatars/."""
    safe = uid if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", uid) else hashlib.sha256(uid.encode()).hexdigest()
    return f"avatars/{safe}.jpg"


def stored(docs: DocStore, uid: str) -> dict[str, Any]:
    return docs.get(USERS, uid) or {"id": uid}


def notifications_of(doc: dict[str, Any]) -> dict[str, bool]:
    return {**DEFAULT_NOTIFICATIONS, **{k: bool(v) for k, v in (doc.get("notifications") or {}).items() if k in NOTIFICATION_KEYS}}


def preferences_of(doc: dict[str, Any]) -> dict[str, str]:
    return {**DEFAULT_PREFERENCES, **{k: v for k, v in (doc.get("preferences") or {}).items() if k in DEFAULT_PREFERENCES}}


def wants(docs: DocStore, uid: str, kind: str) -> bool:
    """Si la persona quiere este tipo de aviso (`processing`, `platform`, `promotions`)."""
    return notifications_of(stored(docs, uid))[kind]


def preview_quality(docs: DocStore, uid: str) -> str:
    return preferences_of(stored(docs, uid))["preview_quality"]


# ----- validación -----


def _text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ProfileError(f"{label} debe ser texto.")
    value = value.strip()
    if len(value) > limit:
        raise ProfileError(f"{label} admite hasta {limit} caracteres.")
    return value


def _flags(raw: Any, allowed: tuple[str, ...], label: str) -> dict[str, bool]:
    if not isinstance(raw, dict):
        raise ProfileError(f"{label} no es válido.")
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        raise ProfileError(f"{label}: opción desconocida ({', '.join(unknown)}).")
    if any(not isinstance(v, bool) for v in raw.values()):
        raise ProfileError(f"{label}: cada opción debe ser verdadera o falsa.")
    return dict(raw)


def validate(body: dict[str, Any]) -> dict[str, Any]:
    """Los campos editables de `body` ya validados y normalizados (solo los que vienen)."""
    unknown = sorted(set(body) - {"display_name", "username", "country", "bio", "notifications", "preferences"})
    if unknown:
        raise ProfileError(f"Campo no editable: {', '.join(unknown)}.")
    out: dict[str, Any] = {}
    if "display_name" in body:
        name = _text(body["display_name"], "El nombre", NAME_MAX)
        if not name:
            raise ProfileError("Escribe tu nombre.")
        out["display_name"] = name
    if "username" in body:
        raw = body["username"]
        if raw in (None, ""):
            out["username"] = None
        else:
            name = _text(raw, "El nombre de usuario", 60).lower().lstrip("@")
            if not USERNAME_RE.fullmatch(name):
                raise ProfileError("El nombre de usuario debe tener de 3 a 30 caracteres: letras minúsculas, números, punto o guion bajo.")
            out["username"] = name
    if "country" in body:
        raw = body["country"]
        if raw in (None, ""):
            out["country"] = None
        else:
            code = _text(raw, "El país", 2).upper()
            if code not in COUNTRIES:
                raise ProfileError("Ese país no está en la lista.")
            out["country"] = code
    if "bio" in body:
        out["bio"] = _text(body["bio"] if body["bio"] is not None else "", "La biografía", BIO_MAX)
    if "notifications" in body:
        out["notifications"] = _flags(body["notifications"], NOTIFICATION_KEYS, "Las notificaciones")
    if "preferences" in body:
        raw = body["preferences"]
        if not isinstance(raw, dict):
            raise ProfileError("Las preferencias no son válidas.")
        options = {"language": LANGUAGES, "preview_quality": PREVIEW_QUALITIES, "theme": THEMES}
        for key, value in raw.items():
            if key not in options:
                raise ProfileError(f"Preferencia desconocida: {key}.")
            if value not in options[key]:
                raise ProfileError(f"Valor no válido para {key}: elige {', '.join(options[key])}.")
        out["preferences"] = dict(raw)
    return out


# ----- escritura -----


def _claim_username(docs: DocStore, name: str, uid: str) -> None:
    def take(current: dict | None) -> dict | None:
        if current is not None and current.get("uid") != uid:
            return None
        return {"id": name, "uid": uid}

    if docs.transact(USERNAMES, name, take) is None:
        raise UsernameTaken("Ese nombre de usuario ya está en uso.")


def _release_username(docs: DocStore, name: str | None, uid: str) -> None:
    if not name:
        return

    def drop(current: dict | None):
        return DELETE if current is not None and current.get("uid") == uid else None

    docs.transact(USERNAMES, name, drop)


def save(docs: DocStore, uid: str, changes: dict[str, Any]) -> dict[str, Any]:
    """Aplica los cambios ya validados y devuelve el documento. El nombre de usuario nuevo se
    reclama antes de escribir el perfil y el viejo se suelta después."""
    previous = stored(docs, uid)
    old_name = previous.get("username")
    new_name = changes.get("username", old_name)
    if "username" in changes and new_name and new_name != old_name:
        _claim_username(docs, new_name, uid)

    def write(current: dict | None) -> dict:
        doc = dict(current or {"id": uid})
        for key, value in changes.items():
            if key in ("notifications", "preferences"):
                doc[key] = {**(doc.get(key) or {}), **value}
            else:
                doc[key] = value
        doc.setdefault("created", time.time())
        return doc

    doc = docs.transact(USERS, uid, write)
    if "username" in changes and old_name and old_name != new_name:
        _release_username(docs, old_name, uid)
    return doc


def set_avatar(docs: DocStore, uid: str, present: bool) -> dict[str, Any]:
    return docs.transact(USERS, uid, lambda c: {**(c or {"id": uid, "created": time.time()}), "avatar_updated": time.time() if present else None})


def accept_terms(docs: DocStore, uid: str) -> dict[str, Any]:
    return docs.transact(USERS, uid, lambda c: {**(c or {"id": uid, "created": time.time()}), "accepted_terms_at": time.time(), "terms_version": TERMS_VERSION})


def erase(docs: DocStore, uid: str) -> bool:
    """Borra el perfil y suelta su nombre de usuario. Devuelve si existía."""
    doc = docs.get(USERS, uid)
    _release_username(docs, (doc or {}).get("username"), uid)
    docs.delete(USERS, uid)
    return doc is not None


def check_avatar_type(filename: str | None, content_type: str | None) -> None:
    ext = Path(filename or "").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp") or (content_type and content_type.split(";")[0].strip().lower() not in ("image/jpeg", "image/png", "image/webp", "application/octet-stream")):
        raise ProfileError("La imagen debe ser JPG, PNG o WEBP.")


def square_jpeg(data: bytes, target: Path) -> None:
    """Decodifica la imagen, la recorta al cuadrado central, la lleva a 512 px y la guarda como
    JPEG. Volver a codificar descarta el EXIF y cualquier metadato (ubicación, cámara)."""
    import cv2
    import numpy as np

    picture = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if picture is None or picture.size == 0:
        raise ProfileError("No pudimos leer esa imagen. Prueba con otro archivo JPG, PNG o WEBP.")
    height, width = picture.shape[:2]
    side = min(height, width)
    top, left = (height - side) // 2, (width - side) // 2
    square = picture[top : top + side, left : left + side]
    interpolation = cv2.INTER_AREA if side > AVATAR_SIDE else cv2.INTER_CUBIC
    square = cv2.resize(square, (AVATAR_SIDE, AVATAR_SIDE), interpolation=interpolation)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(target), square, [int(cv2.IMWRITE_JPEG_QUALITY), 88]):
        raise ProfileError("No pudimos guardar la imagen.")
