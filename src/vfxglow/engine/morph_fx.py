"""Efectos de video_52 explicados por el usuario (docs/referencias/video_52.md), casi todos cadenas
de dibujos que se convierten unos en otros (engine/morph.py).

Adornos (`type: adornment`, `style.shapes`):

- horns_morph: cuernos sobre la cabeza; una mano invisible les aprieta la punta hacia abajo y se
  doblan en corchetes; las puntas se juntan en una "V" que se curva, baja hasta los ojos y, de otro
  color, se vuelve una X en cada ojo (seg. 3,4-5,1).
- rubber_band: una liga elástica: la mano izquierda sostiene un aro, la derecha lo agarra y lo
  estira; al soltarse, vibra (seg. 6,0-6,5).
- hand_echo: el contorno de las manos dibujado en cada fotograma donde pasan; se quedan los dos
  anteriores y los más viejos desaparecen (seg. 6,9-7,8; 26,9-28,1).
- head_shot: la mano como un arma apuntando a la cabeza; el disparo y la cabeza que estalla en
  llamas y chispas: la mente que explota (seg. 9,7-9,9).
- dough_tie: los dedos se encienden, aparece una masa que él amasa de lado a lado como un panadero
  (se aplasta y se estira con la mano) y la masa se convierte en la corbata (seg. 14,2-14,9).
- tie_on: ponerse una corbata: el nudo en el cuello y la corbata que baja con la mano; la mano tapa
  su continuidad (seg. 14,6-14,9).
- orbit_ribbons: cintas que orbitan alrededor del cuerpo en 3D, se tuercen (se ven de canto y de
  frente) y pasan por detrás de la persona.
- ribbon_watch: las cintas que orbitan se cierran sobre la muñeca, se vuelven un moño (un
  garrapiño) y el moño, de otro color, un reloj (seg. 19,4-20,5).
- samurai_swords: dos empuñaduras de espada asoman sobre los hombros; las espadas solo salen
  cuando las manos suben alineadas con los hombros y las alcanzan (seg. 21,5-22,2).
- energy_chain: la espada se vuelve un zigzag por la cintura, el zigzag un moño, el moño un aro que
  orbita una soga imaginaria y viaja hasta el puño, el aro una bola y la bola el aro del puño, donde
  la energía se queda (seg. 22,3-23,1).
- jail_break: un hombre enojado tras las rejas: barrotes frente a la cara y ojos enojados; los
  barrotes tiemblan y se rompen en muchas partículas (seg. 26,0-26,8).
- moon_dove_wifi: una luna en la palma se vuelve una paloma blanca que desciende y su energía toma
  forma de arcos de wifi (seg. 29,6-30,5).
"""

from __future__ import annotations

import colorsys
import zlib

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.duo_fx import body_mask, fill_band, visible
from vfxglow.engine.face_toon import _finger_outline
from vfxglow.engine.morph import chain, morph_lines, resample
from vfxglow.engine.raster import fill_polygon, splat
from vfxglow.engine.solo_fx import head_point

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
MORPH_FX = ("horns_morph", "rubber_band", "hand_echo", "head_shot", "dough_tie", "tie_on", "orbit_ribbons", "ribbon_watch", "samurai_swords", "energy_chain", "jail_break", "moon_dove_wifi")
FINGERS = ("thumb", "index", "middle", "ring", "pinky")
# Cuántos contornos de las manos se quedan atrás (además del actual).
ECHO_KEEP = 2
# Distancia (anchos de hombros) que se aparta la mano antes de dejar otra copia, y cuánto se apaga
# cada copia hacia atrás.
ECHO_STEP = 0.15
ECHO_FADE = 0.45


def accent(runtime, color) -> np.ndarray:
    """El segundo color del capítulo, o el mismo con el tono girado si solo hay uno."""
    color = np.asarray(color, np.float32)
    for other in runtime.effect.style.colors:
        other = np.asarray(other, np.float32)
        if float(np.abs(other - color).sum()) > 0.15:
            return other
    h, l, s = colorsys.rgb_to_hls(*[float(c) for c in color])
    return np.array(colorsys.hls_to_rgb((h + 0.33) % 1.0, l, s), np.float32)


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-6 else np.array([1.0, 0.0])


def _ellipse(center, rx, ry, across, up, a0=0.0, a1=TAU, n=32) -> np.ndarray:
    t = np.linspace(a0, a1, n)
    return center + np.outer(np.cos(t) * rx, across) + np.outer(np.sin(t) * ry, up)


def _eyes(body, nose, across, up, scale) -> tuple[np.ndarray, np.ndarray]:
    left, right = body.get("left_eye"), body.get("right_eye")
    if left is not None and right is not None:
        return left, right
    base = nose + up * 0.06 * scale
    return base - across * 0.08 * scale, base + across * 0.08 * scale


