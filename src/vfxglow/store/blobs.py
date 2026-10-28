"""Archivos (videos, salidas, artefactos del editor, capas) detrás de una interfaz pequeña.

La clave de un archivo es su ruta relativa a api_data/ ("outputs/<id>.mp4",
"uploads/<id>/clip.mp4"). Así el disco local sigue igual que siempre y en la nube la misma clave
es el nombre del objeto en el bucket.

- `LocalBlobStore` (VEXORA_BLOBS=local, por defecto): los archivos ya están en api_data/; guardar o
  traer el mismo archivo no hace nada.
- `GcsBlobStore` (VEXORA_BLOBS=gcs): el bucket de Firebase Storage (VEXORA_BUCKET). El trabajador
  sube lo que produce y la API, que puede ser otra instancia, lo sirve con una URL firmada corta.

Cada proceso trabaja sobre archivos locales (el pipeline y OpenCV leen rutas): `fetch` trae una
copia cuando falta y `put` publica la que se acaba de escribir.

Subidas directas: con GCS el navegador sube el video al bucket con una URL firmada de PUT
(`signed_upload_url`, tipo y tamaño máximo atados a la firma) y la API solo comprueba que llegó
(`size`). Al crear el trabajo, el video se copia dentro del bucket (`copy`), sin pasar por la API.
"""

from __future__ import annotations

import datetime
import mimetypes
import os
import shutil
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any

BUCKET_ENV = "VEXORA_BUCKET"
# Una respuesta negativa de `exists` se recuerda poco: el trabajador puede subir el archivo
# en cualquier momento. Una positiva, hasta que este proceso lo borre (los archivos no cambian).
NEGATIVE_TTL_S = 10.0


def check_key(key: str) -> str:
    """Una clave relativa y sin `..`: nunca sale de api_data/ ni del bucket."""
    if not key or key.startswith("/") or ".." in Path(key).parts or "\\" in key:
        raise ValueError(f"Clave de archivo no válida: {key!r}")
    return key


