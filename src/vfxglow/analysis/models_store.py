"""Descarga perezosa de los modelos de MediaPipe."""

from __future__ import annotations

import shutil
import ssl
import urllib.request
from pathlib import Path

MODEL_URLS: dict[str, str] = {
    "pose_landmarker_full.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "pose_landmarker_lite.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "hand_landmarker.task": "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
}


def ssl_context() -> ssl.SSLContext:
    """Python de python.org en macOS no trae la cadena raíz del sistema."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def ensure_model(models_dir: Path, filename: str) -> Path:
    destination = models_dir / filename
    if destination.exists() and destination.stat().st_size > 0:
        return destination
    url = MODEL_URLS.get(filename)
    if url is None:
        raise FileNotFoundError(f"No hay URL conocida para el modelo {filename}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, context=ssl_context()) as response, tmp.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    tmp.replace(destination)
    return destination


def pose_filename(variant: str) -> str:
    if variant == "lite":
        return "pose_landmarker_lite.task"
    return "pose_landmarker_full.task"
