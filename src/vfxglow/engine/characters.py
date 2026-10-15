"""Personajes, gestos dibujados y metáforas de energía de video_35 (adornos `type: adornment`).

Cada pose es un personaje y el dibujo lo nombra (docs/referencias/video_35.md):

- Cabeza: `venom` (ojos blancos rasgados, boca enorme con dientes y lengua), `iron_man` (casco con
  rendijas en los ojos), `devil_eyes` (cuernos rojos y ojos que brillan), `punk_crest` (cresta de
  tres puntas con volumen y gafas: de perfil se ven las tres puntas, de frente solo una, porque las
  otras quedan detrás; la base es el borde de la gorra visto desde abajo; al final las gafas suben
  a la cabeza y la cresta se deshace en arcos que giran sobre ella).
- Manos: `rock_hands` (cuernos de rock 🤘 sobre cada mano), `hand_flames` (llamas en las manos),
  `claws` (tres zarpazos que siguen a la mano), `exclaim` ("!" sobre los antebrazos cruzados).
- Pecho: `battery` (una batería que se carga y llega al "100%"), `hero_text` ("HERO").

La cabeza se mide con la cara (costumes.Face): giran e inclinan con ella.
"""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
CHARACTERS = ("venom", "iron_man", "devil_eyes", "punk_crest", "rock_hands", "hand_flames", "claws", "exclaim", "battery", "hero_text")


def _phase(runtime, event) -> float:
    from vfxglow.engine.critters import _phase as phase

    return phase(runtime, event)


def _bezier(points, n: int = 20) -> np.ndarray:
    ctrl = np.array(points, dtype=np.float64)
    out = []
    for u in np.linspace(0.0, 1.0, n):
        level = ctrl.copy()
        while len(level) > 1:
            level = (1 - u) * level[:-1] + u * level[1:]
        out.append(level[0])
    return np.array(out)


