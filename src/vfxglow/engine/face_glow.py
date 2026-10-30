"""Efectos glowing del rostro para el catálogo `cara` (adornos `type: adornment`, `style.shapes`).

Solo luz sobre la cara real: nada de deformarla ni cambiarle la piel. Se anclan a la malla facial
(`face_<n>`, engine/anchors.py) y, si la malla se pierde, a plantillas puestas con los ojos y la nariz
de la pose. El lado de la cara que gira hacia atrás (su ojo se ve mucho más angosto que el otro) no
se dibuja.

- liner_trace: ojos, cejas y labios se delinean en orden con una chispa en la punta.
- face_oval_trace: el contorno de la cara y la línea de la frente se trazan solos.
- face_geometry: triángulos sobre frente, pómulos y mentón que se encienden uno tras otro.
- face_mesh_live: la malla de la cara (triangulada) se arma desde la nariz, late y al final se rompe
  en puntos.
- face_scan: un barrido holográfico baja por la cara y enciende los puntos que toca.
- face_crystal: facetas de cristal (triángulos grandes rellenos y tenues, bordes brillantes) y grietas.
- face_circuit: pistas de circuito que salen de la nariz hacia los bordes, con nodos.
- face_runes: runas que se escriben trazo a trazo en la frente y las mejillas.
- eye_beams: rayos que salen de los ojos hacia afuera (ojos muy abiertos).
- eye_flames: llamas de contorno que suben de los ojos.
- mouth_charge: una esfera crece en la boca abierta y al final sale en ondas.
- breath: un aliento de partículas finas que sale de la boca.
- smile_sparks: destellos que saltan de las mejillas al sonreír.
- brow_lines: arcos de sorpresa sobre las cejas.
- cheek_glow: círculos que se inflan en las mejillas.
- blink_mask: al parpadear, por un momento, una máscara de neón (robot o calavera).
- rune_orbit: un anillo de runas que gira alrededor de la cabeza y se esconde detrás.
- head_echo: copias del contorno de la cabeza que se quedan atrás y se apagan.
- face_emanate: partículas que nacen en el contorno de la cara y salen hacia afuera, como vapor de
  luz.
- face_swirl: un remolino de partículas que gira alrededor de la cabeza en dos órbitas, pasando por
  detrás.
- face_sparkle_rain: destellos que caen desde la frente por los lados de la cara.
- eye_sparks: chispas que salen de los ojos y se esparcen.
- makeup_figure: el trazo de maquillaje (`paint_stroke`) se vuelve su figura (triángulo, elipse,
  rectángulo, círculo): se traza desde un vértice, un arco la recorre, se itera hacia afuera y queda
  como cristal; sigue a la cara aunque se mueva.
"""

from __future__ import annotations

import zlib

import cv2
import numpy as np

from vfxglow.analysis.names import FACE_FEATURES
from vfxglow.engine.critters import _ease, _phase, _seg
from vfxglow.engine.dissolve import melt
from vfxglow.engine.duo_fx import body_mask, fill_band, visible
from vfxglow.engine.raster import fill_polygon, splat

TAU = 2.0 * np.pi
WHITE = np.array([1.0, 1.0, 1.0], np.float32)
FACE_GLOW = (
    "liner_trace", "face_oval_trace", "face_geometry", "face_mesh_live", "face_scan", "face_crystal",
    "face_circuit", "face_runes", "eye_beams", "eye_flames", "mouth_charge", "breath", "smile_sparks",
    "brow_lines", "cheek_glow", "blink_mask", "rune_orbit", "head_echo", "makeup_figure",
    "face_emanate", "face_swirl", "face_sparkle_rain", "eye_sparks",
)
# Los que van sobre la piel: con poco halo (FACE_HALO), para no lavar la cara de luz.
ON_FACE = tuple(s for s in FACE_GLOW if s not in ("rune_orbit", "head_echo", "eye_beams", "breath", "face_emanate", "face_swirl", "face_sparkle_rain", "eye_sparks"))
# Lo que ya tiene su propia salida no se suelta en polvo.
NO_MELT = ("face_mesh_live", "head_echo")
# Un ojo que se ve más angosto que esto frente al otro está del lado que gira hacia atrás.
FAR_EYE = 0.6
# Orden del delineado y del contorno.
LINER_ORDER = ("right_eye", "left_eye", "right_brow", "left_brow", "lips_outer")
# Plantillas en coordenadas de la cara (engine/anchors.local_frame): ojos en x=±0.5, y hacia el mentón.
_TEMPLATES = {
    "right_eye": ((-0.5, 0.0), 0.2, 0.08),
    "left_eye": ((0.5, 0.0), 0.2, 0.08),
    "lips_outer": ((0.0, 1.0), 0.32, 0.12),
    "face_oval": ((0.0, 0.45), 0.95, 1.2),
}
# Runas: trazos en una caja de 1x1 (x a la derecha, y hacia abajo), al estilo futhark.
_RUNES = (
    [[(0.5, 0.0), (0.5, 1.0)], [(0.5, 0.25), (0.85, 0.05)], [(0.5, 0.5), (0.85, 0.3)]],
    [[(0.3, 0.0), (0.3, 1.0)], [(0.3, 0.0), (0.75, 0.3), (0.3, 0.55)], [(0.3, 0.55), (0.75, 1.0)]],
    [[(0.5, 0.0), (0.5, 1.0)], [(0.15, 0.2), (0.85, 0.8)], [(0.85, 0.2), (0.15, 0.8)]],
    [[(0.2, 1.0), (0.5, 0.0), (0.8, 1.0)], [(0.35, 0.55), (0.65, 0.55)]],
    [[(0.5, 0.0), (0.5, 1.0)], [(0.5, 0.0), (0.15, 0.35)], [(0.5, 0.0), (0.85, 0.35)]],
    [[(0.2, 0.0), (0.2, 1.0)], [(0.8, 0.0), (0.8, 1.0)], [(0.2, 0.35), (0.8, 0.65)], [(0.8, 0.35), (0.2, 0.65)]],
)