class BlobStore(ABC):
    # True si los archivos viven en el mismo disco que api_data/ (nada que subir ni bajar).
    local: bool = True

    @abstractmethod
    def put(self, key: str, source: Path) -> None:
        """Publica el archivo local `source` con la clave `key`."""

    @abstractmethod
    def fetch(self, key: str, target: Path) -> bool:
        """Deja una copia de `key` en `target`. Devuelve si el archivo existe."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def delete_prefix(self, prefix: str) -> None:
        """Borra todo lo que empieza por `prefix` ("outputs/<id>." o "uploads/<id>/")."""

    @abstractmethod
    def size(self, key: str) -> int | None:
        """Bytes del archivo, o None si no existe (sin recordar la respuesta: se pregunta al almacén)."""

    @abstractmethod
    def copy(self, source: str, target: str) -> None:
        """Copia `source` en `target` dentro del almacén (sin bajarlo a esta máquina)."""

    def signed_url(self, key: str, ttl_s: int = 900, filename: str | None = None, media_type: str | None = None) -> str | None:
        """Una URL temporal para descargar el archivo sin pasar por la API; None si no aplica."""
        return None

    def signed_upload_url(self, key: str, content_type: str, max_bytes: int, ttl_s: int = 900) -> tuple[str, dict[str, str]] | None:
        """Una URL temporal para que el navegador suba el archivo directo al almacén (PUT), con las
        cabeceras que debe mandar tal cual. None si no aplica (archivos locales: sube la API)."""
        return None


class LocalBlobStore(BlobStore):
    def __init__(self, root: Path) -> None:
        self.root = root

    def path(self, key: str) -> Path:
        return self.root / check_key(key)

    def put(self, key: str, source: Path) -> None:
        target = self.path(key)
        if target.exists() and target.resolve() == Path(source).resolve():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        shutil.copy2(source, tmp)
        tmp.replace(target)

    def fetch(self, key: str, target: Path) -> bool:
        source = self.path(key)
        if not source.exists():
            return False
        if Path(target).resolve() != source.resolve():
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return True

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    def size(self, key: str) -> int | None:
        path = self.path(key)
        return path.stat().st_size if path.is_file() else None

    def copy(self, source: str, target: str) -> None:
        origin, dest = self.path(source), self.path(target)
        if dest.exists() and dest.resolve() == origin.resolve():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.unlink(missing_ok=True)
        try:
            os.link(origin, dest)  # mismo disco: un enlace, sin copiar bytes
        except OSError:
            shutil.copy2(origin, dest)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        folder, _, stem = check_key(prefix).rpartition("/")
        base = self.root / folder
        if not stem:
            shutil.rmtree(base, ignore_errors=True)
            return
        for item in base.glob(f"{stem}*") if base.exists() else []:
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)


def _missing(error: Exception) -> bool:
    return getattr(error, "code", None) == 404 or type(error).__name__ == "NotFound"


class GcsBlobStore(BlobStore):
    """Un bucket de Cloud Storage (el de Firebase Storage del proyecto)."""

    local = False

    def __init__(self, bucket: Any = None, signing: Callable[[], dict] | None = None, clock: Callable[[], float] = time.time) -> None:
        """`bucket` y `signing` se pueden inyectar (las pruebas usan un bucket falso)."""
        if bucket is None:
            from google.cloud import storage

            name = os.environ.get(BUCKET_ENV, "").strip()
            if not name:
                raise RuntimeError(f"VEXORA_BLOBS=gcs necesita {BUCKET_ENV} (p. ej. mi-proyecto.firebasestorage.app).")
            bucket = storage.Client(project=os.environ.get("VEXORA_FIREBASE_PROJECT") or None).bucket(name)
        self.bucket = bucket
        self._signing = signing or _signing_kwargs
        self._clock = clock
        self._known: dict[str, tuple[bool, float]] = {}
        self._lock = threading.Lock()

    def _remember(self, key: str, present: bool) -> None:
        with self._lock:
            self._known[key] = (present, self._clock())

    def put(self, key: str, source: Path) -> None:
        media_type = mimetypes.guess_type(str(source))[0] or "application/octet-stream"
        self.bucket.blob(check_key(key)).upload_from_filename(str(source), content_type=media_type)
        self._remember(key, True)

    def fetch(self, key: str, target: Path) -> bool:
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        try:
            self.bucket.blob(check_key(key)).download_to_filename(str(tmp))
        except Exception as error:
            tmp.unlink(missing_ok=True)
            if _missing(error):
                self._remember(key, False)
                return False
            raise
        tmp.replace(target)
        self._remember(key, True)
        return True

    def exists(self, key: str) -> bool:
        with self._lock:
            known = self._known.get(key)
        if known is not None and (known[0] or self._clock() - known[1] < NEGATIVE_TTL_S):
            return known[0]
        present = bool(self.bucket.blob(check_key(key)).exists())
        self._remember(key, present)
        return present

    def size(self, key: str) -> int | None:
        blob = self.bucket.get_blob(check_key(key))
        present = blob is not None
        self._remember(key, present)
        return int(blob.size or 0) if present else None

    def copy(self, source: str, target: str) -> None:
        # Copia del lado del servidor (mismo bucket): no pasa por esta máquina ni por la API.
        self.bucket.copy_blob(self.bucket.blob(check_key(source)), self.bucket, check_key(target))
        self._remember(target, True)

    def delete(self, key: str) -> None:
        try:
            self.bucket.blob(check_key(key)).delete()
        except Exception as error:
            if not _missing(error):
                raise
        self._remember(key, False)

    def delete_prefix(self, prefix: str) -> None:
        for blob in list(self.bucket.list_blobs(prefix=check_key(prefix))):
            try:
                blob.delete()
            except Exception as error:
                if not _missing(error):
                    raise
            self._remember(blob.name, False)

    def signed_url(self, key: str, ttl_s: int = 900, filename: str | None = None, media_type: str | None = None) -> str | None:
        disposition = f'attachment; filename="{filename}"' if filename else None
        return self.bucket.blob(check_key(key)).generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(seconds=ttl_s),
            method="GET",
            response_disposition=disposition,
            response_type=media_type,
            **self._signing(),
        )

    def signed_upload_url(self, key: str, content_type: str, max_bytes: int, ttl_s: int = 900) -> tuple[str, dict[str, str]] | None:
        """PUT firmado (V4) con el tipo de contenido y un tope de tamaño atados a la firma: GCS
        rechaza la subida si el navegador manda otro tipo o más bytes (x-goog-content-length-range)."""
        headers = {"x-goog-content-length-range": f"0,{int(max_bytes)}"}
        url = self.bucket.blob(check_key(key)).generate_signed_url(
            version="v4",
            expiration=datetime.timedelta(seconds=ttl_s),
            method="PUT",
            content_type=content_type,
            headers=headers,
            **self._signing(),
        )
        return url, {"Content-Type": content_type, **headers}


_credentials: Any = None
_credentials_lock = threading.Lock()


def _signing_kwargs() -> dict:
    """Con qué se firma la URL. Con un archivo de llave (GOOGLE_APPLICATION_CREDENTIALS) la
    librería firma sola. En Cloud Run la cuenta de servicio no trae llave privada: se firma con la
    API de IAM (signBlob), que pide el correo de la cuenta y un token de acceso (rol
    "Service Account Token Creator" de la cuenta sobre sí misma)."""
    global _credentials
    import google.auth
    from google.auth.transport.requests import Request

    with _credentials_lock:
        if _credentials is None:
            _credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        credentials = _credentials
        if getattr(credentials, "signer", None) is not None and hasattr(credentials, "sign_bytes"):
            return {}
        if not credentials.valid:
            credentials.refresh(Request())
        return {"service_account_email": credentials.service_account_email, "access_token": credentials.token}