def text_outline(text: str, center: np.ndarray, height: float, angle: float = 0.0) -> list[np.ndarray]:
    """Contornos de un texto (fuente de trazo de OpenCV), centrado y de `height` px de alto."""
    font, base = cv2.FONT_HERSHEY_DUPLEX, 4.0
    (w, h), _ = cv2.getTextSize(text, font, base, 10)
    canvas = np.zeros((h + 40, w + 40), np.uint8)
    cv2.putText(canvas, text, (20, h + 20), font, base, 255, 10, cv2.LINE_AA)
    contours, _ = cv2.findContours(canvas, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    k = height / max(h, 1)
    c, s = np.cos(angle), np.sin(angle)
    rot = np.array([[c, -s], [s, c]])
    out = []
    for contour in contours:
        pts = contour.reshape(-1, 2).astype(np.float64)[::3]
        if len(pts) < 4:
            continue
        pts = (pts - np.array([(w + 40) / 2, (h + 40) / 2])) * k
        out.append(center + pts @ rot.T)
    return out


def _face(body, frame, scale):
    from vfxglow.engine.costumes import Face

    try:
        return Face(body, frame, scale)
    except ValueError:
        return None


def head_yaw(body) -> float:
    """-1 (mira a la izquierda de la imagen) .. 0 (de frente) .. 1 (a la derecha)."""
    nose, le, re = body.get("nose"), body.get("left_ear"), body.get("right_ear")
    if nose is None:
        return 0.0
    if le is None or re is None:
        other = le if le is not None else re
        return 0.0 if other is None else float(np.sign(nose[0] - other[0]))
    mid, half = (le + re) / 2, max(abs(float(le[0] - re[0])) / 2, 1.0)
    return float(np.clip((nose[0] - mid[0]) / half, -1.0, 1.0))


# ----- cabeza -----


def _venom(f, layer, alpha) -> list[np.ndarray]:
    lines = []
    for side in (-1, 1):  # ojos rasgados, rellenos de blanco
        eye = f.curve([(side * 0.15, -0.05), (side * 0.75, -0.55), (side * 1.05, -0.2), (side * 0.65, 0.15), (side * 0.15, -0.05)], n=5)
        fill_polygon(layer, eye, WHITE, alpha, 1.0, feather=1.5)
        lines.append(eye)
    mouth = f.curve([(-0.95, 0.85), (-0.5, 1.35), (0.0, 1.45), (0.5, 1.35), (0.95, 0.85), (0.5, 1.05), (0.0, 1.1), (-0.5, 1.05), (-0.95, 0.85)], n=4)
    lines.append(mouth)
    for k in range(9):  # dientes
        x = -0.8 + 0.2 * k
        top = 1.0 + 0.07 * (1 - abs(x))
        lines.append(f.curve([(x - 0.06, top), (x, top + 0.2), (x + 0.06, top)]))
    tongue = f.curve([(-0.1, 1.3), (-0.25, 1.9), (0.15, 2.4), (0.0, 2.9), (0.3, 2.5), (0.35, 1.9), (0.15, 1.3)], n=4)
    fill_polygon(layer, tongue, WHITE * 0.9, alpha * 0.8, 1.0, feather=1.5)
    lines.append(tongue)
    return lines


def _iron_man(f, layer, color, alpha) -> list[np.ndarray]:
    helmet = f.curve([(-1.0, 0.9), (-1.15, -0.4), (-0.7, -1.25), (0.0, -1.45), (0.7, -1.25), (1.15, -0.4), (1.0, 0.9), (0.55, 1.6), (-0.55, 1.6), (-1.0, 0.9)], n=4)
    fill_polygon(layer, helmet, np.asarray(color, np.float32), alpha * 0.35, 0.9, feather=1.5)
    lines = [helmet]
    plate = f.curve([(-0.8, -0.55), (0.0, -0.75), (0.8, -0.55), (0.75, 0.6), (0.4, 1.35), (-0.4, 1.35), (-0.75, 0.6), (-0.8, -0.55)])
    lines.append(plate)
    for side in (-1, 1):
        slit = f.curve([(side * 0.15, 0.0), (side * 0.6, -0.08), (side * 0.65, 0.08), (side * 0.18, 0.12), (side * 0.15, 0.0)])
        fill_polygon(layer, slit, WHITE, alpha, 1.0, feather=1.0)
        lines.append(slit)
        lines.append(f.curve([(side * 0.75, 0.6), (side * 0.35, 0.75), (side * 0.25, 1.1)]))
    lines.append(f.curve([(-0.35, 1.05), (0.35, 1.05)]))
    return lines


def _devil_eyes(f, layer, alpha, runtime) -> list[np.ndarray]:
    lines = []
    for side in (-1, 1):
        horn = f.curve([(side * 0.55, 0.3), (side * 1.05, -0.35), (side * 0.95, -1.15), (side * 0.6, -1.6), (side * 0.72, -0.95), (side * 0.55, -0.25), (side * 0.25, 0.35)], origin=f.top, n=3)
        fill_polygon(layer, horn, np.array([1.0, 0.15, 0.15], np.float32), alpha * 0.55, 0.9, feather=1.5)
        lines.append(np.vstack([horn, horn[:1]]))
    for eye in f.eyes:
        splat(layer, float(eye[0]), float(eye[1]), 0.22 * f.d, np.array([1.0, 0.2, 0.15], np.float32) * 1.8, alpha, runtime.kernels)
        splat(layer, float(eye[0]), float(eye[1]), 0.09 * f.d, WHITE * 1.8, alpha, runtime.kernels)
    return lines


def _crest(f, yaw: float, layer, color, alpha, reveal: float = 1.0) -> list[np.ndarray]:
    """Cresta de tres puntas en perspectiva. Las puntas están una detrás de otra (de la frente a la
    nuca); de perfil se separan y se ven las tres, de frente se tapan y queda una. Se dibujan de
    atrás hacia adelante: la de adelante tapa a las de atrás."""
    tint = np.asarray(color, np.float32)
    lines = []
    # Base: el borde de la gorra visto desde abajo (media elipse sobre la frente).
    base_c = f.p(0.0, -0.95)
    t = np.linspace(np.pi * 1.05, np.pi * 1.95, 24)
    cap = np.array([base_c + f.x * np.cos(a) * 1.15 * f.d - f.y * np.sin(a) * 0.35 * f.d for a in t])
    lines.append(cap)
    spikes = [(-1.0, 0.85, 0.55), (0.0, 1.15, 0.65), (1.0, 0.95, 0.6)]  # (profundidad, alto, ancho)
    order = sorted(range(3), key=lambda k: -spikes[k][0] * np.sign(yaw or 1.0))
    shown = max(int(round(reveal * 3)), 0)
    for rank, k in enumerate(order[:shown] if reveal < 1 else order):
        depth, tall, wide = spikes[k]
        x = depth * yaw * 0.55
        root = base_c + f.x * x * f.d - f.y * 0.1 * f.d
        lean = f.x * (-yaw * 0.35 - depth * 0.25) * f.d
        tip = root - f.y * tall * 1.9 * f.d + lean
        left = root - f.x * wide * f.d
        right = root + f.x * wide * f.d
        # Lados curvos (no un serrucho): suben abombados y se juntan en la punta curvada.
        side_l = _bezier([left, left - f.y * 0.9 * f.d + lean * 0.3, tip], 14)
        side_r = _bezier([tip, right - f.y * 0.7 * f.d + lean * 0.5, right], 14)
        spike = np.vstack([side_l, side_r[1:]])
        shade = 0.55 + 0.25 * (rank / 2)
        fill_polygon(layer, spike, tint, alpha * shade, 0.9, feather=1.5)
        lines.append(spike)
        # Brillo de volumen: una veta clara por el centro de la punta.
        sheen = _bezier([root - f.y * 0.25 * f.d, root - f.y * 0.9 * f.d + lean * 0.35, tip - (tip - root) * 0.15], 10)
        fill_polygon(layer, np.vstack([sheen + f.x * 0.06 * f.d, (sheen - f.x * 0.06 * f.d)[::-1]]), WHITE, alpha * 0.55, 1.0, feather=1.0)
    return lines


def _glasses(f, lift: float = 0.0, scale_k: float = 1.0) -> list[np.ndarray]:
    out = []
    offset = -f.y * lift * 1.4 * f.d
    for side in (-1, 1):
        out.append(f.ellipse(side * 0.5, 0.0, 0.3 * scale_k, 0.18 * scale_k, k=20) + offset)
    out.append(np.array([f.p(-0.2, -0.02), f.p(0.2, -0.02)]) + offset)
    return out


def _punk_crest(body, f, runtime, layer, color, alpha, event, frame_index) -> list[np.ndarray]:
    from vfxglow.engine.duo_fx import fill_band, taper

    u = _phase(runtime, event)
    yaw = head_yaw(body)
    if u < 0.6:
        return _crest(f, yaw, layer, color, alpha) + _glasses(f)
    if u < 0.75:  # las gafas suben, atraídas a la cabeza; la cresta se encoge
        k = (u - 0.6) / 0.15
        return _crest(f, yaw * (1 - k), layer, color, alpha * (1 - k)) + _glasses(f, lift=k, scale_k=1 - 0.5 * k)
    # la cresta se deshace en arcos que giran sobre la cabeza, en perspectiva
    k = (u - 0.75) / 0.25
    center = f.p(0.0, -1.2)
    lines = []
    for n in range(3):
        a0 = frame_index * 0.25 + n * TAU / 3
        phi = np.linspace(a0, a0 + 1.8, 30)
        arc = np.array([center + f.x * np.cos(a) * 1.2 * f.d - f.y * np.sin(a) * 0.35 * f.d for a in phi])
        widths = 0.12 * f.d * taper(len(phi), 0.8) * (0.4 + 0.6 * (np.sin(phi) < 0))
        fill_band(layer, arc, widths, alpha * (1 - 0.6 * k))
        lines.append(arc)
    return lines


# ----- manos -----


def _hand_frame(body, side: str, scale: float):
    wrist, elbow = body.get(f"{side}_wrist"), body.get(f"{side}_elbow")
    if wrist is None or elbow is None:
        return None
    along = (wrist - elbow) / max(float(np.linalg.norm(wrist - elbow)), 1e-6)
    return wrist, along, np.array([-along[1], along[0]]), 0.22 * scale


def _rock_hand(wrist, along, normal, size, layer, color, alpha) -> list[np.ndarray]:
    """Mano 🤘: palma, índice y meñique estirados, medio y anular doblados, pulgar encima."""
    def p(x, y):  # x: a lo largo del antebrazo; y: de lado
        return wrist + along * x * size + normal * y * size

    palm = np.array([p(0.1, -0.45), p(0.75, -0.5), p(0.8, 0.45), p(0.1, 0.4), p(0.1, -0.45)])
    lines = [palm]
    for y in (-0.38, 0.35):  # índice y meñique
        finger = np.array([p(0.75, y - 0.1), p(1.55, y - 0.12), p(1.6, y + 0.04), p(0.78, y + 0.12)])
        lines.append(finger)
    for y in (-0.12, 0.12):  # nudillos doblados
        lines.append(np.array([p(0.78, y - 0.1), p(0.95, y - 0.08), p(0.95, y + 0.1), p(0.78, y + 0.12)]))
    lines.append(np.array([p(0.35, -0.45), p(0.65, -0.1), p(0.8, 0.05)]))  # pulgar
    lines.append(np.array([p(0.0, -0.5), p(0.0, 0.45)]))  # pulsera
    fill_polygon(layer, palm, np.asarray(color, np.float32), alpha * 0.35, 0.9, feather=1.5)
    return lines


def _flames(wrist, size, frame_index, layer, color, alpha, runtime) -> list[np.ndarray]:
    rng = np.random.default_rng(frame_index // 2)
    lines = []
    for k in range(5):
        x = (k - 2) * 0.25 * size + rng.normal(0, 0.04 * size)
        tall = size * rng.uniform(0.7, 1.3) * (1.2 - abs(k - 2) * 0.2)
        base = wrist + np.array([x, -0.1 * size])
        sway = np.array([np.sin(frame_index * 0.5 + k) * 0.15 * size, 0.0])
        tongue = np.vstack([_bezier([base + [-0.14 * size, 0], base + [-0.2 * size, -tall * 0.5] + sway * 0.5, base + [0, -tall] + sway], 10),
                            _bezier([base + [0, -tall] + sway, base + [0.2 * size, -tall * 0.5] + sway * 0.5, base + [0.14 * size, 0]], 10)[1:]])
        fill_polygon(layer, tongue, np.array([1.0, 0.75, 0.2], np.float32), alpha * 0.6, 0.9, feather=1.5)
        lines.append(tongue)
    splat(layer, float(wrist[0]), float(wrist[1]), 0.5 * size, np.array([1.0, 0.6, 0.1], np.float32) * 1.4, alpha * 0.5, runtime.kernels)
    return lines


def character(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event=None) -> list[np.ndarray]:
    from vfxglow.engine.bodyglow import facing

    center, across, down = frame
    back = facing(body) == "back"
    if shape in ("venom", "iron_man", "devil_eyes", "punk_crest"):
        f = _face(body, frame, scale)
        if f is None or (back and shape in ("venom", "iron_man")):
            return []
        if shape == "venom":
            return _venom(f, layer, alpha)
        if shape == "iron_man":
            return _iron_man(f, layer, color, alpha)
        if shape == "devil_eyes":
            return _devil_eyes(f, layer, alpha, runtime)
        return _punk_crest(body, f, runtime, layer, color, alpha, event, frame_index)
    if shape in ("rock_hands", "hand_flames", "claws"):
        lines = []
        for side in ("left", "right"):
            hand = _hand_frame(body, side, scale)
            if hand is None:
                continue
            wrist, along, normal, size = hand
            if shape == "rock_hands":
                lines += _rock_hand(wrist, along, normal, size, layer, color, alpha)
            elif shape == "hand_flames":
                lines += _flames(wrist, size, frame_index, layer, color, alpha, runtime)
            else:
                vel = body.points.get(f"vel:{body.prefix}{side}_wrist")
                if vel is None or float(np.linalg.norm(vel)) < 0.01 * scale:
                    continue
                d = vel / float(np.linalg.norm(vel))
                n = np.array([-d[1], d[0]])
                for k in (-1, 0, 1):  # tres zarpazos en medialuna detrás de la mano
                    start = wrist - d * 0.9 * scale + n * k * 0.12 * scale
                    end = wrist + n * k * 0.12 * scale
                    claw = _bezier([start, (start + end) / 2 + n * 0.12 * scale, end], 16)
                    from vfxglow.engine.duo_fx import fill_band, taper

                    fill_band(layer, claw, 0.06 * scale * taper(len(claw), 0.7), alpha)
                    lines.append(claw)
        return lines
    if shape == "exclaim":
        lines = []
        for side in ("left", "right"):
            hand = _hand_frame(body, side, scale)
            if hand is None:
                continue
            wrist, along, normal, size = hand
            up = -down
            top = wrist + up * 0.85 * scale
            bar = np.array([top, wrist + up * 0.3 * scale])
            lines.append(bar)
            dot = wrist + up * 0.16 * scale
            splat(layer, float(dot[0]), float(dot[1]), 0.035 * scale, WHITE * 1.5, alpha, runtime.kernels)
        return lines
    hips = body.mid("left_hip", "right_hip")
    if hips is None or back:
        return []
    chest = center + (hips - center) * 0.4
    if shape == "hero_text":
        return text_outline("HERO", chest, 0.22 * scale)
    if shape == "battery":
        u = _phase(runtime, event)
        w, h = 0.38 * scale, 0.6 * scale
        if u >= 0.65:
            return text_outline("100%", chest, 0.2 * scale)
        level = min(u / 0.6, 1.0)
        box = np.array([chest + [-w / 2, -h / 2], chest + [w / 2, -h / 2], chest + [w / 2, h / 2], chest + [-w / 2, h / 2], chest + [-w / 2, -h / 2]])
        cap = np.array([chest + [-w / 6, -h / 2], chest + [-w / 6, -h / 2 - 0.06 * scale], chest + [w / 6, -h / 2 - 0.06 * scale], chest + [w / 6, -h / 2]])
        fill = np.array([chest + [-w / 2 + 6, h / 2 - 6], chest + [w / 2 - 6, h / 2 - 6], chest + [w / 2 - 6, h / 2 - 6 - (h - 12) * level], chest + [-w / 2 + 6, h / 2 - 6 - (h - 12) * level]])
        fill_polygon(layer, fill, np.asarray(color, np.float32) * 1.2, alpha * 0.9, 1.0, feather=1.0)
        return [box, cap]
    return []