def _hand(body, side: str) -> np.ndarray | None:
    knuckle = body.get(f"{side}_middle_mcp")
    return knuckle if knuckle is not None else body.get(f"{side}_wrist")


def _x(center: np.ndarray, r: float) -> np.ndarray:
    """Una X de un solo trazo (las dos diagonales pasan por el centro)."""
    d1, d2 = np.array([1.0, 1.0]) * r, np.array([1.0, -1.0]) * r
    return np.array([center - d1, center, center + d1, center, center - d2, center, center + d2])


# ----- cuernos que se aplastan y se vuelven ojos en X -----


def _horns_morph(body, frame, scale, runtime, color, event) -> list:
    _center, across, down = frame
    up = -down
    nose = head_point(body, frame, scale)
    top = nose + up * 0.42 * scale  # la coronilla
    eyes = _eyes(body, nose, across, up, scale)
    u = _phase(runtime, event)
    horns, brackets, vee, low, crosses = [], [], [], [], []
    for side, eye in ((-1.0, eyes[0]), (1.0, eyes[1])):
        out = across * side
        b1, b2 = top + out * 0.08 * scale, top + out * 0.22 * scale
        tip = top + out * 0.3 * scale + up * 0.32 * scale
        horns.append(np.array([b1, b1 + up * 0.15 * scale + out * 0.04 * scale, tip, b2 + up * 0.12 * scale + out * 0.06 * scale, b2]))
        # Apretada desde la punta: se dobla hacia abajo y afuera, como un corchete.
        bend = top + out * 0.34 * scale + up * 0.04 * scale
        brackets.append(np.array([b1, b1 + up * 0.14 * scale, top + out * 0.3 * scale + up * 0.16 * scale, bend, b2]))
        # Las puntas se juntan en el centro: una "V" con un poco de curva.
        meet = top + up * 0.02 * scale
        vee.append(np.array([b2 + up * 0.12 * scale, b1 + up * 0.04 * scale + out * 0.02 * scale, meet + out * 0.01 * scale, meet]))
        # La misma "V" ya sobre los ojos, más chica.
        center = (eyes[0] + eyes[1]) / 2 + up * 0.08 * scale
        low.append(np.array([center + out * 0.2 * scale + up * 0.05 * scale, center + out * 0.1 * scale - up * 0.02 * scale, center + out * 0.02 * scale, center]))
        crosses.append(_x(eye, 0.055 * scale))
    grow = _ease(_seg(u, 0.0, 0.12))
    if grow < 1.0:  # los cuernos salen de la cabeza
        horns = [h[:1] + (h - h[:1]) * grow for h in horns]
    lines, _stage = chain([(0.0, horns), (0.25, brackets), (0.42, vee), (0.58, low), (0.72, crosses)], u)
    tint = accent(runtime, color) if u >= 0.66 else color  # cambia de color al volverse X
    return [(line, tint) for line in lines]


# ----- la liga elástica -----


def _rubber_band(body, frame, scale, frame_index, runtime, layer, event) -> list[np.ndarray]:
    a, b = _hand(body, "left"), _hand(body, "right")
    if a is None or b is None:
        return []
    u = _phase(runtime, event)
    st = runtime.swoosh.setdefault(f"band:{body.prefix}:{event.start_frame if event else 0}", {"last": None, "wobble": 0})
    span = b - a
    dist = float(np.linalg.norm(span))
    if u < 0.15 or dist < 0.25 * scale:  # el aro en la mano izquierda, antes de que la otra lo agarre
        return [_ellipse(a, 0.13 * scale, 0.13 * scale, np.array([1.0, 0.0]), np.array([0.0, 1.0]), n=36)]
    if st["last"] is not None and dist < st["last"] - 0.03 * scale:
        st["wobble"] = runtime.active_frames  # la soltó: vibra
    st["last"] = dist
    d = span / dist
    n = np.array([-d[1], d[0]])
    stretch = float(np.clip(dist / scale - 0.3, 0.0, 1.5))
    gap = max(0.07, 0.14 - 0.04 * stretch) * scale  # se adelgaza al estirarse, sin cerrarse
    q = np.linspace(0, 1, 40)
    since = runtime.active_frames - st["wobble"]
    shake = np.sin(q * np.pi * 3 + frame_index * 1.3) * 0.05 * scale * np.exp(-since / 5.0) * np.sin(q * np.pi)
    sides = []
    for sign in (1.0, -1.0):
        sides.append(a + np.outer(q * dist, d) + np.outer(sign * gap * (0.6 + 0.4 * np.sin(q * np.pi)) + shake * sign, n))
    t = np.linspace(-np.pi / 2, np.pi / 2, 12)
    cap_b = b + np.outer(np.cos(t) * gap * 0.9, d) + np.outer(np.sin(t) * gap, n)
    cap_a = a - np.outer(np.cos(t) * gap * 0.9, d) + np.outer(np.sin(t) * gap, n)
    return [np.vstack([sides[0], cap_b[::-1], sides[1][::-1], cap_a])]


