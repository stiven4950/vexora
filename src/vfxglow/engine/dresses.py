"""Vestidos dibujados en neón sobre el cuerpo (adornos `type: adornment`, `style.shapes`).

La contraparte de la chaqueta metalera (engine/jacket.py) en el vestuario que elige el usuario
para cada persona (director/choreography.py: `wardrobe`):

- `gown`: vestido largo de gala: escote de corazón, corpiño ceñido, falda que se abre hasta los
  tobillos con pliegues y destellos.
- `cocktail`: vestido corto: tirantes finos, cinturón con moño y falda con vuelo hasta la rodilla,
  de borde ondulado.
- `ruffle`: vestido de volantes: escote de hombros descubiertos y tres capas de volantes.

El ruedo sigue a las piernas: se ensancha cuando se abren y se mueve con ellas. El cuerpo va teñido
suave con el color de la persona; costuras, volantes y destellos, en neón.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.raster import fill_polygon

TAU = 2.0 * np.pi
DRESSES = ("gown", "cocktail", "ruffle")


def _wave(a: np.ndarray, b: np.ndarray, bumps: int, depth: float, down: np.ndarray, n: int = 48) -> np.ndarray:
    """Borde ondulado de a a b, con `bumps` ondas hacia abajo de `depth` px."""
    t = np.linspace(0.0, 1.0, n)
    return a + np.outer(t, b - a) + np.outer(np.abs(np.sin(t * np.pi * bumps)) * depth, down)


def _bezier(points: list[np.ndarray], n: int = 24) -> np.ndarray:
    """Curva de Bézier por los puntos de control (De Casteljau)."""
    ctrl = np.array(points, dtype=np.float64)
    out = []
    for u in np.linspace(0.0, 1.0, n):
        level = ctrl.copy()
        while len(level) > 1:
            level = (1 - u) * level[:-1] + u * level[1:]
        out.append(level[0])
    return np.array(out)


def dress(shape: str, body, frame, scale: float, frame_index: int, layer: np.ndarray, color, alpha: float) -> list[np.ndarray]:
    from vfxglow.engine.burst import sparkle

    center, across, down = frame
    hips = body.mid("left_hip", "right_hip")
    if hips is None:
        return []
    length = float(np.linalg.norm(hips - center))
    tint = np.asarray(color, np.float32)
    waist = center + (hips - center) * 0.62
    lines: list[np.ndarray] = []

    # Dónde termina la falda: tobillos (gala), rodillas (cóctel) o debajo de ellas (volantes).
    def level(names: tuple[str, str], fallback: float) -> np.ndarray:
        pts = [body.get(n) for n in names]
        pts = [p for p in pts if p is not None]
        return np.mean(pts, axis=0) if pts else hips + down * fallback * length

    def spread(names: tuple[str, str], minimum: float) -> float:
        pts = [body.get(n) for n in names]
        if any(p is None for p in pts):
            return minimum * scale
        return max(abs(float((pts[0] - pts[1]) @ across)) / 2 + 0.25 * scale, minimum * scale)

    if shape == "gown":
        hem_c = level(("left_ankle", "right_ankle"), 1.6) + down * 0.06 * length
        half = spread(("left_ankle", "right_ankle"), 0.75)
    elif shape == "cocktail":
        hem_c = level(("left_knee", "right_knee"), 0.75)
        half = spread(("left_knee", "right_knee"), 0.6)
    else:
        knees, ankles = level(("left_knee", "right_knee"), 0.75), level(("left_ankle", "right_ankle"), 1.6)
        hem_c = knees + (ankles - knees) * 0.35
        half = spread(("left_knee", "right_knee"), 0.68)
    hem_l, hem_r = hem_c - across * half, hem_c + across * half
    bodice_w = 0.3 * scale

    # ----- corpiño y escote -----
    sides = []
    for s in (-1.0, 1.0):
        top = center + across * s * 0.3 * scale + down * 0.08 * length
        sides.append((top, waist + across * s * bodice_w))
    if shape == "gown":
        # Escote de corazón: dos lóbulos.
        neckline = np.vstack([
            _bezier([sides[0][0], center - across * 0.18 * scale + down * 0.02 * length, center + down * 0.2 * length], 12),
            _bezier([center + down * 0.2 * length, center + across * 0.18 * scale + down * 0.02 * length, sides[1][0]], 12),
        ])
    elif shape == "cocktail":
        neckline = _bezier([sides[0][0], center + down * 0.24 * length, sides[1][0]], 16)
        for s in (-1.0, 1.0):  # tirantes finos
            shoulder = center + across * s * 0.36 * scale - down * 0.02 * length
            lines.append(np.array([shoulder, center + across * s * 0.26 * scale + down * 0.1 * length]))
    else:
        # Hombros descubiertos: escote recto de lado a lado con un volantito.
        a, b = center - across * 0.55 * scale + down * 0.1 * length, center + across * 0.55 * scale + down * 0.1 * length
        neckline = _wave(a, b, 7, 0.03 * scale, down, 40)
        sides = [(a, waist - across * bodice_w), (b, waist + across * bodice_w)]
    bodice = np.vstack([neckline, [sides[1][1], sides[0][1]]])
    fill_polygon(layer, bodice, tint, alpha * 0.4, 0.9, feather=1.5)
    lines += [neckline, np.array([sides[0][0], sides[0][1]]), np.array([sides[1][0], sides[1][1]])]

    # ----- cintura -----
    waist_line = np.array([sides[0][1], sides[1][1]])
    lines.append(waist_line)
    if shape == "cocktail":  # cinturón con moño
        lines.append(waist_line + down * 0.06 * length)
        bow = waist + across * 0.12 * scale + down * 0.03 * length
        for s in (-1.0, 1.0):
            loop = np.array([bow, bow + across * s * 0.12 * scale - down * 0.05 * length, bow + across * s * 0.12 * scale + down * 0.07 * length, bow])
            lines.append(loop)

    # ----- falda -----
    if shape == "cocktail":
        hem = _wave(hem_l, hem_r, 6, 0.05 * scale, down)
    elif shape == "gown":
        hem = _wave(hem_l, hem_r, 4, 0.04 * scale, down)
    else:
        hem = _wave(hem_l, hem_r, 9, 0.05 * scale, down)
    left_edge = _bezier([sides[0][1], sides[0][1] - across * 0.05 * scale + (hem_l - sides[0][1]) * 0.5, hem_l], 16)
    right_edge = _bezier([hem_r, sides[1][1] + across * 0.05 * scale + (hem_r - sides[1][1]) * 0.5, sides[1][1]], 16)
    skirt = np.vstack([left_edge, hem, right_edge])
    fill_polygon(layer, skirt, tint, alpha * 0.32, 0.9, feather=2.0)
    lines += [left_edge, right_edge, hem]
    if shape == "gown":
        for u in (-0.55, -0.15, 0.25, 0.6):  # pliegues
            lines.append(_bezier([waist + across * u * bodice_w, hem_c + across * u * half * 0.9 - down * 0.02 * length], 12))
    if shape == "ruffle":
        for k, u in enumerate((0.33, 0.66)):  # capas de volantes
            left = sides[0][1] + (hem_l - sides[0][1]) * u
            right = sides[1][1] + (hem_r - sides[1][1]) * u
            lines.append(_wave(left, right, 7 + 2 * k, 0.045 * scale, down))

    # ----- destellos -----
    rng = np.random.default_rng(7 + frame_index // 4)
    count = {"gown": 6, "cocktail": 3, "ruffle": 3}[shape]
    for _ in range(count):
        u, v = rng.uniform(0.1, 0.9), rng.uniform(-0.7, 0.7)
        point = waist + (hem_c - waist) * u + across * v * (bodice_w + (half - bodice_w) * u)
        lines.append(sparkle(point, 0.05 * scale * rng.uniform(0.6, 1.0)))
    return lines
