"""Efectos sobre el cuerpo entero.

- xray: esqueleto en rayos X sobre la pose (cráneo, columna, costillas, pelvis, huesos de brazos y
  piernas), para movimientos raros o quiebres.
- wings: alas con plumas que salen de los hombros siguiendo los brazos (brazos en cruz).
- ghost_trail: copias de la silueta de fotogramas anteriores, cada vez más tenues (movimiento
  rápido).
- footprints: huellas de neón donde cayó cada paso (`stomp`), que se desvanecen. Lee los pasos de
  `runtime.steps` (el motor los pone).
"""

from __future__ import annotations

from collections import deque

import numpy as np

from vfxglow.engine.anchors import torso_pixels
from vfxglow.engine.raster import stroke_batch
from vfxglow.engine.swoosh import neon_layers

GHOST_LAGS = (3, 6, 9)
STEP_LIFE_S = 2.0


def _getter(points, event):
    """Puntos de la persona del evento (person_N:...), o los de la principal sin evento."""
    person = None
    if event is not None:
        person = event.attacker or (event.target.split(":", 1)[0] if event.target.startswith("person_") else None)
    prefix = f"{person}:" if person else ""
    return lambda name: points.get(f"{prefix}{name}", points.get(name) if not prefix else None)


def _torso(get, points, height: int) -> float:
    a, b = get("mid_shoulder"), get("left_hip")
    c = get("right_hip")
    if a is not None and b is not None and c is not None:
        return max(float(np.linalg.norm(a - (b + c) / 2)), 8.0)
    return torso_pixels(points, height)


