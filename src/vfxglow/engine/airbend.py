"""Aire control (estilo Avatar): viento energético translúcido.

El aire se siente ligero, veloz y casi invisible, salvo por lo que le hace al entorno: menos
brillante que el fuego y menos sólido que el agua, y siempre siguiendo el movimiento. Se arma con
tres componentes:
- cintas: muy finas y en punta, de blanco (la cabeza) a cian pálido (la cola), que nacen, se estiran
  y se apagan en pocos cuadros siguiendo el recorrido de la extremidad;
- partículas: motas que arrastra la corriente y se pierden;
- distorsión: `air_refract` (blend `refract`) dobla el fondo solo donde pasó el viento, poco.
La luz sale del núcleo blanco y del borde, no de iluminar todo el efecto.

Figuras:
- `air_slash`: cuchilla de viento con la forma del golpe rápido, que sale despedida y se apaga.
- `air_dash`: corrientes que siguen a las extremidades rápidas (volteretas, saltos, estocadas).
- `air_vortex`: corrientes que giran alrededor del cuerpo, unas por delante y otras por detrás.
- `air_burst`: golpe de presión: un anillo fino que se abre desde el pie o el puño y empuja motas.
- `air_refract`: la distorsión del aire del mismo cuadro (va en su propio efecto).
"""

from __future__ import annotations

import weakref

import cv2
import numpy as np

from vfxglow.engine.critters import TAU, _activation, _ease, _phase, _seg

AIRBEND = ("air_slash", "air_dash", "air_vortex", "air_burst", "air_refract")

WHITE = np.array([1.0, 1.0, 1.0], np.float32)  # núcleo y destellos
PALE = np.array([0.72, 0.94, 1.0], np.float32)  # las corrientes
SKY = np.array([0.45, 0.72, 1.0], np.float32)  # bordes y profundidad
LAVENDER = np.array([0.82, 0.76, 1.0], np.float32)  # acento mínimo (las motas)

TRAIL = 9  # cuadros del recorrido que forman una corriente (el aire se apaga rápido)
STRETCH = 1.7  # la corriente, más larga que el recorrido real
SHARP_TURN = np.radians(95)  # un giro así de brusco corta la corriente (no hace rulos)

_FIELDS: dict = {}
_LAST: dict = {}  # la máscara del aire del cuadro, para air_refract


def _unit(scale: float, layer) -> float:
    return max(float(scale), 0.07 * layer.shape[0])


def _entry(layer) -> dict:
    entry = _FIELDS.get(id(layer))
    if entry is not None and entry["ref"]() is not layer:
        entry = None
    if entry is None:
        height, width = layer.shape[:2]
        entry = _FIELDS[id(layer)] = {"body": np.zeros((height, width), np.float32), "core": np.zeros((height, width), np.float32), "motes": [], "ref": weakref.ref(layer)}
    return entry


def _chaikin(points: np.ndarray, passes: int = 2) -> np.ndarray:
    pts = points.astype(np.float64)
    for _ in range(passes):
        if len(pts) < 3:
            break
        q, r = pts[:-1] * 0.75 + pts[1:] * 0.25, pts[:-1] * 0.25 + pts[1:] * 0.75
        pts = np.vstack([pts[:1], np.stack([q, r], axis=1).reshape(-1, 2), pts[-1:]])
    return pts


def _normals(spine: np.ndarray) -> np.ndarray:
    d = np.gradient(spine, axis=0)
    d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
    return np.stack([-d[:, 1], d[:, 0]], axis=1)


def streak(layer, spine: np.ndarray, half: float, alpha: float, belly: float = 0.55) -> None:
    """Una corriente por `spine` (de la cola a la cabeza): en punta en los dos extremos, más ancha
    en `belly`, tenue en la cola y con núcleo blanco hacia la cabeza."""
    if len(spine) < 3 or alpha <= 0.01 or half < 0.3:
        return
    entry = _entry(layer)
    n = _normals(spine)
    q = np.linspace(0.0, 1.0, len(spine))
    shape = np.clip(np.where(q < belly, q / belly, (1 - q) / (1 - belly)), 0.0, 1.0) ** 0.7
    width = half * shape + 0.4
    left, right = spine + n * width[:, None], spine - n * width[:, None]
    core_w = half * 0.3 * shape
    cl, cr = spine + n * core_w[:, None], spine - n * core_w[:, None]
    for i in range(len(spine) - 1):
        value = alpha * (0.15 + 0.85 * q[i + 1])  # la cola, casi invisible
        quad = np.array([left[i], left[i + 1], right[i + 1], right[i]])
        _max_poly(entry["body"], quad, value)
        if q[i] > 0.35:
            _max_poly(entry["core"], np.array([cl[i], cl[i + 1], cr[i + 1], cr[i]]), value)


