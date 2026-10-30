"""Bichos de luz que caminan sobre la cara (adornos `type: adornment`, como los filtros de Instagram).

Efectos largos, de varios segundos. Cada bicho sigue una ruta en coordenadas de cara (se queda pegado
aunque la cabeza se mueva): entra por fuera del rostro, cruza la cara haciendo pausas, como un insecto
de verdad (corre, se queda quieto, corre) y sale por otro lado. Las patas se mueven con lo caminado:
si se detiene, se detienen. Del lado de la cara que gira hacia atrás no se dibujan.

- face_spiders: arañas de cuerpo ovalado y ocho patas.
- face_ants: una fila de hormigas por el mismo camino.
- face_centipede: un ciempiés cuyo cuerpo sigue la ruta, con sus patas en ola.
- face_roaches: cucarachas que corren a tirones, con antenas largas.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import _phase
from vfxglow.engine.dissolve import fine
from vfxglow.engine.face_glow import Face, _palette, _seed
from vfxglow.engine.raster import fill_polygon, splat
from vfxglow.geom import catmull_rom

TAU = 2.0 * np.pi
CREATURES = ("face_spiders", "face_ants", "face_centipede", "face_roaches")
# Por dónde entran y salen (óvalo por fuera de la cara) y dónde pueden hacer sus pausas.
GATE = (0.0, 0.45, 1.7, 2.2)
STOPS_ON = ((-0.8, 0.8), (-0.7, 1.45))
# Qué tanto se frena en cada pausa (1 = se detiene del todo).
PAUSE = 0.93
# Por bicho: (cuántos, tamaño en unidades de cara, pausas, entre uno y otro).
KINDS = {"face_spiders": (4, 0.26, 3, 0.1), "face_roaches": (3, 0.24, 4, 0.14), "face_centipede": (1, 0.1, 3, 0.0)}
ANTS = 16
ANT_SIZE = 0.15
ANT_GAP = 0.27
CENTIPEDE_SEGMENTS = 18
CENTIPEDE_GAP = 0.085


def _gate(angle: float) -> tuple[float, float]:
    cx, cy, rx, ry = GATE
    return cx + rx * np.cos(angle), cy + ry * np.sin(angle)


def _route(rng, stops: int) -> np.ndarray:
    """Entra por un lado, pasa por `stops` puntos de la cara y sale por otro."""
    a = rng.uniform(0, TAU)
    b = a + rng.uniform(2.2, 4.0)
    inner = np.stack([rng.uniform(*STOPS_ON[0], stops), rng.uniform(*STOPS_ON[1], stops)], axis=1)
    return catmull_rom(np.vstack([_gate(a), inner, _gate(b)]), 12)


def _lengths(route: np.ndarray) -> np.ndarray:
    return np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(route, axis=0), axis=1))])


def _at(route: np.ndarray, acc: np.ndarray, s: float) -> np.ndarray:
    return np.array([np.interp(s, acc, route[:, 0]), np.interp(s, acc, route[:, 1])])


def _gait(t: float, stops: int) -> float:
    """Avance (0-1) con pausas: corre y se detiene `stops` veces."""
    w = t * (stops + 1)
    return float(np.clip((w - PAUSE * np.sin(TAU * w) / TAU) / (stops + 1), 0.0, 1.0))


def _pose(face: Face, route: np.ndarray, acc: np.ndarray, s: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(punto en la cara, punto en píxeles, hacia dónde va, su costado) a `s` de la ruta."""
    local = _at(route, acc, s)
    here, ahead = face.place(np.vstack([local, _at(route, acc, s + 0.04)]))
    d = ahead - here
    d = d / max(float(np.linalg.norm(d)), 1e-6)
    return local, here, d, np.array([-d[1], d[0]])


def _hidden(local: np.ndarray, far: str | None) -> bool:
    return (far == "right" and local[0] < -0.2) or (far == "left" and local[0] > 0.2)


