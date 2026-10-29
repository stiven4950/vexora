"""Brazos, manos y lo que sostienen: efectos de la referencia video_41 (docs/referencias/video_41.md).

Adornos (`type: adornment`, `style.shapes`), como los de engine/duo_fx.py y engine/solo_fx.py:

- walk_slash: al caminar, cada paso es un tajo: una banda ancha que cruza el torso en diagonal, del
  hombro de la derecha de la imagen a la cadera de la izquierda, y se desliza hacia abajo
  (seg. 2,0-4,1). Es siempre la misma diagonal.
- spray_can: un aerosol en la mano que rocía una nube blanca hacia adelante; la nube crece y se abre
  con salpicaduras (seg. 5,0-5,9). camera_flash: la variante de flash de cámara, un destello que
  sale de la mano y se apaga.
- hook_ball: el contorno de la mano se recoge en una pelota que se aplasta con la velocidad de la
  mano y al final se vuelve un gancho ("C"), el gancho de la muerte (seg. 7,3-7,6).
- zipper_line: una línea sube por un brazo, baja por el cierre de la chaqueta y sube por el otro
  brazo hasta la mano (seg. 6,7-7,1).
- charge_bar: el antebrazo como una barra de carga: segmentos que se llenan del codo a la mano y
  vuelven a empezar (seg. 10,0-11,3).
- profile_head: la cabeza dibujada en línea, con la oreja y el cuello (seg. 8,2).
- fan: con las manos juntas sobre la cabeza que se separan, un abanico que se abre (seg. 14,0).
- hand_lines: una línea por mano que se juntan en una punta sobre la cara: un triángulo que se abre
  y se cierra con las manos (seg. 15,6-15,9).
- bubble_blow: una burbuja sale de la boca, crece y pasa a estar entre las manos, que la manejan; al
  final revienta en gotitas (seg. 16,5-17,9).
- wave_pull: una ola bajo el antebrazo que va y viene con él; cuando la mano cambia de dirección, se
  va por la mano y reaparece arqueada del otro lado (seg. 18,0-19,3).
- paint_relay: se pinta de neón la parte del cuerpo que se mueve más, y el relleno pasa a la
  siguiente cuando el foco cambia (seg. 20,0-20,9).
- arrows_mask: flechas "^" que suben por el antebrazo y, al llegar a la cabeza, se vuelven la
  máscara: el contorno de la cara con ojos redondos (seg. 21,4-21,9).
"""

from __future__ import annotations

import zlib

import cv2
import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.duo_fx import fill_band, taper
from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
ARM_FX = ("walk_slash", "spray_can", "camera_flash", "hook_ball", "zipper_line", "charge_bar", "profile_head", "fan", "hand_lines", "bubble_blow", "wave_pull", "paint_relay", "arrows_mask")
# Segmentos de la barra de carga y fotogramas que tarda en llenarse.
CHARGE_SEGMENTS = 5
CHARGE_FRAMES = 12
# Velocidad de la mano (anchos de hombros por fotograma) a la que la pelota se aplasta del todo.
SQUASH_SPEED = 0.25


def _side(body, event) -> str:
    for side in ("left", "right"):
        if event is not None and (event.kind == side or event.target.endswith(f":{side}") or f"{side}_" in event.target):
            return side
    speeds = {s: float(np.linalg.norm(_vel(body, f"{s}_wrist"))) for s in ("left", "right")}
    return max(speeds, key=speeds.get) if abs(speeds["left"] - speeds["right"]) > 1e-6 else "right"


def _vel(body, joint: str) -> np.ndarray:
    vel = body.points.get(f"vel:{body.prefix}{joint}")
    return np.asarray(vel, dtype=np.float64) if vel is not None else np.zeros(2)


def _hand(body, side: str) -> np.ndarray | None:
    knuckle = body.get(f"{side}_middle_mcp")
    return knuckle if knuckle is not None else body.get(f"{side}_wrist")


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-6 else np.array([1.0, 0.0])