def _max_poly(target: np.ndarray, poly: np.ndarray, value: float) -> None:
    lo = np.floor(poly.min(axis=0)).astype(int) - 2
    hi = np.ceil(poly.max(axis=0)).astype(int) + 2
    x0, y0 = max(lo[0], 0), max(lo[1], 0)
    x1, y1 = min(hi[0], target.shape[1]), min(hi[1], target.shape[0])
    if x0 >= x1 or y0 >= y1:
        return
    patch = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(patch, [np.round(poly - [x0, y0]).astype(np.int32)], 255, lineType=cv2.LINE_AA)
    np.maximum(target[y0:y1, x0:x1], patch.astype(np.float32) / 255.0 * value, out=target[y0:y1, x0:x1])


def flush_air(layer, frame_index: int) -> None:
    """Pinta el aire acumulado: corrientes cian pálido con núcleo blanco, un borde celeste corto y
    las motas. Translúcido: nunca tapa del todo lo de atrás."""
    entry = _FIELDS.pop(id(layer), None)
    if entry is None or entry["ref"]() is not layer:
        return
    body, core = entry["body"], entry["core"]
    height = layer.shape[0]
    for pos, size, life in entry["motes"]:
        cv2.circle(body, (int(pos[0]), int(pos[1])), max(int(round(size)), 1), float(0.7 * life), -1, lineType=cv2.LINE_AA)
    ys, xs = np.nonzero(body > 0.01)
    if len(xs) == 0:
        return
    pad = int(0.03 * height)
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, layer.shape[1])
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, height)
    b, c = body[y0:y1, x0:x1], core[y0:y1, x0:x1]
    edge = np.clip(cv2.GaussianBlur(b, (0, 0), max(0.004 * height, 1.0)) - b, 0.0, 1.0)
    rgb = PALE * (b * 0.55)[..., None] + WHITE * (c * 0.9)[..., None] + SKY * (edge * 0.8)[..., None]
    cover = np.clip(b * 0.5 + c * 0.35 + edge * 0.3, 0.0, 0.85)
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += rgb
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - cover)
    full = np.zeros(body.shape, np.float32)
    full[y0:y1, x0:x1] = b
    _LAST["frame"], _LAST["mask"] = frame_index, full


def _refract(layer, frame_index: int, strength: float) -> None:
    """El aire dobla un poco el fondo donde pasa (como el calor): R y G llevan el desplazamiento y A
    la máscara (blend `refract`)."""
    if _LAST.get("frame") != frame_index or _LAST["mask"].shape != layer.shape[:2]:
        return
    mask = cv2.GaussianBlur(_LAST["mask"], (0, 0), max(0.008 * layer.shape[0], 1.0))
    gy, gx = np.gradient(mask)
    norm = max(float(np.abs(gx).max()), float(np.abs(gy).max()), 1e-6)
    reach = strength * layer.shape[0]
    layer[..., 0] = gx / norm * reach
    layer[..., 1] = gy / norm * reach
    layer[..., 3] = np.maximum(layer[..., 3], np.clip(mask * 1.5, 0.0, 0.8))


# ----- recorridos y motas -----


def _clean_tail(path: np.ndarray) -> np.ndarray:
    """El recorrido desde la extremidad hacia atrás hasta el primer giro brusco (sin rulos)."""
    if len(path) < 3:
        return path
    d = np.diff(path, axis=0)
    for i in range(len(d) - 1, 0, -1):
        a, b = d[i], d[i - 1]
        na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
        if na > 1 and nb > 1 and float(np.arccos(np.clip(np.dot(a, b) / (na * nb), -1, 1))) > SHARP_TURN:
            return path[i:]
    return path


def _limb_path(st: dict, key: str, point: np.ndarray, unit: float) -> np.ndarray:
    hist = st.setdefault(key, [])
    if hist and float(np.linalg.norm(point - hist[-1])) > 2.0 * unit:
        hist.clear()  # salto del detector
    hist.append(np.asarray(point, np.float64).copy())
    del hist[:-TRAIL]
    return np.array(hist)


