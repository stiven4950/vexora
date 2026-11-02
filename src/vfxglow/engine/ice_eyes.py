"""Ojos de hielo: el iris se vuelve azul eléctrico, grietas de luz, escarcha y cristales.

Es la pareja fría de Cleopatra (engine/cleopatra.py). El iris se tiñe poco a poco y alrededor del ojo
crecen grietas finas que se ramifican; sobre las pestañas sale escarcha. Al abrir los ojos después de
parpadear se sueltan cristales diminutos que suben y se apagan, y mientras tanto cae una nieve fina.
Solo luz sobre la cara, con línea fina: lo pequeño con mucho halo se vuelve una mancha.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _seg
from vfxglow.engine.dissolve import fine, melt
from vfxglow.engine.face_glow import Face, _trim
from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
ICE = np.array([0.45, 0.85, 1.0], np.float32)
ICE_DEEP = np.array([0.1, 0.45, 1.0], np.float32)
FROST = np.array([0.85, 0.97, 1.0], np.float32)
# Fases: el iris se tiñe y las grietas crecen.
IRIS_END = 0.14
CRACKS_END = 0.32
IRIS_RADIUS = 0.11
CRACKS = 4
FROST_EVERY = 2
FROST_SPIKE = 0.1
# Cristales al parpadear: cuántos por ojo, cuánto viven (cuadros de 30 fps) y hasta dónde suben.
SHARDS = 9
SHARD_LIFE = 34
SHARD_RISE = 1.5
SNOW = 26


def _cracks(eye: np.ndarray, across: np.ndarray, down: np.ndarray, out: float, unit: float, rng) -> list[np.ndarray]:
    """Grietas quebradas que salen del ojo hacia la sien y la mejilla, con una rama cada una."""
    lines = []
    for k in range(CRACKS):
        angle = rng.uniform(-0.9, 1.5)
        length = rng.uniform(0.32, 0.6)
        steps = 6
        q = (0.42 + 0.58 * np.linspace(0.0, 1.0, steps)) * length
        jitter = np.concatenate([[0.0], rng.uniform(-0.04, 0.04, steps - 1)])
        x, y = np.cos(angle) * q + jitter * np.sin(angle), np.sin(angle) * q + jitter * np.cos(angle)
        line = eye + np.outer(x * out * unit, across) + np.outer(y * unit, down)
        lines.append(line)
        turn = angle + rng.choice([-0.7, 0.7])
        tail = rng.uniform(0.08, 0.16) * np.linspace(0.0, 1.0, 3)
        lines.append(line[3] + np.outer(np.cos(turn) * tail * out * unit, across) + np.outer(np.sin(turn) * tail * unit, down))
    return lines


def _shard(center: np.ndarray, size: float, turn: float) -> np.ndarray:
    a = turn + np.array([0.0, 0.5, 1.0, 1.5, 2.0]) * np.pi
    r = np.array([1.0, 0.4, 1.0, 0.4, 1.0]) * size
    return center + np.stack([np.cos(a) * r, np.sin(a) * r], axis=1)


def ice_eyes(face: Face, u: float, frame_index: int, runtime, layer, alpha: float, seed: int, event) -> list:
    e = getattr(runtime, "expressions", {}) or {}
    across, down = face.ux / face.unit, face.uy / face.unit
    st = runtime.swoosh.setdefault(f"_ice:{event.start_frame if event else 0}", {"shut": 0.0, "shards": []})
    blink = max(float(e.get("eyeBlinkLeft", 0.0)), float(e.get("eyeBlinkRight", 0.0)))
    opened = st["shut"] > 0.5 and blink < 0.35
    st["shut"] = blink
    tint = _ease(_seg(u, 0.0, IRIS_END))
    grow = _ease(_seg(u, IRIS_END * 0.5, CRACKS_END))
    lit = 1.0 - min(blink * 1.4, 1.0)
    lines: list[np.ndarray] = []
    for side, out in (("right", -1.0), ("left", 1.0)):
        if not face.visible(side):
            continue
        eye = face.at(f"{side}_iris", (0.5 * out, 0.0))
        t = np.linspace(0.0, TAU, 26)
        radius = IRIS_RADIUS * face.unit
        circle = eye + np.stack([np.cos(t), np.sin(t)], axis=1) * radius
        if lit > 0.0 and tint > 0.0:
            fill_polygon(layer, circle, ICE_DEEP, alpha * 0.6 * tint * lit, 1.0, feather=1.5)
            fine([circle], ICE, alpha * 0.45 * tint * lit, layer, width=1.0)
        rng = np.random.default_rng(seed + (0 if side == "right" else 1))
        lines += [_trim(crack, grow) for crack in _cracks(eye, across, down, out, face.unit, rng) if grow > 0.0]
        lid = face.feature(f"{side}_eye")
        if lid is not None and len(lid) > 4 and grow > 0.0:  # la escarcha: púas sobre el párpado
            upper = lid[: len(lid) // 2 + 1]
            for k in range(0, len(upper), FROST_EVERY):
                tall = FROST_SPIKE * face.unit * grow * (0.6 + 0.4 * float(np.sin(k * 1.9)))
                lines.append(np.array([upper[k], upper[k] - down * tall]))
        if opened:  # abrió los ojos: los cristales se sueltan
            for k in range(SHARDS):
                a = rng.uniform(0.0, TAU)
                st["shards"].append({"at": eye + np.array([np.cos(a), np.sin(a)]) * 0.3 * face.unit, "born": frame_index, "turn": a, "drift": rng.uniform(-0.5, 0.5)})
    kept = []
    for shard in st["shards"]:
        age = (frame_index - shard["born"]) / SHARD_LIFE
        if age >= 1.0:
            continue
        kept.append(shard)
        at = shard["at"] + (-down * age * SHARD_RISE + across * shard["drift"] * age) * face.unit
        fine([_shard(at, 0.06 * face.unit + 1.0, shard["turn"] + age * 3.0)], FROST, alpha * (1.0 - age), layer, width=1.0)
    st["shards"] = kept
    rng = np.random.default_rng(seed)
    start = rng.uniform(-2.2, 2.2, (SNOW, 2))
    speed = rng.uniform(0.5, 1.2, SNOW)
    for k in range(SNOW):  # nieve fina alrededor de la cabeza
        age = (frame_index * 0.012 * speed[k] + k * 0.618) % 1.0
        at = face.place([(start[k, 0], start[k, 1] * 0.5 - 1.0 + age * 2.6)])[0]
        splat(layer, float(at[0]), float(at[1]), 0.012 * face.unit + 0.7, FROST, alpha * 0.7 * tint * float(np.sin(age * np.pi)), runtime.kernels)
    left = melt([(line, ICE) for line in lines], u, face, layer, ICE, alpha, runtime.kernels, seed)
    fine([item[0] if isinstance(item, tuple) else item for item in left], ICE, alpha, layer, width=max(1.0, 0.008 * face.unit))
    return []
