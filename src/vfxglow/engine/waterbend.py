"""Agua control (estilo Avatar): agua cristalina energética.

Lo que hace que algo se lea como agua (VFX Apprentice, "Drawing stylized water"): transparencia,
reflejos, burbujas y ondas. Y cómo se arma un látigo de agua (los efectos de Avatar: The Last
Airbender): una forma guía simple que se anima, con un brillo en espiral que gira a lo largo
(el "barbershop pole") y las gotas encima.

La física, de un cuadro al siguiente:
- La cinta es una cadena de puntos con inercia (Verlet) atada a la extremidad: la sigue como una
  cuerda, con gravedad, y una tensión superficial que la alisa (laplaciano).
- Conserva el volumen: estirada, se adelgaza; muy estirada (más larga que π veces su grosor,
  Plateau-Rayleigh) se corta en gotas desde la cola.
- Las gotas caen con gravedad y arrastre, se achican y rebotan amortiguadas en el piso.

La pintura (flush_water), en capas:
1. volumen azul semitransparente, más denso donde es más grueso;
2. contorno cian fino;
3. reflejos blancos: el brillo en espiral y uno fijo del lado de la luz (arriba a la izquierda);
4. halo cian corto y tenue (más que el del fuego);
5. gotas.
`style.water_look`: "cristalina" (todo lo anterior) o "neon" (contorno y líneas de flujo, casi sin
volumen). La refracción va aparte: `water_refract` (blend `refract`) dobla el fondo según el
grosor que dejó el agua en el mismo cuadro.

Figuras:
- `water_ribbon`: látigo de agua en la extremidad que se mueve; al morir se suelta y se hace gotas.
- `water_stream`: chorro desde la mano en la dirección del antebrazo, que cae y se hace gotas.
- `water_orb`: esfera entre las manos (o sobre la mano alzada) que tiembla; al final revienta.
- `water_splash`: al pisar o caer, una corona de gotas y ondas en el piso.
- `water_ring`: un anillo de agua que gira alrededor de la cadera en un giro.
- `water_refract`: la refracción del agua del mismo cuadro (va en su propio efecto).
"""

from __future__ import annotations

import weakref

import cv2
import numpy as np

from vfxglow.engine.critters import TAU, _activation, _ease, _phase, _seg

WATERBEND = ("water_ribbon", "water_stream", "water_orb", "water_splash", "water_ring", "water_refract")

GRAVITY = 0.0035  # px por cuadro² en fracción del alto del cuadro (la persona mide ~0,5 del alto)
DAMPING = 0.9  # cuánto de la velocidad conserva la cadena de un cuadro al otro
TENSION = 0.22  # alisado de la tensión superficial por iteración
BREAKUP = np.pi  # Plateau-Rayleigh: un tramo más largo que π veces su grosor se corta en gotas
STREAM_ON = 0.7  # fracción de su vida en que la mano echa agua (después el chorro cae en gotas)
STREAM_PIECES = 36  # trozos del chorro (dos por cuadro: ~0,6 s de agua en el aire)
LIGHT = np.array([-0.6, -0.8])  # de dónde viene la luz (arriba a la izquierda)

DEEP = np.array([0.03, 0.2, 0.62], np.float32)  # el azul de lo grueso
SHALLOW = np.array([0.35, 0.85, 1.0], np.float32)  # el cian de lo fino
RIM = np.array([0.55, 1.0, 1.0], np.float32)
WHITE = np.array([1.0, 1.0, 1.0], np.float32)

_FIELDS: dict = {}
_LAST: dict = {}  # el grosor del agua del cuadro, para water_refract


def _unit(scale: float, layer) -> float:
    """Como el fuego (firebend._unit): la escala del cuerpo, pero no menos del 7% del alto."""
    return max(float(scale), 0.07 * layer.shape[0])


