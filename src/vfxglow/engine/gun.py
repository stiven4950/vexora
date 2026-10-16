"""El revólver con la mano (adornos `type: adornment`, `style.shapes`).

Idea del usuario al ver dance_two_mens (seg. 7,2): la mano en forma de pistola (índice al frente,
pulgar arriba) y el pulgar que baja como el martillo, con un pequeño retroceso. El análisis
(gestures.finger_gun_events) marca cada caída del pulgar como un disparo en `event.detail`
("disparos=180,192"); sin caída, se dispara una vez en un instante al azar de la pose.

- `finger_gun`: un revólver de neón dibujado sobre la mano (cañón por el índice, tambor, martillo,
  guardamonte y cacha), que en cada disparo da un fogonazo, patea hacia arriba (retroceso) y suelta
  la bala con su estela, ondas en la boca del cañón, el casquillo que salta y humo que sube.
- `bullet`: solo el disparo desde el dedo, sin el arma dibujada.
"""

from __future__ import annotations

import zlib

import numpy as np

from vfxglow.engine.critters import TAU, WHITE, _activation
from vfxglow.engine.raster import fill_polygon, splat

GUNS = ("finger_gun", "bullet")
# Cuadros que dura cada parte del disparo.
FLASH, RECOIL, BULLET, SMOKE = 4, 8, 14, 22


def _shots(event, first_frame: int) -> list[int]:
    """Los cuadros de disparo del evento, o uno al azar (estable) si el análisis no vio ninguno.
    Sin evento (efecto encendido a mano), dispara apenas se enciende."""
    if event is None:
        return [first_frame]
    text = event.detail.split("disparos=", 1)[1] if "disparos=" in event.detail else ""
    shots = [int(x) for x in text.split(",") if x.strip().isdigit()]
    if shots:
        return shots
    span = max(event.end_frame - event.start_frame, 1)
    pick = zlib.crc32(f"{event.target}:{event.start_frame}".encode()) % 1000 / 1000.0
    return [event.start_frame + int(span * (0.35 + 0.3 * pick))]


def _aim(body, side: str, scale: float):
    """(boca de la mano, dirección del cañón, normal hacia el pulgar, largo del arma)."""
    wrist, elbow = body.get(f"{side}_wrist"), body.get(f"{side}_elbow")
    if wrist is None:
        return None
    tip, knuckle, thumb = body.get(f"{side}_index_tip"), body.get(f"{side}_index_mcp"), body.get(f"{side}_thumb_tip")
    if tip is not None and knuckle is not None and np.linalg.norm(tip - knuckle) > 2:
        d = (tip - knuckle) / float(np.linalg.norm(tip - knuckle))
        base = knuckle
    elif elbow is not None:
        d = (wrist - elbow) / max(float(np.linalg.norm(wrist - elbow)), 1e-6)
        base, tip = wrist + d * 0.08 * scale, wrist + d * 0.22 * scale
    else:
        return None
    n = np.array([-d[1], d[0]])
    up = (thumb - base) if thumb is not None else np.array([0.0, -1.0])
    if float(np.dot(n, up)) < 0:  # la normal apunta hacia el pulgar (arriba del arma)
        n = -n
    length = max(float(np.linalg.norm(tip - wrist)) * 1.5, 0.35 * scale)
    return base, d, n, length


def _revolver(origin, d, n, L, layer, color, alpha, spin: float) -> list[np.ndarray]:
    """Revólver en coordenadas del arma: x por el cañón, y hacia el martillo (arriba)."""

    def at(points):
        return np.array([origin + d * x * L + n * y * L for x, y in points])

    frame = at([(-0.05, -0.02), (0.42, -0.02), (0.42, 0.2), (0.1, 0.24), (-0.05, 0.18), (-0.05, -0.02)])
    barrel = at([(0.42, 0.06), (1.0, 0.06), (1.0, 0.18), (0.42, 0.18)])
    grip = at([(0.05, -0.02), (-0.08, -0.5), (-0.28, -0.46), (-0.12, -0.02)])
    fill_polygon(layer, frame, np.asarray(color, np.float32), alpha * 0.3, 0.9, feather=1.0)
    fill_polygon(layer, grip, np.asarray(color, np.float32), alpha * 0.45, 0.9, feather=1.0)
    t = np.linspace(0, TAU, 20)
    center = origin + d * 0.25 * L + n * 0.09 * L
    cylinder = center + np.outer(np.cos(t), d) * 0.13 * L + np.outer(np.sin(t), n) * 0.11 * L
    chambers = [center + (np.cos(a + spin) * d * 0.13 + np.sin(a + spin) * n * 0.11) * 0.55 * L for a in (0.0, TAU / 3, 2 * TAU / 3)]
    hammer = at([(-0.02, 0.18), (-0.1, 0.32), (-0.04, 0.33)])
    guard = at([(0.12, -0.02), (0.15, -0.16), (0.3, -0.16), (0.32, -0.02)])
    trigger = at([(0.2, -0.02), (0.22, -0.11)])
    sight = at([(0.95, 0.18), (0.95, 0.23)])
    grooves = [at([(-0.06 - 0.04 * k, -0.12 - 0.1 * k), (-0.16 - 0.03 * k, -0.11 - 0.1 * k)]) for k in range(3)]
    lines = [frame, barrel, grip, cylinder, hammer, guard, trigger, sight, *grooves]
    lines += [c + np.array([[0.02 * L, 0.0], [-0.02 * L, 0.0]]) for c in chambers]
    return lines


