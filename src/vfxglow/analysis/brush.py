"""El pincel (referencia video_2): mango de color saturado, largo y fino; la punta es el final de
la virola (dorada o gris) y las cerdas oscuras, más allá del extremo del mango que apunta a la cara.

Sirve para las líneas finas: el trazo que se ilumina es la pintura nueva junto a la punta.
"""

from __future__ import annotations

import cv2
import numpy as np

# Mango: tono (OpenCV 0-180) azul verdoso, saturado y no oscuro; alargado.
HUE = (80, 115)
MIN_SAT = 90
MIN_VAL = 60
MIN_LENGTH = 40  # px a la resolución de trabajo (360 x 640)
MIN_ELONGATION = 5.0
# Más allá del mango: hasta esta fracción de su largo se buscan la virola y las cerdas.
REACH = 0.45


def find_brush(small_bgr: np.ndarray, face_center: np.ndarray | None) -> tuple[np.ndarray, np.ndarray] | None:
    """(punta, dirección hacia la punta) en píxeles de `small_bgr`, o None."""
    hsv = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    mask = ((h >= HUE[0]) & (h <= HUE[1]) & (s > MIN_SAT) & (v > MIN_VAL)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    best = None
    for k in range(1, count):
        if stats[k, 4] < 40:
            continue
        ys, xs = np.nonzero(labels == k)
        pts = np.stack([xs, ys], axis=1).astype(np.float32)
        (_, _), (a, b), _ = cv2.minAreaRect(pts)
        length, width = max(a, b), max(min(a, b), 1.0)
        if length < MIN_LENGTH or length / width < MIN_ELONGATION:
            continue
        if best is None or length > best[0]:
            best = (length, pts)
    if best is None:
        return None
    length, pts = best
    mean = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - mean, full_matrices=False)
    axis = vt[0]
    proj = (pts - mean) @ axis
    ends = (mean + axis * proj.min(), mean + axis * proj.max())
    target = face_center if face_center is not None else np.array([small_bgr.shape[1] / 2, small_bgr.shape[0] / 3])
    end = min(ends, key=lambda e: float(np.linalg.norm(e - target)))
    direction = (end - mean) / max(float(np.linalg.norm(end - mean)), 1e-6)
    # Caminar desde el final del mango mientras haya virola o cerdas (poco saturado u oscuro).
    tip = end
    gray = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2GRAY)
    misses = 0
    for step in range(1, int(length * REACH)):
        x, y = (end + direction * step).astype(int)
        if not (0 <= x < gray.shape[1] and 0 <= y < gray.shape[0]):
            break
        window = hsv[max(y - 1, 0) : y + 2, max(x - 1, 0) : x + 2].reshape(-1, 3)
        dark = window[:, 2] < 80  # cerdas
        metal = (window[:, 0] >= 18) & (window[:, 0] <= 40) & (window[:, 1] > 50) & (window[:, 2] > 90)  # virola
        tool = (dark | metal).any()
        if tool:
            tip = end + direction * step
            misses = 0
        else:
            misses += 1
            if misses > 3:
                break
    return tip, direction