def _entry(layer) -> dict:
    """El agua acumulada de la capa en este cuadro (la pinta flush_water)."""
    entry = _FIELDS.get(id(layer))
    if entry is not None and entry["ref"]() is not layer:
        entry = None  # quedó de otra capa liberada con la misma dirección de memoria
    if entry is None:
        height, width = layer.shape[:2]
        entry = _FIELDS[id(layer)] = {"mask": np.zeros((height, width), np.float32), "lights": [], "alpha": 0.0, "ref": weakref.ref(layer)}
    return entry


def _fill(layer, poly: np.ndarray, alpha: float) -> None:
    if len(poly) < 3 or alpha <= 0:
        return
    entry = _entry(layer)
    entry["alpha"] = max(entry["alpha"], float(alpha))
    shape = np.zeros(entry["mask"].shape, np.uint8)
    cv2.fillPoly(shape, [np.round(poly).astype(np.int32)], 255, lineType=cv2.LINE_AA)
    np.maximum(entry["mask"], shape.astype(np.float32) / 255.0, out=entry["mask"])


def _disc(layer, center: np.ndarray, radius: float, alpha: float) -> None:
    if radius < 0.6 or alpha <= 0:
        return
    entry = _entry(layer)
    entry["alpha"] = max(entry["alpha"], float(alpha))
    shape = np.zeros(entry["mask"].shape, np.uint8)
    cv2.circle(shape, (int(round(center[0])), int(round(center[1]))), max(int(round(radius)), 1), 255, -1, lineType=cv2.LINE_AA)
    np.maximum(entry["mask"], shape.astype(np.float32) / 255.0, out=entry["mask"])
    # Cada gota con su punto de luz del lado de la luz.
    if radius > 2.0:
        dot = center + LIGHT * radius * 0.4
        entry["lights"].append(np.array([dot, dot + np.array([radius * 0.15, -radius * 0.05])]))


def _chaikin(points: np.ndarray, passes: int = 2) -> np.ndarray:
    """La polilínea suavizada (Chaikin): sin las esquinas entre trozo y trozo."""
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


def _outline(spine: np.ndarray, widths: np.ndarray) -> np.ndarray:
    n = _normals(spine)
    # Las puntas redondas (el agua no termina en punta afilada como el fuego).
    head = spine[-1] + (spine[-1] - spine[-2]) / max(float(np.linalg.norm(spine[-1] - spine[-2])), 1e-6) * widths[-1] * 0.8
    tail = spine[0] - (spine[1] - spine[0]) / max(float(np.linalg.norm(spine[1] - spine[0])), 1e-6) * widths[0] * 0.8
    return np.vstack([[tail], spine + n * widths[:, None], [head], (spine - n * widths[:, None])[::-1]])


# ----- la cadena (cinta y anillo) -----


def chain_step(st: dict, anchor: np.ndarray | None, n: int, rest: float, height: int, free: bool = False) -> np.ndarray:
    """Un paso de la cadena atada a `anchor` (la cabeza es el último punto). Con `free`, la cabeza
    también vuela (al soltarse). Devuelve los puntos (de la cola a la cabeza)."""
    if "pts" not in st:
        start = np.asarray(anchor, np.float64)
        st["pts"] = np.repeat(start[None], n, axis=0)
        st["prev"] = st["pts"].copy()
    pts, prev = st["pts"], st["prev"]
    velocity = (pts - prev) * DAMPING
    st["prev"] = pts.copy()
    pts = pts + velocity + np.array([0.0, GRAVITY * height])
    if anchor is not None and not free:
        pts[-1] = anchor
    for _ in range(4):
        # Cuerda: cada punto a lo sumo `rest` del siguiente (hacia la cabeza); la cola sigue.
        for i in range(len(pts) - 2, -1, -1):
            d = pts[i] - pts[i + 1]
            dist = float(np.linalg.norm(d))
            if dist > rest:
                pts[i] = pts[i + 1] + d / dist * rest
        # Tensión superficial: la cadena se alisa (sin tocar la cabeza atada).
        pts[1:-1] += TENSION * (pts[:-2] + pts[2:] - 2 * pts[1:-1])
    st["pts"] = pts
    return pts