class Face:
    """Los rasgos de la cara en píxeles, de la malla o de las plantillas."""

    def __init__(self, body, scale: float) -> None:
        from vfxglow.engine.anchors import local_frame

        self.points = body.points
        frame = local_frame(body.points, "face")
        if frame is None:  # sin ojos: la cabeza de la pose
            nose = body.get("nose")
            center = nose if nose is not None else body.mid("left_shoulder", "right_shoulder")
            unit = 0.32 * scale
            frame = (center - np.array([0.0, 0.1 * scale]) if center is not None else np.zeros(2), np.array([unit, 0.0]), np.array([0.0, unit]))
        self.origin, self.ux, self.uy = frame
        self.unit = max(float(np.linalg.norm(self.ux)), 1.0)
        self.mesh = any(k.startswith("face_") and k[5:].isdigit() for k in body.points)

    def place(self, local) -> np.ndarray:
        local = np.asarray(local, dtype=np.float64).reshape(-1, 2)
        return self.origin + np.outer(local[:, 0], self.ux) + np.outer(local[:, 1], self.uy)

    def feature(self, name: str) -> np.ndarray | None:
        chain = FACE_FEATURES.get(name)
        if chain is not None and self.mesh:
            found = [self.points[f"face_{i}"] for i in chain if f"face_{i}" in self.points]
            if len(found) >= max(3, len(chain) // 2):
                return np.array(found, dtype=np.float64)
        if name in _TEMPLATES:
            (cx, cy), rx, ry = _TEMPLATES[name]
            t = np.linspace(0, TAU, 32)
            return self.place(np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1))
        if name.endswith("_brow"):
            sx = -0.5 if name.startswith("right") else 0.5
            return self.place([(sx - 0.25, -0.22), (sx, -0.32), (sx + 0.25, -0.24)])
        return None

    def local(self, name: str, default) -> tuple[float, float]:
        """Un punto de la malla en coordenadas de cara, o `default` si no hay malla."""
        point = self.points.get(name)
        if point is None or not self.mesh:
            return float(default[0]), float(default[1])
        x, y = np.linalg.solve(np.stack([self.ux, self.uy], axis=1), point - self.origin)
        return float(x), float(y)

    def at(self, name: str, local) -> np.ndarray:
        point = self.points.get(name)
        return point if point is not None and self.mesh else self.place(local)[0]

    def far_side(self) -> str | None:
        """El lado de la cara que gira hacia atrás ("right"/"left" de la persona), o None."""
        widths = {}
        for side in ("right", "left"):
            eye = self.feature(f"{side}_eye")
            if eye is None or not self.mesh:
                return None
            widths[side] = float(np.ptp(eye @ (self.ux / self.unit)))
        if min(widths.values()) < FAR_EYE * max(widths.values()):
            return min(widths, key=widths.get)
        return None

    def visible(self, name: str) -> bool:
        far = self.far_side()
        return far is None or not name.startswith(far)


def _trim(line: np.ndarray, fraction: float) -> np.ndarray:
    """El tramo inicial de la línea, hasta `fraction` de su largo."""
    if fraction >= 1.0 or len(line) < 2:
        return line
    seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    stop = acc[-1] * max(fraction, 0.0)
    keep = acc <= stop
    k = int(keep.sum())
    if k < 1:
        return line[:1]
    if k >= len(line):
        return line
    t = (stop - acc[k - 1]) / max(seg[k - 1], 1e-9)
    return np.vstack([line[:k], line[k - 1] + (line[k] - line[k - 1]) * t])


def _oval(face: Face) -> np.ndarray:
    return face.feature("face_oval")


def _seed(shape: str, body, event) -> int:
    return zlib.crc32(f"{shape}:{body.prefix}:{event.start_frame if event else 0}".encode())


# ----- delineado y contorno -----


def _liner(face: Face, u: float, layer, kernels) -> list[np.ndarray]:
    names = [n for n in LINER_ORDER if face.visible(n)]
    lines = []
    for k, name in enumerate(names):
        line = face.feature(name)
        if line is None:
            continue
        local = _seg(u, k / (len(names) + 1), (k + 1.5) / (len(names) + 1))
        if local <= 0:
            continue
        drawn = _trim(line, _ease(local))
        lines.append(drawn)
        if local < 1.0:  # la chispa en la punta del delineador
            tip = drawn[-1]
            splat(layer, float(tip[0]), float(tip[1]), 0.12 * face.unit, WHITE * 0.9, 1.0, kernels)
    return lines


