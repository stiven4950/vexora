"""Zapatos dibujados en neón sobre los pies (adornos `type: adornment`, `style.shapes`).

Cada zapato se dibuja de perfil en el marco del pie: del talón a la punta (`heel` → `foot_index`)
y hacia arriba, hacia el tobillo. Si el pie apunta a la cámara (escorzo: talón y punta casi en el
mismo punto), se dibuja de frente. Estilos:

- `sneaker`: tenis con suela, puntera, franja lateral y agujetas cruzadas.
- `hightop`: tenis de bota con almohadilla en el tobillo y parche redondo con estrella.
- `combat_boot`: bota alta de suela gruesa con labrado y agujetas con ganchos.
- `cowboy_boot`: bota vaquera de punta fina, tacón, caña con muesca, costuras y espuela.
- `roller_skate`: patín: bota alta sobre una base con cuatro ruedas y freno.
- `winged_shoe`: tenis con alas en el talón (como el mensajero de los dioses).

El cuerpo del zapato va teñido suave con el color de la persona, la suela en blanco y los
detalles en líneas de neón.
"""

from __future__ import annotations

import numpy as np

from vfxglow.engine.raster import fill_polygon

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
SHOES = ("sneaker", "hightop", "combat_boot", "cowboy_boot", "roller_skate", "winged_shoe")
# Largo del pie (talón-punta, en anchos de hombros) por debajo del cual el pie mira a la cámara.
FORESHORTENED = 0.22


class FootFrame:
    """x: del talón a la punta; y: hacia arriba (hacia el tobillo). Unidades: largo del zapato."""

    def __init__(self, heel: np.ndarray, toe: np.ndarray, ankle: np.ndarray | None, scale: float) -> None:
        span = toe - heel
        reach = float(np.linalg.norm(span))
        self.forward = span / max(reach, 1e-6)
        up = np.array([self.forward[1], -self.forward[0]])
        if ankle is not None and float((ankle - heel) @ up) < 0:
            up = -up
        elif ankle is None and up[1] > 0:
            up = -up
        self.up = up
        self.length = float(np.clip(reach * 1.25, 0.35 * scale, 0.9 * scale))
        # El talón de la pose queda algo dentro del zapato: el origen es la suela bajo el talón.
        self.origin = heel - self.forward * 0.08 * self.length - self.up * 0.06 * self.length

    def p(self, x: float, y: float) -> np.ndarray:
        return self.origin + self.forward * x * self.length + self.up * y * self.length

    def curve(self, pts, n: int = 0) -> np.ndarray:
        arr = np.array([self.p(x, y) for x, y in pts])
        if n:
            from vfxglow.geom import catmull_rom

            arr = catmull_rom(arr, samples_per_seg=n)
        return arr

    def circle(self, cx: float, cy: float, r: float, k: int = 20) -> np.ndarray:
        t = np.linspace(0, TAU, k)
        return np.array([self.p(cx + r * np.cos(a), cy + r * np.sin(a)) for a in t])


def _star(f: FootFrame, cx: float, cy: float, r: float) -> np.ndarray:
    angles = np.linspace(0, TAU, 11)[:-1] - np.pi / 2
    radii = np.where(np.arange(10) % 2 == 0, r, r * 0.45)
    pts = [(cx + rr * np.cos(a), cy - rr * np.sin(a)) for a, rr in zip(angles, radii)]
    return f.curve(pts + [pts[0]])


def _laces(f: FootFrame, start: tuple[float, float], end: tuple[float, float], count: int, half: float) -> list[np.ndarray]:
    """Agujetas cruzadas entre dos puntos de la lengüeta."""
    out = []
    (x0, y0), (x1, y1) = start, end
    for k in range(count):
        u0, u1 = k / count, (k + 1) / count
        a = (x0 + (x1 - x0) * u0, y0 + (y1 - y0) * u0)
        b = (x0 + (x1 - x0) * u1, y0 + (y1 - y0) * u1)
        out.append(f.curve([(a[0] - half, a[1] - half * 0.4), (b[0] + half, b[1] + half * 0.4)]))
        out.append(f.curve([(a[0] + half, a[1] + half * 0.4), (b[0] - half, b[1] - half * 0.4)]))
    return out