def ribbon_widths(pts: np.ndarray, volume: float) -> np.ndarray:
    """Medio ancho a lo largo de la cinta (de la cola a la cabeza) conservando el volumen (el
    área de la cinta): más larga, más fina. Gruesa cerca de la cabeza y fina en la cola."""
    s = np.linspace(0.0, 1.0, len(pts))
    profile = (0.25 + 0.75 * s ** 0.8) * np.sin(np.pi * np.clip(s * 0.9 + 0.1, 0.0, 1.0)) ** 0.35
    length = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
    area_per_width = 2.0 * float(np.trapezoid(profile, dx=1.0 / max(len(pts) - 1, 1))) * max(length, 1.0)
    return profile * volume / area_per_width


def shed_drops(st: dict, pts: np.ndarray, widths: np.ndarray, height: int, rate: float) -> None:
    """Gotas que se desprenden de la cola (la cinta estirada se corta: Plateau-Rayleigh)."""
    drops = st.setdefault("drops", [])
    rng = np.random.default_rng(len(drops) * 7919 + int(pts[0, 0]))
    if len(pts) < 3:
        return
    seg = float(np.linalg.norm(pts[1] - pts[0]))
    tail = max(float(widths[1]) * 2.0, 1.0)
    count = int(rate) + int(rng.random() < rate % 1.0)
    if seg <= BREAKUP * tail and rate < 1.0:
        count = 0
    for _ in range(count):
        k = int(rng.integers(0, max(len(pts) // 3, 1)))
        vel = (st["pts"][k] - st["prev"][k]) + rng.normal(0, 0.003 * height, 2)
        drops.append([pts[k].copy(), vel, max(float(widths[k]) * rng.uniform(0.6, 1.1), 0.004 * height), 0])


def step_drops(st: dict, height: int, floor: float | None) -> list:
    """Las gotas: caen, se frenan con el aire, se achican y rebotan amortiguadas en el piso."""
    keep = []
    for drop in st.get("drops", []):
        pos, vel, radius, age = drop
        vel = vel * 0.97 + np.array([0.0, GRAVITY * height])
        pos = pos + vel
        if floor is not None and pos[1] > floor and vel[1] > 0:
            pos[1] = floor
            vel = np.array([vel[0] * 0.6, -vel[1] * 0.3])  # rebote amortiguado
            radius *= 0.7  # al chocar se reparte
        radius *= 0.975
        age += 1
        if radius > 0.6 and age < 40 and pos[1] < height * 1.2:
            keep.append([pos, vel, radius, age])
    st["drops"] = keep
    return keep


def _draw_drops(layer, drops: list, alpha: float) -> None:
    for pos, _vel, radius, _age in drops:
        _disc(layer, pos, radius, alpha)


def _spiral_lights(spine: np.ndarray, widths: np.ndarray, frame_index: int, seed: float = 0.0) -> list[np.ndarray]:
    """El brillo en espiral que gira a lo largo de la cinta (el "barbershop pole" del látigo de
    agua) y uno fijo del lado de la luz: trazos blancos cortos dentro de la forma."""
    if len(spine) < 4:
        return []
    n = _normals(spine)
    s = np.linspace(0.0, 1.0, len(spine))
    phase = TAU * (s * 1.6 - frame_index * 0.09) + seed
    across = np.sin(phase) * 0.55
    front = np.cos(phase) > 0.25  # el brillo se ve solo del lado de adelante del giro
    line = spine + n * (widths * across)[:, None]
    out, run = [], []
    for k in range(len(spine)):
        if front[k] and 0.08 < s[k] < 0.95:
            run.append(line[k])
        elif len(run) >= 2:
            out.append(np.array(run))
            run = []
    if len(run) >= 2:
        out.append(np.array(run))
    side = np.sign(float(np.mean(n @ LIGHT))) or 1.0  # el borde que mira a la luz
    lo, hi = int(len(spine) * 0.35), int(len(spine) * 0.75)
    if hi - lo >= 2:
        out.append(spine[lo:hi] + n[lo:hi] * (widths[lo:hi] * 0.62 * side)[:, None])
    return out


# ----- la pintura -----


def flush_water(layer, frame_index: int, look: str = "cristalina", gain: float = 1.0) -> None:
    """Pinta el agua acumulada: volumen semitransparente, contorno cian, reflejos, halo y gotas."""
    entry = _FIELDS.pop(id(layer), None)
    if entry is None or entry["ref"]() is not layer:
        return
    mask = entry["mask"]
    ys, xs = np.nonzero(mask > 0.02)
    if len(xs) == 0:
        return
    height, width = mask.shape
    pad = int(0.05 * height)
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, width)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, height)
    m = mask[y0:y1, x0:x1]
    solid = (m > 0.5).astype(np.uint8)
    dist = cv2.distanceTransform(solid, cv2.DIST_L2, 3)
    thick = np.clip(dist / max(0.022 * height, 1.0), 0.0, 1.0)  # 0 en el borde, 1 en lo grueso
    full = np.zeros((height, width), np.float32)
    full[y0:y1, x0:x1] = thick * m
    _LAST["frame"], _LAST["thick"], _LAST["mask"] = frame_index, full, mask.copy()
    edge = np.clip(m - cv2.erode(m, np.ones((3, 3), np.uint8)), 0.0, 1.0)
    edge = cv2.GaussianBlur(edge, (0, 0), max(0.0012 * height, 0.6))
    halo = cv2.GaussianBlur(edge, (0, 0), max(0.006 * height, 1.0))
    lights = np.zeros_like(m)
    line = max(int(round(0.0035 * height)), 1)
    for poly in entry["lights"]:
        cv2.polylines(lights, [np.round(poly - [x0, y0]).astype(np.int32)], False, 1.0, line, lineType=cv2.LINE_AA)
    lights = cv2.GaussianBlur(lights, (0, 0), max(0.001 * height, 0.5)) * m.clip(0.0, 1.0)
    a = np.float32(min(entry["alpha"], 1.0) * gain)
    if look == "neon":
        body_a = m * 0.06
        body = SHALLOW
        rim_gain, light_color = 2.2, RIM
    else:
        body_a = m * (0.24 + 0.36 * thick)  # fino: casi transparente; grueso: más denso
        body = None
        rim_gain, light_color = 1.6, WHITE
    tone = (SHALLOW[None, None, :] * (1 - thick[..., None]) + DEEP[None, None, :] * thick[..., None]) if body is None else body[None, None, :]
    # Una banda azul oscura justo adentro del contorno (el agua se ve más densa en el borde, por
    # donde la luz la atraviesa en diagonal): con ella se lee aun sobre un cielo azul.
    band = np.clip(dist / max(0.006 * height, 1.0), 0.0, 1.0)
    band = (band * (1.0 - band) * 4.0) * m * (0.0 if look == "neon" else 0.45)
    rgb = tone * body_a[..., None] + DEEP * (band * 0.4)[..., None] + RIM * (edge * rim_gain)[..., None] + RIM * (halo * 0.18)[..., None] + light_color * (lights * 1.8)[..., None]
    cover = np.clip(body_a + band + edge * 0.9 + halo * 0.2 + lights * 0.9, 0.0, 1.0)
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += rgb * a
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - cover * a)


