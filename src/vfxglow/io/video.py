"""Lectura de video y detección de audio."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import VideoMeta
from vfxglow.composite.encode import find_ffmpeg


class VideoReader:
    """Itera fotogramas BGR sin cargarlos todos en memoria."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir el video: {path}")
        fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        if fps <= 1e-3:
            fps = 30.0
        width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.meta = VideoMeta(
            path=str(path),
            fps=fps,
            width=width,
            height=height,
            frame_count=max(frame_count, 0),
            duration_s=(frame_count / fps) if frame_count else 0.0,
            has_audio=has_audio(path),
        )

    def __iter__(self) -> Iterator[tuple[int, np.ndarray]]:
        index = 0
        while True:
            ok, frame = self.cap.read()
            if not ok:
                break
            yield index, frame
            index += 1

    def frames(self, start: int, end: int) -> Iterator[tuple[int, np.ndarray]]:
        """Los fotogramas start..end; los de antes se saltan sin convertirlos."""
        for _ in range(start):
            if not self.cap.grab():
                return
        for index in range(start, end + 1):
            ok, frame = self.cap.read()
            if not ok:
                return
            yield index, frame

    def close(self) -> None:
        self.cap.release()

    def __enter__(self) -> VideoReader:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def has_audio(path: Path) -> bool:
    """Detecta pista de audio con ffmpeg, sin reencodear el archivo."""
    ffmpeg = find_ffmpeg(required=False)
    if ffmpeg is None:
        return False
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    log = (proc.stderr or "") + (proc.stdout or "")
    return "Audio:" in log


def write_silent_video(path: Path, frames_bgr: list[np.ndarray], fps: float) -> None:
    """Escribe un mp4 de prueba con el codec que OpenCV tenga a mano."""
    if not frames_bgr:
        raise RuntimeError("No hay fotogramas para escribir.")
    height, width = frames_bgr[0].shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV no pudo crear el video: {path}")
    try:
        for frame in frames_bgr:
            writer.write(frame)
    finally:
        writer.release()
