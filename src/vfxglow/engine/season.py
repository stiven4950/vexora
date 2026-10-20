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
- bat_release: la mano del gesto suelta murciélagos que salen en la dirección del movimiento y se
  alejan aleteando (soltar algo: un golpe, abrir los brazos, lanzar).
- pumpkin_head: la cabeza se vuelve una calabaza tallada, encendida por dentro, que sigue la
  inclinación de la cabeza (solo de frente, en una pausa).
- ghost_rise: un fantasma sale del piso donde pisó el pie y sube meciéndose.
- claw_slash: arañazos que se abren a lo largo del tajo de la mano.

Los dibujos de Halloween siguen las figuras de glowing_assets (calabaza, murciélago, fantasma,
araña, arañazos), redibujadas con líneas de neón.
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
MOMENTS = ("spider_drop", "web_corner", "bat_swarm", "bat_release", "pumpkin_head", "ghost_rise", "claw_slash", "snow_burst", "hearts_rise", "marigold_rain", "fireworks", "star_crown")
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


def _spider_at(body: np.ndarray, size: float, step: float = 0.0) -> list[np.ndarray]:
    """Araña con el cuerpo en `body`: abdomen ovalado con una marca, cabeza y cuatro patas por lado
    con la rodilla alta (como la de glowing_assets); `step` las mueve un poco."""
    t = np.linspace(0, TAU, 24)
    abdomen = body + np.stack([np.cos(t) * size * 0.32, np.sin(t) * size * 0.42], axis=1)
    head = _circle(body + [0, -size * 0.55], size * 0.2, 14)
    mark = np.array([body + [0, -size * 0.18], body + [size * 0.1, 0], body + [0, size * 0.18], body + [-size * 0.1, 0], body + [0, -size * 0.18]])
    lines = [abdomen, head, mark]
    for side in (-1, 1):
        for k in range(4):  # de adelante hacia atrás, salen de los costados del cuerpo
            a = np.radians(-55 + 35 * k) + 0.08 * np.sin(step + k * 1.7)
            hip = body + np.array([side * size * 0.15, -size * (0.55 - 0.15 * k)])
            out = np.array([side * np.cos(a), np.sin(a)])
            knee = hip + out * size * 0.6 + np.array([0.0, -size * 0.28])
            foot = knee + out * size * 0.55 + np.array([0.0, size * 0.35])
            lines.append(np.stack([hip, knee, foot]))
    return lines


def _scallop(a: np.ndarray, b: np.ndarray, toward: np.ndarray, depth: float = 0.35, n: int = 8) -> np.ndarray:
    """Arco cóncavo de `a` a `b` que se mete hacia `toward` (el borde festoneado del ala)."""
    control = (a + b) / 2 + (toward - (a + b) / 2) * depth
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * a + 2 * (1 - t) * t * control + t ** 2 * b


def _bat(center: np.ndarray, size: float, flap: float) -> list[np.ndarray]:
    """Murciélago de frente con las alas abiertas (`size` = media envergadura), como el de
    glowing_assets: borde de ataque hasta la muñeca y la punta, borde de fuga festoneado entre los
    dedos, varillas de los dedos, cuerpo, cabeza y orejas en punta. `flap` (-1 a 1) sube o baja
    las alas."""
    c = np.asarray(center, dtype=np.float64)
    lines = []
    for s in (-1.0, 1.0):
        p = lambda x, y: c + np.array([s * x, y]) * size  # noqa: E731
        shoulder, wrist, tip = p(0.12, -0.12), p(0.45, -0.38 - 0.28 * flap), p(1.0, -0.2 - 0.4 * flap)
        f1, f2, f3, hip = p(0.78, 0.12 - 0.22 * flap), p(0.52, 0.2 - 0.1 * flap), p(0.3, 0.18), p(0.1, 0.16)
        edge = np.vstack([np.stack([shoulder, wrist, tip]), _scallop(tip, f1, wrist)[1:], _scallop(f1, f2, wrist)[1:], _scallop(f2, f3, wrist)[1:], _scallop(f3, hip, wrist, 0.25)[1:]])
        lines.append(edge)
        lines += [np.stack([wrist, f1]), np.stack([wrist, f2])]  # varillas de los dedos
    t = np.linspace(0, TAU, 18)
    lines.append(c + np.stack([np.cos(t) * size * 0.11, np.sin(t) * size * 0.2 + size * 0.02], axis=1))  # cuerpo
    lines.append(np.array([c + np.array([-0.09, -0.16]) * size, c + np.array([-0.07, -0.32]) * size, c + np.array([-0.02, -0.2]) * size, c + np.array([0.02, -0.2]) * size, c + np.array([0.07, -0.32]) * size, c + np.array([0.09, -0.16]) * size]))  # orejas
    return lines