def draw_xray(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    if envelope <= 0:
        return
    get = _getter(points, event)
    p = {name: get(name) for name in ("nose", "left_ear", "right_ear", "left_shoulder", "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle")}
    if p["left_shoulder"] is None or p["right_shoulder"] is None or p["left_hip"] is None or p["right_hip"] is None:
        return
    color = np.asarray(style.colors[0], dtype=np.float32)
    torso = _torso(get, points, height)
    line = max(1.5, style.thickness * torso)
    neck = (p["left_shoulder"] + p["right_shoulder"]) / 2
    pelvis = (p["left_hip"] + p["right_hip"]) / 2
    down = (pelvis - neck) / max(float(np.linalg.norm(pelvis - neck)), 1e-6)
    across = np.array([-down[1], down[0]])
    half = float(np.linalg.norm(p["left_shoulder"] - p["right_shoulder"])) / 2
    bones = [np.stack([neck, pelvis]), np.stack([p["left_shoulder"], p["right_shoulder"]])]
    for k in range(4):  # costillas: arcos que bajan desde la columna
        y = 0.12 + 0.12 * k
        for side in (-1.0, 1.0):
            t = np.linspace(0, 1, 8)
            rib = np.array([neck + down * torso * (y + 0.06 * u) + across * side * half * (0.08 + 0.75 * np.sin(u * np.pi / 2)) for u in t])
            bones.append(rib)
    hips = [pelvis + across * half * s * 0.7 for s in (-1, 1)]
    bones.append(np.array([hips[0], pelvis - down * torso * 0.08, hips[1], pelvis + down * torso * 0.12, hips[0]]))
    for side in ("left", "right"):
        for a, b in (("shoulder", "elbow"), ("elbow", "wrist"), ("hip", "knee"), ("knee", "ankle")):
            pa, pb = p[f"{side}_{a}"], p[f"{side}_{b}"]
            if pa is not None and pb is not None:
                bones.append(np.stack([pa, pb]))
                for end in (pa, pb):  # articulaciones como bolitas
                    theta = np.linspace(0, 2 * np.pi, 10)
                    bones.append(end + np.stack([np.cos(theta), np.sin(theta)], axis=1) * torso * 0.03)
    if p["nose"] is not None:
        ears = [e for e in (p["left_ear"], p["right_ear"]) if e is not None]
        size = float(np.linalg.norm(ears[0] - ears[1])) if len(ears) == 2 else half * 0.8
        theta = np.linspace(0, 2 * np.pi, 30)
        skull = p["nose"] - down * size * 0.25 + np.stack([np.cos(theta) * size * 0.55, np.sin(theta) * size * 0.7], axis=1)
        bones.append(skull)
        for side in (-1.0, 1.0):
            socket = p["nose"] - down * size * 0.15 + across * side * size * 0.2
            bones.append(socket + np.stack([np.cos(theta), np.sin(theta)], axis=1) * size * 0.1)
    strokes = [s for bone in bones for s in neon_layers(bone, color, line, envelope)]
    stroke_batch(layer, strokes, style.hdr_gain)


def _wing(shoulder: np.ndarray, wrist: np.ndarray, torso: float) -> list[np.ndarray]:
    """Ala sobre el brazo: borde de arriba que pasa por la muñeca y plumas que cuelgan abajo."""
    along = wrist - shoulder
    length = float(np.linalg.norm(along))
    if length < 1:
        return []
    out = along / length
    down = np.array([-out[1], out[0]])
    if down[1] < 0:
        down = -down
    tip = wrist + out * torso * 0.35 - down * torso * 0.15
    top = np.array([shoulder - down * torso * 0.1 + out * length * u + (-down) * torso * 0.25 * np.sin(np.pi * u) for u in np.linspace(0, 1, 12)] + [tip])
    feathers = []
    for k in range(5):
        u = 0.2 + 0.18 * k
        base = shoulder + out * (length + torso * 0.3) * u
        drop = torso * (0.35 + 0.25 * (1 - abs(u - 0.6)))
        feathers.append(np.array([base, base + down * drop * 0.6 + out * torso * 0.05, base + down * drop + out * torso * 0.12]))
    return [top, *feathers]


def draw_wings(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    if envelope <= 0:
        return
    get = _getter(points, event)
    torso = _torso(get, points, height)
    color = np.asarray(style.colors[0], dtype=np.float32)
    line = max(1.5, style.thickness * torso)
    strokes = []
    for side in ("left", "right"):
        shoulder, wrist = get(f"{side}_shoulder"), get(f"{side}_wrist")
        if shoulder is not None and wrist is not None:
            for curve in _wing(shoulder, wrist, torso):
                strokes += neon_layers(curve, color, line, envelope)
    stroke_batch(layer, strokes, style.hdr_gain)


def draw_ghost_trail(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    history = runtime.swoosh.setdefault("ghost", deque(maxlen=max(GHOST_LAGS) + 1))
    width = layer.shape[1]
    contour = np.array(track.body_contour) * [width, height] if track is not None and track.body_contour else None
    history.append(contour)
    if envelope <= 0:
        return
    strokes = []
    for k, lag in enumerate(GHOST_LAGS):
        if len(history) > lag and history[-1 - lag] is not None:
            old = history[-1 - lag]
            color = np.asarray(style.colors[k % len(style.colors)], dtype=np.float32)
            strokes += neon_layers(np.vstack([old, old[:1]]), color, 1.6, envelope * (0.7 - 0.18 * k))
    stroke_batch(layer, strokes, style.hdr_gain)


def _footprint(center: np.ndarray, size: float, forward: np.ndarray) -> list[np.ndarray]:
    side = np.array([-forward[1], forward[0]])
    theta = np.linspace(0, 2 * np.pi, 20)
    sole = center + np.outer(np.cos(theta) * size * 0.35, side) + np.outer(np.sin(theta) * size * 0.6, forward)
    toes = [center + forward * size * 0.78 + side * size * dx for dx in (-0.25, -0.08, 0.1, 0.26)]
    return [sole] + [t + np.outer(np.cos(theta[:12]), side) * size * 0.06 + np.outer(np.sin(theta[:12]), forward) * size * 0.06 for t in toes]


def draw_footprints(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    if envelope <= 0:
        return
    width = layer.shape[1]
    torso = torso_pixels(points, height)
    life = STEP_LIFE_S * runtime.fps
    strokes = []
    for frame, position, kind in getattr(runtime, "steps", []):
        age = (frame_index - frame) / life
        if not 0 <= age <= 1 or position is None:
            continue
        center = np.array(position) * [width, height]
        # La huella se ve "desde arriba", aplastada por la perspectiva del piso.
        forward = np.array([0.0, -1.0])
        color = np.asarray(style.colors[0 if kind == "left" else 1 % len(style.colors)], dtype=np.float32)
        for curve in _footprint(center, torso * 0.32, forward):
            curve = center + (curve - center) * np.array([1.0, 0.5])
            strokes += neon_layers(curve, color, 1.6, envelope * (1.0 - age))
    stroke_batch(layer, strokes, style.hdr_gain)