def shoe(shape: str, body, frame, scale: float, frame_index: int, layer: np.ndarray, color, alpha: float) -> list[np.ndarray]:
    tint = np.asarray(color, np.float32)
    lines: list[np.ndarray] = []
    for side in ("left", "right"):
        heel, toe, ankle = (body.get(f"{side}_{n}") for n in ("heel", "foot_index", "ankle"))
        if heel is None or toe is None:
            # Sin talón ni punta (la pose a veces no los da): de frente, bajo el tobillo.
            if ankle is None:
                continue
            under = ankle + np.array([0.0, 0.12 * scale])
            lines += _front(shape, under, under, ankle, scale, layer, tint, alpha)
            continue
        span = toe - heel
        reach = float(np.linalg.norm(span))
        # De frente: talón y punta casi juntos, o la punta "baja" hacia la cámara (el pie apunta a
        # la cámara y el talón queda arriba en la imagen).
        if reach < FORESHORTENED * scale or (abs(span[1]) > 0.85 * reach and reach < 0.4 * scale):
            lines += _front(shape, heel, toe, ankle, scale, layer, tint, alpha)
            continue
        f = FootFrame(heel, toe, ankle, scale)
        lines += _profile(shape, f, frame_index, layer, tint, alpha)
    return lines


def _fill(layer, poly, color, alpha) -> list[np.ndarray]:
    fill_polygon(layer, poly, color, alpha, 0.9, feather=1.5)
    return [np.vstack([poly, poly[:1]])]


