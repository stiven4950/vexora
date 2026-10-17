"""Criaturas y momentos del maestro fuego (glowing/video_18.mp4, lectura del usuario).

- `fire_skull`: calavera de frente dibujada en línea blanca (cráneo, sienes, cuencas, cavidad
  nasal, pómulos, dientes y mandíbula) con una melena de fuego alta y ondulada; al final el fuego
  deja la cabeza y viaja en un trazo hasta la mano que toma el protagonismo (seg. 3,1-3,6).
- `fire_bird` / `fire_serpent`: de la mano levantada sale un ave de fuego (o un dragón serpiente)
  unida a la mano por una corriente en S; vuela, vuelve y se ondula siguiendo la mano (seg. 4,2-4,8).
- `fire_splash`: el fuego que choca contra el piso se expande en olas con crestas enroscadas que
  tiemblan como gelatina y se aplanan en una línea con escamas (seg. 5,0-5,2).
- `fire_breath`: el fuego sube por el costado hasta la cabeza, la envuelve, estalla una bola de
  fuego desde la boca y queda una cara de demonio (ojos y colmillos); luego el fuego rodea el
  cuerpo hasta la mano que toma el protagonismo (seg. 7,8-8,6).
- `fire_dragon`: las llamas suben por los brazos desde el piso, se cruzan en X arriba de la
  espalda y forman un dragón con cabeza y alas enormes de borde dentado; al final se deshace en
  chispas que caen (seg. 11,0-11,9).

Todo usa el fuego plano de firebend (cel, ribbon, teardrop, shed, rim).
"""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.firebend import CORE, MID, _floor, cel, ribbon, rim, shed, teardrop, warm
from vfxglow.engine.raster import fill_polygon, splat

FIRE_CREATURES = ("fire_skull", "fire_bird", "fire_serpent", "fire_splash", "fire_breath", "fire_dragon")


def ink(layer, curves: list[np.ndarray], color, alpha: float, width: int = 2) -> None:
    """Líneas finas de un color fijo (la calavera es blanca aunque el fuego sea naranja)."""
    height, w = layer.shape[:2]
    mask = np.zeros((height, w), np.float32)
    for curve in curves:
        if len(curve) >= 2:
            cv2.polylines(mask, [np.round(curve).astype(np.int32)], False, 1.0, width, cv2.LINE_AA)
    mask *= np.float32(alpha)
    layer[..., :3] += np.asarray(color, np.float32) * 1.8 * mask[..., None]
    layer[..., 3] = 1.0 - (1.0 - layer[..., 3]) * (1.0 - mask)


def bezier(points: list[np.ndarray], n: int = 30) -> np.ndarray:
    """Curva de Bézier por los puntos de control dados (de 3 o 4)."""
    q = np.linspace(0, 1, n)[:, None]
    if len(points) == 3:
        a, c, b = points
        return (1 - q) ** 2 * a + 2 * (1 - q) * q * c + q ** 2 * b
    a, c1, c2, b = points
    return (1 - q) ** 3 * a + 3 * (1 - q) ** 2 * q * c1 + 3 * (1 - q) * q ** 2 * c2 + q ** 3 * b


def comet(curve: np.ndarray, head: float, length: float, width: float, frame_index: int, layer, color, alpha, runtime, st=None, scale=1.0) -> np.ndarray | None:
    """Un tramo de fuego que viaja por `curve`: la cabeza en la fracción `head`, gruesa adelante."""
    n = len(curve)
    hi = int(np.clip(head, 0, 1) * (n - 1))
    lo = max(int((head - length) * (n - 1)), 0)
    if hi - lo < 3:
        return None
    part = curve[lo : hi + 1]
    q = np.linspace(0, 1, len(part))
    widths = width * (0.15 + 0.85 * np.sin(np.pi * np.clip(q * 0.9 + 0.1, 0, 1)) ** 0.6 * q ** 0.5)
    cel(layer, ribbon(part, widths, frame_index, 3.0), color, alpha, runtime)
    if st is not None:
        shed(layer, part, widths, st, frame_index, scale, color, alpha)
    return part[-1]