def _circle(center: np.ndarray, rx: float, ry: float | None = None, n: int = 28, axis: np.ndarray | None = None) -> np.ndarray:
    t = np.linspace(0, TAU, n)
    a = _unit(axis) if axis is not None else np.array([1.0, 0.0])
    b = np.array([-a[1], a[0]])
    return center + np.outer(np.cos(t) * rx, a) + np.outer(np.sin(t) * (ry if ry is not None else rx), b)


def _walk_slash(body, frame, scale, runtime, layer, alpha, event) -> list[np.ndarray]:
    ls, rs, lh, rh = (body.get(n) for n in ("left_shoulder", "right_shoulder", "left_hip", "right_hip"))
    if any(p is None for p in (ls, rs, lh, rh)):
        return []
    # Del hombro de la derecha de la imagen a la cadera de la izquierda, siempre la misma diagonal
    # (video_41 seg. 2,0-4,1), cruzando todo el torso de lado a lado.
    shoulders, hips = sorted((ls, rs), key=lambda p: p[0]), sorted((lh, rh), key=lambda p: p[0])
    a, b = shoulders[1] - (shoulders[0] - shoulders[1]) * 0.15, hips[0] - (hips[1] - hips[0]) * 0.8
    u = _phase(runtime, event)
    d = _unit(b - a)
    normal = np.array([-d[1], d[0]])
    if normal[1] < 0:
        normal = -normal
    slide = (_ease(_seg(u, 0.0, 0.8)) - 0.6) * 0.7 * scale  # se desliza hacia abajo, de lado
    q = np.linspace(-0.2, 1.0, 30)[:, None]
    curve = a + (b - a) * q + normal * slide
    widths = 0.38 * scale * taper(len(curve), 0.3).clip(0.3, 1.0) * (1.0 - 0.6 * _seg(u, 0.7, 1.0))
    fill_band(layer, curve, widths, alpha)
    return [curve]


def _spray(shape, body, scale, frame_index, runtime, layer, color, alpha, event, rng) -> list[np.ndarray]:
    side = _side(body, event)
    wrist, elbow = body.get(f"{side}_wrist"), body.get(f"{side}_elbow")
    if wrist is None or elbow is None:
        return []
    ahead = _unit(wrist - elbow)
    u = _phase(runtime, event)
    tint = np.asarray(color, np.float32)
    if shape == "camera_flash":
        flash = np.sin(np.pi * _seg(u, 0.1, 0.6))
        at = wrist + ahead * 0.15 * scale
        splat(layer, float(at[0]), float(at[1]), (0.15 + 0.6 * flash) * scale, WHITE * 0.9, alpha * flash, runtime.kernels)
        body_ = _circle(wrist, 0.12 * scale, 0.08 * scale, 16, ahead)
        return [body_] if u < 0.7 else []
    side_axis = np.array([-ahead[1], ahead[0]])
    can = wrist + ahead * 0.02 * scale
    w, h = 0.07 * scale, 0.22 * scale
    lines = [np.array([can - side_axis * w, can - side_axis * w - ahead * h, can + side_axis * w - ahead * h, can + side_axis * w, can - side_axis * w])]
    nozzle = can + ahead * 0.05 * scale
    lines.append(np.array([can, nozzle]))
    spray = _seg(u, 0.1, 0.75)
    if spray > 0:  # la nube blanca, rellena y con bordes de nube, que crece frente a la boquilla
        t = np.linspace(0, TAU, 60)
        lump = 1.0 + 0.18 * np.abs(np.sin(t * 3.5 + frame_index * 0.2))
        r = (0.15 + 0.45 * spray) * scale * lump
        cloud = nozzle + ahead * r.mean() * 0.8 + np.stack([np.cos(t) * r, np.sin(t) * r], axis=1)
        fill_polygon(layer, cloud, WHITE * 0.9 + tint * 0.15, alpha * 0.85 * (1 - _seg(u, 0.8, 1.0)), 1.0, feather=2.0)
    for _ in range(int(60 * spray)):  # la nube: muchas gotas finas en un cono
        r = rng.uniform(0.1, 1.0) * (0.3 + 1.1 * spray) * scale
        angle = rng.normal(0.0, 0.35 + 0.3 * spray)
        d = ahead * np.cos(angle) + side_axis * np.sin(angle)
        at = nozzle + d * r
        splat(layer, float(at[0]), float(at[1]), (0.05 + 0.1 * spray) * scale, WHITE * 0.55 + tint * 0.25, alpha * 0.5 * (1 - _seg(u, 0.8, 1.0)), runtime.kernels)
    if u > 0.75:  # salpicaduras al abrirse
        burst = _seg(u, 0.75, 1.0)
        for k in range(8):
            angle = TAU * k / 8
            at = nozzle + ahead * 0.9 * scale + np.array([np.cos(angle), np.sin(angle)]) * (0.3 + 0.4 * burst) * scale
            splat(layer, float(at[0]), float(at[1]), 0.025 * scale, WHITE * 0.6, alpha * (1 - burst), runtime.kernels)
    return lines


