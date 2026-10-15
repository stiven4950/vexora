"""Disfraces de cara y cabeza, y prendas del cuello (adornos `type: adornment`, `style.shapes`).

Se anclan a la cara (ojos, nariz, boca y orejas de la pose), giran con la inclinación de la cabeza
y escalan con la distancia entre ojos (o con los hombros si la cara está lejos):

- Antifaces: `hero_mask` (de superhéroe, con alas hacia las sienes), `masquerade` (veneciano con
  plumas), `bat_mask` (con orejas puntiagudas sobre la cabeza).
- Animales: `cat_mask` (antifaz, orejas, nariz y bigotes), `fox_mask` (antifaz en punta, orejas
  altas y marcas en las mejillas), `bunny` (orejas largas, nariz y bigotes).
- Ocurrencias: `mustache` (bigote de manubrio), `horns` (cuernos de diablo), `antennae` (antenas
  que se balancean), `ninja_band` (bandana con nudo y puntas al viento), `pirate_patch` (parche
  con su correa).
- Cuello: `tie` (corbata con rayas) y `bowtie` (moño).

De espaldas no se dibuja nada que vaya sobre la cara (P6); sí orejas, cuernos, antenas y bandana.
Los antifaces y el parche van rellenos con el color de la persona (con los ojos libres); el
resto, líneas de neón.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.raster import fill_polygon

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
FACE = ("hero_mask", "masquerade", "bat_mask", "cat_mask", "fox_mask", "mustache", "pirate_patch")
HEAD = ("bunny", "horns", "antennae", "ninja_band")
NECK = ("tie", "bowtie")
COSTUMES = FACE + HEAD + NECK


class Face:
    """Ejes de la cara: x de un ojo al otro (en la imagen), y hacia la boca; d = distancia entre ojos."""

    def __init__(self, body, frame, scale: float) -> None:
        center, across, down = frame
        eyes = [body.get("left_eye"), body.get("right_eye")]
        nose = body.get("nose")
        if all(e is not None for e in eyes):
            left, right = sorted(eyes, key=lambda p: float(p[0]))
            span = right - left
            self.x = span / max(float(np.linalg.norm(span)), 1e-6)
            self.y = np.array([-self.x[1], self.x[0]])
            if float(self.y @ down) < 0:
                self.y = -self.y
            self.mid = (left + right) / 2
        elif nose is not None:
            self.x, self.y = across, down
            self.mid = nose - down * 0.1 * scale
        else:
            raise ValueError("sin cara")
        # Planos lejanos: la pose junta los ojos; los hombros dan la escala (como eyewear.py).
        self.d = max(float(np.linalg.norm(eyes[1] - eyes[0])) if all(e is not None for e in eyes) else 0.0, 0.2 * scale)
        self.nose = nose if nose is not None else self.mid + self.y * 0.6 * self.d
        self.eyes = (self.mid - self.x * self.d / 2, self.mid + self.x * self.d / 2)
        self.top = self.mid - self.y * 1.55 * self.d  # coronilla

    def p(self, x: float, y: float, origin=None) -> np.ndarray:
        """Punto en unidades de distancia entre ojos, desde `origin` (los ojos por defecto)."""
        base = self.mid if origin is None else origin
        return base + self.x * x * self.d + self.y * y * self.d

    def curve(self, points, origin=None, n: int = 0) -> np.ndarray:
        pts = np.array([self.p(x, y, origin) for x, y in points])
        if n:
            from vfxglow.geom import catmull_rom

            pts = catmull_rom(pts, samples_per_seg=n)
        return pts

    def ellipse(self, cx: float, cy: float, rx: float, ry: float, a0: float = 0.0, a1: float = TAU, k: int = 28, origin=None) -> np.ndarray:
        t = np.linspace(a0, a1, k)
        return np.array([self.p(cx + rx * np.cos(a), cy + ry * np.sin(a), origin) for a in t])


def _domino(f: Face, wing: float = 1.25, drop: float = 0.45, point: float = 0.0) -> tuple[np.ndarray, list[np.ndarray]]:
    """Antifaz: contorno y huecos de los ojos. `wing`: cuánto sale hacia las sienes; `point`: pico
    hacia la nariz (zorro)."""
    outline = f.curve(
        [(-wing, -0.15), (-wing * 0.85, -0.45), (-0.45, -0.42), (0.0, -0.3), (0.45, -0.42), (wing * 0.85, -0.45), (wing, -0.15),
         (wing * 0.75, drop * 0.7), (0.4, drop), (0.0, 0.2 + point), (-0.4, drop), (-wing * 0.75, drop * 0.7), (-wing, -0.15)],
        n=4,
    )
    holes = [f.ellipse(sx * 0.5, 0.02, 0.24, 0.15) for sx in (-1, 1)]
    return outline, holes


def _whiskers(f: Face) -> list[np.ndarray]:
    out = []
    for side in (-1, 1):
        for dy, tilt in ((-0.05, -0.12), (0.05, 0.0), (0.15, 0.12)):
            out.append(f.curve([(side * 0.25, 0.0 + dy), (side * 0.85, -0.05 + dy + tilt), (side * 1.3, -0.1 + dy + tilt * 1.8)], origin=f.nose, n=3))
    return out


def costume(shape: str, body, frame, scale: float, frame_index: int, layer: np.ndarray, color: np.ndarray, alpha: float, back: bool) -> list[np.ndarray]:
    if shape in NECK:
        return _neck(shape, body, frame, scale, layer, color, alpha, back)
    if back and shape in FACE:
        return []
    try:
        f = Face(body, frame, scale)
    except ValueError:
        return []
    lines: list[np.ndarray] = []
    tint = np.asarray(color, np.float32)

    def mask(outline, holes, strength=0.55):
        fill_polygon(layer, outline, tint, alpha * strength, 0.9, feather=1.5, holes=holes)
        lines.append(np.vstack([outline, outline[:1]]))
        lines.extend(holes)

    if shape == "hero_mask":
        mask(*_domino(f, wing=1.35, drop=0.42))
    elif shape == "masquerade":
        outline, holes = _domino(f, wing=1.1, drop=0.38)
        mask(outline, holes, 0.45)
        # Plumas que suben de la sien derecha, con su eje y barbas.
        for k, (lean, tall) in enumerate(((0.2, 1.9), (0.55, 1.6), (0.9, 1.3))):
            base = f.p(1.0, -0.35)
            spine = f.curve([(0, 0), (lean * 0.5, -tall * 0.5), (lean, -tall)], origin=base, n=4)
            lines.append(spine)
            for u in np.linspace(0.25, 0.9, 5):
                q = spine[int(u * (len(spine) - 1))]
                lines.append(np.array([q, q + f.x * 0.18 * f.d - f.y * 0.12 * f.d]))
        lines.append(f.curve([(-1.0, 0.1), (-1.25, 0.6), (-1.15, 1.2)], n=4))  # varilla
    elif shape == "bat_mask":
        outline, holes = _domino(f, wing=1.25, drop=0.45)
        mask(outline, holes, 0.6)
        for side in (-1, 1):
            ear = f.curve([(side * 0.55, -0.4), (side * 0.85, -2.1), (side * 1.05, -0.9)], n=0)
            fill_polygon(layer, ear, tint, alpha * 0.55, 0.9, feather=1.5)
            lines.append(np.vstack([ear, ear[:1]]))
        lines.append(f.curve([(-0.55, -0.4), (0.0, -0.15), (0.55, -0.4)]))  # ceño
    elif shape == "cat_mask":
        outline, holes = _domino(f, wing=1.15, drop=0.4)
        mask(outline, holes, 0.45)
        for side in (-1, 1):
            outer = f.curve([(side * 0.45, 0), (side * 0.85, -0.85), (side * 1.15, 0.05)], origin=f.top)
            inner = f.curve([(side * 0.58, -0.05), (side * 0.85, -0.55), (side * 1.02, -0.02)], origin=f.top)
            lines += [outer, inner]
        lines.append(f.curve([(-0.12, -0.05), (0.12, -0.05), (0.0, 0.1), (-0.12, -0.05)], origin=f.nose))
        lines += _whiskers(f)
    elif shape == "fox_mask":
        outline, holes = _domino(f, wing=1.4, drop=0.7, point=1.05)
        mask(outline, holes, 0.5)
        for side in (-1, 1):
            ear = f.curve([(side * 0.25, 0.15), (side * 0.95, -1.45), (side * 1.35, 0.25)], origin=f.top)
            fill_polygon(layer, ear, tint, alpha * 0.5, 0.9, feather=1.5)
            lines.append(np.vstack([ear, ear[:1]]))
            lines.append(f.curve([(side * 0.55, 0.05), (side * 0.95, -0.85), (side * 1.12, 0.12)], origin=f.top))
            # Pelaje de las mejillas en zigzag.
            lines.append(f.curve([(side * 1.4, -0.1), (side * 1.25, 0.25), (side * 1.45, 0.4), (side * 1.15, 0.65), (side * 0.9, 0.55)]))
        fill_polygon(layer, f.ellipse(0.0, 0.05, 0.13, 0.09, origin=f.nose), WHITE, alpha, 1.0, feather=1.0)
    elif shape == "bunny":
        for side, lean in ((-1, -0.15), (1, 0.25)):
            ear = f.ellipse(side * 0.45 + lean, -1.15, 0.28, 1.15, origin=f.top, k=32)
            inner = f.ellipse(side * 0.45 + lean, -1.05, 0.13, 0.8, origin=f.top, k=24)
            lines += [ear, inner]
        if not back:
            lines.append(f.ellipse(0.0, 0.0, 0.11, 0.08, origin=f.nose))
            lines += _whiskers(f)
            lines.append(f.curve([(-0.12, 0.45), (-0.12, 0.65), (0.12, 0.65), (0.12, 0.45)], origin=f.nose))  # dientes
    elif shape == "mustache":
        base = f.p(0.0, 0.35, f.nose)
        for side in (-1, 1):
            lines.append(f.curve([(0.0, 0.0), (side * 0.35, -0.08), (side * 0.7, 0.1), (side * 0.85, -0.15), (side * 0.72, -0.3)], origin=base, n=4))
            lines.append(f.curve([(0.0, 0.08), (side * 0.38, 0.12), (side * 0.66, 0.2)], origin=base, n=3))
    elif shape == "horns":
        for side in (-1, 1):
            horn = f.curve([(side * 0.55, 0.3), (side * 1.05, -0.35), (side * 0.95, -1.15), (side * 0.6, -1.6),
                            (side * 0.72, -0.95), (side * 0.55, -0.25), (side * 0.25, 0.35)], origin=f.top, n=3)
            fill_polygon(layer, horn, tint, alpha * 0.5, 0.9, feather=1.5)
            lines.append(np.vstack([horn, horn[:1]]))
    elif shape == "antennae":
        sway = 0.25 * np.sin(frame_index * 0.25)
        for side in (-1, 1):
            tip = (side * 0.85 + sway, -1.6)
            lines.append(f.curve([(side * 0.3, 0.15), (side * 0.55 + sway * 0.4, -0.8), tip], origin=f.top, n=4))
            ball = f.p(*tip, origin=f.top)
            fill_polygon(layer, f.ellipse(tip[0], tip[1], 0.16, 0.16, origin=f.top), WHITE, alpha, 1.0, feather=1.5)
            lines.append(f.ellipse(tip[0], tip[1], 0.16, 0.16, origin=f.top))
            del ball
    elif shape == "ninja_band":
        band_y = -0.75
        for dy in (-0.14, 0.14):
            lines.append(f.ellipse(0.0, band_y + dy, 1.3, 0.22, np.pi * 0.05, np.pi * 0.95, 20))
        knot = f.p(1.25, band_y)
        flutter = np.sin(frame_index * 0.35)
        for k, (dx, dy) in enumerate(((1.1, 0.25), (0.9, 0.75))):
            tail = f.curve([(0, 0), (dx * 0.5, dy * 0.4 + 0.12 * flutter), (dx, dy + 0.2 * flutter * (k + 1))], origin=knot, n=4)
            lines.append(tail)
        lines.append(f.ellipse(0.0, 0.0, 0.14, 0.14, origin=knot))
    elif shape == "pirate_patch":
        eye = f.eyes[1]
        patch = f.ellipse(0.0, 0.05, 0.36, 0.3, origin=eye)
        fill_polygon(layer, patch, tint, alpha * 0.85, 0.9, feather=1.5)
        lines.append(patch)
        lines.append(np.array([f.p(-0.3, -0.2, eye), f.p(-1.6, -1.1, eye)]))
        lines.append(np.array([f.p(0.3, -0.15, eye), f.p(0.9, 0.0, eye)]))
    return lines


def _neck(shape: str, body, frame, scale: float, layer, color, alpha: float, back: bool) -> list[np.ndarray]:
    if back:
        return []
    center, across, down = frame
    hips = body.mid("left_hip", "right_hip")
    length = float(np.linalg.norm(hips - center)) if hips is not None else 1.4 * scale
    knot = center + down * 0.06 * length
    tint = np.asarray(color, np.float32)
    lines: list[np.ndarray] = []

    def p(x: float, y: float) -> np.ndarray:
        return knot + across * x * scale + down * y * length

    if shape == "tie":
        knot_shape = np.array([p(-0.05, -0.02), p(0.05, -0.02), p(0.035, 0.07), p(-0.035, 0.07)])
        blade = np.array([p(-0.035, 0.07), p(0.035, 0.07), p(0.09, 0.5), p(0.0, 0.58), p(-0.09, 0.5)])
        fill_polygon(layer, blade, tint, alpha * 0.45, 0.9, feather=1.5)
        fill_polygon(layer, knot_shape, tint, alpha * 0.6, 0.9, feather=1.5)
        lines += [np.vstack([knot_shape, knot_shape[:1]]), np.vstack([blade, blade[:1]])]
        for y in np.linspace(0.14, 0.44, 4):  # rayas diagonales
            half = 0.035 + (0.09 - 0.035) * (y - 0.07) / 0.43
            lines.append(np.array([knot + across * -half * scale + down * y * length, knot + across * half * scale + down * (y - 0.06) * length]))
        lines.append(np.array([p(-0.16, -0.06), p(-0.05, -0.02)]))  # cuello de la camisa
        lines.append(np.array([p(0.16, -0.06), p(0.05, -0.02)]))
    elif shape == "bowtie":
        for side in (-1, 1):
            wing = np.array([p(side * 0.04, 0.0), p(side * 0.2, -0.06), p(side * 0.22, 0.07), p(side * 0.04, 0.03)])
            fill_polygon(layer, wing, tint, alpha * 0.5, 0.9, feather=1.5)
            lines.append(np.vstack([wing, wing[:1]]))
        center_knot = np.array([p(-0.04, -0.01), p(0.04, -0.01), p(0.04, 0.04), p(-0.04, 0.04)])
        fill_polygon(layer, center_knot, WHITE, alpha, 1.0, feather=1.0)
        lines.append(np.vstack([center_knot, center_knot[:1]]))
    return lines