def _motes(st: dict, spine: np.ndarray, frame_index: int, unit: float, count: int) -> None:
    """Motas que suelta la corriente: siguen su dirección, se frenan, se mecen y se apagan."""
    motes = st.setdefault("motes", [])
    rng = np.random.default_rng(frame_index * 13 + len(motes))
    if len(spine) >= 3:
        flow = spine[-1] - spine[-3]
        for _ in range(count):
            k = int(rng.integers(len(spine) // 2, len(spine)))
            vel = flow * rng.uniform(0.2, 0.5) + rng.normal(0, 0.03 * unit, 2)
            motes.append([spine[k] + rng.normal(0, 0.1 * unit, 2), vel, rng.uniform(0.012, 0.03) * unit, 1.0])
    keep = []
    for pos, vel, size, life in motes:
        vel = vel * 0.86 + np.array([np.sin(pos[1] * 0.05 + frame_index * 0.3), np.cos(pos[0] * 0.05)]) * 0.02 * unit
        life -= 0.09
        if life > 0:
            keep.append([pos + vel, vel, size, life])
    st["motes"] = keep[-60:]


def _draw_motes(layer, st: dict) -> None:
    _entry(layer)["motes"] += [(pos, size, life) for pos, _vel, size, life in st.get("motes", [])]


def _speed(body, name: str, unit: float) -> float:
    vel = body.get(f"vel:{name}")
    return float(np.linalg.norm(vel)) / max(unit, 1.0) if vel is not None else 0.0


# ----- las figuras -----


def _air_dash(body, scale, frame_index, runtime, layer, alpha, event, limbs=("left_wrist", "right_wrist", "left_ankle", "right_ankle")) -> None:
    st = _activation(runtime, event, "air:dash", body)
    unit = _unit(scale, layer)
    for k, name in enumerate(limbs):
        point = body.get(name)
        if point is None:
            continue
        path = _clean_tail(_limb_path(st, name, point, unit))
        if len(path) < 3:
            continue
        span = float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum())
        if span < 0.35 * unit:  # quieta: no hay viento
            continue
        spine = _chaikin(path)
        spine = spine[-1] + (spine - spine[-1]) * STRETCH
        strength = float(np.clip(span / (2.0 * unit), 0.5, 1.0))
        # Dos o tres corrientes finas y paralelas, de largos distintos (no un tubo).
        n = _normals(spine)
        for j, (off, keep, w) in enumerate(((0.0, 1.0, 1.0), (0.22, 0.7, 0.6), (-0.3, 0.5, 0.45))):
            part = spine[int(len(spine) * (1 - keep)) :] + n[int(len(spine) * (1 - keep)) :] * off * unit * np.linspace(1, 0.2, len(spine) - int(len(spine) * (1 - keep)))[:, None]
            streak(layer, part, 0.1 * unit * w * strength, alpha * strength * (1.0 if j == 0 else 0.7))
        _motes(st.setdefault(f"m{k}", {}), spine, frame_index, unit, 1)
        _draw_motes(layer, st[f"m{k}"])


def crescent(path: np.ndarray, unit: float) -> np.ndarray:
    """La cuchilla: una medialuna por el recorrido del golpe (de la cola a la cabeza). Aunque el
    golpe sea recto se curva hacia el lado al que se doblaba (o hacia arriba): recta parecía un
    láser."""
    start, end = path[0], path[-1]
    chord = end - start
    length = max(float(np.linalg.norm(chord)) * STRETCH, 1.6 * unit)
    d = chord / max(float(np.linalg.norm(chord)), 1e-6)
    n = np.array([-d[1], d[0]])
    mid = path[len(path) // 2] - (start + end) / 2
    side = np.sign(float(np.dot(mid, n))) or (1.0 if n[1] < 0 else -1.0)  # hacia donde se doblaba; si no, arriba
    q = np.linspace(-0.5, 0.5, 24)
    center = end - d * length * 0.5
    return center + np.outer(q * length, d) + np.outer(np.cos(q * np.pi) * 0.28 * length * side, n)


def _air_slash(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    from vfxglow.engine.waterbend import _limb

    found = _limb(body, event, ("left_wrist", "right_wrist", "left_ankle", "right_ankle"))
    if found is None:
        return
    name, hand = found
    st = _activation(runtime, event, f"air:slash:{name}", body)
    unit = _unit(scale, layer)
    path = _clean_tail(_limb_path(st, "path", hand, unit))
    u = _phase(runtime, event)
    if "blade" not in st and len(path) >= 4 and (u > 0.25 or _speed(body, name, unit) < 0.05):
        # La cuchilla: la forma del golpe, que se suelta y sigue de largo hacia donde iba.
        st["blade"] = (crescent(path, unit), (path[-1] - path[-3]) * 0.6, frame_index)
    if "blade" in st:
        spine, vel, born = st["blade"]
        age = frame_index - born
        if age <= 9:
            moved = spine + vel * age * (1.0 - age / 20.0)
            fade = 1.0 - _seg(age, 4, 9)
            streak(layer, moved, 0.2 * unit * (1.0 + 0.15 * age / 9), alpha * fade, belly=0.5)
            # El filo de atrás: una medialuna más chica y fina por dentro de la curva.
            inner = moved + (moved.mean(axis=0) - moved) * 0.22
            streak(layer, inner, 0.06 * unit, alpha * fade * 0.55, belly=0.5)
            _motes(st, moved, frame_index, unit, 2 if age < 4 else 0)
    else:
        if len(path) >= 3:  # mientras golpea: la corriente fina que lo sigue
            spine = _chaikin(path)
            streak(layer, spine, 0.06 * unit, alpha * 0.7)
        _motes(st, path, frame_index, unit, 0)
    _draw_motes(layer, st)


def _air_vortex(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    hips = [p for p in (body.get("left_hip"), body.get("right_hip")) if p is not None]
    shoulders = [p for p in (body.get("left_shoulder"), body.get("right_shoulder")) if p is not None]
    if not hips:
        return
    st = _activation(runtime, event, "air:vortex", body)
    unit = _unit(scale, layer)
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.2)) * (1.0 - _seg(u, 0.8, 1.0))
    bottom = np.mean(hips, axis=0) + np.array([0.0, 0.6 * unit])
    top = np.mean(shoulders, axis=0) - np.array([0.0, 0.5 * unit]) if shoulders else bottom - np.array([0.0, 2.5 * unit])
    turn = st.setdefault("turn", 1.0 if frame_index % 2 else -1.0)
    spin = turn * frame_index * 0.32
    # Corrientes helicoidales: cada una un arco de elipse a su altura; adelante (abajo de la
    # elipse) más gruesas y brillantes, atrás más finas y tenues: la profundidad.
    for k in range(5):
        h = k / 4.0
        center = bottom + (top - bottom) * h
        rx, ry = unit * (1.5 - 0.35 * abs(h - 0.5)) * (0.7 + 0.3 * grow), unit * 0.32
        start = spin + k * 1.3
        a = np.linspace(start, start + 1.9, 18)
        arc = center + np.stack([np.cos(a) * rx, np.sin(a) * ry], axis=1)
        if turn < 0:
            arc = arc[::-1]
        front = float(np.mean(np.sin(a))) > 0  # la mitad de abajo de la elipse va adelante
        streak(layer, arc, (0.11 if front else 0.05) * unit, alpha * grow * (1.0 if front else 0.45))
        _motes(st.setdefault(f"m{k}", {}), arc, frame_index, unit, 1 if front else 0)
        _draw_motes(layer, st[f"m{k}"])


def _air_burst(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    from vfxglow.engine.waterbend import _floor

    st = _activation(runtime, event, "air:burst", body)
    unit = _unit(scale, layer)
    if "at" not in st:
        floor = _floor(body, scale)
        feet = [p for p in (body.get("left_ankle"), body.get("right_ankle")) if p is not None]
        st["at"] = np.array([float(np.mean([f[0] for f in feet])), floor]) if feet and floor is not None else np.asarray(body.get("nose") if body.get("nose") is not None else [layer.shape[1] / 2, layer.shape[0] / 2], float)
        st["born"] = frame_index
    age = frame_index - st["born"]
    # El anillo de presión: fino, casi transparente, se abre rápido y se apaga.
    for k, delay in enumerate((0, 3)):
        t = (age - delay) / 12.0
        if not 0 < t < 1:
            continue
        rx, ry = unit * (0.4 + 2.6 * _ease(t)), unit * (0.12 + 0.75 * _ease(t))
        a = np.linspace(0, TAU, 64)
        ring = st["at"] + np.stack([np.cos(a) * rx, np.sin(a) * ry], axis=1)
        for half_ring in (ring[:33], ring[32:]):
            streak(layer, half_ring, unit * 0.05 * (1 - t), alpha * (1 - t) * (0.8 if k == 0 else 0.45), belly=0.5)
        if k == 0 and age < 8:  # empuja motas hacia afuera
            _motes(st, ring[::4], frame_index, unit, 3)
    _motes(st, np.zeros((0, 2)), frame_index, unit, 0)
    _draw_motes(layer, st)


def airbend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    from vfxglow.engine.firebend import note_wind

    note_wind(frame_index)  # el capítulo es de aire: las brasas del fuego no salen
    if shape == "air_dash":
        _air_dash(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "air_slash":
        _air_slash(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "air_vortex":
        _air_vortex(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "air_burst":
        _air_burst(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "air_refract":
        _refract(layer, frame_index, 0.006 * alpha)
    return []
