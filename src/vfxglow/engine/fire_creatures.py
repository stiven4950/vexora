"""Criaturas y momentos del maestro fuego (glowing/video_18.mp4, lectura del usuario).

- `fire_skull`: calavera de frente dibujada en línea blanca (cráneo, sienes, cuencas, cavidad
  nasal, pómulos, dientes y mandíbula) con una melena de fuego alta y ondulada; al final el fuego
  deja la cabeza y viaja en un trazo hasta la mano que toma el protagonismo (seg. 3,1-3,6).
- `fire_bird` / `fire_serpent`: de la mano levantada sale un ave de fuego (o un dragón serpiente)
  unida a la mano por una corriente en S; vuela, vuelve y se ondula siguiendo la mano (seg. 4,2-4,8).
- `fire_phoenix` / `fire_dragon_launch`: bestias que se lanzan (video_51, seg. 7,0-7,3): salen del
  puño en la dirección del golpe o del lanzamiento, el ave aleteando y el dragón serpiente
  ondulando, y se van sin volver; al alejarse se deshacen en trozos.
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
from vfxglow.engine.firebend import CORE, MID, _floor, _unit, _wrist, cel, flame_physics, note_fire, note_frame, ribbon, rim, shed, teardrop, transfer_fire, warm
from vfxglow.engine.raster import fill_polygon, splat

FIRE_CREATURES = ("fire_skull", "fire_bird", "fire_serpent", "fire_splash", "fire_breath", "fire_dragon", "fire_phoenix", "fire_dragon_launch")


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
    name = _leader_name(body)
    return body.get(name) if name else None


def _leader_name(body) -> str | None:
    best, speed = None, -1.0
    for name in ("left_wrist", "right_wrist"):
        p = body.get(name)
        if p is None:
            continue
        vel = body.points.get(f"vel:{body.prefix}{name}")
        v = float(np.linalg.norm(vel)) if vel is not None else -p[1] * 1e-3
        if v > speed:
            best, speed = name, v
    return best


# ----- la calavera -----


# Calavera en 3D (x a la derecha, y arriba, z hacia la cámara; unidad = radio de la cara). Se
# proyecta con el giro real de la cabeza: de frente como siempre y, al girar, de perfil (cuenca de
# lado, mandíbula hacia adelante, sutura del costado), ocultando lo que queda atrás.


def _rot(points: np.ndarray, yaw: float) -> np.ndarray:
    c, s = np.cos(yaw), np.sin(yaw)
    x, y, z = points[:, 0], points[:, 1], points[:, 2]
    return np.stack([x * c + z * s, y, -x * s + z * c], axis=1)


def _circle3d(center, normal, radius, n: int = 20) -> np.ndarray:
    normal = np.asarray(normal, float) / np.linalg.norm(normal)
    a = np.cross(normal, [0.0, 1.0, 0.0])
    if np.linalg.norm(a) < 1e-3:
        a = np.array([1.0, 0.0, 0.0])
    a /= np.linalg.norm(a)
    b = np.cross(normal, a)
    t = np.linspace(0, TAU, n)
    return np.asarray(center, float) + np.outer(np.cos(t) * radius[0], a) + np.outer(np.sin(t) * radius[1], b)


def _skull3d(c, r, up, across, yaw: float, layer) -> list[np.ndarray]:
    """Líneas de la calavera vista con giro `yaw` (radianes; + mira a la derecha de la imagen)."""

    def screen(pts3):
        q = _rot(np.asarray(pts3, float), yaw)
        return np.array([c + across * x * r + up * y * r for x, y in q[:, :2]]), q[:, 2]

    def facing(normal) -> float:
        return float(_rot(np.asarray([normal], float), yaw)[0, 2])

    lines: list[np.ndarray] = []
    height, width = layer.shape[:2]
    # Silueta: la unión del cráneo (elipsoide) y la cara de abajo (pómulos, maxilar y mandíbula),
    # con el contorno real de esa unión (conserva la entrada bajo el pómulo del perfil).
    u = np.linspace(0, TAU, 28)
    v = np.linspace(-0.42 * np.pi, 0.5 * np.pi, 12)
    # Abajo el cráneo se cierra más (la nuca baja curvada hasta la base, no una línea recta).
    shell = np.array([[0.88 * np.cos(a) * np.cos(b) * (1.0 if b > 0 else 0.85 + 0.15 * np.cos(b)), 0.25 + (1.0 if b > 0 else 0.62) * np.sin(b), -0.15 + 0.95 * np.sin(a) * np.cos(b) * (1.0 if b > 0 or np.sin(a) >= 0 else 0.75)] for a in u for b in v])
    face = []
    for s in (-1.0, 1.0):
        face += [[s * 0.62, -0.2, 0.45], [s * 0.5, -0.45, 0.55], [s * 0.45, -0.62, 0.62], [s * 0.52, -0.9, 0.2], [s * 0.6, -0.4, -0.05], [s * 0.2, -1.08, 0.55]]
    face += [[0.0, -0.62, 0.86], [0.0, -1.1, 0.62], [0.0, -0.3, 0.92]]
    mask = np.zeros((height, width), np.uint8)
    hull_a = cv2.convexHull(np.round(screen(shell)[0]).astype(np.int32))
    hull_b = cv2.convexHull(np.round(screen(np.array(face))[0]).astype(np.int32))
    cv2.fillPoly(mask, [hull_a, hull_b], 1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if contours:
        outline = max(contours, key=cv2.contourArea).reshape(-1, 2).astype(float)[::3]
        lines.append(np.vstack([outline, outline[:1]]))
    # Cuencas de los ojos: círculos sobre la cara, que se achatan al girar y se ocultan atrás.
    for s in (-1.0, 1.0):
        normal = [s * 0.35, 0.0, 0.94]
        if facing(normal) > 0.35:  # la del lado de atrás se oculta antes de asomar por el borde
            ring = _circle3d([s * 0.36, 0.12, 0.72], normal, (0.22, 0.2))
            lines.append(screen(ring)[0])
        # Sutura del costado y borde del pómulo: se ven sobre todo de perfil (como en la imagen).
        if facing([s, 0.0, 0.25]) > 0.2:
            lines.append(screen([[s * 0.8, 0.35, 0.15], [s * 0.86, 0.12, 0.2], [s * 0.78, -0.05, 0.3], [s * 0.82, -0.2, 0.35]])[0])
            lines.append(screen([[s * 0.82, -0.2, 0.35], [s * 0.66, -0.3, 0.45], [s * 0.55, -0.5, 0.56]])[0])
    # Cavidad nasal.
    if facing([0.0, 0.0, 1.0]) > 0.05:
        lines.append(screen([[0.0, -0.08, 0.86], [0.11, -0.34, 0.88], [0.0, -0.4, 0.92], [-0.11, -0.34, 0.88], [0.0, -0.08, 0.86]])[0])
    # Dientes: en arco (los del costado se ven de canto al girar y los de atrás se ocultan).
    xs = np.linspace(-0.38, 0.38, 9)
    arc_top = np.array([[x, -0.58, 0.82 - 0.9 * x * x] for x in xs])
    arc_low = np.array([[x, -0.76, 0.78 - 0.9 * x * x] for x in xs])
    seen = np.array([facing([x * 1.8, 0.0, 1.0]) > 0.05 for x in xs])
    for arc in (arc_top, arc_low):
        pts = screen(arc[seen])[0] if seen.sum() >= 2 else None
        if pts is not None:
            lines.append(pts)
    for i, x in enumerate(xs):
        if seen[i]:
            lines.append(screen([[x, -0.53, 0.82 - 0.9 * x * x], [x, -0.81, 0.78 - 0.9 * x * x]])[0])
    # Mandíbula: del ángulo de cada lado al mentón (se dibuja el lado visible).
    for s in (-1.0, 1.0):
        if facing([s, -0.3, 0.4]) > -0.25:
            lines.append(screen([[s * 0.58, -0.35, -0.02], [s * 0.53, -0.88, 0.18], [s * 0.3, -1.04, 0.5], [0.0, -1.1, 0.62]])[0])
    return lines


def _skull_eyes(c, r, up, across, yaw: float):
    out = []
    for s in (-1.0, 1.0):
        q = _rot(np.array([[s * 0.36, 0.12, 0.72]]), yaw)[0]
        normal_z = _rot(np.array([[s * 0.35, 0.0, 0.94]]), yaw)[0, 2]
        if normal_z > 0.35:
            out.append(c + across * q[0] * r + up * q[1] * r)
    return out


def _fire_skull(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = _face(body, frame, scale)
    if face is None:
        return []
    nose, r, up, across = face
    u = _phase(runtime, event)
    st = _activation(runtime, event, "skull", body)
    # Giro de la cabeza (suavizado): la nariz respecto de las orejas, en radianes.
    from vfxglow.engine.characters import head_yaw

    yaw = float(np.arcsin(np.clip(head_yaw(body), -0.98, 0.98)))
    yaw = st["yaw"] = st.get("yaw", yaw) * 0.6 + yaw * 0.4
    # El centro de la calavera: detrás de la nariz (de perfil la nariz está adelante del cráneo).
    c = nose + up * 0.15 * r - across * np.sin(yaw) * 0.75 * r
    grow = _ease(_seg(u, 0.0, 0.2))
    leave = _seg(u, 0.7, 1.0)  # al final el fuego deja la cabeza
    if leave < 0.6:
        ink(layer, _skull3d(c, r, up, across, yaw, layer), CORE, alpha * (1 - leave))
        for eye in _skull_eyes(c, r, up, across, yaw):
            splat(layer, float(eye[0]), float(eye[1]), 0.12 * r, WHITE * 2.0, alpha, runtime.kernels)
    hair = grow * (1 - 0.8 * leave)
    # Física: la melena se inclina contra el movimiento de la cabeza, con inercia.
    lean, stretch = flame_physics(st, "hair", c, scale, up)
    for k, tilt in enumerate((-0.55, -0.15, 0.25, 0.6)):  # la melena: alta y ondulada
        d = lean + across * tilt * 0.6
        d = d / float(np.linalg.norm(d))
        base = c + up * 0.95 * r + across * tilt * 0.75 * r
        tall = (1.0 - 0.3 * abs(tilt)) * 3.0 * r * hair * stretch
        if tall > 2:
            cel(layer, wavy(base, d, tall, 0.5 * r, frame_index, k * 1.9), color, alpha, runtime)
    rim(layer, runtime, [c], scale, color, alpha * grow, 1.0)
    if leave <= 0:
        note_fire(body, ("head",), frame_index)  # el fuego está en la cabeza
        return []
    # Al final el fuego deja la cabeza y viaja a la mano que toma el protagonismo (video_51, seg.
    # 3,5), con el traspaso de siempre: trocitos que se enroscan y se juntan en la mano.
    name = st.setdefault("hand", _leader_name(body))
    hand = body.get(name) if name else None
    if hand is not None:
        lit = transfer_fire(body, (name,), frame_index, scale, layer, color, alpha, runtime, st.setdefault("transfer", {}))[name]
        if lit > 0:  # llegó: la llama prendida en la mano
            cel(layer, teardrop(hand, up, 0.9 * scale * lit, 0.2 * scale * lit + 0.5, frame_index, 4.4), color, alpha, runtime)
    return []


# ----- el ave de fuego y el dragón serpiente -----


# Fénix en coordenadas propias: x hacia adelante (el pico), y hacia el ala izquierda.
# Ala barrida hacia atrás: borde de ataque que sube y se curva a la punta, y plumas en el borde de
# fuga que vuelven al cuerpo.
_WING = [(0.12, 0.08), (0.3, 0.5), (0.25, 0.95), (0.0, 1.45), (-0.55, 1.75), (-0.35, 1.35), (-0.62, 1.3), (-0.4, 1.0), (-0.7, 0.92), (-0.42, 0.66), (-0.66, 0.5), (-0.3, 0.14)]
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
        cel(layer, _bird_shape(pos, heading, 0.65 * scale * grow, flap, frame_index), color, alpha, runtime)
    shed(layer, stream, np.full(30, 0.06 * scale), st, frame_index, scale, color, alpha, 0.7)
    rim(layer, runtime, [hand], scale, color, alpha)
    return []


# ----- bestias que se lanzan -----


def _launched_beast(body, frame, scale, frame_index, runtime, layer, color, alpha, event, dragon: bool = False) -> list:
    """Una bestia de fuego que se lanza (video_51, seg. 7,0-7,3): nace en el puño, sale en la
    dirección del golpe o del lanzamiento (el antebrazo) y un poco hacia arriba, y se va sin volver:
    el ave aleteando (fénix), el dragón serpiente ondulando con el cuerpo como su recorrido. Al
    alejarse se achica y se deshace en trozos."""
    center, across, down = frame
    up = -down
    found = _wrist(body, event, scale)
    if found is None:
        return []
    name, hand = found
    st = _activation(runtime, event, f"beast:{name}", body)
    if "aim" not in st:  # se decide al lanzar: hacia donde apunta el antebrazo, y algo hacia arriba
        elbow = body.get(name.replace("wrist", "elbow").replace("ankle", "knee"))
        aim = (hand - elbow) if elbow is not None and float(np.linalg.norm(hand - elbow)) > 1 else across
        aim = aim / max(float(np.linalg.norm(aim)), 1e-6) + up * 0.6
        aim = aim / float(np.linalg.norm(aim))
        # Hacia el espacio libre: si el vuelo se sale enseguida del cuadro (el puño junto a un
        # borde), se va hacia el otro lado (una bestia que se pierde al nacer no se ve).
        height, width = layer.shape[:2]
        land = hand + aim * 3.0 * _unit(scale, layer)
        if not (0 <= land[0] < width):
            aim = np.array([-aim[0], aim[1]])
        st.update(aim=aim, origin=np.asarray(hand, dtype=np.float64).copy())
    aim, origin = st["aim"], st["origin"]
    side = np.array([-aim[1], aim[0]])
    u = _phase(runtime, event)
    unit = _unit(scale, layer)
    # Sale despacio (se ve la bestia junto al puño) y después se aleja rápido; la trayectoria ondula.
    travel = _seg(u, 0.05, 0.85) ** 1.6
    wave = np.sin(u * 9.0) * 0.35 * unit * travel
    pos = origin + aim * 5.0 * unit * travel + side * wave
    prev = st.get("pos", pos)
    heading = pos - prev if float(np.linalg.norm(pos - prev)) > 0.5 else st.get("heading", aim)
    st.update(pos=pos, heading=heading)
    trail = st.setdefault("trail", [])
    trail.append(pos.copy())
    del trail[:-18]
    grow = _ease(_seg(u, 0.0, 0.12))
    fade = 1.0 - _seg(u, 0.7, 1.0)  # al alejarse se achica y se deshace
    size = (2.2 if dragon else 1.6) * unit * grow * fade * (1.0 - 0.3 * travel)
    if size < 1.0:
        return []
    if u < 0.25:  # la corriente que lo une al puño al salir
        q = np.linspace(0, 1, 20)
        stream = origin + np.outer(q, pos - origin) + np.outer(np.sin(np.pi * q) * 0.2 * unit, side)
        cel(layer, ribbon(stream, (0.04 + 0.14 * q) * unit * (1 - u / 0.25) + 0.5, frame_index, 4.0), color, alpha, runtime)
    if dragon:
        # El cuerpo es el tramo de trayectoria detrás de la cabeza (no el historial de cuadros: al
        # salir despacio quedaba un muñón): largo y ondulando como serpiente.
        # El cuerpo: 3 unidades detrás de la cabeza, en S (aunque recién salga del puño).
        body_len = 4.5 * unit * min(travel * 4.0 + 0.4, 1.0)
        q_ = np.linspace(-1.0, 0.0, 28)
        spine = pos + np.outer(q_ * body_len, aim) + np.outer(np.sin(q_ * 7.0 + frame_index * 0.35) * 0.45 * unit * (-q_) ** 0.6, side)
        spine[-1] = pos
        q = np.linspace(0, 1, len(spine))
        widths = (0.02 + 0.07 * np.sin(np.pi * np.clip(q * 0.85 + 0.1, 0, 1)) ** 0.6) * size
        cel(layer, ribbon(spine, widths, frame_index, 6.0, 3.3), color, alpha, runtime)
        normals = np.gradient(spine, axis=0)
        normals = np.stack([-normals[:, 1], normals[:, 0]], axis=1) / np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-6)
        for j in range(4, len(spine) - 3, 3):  # crestas del lomo, inclinadas hacia la cola
            tip_dir = normals[j] * 0.8 - (spine[j + 1] - spine[j - 1]) / max(float(np.linalg.norm(spine[j + 1] - spine[j - 1])), 1e-6) * 0.6
            cel(layer, teardrop(spine[j] + normals[j] * widths[j] * 0.8, tip_dir / max(float(np.linalg.norm(tip_dir)), 1e-6), widths[j] * 2.2, widths[j] * 0.3 + 0.5, frame_index, j * 0.7), color, alpha, None)
        d = heading / max(float(np.linalg.norm(heading)), 1e-6)
        n = np.array([-d[1], d[0]])
        h = 0.42 * size
        jaw = 0.35 + 0.15 * np.sin(frame_index * 0.6)  # la boca se abre y se cierra
        upper = np.array([pos - d * h * 0.5 + n * h * 0.35, pos + d * h * 0.4 + n * h * 0.4, pos + d * h * 1.3 + n * h * jaw * 0.5, pos + d * h * 0.3, pos - d * h * 0.5])
        lower = np.array([pos - d * h * 0.4, pos + d * h * 0.3 - n * h * 0.05, pos + d * h * 1.1 - n * h * jaw * 0.6, pos + d * h * 0.3 - n * h * 0.35, pos - d * h * 0.4 - n * h * 0.3])
        cel(layer, lambda k, upper=upper: upper, color, alpha, runtime)
        cel(layer, lambda k, lower=lower: lower, color, alpha, None)
        for s_ in (1, -1):  # los cuernos, hacia atrás y separados de la cabeza
            root = pos - d * h * 0.35 + n * s_ * h * 0.3
            cel(layer, teardrop(root, -d * 0.8 + n * s_ * 0.6, h * 1.1, h * 0.12 + 0.5, frame_index, 5.1 + s_, 0.3 * s_), color, alpha, None)
        eye = pos + d * h * 0.15 + n * h * 0.25
        splat(layer, float(eye[0]), float(eye[1]), 0.07 * h + 1, WHITE * 2.0, alpha, runtime.kernels)
        shed(layer, spine, widths, st, frame_index, scale, color, alpha, 1.5 * (1 + 2 * (1 - fade)))
    else:
        flap = np.sin(frame_index * 0.8)
        cel(layer, _bird_shape(pos, heading, 1.1 * size, flap, frame_index), color, alpha, runtime)
        if len(trail) > 3:  # la estela de fuego que deja al volar
            spine = np.array(trail)
            q = np.linspace(0, 1, len(spine))
            cel(layer, ribbon(spine, (0.02 + 0.12 * q) * size, frame_index, 5.0, 1.1), color, alpha, None)
            shed(layer, spine, (0.02 + 0.12 * q) * size, st, frame_index, scale, color, alpha, 1.0 + 3 * (1 - fade))
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
    height = 0.9 * scale * jelly * flatten
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
    # Duración propia (~1,4 s): disparado por un movimiento frenético largo, la bola de fuego
    # crecía hasta tapar todo (seg. 11,2).
    u = min(runtime.active_frames / max(1.4 * runtime.fps, 1.0), 1.0)
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
            off = np.array([rng.uniform(-1.0, 1.0), -abs(rng.uniform(0.4, 1.8))]) * scale * (0.3 + 0.8 * s)
            rad = rng.uniform(0.28, 0.55) * scale * (0.5 + 0.7 * s) * (1 - 0.35 * s)
            blob = lambda kk, at=mouth + off, rad=rad: np.array([at + np.array([np.cos(a), np.sin(a)]) * rad * (0.6 + 0.4 * kk) * (1 + 0.08 * np.sin(a * 5 + frame_index)) for a in np.linspace(0, TAU, 22)])
            cel(layer, blob, color, alpha, runtime, 0.6, mass=True)
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
    note_frame(frame_index)
    if shape == "fire_skull":
        return _fire_skull(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape in ("fire_bird", "fire_serpent"):
        return _fire_bird(body, frame, scale, frame_index, runtime, layer, color, alpha, event, shape == "fire_serpent")
    if shape in ("fire_phoenix", "fire_dragon_launch"):
        return _launched_beast(body, frame, scale, frame_index, runtime, layer, color, alpha, event, shape == "fire_dragon_launch")
    if shape == "fire_splash":
        return _fire_splash(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_breath":
        return _fire_breath(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_dragon":
        return _fire_dragon(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