def _star(center, radius, spikes, rotation) -> np.ndarray:
    angles = np.linspace(0, TAU, spikes * 2 + 1) + rotation
    radii = np.where(np.arange(len(angles)) % 2 == 0, radius, radius * 0.4)
    return center + np.stack([np.cos(angles) * radii, np.sin(angles) * radii], axis=1)


def _rotate(v: np.ndarray, angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([v[0] * c - v[1] * s, v[0] * s + v[1] * c])


def gun(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list[np.ndarray]:
    side = event.kind if event is not None and event.kind in ("left", "right") else None
    if side is None:  # el brazo más extendido
        center = frame[0]
        reach = {s: float(np.linalg.norm(body.get(f"{s}_wrist") - center)) for s in ("left", "right") if body.get(f"{s}_wrist") is not None}
        if not reach:
            return []
        side = max(reach, key=reach.get)
    aim = _aim(body, side, scale)
    if aim is None:
        return []
    base, d, n, L = aim
    st = _activation(runtime, event, "gun", body)
    shots = _shots(event, st.setdefault("first", frame_index - 1))
    lines: list[np.ndarray] = []
    # Retroceso: la boca sube hacia el pulgar justo después de cada disparo y vuelve.
    kick = 0.0
    for shot in shots:
        age = frame_index - shot
        if 0 <= age < RECOIL:
            kick = max(kick, 0.45 * np.exp(-age / 2.5))
    toward = 1.0 if float(d[0] * n[1] - d[1] * n[0]) > 0 else -1.0  # gira el cañón hacia el pulgar
    d_now = _rotate(d, kick * toward)
    n_now = np.array([-d_now[1], d_now[0]]) * (1 if float(np.dot(np.array([-d_now[1], d_now[0]]), n)) > 0 else -1)
    origin = base - d_now * 0.35 * L
    muzzle = origin + d_now * 1.02 * L + n_now * 0.12 * L
    if shape == "finger_gun":
        spin = sum(TAU / 3 for s in shots if frame_index >= s)  # el tambor gira un tiro
        lines += _revolver(origin, d_now, n_now, L, layer, color, alpha, spin)
    else:
        muzzle = body.get(f"{side}_index_tip") if body.get(f"{side}_index_tip") is not None else base + d * 0.2 * scale
    height, width = layer.shape[:2]
    for k, shot in enumerate(shots):
        age = frame_index - shot
        if age < 0:
            continue
        key = f"shot{k}"
        if key not in st:  # la bala sigue la dirección del instante del disparo
            st[key] = (muzzle.copy(), d.copy())
        start, way = st[key]
        if age < FLASH:  # fogonazo
            r = (0.32 - 0.06 * age) * L
            flash = _star(muzzle + way * r * 0.6, r, 7, frame_index * 0.7)
            fill_polygon(layer, flash, np.asarray(color, np.float32), alpha * 0.8, 0.9, feather=1.5)
            splat(layer, float(muzzle[0]), float(muzzle[1]), 0.18 * L, WHITE * 2.0, alpha, runtime.kernels)
            lines.append(flash)
        if age < BULLET:  # la bala y su estela, a toda velocidad
            head = start + way * (0.3 + age * 0.9) * scale
            if -0.2 * width < head[0] < 1.2 * width and -0.2 * height < head[1] < 1.2 * height:
                tail = head - way * min(0.3 + age * 0.9, 1.4) * scale
                lines.append(np.array([tail, head]))
                side_n = np.array([-way[1], way[0]])
                slug = np.array([head + side_n * 0.025 * scale, head + way * 0.07 * scale, head - side_n * 0.025 * scale])
                lines.append(slug)
                splat(layer, float(head[0]), float(head[1]), 0.03 * scale + 1, WHITE * 1.8, alpha, runtime.kernels)
        if age < 6:  # ondas en la boca del cañón
            t = np.linspace(0, TAU, 24)
            ring_n = np.array([-way[1], way[0]])
            ring = start + way * (0.05 + 0.08 * age) * scale + np.outer(np.cos(t), way) * 0.03 * scale * (1 + age) + np.outer(np.sin(t), ring_n) * 0.08 * scale * (1 + age)
            lines.append(ring)
        if shape == "finger_gun" and age < 10:  # el casquillo salta hacia atrás y cae
            casing = origin + d * 0.2 * L + n * 0.3 * L - d * age * 0.05 * scale + n * (age * 0.06 - age * age * 0.008) * scale
            lines.append(np.array([casing - d * 0.03 * scale, casing + d * 0.03 * scale]))
        if 3 <= age < SMOKE:  # humo que sube enroscado desde la boca
            s = (age - 3) / (SMOKE - 3)
            rise = np.linspace(0, 1, 10)[: max(int(10 * (1 - s)), 2)]
            curl = np.array([muzzle + n * r * 0.6 * scale * (0.3 + s) + d * np.sin(r * 6 + frame_index * 0.3) * 0.05 * scale for r in rise])
            lines.append(curl)
    return lines