def _oval_trace(face: Face, u: float, layer, kernels) -> list[np.ndarray]:
    oval = _oval(face)
    if oval is None:
        return []
    drawn = _trim(np.vstack([oval, oval[:1]]), _ease(_seg(u, 0.0, 0.6)))
    if u < 0.6:
        splat(layer, float(drawn[-1][0]), float(drawn[-1][1]), 0.14 * face.unit, WHITE * 0.9, 1.0, kernels)
    brow = face.place([(-0.9, -0.55), (0.0, -0.75), (0.9, -0.55)])
    return [drawn] + ([_trim(brow, _seg(u, 0.5, 0.8))] if u > 0.5 else [])


# ----- geometría y malla -----


def _cells(face: Face) -> list[tuple[str, np.ndarray]]:
    """Triángulos de la cara por zona: frente, dos pómulos, nariz y mentón (en coordenadas de cara)."""
    # Con malla, la frente y el mentón se miden en la cara real (la plantilla subía la frente hasta
    # el pelo en las caras de cerca).
    forehead = face.local("forehead_top", (0.0, -1.05))[1] * 0.85
    chin = face.local("chin", (0.0, 1.6))[1]
    cells = [
        ("forehead", [(-0.6, -0.5), (0.0, forehead), (0.6, -0.5)]),
        ("right", [(-0.85, 0.25), (-0.35, 0.3), (-0.65, 0.75)]),
        ("left", [(0.85, 0.25), (0.35, 0.3), (0.65, 0.75)]),
        ("nose", [(0.0, 0.05), (-0.18, 0.6), (0.18, 0.6)]),
        ("chin", [(-0.25, chin - 0.3), (0.25, chin - 0.3), (0.0, chin - 0.05)]),
    ]
    return [(zone, face.place(tri)) for zone, tri in cells if zone not in ("right", "left") or face.visible(zone)]


def _geometry(face: Face, u: float, layer, color) -> list[np.ndarray]:
    lines = []
    cells = _cells(face)
    for k, (_zone, tri) in enumerate(cells):
        on = _seg(u, k * 0.12, k * 0.12 + 0.2)
        if on <= 0:
            continue
        closed = np.vstack([tri, tri[:1]])
        lines.append(_trim(closed, _ease(on)))
        if on >= 1.0:
            fill_polygon(layer, tri, np.asarray(color, np.float32), 0.18, 1.0, feather=1.5)
    return lines


def _mesh_points(face: Face) -> np.ndarray:
    pts = [v for k, v in face.points.items() if k.startswith("face_") and k[5:].isdigit()]
    if len(pts) < 12:  # sin malla: puntos de las plantillas
        pts = [p for name in ("face_oval", "right_eye", "left_eye", "lips_outer") if (f := face.feature(name)) is not None for p in f[::3]]
    return np.array(pts, dtype=np.float64)


def _triangles(points: np.ndarray, stride: int = 1) -> list[np.ndarray]:
    points = points[::stride]
    if len(points) < 4:
        return []
    lo = points.min(axis=0) - 2
    hi = points.max(axis=0) + 2
    subdiv = cv2.Subdiv2D((int(lo[0]), int(lo[1]), int(hi[0] - lo[0]) + 1, int(hi[1] - lo[1]) + 1))
    for p in points:
        subdiv.insert((float(p[0]), float(p[1])))
    out = []
    for t in subdiv.getTriangleList():
        tri = t.reshape(3, 2).astype(np.float64)
        if np.all(tri >= lo) and np.all(tri <= hi):
            out.append(tri)
    return out


def _mesh_live(face: Face, u: float, frame_index: int, layer, kernels, color) -> list[np.ndarray]:
    tris = _triangles(_mesh_points(face), 5)  # una malla abierta: tupida, la cara se lava de luz
    if not tris:
        return []
    nose = face.at("nose_tip", (0.0, 0.55))
    reach = _ease(_seg(u, 0.0, 0.45)) * 2.2 * face.unit  # se arma desde la nariz
    pulse = 0.6 + 0.4 * np.sin(frame_index * 0.35)
    lines = []
    if u > 0.85:  # se rompe en puntos
        fade = _seg(u, 0.85, 1.0)
        for tri in tris[::2]:
            c = tri.mean(axis=0)
            splat(layer, float(c[0]), float(c[1]), 0.04 * face.unit + 0.6, WHITE * 0.6, 1.0 - fade, kernels)
        return []
    for tri in tris:
        if float(np.linalg.norm(tri.mean(axis=0) - nose)) <= reach:
            lines.append(np.vstack([tri, tri[:1]]))
    if lines:
        c = nose
        splat(layer, float(c[0]), float(c[1]), 0.2 * face.unit, np.asarray(color, np.float32) * 0.4, 0.4 * pulse, kernels)
    return lines


def _scan(face: Face, u: float, layer, kernels) -> list[np.ndarray]:
    oval = _oval(face)
    if oval is None:
        return []
    top, bottom = oval[:, 1].min(), oval[:, 1].max()
    y = top + (bottom - top) * ((u * 1.6) % 1.0)  # baja por la cara, dos pasadas
    inside = oval[np.abs(oval[:, 1] - y) < (bottom - top) * 0.5]
    left, right = (inside[:, 0].min(), inside[:, 0].max()) if len(inside) else (oval[:, 0].min(), oval[:, 0].max())
    span = right - left
    lines = [np.array([[left - span * 0.15, y], [right + span * 0.15, y]])]
    for k in range(1, 4):  # la estela tenue de la rejilla
        yy = y - k * (bottom - top) * 0.05
        if yy > top:
            lines.append(np.array([[left, yy], [right, yy]]))
    for p in _mesh_points(face):
        if abs(p[1] - y) < (bottom - top) * 0.04:
            splat(layer, float(p[0]), float(p[1]), 0.05 * face.unit + 0.6, WHITE * 0.9, 1.0, kernels)
    return lines


