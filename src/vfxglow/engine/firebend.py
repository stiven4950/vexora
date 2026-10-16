"""Fuego de maestro fuego, estilo anime (adornos `type: adornment`, `style.shapes`).

Leído de glowing/video_18.mp4 (docs/referencias/video_18.md): el fuego sale de lo que hace el
cuerpo y se dibuja plano, en tres capas anidadas (borde naranja, cuerpo amarillo, núcleo casi
blanco) con lenguas definidas, no como un brillo difuso.

- `fire_whip`: látigo de fuego con la forma de la trayectoria reciente de la mano (o del pie).
- `hand_fire`: llamas que suben de las manos.
- `candle`: una sola llama que sale de las manos juntas y se achica de a poco (seg. 6-7,6).
- `floor_fire`: fuego a ras del piso: charco bajo la mano o el pie apoyado, o una raya que crece
  por donde barre (seg. 2, 5,2, 9,2-10,8).
- `fire_ring`: un aro de fuego que gira alrededor de la mano (seg. 8).
- `fire_skull`: calavera con melena de llamas sobre la cara (seg. 3,2).
- `avatar_mark`: la flecha de Avatar en la frente y los ojos encendidos (seg. 0 y 15).
- `body_blaze`: el cuerpo arde: llamas que trepan por brazos y piernas y alas de fuego (seg. 11,2).
- `fire_wall`: cierre: en el último tramo una pared de fuego sube desde el piso hasta llenar el
  cuadro, con la flecha y los ojos encendidos (seg. 14,4-16). Se usa en `always`: se cronometra
  sola con `runtime.frame_count` (`style.size` = segundos del cierre).
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.raster import fill_polygon, splat

FIREBEND = ("fire_whip", "hand_fire", "candle", "floor_fire", "fire_ring", "fire_skull", "avatar_mark", "body_blaze", "fire_wall")
MID = np.array([1.0, 0.66, 0.1], np.float32)
CORE = np.array([1.0, 0.97, 0.78], np.float32)


_WARM: dict[int, np.ndarray] = {}


def warm(layer, center: np.ndarray, radius: float, color: np.ndarray, alpha: float) -> None:
    """Resplandor radial que llega a cero en el borde (el de `splat` corta en ~8% y, grande, se
    veía como un recuadro naranja)."""
    r = int(min(max(radius, 2.0), 1600))
    kernel = _WARM.get(r)
    if kernel is None:
        axis = np.arange(-r, r + 1, dtype=np.float32) / r
        xx, yy = np.meshgrid(axis, axis)
        kernel = np.clip(1.0 - (xx * xx + yy * yy), 0.0, 1.0) ** 2
        _WARM[r] = kernel
    height, width = layer.shape[:2]
    x0, y0 = int(round(center[0])) - r, int(round(center[1])) - r
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = kernel.shape[1] - max(0, x0 + kernel.shape[1] - width), kernel.shape[0] - max(0, y0 + kernel.shape[0] - height)
    if sx0 >= sx1 or sy0 >= sy1:
        return
    dst = layer[y0 + sy0 : y0 + sy1, x0 + sx0 : x0 + sx1]
    weight = kernel[sy0:sy1, sx0:sx1] * np.float32(alpha)
    dst[..., :3] += np.asarray(color, np.float32) * weight[..., None]
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - weight)


def cel(layer, make, color, alpha: float, runtime=None, heat: float = 1.0, core: bool = True) -> None:
    """Fuego plano en tres capas: make(k) da el contorno con el grosor multiplicado por k. Con
    `runtime`, además un resplandor naranja amplio alrededor (el aire caliente). Sin `core`, sin
    la capa casi blanca (para fuego que llena medio cuadro: si no, el bloom lo quema en blanco)."""
    outer = np.asarray(color, np.float32)
    passes = ((1.0, outer, 0.85, 1.0), (0.62, MID, 0.95, 1.3), (0.3, CORE, 1.0, 1.7))
    for k, tint, a, gain in passes if core else passes[:2]:
        poly = make(k)
        if poly is not None and len(poly) >= 3:
            fill_polygon(layer, poly, tint, alpha * a, gain, feather=1.2)
            if k == 1.0 and runtime is not None and heat > 0:
                lo, hi = poly.min(axis=0), poly.max(axis=0)
                size = float(np.linalg.norm(hi - lo))
                mid = (lo + hi) / 2
                warm(layer, mid, size * 1.1, outer * 0.6, alpha * 0.3 * heat)


def _normals(spine: np.ndarray) -> np.ndarray:
    tangent = np.gradient(spine, axis=0)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    return normal / np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)


def ribbon(spine: np.ndarray, widths: np.ndarray, frame_index: int, tongues: float = 4.0, phase: float = 0.0):
    """make(k) de una cinta de fuego por `spine` (de la cola a la cabeza), con lenguas que
    corren por el borde exterior."""
    if len(spine) < 3:
        return lambda k: None
    normal = _normals(spine)
    t = np.linspace(0, 1, len(spine))
    flick = 1.0 + 0.7 * np.maximum(0.0, np.sin(t * tongues * TAU - frame_index * 0.9 + phase)) ** 3

    def make(k: float):
        w = widths * k
        upper = spine + normal * (w * flick)[:, None]
        lower = spine - normal * (w * (0.65 + 0.35 * flick))[:, None]
        return np.vstack([upper, lower[::-1]])

    return make


def teardrop(base: np.ndarray, up: np.ndarray, length: float, width: float, frame_index: int, seed: float = 0.0):
    """make(k) de una llama que sube desde `base` en la dirección `up` y se mece."""
    side = np.array([-up[1], up[0]])
    s = np.linspace(0, 1, 18)
    sway = np.sin(s * 3.0 - frame_index * 0.45 + seed) * 0.16 * length * s
    spine = base + np.outer(s * length, up) + np.outer(sway, side)
    widths = width * np.sin(np.pi * (0.12 + 0.88 * s)) ** 0.8 * (1 - s) ** 0.35 + 0.5
    return ribbon(spine, widths, frame_index, 2.0, seed)


def _floor(body, scale: float) -> float | None:
    feet = [p for p in (body.get(j) for j in ("left_ankle", "right_ankle", "left_heel", "right_heel", "left_foot_index", "right_foot_index")) if p is not None]
    return max(p[1] for p in feet) + 0.02 * scale if feet else None


def _wrist(body, event, scale) -> tuple[str, np.ndarray] | None:
    """La extremidad del evento (muñeca o tobillo) o, sin ella, la mano más rápida."""
    if event is not None:
        joint = event.target.split(":")[-1]
        if not joint.endswith(("_wrist", "_ankle")) and event.kind in ("left", "right"):
            joint = f"{event.kind}_wrist"
        if joint.endswith(("_wrist", "_ankle")) and body.get(joint) is not None:
            return joint, body.get(joint)
    best, speed = None, -1.0
    for name in ("left_wrist", "right_wrist"):
        point = body.get(name)
        if point is None:
            continue
        vel = body.points.get(f"vel:{body.prefix}{name}")
        v = float(np.linalg.norm(vel)) if vel is not None else 0.0
        if v > speed:
            best, speed = (name, point), v
    return best


# ----- látigo, llamas en las manos, vela -----


TWO_HANDED = ("arms_open", "arms_up", "jump", "landing", "spin_body")
WHIP_SCALE = 2.0


def _fire_whip(body, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    if event is not None and (event.kind == "both" or event.name in TWO_HANDED):
        limbs = [(n, body.get(n)) for n in ("left_wrist", "right_wrist") if body.get(n) is not None]
    else:
        found = _wrist(body, event, scale)
        limbs = [found] if found is not None else []
    for name, point in limbs:
        st = _activation(runtime, event, f"whip:{name}", body)
        trail = st.setdefault("trail", [])
        trail.append(point.copy())
        del trail[:-16]
        if len(trail) < 3:
            continue
        spine = np.array(trail)
        if float(np.linalg.norm(spine[-1] - spine[0])) < 0.25 * scale:  # casi quieta: sin látigo
            continue
        # Exagerado como en la referencia: el látigo dobla el recorrido real (desde la mano hacia
        # atrás) y la llama se adelanta a la mano, como si la lanzara.
        spine = spine[-1] + (spine - spine[-1]) * WHIP_SCALE
        ahead = spine[-1] - spine[-3]
        spine = np.vstack([spine, spine[-1] + ahead * 0.8])
        q = np.linspace(0, 1, len(spine))
        widths = (0.04 + 0.4 * np.sin(np.pi * np.clip(q * 1.05, 0, 1)) ** 0.7 * q ** 0.8) * scale  # medialuna gruesa
        cel(layer, ribbon(spine, widths, frame_index, 3.0), color, alpha, runtime)
        splat(layer, float(point[0]), float(point[1]), 0.12 * scale, CORE * 1.4, alpha * 0.6, runtime.kernels)
    return []


def _hand_fire(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    up = -down
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.2))
    sides = [event.kind] if event is not None and event.kind in ("left", "right") else ["left", "right"]
    for k, side in enumerate(sides):
        wrist = body.get(f"{side}_wrist")
        if wrist is None:
            continue
        cel(layer, teardrop(wrist, up, 0.85 * scale * grow, 0.2 * scale, frame_index, k * 1.7), color, alpha, runtime)
    return []


def _candle(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    up = -down
    wrists = [body.get("left_wrist"), body.get("right_wrist")]
    if any(w is None for w in wrists):
        return []
    base = (wrists[0] + wrists[1]) / 2
    u = _phase(runtime, event)
    size = _ease(_seg(u, 0.0, 0.15)) * (1.0 - 0.65 * _seg(u, 0.15, 1.0))  # nace grande y se achica
    cel(layer, teardrop(base, up, 1.1 * scale * size, 0.2 * scale * size + 1, frame_index), color, alpha, runtime)
    return []


# ----- piso y aro -----


def _floor_fire(body, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    floor = _floor(body, scale)
    if floor is None:
        return []
    joints = [p for p in (body.get(j) for j in ("left_wrist", "right_wrist", "left_ankle", "right_ankle")) if p is not None]
    if not joints:
        return []
    low = max(joints, key=lambda p: p[1])  # la extremidad más cerca del piso
    st = _activation(runtime, event, "floor", body)
    st["x0"] = min(st.get("x0", low[0]), low[0])
    st["x1"] = max(st.get("x1", low[0]), low[0])
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.2))
    x0, x1 = st["x0"] - 0.35 * scale, st["x1"] + 0.35 * scale
    xs = np.linspace(x0, x1, 60)
    edge = np.minimum(np.linspace(0, 1, 60) * 3, 1) ** 0.7 * np.minimum(np.linspace(1, 0, 60) * 3, 1) ** 0.7
    w = 0.16 * scale
    lick = 0.35 + 0.65 * np.clip(
        0.55 * np.sin(xs / w - frame_index * 0.55) + 0.35 * np.sin(xs / (w * 0.43) + frame_index * 0.8 + 1.3) + 0.25 * np.sin(xs / (w * 2.3) - frame_index * 0.3), -1, 1) ** 2
    lean = np.sin(xs / (w * 1.7) + frame_index * 0.4) * 0.12 * scale  # las lenguas se mecen de lado

    def make(k: float):
        h = 0.42 * scale * grow * edge * lick * k
        top = np.stack([xs + lean * (h / max(h.max(), 1e-6)), floor - h], axis=1)
        return np.vstack([top, [[x1, floor], [x0, floor]]])

    cel(layer, make, color, alpha, runtime, 1.4)
    return []


def _fire_ring(body, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    found = _wrist(body, event, scale)
    if found is None:
        return []
    _, point = found
    u = _phase(runtime, event)
    r = 0.38 * scale * _ease(_seg(u, 0.0, 0.25))
    a0 = frame_index * 0.35
    a = np.linspace(a0, a0 + TAU * 0.8, 36)  # un aro abierto que gira
    spine = point + np.stack([np.cos(a), np.sin(a)], axis=1) * r
    widths = 0.06 * scale * np.sin(np.linspace(0.05, np.pi - 0.05, 36)) + 0.5
    cel(layer, ribbon(spine, widths, frame_index, 5.0), color, alpha, runtime)
    return []


# ----- la cara: calavera y estado Avatar -----


def _face(body, frame, scale):
    center, across, down = frame
    nose = body.get("nose")
    if nose is None:
        return None
    ears = [body.get("left_ear"), body.get("right_ear")]
    width = float(np.linalg.norm(ears[0] - ears[1])) if all(e is not None for e in ears) else 0.0
    return nose, max(width * 0.75, 0.28 * scale), -down, across


def _glowing_eyes(body, layer, r, alpha, runtime) -> None:
    for name in ("left_eye", "right_eye"):
        eye = body.get(name)
        if eye is not None:
            splat(layer, float(eye[0]), float(eye[1]), 0.16 * r, WHITE * 2.2, alpha, runtime.kernels)


def _avatar_mark(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = _face(body, frame, scale)
    if face is None:
        return []
    nose, r, up, across = face
    forehead = nose + up * 0.55 * r
    top = nose + up * 1.25 * r
    # La flecha de Aang: una banda que baja por la cabeza y termina en punta sobre la frente.
    shaft = np.array([top + across * 0.07 * r, forehead + up * 0.18 * r + across * 0.07 * r, forehead + up * 0.18 * r - across * 0.07 * r, top - across * 0.07 * r])
    head = np.array([forehead + up * 0.2 * r + across * 0.2 * r, forehead, forehead + up * 0.2 * r - across * 0.2 * r])
    fill_polygon(layer, shaft, CORE, alpha, 1.6, feather=1.0)
    fill_polygon(layer, head, CORE, alpha, 1.6, feather=1.0)
    warm(layer, forehead, 1.6 * r, np.asarray(color, np.float32), alpha * 0.45)
    _glowing_eyes(body, layer, r, alpha, runtime)
    return [shaft, head]


def _fire_skull(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = _face(body, frame, scale)
    if face is None:
        return []
    nose, r, up, across = face
    t = np.linspace(0, TAU, 32)
    c = nose + up * 0.15 * r
    skull = c + np.outer(np.cos(t) * 0.95 * r, across) + np.outer(np.sin(t) * 1.05 * r, up)
    sockets = [nose + up * 0.35 * r + across * s * 0.38 * r for s in (-1, 1)]
    lines = [skull]
    for socket in sockets:
        hole = socket + np.outer(np.cos(t) * 0.24 * r, across) + np.outer(np.sin(t) * 0.2 * r, up)
        lines.append(hole)
        splat(layer, float(socket[0]), float(socket[1]), 0.1 * r, CORE * 2.0, alpha, runtime.kernels)
    lines.append(np.array([nose + across * 0.1 * r, nose + up * 0.12 * r, nose - across * 0.1 * r, nose + across * 0.1 * r]))
    jaw = nose - up * 0.45 * r
    lines.append(np.array([jaw - across * 0.45 * r, jaw + across * 0.45 * r]))
    for k in np.linspace(-0.36, 0.36, 6):  # dientes
        lines.append(np.array([jaw + across * k * r + up * 0.12 * r, jaw + across * k * r - up * 0.12 * r]))
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.2))
    for k, tilt in enumerate((-0.5, 0.0, 0.5)):  # melena de llamas
        d = up + across * tilt
        d = d / float(np.linalg.norm(d))
        base = c + up * 0.85 * r + across * tilt * 0.6 * r
        cel(layer, teardrop(base, d, (1.0 - 0.25 * abs(tilt)) * 1.4 * r * grow, 0.35 * r, frame_index, k), color, alpha)
    return lines


# ----- el cuerpo arde, y el cierre -----


def _body_blaze(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    up = np.array([0.0, -1.0])  # el fuego sube hacia arriba de la imagen, sin importar la pose
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.3))
    chains = [(f"{s}_{a}", f"{s}_{b}", f"{s}_{c}") for s in ("left", "right") for a, b, c in (("shoulder", "elbow", "wrist"), ("hip", "knee", "ankle"))]
    k = 0
    for names in chains:
        pts = [body.get(n) for n in names]
        if any(p is None for p in pts):
            continue
        for a_, b_ in ((pts[0], pts[1]), (pts[1], pts[2])):
            for q in (0.2, 0.6, 0.95):  # tres llamas por hueso, de distinto tamaño
                k += 1
                base = a_ + (b_ - a_) * q
                size = (0.45 + 0.35 * np.sin(k * 2.3) ** 2) * scale * grow
                cel(layer, teardrop(base, up, size, 0.13 * scale, frame_index, k * 0.9), color, alpha, runtime, 0.5)
    for s in (-1, 1):  # alas de fuego sobre los hombros
        shoulder = body.get("left_shoulder" if (s < 0) == (across[0] > 0) else "right_shoulder")
        if shoulder is None:
            continue
        d = up + np.array([s * 0.9, 0.0])
        cel(layer, teardrop(shoulder, d / float(np.linalg.norm(d)), 1.5 * scale * grow, 0.35 * scale, frame_index, s), color, alpha, runtime)
    return []


def _fire_wall(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    st = runtime.swoosh.setdefault("_firewall", {})
    if st.get("frame") == frame_index:  # una sola pared por cuadro, aunque haya dos personas
        return []
    st["frame"] = frame_index
    total = runtime.frame_count
    length = int(max(runtime.effect.style.size, 0.5) * runtime.fps)
    if total <= 0 or frame_index < total - length:
        return []
    s = _ease((frame_index - (total - length)) / max(length - 1, 1))
    height, width = layer.shape[:2]
    rise = height * (0.12 + 0.55 * s)
    base_y = height + 2
    band = np.array([[-0.05 * width, base_y - rise * 0.35], [1.05 * width, base_y - rise * 0.35], [1.05 * width, base_y + 2], [-0.05 * width, base_y + 2]])
    alpha *= 0.75  # tres capas a lo ancho del cuadro, más el bloom: sin bajar, se quema en blanco
    cel(layer, lambda k: band if k == 1.0 else band + np.array([0.0, rise * 0.35 * (1 - k)]), color, alpha, core=False)
    rng = np.random.default_rng(18)
    for j in range(8):  # llamaradas: cada una sube, se mece y se enrosca
        x = width * (j + rng.uniform(-0.3, 0.3)) / 7
        tall = rise * rng.uniform(0.55, 1.0) * (0.9 + 0.15 * np.sin(frame_index * 0.3 + j))
        lean = np.array([np.sin(frame_index * 0.12 + j * 1.7) * 0.35, -1.0])
        # Llamaradas anchas y redondas (anchas como 4/10 de su alto), no puntas finas.
        cel(layer, teardrop(np.array([x, base_y - rise * 0.25]), lean / float(np.linalg.norm(lean)), tall, tall * rng.uniform(0.32, 0.45), frame_index, j * 1.3), color, alpha, core=False)
    return _avatar_mark(body, frame, scale, frame_index, runtime, layer, color, alpha * min(s * 3, 1.0), event)


def firebend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    if shape == "fire_whip":
        return _fire_whip(body, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "hand_fire":
        return _hand_fire(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "candle":
        return _candle(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "floor_fire":
        return _floor_fire(body, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_ring":
        return _fire_ring(body, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_skull":
        return _fire_skull(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "avatar_mark":
        return _avatar_mark(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "body_blaze":
        return _body_blaze(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_wall":
        return _fire_wall(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
