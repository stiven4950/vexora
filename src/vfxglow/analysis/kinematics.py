"""Cinemática y brief compacto. El LLM ve esto, no los landmarks crudos."""

from __future__ import annotations

import math

import numpy as np

from vfxglow.analysis.names import FACE_ANCHORS, LIMB_JOINTS, MOTION_JOINTS
from vfxglow.analysis.schema import (
    Beat,
    FrameRecord,
    HandFrame,
    HandState,
    JointMotion,
    LimbStats,
    MotionBrief,
    MotionEvent,
    SceneBeat,
    VideoMeta,
)
from vfxglow.geom import rdp


def _map(frame: FrameRecord) -> dict[str, tuple[float, float, float]]:
    return {lm.name: (lm.x, lm.y, lm.c) for lm in frame.pose if lm.c > 0}


def _series(frames: list[FrameRecord], name: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = len(frames)
    xs = np.full(n, np.nan)
    ys = np.full(n, np.nan)
    cs = np.zeros(n)
    for i, frame in enumerate(frames):
        for lm in frame.pose:
            if lm.name == name and lm.c > 0:
                xs[i] = lm.x
                ys[i] = lm.y
                cs[i] = lm.c
                break
    return xs, ys, cs


def torso_length_px(frame: FrameRecord, width: int, height: int) -> float:
    pts = _map(frame)
    if "left_shoulder" in pts and "right_shoulder" in pts and "left_hip" in pts and "right_hip" in pts:
        sx = (pts["left_shoulder"][0] + pts["right_shoulder"][0]) * 0.5 * width
        sy = (pts["left_shoulder"][1] + pts["right_shoulder"][1]) * 0.5 * height
        hx = (pts["left_hip"][0] + pts["right_hip"][0]) * 0.5 * width
        hy = (pts["left_hip"][1] + pts["right_hip"][1]) * 0.5 * height
        return float(max(math.hypot(sx - hx, sy - hy), 1.0))
    return float(max(height * 0.25, 1.0))


def add_motion(frames: list[FrameRecord], meta: VideoMeta, glitch_speed: float = 2.5) -> None:
    """Velocidad y aceleración normalizadas por el torso, apertura de mano y giro del torso."""
    series = {name: _series(frames, name) for name in MOTION_JOINTS}
    previous_speed: dict[str, float] = {}
    previous_yaw: float | None = None
    for i, frame in enumerate(frames):
        scale = torso_length_px(frame, meta.width, meta.height)
        motion: list[JointMotion] = []
        frame.hand_state = {
            "left": HandState(**_openness(frame.left_hand)),
            "right": HandState(**_openness(frame.right_hand)),
        }
        yaw = _shoulder_yaw(frame)
        if i == 0 or yaw is None or previous_yaw is None:
            frame.torso_yaw_rate = 0.0
        else:
            delta = (yaw - previous_yaw + 180.0) % 360.0 - 180.0
            frame.torso_yaw_rate = float(delta)
        previous_yaw = yaw
        if i == 0:
            frame.motion = motion
            continue
        for name, (xs, ys, cs) in series.items():
            if not (np.isfinite(xs[i]) and np.isfinite(xs[i - 1]) and cs[i] > 0 and cs[i - 1] > 0):
                previous_speed.pop(name, None)
                continue
            vx = float((xs[i] - xs[i - 1]) * meta.width)
            vy = float((ys[i] - ys[i - 1]) * meta.height)
            speed = math.hypot(vx, vy) / scale
            direction = math.degrees(math.atan2(vy, vx)) if speed > 1e-6 else 0.0
            accel = speed - previous_speed.get(name, speed)
            previous_speed[name] = speed
            motion.append(
                JointMotion(
                    name=name,
                    speed=speed,
                    direction_deg=direction,
                    vx=vx / meta.width,
                    vy=vy / meta.height,
                    accel=accel,
                    glitch=speed > glitch_speed,
                )
            )
        frame.motion = motion
    _people_motion(frames, meta, glitch_speed)


def _openness(hand: HandFrame | None) -> dict[str, float | bool]:
    """Apertura 0..1: distancia media punta-muñeca sobre el tamaño de la palma."""
    if hand is None or len(hand.landmarks) < 21:
        return {"openness": 0.5, "valid": False}
    pts = {lm.name.split("_", 1)[1]: (lm.x, lm.y) for lm in hand.landmarks if "_" in lm.name}
    needed = ("wrist", "middle_mcp", "index_tip", "middle_tip", "ring_tip", "pinky_tip")
    if any(name not in pts for name in needed):
        return {"openness": 0.5, "valid": False}
    wrist = pts["wrist"]
    palm = math.hypot(pts["middle_mcp"][0] - wrist[0], pts["middle_mcp"][1] - wrist[1])
    if palm < 1e-5:
        return {"openness": 0.5, "valid": False}
    tips = [math.hypot(pts[t][0] - wrist[0], pts[t][1] - wrist[1]) for t in needed[2:]]
    ratio = float(np.mean(tips)) / palm
    openness = float(np.clip((ratio - 1.05) / 0.85, 0.0, 1.0))
    return {"openness": openness, "valid": True}


def _shoulder_yaw(frame: FrameRecord) -> float | None:
    pts = _map(frame)
    if "left_shoulder" not in pts or "right_shoulder" not in pts:
        return None
    dx = pts["left_shoulder"][0] - pts["right_shoulder"][0]
    dy = pts["left_shoulder"][1] - pts["right_shoulder"][1]
    return math.degrees(math.atan2(dy, dx))


def _limb_speeds(frames: list[FrameRecord], joint: str) -> np.ndarray:
    speeds = np.zeros(len(frames))
    for i, frame in enumerate(frames):
        for item in frame.motion:
            if item.name == joint:
                speeds[i] = item.speed
                break
    return speeds


def _direction_mean(frames: list[FrameRecord], joint: str) -> float:
    angles = [item.direction_deg for frame in frames for item in frame.motion if item.name == joint and item.speed > 0.02]
    if not angles:
        return 0.0
    rad = np.radians(angles)
    return float(math.degrees(math.atan2(np.sin(rad).mean(), np.cos(rad).mean())))


def _path_length(frames: list[FrameRecord], joint: str, meta: VideoMeta) -> float:
    xs, ys, cs = _series(frames, joint)
    total = 0.0
    prev: tuple[float, float] | None = None
    scale = max(np.nanmedian([torso_length_px(f, meta.width, meta.height) for f in frames]), 1.0)
    for x, y, c in zip(xs, ys, cs, strict=True):
        if c <= 0 or not np.isfinite(x):
            prev = None
            continue
        point = (float(x * meta.width), float(y * meta.height))
        if prev is not None:
            total += math.hypot(point[0] - prev[0], point[1] - prev[1]) / scale
        prev = point
    return float(total)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start: int | None = None
    for i, flag in enumerate(mask):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            spans.append((start, i - 1))
            start = None
    if start is not None:
        spans.append((start, len(mask) - 1))
    return spans


def _anchors(frames: list[FrameRecord]) -> list[str]:
    counts: dict[str, int] = {}
    for frame in frames:
        for lm in frame.pose:
            if lm.c > 0:
                counts[lm.name] = counts.get(lm.name, 0) + 1
        for hand in (frame.left_hand, frame.right_hand):
            if hand is None:
                continue
            for lm in hand.landmarks:
                if lm.c > 0:
                    counts[lm.name] = counts.get(lm.name, 0) + 1
    need = max(1, int(len(frames) * 0.1))
    names = [name for name, count in counts.items() if count >= need]
    names.extend(["mid_shoulder", "mid_hip", "neck"])
    if sum(1 for frame in frames if frame.face) >= need:
        names.extend(FACE_ANCHORS)
    for label in seen_objects(frames):
        names.append(f"object:{label}")
    return sorted(set(names))


def seen_objects(frames: list[FrameRecord], min_fraction: float = 0.05) -> list[str]:
    """Etiquetas de objeto presentes en una fracción mínima de fotogramas."""
    counts: dict[str, int] = {}
    for frame in frames:
        for obj in frame.objects:
            counts[obj.label] = counts.get(obj.label, 0) + 1
    need = max(2, int(len(frames) * min_fraction))
    return sorted(label for label, count in counts.items() if count >= need)


def _valid_speeds(frames: list[FrameRecord], joint: str) -> np.ndarray:
    """Velocidades por fotograma con los glitches del tracker a cero."""
    speeds = np.zeros(len(frames))
    for i, frame in enumerate(frames):
        for item in frame.motion:
            if item.name == joint:
                speeds[i] = 0.0 if item.glitch else item.speed
                break
    return speeds


def _summary(limbs: list[LimbStats], events: list[MotionEvent], objects: list[str]) -> str:
    if not limbs:
        return "No se detectó un actor estable."
    parts = [
        (
            f"{limb.name}: velocidad media {limb.mean_speed:.2f} torsos/fotograma, "
            f"pico {limb.peak_speed:.2f} en el fotograma {limb.peak_frame}"
        )
        for limb in limbs
    ]
    if objects:
        parts.append("Objetos visibles: " + ", ".join(objects))
    if events:
        counts: dict[str, int] = {}
        for event in events:
            counts[event.name] = counts.get(event.name, 0) + 1
        shown = ", ".join(f"{name} x{count}" for name, count in sorted(counts.items()))
        parts.append(f"Eventos detectados: {shown}")
        first = "; ".join(
            f"{event.name} ({event.target}) {event.start_frame}-{event.end_frame}" for event in events[:10]
        )
        parts.append(f"Primeros eventos: {first}")
    return ". ".join(parts) + "."


def simplified_path(frames: list[FrameRecord], joint: str) -> list[tuple[float, float]]:
    """Trayectoria en coordenadas normalizadas, reducida para el brief."""
    xs, ys, cs = _series(frames, joint)
    points = [(float(x), float(y)) for x, y, c in zip(xs, ys, cs, strict=True) if c > 0 and np.isfinite(x)]
    if len(points) < 3:
        return points
    reduced = rdp(np.asarray(points, dtype=np.float64), epsilon=0.015)
    return [(float(p[0]), float(p[1])) for p in reduced]


def _people_motion(frames: list[FrameRecord], meta: VideoMeta, glitch_speed: float) -> None:
    previous: dict[str, dict[str, tuple[float, float]]] = {}
    previous_speed: dict[tuple[str, str], float] = {}
    for frame in frames:
        for person in frame.people:
            current = {lm.name: (lm.x, lm.y) for lm in person.pose if lm.c > 0 and lm.name in MOTION_JOINTS}
            old = previous.get(person.person_id, {})
            scale = torso_length_px(frame, meta.width, meta.height)
            motion: list[JointMotion] = []
            for name, (x, y) in current.items():
                if name not in old:
                    continue
                vx = float((x - old[name][0]) * meta.width)
                vy = float((y - old[name][1]) * meta.height)
                speed = math.hypot(vx, vy) / scale
                key = (person.person_id, name)
                motion.append(
                    JointMotion(
                        name=name,
                        speed=speed,
                        direction_deg=math.degrees(math.atan2(vy, vx)) if speed > 1e-6 else 0.0,
                        vx=vx / meta.width,
                        vy=vy / meta.height,
                        accel=speed - previous_speed.get(key, speed),
                        glitch=speed > glitch_speed,
                    )
                )
                previous_speed[key] = speed
            person.motion = motion
            previous[person.person_id] = current


def build_brief(
    frames: list[FrameRecord],
    meta: VideoMeta,
    person_id: str = "person_0",
    events: list[MotionEvent] | None = None,
    beats: list[Beat] | None = None,
    scene: list[SceneBeat] | None = None,
    audio_onsets: list[int] | None = None,
) -> MotionBrief:
    limbs: list[LimbStats] = []
    for limb_name, joint in LIMB_JOINTS.items():
        speeds = _valid_speeds(frames, joint)
        if not np.any(speeds > 0):
            continue
        peak = int(np.argmax(speeds))
        limbs.append(
            LimbStats(
                name=limb_name,
                mean_speed=float(speeds.mean()),
                peak_speed=float(speeds[peak]),
                peak_frame=peak,
                mean_direction_deg=_direction_mean(frames, joint),
                path_length=_path_length(frames, joint, meta),
                path=simplified_path(frames, joint),
            )
        )
    if events is None:
        from vfxglow.analysis.events import EventDetector
        from vfxglow.config import EventsConfig

        events = EventDetector(EventsConfig()).detect(frames, meta)
    objects = seen_objects(frames)
    people = sorted({person.person_id for frame in frames for person in frame.people})
    return MotionBrief(
        version="1.0",
        video=meta,
        person_id=person_id,
        anchors=_anchors(frames),
        limbs=limbs,
        events=events,
        objects=objects,
        summary=_summary(limbs, events, objects),
        beats=beats or [],
        people=people,
        scene=scene or [],
        audio_onsets=audio_onsets or [],
    )
