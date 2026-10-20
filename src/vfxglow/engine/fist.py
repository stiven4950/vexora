"""Efectos del puño en alto (adornos `type: adornment`, `style.shapes`).

Idea del usuario en dance_two_mens (seg. 28-29,9): los dos levantan el puño y uno se queda
mirándolo; la atención está en el puño. El análisis lo marca como `fist_up`.

- `fist_orb`: una bola brillante pequeña en el puño con rayos que chisporrotean.
- `fist_rays`: rayitos de colores distintos que salen del puño.
- `coins`: monedas que caen del puño girando (se ven de canto y de frente) y rebotan en el piso.
- `sand` / `glitter`: un chorro de arena que cae del puño y hace un montoncito en el piso; la
  escarcha además destella y se dispersa.
- `hourglass`: un reloj de arena grande: la mitad de abajo en el piso y la de arriba cortada,
  abierta hasta el puño, que vierte la arena; el montón de abajo crece. Él controla el tiempo.
  Solo con el puño separado del torso (pegado al cuerpo, el reloj quedaba encima de la persona).
"""

from __future__ import annotations

import colorsys

import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation, _ease, _phase, _seg
from vfxglow.engine.raster import fill_polygon, splat

FISTS = ("fist_orb", "fist_rays", "coins", "sand", "glitter", "hourglass")


def _fists(body, event, scale: float) -> list[tuple[np.ndarray, np.ndarray]]:
    """[(centro del puño, dirección del antebrazo)] de las manos en alto (la del evento primero)."""
    wanted = [event.kind] if event is not None and event.kind in ("left", "right") else ["left", "right"]
    out = []
    for side in wanted:
        wrist, elbow = body.get(f"{side}_wrist"), body.get(f"{side}_elbow")
        if wrist is None or elbow is None or (len(wanted) == 2 and wrist[1] >= elbow[1]):
            continue
        along = (wrist - elbow) / max(float(np.linalg.norm(wrist - elbow)), 1e-6)
        knuckles = [body.get(f"{side}_{k}_mcp") for k in ("index", "middle", "ring", "pinky")]
        knuckles = [k for k in knuckles if k is not None]
        center = np.mean(knuckles, axis=0) if len(knuckles) >= 2 else wrist + along * 0.07 * scale
        out.append((center, along))
    if not out and len(wanted) == 2:  # ningún puño en alto (momento fijado a mano): la mano más alta
        wrists = {s: body.get(f"{s}_wrist") for s in wanted if body.get(f"{s}_wrist") is not None}
        if wrists:
            side = min(wrists, key=lambda s: wrists[s][1])
            return _fists(body, type("E", (), {"kind": side})(), scale)
    return out


def _floor(body, fist: np.ndarray, scale: float) -> float:
    feet = [p for p in (body.get("left_ankle"), body.get("right_ankle"), body.get("left_heel"), body.get("right_heel")) if p is not None]
    return max(p[1] for p in feet) + 0.05 * scale if feet else fist[1] + 2.2 * scale


def _circle(center, r, n: int = 24, ry: float | None = None) -> np.ndarray:
    t = np.linspace(0, TAU, n)
    return center + np.stack([np.cos(t) * r, np.sin(t) * (r if ry is None else ry)], axis=1)


# ----- la bola y los rayos -----