def _refract(layer, frame_index: int, strength: float) -> None:
    """Dobla el fondo según el grosor del agua de este cuadro (como una lente): R y G llevan el
    desplazamiento en píxeles y A la máscara (blend `refract`)."""
    if _LAST.get("frame") != frame_index:
        return
    thick, mask = _LAST["thick"], _LAST["mask"]
    if thick.shape != layer.shape[:2]:
        return
    smooth = cv2.GaussianBlur(thick, (0, 0), max(0.006 * layer.shape[0], 1.0))
    gy, gx = np.gradient(smooth)
    reach = strength * layer.shape[0]
    norm = max(float(np.abs(gx).max()), float(np.abs(gy).max()), 1e-6)
    layer[..., 0] = -gx / norm * reach
    layer[..., 1] = -gy / norm * reach
    layer[..., 3] = np.maximum(layer[..., 3], np.clip(mask, 0.0, 1.0) * 0.9)


# ----- las figuras -----


def _limb(body, event, names=("left_wrist", "right_wrist")):
    """La extremidad del evento o, sin ella, la más rápida."""
    if event is not None and event.target:
        joint = event.target.split(":")[-1]
        if joint.endswith(("_wrist", "_ankle")) and body.get(joint) is not None:
            return joint, body.get(joint)
    best = None
    for name in names:
        point = body.get(name)
        if point is None:
            continue
        speed = float(np.linalg.norm(body.get(f"vel:{name}") if body.get(f"vel:{name}") is not None else np.zeros(2)))
        if best is None or speed > best[2]:
            best = (name, point, speed)
    return (best[0], best[1]) if best else None