def wavy(base: np.ndarray, up: np.ndarray, length: float, width: float, frame_index: int, seed: float = 0.0):
    """make(k) de una llama alta y ondulada (más ondas que teardrop): la melena de la calavera."""
    side = np.array([-up[1], up[0]])
    s = np.linspace(0, 1, 26)
    sway = (np.sin(s * 6.0 - frame_index * 0.55 + seed) * 0.22 + np.sin(s * 2.0 + seed) * 0.12) * length * s
    spine = base + np.outer(s * length, up) + np.outer(sway, side)
    widths = width * np.sin(np.pi * (0.1 + 0.9 * s)) ** 0.7 * (1 - s) ** 0.3 + 0.5
    return ribbon(spine, widths, frame_index, 3.0, seed)


def _face(body, frame, scale):
    center, across, down = frame
    nose = body.get("nose")
    if nose is None:
        return None
    ears = [body.get("left_ear"), body.get("right_ear")]
    width = float(np.linalg.norm(ears[0] - ears[1])) if all(e is not None for e in ears) else 0.0
    return nose, max(width * 1.0, 0.36 * scale), -down, across


def _leader(body):
    """La mano que toma el protagonismo: la más rápida (o la más alta)."""
    best, speed = None, -1.0
    for name in ("left_wrist", "right_wrist"):
        p = body.get(name)
        if p is None:
            continue
        vel = body.points.get(f"vel:{body.prefix}{name}")
        v = float(np.linalg.norm(vel)) if vel is not None else -p[1] * 1e-3
        if v > speed:
            best, speed = p, v
    return best


# ----- la calavera -----


def _skull_lines(c, r, up, across) -> list[np.ndarray]:
    def at(pts):
        return np.array([c + across * x * r + up * y * r for x, y in pts])

    t = np.linspace(np.radians(-15), np.radians(195), 30)
    cranium = np.array([c + across * np.cos(a) * 0.95 * r + up * (0.05 + np.sin(a) * 1.05) * r for a in t])
    lines = [cranium]
    for s in (-1, 1):
        lines.append(at([(s * 0.92, 0.0), (s * 0.82, -0.3), (s * 0.62, -0.48), (s * 0.5, -0.62)]))  # sien y pómulo
        e = np.linspace(0, TAU, 18)  # cuenca: un óvalo algo cuadrado
        sock = np.stack([np.sign(np.cos(e)) * np.abs(np.cos(e)) ** 0.7, np.sign(np.sin(e)) * np.abs(np.sin(e)) ** 0.7], axis=1)
        lines.append(at([(s * 0.36 + x * 0.24, 0.12 + y * 0.22) for x, y in sock]))
    lines.append(at([(0.0, -0.08), (0.11, -0.34), (0.0, -0.4), (-0.11, -0.34), (0.0, -0.08)]))  # cavidad nasal
    lines.append(at([(-0.4, -0.6), (0.4, -0.6)]))  # dientes de arriba
    lines += [at([(x, -0.54), (x, -0.7)]) for x in np.linspace(-0.3, 0.3, 6)]
    lines.append(at([(-0.5, -0.6), (-0.46, -0.9), (-0.2, -1.05), (0.2, -1.05), (0.46, -0.9), (0.5, -0.6)]))  # mandíbula
    lines.append(at([(-0.34, -0.74), (0.34, -0.74)]))  # dientes de abajo
    lines += [at([(x, -0.72), (x, -0.84)]) for x in np.linspace(-0.25, 0.25, 5)]
    return lines


