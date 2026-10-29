"""Efectos de solista de la referencia video_52 (docs/referencias/video_52.md).

Adornos (`type: adornment`, `style.shapes`), como los de engine/duo_fx.py:

- ecg_arm: con el brazo estirado, una línea de electrocardiograma corre del hombro a la mano con
  el pulso que avanza; al final se vuelve aros ("OOOO") y se deshace en puntos (seg. 23,5-24,5).
- sky_bolt: la mano levantada recibe un rayo que baja desde el borde de arriba del cuadro y se
  abre en chispas al tocarla (seg. 10,4-10,6; el meteoro de unpair_dance, seg. 12,8-13,6).
- wifi_hand: arcos de wifi que se abren uno tras otro sobre la mano abierta (seg. 30,0-30,5).
- thought_cloud: círculos que suben de la cabeza a una nube que tiembla (seg. 13,4-14,1).
- leg_coil: un resorte que sube enroscado por la pierna, del tobillo a la rodilla, y se esconde
  detrás de ella (seg. 32,1-32,4).
- kick_bolt: un rayo que sale del pie en la dirección de la patada y se deshace en chispas
  (seg. 32,5-32,8).
- hair_trails: en un latigazo de la cabeza, estelas que salen del pelo al lado contrario del
  movimiento y se apagan en chispas (seg. 33,1-33,2).
- head_orbit: un aro inclinado que orbita la cabeza; la parte de atrás se esconde detrás de ella
  (seg. 1,8-2,4).
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.duo_fx import branched, fill_band, taper, visible
from vfxglow.engine.raster import splat

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
SOLO_FX = ("ecg_arm", "sky_bolt", "wifi_hand", "thought_cloud", "leg_coil", "kick_bolt", "hair_trails", "head_orbit")
# Los rayos cambian de forma cada tantos fotogramas, como un dibujo a mano.
BOLT_FRAMES = 2


def _side(body, event, joint: str = "wrist") -> str | None:
    """El lado del evento, o el de la articulación más alta (la que hace el gesto)."""
    for side in ("left", "right"):
        if event is not None and (event.kind == side or event.target.endswith(f":{side}") or f"{side}_" in event.target):
            return side
    found = [(s, body.get(f"{s}_{joint}")) for s in ("left", "right")]
    found = [(s, p) for s, p in found if p is not None]
    if not found:
        return None
    return min(found, key=lambda item: item[1][1])[0] if joint == "wrist" else max(found, key=lambda item: item[1][1])[0]


def _velocity(body, joint: str) -> np.ndarray:
    vel = body.points.get(f"vel:{body.prefix}{joint}")
    return np.asarray(vel, dtype=np.float64) if vel is not None else np.zeros(2)


def _ecg(body, scale, frame_index, runtime, layer, color, alpha, event, rng) -> list[np.ndarray]:
    side = _side(body, event)
    if side is None:
        return []
    shoulder, elbow, wrist = (body.get(f"{side}_{j}") for j in ("shoulder", "elbow", "wrist"))
    if shoulder is None or wrist is None:
        return []
    along = wrist - shoulder
    length = float(np.linalg.norm(along))
    if length < 0.4 * scale:
        return []
    d = along / length
    n = np.array([-d[1], d[0]])
    if n[1] > 0:
        n = -n  # el pulso sube
    u = _phase(runtime, event)
    if u > 0.8:  # el pulso se vuelve aros y luego puntos
        rings = []
        fade = _seg(u, 0.9, 1.0)
        for k in range(4):
            at = shoulder + along * (0.35 + 0.18 * k)
            if fade > 0:
                splat(layer, float(at[0]), float(at[1]), 0.03 * scale, WHITE * 0.6, alpha * (1 - fade), runtime.kernels)
                continue
            t = np.linspace(0, TAU, 18)
            rings.append(at + np.outer(np.cos(t), d * 0.07 * scale) + np.outer(np.sin(t), n * 0.07 * scale))
        return rings
    # La línea base con un latido cada tanto; el latido corre hacia la mano.
    x = np.linspace(0.0, 1.0, 90)
    head = (frame_index * 0.06) % 1.0
    beat = np.zeros_like(x)
    for center in (head, (head + 0.5) % 1.0):
        s = (x - center) / 0.08
        beat += np.where(np.abs(s) < 1.0, np.interp(s, [-1, -0.6, -0.3, 0.0, 0.3, 0.6, 1.0], [0, 0.1, -0.25, 1.0, -0.45, 0.08, 0]), 0.0)
    grow = _ease(_seg(u, 0.0, 0.2))  # la línea se traza del hombro a la mano
    keep = x <= grow
    line = shoulder + np.outer(x[keep] * length, d) + np.outer(beat[keep] * 0.5 * scale, n)
    if len(line) < 2:
        return []
    tip = line[-1]
    splat(layer, float(tip[0]), float(tip[1]), 0.04 * scale, WHITE * 0.8, alpha, runtime.kernels)
    return [line]


def _sky_bolt(body, scale, frame_index, runtime, layer, color, alpha, event, rng) -> list[np.ndarray]:
    side = _side(body, event)
    hand = body.get(f"{side}_wrist") if side else None
    if hand is None:
        return []
    u = _phase(runtime, event)
    drop = _ease(_seg(u, 0.15, 0.4))  # baja desde arriba del cuadro
    if drop <= 0:
        return []
    top = np.array([hand[0], -0.05 * layer.shape[0]])  # justo encima de la mano
    end = top + (hand - top) * drop
    from vfxglow.engine.duo_doodles import zigzag

    main = zigzag(np.array([top, end]), 0.12 * scale, rng, 0.12 * scale)
    lines = [main]
    for _ in range(3):  # ramitas
        k = int(rng.integers(1, max(len(main) - 1, 2)))
        angle = rng.uniform(np.pi * 0.15, np.pi * 0.85)
        lines += branched(main[k], np.array([np.cos(angle) * rng.choice([-1, 1]), np.sin(angle)]), scale * 0.2, rng, 1)
    if drop >= 1.0:  # el golpe en la mano
        hit = _seg(u, 0.4, 0.7)
        splat(layer, float(hand[0]), float(hand[1]), (0.12 + 0.2 * hit) * scale, WHITE * 0.8 + np.asarray(color, np.float32) * 0.6, alpha * (1 - 0.7 * hit), runtime.kernels)
        for k in range(6):
            angle = TAU * k / 6 + rng.uniform(-0.3, 0.3)
            lines += branched(hand, np.array([np.cos(angle), np.sin(angle)]), scale * (0.15 + 0.2 * hit), rng, 1)
        if u > 0.75:
            return lines[:1] if u < 0.85 else []
    return lines


def _wifi(body, scale, frame_index, runtime, layer, color, alpha, event, rng, frame) -> list[np.ndarray]:
    side = _side(body, event)
    hand = body.get(f"{side}_wrist") if side else None
    if hand is None:
        return []
    tip = body.get(f"{side}_middle_tip")
    up = -frame[2]
    base = (tip if tip is not None else hand) + up * 0.12 * scale
    splat(layer, float(base[0]), float(base[1]), 0.035 * scale, WHITE * 0.8, alpha, runtime.kernels)
    lines = []
    age = runtime.active_frames
    side_axis = np.array([-up[1], up[0]])
    for k in range(3):
        grow = float(np.clip((age - k * 3) / 4.0, 0.0, 1.0))  # cada arco aparece después del anterior
        pulse = 1.0 + 0.12 * np.sin(age * 0.5 - k)
        if grow <= 0:
            continue
        r = (0.16 + 0.17 * k) * scale * pulse
        t = np.linspace(np.pi * 0.22, np.pi * 0.78, 14)
        half = (t - np.pi / 2) * grow + np.pi / 2
        lines.append(base + np.outer(np.cos(half), side_axis * r) + np.outer(np.sin(half), up * r))
    return lines


def _cloud(center: np.ndarray, rx: float, ry: float, wobble: float, lumps: int = 7) -> np.ndarray:
    t = np.linspace(0, TAU, 80)
    bump = 1.0 + 0.16 * np.abs(np.sin(t * lumps / 2)) + 0.03 * np.sin(t * 3 + wobble)
    return center + np.stack([np.cos(t) * rx * bump, np.sin(t) * ry * bump], axis=1)


def _thought(body, scale, frame_index, runtime, layer, color, alpha, event, rng, frame) -> list[np.ndarray]:
    nose = body.get("nose")
    if nose is None:
        return []
    center, across, down = frame
    up = -down
    u = _phase(runtime, event)
    lean = across if (nose - center) @ across >= 0 else -across
    head = nose + up * 0.25 * scale
    lines = []
    for k, size in enumerate((0.05, 0.08, 0.11)):  # los círculos que suben
        if u < 0.08 * (k + 1):
            continue
        at = head + up * (0.18 + 0.2 * k) * scale + lean * (0.12 + 0.12 * k) * scale
        t = np.linspace(0, TAU, 16)
        lines.append(at + np.stack([np.cos(t), np.sin(t)], axis=1) * size * scale)
    grow = _ease(_seg(u, 0.3, 0.45))
    if grow > 0:
        at = head + up * 1.05 * scale + lean * 0.55 * scale
        lines.append(_cloud(at, 0.42 * scale * grow, 0.28 * scale * grow, frame_index * 0.3))
    return lines


def _coil(body, scale, frame_index, runtime, layer, color, alpha, event, rng) -> list[np.ndarray]:
    side = _side(body, event, "ankle")
    if side is None:
        return []
    ankle, knee = body.get(f"{side}_ankle"), body.get(f"{side}_knee")
    if ankle is None or knee is None:
        return []
    u = _phase(runtime, event)
    reach = _ease(_seg(u, 0.0, 0.5))
    along = knee - ankle
    length = float(np.linalg.norm(along))
    if length < 1:
        return []
    d = along / length
    n = np.array([-d[1], d[0]])
    turns = 3.5
    phi = np.linspace(0, turns * TAU, 160)
    s = np.linspace(0, 1, 160) * reach
    radius = 0.13 * scale * (1.1 - 0.3 * s)
    spin = runtime.active_frames * 0.25
    x = np.cos(phi + spin)
    z = np.sin(phi + spin)
    curve = ankle + np.outer(s * length, d) + np.outer(x * radius, n) + np.outer(z * radius * 0.28, d)
    widths = 0.035 * scale * np.ones(len(curve))
    lines = []
    for a, b in visible(curve, z, None):  # la parte de atrás del resorte queda detrás de la pierna
        fill_band(layer, curve[a:b], widths[a:b], alpha * 0.9)
        lines.append(curve[a:b])
    return lines


def _kick(body, scale, frame_index, runtime, layer, color, alpha, event, rng) -> list[np.ndarray]:
    side = _side(body, event, "ankle")
    if side is None:
        return []
    foot = body.get(f"{side}_foot_index")
    ankle = body.get(f"{side}_ankle")
    tip = foot if foot is not None else ankle
    if tip is None:
        return []
    st = runtime.swoosh.setdefault(f"kick:{body.prefix}:{event.start_frame if event else 0}", {})
    vel = _velocity(body, f"{side}_ankle")
    if "dir" not in st and float(np.linalg.norm(vel)) > 1e-3:
        st["dir"] = vel / float(np.linalg.norm(vel))
    knee = body.get(f"{side}_knee")
    fallback = (tip - knee) / max(float(np.linalg.norm(tip - knee)), 1e-6) if knee is not None else np.array([1.0, 0.0])
    d = st.get("dir", fallback)
    u = _phase(runtime, event)
    reach = _ease(_seg(u, 0.0, 0.35))
    from vfxglow.engine.duo_doodles import zigzag

    end = tip + d * 1.6 * scale * reach
    lines = [zigzag(np.array([tip, end]), 0.08 * scale, rng, 0.1 * scale)] if reach > 0.05 and u < 0.7 else []
    if u >= 0.35:  # se deshace en chispas en la punta
        sparks = _seg(u, 0.35, 1.0)
        for k in range(7):
            angle = np.arctan2(d[1], d[0]) + rng.uniform(-1.0, 1.0)
            at = tip + d * 1.6 * scale + np.array([np.cos(angle), np.sin(angle)]) * sparks * 0.5 * scale
            splat(layer, float(at[0]), float(at[1]), 0.02 * scale + 0.5, WHITE * 0.7, alpha * (1 - sparks), runtime.kernels)
    return lines


def _hair(body, scale, frame_index, runtime, layer, color, alpha, event, rng, frame) -> list[np.ndarray]:
    nose = body.get("nose")
    if nose is None:
        return []
    up = -frame[2]
    crown = nose + up * 0.3 * scale
    st = runtime.swoosh.setdefault(f"hair:{body.prefix}:{event.start_frame if event else 0}", {})
    vel = _velocity(body, "nose")
    if "dir" not in st:
        st["dir"] = -vel / float(np.linalg.norm(vel)) if float(np.linalg.norm(vel)) > 1e-3 else -frame[1]
    back = st["dir"]
    u = _phase(runtime, event)
    lines = []
    if u < 0.55:
        for k in range(5):
            spread = (k - 2) * 0.28  # en abanico desde la coronilla
            ray = np.array([back[0] * np.cos(spread) - back[1] * np.sin(spread), back[0] * np.sin(spread) + back[1] * np.cos(spread)])
            side = np.array([-ray[1], ray[0]])
            start = crown + ray * 0.15 * scale
            length = (0.75 + 0.25 * np.sin(k * 1.7)) * scale * _ease(_seg(u, 0.0, 0.25))
            q = np.linspace(0, 1, 14)[:, None]
            curve = start + ray * q * length + side * np.sin(q * np.pi) * 0.06 * scale * (1 if k % 2 else -1)
            fill_band(layer, curve, 0.022 * scale * np.linspace(1.0, 0.2, len(curve)), alpha * 0.8)
            lines.append(curve)
    else:  # se apagan en chispas
        sparks = _seg(u, 0.55, 1.0)
        for k in range(8):
            at = crown + back * (0.4 + 0.4 * sparks) * scale + np.array([rng.uniform(-1, 1), rng.uniform(-1, 1)]) * 0.15 * scale
            splat(layer, float(at[0]), float(at[1]), 0.015 * scale + 0.5, WHITE * 0.7, alpha * (1 - sparks), runtime.kernels)
    return lines


def _head_orbit(body, scale, frame_index, runtime, layer, color, alpha, event, frame) -> list[np.ndarray]:
    nose = body.get("nose")
    if nose is None:
        return []
    _center, across, down = frame
    up = -down
    from vfxglow.engine.duo_fx import body_mask

    pivot = nose + up * 0.1 * scale
    radius = 0.5 * scale
    age = runtime.active_frames
    a0 = age * 0.35
    phi = np.linspace(a0, a0 + 3.2, 48)  # un arco que gira
    x, z = np.cos(phi), np.sin(phi)
    tilt = 0.35 * np.sin(age * 0.08)
    curve = pivot + np.outer(x * radius, across) + np.outer(z * radius * 0.3 + x * radius * tilt, up)
    widths = 0.09 * scale * taper(len(phi), 0.8) * (0.55 + 0.45 * (z > 0))
    lines = []
    for a, b in visible(curve, z, body_mask(body, layer.shape[:2], scale)):
        fill_band(layer, curve[a:b], widths[a:b], alpha * 0.95)
        lines.append(curve[a:b])
    return lines


def solo_fx(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    seed = zlib.crc32(f"{shape}:{body.prefix}:{event.start_frame if event else 0}".encode())
    rng = np.random.default_rng((seed + frame_index // BOLT_FRAMES) & 0xFFFFFFFF)
    if shape == "ecg_arm":
        return _ecg(body, scale, frame_index, runtime, layer, color, alpha, event, rng)
    if shape == "sky_bolt":
        return _sky_bolt(body, scale, frame_index, runtime, layer, color, alpha, event, rng)
    if shape == "wifi_hand":
        return _wifi(body, scale, frame_index, runtime, layer, color, alpha, event, rng, frame)
    if shape == "thought_cloud":
        return _thought(body, scale, frame_index, runtime, layer, color, alpha, event, rng, frame)
    if shape == "leg_coil":
        return _coil(body, scale, frame_index, runtime, layer, color, alpha, event, rng)
    if shape == "kick_bolt":
        return _kick(body, scale, frame_index, runtime, layer, color, alpha, event, rng)
    if shape == "hair_trails":
        return _hair(body, scale, frame_index, runtime, layer, color, alpha, event, rng, frame)
    if shape == "head_orbit":
        return _head_orbit(body, scale, frame_index, runtime, layer, color, alpha, event, frame)
    return []