def _profile(shape: str, f: FootFrame, frame_index: int, layer, tint, alpha: float) -> list[np.ndarray]:
    lines: list[np.ndarray] = []
    # Altura de la caña según el estilo.
    collar = {"sneaker": 0.42, "winged_shoe": 0.42, "hightop": 0.78, "roller_skate": 0.8, "combat_boot": 1.0, "cowboy_boot": 1.15}[shape]
    sole = 0.14 if shape == "combat_boot" else 0.09
    toe_tip = (1.12, 0.06) if shape == "cowboy_boot" else (1.04, 0.1)
    upper = [
        (-0.04, sole), (-0.08, 0.25), (-0.05, collar), (0.32, collar + (0.0 if collar < 0.6 else -0.02)),
        (0.48, collar * 0.62 if collar > 0.6 else 0.34), (0.78, 0.3), toe_tip, (1.0, sole), (-0.04, sole),
    ]
    if shape == "cowboy_boot":
        # Caña con muesca en V adelante y punta fina.
        upper = [(-0.04, sole), (-0.06, 0.6), (-0.02, collar), (0.14, collar - 0.08), (0.3, collar), (0.36, 0.55),
                 (0.7, 0.28), toe_tip, (0.95, sole), (-0.04, sole)]
    body_poly = f.curve(upper, n=4)
    lines += _fill(layer, body_poly, tint, alpha * 0.35)
    # Suela blanca (tacón alto en la bota vaquera).
    if shape == "cowboy_boot":
        heel_block = f.curve([(-0.04, sole), (0.2, sole), (0.18, -0.12), (-0.02, -0.12)])
        lines += _fill(layer, heel_block, WHITE, alpha * 0.8)
        lines += _fill(layer, f.curve([(0.2, sole), (1.08, 0.04), (1.0, 0.0), (0.2, 0.02)]), WHITE, alpha * 0.8)
    else:
        lines += _fill(layer, f.curve([(-0.06, sole), (1.02, sole), (1.06, 0.04), (0.98, 0.0), (-0.04, 0.0), (-0.08, 0.05)], n=2), WHITE, alpha * 0.8)
    if shape == "combat_boot":
        lines.append(f.curve([(x, 0.0 if k % 2 else -0.04) for k, x in enumerate(np.linspace(-0.04, 1.0, 13))]))  # labrado

    if shape in ("sneaker", "winged_shoe", "hightop", "roller_skate"):
        lines.append(f.curve([(0.72, 0.1), (0.8, 0.28), (1.0, 0.14)], n=3))  # puntera
        lines.append(f.curve([(0.18, 0.14), (0.45, 0.24), (0.7, 0.2)], n=3))  # franja
        lines += _laces(f, (0.42, collar * (0.75 if collar > 0.6 else 0.88)), (0.7, 0.31), 3 if collar < 0.6 else 5, 0.035)
    if shape in ("hightop", "roller_skate"):
        lines.append(f.circle(0.12, collar * 0.62, 0.09))  # parche del tobillo
        lines.append(_star(f, 0.12, collar * 0.62, 0.06))
        lines.append(f.curve([(-0.05, collar), (0.3, collar)]))  # almohadilla
    if shape == "combat_boot":
        lines += _laces(f, (0.36, collar - 0.08), (0.68, 0.33), 6, 0.04)
        for k in range(5):  # ganchos
            y = collar - 0.12 - k * 0.11
            lines.append(f.circle(0.36 + (0.68 - 0.36) * k / 5, y, 0.018, 8))
        lines.append(f.curve([(-0.05, collar - 0.06), (0.32, collar - 0.08)]))
    if shape == "cowboy_boot":
        lines.append(f.curve([(0.02, 0.75), (0.12, 0.9), (0.22, 0.72), (0.12, 0.6), (0.06, 0.68)], n=3))  # costura
        lines.append(f.curve([(0.5, 0.3), (0.75, 0.25), (0.98, 0.1)], n=3))
        spur = f.p(-0.12, 0.18)
        lines.append(np.array([f.p(-0.04, 0.18), spur]))
        angle = frame_index * 0.3
        for k in range(6):  # estrella de la espuela, girando
            a = angle + k * TAU / 6
            lines.append(np.array([spur, spur + (f.forward * np.cos(a) + f.up * np.sin(a)) * 0.07 * f.length]))
    if shape == "roller_skate":
        lines.append(f.curve([(-0.02, -0.02), (1.0, -0.02)]))  # base
        for x in (0.08, 0.32, 0.62, 0.86):
            wheel = f.circle(x, -0.13, 0.1)
            lines += _fill(layer, wheel, tint, alpha * 0.6)
            lines.append(f.circle(x, -0.13, 0.03, 8))
        lines.append(f.curve([(1.0, 0.0), (1.1, -0.08), (1.04, -0.14)]))  # freno
    if shape == "winged_shoe":
        flap = 0.08 * np.sin(frame_index * 0.5)
        root = (0.0, 0.32)
        for k, (dx, dy) in enumerate(((-0.35, 0.3), (-0.42, 0.14), (-0.38, -0.02))):
            tip = (root[0] + dx, root[1] + dy + flap * (1 - k * 0.3))
            lines.append(f.curve([root, ((root[0] + tip[0]) / 2, (root[1] + tip[1]) / 2 + 0.08), tip], n=3))
    return lines