# ----- el eco de las manos -----


def _hand_shape(body, side: str, scale: float) -> list[np.ndarray]:
    """El contorno de la mano: sus dedos si se ven los puntos de la mano; si no, una mano gruesa."""
    lines = []
    for finger in FINGERS:
        joints = ("cmc", "mcp", "ip", "tip") if finger == "thumb" else ("mcp", "pip", "dip", "tip")
        chain_ = [body.get(f"{side}_{finger}_{j}") for j in joints]
        chain_ = [c for c in chain_ if c is not None]
        if len(chain_) >= 2:
            lines.append(_finger_outline(chain_, 0.035 * scale))
    palm = [body.get(f"{side}_{k}") for k in ("index_mcp", "wrist", "pinky_mcp")]
    if all(p is not None for p in palm):
        lines.append(np.array(palm + palm[:1]))
    if lines:
        return lines
    wrist, elbow = body.get(f"{side}_wrist"), body.get(f"{side}_elbow")
    if wrist is None or elbow is None:
        return []
    d = _unit(wrist - elbow)
    n = np.array([-d[1], d[0]])
    center = wrist + d * 0.12 * scale
    t = np.linspace(0, TAU, 30)
    bump = 1.0 + 0.18 * np.maximum(np.cos(t), 0) * np.abs(np.sin(t * 2.5))  # los dedos
    return [center + np.outer(np.cos(t) * 0.14 * scale * bump, d) + np.outer(np.sin(t) * 0.1 * scale, n)]


def _moving_hand(body, event) -> str:
    """La mano que se mueve (la de más velocidad); si ninguna se mueve, la del evento o la más alta."""
    speeds = {}
    for side in ("left", "right"):
        vel = body.points.get(f"vel:{body.prefix}{side}_wrist")
        speeds[side] = float(np.linalg.norm(vel)) if vel is not None else 0.0
    if max(speeds.values()) > 1e-3:
        return max(speeds, key=speeds.get)
    if event is not None and event.kind in ("left", "right"):
        return event.kind
    wrists = {s: body.get(f"{s}_wrist") for s in ("left", "right") if body.get(f"{s}_wrist") is not None}
    return min(wrists, key=lambda s: wrists[s][1]) if wrists else "right"


def _hand_echo(body, scale, frame_index, runtime, color, event) -> list:
    """El contorno de la mano que se mueve y, detrás, las copias que dejó: cada copia nueva solo si
    la mano se apartó ECHO_STEP de la anterior (si no, se encimarían en un bloque de luz), y las de
    atrás más tenues (video_52, explicación del usuario: se quedan las dos anteriores)."""
    side = _moving_hand(body, event)
    current = _hand_shape(body, side, scale)
    wrist = body.get(f"{side}_wrist")
    st = runtime.swoosh.setdefault(f"echo:{body.prefix}", {"copies": []})
    copies = st["copies"]
    if current and wrist is not None and (not copies or float(np.linalg.norm(wrist - copies[-1][0])) >= ECHO_STEP * scale):
        copies.append((wrist.copy(), current))
        del copies[:-(ECHO_KEEP + 1)]
    tint = np.asarray(color, np.float32)
    out = [(line, tint) for line in current]
    behind = [c for c in copies if c[1] is not current][-ECHO_KEEP:]
    for age, (_at, lines) in enumerate(reversed(behind), start=1):
        out += [(line, tint * ECHO_FADE ** age) for line in lines]
    return out


# ----- el disparo a la cabeza: la mente que explota -----