def _jack(size: float, tilt: float, center: np.ndarray, flicker: float = 0.0) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Calabaza tallada como la de glowing_assets: gajos, tallo con zarcillo, ojos en triángulo
    enojados, nariz y una sonrisa de dientes. Devuelve (contornos, huecos tallados), en el plano
    de la cara: `size` = medio ancho, `tilt` = inclinación de la cabeza (rad)."""
    rot = np.array([[np.cos(tilt), -np.sin(tilt)], [np.sin(tilt), np.cos(tilt)]])
    place = lambda pts: np.asarray(center) + (np.asarray(pts, dtype=np.float64) * size) @ rot.T  # noqa: E731
    t = np.linspace(0, TAU, 36)
    lines = [place(np.stack([np.cos(t), np.sin(t) * 0.82], axis=1))]  # contorno
    for x in (-0.55, -0.2, 0.2, 0.55):  # gajos: arcos de arriba abajo, curvados hacia afuera
        y = np.linspace(-0.78, 0.78, 14)
        lines.append(place(np.stack([x + np.sign(x) * 0.18 * np.cos(y / 0.78 * np.pi / 2), y * (1 - 0.15 * abs(x))], axis=1)))
    lines.append(place([[-0.06, -0.8], [-0.04, -1.0], [0.08, -1.12], [0.14, -1.08]]))  # tallo
    v = np.linspace(0, 1.6 * np.pi, 14)
    lines.append(place(np.stack([0.14 + 0.12 * np.cos(v) * (1 - v / 6), -1.05 + 0.12 * np.sin(v) * (1 - v / 6)], axis=1)))  # zarcillo
    holes = [place([[-0.58, -0.28], [-0.18, -0.12], [-0.42, 0.06], [-0.58, -0.28]]),  # ojos enojados
             place([[0.58, -0.28], [0.18, -0.12], [0.42, 0.06], [0.58, -0.28]]),
             place([[0.0, 0.0], [0.08, 0.16], [-0.08, 0.16], [0.0, 0.0]])]  # nariz
    xs = np.linspace(-0.6, 0.6, 9)
    top = [[x, 0.3 + 0.12 * x * x + (0.1 if k % 2 else 0.0)] for k, x in enumerate(xs)]  # dientes de arriba
    bottom = [[x, 0.42 + 0.22 * (1 - x * x) - (0.1 if k % 2 == 0 and 0 < k < 8 else 0.0)] for k, x in enumerate(xs[::-1])]
    holes.append(place(top + bottom + [top[0]]))  # sonrisa
    return lines, holes


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
    """Fantasma (como el de glowing_assets): cabeza redonda, cuerpo que se ensancha en una cola
    ondulada que se mece, brazos que flotan, ojos huecos y la boca abierta. `wave` lo anima."""
    c = np.asarray(center, dtype=np.float64)
    t = np.linspace(np.pi, TAU, 18)
    head = c + np.stack([np.cos(t) * size * 0.32, np.sin(t) * size * 0.36 - size * 0.05], axis=1)
    sway = lambda y: np.sin(wave + y * 4.0) * size * 0.08 * max(y, 0.0)  # noqa: E731  la cola se mece más abajo
    right = np.array([c + [size * (0.32 + 0.12 * y) + sway(y), size * y] for y in np.linspace(-0.05, 0.75, 9)])
    tails = []
    for k, x in enumerate(np.linspace(0.44, -0.44, 25)):  # el borde de la cola: una onda suave
        y = 0.8 + 0.1 * np.sin(x * 14.0 + wave * 1.3) + 0.06 * (1 - abs(x) / 0.44)
        tails.append(c + [x * size + sway(y), y * size])
    left = np.array([c + [-size * (0.32 + 0.12 * y) + sway(y), size * y] for y in np.linspace(0.75, -0.05, 9)])
    body = np.vstack([head, right, np.array(tails), left, head[:1]])
    arms = [np.array([c + [s * 0.3 * size, 0.15 * size], c + [s * 0.55 * size, (0.0 + 0.06 * np.sin(wave + s)) * size], c + [s * 0.66 * size, (-0.1 + 0.08 * np.sin(wave * 1.2 + s)) * size]]) for s in (-1, 1)]
    eyes = []
    for s in (-1, 1):
        e = np.linspace(0, TAU, 14)
        eyes.append(c + np.stack([s * 0.12 * size + np.cos(e) * size * 0.06, -0.1 * size + np.sin(e) * size * 0.09], axis=1))
    m = np.linspace(0, TAU, 16)
    mouth = c + np.stack([np.cos(m) * size * 0.07, 0.12 * size + np.sin(m) * size * 0.1], axis=1)
    return [body, *arms, *eyes, mouth]


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


def _gesture_joint(points, event) -> tuple[np.ndarray | None, np.ndarray | None]:
    """La articulación del gesto (la mano del golpe, el pie que pisó) y su velocidad en píxeles."""
    if event is None:
        return None, None
    name = event.target.split(":")[-1]
    for key in (event.target, name):
        if key in points:
            return points[key], points.get(f"vel:{key}")
    return None, None


def _front_face(points) -> tuple[np.ndarray, float, float] | None:
    """(centro de la cara, medio ancho de la cabeza, inclinación) si la persona mira de frente."""
    eyes = [points.get("left_eye"), points.get("right_eye")]
    ears = [points.get("left_ear"), points.get("right_ear")]
    nose = points.get("nose")
    if nose is None or any(e is None for e in eyes + ears):
        return None
    left, right = (eyes[0], eyes[1]) if eyes[0][0] > eyes[1][0] else (eyes[1], eyes[0])
    # De frente la nariz cae entre los ojos (de perfil, por fuera) y las orejas a los lados.
    if not (min(eyes[0][0], eyes[1][0]) < nose[0] < max(eyes[0][0], eyes[1][0])):
        return None
    half = float(np.linalg.norm(ears[0] - ears[1])) * 0.62
    tilt = float(np.arctan2(left[1] - right[1], left[0] - right[0]))
    center = (eyes[0] + eyes[1]) / 2 * 0.6 + nose * 0.4 - np.array([0.0, half * 0.1])
    return center, half, tilt


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
    elif moment == "bat_release":
        # La mano suelta murciélagos: salen de ella en la dirección del movimiento, uno tras otro,
        # se abren en abanico, suben y se alejan (se achican) aleteando.
        hand, vel = _gesture_joint(points, event)
        st = runtime.swoosh.setdefault("_bats", {})
        if st.get("key") != key:
            origin = np.asarray(hand if hand is not None else center, dtype=np.float64)
            # Escapan: la dirección de la mano, pero alejándose del cuerpo y hacia arriba (si la
            # mano iba hacia el cuerpo o hacia el piso, se amontonaban sobre la persona).
            d = vel / float(np.linalg.norm(vel)) if vel is not None and float(np.linalg.norm(vel)) > 1e-3 else np.zeros(2)
            away = origin - (np.mean(hips, axis=0) if hips else center)
            away = away / max(float(np.linalg.norm(away)), 1e-6)
            d = 0.6 * d + away + np.array([0.0, -1.2])
            st.update(key=key, origin=origin, dir=d / float(np.linalg.norm(d)))
        origin, d = st["origin"], st["dir"]
        side = np.array([-d[1], d[0]])
        for k in range(8):
            t = np.clip((u - k * 0.05) / 0.8, 0.0, 1.0)  # salen de a uno
            if t <= 0:
                continue
            spread = rng.uniform(-0.7, 0.7)
            pos = origin + d * unit * 0.9 * t + side * unit * 0.45 * spread * t - np.array([0.0, unit * 0.45 * t * t])
            size = unit * 0.075 * min(t * 6.0, 1.0) * (1.0 - 0.45 * t)  # nace chico en la mano y se aleja
            flap = np.sin(frame_index * 0.9 + k * 1.3)
            fade = 1.0 - max(t - 0.75, 0.0) / 0.25
            purple = np.array([0.6, 0.2, 1.0], np.float32) if k % 3 else np.array([1.0, 0.45, 0.05], np.float32)  # morados, alguno naranja
            add(_bat(pos, size, flap), purple, fade, line * 0.8)
    elif moment == "pumpkin_head":
        # En una pausa de frente, la cabeza se vuelve una calabaza tallada encendida por dentro.
        face = _front_face(points)
        if face is not None:
            mid, half, tilt = face
            grow = min(u / 0.15, 1.0)
            grow = grow * (1.0 + 0.2 * np.sin(np.pi * grow))  # aparece con un rebote
            shrink = 1.0 - max(u - 0.85, 0.0) / 0.15
            size = half * 1.15 * grow * shrink
            if size > 1:
                outline, carved = _jack(size, tilt, mid)
                orange = np.array([1.0, 0.45, 0.05], np.float32)
                splat(layer, float(mid[0]), float(mid[1]), size * 1.1, orange * 0.6, envelope * 0.35, runtime.kernels)  # la piel
                flicker = 0.75 + 0.25 * np.sin(frame_index * 0.7) * np.sin(frame_index * 0.23 + 1.0)  # la vela adentro
                for hole in carved:
                    c = hole.mean(axis=0)
                    splat(layer, float(c[0]), float(c[1]), size * 0.22, np.array([1.0, 0.75, 0.2], np.float32), envelope * flicker, runtime.kernels)
                add(outline, orange, 1.0, line)
                add(carved, np.array([1.0, 0.85, 0.3], np.float32), flicker, line)
    elif moment == "claw_slash":
        # Un tajo con la mano deja arañazos: cuatro marcas en la dirección del golpe que se abren
        # de un extremo al otro (como un zarpazo) y se apagan.
        hand, vel = _gesture_joint(points, event)
        st = runtime.swoosh.setdefault("_claws", {})
        if st.get("key") != key and hand is not None:
            d = vel if vel is not None and float(np.linalg.norm(vel)) > 1e-3 else np.array([1.0, 0.4])
            st.update(key=key, at=np.asarray(hand, dtype=np.float64), dir=d / float(np.linalg.norm(d)))
        if st.get("key") == key:
            at, d = st["at"], st["dir"]
            side = np.array([-d[1], d[0]])
            length = unit * 0.32
            draw = min(u / 0.2, 1.0)  # el zarpazo se abre rápido
            fade = 1.0 - max(u - 0.5, 0.0) / 0.5
            for k in range(4):
                off = (k - 1.5) * unit * 0.045
                q = np.linspace(0, draw, 16)
                bow = np.sin(np.pi * q) * unit * 0.025
                spine = at - d * length * 0.5 + np.outer(q * length, d) + np.outer(off + bow, side)
                w = np.sin(np.pi * np.clip(q / max(draw, 1e-3), 0, 1)) * unit * 0.008 + 0.5  # afilado en las puntas
                sliver = np.vstack([spine + np.outer(w, side), (spine - np.outer(w, side))[::-1]])
                claw = np.array([1.0, 0.45, 0.05], np.float32) if k % 2 == 0 else np.array([0.6, 0.2, 1.0], np.float32)  # naranja y morado
                add([sliver], claw, fade, line * 0.8)
    elif moment == "ghost_rise":
        # Al pisar fuerte sale un fantasma del piso, donde pisó el pie, y sube meciéndose.
        foot, _vel = _gesture_joint(points, event)
        base = foot if foot is not None else (np.mean(feet, axis=0) if feet else center + [0, unit * 0.3])
        rise = unit * 0.5 * (1 - (1 - u) ** 2)
        pos = np.asarray(base, dtype=np.float64) + np.array([np.sin(u * 7.0) * unit * 0.03, -unit * 0.08 - rise])
        size = unit * 0.15 * min(u / 0.2, 1.0)
        add(_ghost(pos, size, frame_index * 0.25), np.array([0.75, 0.6, 1.0], np.float32), np.sin(np.pi * min(u * 1.2, 1.0)) ** 0.5)
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