def _hook_ball(body, scale, runtime, layer, alpha, event) -> list[np.ndarray]:
    side = _side(body, event)
    hand = _hand(body, side)
    if hand is None:
        return []
    u = _phase(runtime, event)
    vel = _vel(body, f"{side}_wrist")
    speed = float(np.linalg.norm(vel)) / max(scale, 1e-6)
    squash = float(np.clip(speed / SQUASH_SPEED, 0.0, 1.0))
    r = 0.12 * scale
    if u < 0.65:  # la pelota, aplastada en la dirección de la mano
        ball = _circle(hand, r * (1 + 0.9 * squash), r * (1 - 0.45 * squash), 28, vel if speed > 1e-6 else None)
        fill_polygon(layer, ball, WHITE * 0.9, alpha * 0.8, 1.0, feather=1.2)
        return [np.vstack([ball, ball[:1]])]
    hook = _ease(_seg(u, 0.65, 0.8))  # se abre en un gancho
    t = np.linspace(0.6 + 1.2 * (1 - hook), TAU - 0.6 - 1.2 * (1 - hook), 24)
    curve = hand + np.stack([np.cos(t), np.sin(t)], axis=1) * r * 1.6
    fill_band(layer, curve, 0.06 * scale * taper(len(curve), 0.5).clip(0.3, 1.0), alpha)
    return [curve]


def _zipper(body, frame, scale, runtime, layer, alpha, event) -> list[np.ndarray]:
    start = _side(body, event)
    other = "right" if start == "left" else "left"
    a = [_hand(body, start), body.get(f"{start}_elbow"), body.get(f"{start}_shoulder")]
    b = [body.get(f"{other}_shoulder"), body.get(f"{other}_elbow"), _hand(body, other)]
    hips = body.mid("left_hip", "right_hip")
    if any(p is None for p in a + b) or hips is None:
        return []
    center, _across, _down = frame
    neck = center
    belly = center + (hips - center) * 0.75
    path = np.array([*a, neck, belly, neck, *b], dtype=np.float64)
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    u = _phase(runtime, event)
    reach = _ease(_seg(u, 0.0, 0.7)) * acc[-1]
    keep = acc <= reach
    if keep.sum() < 1:
        return []
    k = int(keep.sum()) - 1
    tip = path[k] + (path[min(k + 1, len(path) - 1)] - path[k]) * ((reach - acc[k]) / max(seg[min(k, len(seg) - 1)], 1e-6))
    line = np.vstack([path[: k + 1], tip])
    splat(layer, float(tip[0]), float(tip[1]), 0.06 * scale, WHITE * 0.8, alpha, runtime.kernels)
    if u > 0.85:  # se va de atrás hacia adelante
        drop = _seg(u, 0.85, 1.0)
        line = line[int(len(line) * drop):]
    return [line] if len(line) >= 2 else []


