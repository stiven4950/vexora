"""Chaqueta metalera (adorno `metal_jacket`): una chaqueta de motociclista con púas, dibujada en
neón sobre el cuerpo. Plano tomado de la referencia que dio el usuario (chaqueta de cuero negra
con púas):

- cuello alto con púas, solapas anchas con muesca y tachas en el borde;
- cierre en diagonal (asimétrico) con sus dientes, y bolsillos con cierre en diagonal;
- charreteras en los hombros y una corona de púas que baja por hombros y mangas;
- mangas hasta la muñeca, con puño y cierre;
- cinturón en el bajo con hebilla y púas a los costados de la cadera.

De espaldas no hay solapas, cierre ni bolsillos (P6): cuello, hombros, mangas y bajo.
Las púas van rellenas de blanco con el halo del color de la persona; el resto son líneas.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.raster import fill_polygon

WHITE = np.array([1.0, 1.0, 1.0], np.float32)


def _offset(path: np.ndarray, distance: float) -> np.ndarray:
    """La polilínea desplazada `distance` px a su izquierda (normal de cada tramo)."""
    tangent = np.gradient(path, axis=0)
    normal = np.stack([-tangent[:, 1], tangent[:, 0]], axis=1)
    normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-6)
    return path + normal * distance


def _along(path: np.ndarray, u: float) -> tuple[np.ndarray, np.ndarray]:
    """Punto y dirección a la fracción `u` del largo de la polilínea."""
    seg = np.linalg.norm(np.diff(path, axis=0), axis=1)
    total = max(float(seg.sum()), 1e-6)
    target = u * total
    k = int(np.searchsorted(np.cumsum(seg), target))
    k = min(k, len(seg) - 1)
    start = float(np.cumsum(seg)[k] - seg[k])
    t = (target - start) / max(float(seg[k]), 1e-6)
    direction = (path[k + 1] - path[k]) / max(float(seg[k]), 1e-6)
    return path[k] + (path[k + 1] - path[k]) * t, direction


def _spike(base: np.ndarray, out: np.ndarray, height: float, width: float) -> np.ndarray:
    out = out / max(float(np.linalg.norm(out)), 1e-6)
    side = np.array([-out[1], out[0]])
    return np.array([base - side * width / 2, base + out * height, base + side * width / 2])


def _circle(center: np.ndarray, radius: float, n: int = 10) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n)
    return center + np.stack([np.cos(t), np.sin(t)], axis=1) * radius


def metal_jacket(body, frame, scale: float, layer: np.ndarray, alpha: float, back: bool) -> list[np.ndarray]:
    center, across, down = frame
    up = -down
    hips = body.mid("left_hip", "right_hip")
    if hips is None:
        return []
    length = float(np.linalg.norm(hips - center))
    lines: list[np.ndarray] = []
    spikes: list[np.ndarray] = []
    studs: list[np.ndarray] = []

    def spike(base, out, size=1.0):
        spikes.append(_spike(base, out, 0.12 * scale * size, 0.055 * scale * size))

    # Hombros en la imagen: el de la izquierda y el de la derecha.
    shoulders = {}
    for name in ("left", "right"):
        point = body.get(f"{name}_shoulder")
        if point is not None:
            side = 1.0 if float((point - center) @ across) >= 0 else -1.0
            shoulders[side] = name
    hem_y = hips + down * 0.14 * length

    for side in (-1.0, 1.0):
        name = shoulders.get(side)
        shoulder = body.get(f"{name}_shoulder") if name else None
        if shoulder is None:
            shoulder = center + across * side * 0.5 * scale
        shoulder = shoulder + across * side * 0.04 * scale + up * 0.03 * scale

        # ----- costado y bajo -----
        armpit = center + across * side * 0.5 * scale + down * 0.3 * length
        hem = hem_y + across * side * 0.5 * scale
        lines.append(np.array([shoulder, armpit, (armpit + hem) / 2 + across * side * 0.02 * scale, hem]))
        # Púas en la cadera, hacia afuera (tres filas cortas como en el plano).
        for k in range(4):
            base = armpit + (hem - armpit) * (0.62 + 0.11 * k)
            spike(base, across * side + down * 0.15, 0.8)

        # ----- charretera y corona de púas en el hombro -----
        neck = center + across * side * 0.18 * scale + up * 0.06 * scale
        lines.append(np.array([neck, shoulder]))
        strap_a = neck + (shoulder - neck) * 0.35
        lines.append(np.array([strap_a + down * 0.04 * scale, shoulder + down * 0.04 * scale]))
        studs.append(_circle(strap_a + down * 0.02 * scale, 0.02 * scale))
        # Corona de púas largas y apretadas, que se abren hacia afuera al llegar al hombro.
        for k in range(8):
            base = neck + (shoulder - neck) * (0.12 + 0.12 * k)
            spike(base, up + across * side * (0.2 + 0.22 * k), 1.6 - 0.35 * (k % 2))

        # ----- manga hasta la muñeca, con puño y púas por fuera -----
        elbow = body.get(f"{name}_elbow") if name else None
        wrist = body.get(f"{name}_wrist") if name else None
        if elbow is not None:
            arm = np.array([shoulder, elbow] + ([wrist] if wrist is not None else []), dtype=np.float64)
            half = 0.11 * scale
            outer, inner = _offset(arm, half), _offset(arm, -half)
            # Que el borde "de afuera" sea el más lejano del torso.
            if float(np.linalg.norm(outer[1] - center)) < float(np.linalg.norm(inner[1] - center)):
                outer, inner = inner, outer
            lines += [outer, inner]
            for k in range(6):
                base, direction = _along(outer, 0.06 + 0.1 * k)
                away = base - _along(inner, 0.08 + 0.12 * k)[0]
                spike(base, away, 0.85)
            if wrist is not None:
                end_dir = (arm[-1] - arm[-2]) / max(float(np.linalg.norm(arm[-1] - arm[-2])), 1e-6)
                normal = np.array([-end_dir[1], end_dir[0]])
                for back_k in (0.0, 0.07):
                    cuff = wrist - end_dir * back_k * scale
                    lines.append(np.array([cuff - normal * half, cuff + normal * half]))
                # Cierre del puño.
                zip_a = wrist - end_dir * 0.07 * scale + normal * half * 0.4
                lines.append(np.array([zip_a, zip_a - end_dir * 0.18 * scale]))

        if back:
            continue
        # ----- solapa ancha con muesca y tachas -----
        notch_out = center + across * side * 0.36 * scale + down * 0.1 * length
        notch_in = center + across * side * 0.27 * scale + down * 0.15 * length
        tip = center + across * side * 0.42 * scale + down * 0.24 * length
        foot = center + across * side * 0.1 * scale + down * 0.55 * length
        lapel = np.array([neck, notch_out, notch_in, tip, foot])
        lines.append(lapel)
        for k in range(5):
            stud, _ = _along(lapel[2:], 0.1 + 0.2 * k)
            studs.append(_circle(stud + across * -side * 0.025 * scale, 0.018 * scale))
        # ----- bolsillo con cierre en diagonal -----
        pocket_a = center + across * side * 0.22 * scale + down * 0.7 * length
        pocket_b = pocket_a + across * side * 0.18 * scale + up * 0.12 * scale
        lines.append(np.array([pocket_a, pocket_b]))
        studs.append(_circle(pocket_a, 0.016 * scale))

    # ----- cuello alto con púas -----
    collar = np.array([center + across * x * scale + up * (0.1 + 0.05 * (1 - x * x / 0.04)) * scale for x in np.linspace(-0.2, 0.2, 9)])
    lines.append(collar)
    for k, x in enumerate(np.linspace(-0.16, 0.16, 5)):
        spike(center + across * x * scale + up * 0.14 * scale, up + across * x * 2.5, 1.1)

    # ----- bajo con cinturón y hebilla -----
    left_hem, right_hem = hem_y - across * 0.5 * scale, hem_y + across * 0.5 * scale
    lines += [np.array([left_hem, right_hem]), np.array([left_hem + up * 0.07 * scale, right_hem + up * 0.07 * scale])]
    if not back:
        buckle = hem_y + across * 0.3 * scale + up * 0.035 * scale
        lines.append(np.array([buckle - across * 0.05 * scale + up * 0.05 * scale, buckle + across * 0.05 * scale + up * 0.05 * scale,
                               buckle + across * 0.05 * scale - up * 0.05 * scale, buckle - across * 0.05 * scale - up * 0.05 * scale,
                               buckle - across * 0.05 * scale + up * 0.05 * scale]))
        # Cierre asimétrico: del pecho, de un lado, en diagonal hasta el bajo cerca del centro.
        zip_top = center + across * 0.22 * scale + down * 0.18 * length
        zip_bottom = hem_y - across * 0.06 * scale + up * 0.07 * scale
        lines.append(np.array([zip_top, zip_bottom]))
        direction = (zip_bottom - zip_top) / max(float(np.linalg.norm(zip_bottom - zip_top)), 1e-6)
        normal = np.array([-direction[1], direction[0]])
        for u in np.linspace(0.05, 0.95, 12):
            tooth = zip_top + (zip_bottom - zip_top) * u
            lines.append(np.array([tooth - normal * 0.018 * scale, tooth + normal * 0.018 * scale]))
        studs.append(_circle(zip_top + direction * 0.04 * scale, 0.02 * scale))  # tirador
    else:
        # Espalda: costura central.
        lines.append(np.array([center + down * 0.1 * length, hem_y + up * 0.07 * scale]))

    for poly in spikes:
        fill_polygon(layer, poly, WHITE * 1.2, alpha * 0.95, 1.0, feather=1.0)
    for stud in studs:
        fill_polygon(layer, stud, WHITE * 1.1, alpha * 0.9, 1.0, feather=1.0)
    return lines + [np.vstack([s, s[:1]]) for s in spikes]