def _floor(body, scale) -> float | None:
    feet = [p for p in (body.get(j) for j in ("left_ankle", "right_ankle", "left_heel", "right_heel")) if p is not None]
    return max(p[1] for p in feet) + 0.02 * scale if feet else None


def _water_ribbon(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    found = _limb(body, event, ("left_wrist", "right_wrist", "left_ankle", "right_ankle"))
    if found is None:
        return
    name, hand = found
    st = _activation(runtime, event, f"water:{name}", body)
    u = _phase(runtime, event)
    height = layer.shape[0]
    unit = _unit(scale, layer)
    free = u > 0.72  # al final se suelta de la mano y se hace gotas
    pts = chain_step(st, hand, 22, 0.13 * unit, height, free=free)
    volume = (0.8 * unit) ** 2 * _ease(_seg(u, 0.0, 0.15)) * (1.0 - _seg(u, 0.72, 1.0))
    widths = ribbon_widths(pts, volume)
    if volume > 1.0:
        _fill(layer, _outline(pts, widths), alpha)
        _entry(layer)["lights"] += _spiral_lights(pts, widths, frame_index)
    speed = float(np.linalg.norm(st["pts"][0] - st["prev"][0])) / max(unit, 1.0)
    shed_drops(st, pts, widths, height, (3.0 if free else 0.0) + min(speed * 6.0, 1.5))
    _draw_drops(layer, step_drops(st, height, _floor(body, scale)), alpha)


def _water_ring(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    hips = [p for p in (body.get("left_hip"), body.get("right_hip")) if p is not None]
    if not hips:
        return
    center = np.mean(hips, axis=0)
    st = _activation(runtime, event, "water:ring", body)
    u = _phase(runtime, event)
    unit = _unit(scale, layer)
    turn = st.setdefault("turn", 1.0 if frame_index % 2 else -1.0)
    angle = turn * u * TAU * 1.6
    head = center + np.array([np.cos(angle) * 1.7 * unit, np.sin(angle) * 0.45 * unit - 0.2 * unit])
    free = u > 0.8
    pts = chain_step(st, head, 26, 0.17 * unit, layer.shape[0], free=free)
    volume = (0.5 * unit) ** 2 * _ease(_seg(u, 0.0, 0.15)) * (1.0 - _seg(u, 0.8, 1.0))
    widths = ribbon_widths(pts, volume)
    if volume > 1.0:
        # Detrás del cuerpo (la mitad de arriba de la elipse) más fino: la perspectiva.
        depth = 0.75 + 0.25 * np.clip((pts[:, 1] - center[1]) / max(0.45 * unit, 1.0) + 0.5, 0.0, 1.0)
        _fill(layer, _outline(pts, widths * depth), alpha)
        _entry(layer)["lights"] += _spiral_lights(pts, widths * depth, frame_index, 1.3)
    shed_drops(st, pts, widths, layer.shape[0], 3.0 if free else 0.4)
    _draw_drops(layer, step_drops(st, layer.shape[0], _floor(body, scale)), alpha)


def _water_stream(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    found = _limb(body, event)
    if found is None:
        return
    name, hand = found
    st = _activation(runtime, event, f"stream:{name}", body)
    u = _phase(runtime, event)
    height = layer.shape[0]
    unit = _unit(scale, layer)
    if "aim" not in st:
        elbow = body.get(name.replace("wrist", "elbow").replace("ankle", "knee"))
        aim = (hand - elbow) if elbow is not None and float(np.linalg.norm(hand - elbow)) > 1 else np.array([1.0, -0.2])
        aim = aim / max(float(np.linalg.norm(aim)), 1e-6) + np.array([0.0, -0.45])  # sale algo hacia arriba y cae en arco
        st["aim"] = aim / max(float(np.linalg.norm(aim)), 1e-6)
    jet = st.setdefault("jet", [])
    if u < STREAM_ON:  # la mano echa agua: cada cuadro salen trozos del chorro (dos, para que sea continuo)
        rng = np.random.default_rng(frame_index)
        last = st.get("hand", np.asarray(hand, np.float64))
        for f in (0.5, 1.0):
            at = last + (np.asarray(hand, np.float64) - last) * f
            jet.append([at.copy(), st["aim"] * 0.024 * height + rng.normal(0, 0.0015 * height, 2), 0.32 * unit])
        st["hand"] = np.asarray(hand, np.float64).copy()
    for piece in jet:
        # Un chorro con presión: la gravedad lo curva de a poco (no cae como una gota suelta).
        piece[1] = piece[1] * 0.99 + np.array([0.0, GRAVITY * height * 0.35])
        piece[0] = piece[0] + piece[1]
        piece[2] *= 0.985
    del jet[:-STREAM_PIECES]  # largo máximo: lo más viejo ya cayó
    # El chorro es la línea por los trozos (del más viejo al de la mano); se corta en gotas desde
    # la punta cuando la mano deja de echar agua.
    if u >= STREAM_ON and jet:
        old = jet.pop(0)
        st.setdefault("drops", []).append([old[0], old[1], old[2] * 0.9, 0])
    if len(jet) >= 3:
        spine = _chaikin(np.array([p[0] for p in jet]))
        widths = np.interp(np.linspace(0, 1, len(spine)), np.linspace(0, 1, len(jet)), np.array([p[2] for p in jet]) * np.linspace(0.6, 1.0, len(jet)))
        _fill(layer, _outline(spine, widths), alpha)
        _entry(layer)["lights"] += _spiral_lights(spine, widths, frame_index, 0.7)
    _draw_drops(layer, step_drops(st, height, _floor(body, scale)), alpha)


def _water_orb(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    st = _activation(runtime, event, "water:orb", body)
    u = _phase(runtime, event)
    unit = _unit(scale, layer)
    wrists = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
    if not wrists:
        return
    if len(wrists) == 2 and float(np.linalg.norm(wrists[0] - wrists[1])) < 2.2 * unit:
        target = (wrists[0] + wrists[1]) / 2  # entre las manos
    else:
        target = min(wrists, key=lambda p: p[1]) + np.array([0.0, -0.9 * unit])  # sobre la mano alzada
    center = st.get("center", target) * 0.7 + target * 0.3  # sigue a las manos con inercia
    moved = center - st.get("center", center)
    st["center"] = center
    # Oscilación de la superficie (modos 2 y 3, resortes amortiguados) que excita el movimiento.
    modes = st.setdefault("modes", np.zeros((2, 2)))
    kick = float(np.linalg.norm(moved)) / max(unit, 1.0)
    modes[:, 1] = modes[:, 1] * 0.82 - modes[:, 0] * 0.35 + kick * np.array([0.25, 0.15])
    modes[:, 0] = np.clip(modes[:, 0] + modes[:, 1], -0.25, 0.25)
    if u < 0.85:
        radius = 0.85 * unit * _ease(_seg(u, 0.0, 0.2))
        a = np.linspace(0, TAU, 64, endpoint=False)
        wobble = 1.0 + modes[0, 0] * np.cos(2 * a + frame_index * 0.3) + modes[1, 0] * np.cos(3 * a - frame_index * 0.2) + 0.03 * np.sin(5 * a + frame_index * 0.5)
        ring = center + np.stack([np.cos(a), np.sin(a)], axis=1) * (radius * wobble)[:, None]
        _fill(layer, ring, alpha)
        # Reflejos: un arco del lado de la luz y una línea de agua que gira adentro.
        arc = np.linspace(np.pi * 1.05, np.pi * 1.45, 10)
        _entry(layer)["lights"].append(center + np.stack([np.cos(arc), np.sin(arc)], axis=1) * radius * 0.72)
        swirl = np.linspace(0, np.pi * 0.9, 12) + frame_index * 0.12
        _entry(layer)["lights"].append(center + np.stack([np.cos(swirl), np.sin(swirl) * 0.35], axis=1) * radius * 0.5)
    elif "burst" not in st:  # revienta: gotas hacia afuera
        st["burst"] = True
        rng = np.random.default_rng(frame_index)
        for k in range(18):
            ang = k * TAU / 18 + rng.uniform(-0.15, 0.15)
            vel = np.array([np.cos(ang), np.sin(ang)]) * unit * rng.uniform(0.12, 0.22) + moved
            st.setdefault("drops", []).append([center.copy(), vel, unit * rng.uniform(0.06, 0.12), 0])
    _draw_drops(layer, step_drops(st, layer.shape[0], _floor(body, scale)), alpha)


def _water_splash(body, scale, frame_index, runtime, layer, alpha, event) -> None:
    feet = [p for p in (body.get("left_ankle"), body.get("right_ankle")) if p is not None]
    floor = _floor(body, scale)
    if not feet or floor is None:
        return
    st = _activation(runtime, event, "water:splash", body)
    unit = _unit(scale, layer)
    if "x" not in st:
        foot = max(feet, key=lambda p: p[1])
        st["x"], st["floor"], st["age"] = float(foot[0]), floor, 0
        rng = np.random.default_rng(int(foot[0]) + frame_index)
        for k in range(26):  # la corona: gotas hacia arriba y afuera
            side = -1.0 if k % 2 else 1.0
            vel = np.array([side * rng.uniform(0.02, 0.09), -rng.uniform(0.08, 0.16)]) * unit
            st.setdefault("drops", []).append([np.array([st["x"] + side * rng.uniform(0.1, 0.6) * unit, floor]), vel, unit * rng.uniform(0.05, 0.1), 0])
    st["age"] += 1
    age = st["age"]
    # Ondas en el piso: elipses que se abren y se afinan (solo contorno, el agua se esparce).
    for k in range(2):
        grow = age - 4 * k
        if 0 < grow < 18:
            rx, ry = unit * (0.4 + 0.12 * grow), unit * (0.08 + 0.025 * grow)
            a = np.linspace(0, TAU, 48)
            ellipse = np.stack([st["x"] + np.cos(a) * rx, st["floor"] + np.sin(a) * ry], axis=1)
            inner = np.stack([st["x"] + np.cos(a[::-1]) * rx * 0.9, st["floor"] + np.sin(a[::-1]) * ry * 0.8], axis=1)
            _fill(layer, np.vstack([ellipse, inner]), alpha * (1 - grow / 18))
    _draw_drops(layer, step_drops(st, layer.shape[0], st["floor"]), alpha)


def waterbend(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    if shape == "water_ribbon":
        _water_ribbon(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "water_ring":
        _water_ring(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "water_stream":
        _water_stream(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "water_orb":
        _water_orb(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "water_splash":
        _water_splash(body, scale, frame_index, runtime, layer, alpha, event)
    elif shape == "water_refract":
        _refract(layer, frame_index, 0.012 * alpha)
    return []
