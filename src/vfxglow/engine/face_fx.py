"""Anillos sobre los ojos, delineado del rostro y dibujos trazo a trazo del director."""

from __future__ import annotations

import colorsys
from functools import lru_cache

import numpy as np

from vfxglow.analysis.names import FACE_FEATURE_GROUPS, FACE_FEATURES
from vfxglow.director.schema import Effect
from vfxglow.engine.anchors import feature_polyline, local_frame, to_image
from vfxglow.engine.glyphs import _path_d, boil_jitter
from vfxglow.engine.raster import splat, stroke_batch
from vfxglow.geom import catmull_rom

# Esquinas y párpados de cada ojo en la malla.
_EYE_KEYS = {
    "right": {"corners": (33, 133), "lids": (159, 145), "iris": (469, 470, 471, 472)},
    "left": {"corners": (362, 263), "lids": (386, 374), "iris": (474, 475, 476, 477)},
}


def cycle_color(effect: Effect, t: float) -> np.ndarray:
    """Color que recorre la paleta de forma cíclica. Con un solo color, gira el tono."""
    colors = np.asarray(effect.style.colors, dtype=np.float32)
    t = t % 1.0
    if len(colors) > 1:
        x = t * len(colors)
        i = int(x) % len(colors)
        f = x - int(x)
        return colors[i] * (1 - f) + colors[(i + 1) % len(colors)] * f
    if effect.style.hue_speed <= 0:
        return colors[0]
    h, s, v = colorsys.rgb_to_hsv(*[float(c) for c in colors[0]])
    return np.asarray(colorsys.hsv_to_rgb((h + t) % 1.0, s, v), dtype=np.float32)


def draw_progress(runtime) -> float:
    frames = runtime.effect.style.draw_on
    if frames <= 0:
        return 1.0
    return float(np.clip(runtime.active_frames / frames, 0.0, 1.0))


def trim(polylines: list[np.ndarray], progress: float) -> tuple[list[np.ndarray], np.ndarray | None]:
    """Recorta el conjunto de trazos a `progress` de su longitud total, en orden. Devuelve la punta."""
    if progress >= 1.0:
        return polylines, None
    lengths = [float(np.linalg.norm(np.diff(line, axis=0), axis=1).sum()) for line in polylines]
    budget = sum(lengths) * max(progress, 0.0)
    out: list[np.ndarray] = []
    tip = None
    for line, length in zip(polylines, lengths, strict=True):
        if budget <= 0:
            break
        if length <= budget:
            out.append(line)
            budget -= length
            tip = line[-1]
            continue
        seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
        acc = np.concatenate([[0.0], np.cumsum(seg)])
        k = int(np.searchsorted(acc, budget)) - 1
        k = int(np.clip(k, 0, len(seg) - 1))
        f = (budget - acc[k]) / max(seg[k], 1e-6)
        end = line[k] * (1 - f) + line[k + 1] * f
        out.append(np.vstack([line[: k + 1], end]))
        tip = end
        break
    return out, tip


def draw_eye_rings(runtime, points: dict[str, np.ndarray], frame_index: int, layer: np.ndarray, gain: float) -> None:
    if gain <= 0:
        return
    effect = runtime.effect
    style = effect.style
    fps = max(getattr(runtime, "fps", 30.0), 1.0)
    strokes = []
    for side, keys in _EYE_KEYS.items():
        center = points.get(f"{side}_iris")
        if center is None:
            continue
        a = points.get(f"face_{keys['corners'][0]}")
        b = points.get(f"face_{keys['corners'][1]}")
        if a is not None and b is not None:
            eye_w = float(np.linalg.norm(b - a))
            angle = float(np.arctan2(b[1] - a[1], b[0] - a[0]))
        else:
            other = points.get("left_iris" if side == "right" else "right_iris")
            if other is None:
                continue
            eye_w = float(np.linalg.norm(other - center)) * 0.45
            angle = float(np.arctan2(other[1] - center[1], other[0] - center[0]))
        if eye_w < 3.0:
            continue
        top = points.get(f"face_{keys['lids'][0]}")
        bottom = points.get(f"face_{keys['lids'][1]}")
        openness = float(np.linalg.norm(top - bottom)) / eye_w if top is not None and bottom is not None else 0.3
        # Se aplasta con el párpado y se apaga en el parpadeo.
        lid = float(np.clip((openness - 0.06) / 0.14, 0.0, 1.0))
        if lid <= 0:
            continue
        squash = float(np.clip(openness / 0.3, 0.35, 1.0))
        edge = [points[f"face_{i}"] for i in keys["iris"] if f"face_{i}" in points]
        iris_r = float(np.mean([np.linalg.norm(p - center) for p in edge])) if edge else eye_w * 0.2
        iris_r = max(iris_r, 2.5)
        rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        for ring in range(max(1, style.rings)):
            radius = iris_r * (1.35 + 0.6 * ring) * (0.9 + 0.1 * gain)
            direction = 1.0 if ring % 2 == 0 else -1.0
            phase = direction * style.spin * 2 * np.pi * frame_index / fps + ring * 0.9 + (0.4 if side == "left" else 0.0)
            color = cycle_color(effect, frame_index * style.hue_speed + ring / max(style.rings, 1))
            dashes = 5 + 2 * ring
            duty = 0.62
            for dash in range(dashes):
                start = phase + dash * 2 * np.pi / dashes
                theta = np.linspace(start, start + duty * 2 * np.pi / dashes, 9)
                local = np.stack([np.cos(theta) * radius, np.sin(theta) * radius * squash], axis=1)
                arc = local @ rot.T + center
                width = max(1.2, iris_r * style.thickness * 3.0)
                strokes.append((arc, color, width, lid))
    stroke_batch(layer, strokes, style.hdr_gain * gain)