def _front(shape: str, heel, toe, ankle, scale: float, layer, tint, alpha: float) -> list[np.ndarray]:
    """Zapato visto de frente, del piso a la boca del zapato: suela blanca, puntera redonda, los
    lados que suben hasta la boca (una elipse), la lengüeta que sale de ella y agujetas en cruz.
    Las botas siguen con la caña hacia arriba."""
    ground = max(float(heel[1]), float(toe[1])) + 0.04 * scale
    cx = float(toe[0]) * 0.65 + float(heel[0]) * 0.35
    ankle_y = float(ankle[1]) if ankle is not None else ground - 0.25 * scale
    w = 0.17 * scale
    mouth = min(ankle_y + 0.03 * scale, ground - 0.17 * scale)  # boca del zapato, a la altura del tobillo
    shaft = {"hightop": 0.14, "roller_skate": 0.14, "combat_boot": 0.28, "cowboy_boot": 0.34}.get(shape, 0.0) * scale
    top = mouth - shaft
    lines: list[np.ndarray] = []

    def arc(cy, rx, ry, a0, a1, k=18):
        t = np.linspace(a0, a1, k)
        return np.stack([cx + np.cos(t) * rx, cy + np.sin(t) * ry], axis=1)

    toe_y = ground - 0.05 * scale
    # Contorno: puntera (media elipse abajo), lados curvos hasta la boca o la caña.
    toe_cap = arc(toe_y - 0.02 * scale, w, 0.09 * scale, 0.0, -np.pi, 20)  # de derecha a izquierda, por arriba
    left_side = np.array([[cx - w, toe_y], [cx - w * 0.95, (toe_y + mouth) / 2], [cx - w * 0.7, mouth], [cx - w * 0.66, top]])
    right_side = np.array([[cx + w * 0.66, top], [cx + w * 0.7, mouth], [cx + w * 0.95, (toe_y + mouth) / 2], [cx + w, toe_y]])
    outline = np.vstack([left_side, right_side])
    lines += _fill(layer, outline, tint, alpha * 0.35)
    lines.append(toe_cap)
    # Boca del zapato (o borde de la caña) y la lengüeta que asoma.
    lines.append(arc(top, w * 0.66, 0.035 * scale, 0, TAU, 24))
    tongue = np.array([[cx - w * 0.3, top + 0.02 * scale], [cx - w * 0.28, top - 0.06 * scale], [cx + w * 0.28, top - 0.06 * scale], [cx + w * 0.3, top + 0.02 * scale]])
    lines.append(tongue)
    # Agujetas en cruz entre la puntera y la boca.
    lace_bottom, lace_top = toe_y - 0.1 * scale, top + 0.03 * scale
    count = max(int((lace_bottom - lace_top) / (0.045 * scale)), 2)
    for k in range(count):
        y0 = lace_bottom - k * (lace_bottom - lace_top) / count
        y1 = lace_bottom - (k + 1) * (lace_bottom - lace_top) / count
        lines.append(np.array([[cx - w * 0.3, y0], [cx + w * 0.3, y1]]))
        lines.append(np.array([[cx + w * 0.3, y0], [cx - w * 0.3, y1]]))
    # Suela blanca.
    sole = np.vstack([arc(toe_y, w * 1.06, 0.035 * scale, np.pi, 0, 16), [[cx + w, ground], [cx - w, ground]]])
    lines += _fill(layer, sole, WHITE, alpha * 0.85)
    if shape in ("hightop", "roller_skate"):
        lines.append(_circle_xy(cx - w * 0.82, mouth - 0.03 * scale, 0.035 * scale))
    if shape == "combat_boot":
        lines.append(np.array([[cx - w * 1.06, ground + 0.02 * scale], [cx + w * 1.06, ground + 0.02 * scale]]))
    if shape == "roller_skate":
        for dx in (-0.7, 0.7):
            wheel = _circle_xy(cx + dx * w, ground + 0.06 * scale, 0.055 * scale)
            lines += _fill(layer, wheel, tint, alpha * 0.6)
    if shape == "cowboy_boot":
        lines.append(np.array([[cx - w * 0.66, top], [cx, top + 0.08 * scale], [cx + w * 0.66, top]]))
    if shape == "winged_shoe":
        for sgn in (-1, 1):
            root = np.array([cx + sgn * w * 0.85, mouth + 0.03 * scale])
            for k in range(3):
                lines.append(np.array([root, root + np.array([sgn * (0.13 + 0.03 * k) * scale, -(0.09 - 0.05 * k) * scale])]))
    return lines


def _circle_xy(cx: float, cy: float, r: float, k: int = 14) -> np.ndarray:
    t = np.linspace(0, TAU, k)
    return np.stack([cx + np.cos(t) * r, cy + np.sin(t) * r], axis=1)
