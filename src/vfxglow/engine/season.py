"""Objetos y momentos de temporada (configs/seasons.yaml).

No es un marco fijo: los objetos de la época salen DENTRO de los efectos que ya se disparan (las
partículas de un golpe son murciélagos, el sombrero de una pausa es de bruja) y los momentos de
temporada (season_fx) son efectos disparados por una acción, que empiezan y terminan.

Objetos (object_outline, también como formas de partícula de droplets):

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

Momentos (season_fx, `style.shapes`, uno por activación; anclados a la persona del evento):
- spider_drop: una araña baja de su hilo hasta la cabeza, se balancea y vuelve a subir.
- web_corner: una telaraña se teje en la esquina de arriba más cercana y se desvanece.
- bat_swarm: un enjambre de murciélagos sale del cuerpo y se va volando.
- ghost_rise: fantasmas que salen del piso junto a los pies y suben.
- snow_burst / hearts_rise / marigold_rain: copos, corazones o pétalos alrededor de la persona.
- fireworks: fuegos artificiales sobre la cabeza.
- star_crown: una estrella que aparece sobre la cabeza.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.raster import splat, stroke_batch
from vfxglow.engine.swoosh import neon_layers

OBJECTS = ("bat", "pumpkin", "ghost", "skull", "marigold", "flake", "ornament", "star", "heart", "spider")
MOMENTS = ("spider_drop", "web_corner", "bat_swarm", "ghost_rise", "snow_burst", "hearts_rise", "marigold_rain", "fireworks", "star_crown")
SHAPES = MOMENTS
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


def _spider_at(body: np.ndarray, size: float) -> list[np.ndarray]:
    """Araña con el cuerpo en `body`: abdomen, cabeza y cuatro patas por lado."""
    lines = [_circle(body, size * 0.35), _circle(body + [0, size * 0.55], size * 0.25)]
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




def object_outline(name: str, center: np.ndarray, size: float, age: float = 0.0, spin: float = 0.0) -> list[np.ndarray]:
    """Curvas de un objeto de temporada de tamaño `size` (radio aproximado)."""
    center = np.asarray(center, dtype=np.float64)
    if name == "bat":
        return _bat(center, size * 1.2, np.sin(age * 25 + spin * 3))
    if name == "pumpkin":
        return _pumpkin(center, size * 1.8)
    if name == "ghost":
        return _ghost(center, size * 2.0, age * 8 + spin)
    if name == "skull":
        return _skull(center, size * 1.8)
    if name == "marigold":
        return _flower(center, size * 1.3, spin + age * 4)
    if name == "flake":
        return _flake(center, size, spin + age * 3)
    if name == "ornament":
        return [_circle(center, size * 0.8), np.stack([center - [0, size * 0.8], center - [0, size * 1.2]])]
    if name == "star":
        return [_star(center, size)]
    if name == "heart":
        return [_heart(center, size)]
    if name == "spider":
        return _spider_at(center, size * 0.8)
    return [_circle(center, size)]


def _nearest_corner(point: np.ndarray, width: int) -> tuple[np.ndarray, np.ndarray]:
    if point[0] < width / 2:
        return np.array([0.0, 0.0]), np.array([1.0, 1.0]) / np.sqrt(2)
    return np.array([float(width), 0.0]), np.array([-1.0, 1.0]) / np.sqrt(2)


def draw_season(runtime, track, points, frame_index: int, height: int, envelope: float, layer: np.ndarray, event=None) -> None:
    """Un momento de temporada: dura lo que su activación y se anima con su avance (0-1)."""
    style = runtime.effect.style
    if envelope <= 0:
        return
    width = layer.shape[1]
    unit = min(width, height)
    names = [s for s in style.shapes if s in MOMENTS] or ["bat_swarm"]
    key = event.start_frame if event is not None else frame_index // 90
    rng = np.random.default_rng(zlib.crc32(f"{style.seed_offset}:moment:{key}".encode()) & 0xFFFFFFFF)
    moment = names[int(rng.integers(len(names)))]
    span = max(runtime.fps * max(style.size, 0.5), 1.0)  # duración del momento (s)
    u = min(runtime.active_frames / span, 1.0)
    colors = [np.asarray(c, dtype=np.float32) for c in style.colors] or [np.ones(3, np.float32)]
    color = colors[0]
    line = max(1.5, style.thickness * unit * 0.05)
    head = points.get("nose")
    feet = [p for n, p in points.items() if n.endswith(("ankle", "heel"))]
    hips = [p for n, p in points.items() if n.endswith("hip")]
    center = np.mean(hips, axis=0) if hips else (head if head is not None else np.array([width / 2, height / 2]))
    if event is not None and event.position is not None:
        center = np.array(event.position) * [width, height]
    strokes: list = []

    def add(curves, tint=color, alpha=1.0, w=line):
        for curve in curves:
            strokes.extend(neon_layers(curve, tint, w, envelope * alpha))

    if moment == "spider_drop" and head is not None:
        anchor = np.array([head[0] + unit * 0.08, 0.0])
        down = np.sin(np.pi * u)  # baja y vuelve a subir
        target = head[1] - unit * 0.1
        body_y = target * down
        swing = np.sin(frame_index * 0.12) * unit * 0.015 * down
        size = unit * 0.05
        body = np.array([anchor[0] + swing, body_y])
        add([np.stack([anchor, body])], np.ones(3, np.float32) * 0.8, 0.7, line * 0.5)
        add(_spider_at(body, size))
    elif moment == "web_corner":
        corner, inward = _nearest_corner(head if head is not None else center, width)
        grow = min(u / 0.4, 1.0)
        fade = 1.0 - max(u - 0.75, 0.0) / 0.25
        web = _cobweb(corner, unit * 0.32 * grow, inward)
        add(web[: max(2, int(len(web) * grow))], np.ones(3, np.float32) * 0.9, 0.8 * fade, line * 0.6)
    elif moment == "bat_swarm":
        for k in range(9):
            angle = rng.uniform(-np.pi * 0.95, -np.pi * 0.05)
            speed = rng.uniform(0.5, 1.0)
            pos = center + np.array([np.cos(angle), np.sin(angle)]) * unit * 0.7 * speed * u + [np.sin(u * 20 + k) * unit * 0.01, 0]
            add(object_outline("bat", pos, unit * rng.uniform(0.025, 0.04), u * 2 + k, k), colors[k % len(colors)], 1.0 - u * 0.6)
    elif moment == "ghost_rise":
        base = np.mean(feet, axis=0) if feet else center + [0, unit * 0.3]
        for k, side in enumerate((-1, 1)):
            pos = base + np.array([side * unit * 0.18, -unit * 0.55 * u]) + [np.sin(u * 8 + k) * unit * 0.02, 0]
            add(object_outline("ghost", pos, unit * 0.04, u * 3, k), np.array([0.85, 0.95, 1.0], np.float32), np.sin(np.pi * u))
    elif moment in ("snow_burst", "hearts_rise", "marigold_rain"):
        obj = {"snow_burst": "flake", "hearts_rise": "heart", "marigold_rain": "marigold"}[moment]
        rising = moment == "hearts_rise"
        for k in range(12):
            x = center[0] + rng.uniform(-0.45, 0.45) * unit
            y0 = center[1] + rng.uniform(-0.5, 0.2) * unit
            pos = np.array([x + np.sin(u * 6 + k) * unit * 0.02, y0 + (-1 if rising else 1) * unit * 0.4 * u])
            add(object_outline(obj, pos, unit * rng.uniform(0.012, 0.022), u, k), colors[k % len(colors)], np.sin(np.pi * u), line * 0.7)
    elif moment == "fireworks" and head is not None:
        for k in range(3):
            t = min(max(u * 1.5 - k * 0.25, 0.0), 1.0)
            if t <= 0:
                continue
            burst = head + np.array([(k - 1) * unit * 0.25, -unit * (0.3 + 0.08 * k)])
            for a in np.linspace(0, TAU, 12, endpoint=False):
                d = np.array([np.cos(a), np.sin(a)])
                tip = burst + d * unit * 0.12 * t**0.6 + [0, unit * 0.04 * t**2]
                add([np.stack([tip - d * unit * 0.03 * (1 - t), tip])], colors[k % len(colors)], 1.0 - t, line * 0.7)
    elif moment == "star_crown" and head is not None:
        pulse = 1.0 + 0.1 * np.sin(frame_index * 0.3)
        add([_star(head - [0, unit * 0.2], unit * 0.045 * pulse * min(u / 0.2, 1.0))], np.array([1.0, 0.85, 0.3], np.float32))
    if strokes:
        stroke_batch(layer, strokes, style.hdr_gain)
