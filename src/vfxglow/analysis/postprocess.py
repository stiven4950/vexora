"""Suavizado de tracks ya detectados. No depende de MediaPipe."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import FrameRecord, HandFrame, Landmark
from vfxglow.analysis.smoothing import smooth_series
from vfxglow.config import AnalysisConfig


def _as_map(landmarks: list[Landmark]) -> dict[str, Landmark]:
    return {lm.name: lm for lm in landmarks}


def _smooth_group(
    frames: list[FrameRecord],
    names: list[str],
    read,
    write,
    fps: float,
    cfg: AnalysisConfig,
) -> None:
    if not names:
        return
    n = len(frames)
    for name in names:
        xs = np.full(n, np.nan)
        ys = np.full(n, np.nan)
        zs = np.full(n, np.nan)
        cs = np.zeros(n)
        for i, frame in enumerate(frames):
            lm = read(frame, name)
            if lm is not None:
                xs[i], ys[i], zs[i], cs[i] = lm.x, lm.y, lm.z, lm.c
        jump = cfg.events.glitch_jump
        sx, vx = smooth_series(xs, cs, fps, cfg.min_confidence, cfg.max_gap, cfg.one_euro, jump)
        sy, vy = smooth_series(ys, cs, fps, cfg.min_confidence, cfg.max_gap, cfg.one_euro, jump)
        sz, _ = smooth_series(zs, cs, fps, cfg.min_confidence, cfg.max_gap, cfg.one_euro)
        valid = vx & vy
        for i, frame in enumerate(frames):
            if not valid[i] or not np.isfinite(sx[i]) or not np.isfinite(sy[i]):
                write(frame, name, None)
                continue
            z = float(sz[i]) if np.isfinite(sz[i]) else 0.0
            write(frame, name, Landmark(name=name, x=float(sx[i]), y=float(sy[i]), z=z, c=float(max(cs[i], cfg.min_confidence))))


def _pose_names(frames: list[FrameRecord]) -> list[str]:
    names: set[str] = set()
    for frame in frames:
        names.update(lm.name for lm in frame.pose)
    return sorted(names)


def _read_pose(frame: FrameRecord, name: str) -> Landmark | None:
    for lm in frame.pose:
        if lm.name == name:
            return lm
    return None


def _write_pose(frame: FrameRecord, name: str, lm: Landmark | None) -> None:
    frame.pose = [item for item in frame.pose if item.name != name]
    if lm is not None:
        frame.pose.append(lm)


def _hand_names(frames: list[FrameRecord], side: str) -> list[str]:
    names: set[str] = set()
    for frame in frames:
        hand = frame.left_hand if side == "left" else frame.right_hand
        if hand is not None:
            names.update(lm.name for lm in hand.landmarks)
    return sorted(names)


def _read_hand(side: str):
    def read(frame: FrameRecord, name: str) -> Landmark | None:
        hand = frame.left_hand if side == "left" else frame.right_hand
        if hand is None:
            return None
        for lm in hand.landmarks:
            if lm.name == name:
                return lm
        return None

    return read


def _write_hand(side: str):
    def write(frame: FrameRecord, name: str, lm: Landmark | None) -> None:
        current = frame.left_hand if side == "left" else frame.right_hand
        landmarks = [] if current is None else [item for item in current.landmarks if item.name != name]
        score = 0.0 if current is None else current.score
        if lm is not None:
            landmarks.append(lm)
            score = max(score, lm.c)
        hand = HandFrame(landmarks=landmarks, score=score) if landmarks else None
        if side == "left":
            frame.left_hand = hand
        else:
            frame.right_hand = hand

    return write


def _smooth_face(frames: list[FrameRecord], fps: float, cfg: AnalysisConfig) -> None:
    """Como `_smooth_group`, pero con la malla indexada una vez: son ~150 puntos por fotograma."""
    maps = [_as_map(frame.face) if frame.face else {} for frame in frames]
    names = sorted({name for item in maps for name in item})
    if not names:
        return
    n = len(frames)
    out: list[list[Landmark]] = [[] for _ in range(n)]
    for name in names:
        xs = np.full(n, np.nan)
        ys = np.full(n, np.nan)
        cs = np.zeros(n)
        for i, item in enumerate(maps):
            lm = item.get(name)
            if lm is not None:
                xs[i], ys[i], cs[i] = lm.x, lm.y, lm.c
        sx, vx = smooth_series(xs, cs, fps, cfg.min_confidence, cfg.max_gap, cfg.one_euro, cfg.events.glitch_jump)
        sy, vy = smooth_series(ys, cs, fps, cfg.min_confidence, cfg.max_gap, cfg.one_euro, cfg.events.glitch_jump)
        for i in range(n):
            if vx[i] and vy[i] and np.isfinite(sx[i]) and np.isfinite(sy[i]):
                out[i].append(Landmark(name=name, x=float(sx[i]), y=float(sy[i]), z=0.0, c=float(max(cs[i], cfg.min_confidence))))
    for frame, face in zip(frames, out, strict=True):
        frame.face = face or None


def _refresh_box(frame: FrameRecord) -> None:
    pts = [(lm.x, lm.y) for lm in frame.pose if lm.c > 0]
    if not pts:
        frame.box = None
        return
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = 0.04
    frame.box = (
        float(max(0.0, min(xs) - pad)),
        float(max(0.0, min(ys) - pad)),
        float(min(1.0, max(xs) + pad)),
        float(min(1.0, max(ys) + pad)),
    )


def smooth_tracks(frames: list[FrameRecord], fps: float, cfg: AnalysisConfig) -> list[FrameRecord]:
    _smooth_group(frames, _pose_names(frames), _read_pose, _write_pose, fps, cfg)
    for side in ("left", "right"):
        _smooth_group(frames, _hand_names(frames, side), _read_hand(side), _write_hand(side), fps, cfg)
    if cfg.store_face:
        _smooth_face(frames, fps, cfg)
    else:
        for frame in frames:
            frame.face = None
    for frame in frames:
        frame.pose.sort(key=lambda lm: lm.name)
        _refresh_box(frame)
        if frame.people and frame.people[0].person_id == frame.person_id:
            frame.people[0].pose = frame.pose
            frame.people[0].left_hand = frame.left_hand
            frame.people[0].right_hand = frame.right_hand
            frame.people[0].box = frame.box
    return frames
