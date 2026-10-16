"""Más metáforas con historia (adornos `type: adornment`, `style.shapes`), de docs/metaforas.md.

Como los de engine/critters.py: cada uno es una pequeña aventura sobre el cuerpo con escenario,
conflicto y final, según la fracción `u` del momento. Varios reaccionan al cuerpo de verdad (la
abeja huye de la mano que se acerca, la burbuja revienta con un movimiento fuerte, el pájaro sale
volando si el brazo se sacude).

- `yoyo`: una esfera con un hilo elástico rebota entre la mano y el piso; al final el hilo la
  recoge de golpe y se deshace en chispas (propuesta de Gemini, michael_jackson_dance seg. 37,6).
- `bee`: una abeja zumba en ochos alrededor de la cabeza y esquiva la mano; si las manos se juntan,
  la atrapan con un aplauso (estrellitas); si no, se va volando.
- `energy_ball`: una bola de energía se carga entre las manos con rayitos que la alimentan y sale
  disparada como un rayo ancho al final (kamehameha).
- `rocket`: un cohete despega de los pies con humo, sube por el cuerpo y explota en fuegos
  artificiales sobre la cabeza.
- `bird`: un pájaro llega volando, se posa en el antebrazo extendido, picotea y sale volando al
  final o si el brazo se sacude.
- `bubble`: una burbuja envuelve a la persona, tiembla con los movimientos pequeños y revienta con
  uno fuerte (o al final).

Propuestos por Gemini al leer dance_two_mens:

- `goddess_arms`: los brazos se copian en neón y se abren en abanico desde el hombro (seis brazos,
  como una diosa); las copias siguen al brazo real con un poco de retraso y al final se pliegan de
  golpe sobre él (seg. 25,8: el de atrás asoma brazos como si fueran del de adelante).
- `snap_cables`: cables de energía entre las manos de quien jala y los hombros o la espalda de la
  otra persona: flojos se comban, tensos vibran, y con el tirón (o al final) revientan con un
  latigazo (seg. 17,5-21,3: le arranca la chaqueta). Sin otra persona, de las manos a los propios
  hombros, como quien se arranca algo.

El estado entre cuadros se guarda en `runtime.swoosh["_critters"]`, por activación.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.raster import fill_polygon, splat

STORIES = ("yoyo", "bee", "energy_ball", "rocket", "bird", "bubble", "goddess_arms", "snap_cables")
# Rapidez de una articulación (en anchos de hombros por segundo) que cuenta como sacudida.
SHAKE = 2.5


def _speed(body, joint: str, scale: float) -> float:
    vel = body.points.get(f"vel:{body.prefix}{joint}")
    return float(np.linalg.norm(vel)) / max(scale, 1e-6) if vel is not None else 0.0


def _ellipse(center, rx, ry, axis_x, axis_y, n: int = 32, start: float = 0.0, stop: float = TAU) -> np.ndarray:
    t = np.linspace(start, stop, n)
    return center + np.outer(np.cos(t) * rx, axis_x) + np.outer(np.sin(t) * ry, axis_y)


def _burst(layer, at, scale, s, rng_seed, count, color, alpha, runtime, reach=0.6) -> list[np.ndarray]:
    """Rayos que salen de `at` con una chispa en la punta (s: 0 al nacer, 1 apagado)."""
    rng = np.random.default_rng(rng_seed)
    lines = []
    for _ in range(count):
        angle = rng.uniform(0, TAU)
        d = np.array([np.cos(angle), np.sin(angle)])
        far = rng.uniform(0.6, 1.0) * reach * scale
        tip = at + d * far * _ease(min(s * 1.6, 1.0))
        tail = at + d * far * max(s * 1.6 - 0.5, 0.0)
        if s < 0.95:
            lines.append(np.array([tail, tip]))
        splat(layer, float(tip[0]), float(tip[1]), 0.02 * scale + 1, WHITE * 1.5, alpha * (1 - s), runtime.kernels)
    return lines


# ----- el yo-yo de gravedad -----


def _yoyo(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    center, across, down = frame
    st = _activation(runtime, event, "yoyo", body)
    wrists = {s: body.get(f"{s}_wrist") for s in ("left", "right")}
    if any(w is None for w in wrists.values()):
        return []
    # La mano que hace el gesto: la más alta (la otra cuelga); se decide en el arranque y se queda.
    side = st.get("side") or min(wrists, key=lambda s: float(np.dot(wrists[s] - center, down)))
    if _phase(runtime, event) > 0.1:
        st["side"] = side
    hand = wrists[side]
    feet = [p for p in (body.get("left_ankle"), body.get("right_ankle")) if p is not None]
    floor = max(float(np.dot(f - center, down)) for f in feet) if feet else float(np.dot(hand - center, down)) + 1.5 * scale
    reach = max(floor - float(np.dot(hand - center, down)), 0.3 * scale)
    u = _phase(runtime, event)
    r = 0.09 * scale
    if u >= 0.85:  # el hilo la recoge de golpe y se deshace en chispas en la mano
        s = _seg(u, 0.85, 1.0)
        pos = hand + down * reach * 0.5 * (1 - _ease(min(s * 2.5, 1.0)))
        if s < 0.4:
            return [np.array([hand, pos]), _ellipse(pos, r, r, across, down)]
        return _burst(layer, hand, scale, (s - 0.4) / 0.6, int(hand[0]) % 997, 10, color, alpha, runtime, 0.4)
    bounce = abs(np.sin(frame_index * np.pi / 12))  # baja y sube al ritmo (medio segundo a 25 fps)
    depth = reach * (0.15 + 0.85 * bounce) * _ease(_seg(u, 0.0, 0.1))
    pos = hand + down * (depth - r)
    hit = bounce > 0.93  # contra el piso: se aplasta y suelta polvo de luz
    squash = 0.6 if hit else (1.0 + 0.25 * abs(np.cos(frame_index * np.pi / 12)))
    ball = _ellipse(pos, r / np.sqrt(squash), r * squash, across, down)
    fill_polygon(layer, ball, np.asarray(color, np.float32), alpha * 0.5, 0.9, feather=1.5)
    sway = across * np.sin(frame_index * 0.3) * 0.04 * scale
    string = np.array([hand + (pos - hand) * k + sway * np.sin(k * np.pi) for k in np.linspace(0, 1, 12)])
    lines = [string, ball]
    if hit:
        for side in (-1, 1):
            dust = pos + down * r + across * side * r * 1.2
            lines.append(np.array([dust, dust + across * side * 0.15 * scale - down * 0.05 * scale]))
    return lines


# ----- la abeja -----


def _bee_body(pos, heading, size, frame_index, layer, color, alpha) -> list[np.ndarray]:
    d = heading / max(float(np.linalg.norm(heading)), 1e-6)
    n = np.array([-d[1], d[0]])
    body = _ellipse(pos, size, size * 0.6, d, n, 24)
    fill_polygon(layer, body, np.asarray(color, np.float32), alpha * 0.5, 0.9, feather=1.0)
    stripes = [np.array([pos + d * k * size + n * size * 0.55, pos + d * k * size - n * size * 0.55]) for k in (-0.3, 0.15)]
    flap = 0.6 + 0.4 * abs(np.sin(frame_index * 1.9))  # las alas baten
    wings = [_ellipse(pos - n * size * 0.9 * side + d * size * 0.1, size * 0.45, size * 0.7 * flap, d, n, 16) for side in (-1, 1)]
    sting = np.array([pos - d * size, pos - d * size * 1.4])
    return [body, *stripes, *wings, sting]


def _bee(body, frame, scale, frame_index, runtime, layer, color, alpha, event, head) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    st = _activation(runtime, event, "bee", body)
    head = head if head is not None else center + up * 0.6 * scale
    hands = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
    u = _phase(runtime, event)
    size = 0.14 * scale
    if st.get("caught") is not None:  # atrapada con un aplauso: estrellitas
        s = min((frame_index - st["caught_at"]) / 10.0, 1.0)
        return _burst(layer, st["caught"], scale, s, 31, 8, color, alpha, runtime, 0.35)
    if len(hands) == 2 and u > 0.35 and np.linalg.norm(hands[0] - hands[1]) < 0.3 * scale and np.linalg.norm(st.get("pos", head) - (hands[0] + hands[1]) / 2) < 0.6 * scale:
        st["caught"], st["caught_at"] = (hands[0] + hands[1]) / 2, frame_index
        return []
    t = frame_index * 0.18
    target = head + across * np.sin(t) * 0.9 * scale + up * (0.35 + 0.3 * np.sin(2 * t)) * scale  # en ochos
    if u > 0.85:  # se va volando
        target = target + up * _seg(u, 0.85, 1.0) * 3.0 * scale + across * _seg(u, 0.85, 1.0) * 1.5 * scale
    pos = st.get("pos", head + up * 0.8 * scale)
    for hand in hands:  # esquiva la mano que se le acerca
        away = pos - hand
        dist = float(np.linalg.norm(away))
        if dist < 0.45 * scale:
            target = target + away / max(dist, 1e-6) * (0.45 * scale - dist) * 2.5
    jitter = np.array([np.sin(frame_index * 2.7), np.cos(frame_index * 3.1)]) * 0.02 * scale
    new = pos + (target - pos) * 0.3 + jitter
    heading = new - pos if np.linalg.norm(new - pos) > 0.5 else st.get("heading", across)
    trail = st.setdefault("trail", [])
    trail.append(new.copy())
    del trail[:-8]
    st.update(pos=new, heading=heading)
    lines = _bee_body(new, heading, size, frame_index, layer, color, alpha)
    for k, dot in enumerate(trail[:-2:2]):  # estela punteada del zumbido
        splat(layer, float(dot[0]), float(dot[1]), 0.008 * scale + 1, np.asarray(color, np.float32) * 1.2, alpha * (k + 1) / 5, runtime.kernels)
    return lines


# ----- la bola de energía -----


def _energy_ball(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    from vfxglow.engine.duo_doodles import zigzag
    from vfxglow.engine.duo_fx import fill_band, taper

    center, across, down = frame
    wrists = {s: body.get(f"{s}_wrist") for s in ("left", "right")}
    if any(w is None for w in wrists.values()):
        return []
    st = _activation(runtime, event, "ball", body)
    together = float(np.linalg.norm(wrists["left"] - wrists["right"])) < 0.6 * scale
    if together:  # kamehameha: entre las dos manos
        core = (wrists["left"] + wrists["right"]) / 2
    else:  # lanzamiento con una mano: en la más rápida (o la más separada del cuerpo)
        side = st.get("side") or max(wrists, key=lambda s: _speed(body, f"{s}_wrist", scale) + abs(float(np.dot(wrists[s] - center, across))) / scale)
        st["side"] = side
        core = wrists[side]
    u = _phase(runtime, event)
    rng = np.random.default_rng(frame_index)
    if u < 0.65:  # se carga: crece, gira y la alimentan rayitos desde afuera
        s = _ease(_seg(u, 0.0, 0.65))
        r = (0.08 + 0.22 * s) * scale * (1 + 0.06 * np.sin(frame_index * 1.3))
        vel = body.points.get(f"vel:{body.prefix}{st.get('side', 'right')}_wrist")
        if vel is not None and float(np.linalg.norm(vel)) > 0.5 * scale:
            st["aim"] = vel / float(np.linalg.norm(vel))  # hacia donde va la mano
        st["core"], st["r"] = core, r
        ball = _ellipse(core, r, r, across, down)
        fill_polygon(layer, ball, np.asarray(color, np.float32), alpha * 0.55, 0.9, feather=3.0)
        splat(layer, float(core[0]), float(core[1]), r * 0.6, WHITE * 1.6, alpha, runtime.kernels)
        lines = [ball, _ellipse(core, r * 1.25, r * 0.45, across, down, 24, frame_index * 0.4, frame_index * 0.4 + TAU * 0.6)]
        for _ in range(3):
            angle = rng.uniform(0, TAU)
            d = np.array([np.cos(angle), np.sin(angle)])
            lines.append(zigzag(np.array([core + d * r * 2.4, core + d * r]), 0.03 * scale, rng, 0.04 * scale))
        return lines
    # sale disparada: un rayo ancho hacia donde iba la mano (o del pecho hacia la mano)
    s = _seg(u, 0.65, 1.0)
    start = st.get("core", core)
    d = st.get("aim")
    if d is None:
        out = start - (center + down * 0.3 * scale)
        d = out / max(float(np.linalg.norm(out)), 1e-6) if float(np.linalg.norm(out)) > 0.2 * scale else across
    length = (0.5 + 3.5 * _ease(min(s * 1.5, 1.0))) * scale
    beam = np.array([start + d * k for k in np.linspace(0, length, 20)])
    width = st.get("r", 0.2 * scale) * (1 - 0.6 * s) * (0.5 + 0.5 * np.linspace(1.0, 0.4, 20))
    fill_band(layer, beam, width, alpha * (1 - s * 0.5))
    tip = beam[-1]
    splat(layer, float(tip[0]), float(tip[1]), 0.15 * scale * (1 - s), WHITE * 1.8, alpha, runtime.kernels)
    n = np.array([-d[1], d[0]])
    return [beam + n * width[:, None], beam - n * width[:, None]]


# ----- el cohete -----


def _rocket_shape(pos, up, size, frame_index, layer, color, alpha) -> list[np.ndarray]:
    side = np.array([-up[1], up[0]])
    nose = pos + up * size * 1.2
    hull = np.array([
        nose, pos + up * size * 0.5 + side * size * 0.35, pos - up * size * 0.6 + side * size * 0.35,
        pos - up * size * 0.6 - side * size * 0.35, pos + up * size * 0.5 - side * size * 0.35, nose,
    ])
    fill_polygon(layer, hull, np.asarray(color, np.float32), alpha * 0.45, 0.9, feather=1.0)
    fins = [np.array([pos - up * size * 0.2 + s * side * size * 0.35, pos - up * size * 0.8 + s * side * size * 0.7, pos - up * size * 0.6 + s * side * size * 0.35]) for s in (-1, 1)]
    window = _ellipse(pos + up * size * 0.35, size * 0.15, size * 0.15, side, up, 14)
    flick = 0.7 + 0.3 * abs(np.sin(frame_index * 2.3))  # la llama parpadea
    flame = np.array([pos - up * size * 0.6 + side * size * 0.22, pos - up * size * (0.6 + 0.9 * flick), pos - up * size * 0.6 - side * size * 0.22])
    return [hull, *fins, window, flame]


def _rocket(body, frame, scale, frame_index, runtime, layer, color, alpha, event, head) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    feet = [p for p in (body.get("left_ankle"), body.get("right_ankle")) if p is not None]
    base = np.mean(feet, axis=0) if feet else center + down * 2.0 * scale
    top = (head if head is not None else center + up * 0.6 * scale) + up * 0.7 * scale
    path = np.array([base, (base + center) / 2 + down * 0.3 * scale, center, top])
    st = _activation(runtime, event, "rocket", body)
    u = _phase(runtime, event)
    size = 0.22 * scale
    smoke = st.setdefault("smoke", [])
    if u < 0.7:  # despega con humo y sube por el cuerpo
        s = _ease(_seg(u, 0.12, 0.7))
        k = min(int(s * (len(path) - 1)), len(path) - 2)
        local = s * (len(path) - 1) - k
        pos = path[k] + (path[k + 1] - path[k]) * local
        if frame_index % 2 == 0:
            smoke.append((pos - up * size * 0.9, frame_index))
        del smoke[:-14]
        lines = _rocket_shape(pos + across * np.sin(frame_index * 1.7) * 0.01 * scale * (u < 0.12), up, size, frame_index, layer, color, alpha)
        for at, born in smoke:  # bocanadas que crecen y se apagan
            age = (frame_index - born) / 14.0
            if 0 <= age < 1:
                lines.append(_ellipse(at + across * np.sin(born) * 0.1 * scale * age, (0.04 + 0.1 * age) * scale, (0.04 + 0.1 * age) * scale, across, up, 14))
        return lines
    # fuegos artificiales sobre la cabeza
    s = _seg(u, 0.7, 1.0)
    lines = _burst(layer, top, scale, s, 7, 14, color, alpha, runtime, 1.1)
    if s > 0.3:
        lines += _burst(layer, top + across * 0.5 * scale + up * 0.2 * scale, scale, (s - 0.3) / 0.7, 11, 9, color, alpha, runtime, 0.6)
    return lines


# ----- el pájaro -----


def _bird_shape(pos, facing, flap, perched, size, layer, color, alpha) -> list[np.ndarray]:
    up = np.array([0.0, -1.0])
    f = np.array([facing, 0.0])
    body = _ellipse(pos, size, size * 0.55, f, up, 22)
    fill_polygon(layer, body, np.asarray(color, np.float32), alpha * 0.5, 0.9, feather=1.0)
    head_at = pos + f * size * 0.95 + up * size * 0.45
    head = _ellipse(head_at, size * 0.32, size * 0.32, f, up, 14)
    beak = np.array([head_at + f * size * 0.28 + up * size * 0.08, head_at + f * size * 0.62, head_at + f * size * 0.28 - up * size * 0.08])
    tail = np.array([pos - f * size * 0.9, pos - f * size * 1.5 + up * size * 0.25, pos - f * size * 1.45 - up * size * 0.05])
    lift = up * size * 1.1 * flap
    wing = np.array([pos - f * size * 0.2, pos + lift - f * size * 0.5, pos + lift * 0.6 + f * size * 0.25, pos + f * size * 0.2])
    lines = [body, head, beak, tail, wing]
    if perched:
        for k in (-0.2, 0.2):
            leg = pos + f * size * k - up * size * 0.5
            lines.append(np.array([leg, leg - up * size * 0.4]))
    return lines


def _bird(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    from vfxglow.engine.critters import _sides

    center, across, down = frame
    up = -down
    sides = _sides(body, center)
    if sides is None:
        return []
    st = _activation(runtime, event, "bird", body)
    out = st.setdefault("side", sides[0])  # se posa en un brazo y se queda en ese
    wrist, elbow = body.get(f"{out}_wrist"), body.get(f"{out}_elbow")
    if wrist is None or elbow is None:
        return []
    u = _phase(runtime, event)
    size = 0.22 * scale
    hop = 0.35 + 0.25 * np.sin(frame_index * 0.25)  # salta de un lado a otro del antebrazo
    perch = elbow + (wrist - elbow) * hop - down * size * 0.9
    facing = 1.0 if wrist[0] >= elbow[0] else -1.0
    scared = st.get("scared") or (u > 0.2 and _speed(body, f"{out}_wrist", scale) > SHAKE)
    st["scared"] = scared
    if u < 0.2:  # llega volando desde arriba
        s = _ease(_seg(u, 0.0, 0.2))
        start = perch + up * 2.0 * scale - across * facing * 1.2 * scale
        pos = start + (perch - start) * s
        return _bird_shape(pos, facing, np.sin(frame_index * 1.6), False, size, layer, color, alpha)
    if not scared and u < 0.8:  # posado: picotea de vez en cuando
        peck = 0.25 if (frame_index // 6) % 3 == 0 else 0.0
        st["pos"] = perch
        return _bird_shape(perch - up * size * peck, facing, 0.15, True, size, layer, color, alpha)
    if "left_at" not in st:
        st["left_at"] = frame_index
    s = min((frame_index - st["left_at"]) / 20.0, 1.0)  # sale volando hacia arriba
    pos = st.get("pos", perch) + up * 2.2 * scale * _ease(s) + across * facing * 0.8 * scale * s
    lines = _bird_shape(pos, facing, np.sin(frame_index * 1.8), False, size * (1 - 0.3 * s), layer, color, alpha * (1 - max(s - 0.8, 0) / 0.2))
    if s < 0.4:  # plumitas que caen
        for k in (-1, 1):
            feather = st.get("pos", perch) + across * k * 0.1 * scale + down * s * 0.5 * scale
            lines.append(np.array([feather, feather + across * 0.04 * scale + down * 0.03 * scale]))
    return lines


# ----- la burbuja -----


def _bubble(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    center, across, down = frame
    names = ("nose", "left_wrist", "right_wrist", "left_elbow", "right_elbow", "left_ankle", "right_ankle", "left_hip", "right_hip")
    pts = np.array([p for p in (body.get(n) for n in names) if p is not None])
    if len(pts) < 4:
        return []
    st = _activation(runtime, event, "bubble", body)
    u = _phase(runtime, event)
    middle = (pts.min(axis=0) + pts.max(axis=0)) / 2
    half = (pts.max(axis=0) - pts.min(axis=0)) / 2 + 0.35 * scale
    rx, ry = float(half[0]), float(half[1])
    motion = max(_speed(body, j, scale) for j in ("left_wrist", "right_wrist", "left_ankle", "right_ankle"))
    if "popped" not in st and u > 0.25 and (motion > SHAKE * 1.2 or u > 0.9):
        st["popped"] = frame_index
    if "popped" in st:  # revienta: pedazos de la burbuja que salen despedidos y gotitas
        s = min((frame_index - st["popped"]) / 10.0, 1.0)
        lines = []
        for k in range(10):
            a = k * TAU / 10
            d = np.array([np.cos(a), np.sin(a)])
            arc = _ellipse(st.get("middle", middle) + d * s * 0.5 * scale, rx * (1 + 0.3 * s), ry * (1 + 0.3 * s), across, down, 6, a - 0.15 * (1 - s), a + 0.15 * (1 - s))
            if s < 0.9:
                lines.append(arc)
        lines += _burst(layer, st.get("middle", middle), scale, s, 5, 6, color, alpha, runtime, 0.3)
        return lines
    st["middle"] = middle
    grow = _ease(_seg(u, 0.0, 0.15))
    wobble = 0.03 + 0.05 * min(motion / SHAKE, 1.0)  # tiembla más cuanto más se mueve
    t = np.linspace(0, TAU, 60)
    ripple = 1 + wobble * np.sin(3 * t + frame_index * 0.5) + wobble * 0.6 * np.sin(5 * t - frame_index * 0.7)
    shell = middle + np.outer(np.cos(t) * rx * ripple * grow, across) + np.outer(np.sin(t) * ry * ripple * grow, down)
    shine = _ellipse(middle, rx * 0.8 * grow, ry * 0.85 * grow, across, down, 14, np.pi * 1.1, np.pi * 1.4)
    glint = middle - across * rx * 0.55 * grow - down * ry * 0.6 * grow
    splat(layer, float(glint[0]), float(glint[1]), 0.04 * scale, WHITE * 1.4, alpha * 0.8, runtime.kernels)
    return [shell, shine]


# ----- los brazos de diosa -----


def _turn(points: np.ndarray, pivot: np.ndarray, angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    rel = points - pivot
    return pivot + np.stack([rel[:, 0] * c - rel[:, 1] * s, rel[:, 0] * s + rel[:, 1] * c], axis=1)


def _limb(shoulder, elbow, wrist, n: int = 18) -> np.ndarray:
    """Curva suave del hombro a la muñeca que pasa por el codo (cuadrática)."""
    control = 2 * elbow - (shoulder + wrist) / 2
    q = np.linspace(0, 1, n)[:, None]
    return (1 - q) ** 2 * shoulder + 2 * (1 - q) * q * control + q ** 2 * wrist


def _goddess_arms(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    from vfxglow.engine.duo_fx import fill_band, taper

    center = frame[0]
    st = _activation(runtime, event, "goddess", body)
    u = _phase(runtime, event)
    if u < 0.2:  # se abren en abanico
        spread = _ease(_seg(u, 0.0, 0.2))
    elif u < 0.85:
        spread = 1.0 + 0.08 * np.sin(frame_index * 0.35)  # respiran
    else:  # se pliegan de golpe sobre el brazo real
        spread = 1.0 - _ease(_seg(u, 0.85, 0.95))
    lines: list[np.ndarray] = []
    for side in ("left", "right"):
        joints = [body.get(f"{side}_{j}") for j in ("shoulder", "elbow", "wrist")]
        if any(j is None for j in joints):
            continue
        arm = np.array(joints)
        outward = 1.0 if arm[0][0] >= center[0] else -1.0  # hacia qué lado de la imagen queda este brazo
        history = st.setdefault(side, [])
        history.append(arm.copy())
        del history[:-9]
        for k, turn in enumerate((0.5, -0.5)):  # una copia arriba y otra abajo: seis brazos en total
            echo = history[max(len(history) - 1 - 3 * (k + 1), 0)]  # cada copia va un poco atrasada
            echo = echo - echo[0] + arm[0]  # pero sale del hombro de ahora
            copy = _turn(echo, arm[0], turn * spread * outward)
            if (copy[2][0] - center[0]) * outward < (arm[0][0] - center[0]) * outward * 0.8:
                continue  # cruzaría el cuerpo (o la cara): esa copia no se dibuja
            curve = _limb(*copy)
            width = 0.05 * scale * (1.0 - 0.25 * k) * (0.55 + 0.45 * np.linspace(1.0, 0.6, len(curve)))
            fill_band(layer, curve, width * max(spread, 0.0), alpha * (0.5 - 0.12 * k))
            tangent = np.gradient(curve, axis=0)
            normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
            normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)
            for s in (-1, 1):  # el contorno del brazo, no una línea por el centro
                lines.append(curve + normal * width[:, None] * s * 1.3)
            d = (copy[2] - copy[1]) / max(float(np.linalg.norm(copy[2] - copy[1])), 1e-6)
            palm = copy[2] + d * 0.06 * scale
            ring = np.linspace(0, TAU, 14)
            lines.append(palm + np.stack([np.cos(ring), np.sin(ring)], axis=1) * 0.045 * scale)
            side_n = np.array([-d[1], d[0]])
            for f in (-1.2, -0.4, 0.4, 1.2):  # dedos abiertos en abanico
                ray = d + side_n * f * 0.45
                ray /= float(np.linalg.norm(ray))
                lines.append(np.array([palm + ray * 0.045 * scale, palm + ray * 0.12 * scale]))
    if 0.85 <= u < 0.97:  # destello al plegarse
        for side in ("left", "right"):
            wrist = body.get(f"{side}_wrist")
            if wrist is not None:
                splat(layer, float(wrist[0]), float(wrist[1]), 0.12 * scale, WHITE * 1.6, alpha, runtime.kernels)
    return lines


# ----- los cables que se rompen -----


def _partner_points(body) -> dict[str, np.ndarray]:
    """Hombros y nuca de la otra persona más cercana a las manos de esta (de donde sale la prenda
    que le arrancan), o los propios."""
    own = body.prefix
    wrists = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
    best, best_d = {}, float("inf")
    people = {key.split(":", 1)[0] for key in body.points if key.startswith("person_") and ":" in key}
    for person in people:
        if f"{person}:" == own:
            continue
        pts = {j: body.points.get(f"{person}:{j}") for j in ("left_shoulder", "right_shoulder", "neck", "mid_shoulder")}
        pts = {j: p for j, p in pts.items() if p is not None}
        if len(pts) < 2 or not wrists:
            continue
        d = min(float(np.linalg.norm(w - p)) for w in wrists for p in pts.values())
        if d < best_d:
            best, best_d = pts, d
    if not best:  # sin pareja: de las manos a los propios hombros
        best = {j: body.get(j) for j in ("left_shoulder", "right_shoulder") if body.get(j) is not None}
    return best


def _snap_cables(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    center, across, down = frame
    wrists = [p for p in (body.get("left_wrist"), body.get("right_wrist")) if p is not None]
    anchors = _partner_points(body)
    if not wrists or not anchors:
        return []
    st = _activation(runtime, event, "cables", body)
    u = _phase(runtime, event)
    pairs = []
    shoulders = list(anchors.values())
    line = (min(shoulders, key=lambda p: p[0]), max(shoulders, key=lambda p: p[0]))
    for w in wrists:  # cada mano, a tres puntos repartidos por la línea de hombros: una telaraña
        pairs += [(w, line[0] + (line[1] - line[0]) * f) for f in (0.1, 0.5, 0.9)]
    spans = [float(np.linalg.norm(a - w)) for w, a in pairs]
    mean = float(np.mean(spans))
    st.setdefault("rest", mean)
    stretch = mean / max(st["rest"], 1e-6)
    if "snap" not in st and u > 0.3 and (stretch > 2.2 or u > 0.85):  # el tirón fuerte, o el final
        st["snap"] = frame_index
    lines: list[np.ndarray] = []
    rng = np.random.default_rng(frame_index)
    if "snap" in st:  # revientan: cada mitad vuelve a su extremo con un latigazo
        age = frame_index - st["snap"]
        if age > 10:
            return []
        s = age / 10.0
        for k, (w, a) in enumerate(pairs):
            mid = (w + a) / 2
            for end in (w, a):
                tip = mid + (end - mid) * _ease(min(s * 1.4, 1.0))
                axis = end - tip
                n = np.array([-axis[1], axis[0]]) / max(float(np.linalg.norm(axis)), 1e-6)
                whip = np.array([tip + axis * q + n * np.sin(q * np.pi * 3 + k) * 0.06 * scale * (1 - s) for q in np.linspace(0, 1, 12)])
                lines.append(whip)
            if age < 3:
                splat(layer, float(mid[0]), float(mid[1]), 0.12 * scale, WHITE * 1.8, alpha, runtime.kernels)
        return lines
    tension = float(np.clip((stretch - 1.0) / 0.6, 0.0, 1.0))
    grow = _ease(_seg(u, 0.0, 0.15))  # los cables brotan de las manos
    for k, (w, a) in enumerate(pairs):
        end = w + (a - w) * grow
        axis = end - w
        n = np.array([-axis[1], axis[0]]) / max(float(np.linalg.norm(axis)), 1e-6)
        q = np.linspace(0, 1, 18)
        sag = (1 - tension) * 0.12 * scale * np.sin(q * np.pi)  # flojos se comban
        buzz = tension * 0.025 * scale * np.sin(q * np.pi * 4 + frame_index * 2.1 + k)  # tensos vibran
        cable = w + np.outer(q, axis) + np.outer(sag, down) + np.outer(buzz, n)
        lines.append(cable)
        if tension > 0.4:  # chispas que corren por el cable
            spot = cable[int(rng.integers(2, 16))]
            splat(layer, float(spot[0]), float(spot[1]), 0.02 * scale + 1, WHITE * 1.5, alpha, runtime.kernels)
    return lines


def story(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event=None) -> list[np.ndarray]:
    if shape == "yoyo":
        return _yoyo(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "bee":
        return _bee(body, frame, scale, frame_index, runtime, layer, color, alpha, event, head)
    if shape == "energy_ball":
        return _energy_ball(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "rocket":
        return _rocket(body, frame, scale, frame_index, runtime, layer, color, alpha, event, head)
    if shape == "bird":
        return _bird(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "bubble":
        return _bubble(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "goddess_arms":
        return _goddess_arms(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "snap_cables":
        return _snap_cables(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
