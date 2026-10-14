"""Efectos con volumen y movimiento de la referencia video_34 (segunda lectura, cuadro a cuadro).

Adornos (`type: adornment`, `style.shapes`), como los de engine/duo_doodles.py:

- soul: el "alma" de la cabeza: al mover la cabeza, una media luna brillante se queda atrás por
  el impulso y regresa como una liga (resorte amortiguado) hasta abrazar la cabeza (seg. 15-16,5).
- ribbon: cinta de gimnasia rítmica que sale de la mano: se despliega, ondula, se tuerce (la
  cinta se ve de canto y de frente) y se enrosca en lazos en perspectiva (seg. 3,7-4,7).
- rose_heart: una rosa que empieza como corazón y se abre en rosa; sube de la mano al pecho.
- energy_sparks: hilos de energía cortos y ramificados que saltan por el torso y los brazos y
  cambian de lugar cada dos cuadros (seg. 7,2-7,5).
- chest_heart: corazón blanco relleno en el pecho, donde se junta la energía (seg. 7,5).
- energy_wave: una nube de rayos que recorre el cuerpo siguiendo la parte que más se mueve; si
  la mano toca la de la pareja, un rayo la cruza (seg. 14,3-15,9).
- dj_disc: un disco acostado bajo cada palma, como una tornamesa: gira y suelta chispas de
  colores por el borde, como un esmeril (seg. 12,3).
- orbit_arcs: arcos en media luna (finos en las puntas, gruesos al centro) que giran alrededor
  del cuerpo en 3D; la parte que pasa por detrás de la persona no se ve (seg. 30,8-31,6).
- hand_orbit: el mismo aro de arcos alrededor de la mano, inclinado (seg. 31,9-32,3).

Las bandas con grosor variable se rellenan de blanco y el color va en el halo (P11).
"""

from __future__ import annotations

import colorsys

import cv2
import numpy as np

from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
DUO_FX = ("soul", "ribbon", "rose_heart", "energy_sparks", "chest_heart", "energy_wave", "dj_disc", "orbit_arcs", "hand_orbit")


def band(curve: np.ndarray, widths: np.ndarray) -> np.ndarray | None:
    """Polígono de una banda a lo largo de `curve` con un ancho por punto."""
    if len(curve) < 2:
        return None
    tangent = np.gradient(curve, axis=0)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)
    half = (widths / 2)[:, None] * normal
    return np.vstack([curve + half, (curve - half)[::-1]])


def taper(n: int, power: float = 1.0) -> np.ndarray:
    """Perfil fino-grueso-fino (seno), 0 en las puntas."""
    return np.sin(np.linspace(0.0, np.pi, n)) ** power


def fill_band(layer, curve, widths, alpha) -> None:
    poly = band(curve, widths)
    if poly is not None:
        fill_polygon(layer, poly, WHITE * 1.15, alpha, 1.0, feather=1.5)


def body_mask(body, shape: tuple[int, int], scale: float) -> np.ndarray | None:
    from vfxglow.engine.bodyglow import part_mask

    return part_mask(body, "body", shape, scale)


def visible(curve: np.ndarray, depth: np.ndarray, mask: np.ndarray | None) -> list[tuple[int, int]]:
    """Tramos (inicio, fin) de la curva que se ven: delante, o detrás pero fuera de la persona."""
    keep = depth >= 0
    if mask is not None:
        h, w = mask.shape
        xs = np.clip(np.round(curve[:, 0]).astype(int), 0, w - 1)
        ys = np.clip(np.round(curve[:, 1]).astype(int), 0, h - 1)
        keep = keep | (mask[ys, xs] == 0)
    spans, start = [], None
    for k, flag in enumerate(np.append(keep, False)):
        if flag and start is None:
            start = k
        elif not flag and start is not None:
            if k - start >= 2:
                spans.append((start, k))
            start = None
    return spans


def _zigzag(path, amp, rng, step):
    from vfxglow.engine.duo_doodles import zigzag

    return zigzag(path, amp, rng, step)


def branched(start: np.ndarray, direction: np.ndarray, length: float, rng, depth: int = 2) -> list[np.ndarray]:
    """Rayo corto con ramas que salen de puntos al azar, y ramas de las ramas."""
    end = start + direction * length
    main = _zigzag(np.array([start, end]), 0.25 * length, rng, max(length / 5, 2.0))
    out = [main]
    if depth > 0:
        for _ in range(int(rng.integers(1, 3))):
            k = int(rng.integers(1, max(len(main) - 1, 2)))
            angle = np.arctan2(direction[1], direction[0]) + rng.uniform(-1.2, 1.2)
            out += branched(main[k], np.array([np.cos(angle), np.sin(angle)]), length * rng.uniform(0.35, 0.6), rng, depth - 1)
    return out


