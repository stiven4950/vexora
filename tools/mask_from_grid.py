"""De la cuadrícula de rostros neón (assets/masks/source/halloween_grid.png) a trazos vectoriales.

Cada celda es un rostro dibujado en neón sobre negro, con su nombre debajo
(assets/masks/source/halloween_grid.yaml). No se pega la imagen: se sacan sus líneas como
polilíneas en coordenadas de cara, para ponerlas sobre la persona (engine/horror_masks.py).

1. Se recorta la celda sin la franja del nombre.
2. Lo brillante es línea: umbral sobre el brillo y adelgazamiento al eje de cada línea (esqueleto).
3. El esqueleto se recorre en caminos ordenados y los caminos cuyas puntas se tocan se unen: una
   polilínea por línea del dibujo; los tramos de pocos píxeles (el halo) se descartan.
4. Los rasgos salen de las marcas de la celda (`marks` en el índice) o, sin ellas, de los huecos
   oscuros encerrados por las líneas: los dos grandes de arriba son los ojos, el de abajo la boca y
   el chico del medio la nariz. Cada trazo toma el rol del rasgo que bordea (`eye_right`, `eye_left`,
   `mouth`, `nose`) o `line`; un trazo que pasa de un rasgo a otro se corta donde cambia.
5. Coordenadas de cara (engine/anchors.local_frame): el punto medio entre los centros de los ojos es
   el origen, la distancia entre ellos es 1 (ojos en x = ±0,5) y y crece hacia el mentón.
6. Cada trazo guarda el color que tiene en el dibujo (el degradado de la referencia).

    python tools/mask_from_grid.py --cell 1        # escribe assets/masks/<id>.yaml
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
GRID = ROOT / "assets" / "masks" / "source" / "halloween_grid.png"
INDEX = ROOT / "assets" / "masks" / "source" / "halloween_grid.yaml"
OUT = ROOT / "assets" / "masks"
# Brillo mínimo de una línea (0-255), largo mínimo de un trazo (píxeles de esqueleto) y tolerancia
# al simplificar (píxeles).
BRIGHT = 120
MIN_STROKE = 8
SIMPLIFY = 0.8
# Un trazo rodea un hueco si casi todos sus puntos quedan a menos de esto de su borde (píxeles).
HOLE_NEAR = 7.0
# Dos tramos cuyas puntas quedan a menos de esto (píxeles) son la misma línea cortada en un cruce.
JOIN_PX = 3.5
# Las marcas rodean el rasgo; lo que cae a esta escala de su óvalo es parte de él.
MARK_GROW = 1.2
# La boca de reposo del grito largo (Ghostface): si queda muy abajo se encoge hasta que la persona
# abre la boca; en las caras de proporción humana queda en su lugar.
LONG_MOUTH = 1.4
LONG_MOUTH_REST = 0.8
# Ramitas del esqueleto más cortas que esto (píxeles) se podan.
SPUR_PX = 6
_OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def load_index() -> dict:
    return yaml.safe_load(INDEX.read_text(encoding="utf-8"))


def cell_image(number: int, grid: Path = GRID) -> np.ndarray:
    """La celda `number` (1-24, de izquierda a derecha y de arriba abajo) sin la franja del nombre."""
    index = load_index()
    image = cv2.imread(str(grid))
    cols, rows = index["columns"], index["rows"]
    w, h = image.shape[1] // cols, image.shape[0] // rows
    r, c = divmod(number - 1, cols)
    top, bottom = index.get("rows_y", [[0, h - index["label_px"]]] * rows)[r]
    cell = image[r * h : (r + 1) * h - index["label_px"], c * w : (c + 1) * w].copy()
    cell[:top] = 0  # el nombre de la fila de arriba
    cell[bottom:] = 0
    return cell


def _smooth(path: np.ndarray, window: int = 5) -> np.ndarray:
    """Promedio móvil a lo largo del trazo: quita los escalones de píxel sin mover las puntas."""
    if len(path) < window:
        return path.astype(np.float64)
    closed = np.allclose(path[0], path[-1])
    pts = path[:-1] if closed else path
    half = window // 2
    padded = np.vstack([pts[-half:], pts, pts[:half]]) if closed else np.vstack([np.repeat(pts[:1], half, 0), pts, np.repeat(pts[-1:], half, 0)])
    kernel = np.ones(window) / window
    out = np.stack([np.convolve(padded[:, k], kernel, mode="valid") for k in (0, 1)], axis=1)
    if not closed:
        out[0], out[-1] = pts[0], pts[-1]
        return out
    return np.vstack([out, out[:1]])


def _prune(skeleton: np.ndarray, length: int = SPUR_PX) -> np.ndarray:
    """Quita las ramitas cortas del esqueleto (los pelos que deja el halo a los lados de la línea):
    se borran las puntas `length` veces y lo que era línea larga vuelve a crecer por sus puntas."""
    k = np.ones((3, 3), np.float32)
    k[1, 1] = 0
    work = (skeleton > 0).astype(np.uint8)
    original = work.copy()
    for _ in range(length):
        neighbors = cv2.filter2D(work.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
        work[(work > 0) & (neighbors <= 1)] = 0
    for _ in range(length):  # las líneas largas recuperan lo que perdieron en las puntas
        grown = cv2.dilate(work, np.ones((3, 3), np.uint8)) & original
        neighbors = cv2.filter2D(work.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
        ends = (work > 0) & (neighbors <= 1)
        near_ends = cv2.dilate(ends.astype(np.uint8), np.ones((3, 3), np.uint8))
        work = work | (grown & near_ends)
    return work * 255


def _trace(component: np.ndarray) -> list[np.ndarray]:
    """Recorre todos los píxeles de un tramo en caminos ordenados: empieza por una punta, sigue a los
    vecinos y, si quedan píxeles sin recorrer (una ramita), sigue desde ellos."""
    pixels = {(int(y), int(x)) for y, x in zip(*np.nonzero(component))}

    def around(p, pool):
        return [(p[0] + dy, p[1] + dx) for dy, dx in _OFFSETS if (p[0] + dy, p[1] + dx) in pool]

    paths = []
    while pixels:
        ends = [p for p in pixels if len(around(p, pixels)) <= 1]
        start = ends[0] if ends else next(iter(pixels))
        path = [start]
        pixels.discard(start)
        while True:
            nxt = around(path[-1], pixels)
            if not nxt:
                break
            # Primero los vecinos de lado (no en diagonal): el camino no se salta píxeles.
            nxt.sort(key=lambda p: abs(p[0] - path[-1][0]) + abs(p[1] - path[-1][1]))
            path.append(nxt[0])
            pixels.discard(nxt[0])
        pts = np.array([(x, y) for y, x in path], dtype=np.float32)
        if not ends and len(path) > 3 and np.abs(pts[0] - pts[-1]).max() <= 1.5:
            pts = np.vstack([pts, pts[:1]])  # un lazo
        paths.append(pts)
    return paths


def _join(paths: list[np.ndarray], reach: float = JOIN_PX) -> list[np.ndarray]:
    """Une los tramos cuyas puntas se tocan (los cortes en los cruces del esqueleto), prefiriendo el
    que sigue en la misma dirección."""
    paths = [p for p in paths if len(p) >= 2]
    merged = True
    while merged:
        merged = False
        for i in range(len(paths)):
            a = paths[i]
            if np.allclose(a[0], a[-1]):
                continue
            best = None
            for j in range(len(paths)):
                b = paths[j]
                if i == j or np.allclose(b[0], b[-1]):
                    continue
                for flip_a in (False, True):
                    for flip_b in (False, True):
                        aa = a[::-1] if flip_a else a
                        bb = b[::-1] if flip_b else b
                        gap = float(np.linalg.norm(aa[-1] - bb[0]))
                        if gap > reach:
                            continue
                        da = aa[-1] - aa[max(len(aa) - 4, 0)]
                        db = bb[min(3, len(bb) - 1)] - bb[0]
                        turn = 1.0 - float(np.dot(da, db) / max(np.linalg.norm(da) * np.linalg.norm(db), 1e-6))
                        score = gap + 3.0 * turn
                        if best is None or score < best[0]:
                            best = (score, j, aa, bb)
            if best is not None:
                _score, j, aa, bb = best
                joined = np.vstack([aa, bb])
                paths = [p for k, p in enumerate(paths) if k not in (i, j)] + [joined]
                merged = True
                break
    return paths


def strokes_of(cell: np.ndarray) -> list[np.ndarray]:
    """Las líneas de neón de la celda como polilíneas en píxeles."""
    bright = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)[..., 2]
    mask = (bright > BRIGHT).astype(np.uint8) * 255
    skeleton = _prune(cv2.ximgproc.thinning(mask))
    # No se corta en los "cruces": en un esqueleto de 8 vecinos los escalones de una diagonal tienen
    # tres vecinos y la línea se rompía en pedazos. El recorrido consume todo y los cruces reales
    # quedan como puntas que _join vuelve a unir.
    count, labels = cv2.connectedComponents((skeleton > 0).astype(np.uint8), connectivity=8)
    paths = [path for k in range(1, count) for path in _trace(labels == k)]
    out = []
    for path in _join(paths):
        if len(path) < MIN_STROKE:
            continue
        simple = cv2.approxPolyDP(_smooth(path).astype(np.float32).reshape(-1, 1, 2), SIMPLIFY, False).reshape(-1, 2).astype(np.float64)
        if len(simple) >= 2:
            out.append(simple)
    return out


def holes_of(cell: np.ndarray) -> list[np.ndarray]:
    """Huecos oscuros encerrados por las líneas (sin los que tocan el borde de la celda)."""
    bright = cv2.cvtColor(cell, cv2.COLOR_BGR2HSV)[..., 2]
    dark = (bright <= BRIGHT).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=4)
    h, w = dark.shape
    out = []
    for k in range(1, count):
        x, y, bw, bh, area = stats[k]
        if area < 25 or x == 0 or y == 0 or x + bw >= w or y + bh >= h:
            continue
        contours, _ = cv2.findContours((labels == k).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        out.append(max(contours, key=cv2.contourArea)[:, 0, :].astype(np.float64))
    return out


def features(holes: list[np.ndarray]) -> dict[str, np.ndarray]:
    """Ojos, boca y nariz entre los huecos: los ojos son el par grande, parecido y a la misma altura,
    de la mitad de arriba; la boca, el más grande debajo de ellos; la nariz, el más chico entre
    ojos y boca."""
    info = [(h, cv2.contourArea(h.astype(np.float32)), h.mean(axis=0)) for h in holes]
    info = [i for i in info if i[1] > 0]
    best, best_score = None, None
    for a in range(len(info)):
        for b in range(a + 1, len(info)):
            (ha, aa, ca), (hb, ab, cb) = info[a], info[b]
            if min(aa, ab) / max(aa, ab) < 0.5:
                continue
            gap = abs(ca[0] - cb[0])
            if gap < 10 or abs(ca[1] - cb[1]) > 0.35 * gap:
                continue
            score = (aa + ab) - abs(ca[1] - cb[1]) * 5
            if best_score is None or score > best_score:
                best, best_score = (a, b), score
    if best is None:
        raise ValueError("No se encontraron dos ojos en el dibujo")
    eyes = sorted((info[best[0]], info[best[1]]), key=lambda i: i[2][0])
    out = {"eye_right": eyes[0][0], "eye_left": eyes[1][0]}  # la derecha de la persona, a la izquierda de la imagen
    eye_y = (eyes[0][2][1] + eyes[1][2][1]) / 2
    middle = (eyes[0][2][0] + eyes[1][2][0]) / 2
    gap = abs(eyes[1][2][0] - eyes[0][2][0])
    below = [i for k, i in enumerate(info) if k not in best and i[2][1] > eye_y and abs(i[2][0] - middle) < gap * 0.6]
    if below:
        mouth = max(below, key=lambda i: i[1])
        out["mouth"] = mouth[0]
        between = [i for i in below if i is not mouth and i[2][1] < mouth[2][1]]
        if between:
            out["nose"] = min(between, key=lambda i: i[1])[0]
    return out


def marked(marks: dict[str, list[float]]) -> dict[str, np.ndarray]:
    """Los rasgos de las marcas como óvalos (un poco más grandes: el trazo los rodea)."""
    t = np.linspace(0, 2 * np.pi, 28, endpoint=False)
    out = {}
    for role, (cx, cy, rx, ry) in marks.items():
        out[role] = np.stack([cx + max(rx, 0.5) * MARK_GROW * np.cos(t), cy + max(ry, 0.5) * MARK_GROW * np.sin(t)], axis=1)
    return out


def _roles(stroke: np.ndarray, parts: dict[str, np.ndarray]) -> list[tuple[str, np.ndarray]]:
    """El trazo cortado por rasgo: cada punto toma el rol del hueco que bordea (a menos de
    HOLE_NEAR) o `line`; las rachas cortas se pegan a la anterior para no partirlo en migas."""
    contours = {role: hole.astype(np.float32).reshape(-1, 1, 2) for role, hole in parts.items()}
    labels = []
    for x, y in stroke:
        best, best_d = "line", HOLE_NEAR
        for role, contour in contours.items():
            d = abs(cv2.pointPolygonTest(contour, (float(x), float(y)), True))
            if d <= best_d:
                best, best_d = role, d
        labels.append(best)
    runs: list[list] = []
    for k, label in enumerate(labels):
        if runs and runs[-1][0] == label:
            runs[-1][2] = k
        else:
            runs.append([label, k, k])
    merged: list[list] = []
    for run in runs:
        if merged and run[2] - run[1] < 2:  # una racha de uno o dos puntos sigue a la anterior
            merged[-1][2] = run[2]
        elif merged and merged[-1][0] == run[0]:
            merged[-1][2] = run[2]
        else:
            merged.append(run)
    # Cada tramo comparte su punto de unión con el siguiente: la línea no queda cortada.
    return [(label, stroke[a : min(b + 2, len(stroke))]) for label, a, b in merged if min(b + 2, len(stroke)) - a >= 2]


def _color(cell: np.ndarray, stroke: np.ndarray) -> list[float]:
    """El color del trazo en el dibujo (RGB 0-1, llevado a su máximo: el neón sin el halo)."""
    h, w = cell.shape[:2]
    pts = np.clip(np.round(stroke).astype(int), [0, 0], [w - 1, h - 1])
    bgr = cell[pts[:, 1], pts[:, 0]].astype(np.float64).mean(axis=0)
    rgb = bgr[::-1] / max(float(bgr.max()), 1.0)
    return [round(float(v), 3) for v in rgb]


def extract(number: int, grid: Path = GRID) -> dict:
    """La máscara vectorial de la celda `number`: trazos con rol y color, en coordenadas de cara."""
    index = load_index()
    entry = next(e for e in index["faces"] if e["n"] == number)
    cell = cell_image(number, grid)
    marks = entry.get("marks")
    parts = marked(marks) if marks else features(holes_of(cell))
    centers = {k: v.mean(axis=0) for k, v in parts.items()}
    origin = (centers["eye_right"] + centers["eye_left"]) / 2
    unit = float(np.linalg.norm(centers["eye_left"] - centers["eye_right"]))

    def local(points: np.ndarray) -> list[list[float]]:
        return [[round(float(x), 4), round(float(y), 4)] for x, y in (points - origin) / unit]

    strokes = []
    for stroke in strokes_of(cell):
        for role, piece in _roles(stroke, parts):
            strokes.append({"role": role, "color": _color(cell, piece), "points": local(piece)})
    anchors = {k: [round(float(v[0]), 4), round(float(v[1]), 4)] for k, v in ((k, (c - origin) / unit) for k, c in centers.items())}
    holes = {role: local(cv2.approxPolyDP(hole.astype(np.float32).reshape(-1, 1, 2), 1.0, True).reshape(-1, 2)) for role, hole in parts.items()}
    if "mouth" in parts:
        top = parts["mouth"][:, 1].min()
        anchors["mouth_top"] = [anchors["mouth"][0], round(float((top - origin[1]) / unit), 4)]
        anchors["jaw_rest"] = LONG_MOUTH_REST if anchors["mouth"][1] > LONG_MOUTH else 1.0
    return {"id": entry["id"], "name": entry["name"], "source": f"halloween_grid celda {number}", "anchors": anchors, "holes": holes, "strokes": strokes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--cell", type=int, required=True, help="número del rostro en la cuadrícula (1-24)")
    args = parser.parse_args()
    mask = extract(args.cell)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{mask['id']}.yaml"
    path.write_text(yaml.safe_dump(mask, allow_unicode=True, sort_keys=False, default_flow_style=None), encoding="utf-8")
    roles = {}
    for stroke in mask["strokes"]:
        roles[stroke["role"]] = roles.get(stroke["role"], 0) + 1
    print(f"{path}: {len(mask['strokes'])} trazos {roles}")


if __name__ == "__main__":
    main()
