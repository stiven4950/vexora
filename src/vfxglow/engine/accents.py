"""Acentos de impacto, arcos de velocidad, silueta, contorno de pigmento y tinte."""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import FrameRecord
from vfxglow.director.schema import Effect
from vfxglow.engine.glyphs import boil_jitter, draw_glyph, resolve_glyph
from vfxglow.engine.raster import empty_layer, splat, stroke_polyline


def draw_impact(runtime, layer: np.ndarray, origin: np.ndarray, envelope: float) -> None:
    effect = runtime.effect
    radius = max(18.0, effect.style.thickness * layer.shape[0] * 0.45) * (0.55 + 0.45 * envelope)
    step = max(effect.style.boil_frames, 1)
    boiled = runtime.effect.style.seed_offset + (0 if step <= 1 else (0))
    seed = (int(origin[0]) * 13 + int(origin[1]) * 7 + (boiled // step) * step) & 0xFFFFFFFF
    rng = np.random.default_rng(seed if effect.style.boil_frames <= 1 else (seed // max(effect.style.boil_frames, 1)))
    color = effect.style.colors[0]
    shapes = [_zigzag, _star, _spiral, _burst]
    for index, shape in enumerate(shapes):
        if rng.random() > 0.72 and index:
            continue
        angle = float(rng.uniform(0, np.pi * 2))
        points = shape(origin, radius * float(rng.uniform(0.7, 1.15)), angle, rng)
        jitter = boil_jitter(effect, int(origin.sum()) % 97, len(points), radius * 0.04)
        stroke_polyline(layer, points + jitter, color, max(2.0, radius * 0.06), effect.style.hdr_gain * envelope)


def draw_smear(runtime, points: dict[str, np.ndarray], layer: np.ndarray, envelope: float) -> None:
    effect = runtime.effect
    origin = points.get(effect.target.id)
    if origin is None or envelope <= 0:
        return
    velocity = points.get(f"vel:{effect.target.id}")
    if velocity is None:
        return
    speed = float(np.linalg.norm(velocity))
    if speed < 4:
        return
    direction = velocity / speed
    normal = np.array([-direction[1], direction[0]])
    length = min(speed * 4.0, layer.shape[0] * 0.28)
    bow = max(10.0, length * 0.28)
    start = origin - direction * length
    end = origin
    arc = []
    for step in range(16):
        t = step / 15
        center = start * (1 - t) + end * t
        arc.append(center + normal * np.sin(t * np.pi) * bow)
    color = effect.style.colors[0]
    stroke_polyline(layer, np.asarray(arc), color, max(6.0, bow * 0.55), effect.style.hdr_gain * envelope, alpha=0.85)


def draw_silhouette(runtime, track: FrameRecord | None, width: int, height: int, layer: np.ndarray, envelope: float) -> None:
    if track is None or envelope <= 0:
        return
    pts = [np.array([lm.x * width, lm.y * height]) for lm in track.pose if lm.c > 0.2]
    if len(pts) < 6:
        return
    cloud = np.stack(pts)
    center = cloud.mean(axis=0)
    angles = np.arctan2(cloud[:, 1] - center[1], cloud[:, 0] - center[0])
    order = np.argsort(angles)
    hull = cloud[order]
    hull = np.vstack([hull, hull[0]])
    effect = runtime.effect
    color = effect.style.colors[0]
    stroke_polyline(layer, hull, color, max(2.5, effect.style.thickness * height * 0.15), effect.style.hdr_gain * envelope * 0.7)


def draw_contour(runtime, poly: np.ndarray | None, layer: np.ndarray, envelope: float, closed_loop: bool = True) -> None:
    if poly is None or len(poly) < 4 or envelope <= 0:
        return
    effect = runtime.effect
    closed = np.vstack([poly, poly[0]]) if closed_loop else poly
    color = effect.style.colors[0]
    width = max(2.0, effect.style.thickness * layer.shape[0] * 0.12)
    if effect.style.dash > 0:
        _dashed(layer, closed, color, width, effect.style.hdr_gain * envelope, effect.style.dash)
    else:
        stroke_polyline(layer, closed, color, width, effect.style.hdr_gain * envelope)
        stroke_polyline(layer, closed, color, width * 2.4, effect.style.hdr_gain * envelope * 0.25)


def draw_tip_flame(runtime, origin: np.ndarray | None, layer: np.ndarray, envelope: float) -> None:
    if origin is None or envelope <= 0:
        return
    effect = runtime.effect
    color = np.asarray(effect.style.colors[0], dtype=np.float32)
    height = max(16.0, effect.style.thickness * layer.shape[0] * 0.35) * envelope
    tip = origin + np.array([0.0, -height])
    base_l = origin + np.array([-height * 0.28, height * 0.05])
    base_r = origin + np.array([height * 0.28, height * 0.05])
    stroke_polyline(layer, np.stack([base_l, tip, base_r]), color, max(2.0, height * 0.18), effect.style.hdr_gain * envelope)
    splat(layer, float(tip[0]), float(tip[1]), height * 0.35, color, 0.9 * envelope, runtime.kernels)


def draw_feature_light(
    runtime,
    points: dict[str, np.ndarray],
    layer: np.ndarray,
    envelope: float,
) -> None:
    # El veto de rasgos que ya brillan vive en engine/constraints.py.
    if envelope <= 0:
        return
    effect = runtime.effect
    name = effect.target.id
    origin = points.get(name)
    if origin is None:
        return
    color = np.asarray(effect.style.colors[0], dtype=np.float32)
    radius = max(4.0, effect.style.thickness * layer.shape[0] * 0.08)
    splat(layer, float(origin[0]), float(origin[1]), radius, color, envelope, runtime.kernels)
    splat(layer, float(origin[0]), float(origin[1]), radius * 2.2, color, envelope * 0.35, runtime.kernels)


def draw_grade(effect: Effect, layer: np.ndarray, envelope: float) -> None:
    if envelope <= 0:
        return
    color = np.asarray(effect.style.colors[0], dtype=np.float32)
    alpha = float(np.clip(0.45 * effect.style.intensity * envelope, 0.0, 0.75))
    layer[..., :3] = color * alpha
    layer[..., 3] = alpha


def draw_anchored_glyph(runtime, points: dict[str, np.ndarray], layer: np.ndarray, envelope: float) -> None:
    if envelope <= 0 or not runtime.effect.style.glyph:
        return
    glyph = resolve_glyph(runtime.effect.style.glyph)
    if glyph is None:
        return
    origin = points.get(runtime.effect.target.id)
    if origin is None:
        origin = points.get("nose")
    if origin is None:
        return
    left = points.get("left_shoulder")
    right = points.get("right_shoulder")
    shoulder = float(np.linalg.norm(left - right)) if left is not None and right is not None else layer.shape[0] * 0.18
    color = runtime.effect.style.colors[0]
    width = max(2.0, shoulder * 0.035)
    jitter = boil_jitter(runtime.effect, 0, 8, width * 0.4)
    draw_glyph(layer, glyph, origin, shoulder, color, width, runtime.effect.style.hdr_gain * envelope, jitter=None)
    _ = jitter


def _dashed(layer, points, color, width, gain, dash) -> None:
    stride = 2 if dash < 12 else 3
    for index in range(0, len(points) - 1, stride):
        stroke_polyline(layer, points[index : index + 2], color, width, gain)


def _zigzag(origin, radius, angle, rng) -> np.ndarray:
    pts = []
    for i in range(7):
        t = i / 6
        base = origin + np.array([np.cos(angle), np.sin(angle)]) * radius * (t * 2 - 1)
        side = np.array([-np.sin(angle), np.cos(angle)]) * radius * 0.35 * (1 if i % 2 == 0 else -1)
        pts.append(base + side)
    return np.asarray(pts)


def _star(origin, radius, angle, rng) -> np.ndarray:
    pts = []
    for i in range(11):
        r = radius if i % 2 == 0 else radius * 0.4
        a = angle + i * np.pi / 5
        pts.append(origin + np.array([np.cos(a), np.sin(a)]) * r)
    pts.append(pts[0])
    return np.asarray(pts)


def _spiral(origin, radius, angle, rng) -> np.ndarray:
    pts = []
    for i in range(28):
        t = i / 27
        a = angle + t * np.pi * 3
        pts.append(origin + np.array([np.cos(a), np.sin(a)]) * radius * t)
    return np.asarray(pts)


def _burst(origin, radius, angle, rng) -> np.ndarray:
    pts = [origin]
    for i in range(6):
        a = angle + i * np.pi / 3
        pts.append(origin + np.array([np.cos(a), np.sin(a)]) * radius * float(rng.uniform(0.6, 1.0)))
        pts.append(origin)
    return np.asarray(pts)