def _orb(fist, scale, frame_index, layer, color, alpha, runtime, grow) -> list[np.ndarray]:
    from vfxglow.engine.duo_doodles import zigzag

    r = 0.11 * scale * grow * (1 + 0.08 * np.sin(frame_index * 1.1))
    ball = _circle(fist, r)
    fill_polygon(layer, ball, np.asarray(color, np.float32), alpha * 0.6, 0.9, feather=3.0)
    splat(layer, float(fist[0]), float(fist[1]), r * 0.8, WHITE * 1.9, alpha, runtime.kernels)
    rng = np.random.default_rng(frame_index // 2)  # los rayos cambian cada dos cuadros
    lines = [ball]
    for k in range(7):
        angle = k * TAU / 7 + rng.uniform(-0.3, 0.3)
        d = np.array([np.cos(angle), np.sin(angle)])
        length = rng.uniform(0.12, 0.26) * scale * grow
        lines.append(zigzag(np.array([fist + d * r, fist + d * (r + length)]), 0.025 * scale, rng, 0.03 * scale))
    return lines


def _rainbow_rays(fist, scale, frame_index, layer, alpha, runtime, grow) -> None:
    """Rayitos de colores: cada uno su tono, dibujados directo en la capa (no van con el color
    del efecto)."""
    for k in range(10):
        angle = k * TAU / 10 + frame_index * 0.08
        hue = (k / 10 + frame_index * 0.01) % 1.0
        tint = np.array(colorsys.hsv_to_rgb(hue, 0.85, 1.0), np.float32)
        d = np.array([np.cos(angle), np.sin(angle)])
        n = np.array([-d[1], d[0]])
        reach = (0.18 + 0.08 * np.sin(frame_index * 0.7 + k * 1.3)) * scale * grow
        start, tip = fist + d * 0.06 * scale, fist + d * (0.06 * scale + reach)
        ray = np.array([start + n * 0.012 * scale, tip, start - n * 0.012 * scale])
        fill_polygon(layer, ray, tint, alpha * 0.9, 1.2, feather=1.0)
        splat(layer, float(tip[0]), float(tip[1]), 0.018 * scale + 1, tint * 1.6, alpha, runtime.kernels)
    splat(layer, float(fist[0]), float(fist[1]), 0.06 * scale, WHITE * 1.6, alpha, runtime.kernels)


# ----- lo que cae del puño -----


def _coins(fist, floor, scale, frame_index, layer, color, alpha, runtime, st, u) -> list[np.ndarray]:
    born = st.setdefault("born", frame_index)
    lines = []
    g = 0.02 * scale
    for k in range(0, frame_index - born + 1, 3):  # una moneda cada tres cuadros
        if u > 0.8 and born + k > frame_index - 3:
            break  # al final deja de soltar
        age = frame_index - born - k
        rng = np.random.default_rng(born + k)
        drift = rng.uniform(-0.03, 0.03) * scale
        x = fist[0] + drift * age
        y = fist[1] + 0.05 * scale + 0.5 * g * age * age
        if y > floor:  # rebota una vez y se apaga
            t_hit = np.sqrt(2 * (floor - fist[1]) / g)
            after = age - t_hit
            if after > 8:
                continue
            y = floor - (0.6 * g * t_hit) * after * 0.4 + 0.5 * g * after * after * 0.4
            y = min(y, floor)
        r = 0.07 * scale
        face = abs(np.cos(age * rng.uniform(0.4, 0.8)))  # gira: de canto se ve fina
        coin = _circle(np.array([x, y]), r * max(face, 0.12), 18, r)
        fill_polygon(layer, coin, np.asarray(color, np.float32), alpha * 0.5, 0.9, feather=1.0)
        lines.append(coin)
        if face > 0.6:
            lines.append(_circle(np.array([x, y]), r * face * 0.55, 12, r * 0.55))
            splat(layer, float(x - r * 0.3 * face), float(y - r * 0.3), r * 0.25, WHITE * 1.6, alpha, runtime.kernels)
    return lines


def _stream(fist, floor, scale, frame_index, layer, color, alpha, runtime, st, u, sparkle: bool) -> list[np.ndarray]:
    born = st.setdefault("born", frame_index)
    poured = frame_index - born
    g = 0.02 * scale
    fall = np.sqrt(2 * max(floor - fist[1], 1.0) / g)  # cuadros que tarda un grano en caer
    rng = np.random.default_rng(7)
    color = np.asarray(color, np.float32)
    for k in range(min(poured + 1, 60)):  # un puñado de granos por cuadro, cada uno con su caída
        for j in range(3):
            age = k + j / 3
            if age > fall:
                continue
            spread = rng.uniform(-1, 1) * 0.015 * scale * age * (2.0 if sparkle else 1.0)
            x = fist[0] + spread
            y = fist[1] + 0.06 * scale + 0.5 * g * age * age
            size = 0.01 * scale + 1
            tint = color
            if sparkle:  # la escarcha destella
                size *= 1 + abs(np.sin(frame_index * 0.9 + k + j))
                tint = color * 0.6 + WHITE * 0.8
            splat(layer, float(x), float(y), size, tint * 1.4, alpha, runtime.kernels)
    lines = []
    if poured > 1 and not (u > 0.85):  # el hilo del chorro
        lines.append(np.array([fist + np.array([0, 0.06 * scale]), np.array([fist[0], min(fist[1] + 0.5 * g * poured * poured, floor)])]))
    pile = min(poured / 40.0, 1.0)  # el montoncito crece en el piso
    if poured > fall:
        w, h = 0.3 * scale * pile, 0.12 * scale * pile
        t = np.linspace(0, np.pi, 16)
        mound = np.stack([fist[0] - np.cos(t) * w, floor - np.sin(t) * h], axis=1)
        fill_polygon(layer, mound, color, alpha * 0.4, 0.9, feather=1.5)
        lines.append(mound)
    if sparkle and poured % 4 == 0:
        star = fist + np.array([np.sin(frame_index) * 0.2 * scale, 0.4 * scale])
        lines += [np.array([star - [0.04 * scale, 0], star + [0.04 * scale, 0]]), np.array([star - [0, 0.04 * scale], star + [0, 0.04 * scale]])]
    return lines


# ----- el reloj de arena -----


def _bulb(x: float, neck_y: float, far_y: float, half_w: float, neck_w: float, upto: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Los dos costados de un bulbo de vidrio del cuello (neck_y) hacia far_y: angosto en el
    cuello, ancho al medio y algo más cerrado al final. `upto` < 1 lo corta antes."""
    q = np.linspace(0, upto, 20)
    width = neck_w + (half_w - neck_w) * np.sin(np.clip(q / 0.62, 0, 1) * np.pi / 2) ** 0.7
    width = np.where(q > 0.62, half_w - (half_w - half_w * 0.82) * ((q - 0.62) / 0.38) ** 2, width)
    y = neck_y + (far_y - neck_y) * q
    return np.stack([x - width, y], axis=1), np.stack([x + width, y], axis=1)


def _hourglass(fist, floor, scale, frame_index, layer, color, alpha, runtime, st, u) -> list[np.ndarray]:
    lines = []
    x = fist[0]
    grow = _ease(_seg(u, 0.0, 0.15))
    # Bulbo de abajo entero y medio bulbo de arriba (cortado en lo más ancho, justo bajo el puño).
    room = max(floor - (fist[1] + 0.12 * scale), 0.6 * scale)
    bulb = room / 1.62
    neck_y = floor - bulb
    half_w = 0.3 * bulb
    neck_w = 0.035 * scale
    color = np.asarray(color, np.float32)
    left, right = _bulb(x, neck_y, floor, half_w, neck_w)
    glass = np.vstack([left, right[::-1]])
    fill_polygon(layer, glass, color, alpha * 0.08, 0.9, feather=2.0)  # el vidrio, apenas
    lines += [left, right, np.array([left[-1], right[-1]])]
    upto = 0.62 * grow  # el de arriba crece hacia el puño y queda abierto, cortado
    top_l, top_r = _bulb(x, neck_y, neck_y - bulb, half_w, neck_w, max(upto, 0.05))
    lines += [top_l, top_r]
    for edge, s in ((top_l[-1], -1), (top_r[-1], 1)):  # el filo del corte, un poco dentado
        lines.append(np.array([edge, edge + np.array([s * 0.02 * scale, -0.03 * scale]), edge + np.array([s * 0.05 * scale, 0.0])]))
    plate = half_w * 1.25  # las tapas del marco y sus varillas, hasta la altura del corte
    lines.append(np.array([[x - plate, floor + 0.03 * scale], [x + plate, floor + 0.03 * scale]]))
    for s in (-1, 1):
        lines.append(np.array([[x + s * plate * 0.92, floor + 0.03 * scale], [x + s * plate * 0.92, top_l[-1][1]]]))
    if grow < 0.9:
        return lines
    born = st.setdefault("born", frame_index)
    poured = frame_index - born
    # El chorro: del puño, por el medio bulbo cortado y el cuello, hasta el montón.
    level = min(poured / 40.0, 0.7) * bulb
    stream_end = floor - level * 0.55
    lines.append(np.array([fist + np.array([0, 0.06 * scale]), [x, stream_end]]))
    rng = np.random.default_rng(frame_index)
    for _ in range(14):
        y = rng.uniform(fist[1] + 0.06 * scale, stream_end)
        splat(layer, float(x + rng.uniform(-0.012, 0.012) * scale), float(y), 0.014 * scale + 1, color * 1.5, alpha, runtime.kernels)
    # El montón de abajo crece dentro del bulbo (no se sale del vidrio).
    widths = right[:, 0] - x
    ys = right[:, 1]
    tt = np.linspace(-1, 1, 24)
    top_y = floor - level
    mound = []
    for v in tt:
        yy = top_y + (floor - top_y) * v * v  # una loma
        inside = float(np.interp(yy, ys, widths)) * 0.95
        mound.append([x + v * inside, yy])
    mound = np.array(mound)
    fill_polygon(layer, np.vstack([mound, [[x + widths[-1] * 0.95, floor], [x - widths[-1] * 0.95, floor]]]), color, alpha * 0.6, 0.9, feather=1.5)
    lines.append(mound)
    # Un poco de arena en el fondo del medio bulbo de arriba, en embudo hacia el cuello.
    cup = neck_y - 0.25 * bulb
    funnel = np.array([[x - 0.18 * bulb, cup], [x, neck_y], [x + 0.18 * bulb, cup]])
    fill_polygon(layer, funnel, color, alpha * 0.5, 0.9, feather=1.0)
    return lines


def fist_effect(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    fists = _fists(body, event, scale)
    if not fists:
        return []
    u = _phase(runtime, event)
    grow = _ease(_seg(u, 0.0, 0.12))
    st = _activation(runtime, event, f"fist:{shape}", body)
    lines: list[np.ndarray] = []
    if shape == "fist_orb":
        for fist, _ in fists:
            lines += _orb(fist, scale, frame_index, layer, color, alpha, runtime, grow)
        return lines
    if shape == "fist_rays":
        for fist, _ in fists:
            _rainbow_rays(fist, scale, frame_index, layer, alpha, runtime, grow)
        return lines
    fist = fists[0][0]  # lo que cae, de un solo puño
    floor = _floor(body, fist, scale)
    if shape == "coins":
        return _coins(fist, floor, scale, frame_index, layer, color, alpha, runtime, st, u)
    if shape in ("sand", "glitter"):
        return _stream(fist, floor, scale, frame_index, layer, color, alpha, runtime, st, u, shape == "glitter")
    if shape == "hourglass":
        if "far" not in st:  # se decide al empezar y se mantiene (no parpadea si la mano vuelve)
            st["far"] = next((f for f, _ in fists if _away_from_torso(body, f, scale)), None)
        if st["far"] is None:
            return []
        fist = next((f for f, _ in fists if np.linalg.norm(f - st["far"]) < scale), fists[0][0])
        st["far"] = fist
        return _hourglass(fist, _floor(body, fist, scale), scale, frame_index, layer, color, alpha, runtime, st, u)
    return []


AWAY_FROM_TORSO = 0.75  # anchos de hombros, de costado, entre el puño y el eje del torso


def _away_from_torso(body, fist: np.ndarray, scale: float) -> bool:
    """Si el puño está separado del torso, de costado (el reloj de arena va a un lado del cuerpo)."""
    top, hips = body.mid("left_shoulder", "right_shoulder"), body.mid("left_hip", "right_hip")
    if top is None:
        return False
    axis = (hips - top) if hips is not None else np.array([0.0, 1.0])
    axis = axis / max(float(np.linalg.norm(axis)), 1e-6)
    off = fist - top
    side = off - axis * float(np.dot(off, axis))  # lo que se aparta del eje del torso
    return float(np.linalg.norm(side)) > AWAY_FROM_TORSO * scale
