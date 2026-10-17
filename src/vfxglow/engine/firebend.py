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
- la calavera, el ave, el dragón y la cara que echa fuego están en engine/fire_creatures.py.
- `avatar_mark`: la flecha de Avatar en la frente y los ojos encendidos (seg. 0 y 15).
- `body_blaze`: el cuerpo arde: llamas que trepan por brazos y piernas y alas de fuego (seg. 11,2).
- `fire_wall`: cierre: en el último tramo una pared de fuego sube desde el piso hasta llenar el
  cuadro, con la flecha y los ojos encendidos (seg. 14,4-16). Se usa en `always`: se cronometra
  sola con `runtime.frame_count` (`style.size` = segundos del cierre).
"""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.raster import fill_polygon, splat

FIREBEND = ("fire_whip", "hand_fire", "candle", "floor_fire", "fire_ring", "avatar_mark", "body_blaze", "fire_wall", "fire_light")
MID = np.array([1.0, 0.66, 0.1], np.float32)
# La luz que el fuego echa sobre el escenario: naranja profundo (con más verde, al sumarse sobre el
# cuadro y el bloom, se iba al amarillo).
GLOW = np.array([1.0, 0.27, 0.0], np.float32)
CORE = np.array([1.0, 0.97, 0.78], np.float32)


_WARM: dict[int, np.ndarray] = {}


def warm(layer, center: np.ndarray, radius: float, color: np.ndarray, alpha: float) -> None:
    """Resplandor radial que llega a cero en el borde (el de `splat` corta en ~8% y, grande, se
    veía como un recuadro naranja)."""
    r = int(min(max(radius, 2.0), 1600))
    r = max(8, r // 24 * 24) if r > 32 else r  # radios redondeados: pocos núcleos en memoria
    kernel = _WARM.get(r)
    if kernel is None:
        if len(_WARM) > 48:
            _WARM.clear()
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


# ----- el fuego como campo (metaballs) -----
#
# Las llamas no se pintan como polígonos: cada una suma a un campo suave (más alto hacia su
# centro: borde, cuerpo y núcleo). Al final del efecto, por cuadro (flush_fire), el campo se
# desenfoca, se deforma con ruido que sube y se corta con tres umbrales: naranja, amarillo y núcleo
# casi blanco. Así los bordes salen como líquido viscoso, dos llamas que se tocan se funden, el
# borde se corroe y lo que se apaga se encoge en vez de volverse transparente.

_FIELDS: dict[int, dict] = {}
# Luces de fuego del cuadro (para fire_light, que tiñe el plano): las del cuadro anterior y las de este.
_LIGHTS: dict = {"frame": -1, "now": [], "prev": []}
LEVELS = ((0.5, 0.62), (1.4, 1.55), (2.15, 2.3))  # umbrales (borde, cuerpo, núcleo) con su rampa


def note_frame(frame_index: int) -> None:
    """El primer efecto de fuego de cada cuadro rota la lista de luces."""
    if frame_index != _LIGHTS["frame"]:
        if frame_index < _LIGHTS["frame"]:  # otro video o se volvió atrás
            _LIGHTS["now"] = []
        _LIGHTS["prev"], _LIGHTS["now"], _LIGHTS["frame"] = _LIGHTS["now"], [], frame_index


def cel(layer, make, color, alpha: float, runtime=None, heat: float = 1.0, core: bool = True) -> None:
    """Suma una llama al campo de fuego del efecto: make(k) da el contorno con el grosor
    multiplicado por k (1 = borde naranja, 0,62 = cuerpo, 0,3 = núcleo). Con `runtime`, además un
    resplandor naranja tenue alrededor y la llama cuenta como luz para fire_light."""
    if alpha <= 0:
        return
    height, width = layer.shape[:2]
    entry = _FIELDS.get(id(layer))
    if entry is None:
        entry = _FIELDS[id(layer)] = {"field": np.zeros((height, width), np.float32), "color": np.asarray(color, np.float32), "alpha": 0.0}
    entry["alpha"] = max(entry["alpha"], float(alpha))
    for k in (1.0, 0.62, 0.3) if core else (1.0, 0.62):
        poly = make(k)
        if poly is None or len(poly) < 3:
            continue
        mask = np.zeros((height, width), np.uint8)
        cv2.fillPoly(mask, [np.round(poly).astype(np.int32)], 255, lineType=cv2.LINE_AA)
        entry["field"] += mask.astype(np.float32) * np.float32(min(alpha, 1.0) / 255.0)
        if k == 1.0 and runtime is not None and heat > 0:
            lo, hi = poly.min(axis=0), poly.max(axis=0)
            size = float(np.linalg.norm(hi - lo))
            mid = (lo + hi) / 2
            warm(layer, mid, max(size * 2.4, 0.45 * height), GLOW * 0.55, alpha * 0.16 * heat)  # ancha pero transparente
            _LIGHTS["now"].append((mid, size, float(alpha) * heat))


_NOISE: dict = {}


def _noise(height: int, width: int, frame_index: int, seed: int) -> np.ndarray:
    """Ruido suave en [-1, 1] del tamaño del cuadro que sube con el tiempo (el fuego asciende)."""
    key = (height, width, seed)
    tex = _NOISE.get(key)
    if tex is None:
        rng = np.random.default_rng(seed)
        tall = height * 2
        tex = np.zeros((tall, width), np.float32)
        for cell, weight in ((max(height // 14, 8), 0.65), (max(height // 40, 4), 0.35)):  # dos octavas
            small = rng.uniform(-1, 1, (tall // cell + 2, width // cell + 2)).astype(np.float32)
            tex += cv2.resize(small, (width, tall), interpolation=cv2.INTER_CUBIC) * weight
        _NOISE[key] = tex
    shift = int(frame_index * height * 0.012) % height  # sube ~1,2% del cuadro por fotograma
    return tex[height - shift : 2 * height - shift]


def flush_fire(layer, frame_index: int) -> None:
    """Convierte el campo de fuego acumulado del efecto en las tres capas planas."""
    entry = _FIELDS.pop(id(layer), None)
    if entry is None:
        return
    field = entry["field"]
    ys, xs = np.nonzero(field > 0.02)
    if len(xs) == 0:
        return
    height, width = field.shape
    pad = int(0.06 * height)
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, width)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, height)
    crop = cv2.GaussianBlur(field[y0:y1, x0:x1], (0, 0), max(0.006 * height, 1.0))
    # Ruido que sube: deforma el borde (lenguas caóticas, no el patrón de un seno) y lo corroe.
    nx = _noise(height, width, frame_index, 7)[y0:y1, x0:x1]
    ny = _noise(height, width, frame_index, 11)[y0:y1, x0:x1]
    amp = 0.014 * height
    gx, gy = np.meshgrid(np.arange(x1 - x0, dtype=np.float32), np.arange(y1 - y0, dtype=np.float32))
    crop = cv2.remap(crop, gx + nx * amp, gy + ny * amp + np.abs(ny) * amp * 0.6, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    crop = crop - _noise(height, width, frame_index, 23)[y0:y1, x0:x1] * 0.22  # huecos y bordes comidos

    def step(level):
        lo, hi = level
        x = np.clip((crop - lo) / (hi - lo), 0.0, 1.0)
        return x * x * (3 - 2 * x)

    outer, body, core = (step(level) for level in LEVELS)
    color = entry["color"]
    rgb = color[None, None, :] * (outer - body)[..., None] + MID * 1.3 * (body - core)[..., None] + CORE * 1.7 * core[..., None]
    a = np.float32(min(entry["alpha"], 1.0))
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += rgb * a
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - outer * a)


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


# ----- lo que tienen todos los fuegos: escamas, tramos cortados y el borde del cuerpo iluminado -----


def pieces(spine: np.ndarray, widths: np.ndarray, seed: int, gap: float = 0.05) -> list[tuple[np.ndarray, np.ndarray]]:
    """La cinta partida en 2-3 tramos con huecos (el fuego de la referencia se corta), cada uno
    con su propio grosor que se afina en las puntas del corte."""
    rng = np.random.default_rng(seed)
    cuts = sorted(rng.uniform(0.25, 0.75, size=int(rng.integers(1, 3))))
    n = len(spine)
    out, start = [], 0
    for c in [*cuts, 1.0 + gap]:
        end = min(int((c - gap / 2) * n), n)
        if end - start >= 3:
            seg_w = widths[start:end] * np.sin(np.linspace(0.15, np.pi - 0.15, end - start)) ** 0.25
            out.append((spine[start:end], seg_w))
        start = int((c + gap / 2) * n)
    return out


def shed(layer, spine: np.ndarray, widths: np.ndarray, st: dict, frame_index: int, scale: float, color, alpha: float, rate: float = 1.0) -> None:
    """Escamas de fuego que se desprenden del borde de la llama: medialunas que salen, giran y
    se apagan en ~10 cuadros."""
    flakes = st.setdefault("flakes", [])
    rng = np.random.default_rng(frame_index * 31 + len(flakes))
    if len(spine) >= 3 and rng.random() < 0.8 * rate:
        normal = _normals(spine)
        for _ in range(1 + int(rng.random() < 0.5 * rate)):
            i = int(rng.integers(len(spine) // 3, len(spine)))
            side = rng.choice([-1.0, 1.0])
            pos = spine[i] + normal[i] * widths[i] * side
            vel = normal[i] * side * rng.uniform(0.02, 0.05) * scale + np.array([0.0, -0.015 * scale])
            flakes.append([pos.copy(), vel, frame_index, rng.uniform(0.04, 0.08) * scale, rng.uniform(0, TAU)])
    keep = []
    for flake in flakes:
        pos, vel, born, size, spin = flake
        age = frame_index - born
        if age > 10:
            continue
        keep.append(flake)
        at = pos + vel * age
        fade = 1.0 - age / 10.0
        a = spin + age * 0.4
        arc = np.linspace(a, a + 2.4, 10)  # una medialuna: dos arcos de distinto radio
        outer = at + np.stack([np.cos(arc), np.sin(arc)], axis=1) * size * fade
        inner = at + np.stack([np.cos(arc[::-1]), np.sin(arc[::-1])], axis=1) * size * fade * 0.6 + np.array([np.cos(a + 1.2), np.sin(a + 1.2)]) * size * 0.25
        crescent = np.vstack([outer, inner])
        fill_polygon(layer, crescent, MID, alpha * fade, 1.4, feather=0.8)
    st["flakes"] = keep


def rim(layer, runtime, sources: list[np.ndarray], scale: float, color, alpha: float, reach: float = 1.3) -> None:
    """El borde del cuerpo cercano al fuego, iluminado con una línea muy fina que se apaga con la
    distancia (sobre la silueta real del segmentador)."""
    outlines = getattr(runtime, "silhouettes", None) or []
    if not outlines or not sources:
        return
    src = np.array(sources, dtype=np.float64)
    radius = reach * scale
    height, width = layer.shape[:2]
    glow = np.zeros((height, width), np.float32)
    for outline in outlines:
        d = np.min(np.linalg.norm(outline[:, None, :] - src[None, :, :], axis=2), axis=1)
        weight = np.clip(1.0 - d / radius, 0.0, 1.0) ** 1.5
        pts = np.round(outline).astype(np.int32)
        for i in range(len(pts)):
            w = (weight[i] + weight[(i + 1) % len(pts)]) / 2
            if w > 0.05:
                cv2.line(glow, tuple(pts[i]), tuple(pts[(i + 1) % len(pts)]), float(w), 1, cv2.LINE_AA)
    if glow.max() <= 0:
        return
    glow *= np.float32(alpha)
    tint = np.asarray(color, np.float32) * 0.5 + MID * 0.5
    layer[..., :3] += tint * 1.6 * glow[..., None]
    layer[..., 3] = 1.0 - (1.0 - layer[..., 3]) * (1.0 - glow)


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
        # Más curvo que el recorrido real: se arquea hacia el lado en que gira el golpe.
        chord = spine[-1] - spine[0]
        length = float(np.linalg.norm(chord))
        side = np.array([-chord[1], chord[0]]) / max(length, 1e-6)
        turn = float(np.sign(np.dot(spine[len(spine) // 2] - (spine[0] + spine[-1]) / 2, side)) or 1.0)
        spine = spine + np.outer(np.sin(np.pi * q) * 0.22 * length * turn, side)
        smooth = np.array([spine[max(i - 1, 0)] * 0.25 + spine[i] * 0.5 + spine[min(i + 1, len(spine) - 1)] * 0.25 for i in range(len(spine))])
        widths = (0.04 + 0.4 * np.sin(np.pi * np.clip(q * 1.05, 0, 1)) ** 0.7 * q ** 0.8) * scale  # medialuna gruesa
        seed = (event.start_frame if event is not None else 0) * 7 + len(name)
        for part, part_w in pieces(smooth, widths, seed):
            cel(layer, ribbon(part, part_w, frame_index, 3.0), color, alpha, runtime)
        shed(layer, smooth, widths, st, frame_index, scale, color, alpha)
        rim(layer, runtime, [point, smooth[len(smooth) // 2]], scale, color, alpha)
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
        st = _activation(runtime, event, f"hand:{side}", body)
        flame_spine = np.array([wrist + up * 0.85 * scale * grow * s for s in np.linspace(0, 1, 8)])
        shed(layer, flame_spine, np.full(8, 0.12 * scale), st, frame_index, scale, color, alpha, 0.6)
        rim(layer, runtime, [wrist], scale, color, alpha, 1.0)
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


# Luz del fuego sobre el plano (se mezcla multiplicando, antes del fuego): cerca de las llamas
# sube el rojo y baja el azul conservando la textura (la ropa y el piso se tiñen de naranja con
# sus arrugas y sombras); lejos, con mucho fuego en pantalla, el cuadro se oscurece un poco para
# que el fuego resalte (lo que el animador hace al subexponer el plano).
LIGHT_TINT = np.array([1.55, 0.82, 0.42], np.float32)
LIGHT_DARK = 0.74


def _fire_light(runtime, layer, frame_index: int, alpha: float) -> list:
    st = runtime.swoosh.setdefault("_firelight", {})
    if st.get("frame") == frame_index:  # una vez por cuadro aunque haya dos personas
        return []
    st["frame"] = frame_index
    note_frame(frame_index)
    lights = _LIGHTS["prev"] + _LIGHTS["now"]
    if not lights:
        return []
    height, width = layer.shape[:2]
    step = 8  # la luz es suave: se calcula a 1/8 y se agranda
    gy, gx = np.mgrid[0:height:step, 0:width:step].astype(np.float32)
    light = np.zeros(gx.shape, np.float32)
    amount = 0.0
    for mid, size, a in lights:
        r = max(size * 2.0, 0.5 * height)
        d2 = ((gx - mid[0]) ** 2 + (gy - mid[1]) ** 2) / (r * r)
        light += np.clip(1.0 - d2, 0.0, 1.0) ** 2 * np.float32(a)
        amount += size * a
    light = cv2.resize(np.clip(light, 0.0, 1.0), (width, height), interpolation=cv2.INTER_LINEAR)
    cover = np.float32(min(amount / (0.8 * height), 1.0) * 0.6 * alpha)
    straight = LIGHT_DARK * (1.0 - light)[..., None] + LIGHT_TINT * light[..., None]
    layer[..., :3] = straight * cover
    layer[..., 3] = cover
    return []


def firebend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    note_frame(frame_index)
    if shape == "fire_light":
        return _fire_light(runtime, layer, frame_index, alpha)
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
    if shape == "avatar_mark":
        return _avatar_mark(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "body_blaze":
        return _body_blaze(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "fire_wall":
        return _fire_wall(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
