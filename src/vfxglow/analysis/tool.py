"""La herramienta que pinta (pincel, esponja, lápiz, dedo), sin suponer su color.

Se trabaja con fotogramas alineados a la cara (analysis/paint.py): ahí la cara queda quieta y lo
que se mueve es la mano y la herramienta. La pieza móvil más grande que entra en la cara es la
herramienta con la mano; su punta es el punto de esa pieza, dentro de la cara, más lejos de por
donde entra (el lado de la mano). Si la alineación falla un fotograma, casi toda la cara "se
mueve": ese fotograma se descarta.
"""

from __future__ import annotations

import cv2
import numpy as np

MOVE = 30  # diferencia (0-255, canal máximo) que cuenta como movimiento
MIN_PIXELS = 60
MAX_MOVING_SHARE = 0.35  # más de esto de la cara en movimiento = alineación fallida


def tool_tip(previous: np.ndarray, current: np.ndarray, region: np.ndarray) -> np.ndarray | None:
    """Punta de la herramienta en coordenadas de la cara, o None."""
    diff = np.abs(current.astype(np.int16) - previous.astype(np.int16)).max(axis=2)
    moving = (diff > MOVE).astype(np.uint8)
    moving = cv2.morphologyEx(moving, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    if (moving.astype(bool) & region).sum() > MAX_MOVING_SHARE * region.sum():
        return None
    count, labels, stats, _ = cv2.connectedComponentsWithStats(moving)
    best = None
    for k in range(1, count):
        if stats[k, 4] < MIN_PIXELS:
            continue
        piece = labels == k
        inside = piece & region
        if not inside.any():
            continue
        if best is None or stats[k, 4] > best[0]:
            best = (stats[k, 4], piece, inside)
    if best is None:
        return None
    _, piece, inside = best
    ys, xs = np.nonzero(piece & ~region)
    entry = np.array([xs.mean(), ys.mean()]) if len(xs) else np.array([region.shape[1] / 2, float(region.shape[0])])
    ys, xs = np.nonzero(inside)
    far = int(np.argmax((xs - entry[0]) ** 2 + (ys - entry[1]) ** 2))
    return np.array([xs[far], ys[far]], dtype=np.float64)