def _fire_skull(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = _face(body, frame, scale)
    if face is None:
        return []
    nose, r, up, across = face
    c = nose + up * 0.15 * r
    u = _phase(runtime, event)
    st = _activation(runtime, event, "skull", body)
    grow = _ease(_seg(u, 0.0, 0.2))
    leave = _seg(u, 0.7, 1.0)  # al final el fuego deja la cabeza
    if leave < 0.6:
        ink(layer, _skull_lines(c, r, up, across), CORE, alpha * (1 - leave))
        for s in (-1, 1):
            eye = c + across * s * 0.36 * r + up * 0.12 * r
            splat(layer, float(eye[0]), float(eye[1]), 0.12 * r, WHITE * 2.0, alpha, runtime.kernels)
    hair = grow * (1 - 0.8 * leave)
    for k, tilt in enumerate((-0.55, -0.15, 0.25, 0.6)):  # la melena: alta y ondulada
        d = up + across * tilt * 0.6
        d = d / float(np.linalg.norm(d))
        base = c + up * 0.95 * r + across * tilt * 0.75 * r
        tall = (1.0 - 0.3 * abs(tilt)) * 3.0 * r * hair
        if tall > 2:
            cel(layer, wavy(base, d, tall, 0.5 * r, frame_index, k * 1.9), color, alpha, runtime)
    rim(layer, runtime, [c], scale, color, alpha * grow, 1.0)
    if leave > 0:  # el fuego viaja de la cabeza a la mano que toma el protagonismo
        hand = _leader(body)
        if hand is not None:
            top = c + up * 1.2 * r
            curve = bezier([top, top + up * 1.2 * scale + across * 0.8 * scale, hand + up * 0.8 * scale, hand], 40)
            comet(curve, _ease(leave) * 1.1, 0.5, 0.35 * scale, frame_index, layer, color, alpha, runtime, st, scale)
    return []


# ----- el ave de fuego y el dragón serpiente -----


# Fénix en coordenadas propias: x hacia adelante (el pico), y hacia el ala izquierda.
# Ala barrida hacia atrás: borde de ataque que sube y se curva a la punta, y plumas en el borde de
# fuga que vuelven al cuerpo.
_WING = [(0.2, 0.12), (0.32, 0.55), (0.18, 0.95), (-0.15, 1.3), (-0.65, 1.5), (-0.55, 1.2), (-0.8, 1.12), (-0.62, 0.88), (-0.88, 0.76), (-0.6, 0.55), (-0.8, 0.38), (-0.38, 0.16)]
_TAIL = [(-0.42, 0.1), (-1.0, 0.3), (-1.8, 0.55), (-1.35, 0.12), (-1.95, 0.0), (-1.35, -0.12), (-1.8, -0.55), (-1.0, -0.3), (-0.42, -0.1)]
_HEAD = [(0.35, -0.12), (0.72, -0.06), (0.92, 0.0), (0.72, 0.06), (0.35, 0.12)]


def _bird_shape(at, heading, size, flap, frame_index):
    """make(k) de un ave de fuego: pico, dos alas abiertas con plumas en punta y cola de llamas.
    `flap` en [-1, 1] abre y cierra las alas."""
    d = heading / max(float(np.linalg.norm(heading)), 1e-6)
    n = np.array([-d[1], d[0]])
    open_ = 0.65 + 0.35 * flap
    sway = np.sin(frame_index * 0.5) * 0.15

    def make(k: float):
        s = size * (0.6 + 0.4 * k)
        pts = list(_HEAD)
        pts += [(x, y * open_) for x, y in _WING]
        pts += [(x, y + sway * (x < -0.6)) for x, y in _TAIL]
        pts += [(x, -y * open_) for x, y in reversed(_WING)]
        return np.array([at + d * x * s + n * y * s for x, y in pts])

    return make


def _fire_bird(body, frame, scale, frame_index, runtime, layer, color, alpha, event, serpent: bool = False) -> list:
    center, across, down = frame
    up = -down
    wrists = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
    if not wrists:
        return []
    hand = min(wrists, key=lambda p: p[1])  # la mano levantada
    u = _phase(runtime, event)
    st = _activation(runtime, event, "bird", body)
    side = 1.0 if hand[0] < center[0] else -1.0  # vuela hacia el lado abierto
    # Sale de la mano, sube y se abre, da la vuelta y regresa a la mano.
    a = _ease(_seg(u, 0.0, 0.85)) * TAU * 0.75
    out = np.sin(a * 2 / 3 * 1.0) if u < 0.85 else 0.0
    pos = hand + up * (0.2 + 1.3 * np.sin(a / 1.5)) * scale + across * side * 1.1 * np.sin(a) * scale * (1 if u < 0.85 else 0)
    prev = st.get("pos", pos)
    heading = pos - prev if np.linalg.norm(pos - prev) > 0.5 else st.get("heading", up)
    st.update(pos=pos, heading=heading)
    trail = st.setdefault("trail", [])
    trail.append(pos.copy())
    del trail[:-22]
    grow = _ease(_seg(u, 0.0, 0.15)) * (1.0 - _seg(u, 0.88, 1.0))
    # La corriente en S que une la mano con la criatura (seg. 4,4).
    mid = (hand + pos) / 2 + across * side * 0.35 * scale * np.sin(frame_index * 0.25)
    stream = bezier([hand, mid + up * 0.3 * scale, mid - up * 0.1 * scale, pos], 30)
    q = np.linspace(0, 1, 30)
    cel(layer, ribbon(stream, (0.06 + 0.12 * np.sin(np.pi * q)) * scale * grow + 0.5, frame_index, 4.0), color, alpha, runtime)
    if serpent and len(trail) > 4:  # el dragón serpiente: el cuerpo es su propio recorrido
        spine = np.array(trail)
        q = np.linspace(0, 1, len(spine))
        cel(layer, ribbon(spine, (0.03 + 0.13 * q ** 0.7) * scale * grow, frame_index, 5.0), color, alpha, runtime)
        d = heading / max(float(np.linalg.norm(heading)), 1e-6)
        n = np.array([-d[1], d[0]])
        h = 0.25 * scale * grow
        head = lambda k: np.array([pos + d * h * 1.2 * k, pos + n * h * 0.5 * k - d * h * 0.1, pos - d * h * 0.4 + n * h * 0.9 * k, pos - d * h * 0.3, pos - d * h * 0.4 - n * h * 0.9 * k, pos - n * h * 0.5 * k])
        cel(layer, head, color, alpha, runtime)
        for s in (-1, 1):
            eye = pos + n * s * 0.18 * h
            splat(layer, float(eye[0]), float(eye[1]), 0.05 * h + 1, WHITE * 2.0, alpha, runtime.kernels)
    else:
        flap = np.sin(frame_index * 0.7)
        cel(layer, _bird_shape(pos, heading, 0.9 * scale * grow, flap, frame_index), color, alpha, runtime)
    shed(layer, stream, np.full(30, 0.06 * scale), st, frame_index, scale, color, alpha, 0.7)
    rim(layer, runtime, [hand], scale, color, alpha)
    return []


# ----- el fuego que choca contra el piso -----


def _fire_splash(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    floor = _floor(body, scale)
    if floor is None:
        return []
    st = _activation(runtime, event, "splash", body)
    if "x0" not in st:
        hands = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
        st["x0"] = float(max(hands, key=lambda p: p[1])[0]) if hands else float(frame[0][0])
        st["born"] = frame_index
    x0 = st["x0"]
    age = frame_index - st["born"]
    u = _phase(runtime, event)
    spread = _ease(min(age / 8.0, 1.0)) * 2.6 * scale
    jelly = 1.0 + 0.4 * np.sin(age * 0.9) * np.exp(-age / 7.0)  # tiembla como gelatina y se asienta
    flatten = 1.0 - 0.8 * _seg(u, 0.5, 1.0)
    height = 1.6 * scale * jelly * flatten
    for side in (-1.0, 1.0):
        crest_x = x0 + side * spread
        xs = np.linspace(x0, crest_x, 24)
        q = np.linspace(0, 1, 24)

        def make(k: float, xs=xs, q=q, side=side, crest_x=crest_x):
            h = height * k * (0.12 + 0.88 * q ** 2.5)  # baja cerca del golpe, sube en la cresta
            top = np.stack([xs, floor - h], axis=1)
            peak = h[-1]
            # La cresta se enrosca hacia el golpe: un rulo que vuelve sobre sí mismo.
            a = np.linspace(0.0, np.pi * 1.3, 10)
            curl = np.stack([crest_x - side * (np.sin(a) * 0.35 * peak), floor - peak + (1 - np.cos(a)) * 0.35 * peak - 0.15 * peak * np.sin(a)], axis=1)
            return np.vstack([[[x0, floor]], top, curl, [[crest_x - side * 0.25 * peak, floor - peak * 0.35], [crest_x + side * 0.12 * scale, floor]]])

        cel(layer, make, color, alpha, runtime, 1.2)
        line = np.stack([np.linspace(x0, crest_x + side * 0.6 * scale, 20), np.full(20, floor - 0.3 * height)], axis=1)
        shed(layer, line, np.full(20, 0.2 * height + 1), st, frame_index, scale, color, alpha, 1.0)
    rim(layer, runtime, [np.array([x0, floor])], scale, color, alpha, 1.2)
    return []


# ----- la cara que echa fuego -----


def _fire_breath(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = _face(body, frame, scale)
    hand = _leader(body)
    if face is None or hand is None:
        return []
    nose, r, up, across = face
    center = frame[0]
    u = _phase(runtime, event)
    st = _activation(runtime, event, "breath", body)
    mouth = nose - up * 0.35 * r
    if u < 0.3:  # sube por el costado hasta la cabeza
        st.setdefault("start", hand.copy())
        start = st["start"]
        side = across * (1.0 if start[0] > center[0] else -1.0)
        curve = bezier([start, start + up * 0.6 * scale + side * 0.4 * scale, nose + side * 0.8 * r + up * 0.2 * r, nose], 30)
        if u < 0.1:  # arranca como una llama en la mano (seg. 7,8)
            cel(layer, teardrop(hand, up, 0.6 * scale, 0.16 * scale, frame_index), color, alpha, runtime)
        comet(curve, _seg(u, 0.0, 0.3) * 1.1, 0.5, 0.18 * scale, frame_index, layer, color, alpha, runtime, st, scale)
    elif u < 0.45:  # envuelve la cabeza
        a0 = frame_index * 0.4
        a = np.linspace(a0, a0 + TAU * 0.85, 30)
        ring = nose + np.stack([np.cos(a), np.sin(a)], axis=1) * 1.7 * r
        cel(layer, ribbon(ring, 0.45 * r * np.sin(np.linspace(0.1, np.pi - 0.1, 30)) + 0.5, frame_index, 5.0), color, alpha, runtime)
    elif u < 0.65:  # la bola de fuego sale de la boca hacia arriba y se dispersa
        s = _seg(u, 0.45, 0.65)
        rng = np.random.default_rng(int(event.start_frame) if event is not None else 3)
        for k in range(9):  # una nube de fuego que llena medio cuadro (seg. 8,13-8,2)
            off = np.array([rng.uniform(-1.3, 1.3), -abs(rng.uniform(0.4, 2.4))]) * scale * (0.3 + 1.0 * s)
            rad = rng.uniform(0.5, 1.0) * scale * (0.5 + 0.9 * s) * (1 - 0.35 * s)
            blob = lambda kk, at=mouth + off, rad=rad: np.array([at + np.array([np.cos(a), np.sin(a)]) * rad * (0.6 + 0.4 * kk) * (1 + 0.08 * np.sin(a * 5 + frame_index)) for a in np.linspace(0, TAU, 22)])
            cel(layer, blob, color, alpha, runtime, 0.6, core=k % 2 == 0)
        warm(layer, mouth - up * scale * s, 2.2 * scale, np.asarray(color, np.float32), alpha * 0.4)
    if u >= 0.55:  # la cara de demonio: ojos encendidos y colmillos
        for name, s in (("left_eye", -1), ("right_eye", 1)):
            eye = body.get(name)
            if eye is None:
                eye = nose + up * 0.25 * r + across * s * 0.3 * r
            slant = np.array([eye + across * (-0.2 * r) + up * (0.08 * s * r), eye + across * (0.2 * r) - up * (0.08 * s * r)])
            ink(layer, [slant], CORE, alpha, 3)
            splat(layer, float(eye[0]), float(eye[1]), 0.16 * r, WHITE * 2.2, alpha, runtime.kernels)
        fangs = np.array([mouth + across * x * r + up * (0.0 if i % 2 == 0 else -0.15) * r for i, x in enumerate(np.linspace(-0.35, 0.35, 7))])
        ink(layer, [fangs], CORE, alpha, 2)
    if u >= 0.75:  # el fuego rodea el cuerpo hasta la mano que toma el protagonismo
        s = _seg(u, 0.75, 1.0)
        a = np.linspace(0, TAU * 0.9, 40)
        spiral = np.array([center + np.array([np.cos(x) * 1.1, np.sin(x) * 0.5]) * scale * (1.2 - 0.2 * x / TAU) for x in a])
        curve = np.vstack([spiral, bezier([spiral[-1], (spiral[-1] + hand) / 2 + up * 0.3 * scale, hand], 12)])
        comet(curve, s * 1.05, 0.35, 0.16 * scale, frame_index, layer, color, alpha, runtime, st, scale)
    rim(layer, runtime, [nose, hand], scale, color, alpha, 1.1)
    return []


# ----- el dragón de alas -----


def _wing(root, tip, side: float, drop: float, claws: int, k: float) -> np.ndarray:
    """Ala de dragón: borde de ataque arqueado hacia arriba del cuello a la punta, y borde de fuga
    hecho de festones que terminan en garras afiladas hacia abajo y afuera."""
    span = float(np.linalg.norm(tip - root))
    lead = bezier([root, root + (tip - root) * 0.45 + np.array([0.0, -0.45 * span]), tip], 18)
    edge = [tip]
    for i in range(claws):
        a = root + (tip - root) * (1 - i / claws)
        b = root + (tip - root) * (1 - (i + 1) / claws)
        reach = drop * (0.55 + 0.45 * np.sin(np.pi * (1 - (i + 0.5) / claws))) * k
        claw = (a + b) / 2 + np.array([side * 0.12 * drop, reach])
        sag = [a + (claw - a) * 0.5 + np.array([0.0, -0.15 * drop]), claw]
        back = [claw + (b - claw) * f + np.array([0.0, -0.25 * drop * np.sin(np.pi * f)]) for f in (0.35, 0.7, 1.0)]
        edge += sag + back
    return np.vstack([lead, np.array(edge)])


def _fire_dragon(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    up = np.array([0.0, -1.0])
    joints = {n: body.get(n) for n in ("left_wrist", "right_wrist", "left_shoulder", "right_shoulder", "left_ankle", "right_ankle", "nose")}
    if any(joints[n] is None for n in ("left_wrist", "right_wrist", "left_shoulder", "right_shoulder")):
        return []
    u = _phase(runtime, event)
    st = _activation(runtime, event, "dragon", body)
    top = (joints["left_shoulder"] + joints["right_shoulder"]) / 2 + up * 1.2 * scale  # el cuello del dragón
    if u >= 0.9:  # se deshace en chispas que caen
        s = _seg(u, 0.9, 1.0)
        rng = np.random.default_rng(int(event.start_frame) if event is not None else 11)
        for _ in range(40):
            p = top + np.array([rng.uniform(-2.2, 2.2), rng.uniform(-0.8, 1.6)]) * scale + np.array([0.0, s * s * 1.2 * scale])
            splat(layer, float(p[0]), float(p[1]), 0.015 * scale + 1, MID * 1.6, alpha * (1 - s), runtime.kernels)
        return []
    climb = _ease(_seg(u, 0.0, 0.3))  # las llamas suben por los brazos desde el piso
    for side in ("left", "right"):
        wrist, shoulder = joints[f"{side}_wrist"], joints[f"{side}_shoulder"]
        arm = bezier([wrist, (wrist + shoulder) / 2 + (shoulder - center) * 0.3, shoulder, top], 30)
        q = np.linspace(0, 1, 30)
        cut = max(int(30 * climb), 3)
        cel(layer, ribbon(arm[:cut], (0.08 + 0.07 * np.sin(np.pi * q[:cut])) * scale, frame_index, 6.0), color, alpha, runtime)
        shed(layer, arm[:cut], np.full(cut, 0.06 * scale), st, frame_index, scale, color, alpha, 0.6)
        ankle = joints[f"{side}_ankle"]
        if ankle is not None:  # y por las piernas
            leg = bezier([ankle, (ankle + center) / 2, center + down * 0.2 * scale], 16)
            cel(layer, ribbon(leg[: max(int(16 * climb), 3)], np.full(max(int(16 * climb), 3), 0.04 * scale), frame_index, 4.0), color, alpha, runtime)
    spread = _ease(_seg(u, 0.3, 0.55))
    if spread > 0:
        flap = np.sin(frame_index * 0.35) * 0.15
        for s in (-1.0, 1.0):
            tip = top + np.array([s * 2.2, -1.0 - flap]) * scale * spread
            make = lambda k, tip=tip, s=s: _wing(top, tip, s, 1.1 * scale * spread, 5, k)
            cel(layer, make, color, alpha, runtime, 1.4)
        h = 0.32 * scale * spread  # la cabeza: hocico, cuernos y ojos
        head = lambda k: np.array([top + up * h * 1.6 * k, top + np.array([0.35, -1.0]) * h * k, top + np.array([0.6, -0.9]) * h, top + np.array([0.3, -0.3]) * h, top + np.array([0.0, 0.4]) * h, top + np.array([-0.3, -0.3]) * h, top + np.array([-0.6, -0.9]) * h, top + np.array([-0.35, -1.0]) * h * k])
        cel(layer, head, color, alpha, runtime)
        for s in (-1, 1):
            eye = top + np.array([s * 0.2, -0.75]) * h
            splat(layer, float(eye[0]), float(eye[1]), 0.08 * h + 1, WHITE * 2.0, alpha, runtime.kernels)
    rim(layer, runtime, [joints["left_wrist"], joints["right_wrist"], top], scale, color, alpha, 1.3)
    return []


def fire_creature(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    if shape == "fire_skull":
        return _fire_skull(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in ("fire_bird", "fire_serpent"):
        return _fire_bird(body, frame, scale, frame_index, runtime, layer, color, alpha, event, shape == "fire_serpent")
    if shape == "fire_splash":
        return _fire_splash(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_breath":
        return _fire_breath(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_dragon":
        return _fire_dragon(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
