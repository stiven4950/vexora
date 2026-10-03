"""Señales de apariencia del plano: pigmento activo, punta, rasgos y brillo ya presente.

No segmenta con un modelo generativo. Compara el fotograma con un fondo lento
y se queda con la mancha que toca la mano. La silueta se calcula al render,
desde la pose, para no guardar máscaras.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import Beat, FrameRecord, VideoMeta

log = logging.getLogger("vfxglow.appearance")

_SMALL = (180, 320)


@dataclass
class Appearance:
    contours: dict[int, list[tuple[float, float]]] = field(default_factory=dict)
    tips: dict[int, tuple[float, float]] = field(default_factory=dict)
    bright: list[str] = field(default_factory=list)
    bright_spans: list[tuple[int, int, str]] = field(default_factory=list)
    features: dict[str, tuple[float, float]] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "contours": [{"frame": frame, "points": points} for frame, points in sorted(self.contours.items())],
            "tips": [{"frame": frame, "point": point} for frame, point in sorted(self.tips.items())],
            "bright": self.bright,
            "bright_spans": [{"start": a, "end": b, "region": region} for a, b, region in self.bright_spans],
            "features": self.features,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Appearance:
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            contours={int(item["frame"]): [tuple(p) for p in item["points"]] for item in raw.get("contours", [])},
            tips={int(item["frame"]): tuple(item["point"]) for item in raw.get("tips", [])},
            bright=list(raw.get("bright", [])),
            bright_spans=[(int(item["start"]), int(item["end"]), str(item["region"])) for item in raw.get("bright_spans", [])],
            features={name: tuple(point) for name, point in raw.get("features", {}).items()},
        )


def analyze_appearance(video_path: Path, frames: list[FrameRecord], meta: VideoMeta) -> Appearance:
    """Recorre el plano una vez. El fondo lento hace que solo sobreviva la mancha nueva."""
    cap = cv2.VideoCapture(str(video_path))
    acc: np.ndarray | None = None
    out = Appearance()
    bright_eyes = 0
    eye_samples = 0
    width_s, height_s = _SMALL
    for record in frames:
        ok, frame = cap.read()
        if not ok:
            break
        _sample_features(out, record)
        if _eyes_bright(frame, record):
            bright_eyes += 1
            out.bright_spans.append((record.frame, record.frame, "eyes"))
        if record.pose:
            eye_samples += 1
        small = cv2.resize(frame, _SMALL)
        if acc is None:
            acc = small.astype(np.float32)
            continue
        delta = cv2.absdiff(small, np.clip(acc, 0, 255).astype(np.uint8))
        mask = (delta.mean(axis=2) > 26).astype(np.uint8) * 255
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        wrist, direction = _wrist_and_direction(record)
        if wrist is not None:
            kept = _component_near(mask, (wrist[0] * width_s, wrist[1] * height_s), direction, width_s, height_s)
            if kept is not None:
                contour, tip = kept
                out.contours[record.frame] = [(x / width_s, y / height_s) for x, y in contour]
                out.tips[record.frame] = (tip[0] / width_s, tip[1] / height_s)
        acc = acc * 0.9 + small.astype(np.float32) * 0.1
    cap.release()
    out.bright_spans = _merge_spans(out.bright_spans)
    if eye_samples and bright_eyes / max(eye_samples, 1) > 0.35:
        out.bright.append("eyes")
    log.info("Pigmento en %d fotogramas; rasgos brillantes: %s", len(out.contours), out.bright or "ninguno")
    return out


def retag_paint_beats(beats: list[Beat], appearance: Appearance) -> list[Beat]:
    """Un beat con mucha mancha es pintura ancha; con poca, detalle."""
    updated: list[Beat] = []
    for beat in beats:
        if beat.kind == "cut":
            updated.append(beat)
            continue
        count = sum(1 for frame in range(beat.start_frame, beat.end_frame + 1) if frame in appearance.contours)
        span = max(beat.end_frame - beat.start_frame + 1, 1)
        fraction = count / span
        if fraction > 0.45:
            kind = "paint_broad"
        elif fraction > 0.12:
            kind = "paint_detail"
        else:
            kind = beat.kind
        updated.append(beat.model_copy(update={"kind": kind}))
    return updated


def _sample_features(out: Appearance, record: FrameRecord) -> None:
    named = {lm.name: (lm.x, lm.y) for lm in record.pose if lm.c > 0.2}
    for source, dest in (("left_eye", "left_eye"), ("right_eye", "right_eye"), ("nose", "nose")):
        if source in named:
            out.features[dest] = named[source]
    if "mouth_left" in named and "mouth_right" in named:
        out.features["mouth"] = (
            (named["mouth_left"][0] + named["mouth_right"][0]) * 0.5,
            (named["mouth_left"][1] + named["mouth_right"][1]) * 0.5,
        )
    if "nose" in named:
        out.features["head_top"] = (named["nose"][0], max(0.0, named["nose"][1] - 0.08))


def _eyes_bright(frame: np.ndarray, record: FrameRecord) -> bool:
    """Ojos casi blancos en un plano claro. En un reveal oscuro no se vetan."""
    if float(frame.mean()) < 70:
        return False
    height, width = frame.shape[:2]
    samples = []
    for name in ("left_eye", "right_eye"):
        point = next(((lm.x, lm.y) for lm in record.pose if lm.name == name and lm.c > 0.2), None)
        if point is None:
            continue
        x = int(np.clip(point[0] * width, 0, width - 1))
        y = int(np.clip(point[1] * height, 0, height - 1))
        patch = frame[max(0, y - 3) : y + 4, max(0, x - 3) : x + 4]
        if patch.size:
            samples.append(float(patch.max()))
    return bool(samples) and float(np.mean(samples)) > 220.0


def _merge_spans(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged = [ordered[0]]
    for start, end, region in ordered[1:]:
        prev_s, prev_e, prev_r = merged[-1]
        if region == prev_r and start <= prev_e + 2:
            merged[-1] = (prev_s, max(prev_e, end), region)
        else:
            merged.append((start, end, region))
    return merged


def tip_touch_events(appearance: Appearance):
    """La punta estimada, sostenida varios fotogramas, es un toque de herramienta."""
    from vfxglow.analysis.schema import MotionEvent

    frames = sorted(appearance.tips)
    if not frames:
        return []
    groups: list[list[int]] = [[frames[0]]]
    for frame in frames[1:]:
        if frame <= groups[-1][-1] + 2:
            groups[-1].append(frame)
        else:
            groups.append([frame])
    events = []
    for group in groups:
        if len(group) < 4:
            continue
        point = appearance.tips[group[len(group) // 2]]
        events.append(
            MotionEvent(
                name="tool_touch",
                target="tool_tip",
                start_frame=group[0],
                end_frame=group[-1],
                confidence=0.8,
                detail="La punta de la herramienta deja pigmento nuevo.",
                position=point,
            )
        )
    return events


def _wrist_and_direction(record: FrameRecord) -> tuple[tuple[float, float] | None, tuple[float, float]]:
    pose = {lm.name: (lm.x, lm.y) for lm in record.pose if lm.c > 0.15}
    best: tuple[float, tuple[float, float], tuple[float, float]] | None = None
    for side in ("left", "right"):
        wrist = pose.get(f"{side}_wrist")
        elbow = pose.get(f"{side}_elbow")
        if wrist is None:
            continue
        speed = next((item.speed for item in record.motion if item.name == f"{side}_wrist" and not item.glitch), 0.0)
        direction = (0.0, -1.0)
        if elbow is not None:
            direction = (wrist[0] - elbow[0], wrist[1] - elbow[1])
        if best is None or speed >= best[0]:
            best = (speed, wrist, direction)
    if best is None or best[0] < 0.01:
        return None, (0.0, -1.0)
    return best[1], best[2]


def _component_near(
    mask: np.ndarray,
    wrist_px: tuple[float, float],
    direction: tuple[float, float],
    width: int,
    height: int,
) -> tuple[list[tuple[float, float]], tuple[float, float]] | None:
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    norm = float(np.hypot(*direction)) or 1.0
    ux, uy = direction[0] / norm, direction[1] / norm
    probe = (wrist_px[0] + ux * 18.0, wrist_px[1] + uy * 18.0)
    chosen = -1
    best = 1e9
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < 40:
            continue
        x = stats[label, cv2.CC_STAT_LEFT] + stats[label, cv2.CC_STAT_WIDTH] * 0.5
        y = stats[label, cv2.CC_STAT_TOP] + stats[label, cv2.CC_STAT_HEIGHT] * 0.5
        dist = float(np.hypot(x - probe[0], y - probe[1]))
        if dist < best and dist < 70:
            best = dist
            chosen = label
    if chosen < 0:
        return None
    component = np.uint8(labels == chosen) * 255
    found, contours = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not found:
        return None
    poly = cv2.approxPolyDP(max(found, key=cv2.contourArea), 2.5, closed=True)
    points = [(float(p[0][0]), float(p[0][1])) for p in poly]
    if len(points) < 4:
        return None
    ys, xs = np.where(labels == chosen)
    if xs.size == 0:
        return None
    scores = (xs - wrist_px[0]) * ux + (ys - wrist_px[1]) * uy
    pick = int(np.argmax(scores))
    tip = (float(xs[pick]), float(ys[pick]))
    if tip[0] < 0 or tip[1] < 0 or tip[0] >= width or tip[1] >= height:
        return None
    return points, tip