def _head_shot(body, frame, scale, frame_index, runtime, layer, color, event, rng) -> list:
    _center, across, down = frame
    up = -down
    head = head_point(body, frame, scale) + up * 0.1 * scale
    hands = [(s, _hand(body, s)) for s in ("left", "right") if _hand(body, s) is not None]
    if not hands:
        return []
    side, hand = min(hands, key=lambda item: float(np.linalg.norm(item[1] - head)))
    aim = _unit(head - hand)
    n = np.array([-aim[1], aim[0]])
    u = _phase(runtime, event)
    lines: list = []
    if u < 0.45:  # el arma en la mano, apuntando a la cabeza
        barrel = hand + aim * 0.22 * scale
        lines.append(np.array([hand - n * 0.04 * scale, barrel - n * 0.04 * scale, barrel + n * 0.03 * scale, hand + n * 0.03 * scale]))
        lines.append(np.array([hand, hand - aim * 0.04 * scale - n * 0.12 * scale, hand - aim * 0.1 * scale - n * 0.1 * scale, hand - aim * 0.06 * scale]))
        if u > 0.32:  # el fogonazo
            splat(layer, float(barrel[0]), float(barrel[1]), 0.12 * scale, WHITE, 1.0, runtime.kernels)
        return lines
    blast = _seg(u, 0.45, 0.85)
    fire = np.array([1.0, 0.75, 0.2], np.float32) * 0.5 + np.asarray(color, np.float32) * 0.5
    for k in range(9):  # lenguas de fuego que salen de la cabeza
        angle = -np.pi / 2 + (k - 4) * 0.33 + rng.uniform(-0.08, 0.08)
        d = across * np.cos(angle) + down * np.sin(angle)
        length = (0.25 + 0.55 * np.sin(np.pi * min(blast * 1.3, 1.0))) * scale * (0.8 + 0.4 * rng.uniform())
        q = np.linspace(0, 1, 12)[:, None]
        side_n = np.array([-d[1], d[0]])
        curve = head + d * q * length + side_n * np.sin(q * np.pi * 1.5 + frame_index * 0.5) * 0.06 * scale
        if blast < 0.75:
            lines.append((curve, fire))
    cloud = 0.25 * scale * (0.6 + blast)
    t = np.linspace(0, TAU, 50)
    puff = head + np.stack([np.cos(t), np.sin(t)], axis=1) * cloud * (1 + 0.2 * np.abs(np.sin(t * 4 + frame_index * 0.2)))[:, None]
    if blast < 0.6:
        fill_polygon(layer, puff, WHITE * 0.9 + fire * 0.3, 0.8 * (1 - blast), 1.0, feather=2.0)
    for k in range(14):  # chispas que vuelan
        angle = rng.uniform(0, TAU)
        at = head + np.array([np.cos(angle), np.sin(angle)]) * (0.3 + 0.9 * blast) * scale
        splat(layer, float(at[0]), float(at[1]), 0.02 * scale + 0.5, fire * 1.2, 1.0 - _seg(u, 0.75, 1.0), runtime.kernels)
    return lines


# ----- ponerse la corbata -----


def _tie_outline(knot: np.ndarray, across, down, length: float, scale: float) -> np.ndarray:
    """El contorno de una corbata (nudo y cuerpo que se ensancha y acaba en punta), en un trazo."""
    w = 0.07 * scale
    top = knot + down * w * 1.2
    end = top + down * max(length - w * 1.2, w)
    return np.array([knot - across * w * 0.8, knot + across * w * 0.8, top + across * w * 0.5, end - down * w * 1.2 + across * w * 1.3,
                     end, end - down * w * 1.2 - across * w * 1.3, top - across * w * 0.5, knot - across * w * 0.8])