def _ring(center: np.ndarray, d: np.ndarray, n: np.ndarray, along: float, across: float, points: int = 16) -> np.ndarray:
    t = np.linspace(0, TAU, points)
    return center + np.outer(np.cos(t) * along, d) + np.outer(np.sin(t) * across, n)


def _spider(at: np.ndarray, d: np.ndarray, n: np.ndarray, size: float, step: float, layer, tint, alpha: float, kernels) -> list[np.ndarray]:
    abdomen = _ring(at - d * size * 0.42, d, n, size * 0.42, size * 0.3)
    head = _ring(at + d * size * 0.2, d, n, size * 0.2, size * 0.17, 12)
    fill_polygon(layer, abdomen, tint * 0.5, alpha * 0.55, 1.0, feather=1.0)
    lines = [abdomen, head]
    for side in (-1.0, 1.0):
        for k in range(4):
            angle = np.radians(40.0 + 32.0 * k) + 0.38 * np.sin(step + k * np.pi + (side > 0) * np.pi)
            out = d * np.cos(angle) + n * side * np.sin(angle)
            bend = d * np.cos(angle + 0.7) + n * side * np.sin(angle + 0.7)
            hip = at + d * size * (0.28 - 0.14 * k) + n * side * size * 0.1
            knee = hip + out * size * 0.72
            lines.append(np.stack([hip, knee, knee + bend * size * 0.82]))
    for side in (-1.0, 1.0):  # los ojitos
        eye = at + d * size * 0.32 + n * side * size * 0.07
        splat(layer, float(eye[0]), float(eye[1]), max(size * 0.05, 0.6), np.array([1.0, 0.2, 0.2], np.float32), alpha, kernels)
    return lines


def _roach(at: np.ndarray, d: np.ndarray, n: np.ndarray, size: float, step: float, frame_index: int, layer, tint, alpha: float) -> list[np.ndarray]:
    body = _ring(at, d, n, size * 0.7, size * 0.36, 20)
    fill_polygon(layer, body, tint * 0.45, alpha * 0.5, 1.0, feather=1.0)
    lines = [body, np.stack([at + d * size * 0.3, at - d * size * 0.68])]
    lines.append(at + d * size * 0.3 + np.outer(np.linspace(-1, 1, 9) * size * 0.32, n) - np.outer((np.linspace(-1, 1, 9) ** 2) * size * 0.1, d))
    for side in (-1.0, 1.0):
        for k in range(3):
            angle = np.radians(55.0 + 40.0 * k) + 0.32 * np.sin(step + k * np.pi + (side > 0) * np.pi)
            hip = at + d * size * (0.28 - 0.28 * k) + n * side * size * 0.28
            out = d * np.cos(angle) + n * side * np.sin(angle)
            lines.append(np.stack([hip, hip + out * size * 0.5, hip + out * size * 0.72 - d * size * 0.34]))
        q = np.linspace(0, 1, 8)[:, None]  # las antenas, largas y ondulantes
        wave = np.sin(q * 5.0 + frame_index * 0.4 + side) * size * 0.14 * q
        root = at + d * size * 0.66 + n * side * size * 0.08
        lines.append(root + d * q * size * 1.05 + n * (side * q * size * 0.45 + wave))
    return lines


def _ant(at: np.ndarray, d: np.ndarray, n: np.ndarray, size: float, step: float, layer, tint, alpha: float) -> list[np.ndarray]:
    for offset, along, across in ((-0.5, 0.36, 0.24), (0.0, 0.2, 0.15), (0.42, 0.24, 0.2)):
        fill_polygon(layer, _ring(at + d * size * offset, d, n, size * along, size * across, 10), tint, alpha, 1.3, feather=0.6)
    lines = []
    for side in (-1.0, 1.0):
        for k in range(3):
            angle = np.radians(60.0 + 32.0 * k) + 0.32 * np.sin(step + k * np.pi + (side > 0) * np.pi)
            out = d * np.cos(angle) + n * side * np.sin(angle)
            knee = at + d * size * (0.12 - 0.12 * k) + out * size * 0.3
            lines.append(np.stack([at + d * size * (0.12 - 0.12 * k), knee, knee + (out - d * 0.6) * size * 0.22]))
    return lines


