"""Personajes con historia sobre el cuerpo (adornos `type: adornment`, `style.shapes`).

Leídos de video_35 (docs/referencias/video_35.md) con la explicación del usuario: no son
adornos fijos sino pequeñas aventuras que llaman la atención, con un principio, un conflicto y un
final. Cada uno recorre su guion según la fracción `u` del momento (0 al encenderse, 1 al apagarse):

- `stick_man`: un muñequito de palitos aparece en la mano del brazo extendido, camina sobre el
  brazo como en una plataforma, tropieza y cae, la otra mano lo ataja, da una vuelta y la mano lo
  aplasta: se desintegra en chispas (seg. 4,3-5,9).
- `ufo`: un ovni nace entre las manos, orbita la cabeza en perspectiva (por detrás se oculta y a
  toda velocidad se estira), se sale de control, deja caer algo sobre el pecho y persigue las
  manos (seg. 6,1-9,1).
- `snake`: una serpiente recorre los brazos de una mano a la otra pasando por los hombros, se
  enrosca en la muñeca y se convierte en un rayo que sale disparado (idea propuesta por el usuario).
- `water_balloon`: un globo de agua en la extremidad más rápida: se estira con la velocidad, se
  aplasta al frenar, tiembla, y al final revienta en gotas (seg. 25,4-27,0: el lanzamiento de béisbol
  con un globo de agua).

Propuestos por Gemini al leer video_35 completo como animador (configs/pruebas/video_35_gemini.yaml):

- `spark_trap`: una chispa viva con ojos salta de la gorra a la mano levantada, intenta escapar
  hacia arriba, el puño la atrapa (se aplasta y suelta chispas), se escapa otra vez, la vuelve a
  atrapar y al final se parte en dos aros que corren a las muñecas (seg. 8,9-10,1).
- `time_rope`: un ancla de luz se clava en el aire al costado y una soga va de ella a las manos;
  al jalar se tensa recta, vibra como cuerda de guitarra y marca "<<"; floja, se comba. Al final se
  suelta, se enrolla en las manos y queda una bola de energía (seg. 16,3-17,2).
- `supersuit`: dos cierres suben de la cadera a los hombros y van dibujando una armadura de
  placas (pectorales, emblema, hombreras); el emblema brilla al 100% y al final las placas se
  desarman y caen como gotas ("I don't need no supersuit", seg. 19,9-20,9).
- `glider`: alas de planeador entre las muñecas y los costados, ondas de sonido que salen del
  pecho y estelas en las puntas de los dedos; al final las alas se funden en un rayo que atraviesa
  los brazos de punta a punta (seg. 28,8-30,8).

El estado entre cuadros (posiciones suavizadas) se guarda en `runtime.swoosh["_critters"]`.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
CRITTERS = ("stick_man", "ufo", "snake", "water_balloon", "spark_trap", "time_rope", "supersuit", "glider")


def _state(runtime, key: str) -> dict:
    store = runtime.swoosh.setdefault("_critters", {})
    if not isinstance(store, dict):
        store = runtime.swoosh["_critters"] = {}
    return store.setdefault(key, {})


def _phase(runtime, event) -> float:
    """Fracción del momento: cuadros encendidos sobre la duración del evento más su retención."""
    triggers = runtime.effect.triggers
    hold = triggers[0].hold if triggers else 20
    span = (event.end_frame - event.start_frame + 1 + hold) if event is not None else 60
    return float(np.clip(runtime.active_frames / max(span, 1), 0.0, 1.0))


def _ease(u: float) -> float:
    return u * u * (3 - 2 * u)


def _seg(u: float, a: float, b: float) -> float:
    return float(np.clip((u - a) / max(b - a, 1e-6), 0.0, 1.0))


def _along(path: np.ndarray, t: float) -> tuple[np.ndarray, np.ndarray]:
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    total = max(float(seg.sum()), 1e-6)
    target = float(np.clip(t, 0.0, 1.0)) * total
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    k = int(np.clip(np.searchsorted(acc, target) - 1, 0, len(seg) - 1))
    local = (target - acc[k]) / max(float(seg[k]), 1e-6)
    direction = (path[k + 1] - path[k]) / max(float(seg[k]), 1e-6)
    return path[k] + (path[k + 1] - path[k]) * local, direction


def _sides(body, center):
    """(lado del brazo extendido, lado del otro brazo): el de la muñeca más lejos del pecho."""
    reach = {}
    for side in ("left", "right"):
        wrist = body.get(f"{side}_wrist")
        if wrist is not None:
            reach[side] = float(np.linalg.norm(wrist - center))
    if len(reach) < 2:
        return None
    out = max(reach, key=reach.get)
    return out, ("left" if out == "right" else "right")


# ----- el muñequito de palitos -----


def _stick_figure(foot: np.ndarray, up: np.ndarray, size: float, walk: float, tilt: float = 0.0, squash: float = 1.0) -> list[np.ndarray]:
    """Monito de palitos de pie sobre `foot`. `walk`: fase del paso; `tilt`: inclinación (rad)."""
    c, s = np.cos(tilt), np.sin(tilt)
    up = np.array([up[0] * c - up[1] * s, up[0] * s + up[1] * c])
    side = np.array([-up[1], up[0]])
    h = size * squash
    hip = foot + up * h * 0.45
    neck = foot + up * h * 0.82
    head = foot + up * h * 1.0
    swing = np.sin(walk) * 0.18 * size
    t = np.linspace(0, TAU, 16)
    head_ring = head + np.stack([np.cos(t), np.sin(t)], axis=1) * size * 0.13
    legs = [np.array([hip, foot + side * swing]), np.array([hip, foot - side * swing])]
    arms = [np.array([neck - up * h * 0.08, neck - up * h * 0.3 + side * swing * 1.2]), np.array([neck - up * h * 0.08, neck - up * h * 0.3 - side * swing * 1.2])]
    return [head_ring, np.array([neck, hip]), *legs, *arms]


def _stick_man(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    sides = _sides(body, center)
    if sides is None:
        return []
    out, other = sides
    wrist, elbow, shoulder = (body.get(f"{out}_{j}") for j in ("wrist", "elbow", "shoulder"))
    catcher = body.get(f"{other}_wrist")
    if wrist is None or elbow is None or shoulder is None or catcher is None:
        return []
    u = _phase(runtime, event)
    size = 0.5 * scale
    walk = frame_index * 0.7
    platform = np.array([wrist, elbow, shoulder])
    st = _state(runtime, f"stick:{body.prefix}")
    if u < 0.08:  # aparece en la punta de los dedos
        grow = _seg(u, 0.0, 0.08)
        return _stick_figure(wrist, up, size * max(grow, 0.05), walk)
    if u < 0.45:  # camina sobre el brazo hacia el hombro
        pos, _ = _along(platform, _ease(_seg(u, 0.08, 0.45)) * 0.75)
        st["pos"] = pos
        return _stick_figure(pos, up, size, walk)
    if u < 0.58:  # tropieza y cae, girando
        fall = _seg(u, 0.45, 0.58)
        start = st.get("pos", elbow)
        pos = start + (catcher - start) * fall + up * np.sin(fall * np.pi) * 0.3 * scale
        return _stick_figure(pos, up, size, walk * 2, tilt=fall * 2.5)
    if u < 0.8:  # atajado: da una vuelta alrededor de la mano que lo atrapó
        loop = _seg(u, 0.58, 0.8)
        angle = loop * TAU
        pos = catcher + (across * np.cos(angle) + up * (0.6 + 0.5 * np.sin(angle))) * 0.25 * scale
        return _stick_figure(pos, up, size, walk * 1.5, tilt=np.sin(angle) * 0.6)
    if u < 0.9:  # la mano lo aplasta
        press = _seg(u, 0.8, 0.9)
        return _stick_figure(catcher, up, size, 0.0, squash=1.0 - 0.8 * press)
    # se desintegra en chispas
    burst = _seg(u, 0.9, 1.0)
    rng = np.random.default_rng(int(abs(catcher[0])) % 997)
    for _ in range(14):
        angle, dist = rng.uniform(0, TAU), rng.uniform(0.2, 1.0) * burst * 0.6 * scale
        point = catcher + np.array([np.cos(angle), np.sin(angle)]) * dist
        splat(layer, float(point[0]), float(point[1]), 0.03 * scale * (1 - burst) + 1, WHITE * 1.4, alpha * (1 - burst), runtime.kernels)
    return []


# ----- el ovni -----


def _saucer(center: np.ndarray, size: float, stretch: np.ndarray | None, frame_index: int, layer, color, alpha, runtime) -> list[np.ndarray]:
    """Platillo: domo, borde ancho y luces. `stretch`: dirección y cuánto se estira por la velocidad."""
    t = np.linspace(0, TAU, 40)
    rim = np.stack([np.cos(t) * size, np.sin(t) * size * 0.32], axis=1)
    dome = np.stack([np.cos(t[:21] * 0.5 + np.pi) * size * 0.45 + 0, np.sin(t[:21] * 0.5 + np.pi) * size * 0.45 - size * 0.08], axis=1)
    curves = [rim, dome]
    if stretch is not None:
        amount = float(np.linalg.norm(stretch))
        if amount > 1e-3:
            d = stretch / amount
            n = np.array([-d[1], d[0]])
            k = 1.0 + min(0.5 * amount, 0.6)  # deformado por la velocidad, sin volverse una raya
            transform = np.outer(d, d) * k + np.outer(n, n) / np.sqrt(k)
            curves = [c @ transform.T for c in curves]
    curves = [center + c for c in curves]
    fill_polygon(layer, curves[0], np.asarray(color, np.float32), alpha * 0.4, 0.9, feather=1.5)
    for k in range(5):  # luces que corren por el borde
        a = frame_index * 0.5 + k * TAU / 5
        point = center + np.array([np.cos(a) * size * 0.75, np.sin(a) * size * 0.2])
        splat(layer, float(point[0]), float(point[1]), size * 0.08, WHITE * 1.5, alpha, runtime.kernels)
    return curves


def _ufo(body, frame, scale, frame_index, runtime, layer, color, alpha, event, head) -> list[np.ndarray]:
    from vfxglow.engine.duo_fx import body_mask

    center, across, down = frame
    up = -down
    if head is None:
        return []
    u = _phase(runtime, event)
    hands = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
    size = 0.32 * scale
    st = _state(runtime, f"ufo:{body.prefix}")
    chest = center + down * 0.35 * scale
    if u < 0.15:  # nace entre las manos
        spot = np.mean(hands, axis=0) if hands else head + up * 0.3 * scale
        st["pos"] = spot
        return _saucer(spot, size * max(_seg(u, 0.0, 0.15), 0.1), None, frame_index, layer, color, alpha, runtime)
    if u < 0.55:  # orbita la cabeza en perspectiva
        angle = _seg(u, 0.15, 0.55) * TAU * 2.0
        depth = np.sin(angle)
        pos = head + across * np.cos(angle) * 0.75 * scale + up * (0.15 + 0.12 * depth) * scale
        speed = pos - st.get("pos", pos)
        st["pos"] = pos
        mask = body_mask(body, layer.shape[:2], scale)
        x, y = int(np.clip(pos[0], 0, layer.shape[1] - 1)), int(np.clip(pos[1], 0, layer.shape[0] - 1))
        if depth > 0.2 and mask is not None and mask[y, x]:  # por detrás de la cabeza: oculto
            return []
        return _saucer(pos, size * (0.85 + 0.15 * (1 - depth)), speed / (0.15 * scale), frame_index, layer, color, alpha, runtime)
    if u < 0.68:  # se sale de control y deja caer algo sobre el pecho
        drop = _seg(u, 0.55, 0.68)
        pos = st.get("pos", head)
        wobble = across * np.sin(frame_index * 1.3) * 0.08 * scale
        curves = _saucer(pos + wobble, size, None, frame_index, layer, color, alpha, runtime)
        bomb = pos + (chest - pos) * drop
        t = np.linspace(0, TAU, 14)
        curves.append(bomb + np.stack([np.cos(t), np.sin(t) * 1.3], axis=1) * 0.06 * scale)
        if drop > 0.9:
            splat(layer, float(chest[0]), float(chest[1]), 0.2 * scale, WHITE * 1.6, alpha, runtime.kernels)
        return curves
    # persecución: corre tras las manos, rápido y estirado
    chase = _seg(u, 0.68, 1.0)
    target = hands[int(frame_index // 10) % len(hands)] if hands else chest
    pos = st.get("pos", target)
    pos = pos + (target + up * 0.2 * scale - pos) * 0.25
    speed = pos - st.get("pos", pos)
    st["pos"] = pos
    return _saucer(pos, size * (1 - 0.3 * chase), speed / (0.12 * scale), frame_index, layer, color, alpha * (1 - max(chase - 0.85, 0) / 0.15), runtime)


# ----- la serpiente -----


def _snake(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    from vfxglow.engine.duo_doodles import zigzag
    from vfxglow.engine.duo_fx import fill_band

    center, across, down = frame
    names = ("left_wrist", "left_elbow", "left_shoulder", "right_shoulder", "right_elbow", "right_wrist")
    points = [body.get(n) for n in names]
    if any(p is None for p in points):
        return []
    neck = body.get("neck")
    path = np.array(points[:3] + ([neck] if neck is not None else []) + points[3:])
    u = _phase(runtime, event)
    length = 0.35
    curves: list[np.ndarray] = []
    if u < 0.7:
        head_t = _seg(u, 0.0, 0.7) * (1 + length)
        ts = np.clip(np.linspace(head_t - length, head_t, 40), 0.0, 1.0)
        spine = np.array([_along(path, t)[0] for t in ts])
        tangent = np.gradient(spine, axis=0)
        normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
        normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)
        wave = np.sin(np.linspace(0, TAU * 2.5, len(spine)) - frame_index * 0.6)[:, None] * normal * 0.05 * scale
        body_curve = spine + wave - down * 0.04 * scale
        widths = 0.07 * scale * np.linspace(0.2, 1.0, len(spine)) ** 0.6
        fill_band(layer, body_curve, widths, alpha * 0.9)
        head_point = body_curve[-1]
        splat(layer, float(head_point[0]), float(head_point[1]), 0.04 * scale, WHITE * 1.4, alpha, runtime.kernels)
        tongue_dir = (body_curve[-1] - body_curve[-3]) / max(float(np.linalg.norm(body_curve[-1] - body_curve[-3])), 1e-6)
        tip = head_point + tongue_dir * 0.08 * scale
        flick = np.array([-tongue_dir[1], tongue_dir[0]]) * 0.025 * scale
        curves += [body_curve, np.array([head_point, tip, tip + flick]), np.array([tip, tip - flick])]
        return curves
    wrist = points[-1]
    if u < 0.85:  # se enrosca en la muñeca
        coil = _seg(u, 0.7, 0.85)
        t = np.linspace(0, TAU * 2.5, 60)
        r = 0.09 * scale * (1 - 0.3 * coil)
        spiral = wrist + np.stack([np.cos(t + frame_index * 0.4) * r, np.sin(t + frame_index * 0.4) * r * 0.4 + (t / (TAU * 2.5) - 0.5) * 0.25 * scale], axis=1)
        return [spiral]
    # se convierte en un rayo que sale disparado hacia afuera
    zap = _seg(u, 0.85, 1.0)
    outward = (wrist - center) / max(float(np.linalg.norm(wrist - center)), 1e-6)
    end = wrist + outward * (0.4 + 1.4 * zap) * scale
    rng = np.random.default_rng(frame_index)
    return [zigzag(np.array([wrist, end]), 0.07 * scale, rng, 0.06 * scale)]


# ----- el globo de agua -----


def _water_balloon(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    center, across, down = frame
    st = _state(runtime, f"balloon:{body.prefix}")
    joints = ("left_wrist", "right_wrist", "left_ankle", "right_ankle")
    best, speed = None, -1.0
    for j in joints:
        point = body.get(j)
        vel = body.points.get(f"vel:{body.prefix}{j}")
        if point is None:
            continue
        v = float(np.linalg.norm(vel)) if vel is not None else 0.0
        if v > speed:
            best, speed = (j, point, vel if vel is not None else np.zeros(2)), v
    if best is None:
        return []
    joint, point, vel = best
    if st.get("joint") and st["joint"] != joint and speed < 1.5 * st.get("speed", 0.0):
        held = body.get(st["joint"])
        if held is not None:
            joint, point = st["joint"], held
    # El globo cuelga un poco de la extremidad y la sigue con un resorte (se queda atrás y rebota).
    target = point + down * 0.05 * scale
    pos = st.get("pos", target)
    velocity = st.get("vel", np.zeros(2))
    velocity = (velocity + (target - pos) * 0.35) * 0.7
    pos = pos + velocity
    accel = velocity - st.get("vel", np.zeros(2))
    st.update(pos=pos, vel=velocity, joint=joint, speed=speed)
    u = _phase(runtime, event)
    r = 0.17 * scale
    if u > 0.92:  # revienta en gotas
        burst = _seg(u, 0.92, 1.0)
        rng = np.random.default_rng(17)
        curves = []
        for _ in range(12):
            angle = rng.uniform(0, TAU)
            d = np.array([np.cos(angle), np.sin(angle)])
            drop = pos + d * r * (1 + 3 * burst) + down * burst * burst * 0.4 * scale
            curves.append(np.array([drop - d * 0.04 * scale, drop]))
        return curves
    # Estirado en la dirección del movimiento (más rápido, más largo) y aplastado al frenar.
    move = float(np.linalg.norm(velocity))
    stretch = 1.0 + min(move / (0.08 * scale), 1.2)
    squash = 1.0 + min(float(np.linalg.norm(accel)) / (0.05 * scale), 0.6)
    direction = velocity / move if move > 1e-3 else -down
    normal = np.array([-direction[1], direction[0]])
    wobble = 1.0 + 0.06 * np.sin(frame_index * 1.7)
    t = np.linspace(0, TAU, 40)
    along = np.cos(t) * r * stretch / squash * wobble
    side = np.sin(t) * r / np.sqrt(stretch) * squash
    blob = pos + np.outer(along, direction) + np.outer(side, normal)
    fill_polygon(layer, blob, np.asarray(color, np.float32), alpha * 0.45, 0.9, feather=2.0)
    shine = pos - direction * r * 0.3 + normal * r * 0.35
    splat(layer, float(shine[0]), float(shine[1]), r * 0.18, WHITE * 1.5, alpha, runtime.kernels)
    knot = pos - direction * r * stretch / squash
    return [blob, np.array([knot, knot - direction * 0.05 * scale + normal * 0.03 * scale])]


def _activation(runtime, event, name: str, body) -> dict:
    """Estado propio de cada vez que se enciende (el ancla de la soga no se reutiliza)."""
    start = event.start_frame if event is not None else 0
    return _state(runtime, f"{name}:{body.prefix}:{start}")


# ----- la chispa atrapada en el puño -----


def _sprite(pos, r, k, up, frame_index, layer, color, alpha, runtime) -> list[np.ndarray]:
    """Chispa con ojos. `k` > 1 la estira hacia arriba (huye); < 1 la aplasta (atrapada)."""
    side = np.array([-up[1], up[0]])
    t = np.linspace(0, TAU, 28)
    blob = pos + np.outer(np.cos(t) * r / np.sqrt(k), side) + np.outer(np.sin(t) * r * k, up)
    fill_polygon(layer, blob, np.asarray(color, np.float32), alpha * 0.5, 0.9, feather=1.5)
    for s in (-1, 1):
        eye = pos + up * r * 0.25 * k + side * s * r * 0.35 / np.sqrt(k)
        splat(layer, float(eye[0]), float(eye[1]), max(r * 0.16, 1.0), WHITE * 1.6, alpha, runtime.kernels)
    curves = [blob]
    for n in range(6):  # púas eléctricas que giran
        a = frame_index * 0.35 + n * TAU / 6
        d = np.cos(a) * side + np.sin(a) * up
        base = pos + d * r * 1.15
        kink = base + d * r * 0.3 + np.array([-d[1], d[0]]) * r * 0.15
        curves.append(np.array([base, kink, base + d * r * 0.6]))
    return curves


def _knuckle_sparks(layer, hand, scale, frame_index, alpha, runtime) -> None:
    rng = np.random.default_rng(frame_index)
    for _ in range(6):
        angle, dist = rng.uniform(0, TAU), rng.uniform(0.05, 0.16) * scale
        point = hand + np.array([np.cos(angle), np.sin(angle)]) * dist
        splat(layer, float(point[0]), float(point[1]), 0.015 * scale + 1, WHITE * 1.5, alpha, runtime.kernels)


def _spark_trap(body, frame, scale, frame_index, runtime, layer, color, alpha, event, head) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    wrists = {s: body.get(f"{s}_wrist") for s in ("left", "right")}
    if any(w is None for w in wrists.values()):
        return []
    side = min(wrists, key=lambda s: float(np.dot(wrists[s] - center, down)))  # la mano levantada
    other = wrists["left" if side == "right" else "right"]
    wrist, elbow = wrists[side], body.get(f"{side}_elbow")
    forearm = (wrist - elbow) / max(float(np.linalg.norm(wrist - elbow)), 1e-6) if elbow is not None else up
    hand = wrist + forearm * 0.1 * scale
    top = head + up * 0.25 * scale if head is not None else center + up * 0.7 * scale
    u = _phase(runtime, event)
    r = 0.1 * scale
    if u < 0.15:  # salta de la gorra a la mano en un arco
        s = _ease(_seg(u, 0.0, 0.15))
        pos = top + (hand + up * 0.15 * scale - top) * s + up * np.sin(s * np.pi) * 0.25 * scale
        return _sprite(pos, r, 1.2, up, frame_index, layer, color, alpha, runtime)
    if u < 0.45:  # flota frente a la palma e intenta escapar hacia arriba
        s = _seg(u, 0.15, 0.45)
        pos = hand + up * (0.15 + 0.12 * s) * scale + across * np.sin(frame_index * 0.9) * 0.04 * scale
        return _sprite(pos, r, 1.0 + 0.5 * s, up, frame_index, layer, color, alpha, runtime)
    if u < 0.55 or 0.68 <= u < 0.82:  # el puño la atrapa: aplastada, chispas entre los nudillos
        _knuckle_sparks(layer, hand, scale, frame_index, alpha, runtime)
        return _sprite(hand, r * 0.8, 0.45, up, frame_index, layer, color, alpha, runtime)
    if u < 0.68:  # el puño se abre: se escapa un momento
        s = _seg(u, 0.55, 0.68)
        pos = hand + up * np.sin(s * np.pi) * 0.25 * scale
        return _sprite(pos, r, 1.6 - 0.6 * s, up, frame_index, layer, color, alpha, runtime)
    # se parte en dos aros que corren a las muñecas
    s = _ease(_seg(u, 0.82, 1.0))
    t = np.linspace(0, TAU, 24)
    curves = []
    for target in (wrist, other):
        pos = hand + (target - hand) * s
        ring_r = (0.03 + 0.07 * s) * scale
        curves.append(pos + np.outer(np.cos(t) * ring_r, across) + np.outer(np.sin(t) * ring_r * 0.4, up))
    return curves


# ----- la soga del tiempo -----


def _anchor_glyph(at, size, up) -> list[np.ndarray]:
    side = np.array([-up[1], up[0]])
    t = np.linspace(0, TAU, 16)
    ring = at + up * size + np.outer(np.cos(t), side) * size * 0.18 + np.outer(np.sin(t), up) * size * 0.18
    shank = np.array([at + up * size * 0.82, at - up * size * 0.8])
    stock = np.array([at + up * size * 0.5 - side * size * 0.35, at + up * size * 0.5 + side * size * 0.35])
    a = np.linspace(np.pi * 0.1, np.pi * 0.9, 18)
    arm = at - up * size * 0.35 + np.outer(np.cos(a), side) * size * 0.6 - np.outer(np.sin(a), up) * size * 0.45
    return [ring, shank, stock, arm]


def _time_rope(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    wrists = [body.get("left_wrist"), body.get("right_wrist")]
    if any(w is None for w in wrists):
        return []
    hands = np.mean(wrists, axis=0)
    st = _activation(runtime, event, "rope", body)
    height, width = layer.shape[:2]
    if "anchor" not in st:  # se clava detrás de él, contra su marcha: al jalar se aleja del ancla
        hips = [v for v in (body.points.get(f"vel:{body.prefix}{j}") for j in ("left_hip", "right_hip")) if v is not None]
        drift = float(np.mean([v[0] for v in hips])) if hips else 0.0
        lean = -drift if abs(drift) > 1e-3 else float(hands[0] - center[0]) or 1.0
        anchor = hands + np.array([np.sign(lean) * 2.4 * scale, -0.15 * scale])
        st["anchor"] = np.clip(anchor, [0.05 * width, 0.1 * height], [0.95 * width, 0.9 * height])
        st["dist"] = float(np.linalg.norm(hands - st["anchor"]))
        st["tension"] = 0.0
    anchor = st["anchor"]
    u = _phase(runtime, event)
    dist = float(np.linalg.norm(hands - anchor))
    pull = float(np.clip((dist - st["dist"]) / (0.012 * scale), 0.0, 1.0))  # se aleja: jala
    st["tension"] = 0.6 * st["tension"] + 0.4 * pull
    st["dist"] = dist
    tension = st["tension"]
    curves = _anchor_glyph(anchor, 0.25 * scale, up) if u < 0.8 else []
    if u >= 0.8:  # se suelta, se enrolla en las manos y queda una bola de energía
        s = _seg(u, 0.8, 1.0)
        t = np.linspace(0, TAU * 3 * (1 - s) + 0.5, 50)
        r = (0.25 * (1 - s) + 0.06) * scale * np.linspace(1.0, 0.3, len(t))
        curves.append(hands + np.outer(np.cos(t + frame_index * 0.5) * r, across) + np.outer(np.sin(t + frame_index * 0.5) * r * 0.5, up))
        if s > 0.6:
            ball = hands + np.outer(np.cos(t), across) * 0.08 * scale + np.outer(np.sin(t), up) * 0.08 * scale
            fill_polygon(layer, ball, np.asarray(color, np.float32), alpha * 0.6, 0.9, feather=2.0)
            splat(layer, float(hands[0]), float(hands[1]), 0.06 * scale, WHITE * 1.6, alpha, runtime.kernels)
        return curves
    grow = _ease(_seg(u, 0.0, 0.12))  # la soga sale disparada del ancla hacia las manos
    end = anchor + (hands - anchor) * grow
    s = np.linspace(0, 1, 32)[:, None]
    span = end - anchor
    normal = np.array([-span[1], span[0]]) / max(float(np.linalg.norm(span)), 1e-6)
    sag = (1 - tension) * 0.2 * scale * (1 + 0.15 * np.sin(frame_index * 0.8))  # floja, con rebote
    buzz = tension * 0.025 * scale * np.sin(frame_index * 2.3) * np.sin(s * np.pi * 3)  # tensa: vibra
    rope = anchor + span * s + down * sag * np.sin(s * np.pi) + normal * buzz
    curves.append(rope)
    if tension > 0.35:  # "<<": rebobina hacia las manos
        d = span / max(float(np.linalg.norm(span)), 1e-6)
        for at in (0.4, 0.6):
            tip = rope[int(at * 31)] + up * 0.09 * scale
            for off in (0.0, 0.05):
                point = tip + d * off * scale
                curves.append(np.array([point - d * 0.04 * scale + up * 0.04 * scale, point, point - d * 0.04 * scale - up * 0.04 * scale]))
    return curves


# ----- la armadura de luz -----


def _supersuit(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    center, across, down = frame
    corners = [body.get(j) for j in ("left_shoulder", "right_shoulder", "left_hip", "right_hip")]
    if any(c is None for c in corners):
        return []
    ls, rs, lh, rh = corners
    u = _phase(runtime, event)
    pull = 1.0 + 0.12 * np.sin(np.pi * _seg(u, 0.45, 0.75))  # tira de las solapas hacia afuera

    def at(points):
        out = []
        for x, y in points:
            left, right = ls + (lh - ls) * y, rs + (rh - rs) * y
            mid = (left + right) / 2
            out.append(mid + (right - left) * 0.5 * x * pull)
        return np.array(out)

    plates = [
        [(-0.85, 0.12), (-0.1, 0.12), (-0.1, 0.42), (-0.5, 0.5), (-0.8, 0.38), (-0.85, 0.12)],
        [(0.85, 0.12), (0.1, 0.12), (0.1, 0.42), (0.5, 0.5), (0.8, 0.38), (0.85, 0.12)],
        [(-1.05, 0.05), (-0.95, -0.1), (-0.65, -0.08), (-0.55, 0.05)],
        [(1.05, 0.05), (0.95, -0.1), (0.65, -0.08), (0.55, 0.05)],
        *[[(-0.6, y), (0.0, y + 0.08), (0.6, y)] for y in (0.6, 0.72, 0.84)],
    ]
    emblem = [(0.0, 0.18), (0.13, 0.3), (0.0, 0.42), (-0.13, 0.3), (0.0, 0.18)]
    if u < 0.45:  # dos cierres suben de la cadera a los hombros y dibujan las placas
        level = 1.05 - 1.2 * _ease(_seg(u, 0.0, 0.45))
        curves = []
        for plate in plates + [emblem]:
            shown = [pt for pt in plate if pt[1] >= level]
            if len(shown) >= 2:
                curves.append(at(shown))
        for x in (-0.1, 0.1):
            zipper = at([(x, 1.0), (x, max(level, -0.05))])
            curves.append(zipper)
            splat(layer, float(zipper[-1][0]), float(zipper[-1][1]), 0.03 * scale, WHITE * 1.6, alpha, runtime.kernels)
        return curves
    if u < 0.75:  # completa: el emblema brilla al 100%
        curves = [at(plate) for plate in plates]
        badge = at(emblem)
        fill_polygon(layer, badge, np.asarray(color, np.float32), alpha * 0.7, 0.9, feather=1.5)
        glow = badge.mean(axis=0)
        splat(layer, float(glow[0]), float(glow[1]), 0.07 * scale * (1 + 0.2 * np.sin(frame_index)), WHITE * 1.8, alpha, runtime.kernels)
        return curves + [badge]
    # se desarma: las placas caen como gotas de luz hacia las piernas
    s = _seg(u, 0.75, 1.0)
    curves = []
    for n, plate in enumerate(plates + [emblem]):
        piece = at(plate)
        middle = piece.mean(axis=0)
        fall = down * (s * s * (0.6 + 0.08 * n)) * scale + across * np.sin(n * 2.1) * s * 0.1 * scale
        piece = middle + (piece - middle) * (1 - 0.8 * s) + fall
        curves.append(piece)
        splat(layer, float(piece.mean(axis=0)[0]), float(piece.mean(axis=0)[1]), 0.02 * scale + 1, WHITE * 1.4, alpha * (1 - s), runtime.kernels)
    return curves


# ----- el planeador de la sirena -----


def _glider(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    from vfxglow.engine.duo_doodles import zigzag
    from vfxglow.engine.duo_fx import fill_band, taper

    center, across, down = frame
    joints = {f"{s}_{j}": body.get(f"{s}_{j}") for s in ("left", "right") for j in ("wrist", "elbow", "shoulder", "hip")}
    if any(p is None for p in joints.values()):
        return []
    u = _phase(runtime, event)
    st = _activation(runtime, event, "glider", body)
    chest = center + down * 0.3 * scale
    if u >= 0.85:  # las alas se funden en un rayo de punta a punta de los brazos
        path = np.array([joints[k] for k in ("left_wrist", "left_elbow", "left_shoulder", "right_shoulder", "right_elbow", "right_wrist")])
        rng = np.random.default_rng(frame_index)
        return [zigzag(path, 0.05 * scale, rng, 0.05 * scale)]
    unfold = _ease(_seg(u, 0.0, 0.15))
    curves: list[np.ndarray] = []
    for s in ("left", "right"):
        wrist, elbow, shoulder, hip = (joints[f"{s}_{j}"] for j in ("wrist", "elbow", "shoulder", "hip"))
        tip = shoulder + (wrist - shoulder) * unfold
        root = shoulder + (hip - shoulder) * 0.85
        bend = shoulder + (elbow - shoulder) * unfold
        k = np.linspace(0, 1, 16)[:, None]  # borde de fuga: curva de la cintura a la punta
        control = root + (tip - root) * 0.6 + down * 0.05 * scale
        trailing = (1 - k) ** 2 * root + 2 * (1 - k) * k * control + k ** 2 * tip
        wing = np.vstack([np.array([tip, bend, shoulder, root]), trailing[1:]])
        fill_polygon(layer, wing, np.asarray(color, np.float32), alpha * 0.25, 0.9, feather=2.0)
        curves.append(wing)
        for at in (0.4, 0.7):  # costillas del ala, del hombro al borde de fuga
            curves.append(np.array([shoulder + (bend - shoulder) * at * 0.5, trailing[int(at * 15)]]))
        trail = st.setdefault(s, [])  # estela en la punta de los dedos, con retraso
        trail.append(wrist.copy())
        del trail[:-10]
        if len(trail) >= 3 and unfold > 0.9:
            fill_band(layer, np.array(trail), 0.012 * scale * taper(len(trail), 0.7) + 0.5, alpha * 0.6)
    for n in range(3):  # ondas de la sirena que salen del pecho
        age = ((frame_index + n * 8) % 24) / 24
        r = (0.5 + 1.6 * age) * scale
        spread = (1 - age) * 0.5  # al alejarse se acortan hasta apagarse
        for facing in (0.0, np.pi):  # a los dos costados, no sobre la cara
            a = np.linspace(facing - spread, facing + spread, 16)
            curves.append(chest + np.outer(np.cos(a) * r, across) + np.outer(np.sin(a) * r * 0.6, down))
    return curves


def critter(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event=None) -> list[np.ndarray]:
    if shape == "stick_man":
        return _stick_man(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "ufo":
        return _ufo(body, frame, scale, frame_index, runtime, layer, color, alpha, event, head)
    if shape == "snake":
        return _snake(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "water_balloon":
        return _water_balloon(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "spark_trap":
        return _spark_trap(body, frame, scale, frame_index, runtime, layer, color, alpha, event, head)
    if shape == "time_rope":
        return _time_rope(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "supersuit":
        return _supersuit(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "glider":
        return _glider(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