def _dough_tie(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    center, across, down = frame
    side = _moving_hand(body, event)
    hand = _hand(body, side)
    hips = body.mid("left_hip", "right_hip")
    if hand is None or hips is None:
        return []
    u = _phase(runtime, event)
    tint = np.asarray(color, np.float32)
    if u < 0.25:  # los dedos resaltados: rayitos desde las puntas
        lines = []
        for finger in FINGERS:
            tip = body.get(f"{side}_{finger}_tip")
            base = body.get(f"{side}_{finger}_{'ip' if finger == 'thumb' else 'pip'}")
            if tip is not None and base is not None:
                d = _unit(tip - base)
                lines.append(np.array([tip + d * 0.02 * scale, tip + d * 0.12 * scale]))
        return lines or [np.array([hand, hand + _unit(hand - center) * 0.15 * scale])]
    # La masa bajo la mano: se aplasta y se estira hacia donde la mano la amasa.
    vel = body.points.get(f"vel:{body.prefix}{side}_wrist")
    push = float(np.clip(abs(float(np.asarray(vel) @ across)) / max(scale * 0.05, 1e-6), 0.0, 1.0)) if vel is not None else 0.0
    knead = 0.5 + 0.5 * np.sin(runtime.active_frames * 0.6)  # el vaivén del amasado
    stretch = 0.25 + 0.5 * max(push, knead)
    r = 0.24 * scale  # una masa que se ve: en la referencia ocupa la mano entera
    blob_at = hand + down * 0.08 * scale
    t = np.linspace(0, TAU, 40)
    lumps = 1.0 + 0.1 * np.sin(t * 5 + runtime.active_frames * 0.4) + 0.05 * np.sin(t * 9)
    dough = blob_at + np.outer(np.cos(t) * r * (1 + stretch) * lumps, across) + np.outer(np.sin(t) * r * (1 - 0.4 * stretch) * lumps, down)
    knot = center + down * 0.08 * scale
    full = float(np.linalg.norm(hips - knot)) * 0.85
    tie = _tie_outline(knot, across, down, full, scale)
    if u < 0.6:
        fill_polygon(layer, dough, tint * 0.6 + WHITE * 0.4, alpha * 0.75, 1.0, feather=1.5)
        return [dough]
    if u < 0.75:  # la masa se estira hasta volverse la corbata
        k = (u - 0.6) / 0.15
        shape = morph_lines([dough], [tie], k)[0]
        fill_polygon(layer, shape, tint * 0.6 + WHITE * 0.3, alpha * 0.55 * (1 - 0.3 * k), 1.0, feather=1.5)
        return [shape]
    fill_polygon(layer, tie, tint * 0.6 + WHITE * 0.4, alpha * 0.7, 1.0, feather=1.2)
    return [tie, np.array([knot + down * 0.084 * scale - across * 0.035 * scale, knot + down * 0.084 * scale + across * 0.035 * scale])]


def _tie_on(body, frame, scale, runtime, layer, event) -> list[np.ndarray]:
    center, across, down = frame
    hips = body.mid("left_hip", "right_hip")
    if hips is None:
        return []
    knot = center + down * 0.08 * scale
    full = float(np.linalg.norm(hips - knot)) * 0.85
    u = _phase(runtime, event)
    length = full * _ease(_seg(u, 0.0, 0.55))
    hands = [h for h in (_hand(body, "left"), _hand(body, "right")) if h is not None]
    # La mano que baja por el pecho tira de la corbata: llega al menos hasta ella.
    covering = []
    for hand in hands:
        rel = hand - knot
        if abs(float(rel @ across)) < 0.25 * scale and 0 < float(rel @ down) < full:
            length = max(length, float(rel @ down) + 0.05 * scale)
            covering.append(float(rel @ down))
    w = 0.07 * scale
    lines = [np.array([knot - across * w * 0.8, knot + across * w * 0.8, knot + across * w * 0.5 + down * w * 1.2, knot - across * w * 0.5 + down * w * 1.2, knot - across * w * 0.8])]
    top = knot + down * w * 1.2
    if length <= w * 1.3:
        return lines
    q = np.linspace(0.0, 1.0, 24)
    widths = (w * 0.8 + w * 0.6 * q) * np.where(q > 0.9, (1.0 - q) * 10, 1.0)  # se ensancha y acaba en punta
    spine = top + np.outer(q * (length - w * 1.2), down)
    gap = np.ones(len(q), bool)
    for c in covering:  # la mano tapa la corbata
        gap &= np.abs(q * (length - w * 1.2) + w * 1.2 - c) > 0.07 * scale
    k = 0
    while k < len(q):
        if not gap[k]:
            k += 1
            continue
        j = k
        while j < len(q) and gap[j]:
            j += 1
        if j - k >= 2:
            fill_band(layer, spine[k:j], widths[k:j] * 2, 0.9)
            lines.append(spine[k:j] + np.outer(widths[k:j], across))
            lines.append(spine[k:j] - np.outer(widths[k:j], across))
        k = j
    return lines


# ----- cintas que orbitan -----


def ribbon_curves(body, frame, scale, age: float, layer, alpha, toward: np.ndarray | None = None, pull: float = 0.0) -> list[np.ndarray]:
    """Tres cintas que orbitan el cuerpo en planos inclinados, cada una se tuerce sobre sí misma
    (ancha de frente, fina de canto) y se esconde al pasar detrás de la persona. Con `toward` y
    `pull` (0-1) se cierran y se juntan sobre ese punto."""
    center, across, down = frame
    up = -down
    hips = body.mid("left_hip", "right_hip")
    # Alrededor del pecho y la cabeza (video_52 seg. 10,7-12,8: los arcos pasan junto a la cara).
    pivot = center + (hips - center) * 0.15 if hips is not None else center + down * 0.15 * scale
    mask = body_mask(body, layer.shape[:2], scale)
    out = []
    # Tres cintas repartidas a un tercio de vuelta y largas (más de media vuelta): siempre hay
    # alguna por delante; giran a distinto ritmo, una al revés.
    for k, (height, tilt, speed, span) in enumerate(((-0.35, 0.28, 0.16, 3.6), (0.15, -0.22, -0.13, 3.3), (0.6, 0.18, 0.2, 3.0))):
        radius = (0.75 - 0.1 * k) * scale * (1.0 - 0.85 * pull)  # pegadas al cuerpo, no un aro lejano
        a0 = age * speed + k * TAU / 3
        phi = np.linspace(a0, a0 + span * (1.0 - 0.4 * pull), 72)
        x, z = np.cos(phi), np.sin(phi)
        base = pivot + up * height * scale
        if toward is not None:
            base = base + (toward - base) * _ease(pull)
        curve = base + np.outer(x * radius, across) + np.outer((z * 0.22 + x * tilt) * radius, up)
        twist = np.abs(np.cos(phi * 1.5 + age * 0.2 + k))
        widths = 0.11 * scale * (1.0 - 0.6 * pull) * (0.25 + 0.75 * twist) * np.sin(np.linspace(0, np.pi, len(phi))) ** 0.7 * (0.6 + 0.4 * (z > 0))
        for a, b in visible(curve, z, mask):
            fill_band(layer, curve[a:b], widths[a:b], alpha * 0.95)
            out.append(curve[a:b])
    return out


def _bow(at: np.ndarray, size: float, across, up) -> list[np.ndarray]:
    """Un moño (garrapiño): dos alas en triángulo con el nudo en el centro."""
    wings = []
    for s in (-1.0, 1.0):
        out = across * s
        wings.append(np.array([at, at + out * size + up * size * 0.6, at + out * size * 1.05, at + out * size - up * size * 0.6, at]))
    knot = _ellipse(at, size * 0.18, size * 0.22, across, up, n=14)
    return wings + [knot]


def _watch(at: np.ndarray, size: float, along, frame_index: int) -> list[np.ndarray]:
    """Un reloj en la muñeca: la correa a los lados, la carátula y dos manecillas que avanzan."""
    n = np.array([-along[1], along[0]])
    face = at + 0.0
    t = np.linspace(0, TAU, 28)
    dial = face + np.stack([np.cos(t), np.sin(t)], axis=1) * size * 0.55
    strap = [np.array([face + n * size * 0.35 - along * size * 0.55, face + n * size * 0.35 - along * size * 1.3]),
             np.array([face - n * size * 0.35 - along * size * 0.55, face - n * size * 0.35 - along * size * 1.3]),
             np.array([face + n * size * 0.35 + along * size * 0.55, face + n * size * 0.35 + along * size * 1.3]),
             np.array([face - n * size * 0.35 + along * size * 0.55, face - n * size * 0.35 + along * size * 1.3])]
    minute = frame_index * 0.25
    hands_ = [np.array([face, face + np.array([np.sin(minute), -np.cos(minute)]) * size * 0.42]),
              np.array([face, face + np.array([np.sin(minute / 12), -np.cos(minute / 12)]) * size * 0.28])]
    return [dial] + strap + hands_


def _ribbon_watch(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    _center, across, down = frame
    up = -down
    side = event.kind if event is not None and event.kind in ("left", "right") else "right"
    wrist, elbow = body.get(f"{side}_wrist"), body.get(f"{side}_elbow")
    if wrist is None or elbow is None:
        return []
    u = _phase(runtime, event)
    age = runtime.active_frames
    if u < 0.4:  # las cintas orbitan y se van cerrando sobre la muñeca
        return ribbon_curves(body, frame, scale, age, layer, alpha, wrist, _ease(_seg(u, 0.2, 0.4)) * 0.9)
    along = (wrist - elbow) / max(float(np.linalg.norm(wrist - elbow)), 1e-6)
    size = 0.16 * scale
    ribbons = [resample(c) for c in ribbon_curves(body, frame, scale, age, np.zeros_like(layer), 0.0, wrist, 0.9)] or [np.array([wrist, wrist + across])]
    bow = _bow(wrist, size, across, up)
    watch = _watch(wrist, size, along, frame_index)
    lines, _stage = chain([(0.4, ribbons), (0.5, bow), (0.68, watch)], u, blend=0.6)
    tint = accent(runtime, color) if u >= 0.62 else color  # el cambio de color al volverse reloj
    return [(line, tint) for line in lines]


# ----- las espadas del samurái -----


def _samurai(body, frame, scale, runtime, layer, alpha, event) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    st = runtime.swoosh.setdefault(f"swords:{body.prefix}:{event.start_frame if event else 0}", {})
    lines = []
    for side in ("left", "right"):
        shoulder, wrist, elbow = body.get(f"{side}_shoulder"), body.get(f"{side}_wrist"), body.get(f"{side}_elbow")
        if shoulder is None:
            continue
        sign = 1.0 if float((shoulder - center) @ across) >= 0 else -1.0
        out = across * sign
        hilt_base = shoulder + up * 0.1 * scale - out * 0.05 * scale
        hilt_tip = hilt_base + up * 0.32 * scale + out * 0.12 * scale
        reach = wrist is not None and wrist[1] < shoulder[1] + 0.1 * scale and float(np.linalg.norm(wrist - hilt_tip)) < 0.55 * scale
        if reach:
            st[side] = True  # la alcanzó: la espada sale
        if st.get(side) and wrist is not None and elbow is not None:
            d = _unit(wrist - elbow)
            n = np.array([-d[1], d[0]])
            guard = wrist + d * 0.05 * scale
            tip = guard + d * 1.3 * scale
            blade = np.array([guard + n * 0.025 * scale, tip - d * 0.08 * scale + n * 0.02 * scale, tip, guard - n * 0.025 * scale])
            fill_polygon(layer, blade, WHITE * 0.95, alpha * 0.9, 1.0, feather=1.0)
            lines += [blade, np.array([guard + n * 0.08 * scale, guard - n * 0.08 * scale]), np.array([wrist - d * 0.12 * scale, guard])]
        else:  # la empuñadura asoma sobre el hombro, con su guarda; la hoja va en la espalda
            d = _unit(hilt_tip - hilt_base)
            n = np.array([-d[1], d[0]])
            lines += [np.array([hilt_base, hilt_tip]), np.array([hilt_base + n * 0.06 * scale, hilt_base - n * 0.06 * scale])]
            fill_band(layer, np.array([hilt_base, hilt_tip]), np.array([0.04, 0.04]) * scale, alpha * 0.8)
    return lines


# ----- la energía que cambia de forma hasta el puño -----


def _energy_chain(body, frame, scale, frame_index, runtime, layer, alpha, event) -> list[np.ndarray]:
    _center, across, down = frame
    up = -down
    lh, rh = body.get("left_hip"), body.get("right_hip")
    side = event.kind if event is not None and event.kind in ("left", "right") else "right"
    fist = _hand(body, side)
    if lh is None or rh is None or fist is None:
        return []
    u = _phase(runtime, event)
    waist = (lh + rh) / 2 - down * 0.05 * scale
    span = rh - lh
    q = np.linspace(0, 1, 13)
    zig = lh + np.outer(q, span) - down * 0.05 * scale + np.outer(np.where(np.arange(13) % 2, 0.06, -0.06) * scale, down)
    belly = waist - down * 0.15 * scale
    bow = _bow(belly, 0.12 * scale, across, up)
    # Un aro que orbita una soga imaginaria de la panza al puño: avanza y gira.
    travel = _ease(_seg(u, 0.4, 0.6))
    rope = fist - belly
    on_rope = belly + rope * travel
    d = _unit(rope)
    n = np.array([-d[1], d[0]])
    spin = runtime.active_frames * 0.6
    ring = on_rope + np.outer(np.cos(np.linspace(0, TAU, 28)) * 0.09 * scale, n) + np.outer(np.sin(np.linspace(0, TAU, 28)) * 0.04 * scale * np.cos(spin), d)
    ball = _ellipse(fist, 0.03 * scale, 0.03 * scale, across, up, n=12)
    fist_ring = _ellipse(fist, 0.13 * scale, 0.13 * scale, across, up, n=32)
    if 0.6 <= u < 0.72:
        fill_polygon(layer, _ellipse(fist, 0.05 * scale, 0.05 * scale, across, up, n=14), WHITE, alpha, 1.2, feather=1.0)
    lines, _stage = chain([(0.0, [zig]), (0.2, bow), (0.38, [ring]), (0.6, [ball]), (0.72, [fist_ring])], u, blend=0.5)
    if 0.38 <= u < 0.6:  # mientras viaja, el aro se mueve con la soga
        lines = [ring]
    return lines


# ----- el preso que rompe la reja -----


def _jail_break(body, frame, scale, frame_index, runtime, layer, color, alpha, event, rng) -> list:
    _center, across, down = frame
    up = -down
    nose = head_point(body, frame, scale)
    u = _phase(runtime, event)
    eyes = _eyes(body, nose, across, up, scale)
    lines: list = []
    breaking = _seg(u, 0.62, 1.0)
    if breaking <= 0:
        shake = 0.02 * scale * _seg(u, 0.25, 0.62) * np.sin(frame_index * 2.1)
        for k in range(4):  # los barrotes
            x = (k - 1.5) * 0.17 * scale
            base = nose + across * (x + shake * (1 if k % 2 else -1))
            lines.append(np.array([base + up * 0.45 * scale, base - up * 0.35 * scale]))
        for eye, s in ((eyes[0], -1.0), (eyes[1], 1.0)):  # ojos enojados con cejas hacia el centro
            lines.append(_ellipse(eye, 0.04 * scale, 0.025 * scale, across, up, n=12))
            brow = eye + up * 0.06 * scale
            lines.append(np.array([brow - across * s * 0.06 * scale + up * 0.03 * scale, brow + across * s * 0.03 * scale - up * 0.01 * scale]))
        return lines
    for k in range(4):  # se rompen en partículas que salen volando y caen
        x = (k - 1.5) * 0.17 * scale
        for j in range(10):
            start = nose + across * x + up * (0.45 - 0.08 * j) * scale
            angle = rng.uniform(0, TAU)
            v = np.array([np.cos(angle), np.sin(angle)]) * rng.uniform(0.3, 0.9) * scale
            at = start + v * breaking + down * 0.6 * scale * breaking ** 2
            if j % 3 == 0 and breaking < 0.5:
                lines.append(np.array([at, at + _unit(v) * 0.04 * scale]))
            splat(layer, float(at[0]), float(at[1]), 0.015 * scale + 0.5, np.asarray(color, np.float32) * 1.3, alpha * (1 - breaking), runtime.kernels)
    return lines


# ----- la luna que se vuelve paloma y luego wifi -----


def _dove(at: np.ndarray, size: float, across, up, flap: float) -> list[np.ndarray]:
    """Una paloma de perfil: cuerpo, cabeza con pico, cola y dos alas que aletean."""
    body_ = _ellipse(at, size * 0.55, size * 0.22, across, up, n=24)
    head = at + across * size * 0.6 + up * size * 0.18
    beak = np.array([head + across * size * 0.12, head + across * size * 0.28 - up * size * 0.03, head + across * size * 0.12 - up * size * 0.06])
    tail = np.array([at - across * size * 0.5, at - across * size * 0.95 + up * size * 0.2, at - across * size * 0.9 - up * size * 0.15, at - across * size * 0.5])
    lift = 0.55 + 0.45 * np.sin(flap)
    wing = np.array([at + across * size * 0.15, at - across * size * 0.1 + up * size * lift, at - across * size * 0.45 + up * size * lift * 0.9, at - across * size * 0.25])
    return [body_, _ellipse(head, size * 0.12, size * 0.12, across, up, n=12), beak, tail, wing]


def _moon_dove_wifi(body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    _center, across, down = frame
    up = -down
    side = event.kind if event is not None and event.kind in ("left", "right") else "right"
    hand = _hand(body, side)
    if hand is None:
        return []
    palm = hand + up * 0.18 * scale
    u = _phase(runtime, event)
    size = 0.2 * scale
    t = np.linspace(-np.pi * 0.75, np.pi * 0.75, 20)
    outer = palm + np.outer(np.cos(t) * size, across) + np.outer(np.sin(t) * size, up)
    inner = palm + across * size * 0.4 + np.outer(np.cos(t[::-1]) * size * 0.75, across) + np.outer(np.sin(t[::-1]) * size * 0.75, up)
    moon = [np.vstack([outer, inner])]
    drop = _ease(_seg(u, 0.35, 0.55))
    dove_at = palm + up * (0.9 - 0.75 * drop) * scale  # la paloma aparece arriba y desciende a la palma
    dove = _dove(dove_at, size * 1.2, across, up, frame_index * 0.7)
    age = runtime.active_frames
    arcs = []
    for k in range(3):
        r = (0.14 + 0.15 * k) * scale * (1.0 + 0.1 * np.sin(age * 0.5 - k))
        a = np.linspace(np.pi * 0.25, np.pi * 0.75, 14)
        arcs.append(palm + np.outer(np.cos(a) * r, across) + np.outer(np.sin(a) * r, up))
    lines, stage = chain([(0.0, moon), (0.3, dove), (0.62, arcs)], u, blend=0.35)
    if stage == 0:
        fill_polygon(layer, moon[0], np.asarray(color, np.float32), alpha * 0.5, 1.0, feather=1.0)
    tint = WHITE if 0.25 <= u < 0.62 else (accent(runtime, color) if u >= 0.62 else color)  # la paloma, blanca
    return [(line, tint) for line in lines]


def morph_fx(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    seed = zlib.crc32(f"{shape}:{body.prefix}:{event.start_frame if event else 0}".encode())
    rng = np.random.default_rng((seed + frame_index // 2) & 0xFFFFFFFF)
    if shape == "horns_morph":
        return _horns_morph(body, frame, scale, runtime, color, event)
    if shape == "rubber_band":
        return _rubber_band(body, frame, scale, frame_index, runtime, layer, event)
    if shape == "hand_echo":
        return _hand_echo(body, scale, frame_index, runtime, color, event)
    if shape == "head_shot":
        return _head_shot(body, frame, scale, frame_index, runtime, layer, color, event, np.random.default_rng(seed))
    if shape == "dough_tie":
        return _dough_tie(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "tie_on":
        return _tie_on(body, frame, scale, runtime, layer, event)
    if shape == "orbit_ribbons":
        return ribbon_curves(body, frame, scale, runtime.active_frames, layer, alpha)
    if shape == "ribbon_watch":
        return _ribbon_watch(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    if shape == "samurai_swords":
        return _samurai(body, frame, scale, runtime, layer, alpha, event)
    if shape == "energy_chain":
        return _energy_chain(body, frame, scale, frame_index, runtime, layer, alpha, event)
    if shape == "jail_break":
        return _jail_break(body, frame, scale, frame_index, runtime, layer, color, alpha, event, rng)
    if shape == "moon_dove_wifi":
        return _moon_dove_wifi(body, frame, scale, frame_index, runtime, layer, color, alpha, event)
    return []