def _charge(body, scale, frame_index, runtime, layer, alpha, event) -> list[np.ndarray]:
    side = _side(body, event)
    elbow, wrist = body.get(f"{side}_elbow"), body.get(f"{side}_wrist")
    if elbow is None or wrist is None:
        return []
    d = wrist - elbow
    n = _unit(np.array([-d[1], d[0]]))
    w = 0.06 * scale
    lines = [np.array([elbow + n * w, wrist + n * w, wrist - n * w, elbow - n * w, elbow + n * w])]
    filled = (runtime.active_frames % CHARGE_FRAMES) / CHARGE_FRAMES * (CHARGE_SEGMENTS + 1)
    for k in range(CHARGE_SEGMENTS):
        a = elbow + d * (k + 0.15) / CHARGE_SEGMENTS
        b = elbow + d * (k + 0.85) / CHARGE_SEGMENTS
        if k < int(filled):
            fill_polygon(layer, np.array([a + n * w * 0.7, b + n * w * 0.7, b - n * w * 0.7, a - n * w * 0.7]), WHITE * 0.9, alpha * 0.85, 1.0, feather=1.0)
        else:
            lines.append(np.array([a, b]))  # el tramo vacío, como un guion
    return lines


def _profile_head(body, frame, scale, layer, alpha) -> list[np.ndarray]:
    from vfxglow.engine.solo_fx import head_point

    nose = head_point(body, frame, scale)
    _center, across, down = frame
    ears = [e for e in (body.get("left_ear"), body.get("right_ear")) if e is not None]
    back = np.mean(ears, axis=0) if ears else nose - across * 0.15 * scale
    head = nose + (back - nose) * 0.6 - down * 0.08 * scale
    r = max(float(np.linalg.norm(back - nose)) * 1.15, 0.28 * scale)
    lines = [_circle(head, r * 0.95, r * 1.2, 40, -down)]
    for ear in ears:
        t = np.linspace(-1.3, 1.3, 12)
        out = _unit(ear - head)
        lines.append(ear + np.outer(np.cos(t) * 0.05 * scale, out) + np.outer(np.sin(t) * 0.08 * scale, np.array([-out[1], out[0]])))
    neck_top = head + down * r * 1.15
    for s in (-1.0, 1.0):  # el cuello se abre hacia los hombros
        lines.append(np.array([neck_top + across * s * 0.09 * scale, neck_top + across * s * 0.1 * scale + down * 0.1 * scale, neck_top + across * s * 0.3 * scale + down * 0.2 * scale]))
    return lines


def _fan(body, frame, scale, runtime, layer, alpha, event) -> list[np.ndarray]:
    nose = body.get("nose")
    wrists = [w for w in (body.get("left_wrist"), body.get("right_wrist")) if w is not None]
    if nose is None:
        return []
    _center, across, down = frame
    up = -down
    pivot = (np.mean(wrists, axis=0) if wrists else nose + up * 0.5 * scale) + up * 0.05 * scale
    u = _phase(runtime, event)
    spread = _ease(_seg(u, 0.0, 0.5)) * np.pi * 0.9  # se abre
    ribs = 9
    radius = 0.6 * scale
    lines = []
    angles = np.linspace(-spread / 2, spread / 2, ribs)
    tips = [pivot + (up * np.cos(a) + across * np.sin(a)) * radius for a in angles]
    for tip in tips:
        lines.append(np.array([pivot, tip]))
    if spread > 0.05:
        arc_a = np.linspace(-spread / 2, spread / 2, 30)
        lines.append(np.array([pivot + (up * np.cos(a) + across * np.sin(a)) * radius for a in arc_a]))
        for k in range(len(tips) - 1):  # los pliegues, en zigzag
            mid = (tips[k] + tips[k + 1]) / 2
            lines.append(np.array([tips[k], pivot + (mid - pivot) * 0.92, tips[k + 1]]))
    return lines


def _hand_lines(body, frame, scale, layer, alpha) -> list[np.ndarray]:
    nose = body.get("nose")
    hands = [(s, _hand(body, s), body.get(f"{s}_elbow")) for s in ("left", "right")]
    hands = [(s, h, e) for s, h, e in hands if h is not None and e is not None]
    if nose is None or len(hands) < 2:
        return []
    up = -frame[2]
    apex = nose + up * 0.35 * scale
    lines = []
    for _side_name, hand, elbow in hands:  # una línea por mano, a lo largo del antebrazo hasta la punta
        lines.append(np.array([elbow + (hand - elbow) * 0.4, hand, apex]))
    return lines


