"""Decoración de temporada (configs/seasons.yaml): dibujos de neón que dan la época al video.

season_fx dibuja las formas de `style.shapes` alrededor de la persona, sin taparla:

- cobweb: telarañas en las esquinas de arriba.
- spider: una araña que baja de su hilo desde arriba y se balancea.
- bats: murciélagos que cruzan aleteando.
- pumpkins: calabazas de cara tallada que flotan a los lados.
- ghosts: fantasmas que suben ondulando.
- skull: calaveras con ojos de flor (Día de Muertos).
- marigolds: flores de cempasúchil que caen girando.
- snow: copos que caen.
- ornaments: esferas navideñas que cuelgan de arriba.
- star: una estrella que corona a la persona.
- hearts: corazones que suben.
- fireworks: fuegos artificiales que estallan arriba.

Todo se escala con el cuadro (no con el cuerpo) y se anima con `runtime.active_frames`.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.raster import splat, stroke_batch
from vfxglow.engine.swoosh import neon_layers

SHAPES = ("cobweb", "spider", "bats", "pumpkins", "ghosts", "skull", "marigolds", "snow", "ornaments", "star", "hearts", "fireworks")
TAU = 2.0 * np.pi


def _circle(center, radius, n=24, a0=0.0, a1=TAU) -> np.ndarray:
    t = np.linspace(a0, a1, n)
    return np.asarray(center) + np.stack([np.cos(t), np.sin(t)], axis=1) * radius


def _cobweb(corner: np.ndarray, size: float, inward: np.ndarray) -> list[np.ndarray]:
    """Telaraña de esquina: radios desde la esquina y arcos que los unen, combados hacia adentro."""
    lines = []
    angles = np.linspace(0, np.pi / 2, 6)
    base = np.arctan2(inward[1], inward[0]) - np.pi / 4
    spokes = [np.array([np.cos(base + a), np.sin(base + a)]) for a in angles]
    for s in spokes:
        lines.append(np.stack([corner, corner + s * size]))
    for ring in (0.3, 0.55, 0.8):
        for a, b in zip(spokes, spokes[1:]):
            p, q = corner + a * size * ring, corner + b * size * ring
            sag = corner + (a + b) / 2 * size * ring * 0.86
            t = np.linspace(0, 1, 8)[:, None]
            lines.append((1 - t) ** 2 * p + 2 * (1 - t) * t * sag + t**2 * q)
    return lines


def _spider(anchor: np.ndarray, size: float, frame: int) -> list[np.ndarray]:
    drop = (0.5 + 0.5 * np.sin(frame * 0.05)) * size * 6
    swing = np.sin(frame * 0.09) * size * 0.6
    body = anchor + np.array([swing, drop])
    lines = [np.stack([anchor, body]), _circle(body, size * 0.35), _circle(body + [0, size * 0.55], size * 0.25)]
    for side in (-1, 1):
        for k in range(4):
            a = np.radians(-40 + 25 * k)
            knee = body + np.array([side * np.cos(a), np.sin(a)]) * size * 0.8
            foot = knee + np.array([side * size * 0.35, size * 0.45])
            lines.append(np.stack([body, knee, foot]))
    return lines


def _bat(center: np.ndarray, size: float, flap: float) -> list[np.ndarray]:
    lift = size * 0.35 * flap
    wing = lambda s: np.array([center, center + [s * size * 0.45, -lift - size * 0.15], center + [s * size * 0.75, -lift], center + [s * size, -lift + size * 0.1], center + [s * size * 0.7, size * 0.1], center + [s * size * 0.45, size * 0.05], center + [s * size * 0.25, size * 0.15], center])
    head = _circle(center, size * 0.12, 10)
    ears = np.array([center + [-size * 0.1, -size * 0.08], center + [-size * 0.07, -size * 0.22], center + [0, -size * 0.1], center + [size * 0.07, -size * 0.22], center + [size * 0.1, -size * 0.08]])
    return [wing(-1), wing(1), head, ears]


def _pumpkin(center: np.ndarray, size: float) -> list[np.ndarray]:
    lines = []
    for dx, rx in ((0.0, 0.42), (-0.28, 0.32), (0.28, 0.32)):
        t = np.linspace(0, TAU, 28)
        lines.append(center + np.stack([dx * size + np.cos(t) * rx * size, np.sin(t) * 0.4 * size], axis=1))
    lines.append(np.array([center + [0, -0.38 * size], center + [0.05 * size, -0.55 * size], center + [0.12 * size, -0.58 * size]]))
    for side in (-1, 1):
        lines.append(np.array([center + [side * 0.22 * size, -0.05 * size], center + [side * 0.12 * size, -0.12 * size], center + [side * 0.08 * size, 0.0], center + [side * 0.22 * size, -0.05 * size]]))
    xs = np.linspace(-0.25, 0.25, 7)
    lines.append(np.array([center + [x * size, (0.15 if k % 2 else 0.22) * size] for k, x in enumerate(xs)]))
    return lines


def _ghost(center: np.ndarray, size: float, wave: float) -> list[np.ndarray]:
    t = np.linspace(np.pi, TAU, 14)
    top = center + np.stack([np.cos(t) * size * 0.35, np.sin(t) * size * 0.4], axis=1)
    hem = np.array([center + [x * size + np.sin(wave + x * 9) * size * 0.04, size * (0.45 + (0.06 if k % 2 else 0.0))] for k, x in enumerate(np.linspace(0.35, -0.35, 7))])
    body = np.vstack([top, center + [size * 0.35, size * 0.45], hem, center + [-size * 0.35, 0.0]])
    eyes = [_circle(center + [s * 0.12 * size, -0.05 * size], size * 0.05, 8) for s in (-1, 1)]
    return [body, *eyes, _circle(center + [0, 0.12 * size], size * 0.06, 10)]


def _skull(center: np.ndarray, size: float) -> list[np.ndarray]:
    cranium = _circle(center, size * 0.42, 30, np.radians(-200), np.radians(20))
    jaw = np.array([cranium[-1], center + [0.25 * size, 0.42 * size], center + [-0.25 * size, 0.42 * size], cranium[0]])
    lines = [cranium, jaw]
    for s in (-1, 1):  # ojos de flor
        eye = center + [s * 0.17 * size, 0.0]
        lines.append(_circle(eye, size * 0.11, 14))
        for k in range(5):
            a = k * TAU / 5
            lines.append(_circle(eye + np.array([np.cos(a), np.sin(a)]) * size * 0.1, size * 0.05, 8))
    lines.append(np.array([center + [-0.04 * size, 0.18 * size], center + [0, 0.12 * size], center + [0.04 * size, 0.18 * size]]))
    for x in np.linspace(-0.18, 0.18, 5):
        lines.append(np.array([center + [x * size, 0.3 * size], center + [x * size, 0.4 * size]]))
    return lines


def _flower(center: np.ndarray, size: float, spin: float) -> list[np.ndarray]:
    lines = [_circle(center, size * 0.15, 10)]
    for k in range(8):
        a = spin + k * TAU / 8
        tip = center + np.array([np.cos(a), np.sin(a)]) * size * 0.5
        side = np.array([-np.sin(a), np.cos(a)]) * size * 0.12
        mid = center + np.array([np.cos(a), np.sin(a)]) * size * 0.28
        lines.append(np.array([center, mid + side, tip, mid - side, center]))
    return lines


def _flake(center: np.ndarray, size: float, spin: float) -> list[np.ndarray]:
    lines = []
    for k in range(3):
        a = spin + k * np.pi / 3
        d = np.array([np.cos(a), np.sin(a)]) * size
        lines.append(np.stack([center - d, center + d]))
        for s in (-1, 1):
            p = center + s * d * 0.6
            n = np.array([-d[1], d[0]]) * 0.25
            lines.append(np.array([p + n - s * d * 0.15, p, p - n - s * d * 0.15]))
    return lines


def _star(center: np.ndarray, size: float) -> np.ndarray:
    a = -np.pi / 2 + np.arange(11) * np.pi / 5
    r = np.where(np.arange(11) % 2 == 0, size, size * 0.42)
    return center + np.stack([np.cos(a) * r, np.sin(a) * r], axis=1)


def _heart(center: np.ndarray, size: float) -> np.ndarray:
    t = np.linspace(0, TAU, 40)
    return center + np.stack([16 * np.sin(t) ** 3, -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))], axis=1) / 17 * size


def draw_season(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    style = runtime.effect.style
    if envelope <= 0:
        return
    width = layer.shape[1]
    unit = min(width, height) * 1.35
    frame = runtime.active_frames
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:season".encode()) & 0xFFFFFFFF)
    colors = [np.asarray(c, dtype=np.float32) for c in style.colors] or [np.ones(3, np.float32)]
    line = max(1.5, style.thickness * unit * 0.05)
    # La persona: no se dibuja encima de su centro.
    body_x = float(np.mean([p[0] for name, p in points.items() if name.endswith(("shoulder", "hip"))] or [width / 2]))
    head = points.get("nose")
    strokes: list = []

    def add(curves, color, alpha=1.0, w=line):
        for curve in curves if isinstance(curves, list) else [curves]:
            strokes.extend(neon_layers(curve, color, w, envelope * alpha))

    shapes = [s for s in style.shapes if s in SHAPES]
    for shape in shapes:
        color = colors[SHAPES.index(shape) % len(colors)]
        if shape == "cobweb":
            for corner, inward in ((np.array([0.0, 0.0]), np.array([1.0, 1.0])), (np.array([float(width), 0.0]), np.array([-1.0, 1.0]))):
                add(_cobweb(corner, unit * 0.32, inward / np.linalg.norm(inward)), np.ones(3, np.float32) * 0.9, 0.7, line * 0.6)
        elif shape == "spider":
            side = width * (0.18 if body_x > width / 2 else 0.82)
            add(_spider(np.array([side, 0.0]), unit * 0.035, frame), colors[0])
        elif shape == "bats":
            for k in range(4):
                speed = rng.uniform(0.004, 0.008)
                x = ((frame * speed + k / 4) % 1.2 - 0.1) * width
                y = height * (0.08 + 0.18 * rng.uniform()) + np.sin(frame * 0.1 + k) * unit * 0.02
                add(_bat(np.array([x, y]), unit * rng.uniform(0.04, 0.06), np.sin(frame * 0.6 + k * 1.3)), color)
        elif shape == "pumpkins":
            for k, side in enumerate((0.13, 0.87)):
                y = height * (0.72 + 0.03 * np.sin(frame * 0.07 + k * 2))
                center = np.array([side * width, y])
                add(_pumpkin(center, unit * 0.12), color)
                flicker = 0.7 + 0.3 * np.sin(frame * 1.3 + k)
                splat(layer, float(center[0]), float(center[1]), unit * 0.04, color * 1.5, envelope * 0.5 * flicker, runtime.kernels)
        elif shape == "ghosts":
            for k in range(3):
                life = ((frame * 0.006 + k / 3) % 1.0)
                x = width * (0.12 if k % 2 == 0 else 0.88) + np.sin(frame * 0.05 + k) * unit * 0.04
                y = height * (0.9 - 0.8 * life)
                add(_ghost(np.array([x, y]), unit * 0.09, frame * 0.2 + k), np.array([0.85, 0.95, 1.0], np.float32), 1.0 - life)
        elif shape == "skull":
            for k, side in enumerate((0.14, 0.86)):
                center = np.array([side * width, height * (0.25 + 0.02 * np.sin(frame * 0.06 + k))])
                add(_skull(center, unit * 0.1), color)
        elif shape in ("marigolds", "snow", "hearts"):
            count = {"marigolds": 10, "snow": 26, "hearts": 9}[shape]
            for k in range(count):
                x0 = rng.uniform(0, 1)
                speed = rng.uniform(0.003, 0.007)
                t = (frame * speed + rng.uniform(0, 1)) % 1.0
                if shape == "hearts":
                    pos = np.array([x0 * width + np.sin(t * 8 + k) * unit * 0.02, height * (1.05 - 1.1 * t)])
                else:
                    pos = np.array([x0 * width + np.sin(t * 6 + k) * unit * 0.03, height * (-0.05 + 1.1 * t)])
                if abs(pos[0] - body_x) < width * 0.18:
                    continue  # no encima de la persona
                size = unit * rng.uniform(0.015, 0.03)
                if shape == "snow":
                    add(_flake(pos, size, t * 6), np.array([0.85, 0.95, 1.0], np.float32), 0.8, line * 0.6)
                elif shape == "marigolds":
                    add(_flower(pos, size * 1.6, t * 4), color, 0.9, line * 0.7)
                else:
                    add(_heart(pos, size * 1.3), color, 1.0 - t * 0.5, line * 0.8)
        elif shape == "ornaments":
            for k, x in enumerate((0.1, 0.24, 0.76, 0.9)):
                drop = height * (0.12 + 0.06 * (k % 2))
                swing = np.sin(frame * 0.05 + k) * unit * 0.01
                ball = np.array([x * width + swing, drop])
                add([np.stack([np.array([x * width, 0.0]), ball - [0, unit * 0.03]]), _circle(ball, unit * 0.03)], colors[k % len(colors)])
                splat(layer, float(ball[0] - unit * 0.01), float(ball[1] - unit * 0.01), unit * 0.008, np.ones(3, np.float32) * 1.5, envelope, runtime.kernels)
        elif shape == "star" and head is not None:
            center = head - np.array([0.0, unit * 0.22])
            pulse = 1.0 + 0.1 * np.sin(frame * 0.3)
            add(_star(center, unit * 0.05 * pulse), np.array([1.0, 0.85, 0.3], np.float32))
        elif shape == "fireworks":
            for k in range(3):
                period = 50 + 13 * k
                t = ((frame + k * 17) % period) / period
                center = np.array([width * (0.2 + 0.3 * k), height * (0.12 + 0.05 * k)])
                fw = colors[k % len(colors)]
                for a in np.linspace(0, TAU, 12, endpoint=False):
                    d = np.array([np.cos(a), np.sin(a)])
                    head_pt = center + d * unit * 0.12 * t**0.6 + np.array([0, unit * 0.04 * t**2])
                    tail = head_pt - d * unit * 0.03 * (1 - t)
                    strokes.extend(neon_layers(np.stack([tail, head_pt]), fw, line * 0.7, envelope * (1 - t)))
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)