def _feature_names(spec: str) -> list[str]:
    names: list[str] = []
    for token in (part.strip() for part in spec.split(",")):
        if token in {"", "all", "face"}:
            names.extend(FACE_FEATURES)
        elif token in FACE_FEATURE_GROUPS:
            names.extend(FACE_FEATURE_GROUPS[token])
        elif token in FACE_FEATURES:
            names.append(token)
    return list(dict.fromkeys(names)) or list(FACE_FEATURES)


def draw_face_linework(runtime, points: dict[str, np.ndarray], frame_index: int, layer: np.ndarray, gain: float) -> None:
    if gain <= 0:
        return
    effect = runtime.effect
    frame = local_frame(points, "face")
    if frame is None:
        return
    unit = float(np.linalg.norm(frame[1]))
    lines = []
    for name in _feature_names(effect.target.id):
        raw = feature_polyline(points, name)
        if raw is None:
            continue
        curve = catmull_rom(raw, samples_per_seg=3)
        jitter = boil_jitter(effect, frame_index, len(curve), unit * 0.012)
        lines.append(curve + jitter)
    _draw_lines(runtime, lines, unit, frame_index, layer, gain)


def draw_drawing(runtime, points: dict[str, np.ndarray], frame_index: int, layer: np.ndarray, gain: float) -> None:
    effect = runtime.effect
    drawing = effect.style.drawing
    if gain <= 0 or drawing is None:
        return
    frame = local_frame(points, drawing.space)
    if frame is None:
        return
    sets = [drawing.strokes, *drawing.variants]
    sets = [item for item in sets if item]
    if not sets:
        return
    chosen = sets[(frame_index // max(drawing.variant_every, 1)) % len(sets)] if len(sets) > 1 else sets[0]
    unit = float(np.linalg.norm(frame[1]))
    lines = []
    for d in chosen:
        local = _parsed(d)
        if len(local) < 2:
            continue
        placed = to_image(local, frame)
        lines.append(placed + boil_jitter(effect, frame_index, len(placed), unit * 0.01))
    _draw_lines(runtime, lines, unit, frame_index, layer, gain)


def _draw_lines(runtime, lines: list[np.ndarray], unit: float, frame_index: int, layer: np.ndarray, gain: float) -> None:
    if not lines:
        return
    effect = runtime.effect
    lines, tip = trim(lines, draw_progress(runtime))
    width = max(1.5, unit * effect.style.thickness * 0.5)
    color = cycle_color(effect, frame_index * effect.style.hue_speed)
    strokes = [(line, color, width, 1.0) for line in lines]
    strokes += [(line, color, width * 2.2, 0.14) for line in lines]
    stroke_batch(layer, strokes, effect.style.hdr_gain * gain)
    if tip is not None:
        splat(layer, float(tip[0]), float(tip[1]), width * 3.0, color * effect.style.hdr_gain * 1.5, gain, runtime.kernels)


@lru_cache(maxsize=512)
def _parsed_cached(d: str) -> tuple[tuple[float, float], ...]:
    return tuple(map(tuple, _path_d(d).tolist()))


def _parsed(d: str) -> np.ndarray:
    return np.asarray(_parsed_cached(d), dtype=np.float64).reshape(-1, 2)