def _bubble(body, frame, scale, frame_index, runtime, layer, alpha, event, rng) -> list[np.ndarray]:
    nose = body.get("nose")
    if nose is None:
        return []
    _center, _across, down = frame
    mouth = body.mid("mouth_left", "mouth_right")
    mouth = mouth if mouth is not None else nose + down * 0.1 * scale
    wrists = [w for w in (body.get("left_wrist"), body.get("right_wrist")) if w is not None]
    held = np.mean(wrists, axis=0) if wrists else mouth + down * 0.5 * scale
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.35))
    move = _ease(_seg(u, 0.25, 0.55))  # pasa de la boca a las manos
    at = mouth + (held - mouth) * move
    r = (0.05 + 0.2 * grow) * scale * (1 + 0.05 * np.sin(frame_index * 0.5))
    if u > 0.85:  # revienta
        pop = _seg(u, 0.85, 1.0)
        for k in range(10):
            angle = TAU * k / 10 + rng.uniform(-0.2, 0.2)
            p = at + np.array([np.cos(angle), np.sin(angle)]) * r * (1 + 1.5 * pop)
            splat(layer, float(p[0]), float(p[1]), 0.015 * scale + 0.5, WHITE * 0.7, alpha * (1 - pop), runtime.kernels)
        return []
    wobble = 1 + 0.06 * np.sin(np.linspace(0, TAU, 40) * 3 + frame_index * 0.4)
    t = np.linspace(0, TAU, 40)
    ring = at + np.stack([np.cos(t) * wobble, np.sin(t) / wobble], axis=1) * r
    t2 = np.linspace(3.6, 4.5, 8)  # el brillo de la burbuja
    shine = at + np.stack([np.cos(t2), np.sin(t2)], axis=1) * r * 0.7
    return [ring, shine]


def _wave(body, frame, scale, frame_index, runtime, layer, alpha, event) -> list[np.ndarray]:
    side = _side(body, event)
    wrist, elbow = body.get(f"{side}_wrist"), body.get(f"{side}_elbow")
    if wrist is None or elbow is None:
        return []
    _center, across, down = frame
    st = runtime.swoosh.setdefault(f"wave:{body.prefix}:{event.start_frame if event else 0}", {"dir": 1.0, "flip": -99})
    vx = float(_vel(body, f"{side}_wrist") @ across)
    if abs(vx) > 0.01 * scale and np.sign(vx) != st["dir"]:
        st["dir"], st["flip"] = float(np.sign(vx)), runtime.active_frames
    under = (wrist + elbow) / 2 + down * 0.12 * scale
    since = runtime.active_frames - st["flip"]
    if 0 <= since < 4:  # se va por la mano y reaparece arqueada del otro lado
        t = np.linspace(np.pi, TAU, 16)
        other = under - across * st["dir"] * 0.6 * scale
        return [other + np.outer(np.cos(t) * 0.25 * scale, across) + np.outer(np.sin(t) * 0.18 * scale, down)]
    x = np.linspace(-0.6, 0.6, 40)
    y = np.sin(x * 9 - frame_index * 0.5 * st["dir"]) * 0.05 * np.cos(x * np.pi / 1.2)
    curve = under + np.outer(x * scale, across) + np.outer(y * scale, down)
    fill_band(layer, curve, 0.05 * scale * taper(len(curve), 0.6), alpha * 0.9)
    return [curve]