# Zonas del cristal en coordenadas de cara: (centro x, centro y, radio). Se sortea una por vez.
_CRYSTAL_ZONES = {"forehead": (0.0, -0.6, 0.55), "right": (-0.6, 0.5, 0.42), "left": (0.6, 0.5, 0.42), "nose": (0.0, 0.4, 0.38), "chin": (0.0, 1.25, 0.42)}


def _crystal(face: Face, u: float, layer, color, rng) -> list[np.ndarray]:
    zones = [z for z in _CRYSTAL_ZONES if z not in ("right", "left") or face.visible(z)]
    zone = zones[int(rng.integers(0, len(zones)))]
    cx, cy, radius = _CRYSTAL_ZONES[zone]
    basis = np.stack([face.ux, face.uy], axis=1)
    points = _mesh_points(face)
    local = np.linalg.solve(basis, (points - face.origin).T).T
    near = points[np.linalg.norm(local - [cx, cy], axis=1) <= radius]
    if len(near) < 5:  # sin malla: unos puntos al azar dentro de la zona
        angles = rng.uniform(0, TAU, 9)
        near = face.place(np.stack([cx + np.cos(angles) * radius * rng.uniform(0.3, 1.0, 9), cy + np.sin(angles) * radius * rng.uniform(0.3, 1.0, 9)], axis=1))
    stride = max(len(near) // int(rng.integers(6, 12)), 1)  # entre 6 y 11 puntos: más o menos facetas
    tris = _triangles(near, stride)
    grow = _ease(_seg(u, 0.0, 0.4))
    lines = []
    for k, tri in enumerate(tris):
        if k / max(len(tris), 1) > grow:
            continue
        fill_polygon(layer, tri, np.asarray(color, np.float32) * 0.6 + WHITE * 0.2, 0.12, 1.0, feather=1.0)
        lines.append(np.vstack([tri, tri[:1]]))
    if u > 0.55:  # grietas brillantes
        for tri in tris[:: max(len(tris) // 5, 1)]:
            c = tri.mean(axis=0)
            a = rng.uniform(0, TAU)
            lines.append(np.array([c, c + np.array([np.cos(a), np.sin(a)]) * 0.25 * face.unit, c + np.array([np.cos(a + 0.5), np.sin(a + 0.5)]) * 0.45 * face.unit]))
    return lines


def _circuit(face: Face, u: float, layer, kernels, rng) -> list[np.ndarray]:
    lines = []
    start = face.at("nose_tip", (0.0, 0.55))
    for k in range(8):
        angle = TAU * k / 8 + rng.uniform(-0.2, 0.2)
        path = [start]
        heading = np.array([np.cos(angle), np.sin(angle)])
        for step in range(3):  # tramos rectos que doblan en ángulos de 45°
            length = rng.uniform(0.25, 0.45) * face.unit
            path.append(path[-1] + heading * length)
            turn = rng.choice([-np.pi / 4, np.pi / 4])
            heading = np.array([heading[0] * np.cos(turn) - heading[1] * np.sin(turn), heading[0] * np.sin(turn) + heading[1] * np.cos(turn)])
        line = _trim(np.array(path), _ease(_seg(u, 0.0, 0.5)))
        lines.append(line)
        if u > 0.5:  # el nodo al final de cada pista
            end = path[-1]
            t = np.linspace(0, TAU, 12)
            lines.append(end + np.stack([np.cos(t), np.sin(t)], axis=1) * 0.06 * face.unit)
            splat(layer, float(end[0]), float(end[1]), 0.05 * face.unit, WHITE * 0.7, 1.0, kernels)
    return lines


def _rune(face: Face, index: int, center_local, size: float, progress: float) -> list[np.ndarray]:
    strokes = _RUNES[index % len(_RUNES)]
    out = []
    for k, stroke in enumerate(strokes):
        local = np.array([(center_local[0] + (x - 0.5) * size, center_local[1] + (y - 0.5) * size) for x, y in stroke])
        part = _seg(progress, k / len(strokes), (k + 1) / len(strokes))
        if part > 0:
            out.append(_trim(face.place(local), part))
    return out


def _runes(face: Face, u: float, seed: int) -> list[np.ndarray]:
    spots = [(0.0, -0.75, 0.32), (-0.65, 0.55, 0.22), (0.65, 0.55, 0.22)]
    lines = []
    for k, (x, y, size) in enumerate(spots):
        if (k == 1 and not face.visible("right")) or (k == 2 and not face.visible("left")):
            continue
        lines += _rune(face, seed + k, (x, y), size, _seg(u, k * 0.15, k * 0.15 + 0.45))
    return lines


# ----- ojos y boca -----


def _eye_beams(face: Face, u: float, frame_index: int, layer, kernels, rng) -> list[np.ndarray]:
    lines = []
    reach = _ease(_seg(u, 0.0, 0.3)) * 2.4 * face.unit
    for side, out in (("right", -1.0), ("left", 1.0)):
        if not face.visible(side):
            continue
        eye = face.at(f"{side}_iris", (0.5 * out, 0.0))
        d = (face.ux / face.unit) * out * 0.9 + (face.uy / face.unit) * 0.25
        d = d / float(np.linalg.norm(d))
        n = np.array([-d[1], d[0]])
        for k in (-1, 0, 1):
            wobble = np.sin(frame_index * 0.9 + k) * 0.03 * face.unit
            lines.append(np.array([eye, eye + d * reach + n * (k * 0.12 * face.unit + wobble)]))
        splat(layer, float(eye[0]), float(eye[1]), 0.25 * face.unit, WHITE * 0.9, 1.0, kernels)
    return lines


def _eye_flames(face: Face, u: float, frame_index: int) -> list[np.ndarray]:
    lines = []
    up = -face.uy / face.unit
    for side, out in (("right", -1.0), ("left", 1.0)):
        if not face.visible(side):
            continue
        eye = face.at(f"{side}_iris", (0.5 * out, 0.0))
        across = face.ux / face.unit
        for k in range(3):  # tres lenguas que suben y ondulan
            q = np.linspace(0, 1, 14)[:, None]
            height = (0.45 + 0.15 * k) * face.unit * (0.7 + 0.3 * np.sin(frame_index * 0.5 + k))
            sway = np.sin(q * np.pi * 2 + frame_index * 0.6 + k) * 0.08 * face.unit * q
            base = eye + across * (k - 1) * 0.08 * face.unit
            lines.append(base + up * q * height + across * sway)
    return lines


def _mouth_charge(face: Face, u: float, frame_index: int, layer, kernels, color, openness: float) -> list[np.ndarray]:
    mouth = face.at("mouth_center", (0.0, 1.0))
    lines = []
    if u < 0.75:  # carga mientras la boca está abierta
        r = (0.08 + 0.3 * _ease(_seg(u, 0.0, 0.7)) * (0.6 + 0.4 * openness)) * face.unit
        t = np.linspace(0, TAU, 32)
        lines.append(mouth + np.stack([np.cos(t), np.sin(t)], axis=1) * r * (1 + 0.05 * np.sin(frame_index)))
        splat(layer, float(mouth[0]), float(mouth[1]), r * 1.3, WHITE * 0.7 + np.asarray(color, np.float32) * 0.4, 0.8, kernels)
        return lines
    wave = _seg(u, 0.75, 1.0)  # sale en ondas
    for k in range(3):
        r = (0.4 + 2.2 * wave + 0.35 * k) * face.unit
        t = np.linspace(0, TAU, 48)
        if wave < 0.95:
            lines.append(mouth + np.stack([np.cos(t), np.sin(t) * 0.7], axis=1) * r)
    return lines


def _breath(face: Face, u: float, frame_index: int, layer, kernels, color, rng) -> list[np.ndarray]:
    mouth = face.at("mouth_center", (0.0, 1.0))
    out = face.uy / face.unit  # hacia abajo y afuera de la boca
    tint = np.asarray(color, np.float32)
    for k in range(40):
        age = (k / 40 + frame_index * 0.03) % 1.0
        spread = rng.uniform(-0.6, 0.6)
        at = mouth + (out * 0.2 + face.ux / face.unit * spread * 0.4) * age * 3.0 * face.unit
        splat(layer, float(at[0]), float(at[1]), (0.02 + 0.03 * age) * face.unit + 0.5, WHITE * 0.4 + tint * 0.4, (1 - age) * 0.6 * (1 - _seg(u, 0.85, 1.0)), kernels)
    return []


# ----- expresiones -----


def _star(center: np.ndarray, size: float) -> list[np.ndarray]:
    return [np.array([center - [size, 0], center + [size, 0]]), np.array([center - [0, size], center + [0, size]]),
            np.array([center - [size * 0.5, size * 0.5], center + [size * 0.5, size * 0.5]]), np.array([center - [size * 0.5, -size * 0.5], center + [size * 0.5, -size * 0.5]])]


def _smile_sparks(face: Face, u: float, frame_index: int, rng, smile: float) -> list[np.ndarray]:
    lines = []
    for side, out in (("right", -1.0), ("left", 1.0)):
        if not face.visible(side):
            continue
        cheek = face.place([(0.7 * out, 0.65)])[0]
        for k in range(3):
            age = (u * 2.0 + k / 3) % 1.0  # saltan hacia afuera y arriba
            d = face.ux / face.unit * out * 0.7 - face.uy / face.unit * 0.7
            at = cheek + d * age * 0.9 * face.unit + rng.uniform(-0.1, 0.1, 2) * face.unit
            size = (0.08 + 0.1 * smile) * face.unit * np.sin(age * np.pi)  # más sonrisa, más grandes
            if size > 0.5:
                lines += _star(at, size)
    return lines


def _brow_lines(face: Face, u: float) -> list[np.ndarray]:
    lines = []
    lift = _ease(_seg(u, 0.0, 0.3))
    for k in range(3):
        y = -0.55 - 0.18 * k - 0.1 * lift
        t = np.linspace(-0.6, 0.6, 16)
        arc = np.stack([t, y + 0.08 * t ** 2], axis=1)
        if _seg(u, k * 0.1, k * 0.1 + 0.25) > 0:
            lines.append(_trim(face.place(arc), _seg(u, k * 0.1, k * 0.1 + 0.25)))
    return lines


def _cheek_glow(face: Face, u: float, layer, color, puff: float) -> list[np.ndarray]:
    lines = []
    inflate = 0.15 + (0.12 + 0.2 * puff) * _ease(_seg(u, 0.0, 0.4))  # crecen con la mejilla
    for side, out in (("right", -1.0), ("left", 1.0)):
        if not face.visible(side):
            continue
        center = face.place([(0.7 * out, 0.65)])[0]
        t = np.linspace(0, TAU, 28)
        ring = center + np.stack([np.cos(t), np.sin(t)], axis=1) * inflate * face.unit
        fill_polygon(layer, ring, np.asarray(color, np.float32), 0.2, 1.0, feather=2.0)
        lines.append(ring)
    return lines


def _blink_mask(face: Face, u: float, seed: int) -> list[np.ndarray]:
    oval = _oval(face)
    lines = [np.vstack([oval, oval[:1]])] if oval is not None else []
    if seed % 2 == 0:  # robot: visor sobre los ojos y placas en la mandíbula
        lines.append(face.place([(-0.85, -0.12), (0.85, -0.12), (0.85, 0.15), (-0.85, 0.15), (-0.85, -0.12)]))
        for x in (-0.5, 0.0, 0.5):
            lines.append(face.place([(x, 1.1), (x, 1.45)]))
        lines.append(face.place([(-0.6, 1.1), (0.6, 1.1)]))
    else:  # calavera: cuencas, nariz en hueco y dientes
        for x in (-0.5, 0.5):
            t = np.linspace(0, TAU, 20)
            lines.append(face.place(np.stack([x + 0.22 * np.cos(t), 0.02 + 0.17 * np.sin(t)], axis=1)))
        lines.append(face.place([(0.0, 0.4), (-0.1, 0.62), (0.1, 0.62), (0.0, 0.4)]))
        lines.append(face.place([(-0.35, 1.0), (0.35, 1.0)]))
        for x in np.linspace(-0.3, 0.3, 6):
            lines.append(face.place([(x, 0.92), (x, 1.08)]))
    return lines


# ----- cabeza -----


def _rune_orbit(face: Face, body, scale: float, frame_index: int, layer, seed: int) -> list[np.ndarray]:
    center = face.place([(0.0, -0.2)])[0]
    across, up = face.ux / face.unit, -face.uy / face.unit
    mask = body_mask(body, layer.shape[:2], scale)
    lines = []
    count = 7
    for k in range(count):
        a = frame_index * 0.08 + TAU * k / count
        depth = np.sin(a)
        at = center + across * np.cos(a) * 1.6 * face.unit + up * (0.25 * depth - 0.1) * face.unit
        if depth < 0 and mask is not None:
            x, y = int(np.clip(at[0], 0, mask.shape[1] - 1)), int(np.clip(at[1], 0, mask.shape[0] - 1))
            if mask[y, x]:
                continue  # detrás de la cabeza: no se ve
        size = 0.28 * (0.75 + 0.25 * depth)
        for stroke in _RUNES[(seed + k) % len(_RUNES)]:
            lines.append(np.array([at + across * (x - 0.5) * size * face.unit - up * (y - 0.5) * size * face.unit for x, y in stroke]))
    t = np.linspace(0, TAU, 72)
    ring = center + np.outer(np.cos(t) * 1.6 * face.unit, across) + np.outer((0.25 * np.sin(t) - 0.1) * face.unit, up)
    lines += [ring[a:b] for a, b in visible(ring, np.sin(t), mask)]
    return lines


def _head_echo(face: Face, frame_index: int, runtime) -> list:
    oval = _oval(face)
    if oval is None:
        return []
    st = runtime.swoosh.setdefault("_head_echo", {"copies": []})
    copies = st["copies"]
    if not copies or float(np.linalg.norm(oval.mean(axis=0) - copies[-1].mean(axis=0))) > 0.15 * face.unit:
        copies.append(oval.copy())
        del copies[:-3]
    out = [np.vstack([oval, oval[:1]])]
    for age, old in enumerate(reversed(copies[:-1]), start=1):
        out.append((np.vstack([old, old[:1]]), np.full(3, 0.45 ** age, np.float32)))
    return out


# ----- maquillaje -----


def _figure_local(face: Face, runtime, event) -> tuple[str, np.ndarray] | None:
    """La figura del trazo (en coordenadas de la cara del momento del trazo), una vez por evento."""
    from vfxglow.analysis.shapes import fit_shape

    st = runtime.swoosh.setdefault(f"_makeup:{event.start_frame if event else 0}", {})
    if "figure" in st:
        return st["figure"]
    appearance = getattr(runtime, "appearance", None)
    contour = None
    if appearance is not None and event is not None:
        frames = [f for f in getattr(appearance, "contours", {}) if event.start_frame <= f <= event.end_frame]
        if frames:
            h, w = getattr(runtime, "frame_shape", (1, 1))
            contour = np.array(appearance.contours[max(frames)], dtype=np.float64) * [w, h]
    if contour is None or len(contour) < 5:  # sin la pintura a mano: un triángulo en el pómulo
        corners = face.place([(0.45, 0.35), (0.9, 0.45), (0.6, 0.85)])
        contour = np.vstack([np.linspace(corners[k], corners[(k + 1) % 3], 6, endpoint=False) for k in range(3)])
    figure = fit_shape(contour)
    if figure is None:
        return None
    if "vertices" in figure:
        outline = np.asarray(figure["vertices"], dtype=np.float64)
    else:
        (cx, cy), (aw, ah), ang = figure["center"], figure["axes"], np.radians(figure["angle"])
        t = np.linspace(0, TAU, 32, endpoint=False)
        local = np.stack([aw / 2 * np.cos(t), ah / 2 * np.sin(t)], axis=1)
        rot = np.array([[np.cos(ang), -np.sin(ang)], [np.sin(ang), np.cos(ang)]])
        outline = local @ rot.T + [cx, cy]
    basis = np.stack([face.ux, face.uy], axis=1)
    local = np.linalg.solve(basis, (outline - face.origin).T).T  # queda pegada a la cara
    st["figure"] = (figure["kind"], local)
    return st["figure"]


def _makeup_figure(face: Face, u: float, frame_index: int, runtime, layer, color, event) -> list[np.ndarray]:
    found = _figure_local(face, runtime, event)
    if found is None:
        return []
    _kind, local = found
    shape = face.place(local)
    closed = np.vstack([shape, shape[:1]])
    lines = [_trim(closed, _ease(_seg(u, 0.0, 0.35)))]  # se traza desde un vértice
    center = shape.mean(axis=0)
    if 0.3 < u < 0.7:  # un arco que recorre el borde
        k = int(((u - 0.3) / 0.4) * len(closed)) % len(closed)
        lines.append(closed[max(k - 4, 0):k + 1])
    if u > 0.45:  # copias que crecen hacia afuera y se apagan
        for j in range(3):
            g = (u * 2.0 + j / 3) % 1.0
            lines.append(center + (closed - center) * (1.0 + 0.8 * g))
    if u > 0.6:  # queda como cristal
        fill_polygon(layer, shape, np.asarray(color, np.float32) * 0.5 + WHITE * 0.3, 0.22, 1.0, feather=1.0)
        lines += [np.array([center, p]) for p in shape[:: max(len(shape) // 4, 1)]]
    return lines


# ----- partículas -----


def paced(frame_index: int, runtime) -> int:
    """El fotograma contado como si el video fuera de 30 fps."""
    return int(round(frame_index * 30.0 / (getattr(runtime, "fps", 30.0) or 30.0)))


def steps(runtime) -> int:
    """Pasos de 30 fps que entran en un fotograma de este video (lo que simula paso a paso)."""
    return max(int(round(30.0 / (getattr(runtime, "fps", 30.0) or 30.0))), 1)


def _clock(runtime) -> float:
    """Un reloj que corre más rápido cuando la cabeza se mueve: las partículas siguen su energía."""
    st = runtime.swoosh.setdefault("_clock", {"t": 0.0, "frame": -1})
    if st["frame"] != runtime.active_frames:
        st["frame"] = runtime.active_frames
        st["t"] += (1.0 + 2.5 * float(getattr(runtime, "energy", 0.0))) * steps(runtime)
    return st["t"]


def _palette(runtime, color) -> list[np.ndarray]:
    colors = [np.asarray(c, np.float32) for c in (runtime.effect.style.colors or [])] or [np.asarray(color, np.float32)]
    return colors


def _emanate(face: Face, u: float, frame_index: int, layer, kernels, colors, seed: int) -> list[np.ndarray]:
    oval = _oval(face)
    if oval is None:
        return []
    center = oval.mean(axis=0)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(oval), 70)
    phases = rng.uniform(0, 1, 70)
    fade = 1.0 - _seg(u, 0.85, 1.0)
    for k, (i, ph) in enumerate(zip(starts, phases)):
        age = (frame_index * 0.025 + ph) % 1.0
        p = oval[i]
        out = (p - center) / max(float(np.linalg.norm(p - center)), 1e-6)
        at = p + out * age * 0.9 * face.unit - np.array([0.0, 0.3 * age * face.unit])
        size = (0.02 + 0.05 * (1 - age)) * face.unit + 0.5
        splat(layer, float(at[0]), float(at[1]), size, colors[k % len(colors)] * 1.3, (1 - age) * fade, kernels)
    return []


def _swirl(face: Face, body, scale: float, u: float, frame_index: int, layer, kernels, colors) -> list[np.ndarray]:
    center = face.place([(0.0, 0.3)])[0]
    across, up = face.ux / face.unit, -face.uy / face.unit
    mask = body_mask(body, layer.shape[:2], scale)
    fade = 1.0 - _seg(u, 0.85, 1.0)
    grow = _ease(_seg(u, 0.0, 0.2))
    for ring, (radius, tilt, speed, count) in enumerate(((1.4, 0.3, 0.09, 26), (1.75, -0.25, -0.07, 30))):
        for k in range(count):
            a = frame_index * speed + TAU * k / count
            depth = np.sin(a)
            at = center + across * np.cos(a) * radius * face.unit * grow + up * (depth * tilt + 0.15 * np.sin(a * 3 + k)) * face.unit
            if depth < 0 and mask is not None:
                x, y = int(np.clip(at[0], 0, mask.shape[1] - 1)), int(np.clip(at[1], 0, mask.shape[0] - 1))
                if mask[y, x]:
                    continue  # detrás de la cabeza
            size = (0.035 + 0.025 * (depth + 1)) * face.unit + 0.5
            splat(layer, float(at[0]), float(at[1]), size, colors[(k + ring) % len(colors)] * 1.3, fade * (0.6 + 0.4 * (depth + 1) / 2), kernels)
    return []


def _sparkle_rain(face: Face, u: float, frame_index: int, layer, kernels, colors, seed: int) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    lines = []
    fade = 1.0 - _seg(u, 0.85, 1.0)
    for k in range(28):
        side = rng.choice([-1.0, 1.0])
        x = side * rng.uniform(0.6, 1.3)
        age = (frame_index * 0.03 + rng.uniform()) % 1.0
        at = face.place([(x, -1.0 + 2.8 * age)])[0]
        size = (0.04 + 0.04 * np.sin(age * np.pi)) * face.unit
        tint = colors[k % len(colors)]
        splat(layer, float(at[0]), float(at[1]), size + 0.5, tint * 1.3, fade * np.sin(age * np.pi), kernels)
        if k % 4 == 0 and size > 1.0:
            lines += _star(at, size * 1.6)
    return lines


def _eye_sparks(face: Face, u: float, frame_index: int, layer, kernels, colors, seed: int) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    fade = 1.0 - _seg(u, 0.85, 1.0)
    for side, out in (("right", -1.0), ("left", 1.0)):
        if not face.visible(side):
            continue
        eye = face.at(f"{side}_iris", (0.5 * out, 0.0))
        for k in range(18):
            age = (frame_index * 0.05 + rng.uniform()) % 1.0
            angle = rng.uniform(-1.2, 1.2) + (0.0 if out > 0 else np.pi)
            d = np.array([np.cos(angle), np.sin(angle) - 0.4])
            at = eye + d * age * 1.1 * face.unit
            splat(layer, float(at[0]), float(at[1]), (0.02 + 0.04 * (1 - age)) * face.unit + 0.5, colors[k % len(colors)] * 1.4, (1 - age) * fade, kernels)
    return []


def face_glow(shape, body, frame, scale, frame_index, runtime, layer, color, alpha, event) -> list:
    face = Face(body, scale)
    u = _phase(runtime, event)
    seed = _seed(shape, body, event)
    items = _draw(shape, body, scale, frame_index, runtime, layer, color, face, u, seed, event)
    if shape in NO_MELT:
        return items
    return melt(items, u, face, layer, color, alpha, runtime.kernels, seed)


def _draw(shape, body, scale, frame_index, runtime, layer, color, face, u, seed, event) -> list:
    rng = np.random.default_rng(seed)
    kernels = runtime.kernels
    expressions = getattr(runtime, "expressions", {}) or {}
    openness = float(expressions.get("jawOpen", 0.5))
    if shape == "liner_trace":
        return _liner(face, u, layer, kernels)
    if shape == "face_oval_trace":
        return _oval_trace(face, u, layer, kernels)
    if shape == "face_geometry":
        return _geometry(face, u, layer, color)
    if shape == "face_mesh_live":
        return _mesh_live(face, u, frame_index, layer, kernels, color)
    if shape == "face_scan":
        return _scan(face, u, layer, kernels)
    if shape == "face_crystal":
        return _crystal(face, u, layer, color, rng)
    if shape == "face_circuit":
        return _circuit(face, u, layer, kernels, rng)
    if shape == "face_runes":
        return _runes(face, u, seed)
    if shape == "eye_beams":
        return _eye_beams(face, u, frame_index, layer, kernels, rng)
    if shape == "eye_flames":
        return _eye_flames(face, u, frame_index)
    if shape == "mouth_charge":
        return _mouth_charge(face, u, frame_index, layer, kernels, color, openness)
    if shape == "breath":
        return _breath(face, u, frame_index, layer, kernels, color, rng)
    if shape == "smile_sparks":
        smile = (float(expressions.get("mouthSmileLeft", 0.5)) + float(expressions.get("mouthSmileRight", 0.5))) / 2
        return _smile_sparks(face, u, frame_index, np.random.default_rng((seed + frame_index // 3) & 0xFFFFFFFF), smile)
    if shape == "brow_lines":
        return _brow_lines(face, u)
    if shape == "cheek_glow":
        return _cheek_glow(face, u, layer, color, float(expressions.get("cheekPuff", 0.5)))
    if shape == "blink_mask":
        return _blink_mask(face, u, seed)
    if shape == "rune_orbit":
        return _rune_orbit(face, body, scale, frame_index, layer, seed)
    if shape == "head_echo":
        return _echo_colored(face, frame_index, runtime, color)
    if shape == "makeup_figure":
        return _makeup_figure(face, u, frame_index, runtime, layer, color, event)
    colors = _palette(runtime, color)
    if shape == "face_emanate":
        return _emanate(face, u, _clock(runtime), layer, kernels, colors, seed)
    if shape == "face_swirl":
        return _swirl(face, body, scale, u, _clock(runtime), layer, kernels, colors)
    if shape == "face_sparkle_rain":
        return _sparkle_rain(face, u, frame_index, layer, kernels, colors, seed)
    if shape == "eye_sparks":
        return _eye_sparks(face, u, frame_index, layer, kernels, colors, seed)
    return []


def _echo_colored(face: Face, frame_index: int, runtime, color) -> list:
    tint = np.asarray(color, np.float32)
    out = []
    for item in _head_echo(face, frame_index, runtime):
        if isinstance(item, tuple):
            line, fade = item
            out.append((line, tint * fade))
        else:
            out.append(item)
    return out