def _centipede(face: Face, route: np.ndarray, acc: np.ndarray, s: float, frame_index: int, layer, tint, alpha: float, far) -> list[np.ndarray]:
    size = face.unit * 0.1
    spine, lines = [], []
    for k in range(CENTIPEDE_SEGMENTS):
        back = s - k * CENTIPEDE_GAP
        if back <= 0.0:
            break
        local, at, d, n = _pose(face, route, acc, back)
        if _hidden(local, far):
            continue
        spine.append(at)
        taper = 1.0 - 0.5 * k / CENTIPEDE_SEGMENTS
        fill_polygon(layer, _ring(at, d, n, size * 0.42, size * 0.42 * taper, 10), tint * 0.6, alpha * 0.6, 1.0, feather=0.8)
        for side in (-1.0, 1.0):  # una ola que corre por las patas
            sweep = 0.55 * np.sin(s * 14.0 - k * 0.8 + (side > 0) * np.pi)
            out = n * side * np.cos(sweep) + d * np.sin(sweep)
            lines.append(np.stack([at + n * side * size * 0.3, at + out * size * 1.05, at + out * size * 1.35 - d * size * 0.35]))
        if k == 0:
            for side in (-1.0, 1.0):
                q = np.linspace(0, 1, 7)[:, None]
                lines.append(at + d * q * size * 2.0 + n * (side * q * size * 0.9 + np.sin(q * 6.0 + frame_index * 0.5) * size * 0.14 * q))
    if len(spine) >= 2:
        lines.append(np.array(spine))
    return lines


def _tinted(curves: list[np.ndarray], tint, fade: float) -> list:
    return [(c, tint * fade) for c in curves]


def face_creature(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    rng = np.random.default_rng(_seed(shape, body, event))
    colors = _palette(runtime, color)
    kernels = runtime.kernels
    far = face.far_side()
    out: list = []
    if shape == "face_ants":
        stops = 2
        route = _route(rng, stops)
        acc = _lengths(route)
        tint = colors[0]
        head = _gait(u, stops) * (acc[-1] + ANTS * ANT_GAP)
        for k in range(ANTS):
            s = head - k * ANT_GAP
            if s <= 0.0 or s >= acc[-1]:
                continue
            local, at, d, n = _pose(face, route, acc, s)
            if not _hidden(local, far):
                fine(_ant(at, d, n, ANT_SIZE * face.unit, s * 22.0, layer, tint, alpha), tint, alpha, layer, width=0.7)
        return out
    count, size, stops, stagger = KINDS[shape]
    for k in range(count):
        route = _route(rng, stops)
        acc = _lengths(route)
        start = k * stagger
        t = (u - start) / max(1.0 - start, 1e-6)
        if t <= 0.0 or t >= 1.0:
            continue
        s = _gait(t, stops) * acc[-1]
        tint = colors[k % len(colors)]
        fade = float(np.clip(min(t, 1.0 - t) / 0.03, 0.0, 1.0))
        if shape == "face_centipede":
            out += _tinted(_centipede(face, route, acc, s, frame_index, layer, tint, alpha * fade, far), tint, fade)
            continue
        local, at, d, n = _pose(face, route, acc, s)
        if _hidden(local, far):
            continue
        px = size * face.unit
        if shape == "face_spiders":
            out += _tinted(_spider(at, d, n, px, s * 16.0, layer, tint, alpha * fade, kernels), tint, fade)
        else:
            out += _tinted(_roach(at, d, n, px, s * 24.0, frame_index, layer, tint, alpha * fade), tint, fade)
    return out