def _paint_relay(body, scale, runtime, layer, color, alpha) -> list[np.ndarray]:
    from vfxglow.engine.bodyglow import part_mask

    speeds = {part: float(np.linalg.norm(_vel(body, joint))) for part, joint in (("left_arm", "left_wrist"), ("right_arm", "right_wrist"), ("torso", "nose"))}
    st = runtime.swoosh.setdefault(f"paint:{body.prefix}", {"part": "torso", "since": 0})
    best = max(speeds, key=speeds.get)
    if best != st["part"] and speeds[best] > 1.5 * speeds.get(st["part"], 0.0) + 0.01 * scale:
        st["part"], st["since"] = best, runtime.active_frames
    mask = part_mask(body, st["part"], layer.shape[:2], scale)
    if mask is None or mask.sum() == 0:
        return []
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    grow = float(np.clip((runtime.active_frames - st["since"]) / 4.0, 0.0, 1.0))  # el relleno llega
    lines = []
    for contour in contours:
        poly = contour[:, 0, :].astype(np.float64)
        if len(poly) < 3:
            continue
        fill_polygon(layer, poly, np.asarray(color, np.float32), alpha * 0.45 * grow, 0.9, feather=2.0)
        lines.append(np.vstack([poly, poly[:1]]))
    return lines


def _arrows_mask(body, frame, scale, runtime, layer, alpha, event) -> list[np.ndarray]:
    side = _side(body, event)
    elbow, wrist, nose = body.get(f"{side}_elbow"), body.get(f"{side}_wrist"), body.get("nose")
    if elbow is None or wrist is None or nose is None:
        return []
    u = _phase(runtime, event)
    lines = []
    if u < 0.75:  # flechas que suben por el antebrazo, en la dirección del movimiento
        low, high = (elbow, wrist) if elbow[1] >= wrist[1] else (wrist, elbow)
        d = -frame[2]  # apuntan hacia arriba, hacia la cabeza
        n = np.array([-d[1], d[0]])
        for k in range(3):
            q = (k / 3 + runtime.active_frames * 0.06) % 1.0
            tip = low + (high - low) * q
            lines.append(np.array([tip - d * 0.12 * scale + n * 0.11 * scale, tip, tip - d * 0.12 * scale - n * 0.11 * scale]))
        return lines
    face = _ease(_seg(u, 0.75, 0.85))  # al final, las flechas se vuelven la máscara
    up = -frame[2]
    center = nose + up * 0.05 * scale
    r = 0.3 * scale
    lines.append(_circle(center, r * 0.8 * face, r * 1.05 * face, 40, frame[1]))
    for e in ("left_eye", "right_eye"):
        eye = body.get(e)
        if eye is not None and face > 0.5:
            lines.append(_circle(eye, 0.06 * scale, 0.075 * scale, 16))
            fill_polygon(layer, _circle(eye + up * -0.01 * scale, 0.025 * scale, None, 10), WHITE, alpha, 1.0, feather=0.8)
    if face > 0.5:
        lines.append(_circle(nose + frame[2] * 0.12 * scale, 0.03 * scale, 0.05 * scale, 12))
    return lines


def arm_fx(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    seed = zlib.crc32(f"{shape}:{body.prefix}:{event.start_frame if event else 0}".encode())
    rng = np.random.default_rng((seed + frame_index // 2) & 0xFFFFFFFF)
    if shape == "walk_slash":
        return _walk_slash(body, frame, scale, runtime, layer, alpha, event)
    if shape in ("spray_can", "camera_flash"):
        return _spray(shape, body, scale, frame_index, runtime, layer, color, alpha, event, np.random.default_rng(seed))
    if shape == "hook_ball":
        return _hook_ball(body, scale, runtime, layer, alpha, event)
    if shape == "zipper_line":
        return _zipper(body, frame, scale, runtime, layer, alpha, event)
    if shape == "charge_bar":
        return _charge(body, scale, frame_index, runtime, layer, alpha, event)
    if shape == "profile_head":
        return _profile_head(body, frame, scale, layer, alpha)
    if shape == "fan":
        return _fan(body, frame, scale, runtime, layer, alpha, event)
    if shape == "hand_lines":
        return _hand_lines(body, frame, scale, layer, alpha)
    if shape == "bubble_blow":
        return _bubble(body, frame, scale, frame_index, runtime, layer, alpha, event, rng)
    if shape == "wave_pull":
        return _wave(body, frame, scale, frame_index, runtime, layer, alpha, event)
    if shape == "paint_relay":
        return _paint_relay(body, scale, runtime, layer, color, alpha)
    if shape == "arrows_mask":
        return _arrows_mask(body, frame, scale, runtime, layer, alpha, event)
    return []