def _side(event) -> str | None:
    if event is None:
        return None
    return next((s for s in ("left", "right") if s in event.target or event.kind == s), None)


def _wrist(body, event, center):
    side = _side(event)
    if side and body.get(f"{side}_wrist") is not None:
        return side, body.get(f"{side}_wrist")
    best = None
    for s in ("left", "right"):
        w = body.get(f"{s}_wrist")
        if w is not None and (best is None or np.linalg.norm(w - center) > np.linalg.norm(best[1] - center)):
            best = (s, w)
    return best


def _velocity(body, joint: str) -> np.ndarray:
    v = body.points.get(f"vel:{body.prefix}{joint}")
    return np.zeros(2) if v is None else np.asarray(v, dtype=np.float64)


def _state(runtime, key: str) -> dict:
    store = runtime.swoosh.setdefault("_duo_fx", {})
    if not isinstance(store, dict):
        store = runtime.swoosh["_duo_fx"] = {}
    return store.setdefault(key, {})


def duo_fx(shape, body, frame, scale, frame_index, seed, runtime, layer, color, alpha, head, event=None) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    age = runtime.active_frames
    rng = np.random.default_rng((seed + frame_index // 2) & 0xFFFFFFFF)
    hips = body.mid("left_hip", "right_hip")
    if shape == "soul" and head is not None:
        st = _state(runtime, f"soul:{body.prefix}")
        if age <= 1 or "pos" not in st:
            # Arranca desplazada contra el movimiento de la cabeza (lo que el impulso deja atrás).
            v = _velocity(body, "nose")
            direction = -v / np.linalg.norm(v) if np.linalg.norm(v) > 1.0 else across * (1.0 if seed % 2 else -1.0)
            st["pos"] = head + direction * 0.75 * scale
            st["vel"] = np.zeros(2)
            st["toward"] = -direction
        # Resorte amortiguado: va y se recoge como una goma.
        st["vel"] = (st["vel"] + (head - st["pos"]) * 0.12) * 0.78
        st["pos"] = st["pos"] + st["vel"]
        offset = head - st["pos"]
        if np.linalg.norm(offset) > 0.05 * scale:
            st["toward"] = offset / np.linalg.norm(offset)
        r = 0.5 * scale
        unit = np.stack([np.cos(np.linspace(0, TAU, 48)), np.sin(np.linspace(0, TAU, 48))], axis=1)
        disc = st["pos"] + unit * r
        # La mordida mira a la cabeza: la media luna la abraza al volver.
        bite = st["pos"] + st["toward"] * 0.38 * r + unit * r * 0.86
        fill_polygon(layer, disc, WHITE * 1.05, alpha * 0.9, 1.0, feather=3.0, holes=[bite])
        splat(layer, float(st["pos"][0]), float(st["pos"][1]), r * 1.1, color * 0.8, alpha * 0.35, runtime.kernels)
        return []
    if shape in ("ribbon", "rose_heart"):
        picked = _wrist(body, event, center)
        if picked is None:
            return []
        side, hand = picked
        outward = (hand - center) / max(float(np.linalg.norm(hand - center)), 1e-6)
        if shape == "rose_heart":
            from vfxglow.engine.duo_doodles import _heart, doodle

            chest = center + down * 0.3 * scale + across * (0.12 * scale if outward @ across > 0 else -0.12 * scale)
            u = float(np.clip(age / 12.0, 0.0, 1.0))
            bloom = hand + (chest - hand) * (u * u * (3 - 2 * u))
            if age < 10:
                # Primero un corazón que late en la mano y sube.
                heart = _heart(bloom, 0.14 * scale * (1.0 + 0.1 * np.sin(age)))
                fill_polygon(layer, heart, WHITE * 1.1, alpha * 0.9, 1.0, feather=1.5)
                return [heart]
            return _rose(bloom, scale, across, up)
        st = _state(runtime, f"ribbon:{body.prefix}{side}")
        if age <= 1 or "dir" not in st:
            d = up * 0.35 + outward * 0.95
            st["dir"] = d / np.linalg.norm(d)
        t = age / 30.0
        # La cinta barre: su dirección gira despacio (como el brazo de la gimnasta).
        turn = 0.9 * np.sin(t * 2.2)
        c, s_ = np.cos(turn), np.sin(turn)
        d = np.array([st["dir"][0] * c - st["dir"][1] * s_, st["dir"][0] * s_ + st["dir"][1] * c])
        n = np.array([-d[1], d[0]])
        length = 1.3 * scale * min(age / 8.0, 1.0)
        s = np.linspace(0.0, 1.0, 90)
        phase = s * TAU * 3.2 - t * TAU * 1.6
        loops = (np.cos(phase)[:, None] * d + np.sin(phase)[:, None] * n * 0.55) * (0.32 * scale * (0.3 + 0.7 * s))[:, None]
        wave = np.sin(s * TAU * 1.1 - t * TAU * 1.2)[:, None] * n * 0.3 * scale * s[:, None]
        curve = hand + d * (s * length)[:, None] + wave + loops
        # Perspectiva: la cinta gira sobre sí misma; de canto se ve fina, de frente ancha.
        twist = np.abs(np.cos(s * TAU * 1.5 - t * TAU * 2.0))
        widths = 0.08 * scale * (0.2 + 0.8 * twist) * taper(len(s), 0.5)
        fill_band(layer, curve, widths, alpha * 0.9)
        return [curve]
    if shape == "energy_sparks":
        anchors = [p for p in (body.get("left_shoulder"), body.get("right_shoulder"), body.get("left_elbow"), body.get("right_elbow"), body.get("left_wrist"), body.get("right_wrist")) if p is not None]
        if hips is not None:
            anchors += [center + (hips - center) * f for f in (0.25, 0.5)]
        if not anchors:
            return []
        out = []
        for _ in range(7):
            a = anchors[int(rng.integers(len(anchors)))] + rng.normal(0, 0.12 * scale, 2)
            angle = rng.uniform(0, TAU)
            out += branched(a, np.array([np.cos(angle), np.sin(angle)]), 0.28 * scale, rng)
        return out
    if shape == "chest_heart" and hips is not None:
        from vfxglow.engine.duo_doodles import _heart

        chest = center + (hips - center) * 0.28
        heart = _heart(chest, 0.16 * scale)
        fill_polygon(layer, heart, WHITE * 1.2, alpha, 1.0, feather=1.5)
        splat(layer, float(chest[0]), float(chest[1]), 0.35 * scale, color * 1.1, alpha * 0.4, runtime.kernels)
        return [heart]
    if shape == "energy_wave":
        joints = ("left_wrist", "right_wrist", "left_elbow", "right_elbow", "left_knee", "right_knee", "left_ankle", "right_ankle", "nose", "left_shoulder", "right_shoulder")
        st = _state(runtime, f"wave:{body.prefix}")
        speeds = {j: float(np.linalg.norm(_velocity(body, j))) for j in joints if body.get(j) is not None}
        if not speeds:
            return []
        best = max(speeds, key=speeds.get)
        target = body.get(best)
        # La nube se desliza hacia la parte que más se mueve (no salta): va y viene como una onda.
        st["pos"] = target if "pos" not in st or age <= 1 else st["pos"] + (target - st["pos"]) * 0.35
        out = []
        for _ in range(5):
            a = st["pos"] + rng.normal(0, 0.18 * scale, 2)
            angle = rng.uniform(0, TAU)
            out += branched(a, np.array([np.cos(angle), np.sin(angle)]), 0.32 * scale, rng)
        # Si la mano toca la de la pareja, un rayo la cruza.
        for name, point in body.points.items():
            if not name.endswith("_wrist") or (body.prefix and name.startswith(body.prefix)) or ":" not in name:
                continue
            for s in ("left", "right"):
                own = body.get(f"{s}_wrist")
                if own is not None and np.linalg.norm(own - point) < 0.6 * scale:
                    out.append(_zigzag(np.array([own, point]), 0.08 * scale, rng, 0.05 * scale))
        return out
    if shape == "dj_disc":
        out = []
        sparks = []
        for k, s in enumerate(("left", "right")):
            wrist, elbow = body.get(f"{s}_wrist"), body.get(f"{s}_elbow")
            if wrist is None:
                continue
            along = (wrist - elbow) / max(float(np.linalg.norm(wrist - elbow)), 1e-6) if elbow is not None else down
            disc = wrist + along * 0.1 * scale + down * 0.06 * scale
            rx, ry = 0.3 * scale, 0.08 * scale
            ring = lambda r, a0=0.0, a1=TAU, m=40: disc + np.cos(np.linspace(a0, a1, m))[:, None] * across * rx * r + np.sin(np.linspace(a0, a1, m))[:, None] * down * ry * r  # noqa: E731
            spin = frame_index * 0.45 * (1 if k else -1)
            out += [ring(1.0), ring(0.45)]
            # Marca que gira (se ve que el disco da vueltas).
            out.append(np.array([disc + (np.cos(spin) * across * rx + np.sin(spin) * down * ry) * 0.5, disc + (np.cos(spin) * across * rx + np.sin(spin) * down * ry) * 0.95]))
            # Chispas de esmeril: salen tangentes al borde, de colores, y caen.
            for j in range(10):
                life = 9.0
                birth = (j * 3 + k * 5) % int(life)
                u = ((frame_index - birth) % life) / life
                theta = spin + (np.pi / 2 if k else -np.pi / 2) + j * 0.15
                rim = disc + np.cos(theta) * across * rx + np.sin(theta) * down * ry
                tangent = -np.sin(theta) * across * rx + np.cos(theta) * down * ry
                tangent = tangent / max(float(np.linalg.norm(tangent)), 1e-6) * (1 if k else -1)
                pos = rim + tangent * u * 0.6 * scale + down * (u**2) * 0.35 * scale
                hue = ((frame_index * 0.03) + j * 0.1) % 1.0
                rgb = np.array(colorsys.hsv_to_rgb(hue, 0.8, 1.0), np.float32)
                tail = pos - tangent * 0.08 * scale
                sparks.append((np.array([tail, pos]), rgb, 1.0 - u))
        for curve, rgb, fade in sparks:
            from vfxglow.engine.raster import stroke_batch
            from vfxglow.engine.swoosh import neon_layers

            stroke_batch(layer, neon_layers(curve, rgb, max(1.2, 0.012 * scale), alpha * fade), 1.6)
        return out
    if shape in ("orbit_arcs", "hand_orbit"):
        if shape == "hand_orbit":
            picked = _wrist(body, event, center)
            if picked is None:
                return []
            pivot = picked[1]
            radius, tilt, count, speed = 0.32 * scale, 0.55, 3, 0.4
        else:
            if hips is None:
                return []
            pivot = center + (hips - center) * 0.55
            radius, tilt, count, speed = 1.2 * scale, 0.18, 2, 0.16
        mask = body_mask(body, layer.shape[:2], scale)
        out = []
        for k in range(count):
            if shape == "orbit_arcs":
                # Capa: un círculo alto en un plano vertical que gira alrededor del eje del cuerpo
                # (alpha). De lado se ve como una media luna alta; de frente, ancha.
                alpha_k = age * speed + k * np.pi
                # En el costado (phi = 0 o pi), de la cabeza a la cadera, y se desliza un poco.
                phi = np.linspace(-1.0, 1.15, 40) + k * np.pi + np.sin(age * 0.12 + k) * 0.35
                # De canto la media luna sería una raya: se deja un mínimo de anchura.
                ca = np.cos(alpha_k)
                x = np.cos(phi) * (np.sign(ca) or 1.0) * max(abs(ca), 0.45)
                z = np.cos(phi) * np.sin(alpha_k)
                y = np.sin(phi) * 1.3
                curve = pivot + x[:, None] * across * radius + y[:, None] * up * radius * 0.9
            else:
                a0 = age * speed + k * TAU / count
                phi = np.linspace(a0, a0 + 1.9, 40)
                x = np.cos(phi)
                z = np.sin(phi)
                y = np.sin(phi * 0.5 + k) * tilt
                curve = pivot + x[:, None] * across * radius + (y[:, None] + z[:, None] * 0.25) * up * radius
            widths = 0.16 * scale * (radius / scale if shape == "hand_orbit" else 1.0) * taper(len(phi), 0.8) * (0.55 + 0.45 * (z > 0))
            for a, b in visible(curve, z, mask):
                fill_band(layer, curve[a:b], widths[a:b], alpha * 0.95)
                out.append(curve[a:b])
        return out
    return []


def _rose(bloom: np.ndarray, scale: float, across: np.ndarray, up: np.ndarray) -> list[np.ndarray]:
    t = np.linspace(0, TAU * 2.0, 36)
    r = (0.03 + 0.05 * t / (TAU * 2.0)) * scale
    spiral = bloom + np.cos(t)[:, None] * across * r[:, None] + np.sin(t)[:, None] * up * r[:, None] * 0.8
    cup_t = np.linspace(np.pi * 1.0, np.pi * 2.0, 16)
    cup = bloom + np.cos(cup_t)[:, None] * across * 0.12 * scale + np.sin(cup_t)[:, None] * up * 0.12 * scale
    petals = [bloom + across * s * 0.1 * scale + up * 0.05 * scale + np.cos(np.linspace(0, np.pi, 12))[:, None] * across * 0.05 * scale + np.sin(np.linspace(0, np.pi, 12))[:, None] * up * 0.09 * scale for s in (-1, 1)]
    stem = np.array([bloom - up * 0.12 * scale, bloom - up * 0.55 * scale])
    leaf = np.array([bloom - up * 0.32 * scale, bloom - up * 0.25 * scale + across * 0.1 * scale, bloom - up * 0.36 * scale + across * 0.02 * scale])
    return [spiral, cup, *petals, stem, leaf]
