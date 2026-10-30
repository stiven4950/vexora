"""Qué tan fuerte suena el video en cada fotograma (`FrameRecord.voice`, 0-1).

Se mide la energía del audio por fotograma, en decibeles respecto de lo más fuerte del video, para
que un video grabado bajo no quede en cero. Es volumen, no reconocimiento de voz: con música de fondo
también marca. Por eso `speaking` (analysis/expressions.py) exige además que la boca se mueva.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from vfxglow.analysis.schema import FrameRecord

RATE = 16000
# De cuántos decibeles bajo lo más fuerte a lo más fuerte va la escala 0-1.
RANGE_DB = 32.0
TOP_PERCENTILE = 98.0


def _pcm(video_path: Path) -> np.ndarray | None:
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    proc = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def loudness(pcm: np.ndarray, fps: float, count: int) -> np.ndarray:
    """Volumen 0-1 de cada uno de `count` fotogramas."""
    hop = RATE / max(fps, 1e-3)
    out = np.zeros(count, dtype=np.float64)
    for k in range(count):
        chunk = pcm[int(k * hop) : int((k + 1) * hop)]
        if chunk.size:
            out[k] = float(np.sqrt(np.mean(chunk**2)))
    top = float(np.percentile(out, TOP_PERCENTILE)) if count else 0.0
    if top <= 1e-5:
        return np.zeros(count, dtype=np.float64)
    db = 20.0 * np.log10(np.maximum(out, 1e-6) / top)
    return np.clip(1.0 + db / RANGE_DB, 0.0, 1.0)


def add_voice(frames: list[FrameRecord], video_path: Path, fps: float) -> None:
    pcm = _pcm(video_path)
    if pcm is None or pcm.size == 0 or not frames:
        return
    levels = loudness(pcm, fps, max(f.frame for f in frames) + 1)
    for frame in frames:
        frame.voice = round(float(levels[frame.frame]), 3)
