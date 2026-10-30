"""Heridas de luz sobre el rostro (adornos `type: adornment`).

Solo luz: nada de piel cortada ni sangre real, sino líneas de neón rojo pegadas a la cara. Al final
se sueltan en polvo (engine/dissolve.py).

- face_claws: un zarpazo de cuatro tajos que se abren en la mejilla o la frente y gotean luz.
- face_stitches: una cicatriz que se traza sola y se cose, puntada por puntada.
- face_cracks: la piel se raja desde un punto y por las grietas sale luz de brasa.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import melt
from vfxglow.engine.face_glow import Face, _seed, _trim
from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
WOUNDS = ("face_claws", "face_stitches", "face_cracks")
WOUND = np.array([1.0, 0.08, 0.16], np.float32)
EMBER = np.array([1.0, 0.42, 0.08], np.float32)
THREAD = np.array([1.0, 0.9, 0.85], np.float32)
# Cicatrices posibles, en coordenadas de cara, para que no caigan sobre los ojos.
SCARS = (
    ((-0.95, -0.55), (-0.45, -0.68), (0.05, -0.5), (0.55, -0.62)),
    ((-0.92, 0.3), (-0.62, 0.62), (-0.42, 1.0)),
    ((0.92, 0.3), (0.62, 0.62), (0.42, 1.0)),
    ((0.2, -0.85), (0.32, -0.45), (0.72, 0.38), (0.86, 0.72)),
)
STITCH_EVERY = 0.15
STITCH_LEN = 0.09


def _claws(face: Face, u: float, layer, alpha: float, kernels, rng) -> list:
    forehead = rng.uniform() < 0.3
    side = 1.0 if rng.uniform() < 0.5 else -1.0
    if forehead:
        start, end = np.array([-0.75 * side, -0.85]), np.array([0.65 * side, -0.32])
    else:
        if not face.visible("left" if side > 0 else "right"):
            side = -side
        start, end = np.array([0.4 * side, 0.32]), np.array([0.82 * side, 1.2])
    d = (end - start) / float(np.linalg.norm(end - start))
    n = np.array([-d[1], d[0]])
    out: list = []
    for k in range(4):
        draw = _ease(_seg(u, k * 0.025, k * 0.025 + 0.09))  # se abren rápido, una tras otra
        if draw <= 0:
            continue
        q = np.linspace(0.0, 1.0, 18)
        shift = (k - 1.5) * 0.17
        spine = start + np.outer(q, end - start) * (0.86 + 0.1 * (k % 2)) + np.outer(shift + np.sin(np.pi * q) * 0.06, n)
        spine = spine[: max(int(len(q) * draw), 2)]
        taper = np.sin(np.pi * np.linspace(0.0, 1.0, len(spine))) * 0.038 * (0.5 + 0.5 * draw) + 0.002
        sliver = np.vstack([spine + np.outer(taper, n), (spine - np.outer(taper, n))[::-1]])
        gash = face.place(sliver)
        fill_polygon(layer, gash, WOUND, alpha * 0.8, 1.0, feather=1.0)
        out.append((np.vstack([gash, gash[:1]]), WOUND))
        for j in range(3):  # gotas que bajan despacio por la piel
            at = spine[int((j + 0.5) / 3 * (len(spine) - 1))]
            begin = 0.14 + 0.09 * j + 0.04 * k
            fall = _ease(_seg(u, begin, begin + 0.55)) * (0.28 + 0.1 * ((j + k) % 3))
            if fall <= 0:
                continue
            drip = face.place(np.array([at, at + [0.0, fall]]))
            out.append((drip, WOUND * 0.8))
            splat(layer, float(drip[1, 0]), float(drip[1, 1]), 0.03 * face.unit + 0.5, WOUND, alpha, kernels)
    return out


def _stitches(face: Face, u: float, layer, alpha: float, kernels, rng) -> list:
    usable = [k for k, scar in enumerate(SCARS) if (scar[0][0] >= -0.5 or face.visible("right")) and (scar[0][0] <= 0.5 or face.visible("left"))]
    scar = np.array(SCARS[usable[int(rng.integers(len(usable)))]], dtype=np.float64)
    from vfxglow.geom import catmull_rom

    local = catmull_rom(scar, 10)
    acc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(local, axis=0), axis=1))])
    drawn = _ease(_seg(u, 0.0, 0.22))
    out: list = [(_trim(face.place(local), drawn), WOUND)]
    marks = np.arange(STITCH_EVERY / 2, acc[-1], STITCH_EVERY)
    for k, s in enumerate(marks):  # puntada por puntada, después de la herida
        on = _seg(u, 0.2 + 0.32 * k / len(marks), 0.2 + 0.32 * (k + 1) / len(marks))
        if on <= 0:
            continue
        here = np.array([np.interp(s, acc, local[:, 0]), np.interp(s, acc, local[:, 1])])
        ahead = np.array([np.interp(s + 0.03, acc, local[:, 0]), np.interp(s + 0.03, acc, local[:, 1])])
        d = (ahead - here) / max(float(np.linalg.norm(ahead - here)), 1e-6)
        n = np.array([-d[1], d[0]])
        slant = n * STITCH_LEN * on + d * 0.02
        cross = face.place(np.array([here - slant, here + slant]))
        out.append((cross, THREAD))
        if on < 1.0:  # la chispa de la aguja
            splat(layer, float(cross[1, 0]), float(cross[1, 1]), 0.05 * face.unit, THREAD, alpha, kernels)
    return out


def _crack_branches(rng) -> tuple[np.ndarray, list[np.ndarray]]:
    origin = np.array([rng.choice([-0.55, 0.55]), rng.uniform(0.3, 0.8)]) if rng.uniform() < 0.6 else np.array([rng.uniform(-0.3, 0.3), -0.65])
    branches = []
    for k in range(7):
        angle = TAU * k / 7 + rng.uniform(-0.3, 0.3)
        path = [origin]
        heading = angle
        for _step in range(int(rng.integers(5, 9))):
            heading += rng.uniform(-0.65, 0.65)
            path.append(path[-1] + np.array([np.cos(heading), np.sin(heading)]) * rng.uniform(0.07, 0.15))
            if rng.uniform() < 0.3:  # una rama
                turn = heading + rng.choice([-1.0, 1.0]) * rng.uniform(0.6, 1.1)
                branches.append(np.array([path[-1], path[-1] + np.array([np.cos(turn), np.sin(turn)]) * rng.uniform(0.1, 0.22)]))
        branches.append(np.array(path))
    return origin, branches


def _cracks(face: Face, u: float, frame_index: int, layer, alpha: float, kernels, rng) -> list:
    origin, branches = _crack_branches(rng)
    grow = _ease(_seg(u, 0.0, 0.32))
    out: list = []
    for k, branch in enumerate(branches):
        part = _seg(grow, k * 0.3 / len(branches), 1.0)
        if part > 0:
            out.append((_trim(face.place(branch), part), EMBER))
    pulse = 0.65 + 0.35 * np.sin(frame_index * 0.35)
    center = face.place(origin.reshape(1, 2))[0]
    splat(layer, float(center[0]), float(center[1]), 0.22 * face.unit, EMBER, alpha * 0.5 * pulse * grow, kernels)
    if u > 0.3:  # brasas que se escapan de las grietas
        ages = (frame_index * 0.04 + np.linspace(0.0, 1.0, 24, endpoint=False)) % 1.0
        for k, age in enumerate(ages):
            line = branches[k % len(branches)]
            at = face.place(line[int(k % len(line))].reshape(1, 2))[0] - face.uy / face.unit * age * 0.7 * face.unit
            splat(layer, float(at[0]), float(at[1]), 0.02 * face.unit + 0.5, EMBER * 1.3, alpha * (1 - age), kernels)
    return out


def face_wound(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    seed = _seed(shape, body, event)
    rng = np.random.default_rng(seed)
    if shape == "face_claws":
        items = _claws(face, u, layer, alpha, runtime.kernels, rng)
    elif shape == "face_stitches":
        items = _stitches(face, u, layer, alpha, runtime.kernels, rng)
    else:
        items = _cracks(face, u, frame_index, layer, alpha, runtime.kernels, rng)
    return melt(items, u, face, layer, color, alpha, runtime.kernels, seed)
