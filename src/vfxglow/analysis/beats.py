"""Parte el clip en beats: cortes de plano, onsets de audio y cambios de gesto.

PySceneDetect y librosa se usan cuando están instalados. Si no, el mismo
resultado sale de un corte por histograma y del flujo espectral del audio.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import Beat, FrameRecord, VideoMeta
from vfxglow.config import BeatsConfig

log = logging.getLogger("vfxglow.beats")


def segment_beats(
    frames: list[FrameRecord],
    video_path: Path,
    meta: VideoMeta,
    cfg: BeatsConfig | None = None,
) -> tuple[list[Beat], list[int]]:
    """Devuelve los beats y los fotogramas de onset. Un clip vacío da un beat."""
    cfg = cfg or BeatsConfig()
    if not frames:
        return [], []
    n = len(frames)
    if not cfg.enabled:
        return [_beat(0, 0, n - 1, "gesture", frames)], []
    cuts = _scene_cuts(video_path, n, cfg.cut_correlation)
    onsets = _audio_onsets(video_path, meta.fps, n)
    boundaries = _gesture_boundaries(frames, cfg.min_beat)
    edges = sorted(set([0, n] + [c for c in cuts if 0 < c < n] + boundaries))
    beats: list[Beat] = []
    for index, (start, end) in enumerate(zip(edges, edges[1:], strict=False)):
        stop = end - 1
        if stop < start:
            continue
        kind = "cut" if start in cuts and start != 0 else _gesture_kind(frames, start, stop)
        inside = [frame for frame in onsets if start <= frame <= stop]
        people = sorted({person.person_id for frame in frames[start : stop + 1] for person in frame.people})
        beats.append(_beat(len(beats) if False else index, start, stop, kind, frames, inside, people))
    beats = [beat.model_copy(update={"id": i}) for i, beat in enumerate(beats)]
    if not beats:
        beats = [_beat(0, 0, n - 1, "gesture", frames)]
    log.info("%d beats, %d cortes, %d onsets", len(beats), len(cuts), len(onsets))
    return beats, onsets


def cut_frames(beats: list[Beat]) -> list[int]:
    """Fotogramas donde empieza un beat marcado como corte."""
    return [beat.start_frame for beat in beats if beat.kind == "cut" and beat.start_frame > 0]


def _beat(
    index: int,
    start: int,
    end: int,
    kind: str,
    frames: list[FrameRecord],
    onsets: list[int] | None = None,
    people: list[str] | None = None,
) -> Beat:
    return Beat(
        id=index,
        start_frame=start,
        end_frame=end,
        kind=kind,
        onsets=onsets or [],
        people=people or [],
        gesture=_gesture_kind(frames, start, end) if kind != "cut" else "",
    )


def _gesture_kind(frames: list[FrameRecord], start: int, end: int) -> str:
    speeds = []
    raised = 0
    for frame in frames[start : end + 1]:
        speeds.extend(item.speed for item in frame.motion if item.name in {"left_wrist", "right_wrist"} and not item.glitch)
        for side in ("left", "right"):
            shoulder = next((lm.y for lm in frame.pose if lm.name == f"{side}_shoulder" and lm.c > 0), None)
            wrist = next((lm.y for lm in frame.pose if lm.name == f"{side}_wrist" and lm.c > 0), None)
            if shoulder is not None and wrist is not None and wrist < shoulder - 0.04:
                raised += 1
    if not speeds:
        return "pose"
    mean = float(np.mean(speeds))
    span = max(end - start + 1, 1)
    if raised > span * 0.4:
        return "gesture"
    if mean < 0.04:
        return "pose"
    return "gesture"


def _gesture_boundaries(frames: list[FrameRecord], min_beat: int) -> list[int]:
    """Cambia de beat cuando la energía de las muñecas pasa de quieta a activa."""
    energy = np.zeros(len(frames))
    for i, frame in enumerate(frames):
        vals = [item.speed for item in frame.motion if "wrist" in item.name and not item.glitch]
        energy[i] = float(np.mean(vals)) if vals else 0.0
    active = energy > 0.08
    bounds: list[int] = []
    run = 0
    state = bool(active[0]) if len(active) else False
    for i, flag in enumerate(active):
        if bool(flag) == state:
            run += 1
            continue
        if run >= min_beat:
            bounds.append(i)
            state = bool(flag)
            run = 1
        else:
            run += 1
    return bounds


def _scene_cuts(video_path: Path, frame_count: int, correlation: float) -> list[int]:
    detected = _scenedetect_cuts(video_path, frame_count)
    if detected is None:
        detected = _histogram_cuts(video_path, frame_count, correlation)
    # Tomas del mismo lugar (el mismo cielo y el mismo pasto) tienen casi el mismo histograma: el
    # corte se ve en la forma de la imagen.
    return sorted(set(detected) | set(_structure_cuts(video_path, frame_count)))


def _scenedetect_cuts(video_path: Path, frame_count: int) -> list[int] | None:
    try:
        from scenedetect import SceneManager, open_video
        from scenedetect.detectors import ContentDetector
    except ImportError:
        return None
    try:
        video = open_video(str(video_path))
        manager = SceneManager()
        manager.add_detector(ContentDetector(threshold=27.0))
        manager.detect_scenes(video)
        cuts = []
        for start, _end in manager.get_scene_list():
            frame = int(start.get_frames())
            if 0 < frame < frame_count:
                cuts.append(frame)
        log.info("Cortes con PySceneDetect: %s", cuts)
        return cuts
    except Exception as exc:  # el fallback de histograma cubre videos raros
        log.warning("PySceneDetect no pudo leer el video (%s); uso el histograma", exc)
        return None


CUT_JUMP = 8.0  # salto medio de gris (0-255) entre dos cuadros para que pueda ser un corte...
CUT_RATIO = 4.0  # ...y cuántas veces más grande que el movimiento normal de los cuadros vecinos


def _structure_cuts(video_path: Path, frame_count: int) -> list[int]:
    """Cortes por la forma de la imagen: un salto de diferencia entre dos cuadros muy por encima
    del de los cuadros vecinos (el movimiento de la persona cambia poco de un cuadro al otro)."""
    cap = cv2.VideoCapture(str(video_path))
    jumps: list[float] = []
    previous = None
    while len(jumps) < frame_count:
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, (96, 54)), cv2.COLOR_BGR2GRAY).astype(np.float32), (3, 3), 0)
        if previous is not None:
            jumps.append(float(np.abs(gray - previous).mean()))
        previous = gray
    cap.release()
    d = np.array(jumps)
    cuts = []
    for i in range(len(d)):
        near = np.concatenate([d[max(i - 6, 0) : i], d[i + 1 : i + 7]])
        if d[i] > CUT_JUMP and d[i] > CUT_RATIO * max(float(np.median(near)) if len(near) else 0.0, 1.0):
            cuts.append(i + 1)
    return [c for c in cuts if c < frame_count - 3]  # el último fundido a negro no es un corte


def _histogram_cuts(video_path: Path, frame_count: int, correlation: float) -> list[int]:
    cap = cv2.VideoCapture(str(video_path))
    cuts: list[int] = []
    previous = None
    index = 0
    while index < frame_count:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (80, 45))
        hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
        cv2.normalize(hist, hist)
        if previous is not None and cv2.compareHist(previous, hist, cv2.HISTCMP_CORREL) < correlation:
            cuts.append(index)
        previous = hist
        index += 1
    cap.release()
    return cuts


def _audio_onsets(video_path: Path, fps: float, frame_count: int) -> list[int]:
    detected = _librosa_onsets(video_path, fps, frame_count)
    if detected is not None:
        return detected
    return _flux_onsets(video_path, fps, frame_count)


def _librosa_onsets(video_path: Path, fps: float, frame_count: int) -> list[int] | None:
    try:
        import librosa
    except ImportError:
        return None
    try:
        samples, rate = librosa.load(str(video_path), sr=22050, mono=True)
        times = librosa.frames_to_time(librosa.onset.onset_detect(y=samples, sr=rate), sr=rate)
        frames = sorted({int(np.clip(round(t * fps), 0, frame_count - 1)) for t in times})
        return frames
    except Exception as exc:
        log.warning("librosa no leyó el audio (%s); uso el flujo espectral", exc)
        return None


def _flux_onsets(video_path: Path, fps: float, frame_count: int) -> list[int]:
    try:
        import imageio_ffmpeg
    except ImportError:
        return []
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        return []
    pcm = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32)
    if pcm.size < 1024:
        return []
    pcm /= 32768.0
    hop = 512
    window = np.hanning(1024)
    prev = None
    flux: list[float] = []
    for start in range(0, pcm.size - 1024, hop):
        spec = np.abs(np.fft.rfft(pcm[start : start + 1024] * window))
        if prev is not None:
            flux.append(float(np.maximum(spec - prev, 0.0).mean()))
        prev = spec
    if not flux:
        return []
    values = np.asarray(flux)
    threshold = float(values.mean() + values.std())
    onsets: list[int] = []
    for i, value in enumerate(values):
        if value < threshold or (i > 0 and value < values[i - 1]):
            continue
        frame = int(round((i * hop / 16000.0) * fps))
        if 0 <= frame < frame_count and (not onsets or frame - onsets[-1] > int(fps * 0.12)):
            onsets.append(frame)
    return onsets
