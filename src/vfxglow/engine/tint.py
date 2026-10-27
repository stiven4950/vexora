"""Color y tamaño que la persona elige en el editor para una pista (director/edits.py).

Se aplican a la capa ya dibujada de cada efecto, así que valen para cualquier tipo (el agua, el
fuego, el aire y la tierra pintan con paletas propias y no leen `style.colors`):

- `recolor`: lleva la capa a un color conservando su luminosidad; lo casi blanco (el núcleo
  caliente del fuego, el brillo del agua) sigue blanco, como en un efecto de ese color.
- `scale_about`: agranda o achica la capa alrededor de un punto (el ancla del efecto).
"""

from __future__ import annotations

import cv2
import numpy as np

LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


def recolor(layer: np.ndarray, tint: tuple[float, float, float]) -> np.ndarray:
    """La capa RGBA (energía lineal) teñida de `tint`, con la misma luminosidad por píxel."""
    color = np.asarray(tint, np.float32)
    luma_tint = float(color @ LUMA)
    if luma_tint <= 1e-6:
        return layer
    # Solo el rectángulo donde hay algo dibujado: la capa es del tamaño del cuadro y el efecto
    # suele ocupar una parte. El rectángulo se busca en el alfa reducido 8 veces con promedio de
    # área (un trazo de un píxel deja el bloque por encima de cero, no se pierde) y se agranda un
    # bloque por lado. Se tiñe en sitio: la capa es del fotograma, nadie más la usa.
    step = 8
    height, width = layer.shape[:2]
    coarse = cv2.resize(np.ascontiguousarray(layer[..., 3]), (max(width // step, 1), max(height // step, 1)), interpolation=cv2.INTER_AREA)
    painted = coarse > 0
    if not painted.any():
        return layer
    x, y, w, h = cv2.boundingRect(painted.astype(np.uint8))
    x0, y0 = max((x - 1) * step, 0), max((y - 1) * step, 0)
    x1, y1 = min((x + w + 1) * step, width), min((y + h + 1) * step, height)
    layer[y0:y1, x0:x1] = _recolor_region(layer[y0:y1, x0:x1], color, luma_tint)
    return layer


def _recolor_region(layer: np.ndarray, color: np.ndarray, luma_tint: float) -> np.ndarray:
    rgb = layer[..., :3]
    luma = rgb @ LUMA
    peak = rgb.max(axis=-1)
    # Cuánto de "blanco" tiene el píxel: 1 en lo neutro (núcleo), 0 en lo saturado.
    white = np.where(peak > 1e-6, rgb.min(axis=-1) / np.maximum(peak, 1e-6), 0.0)[..., None]
    tinted = luma[..., None] * (color / luma_tint)
    out = layer.copy()
    out[..., :3] = tinted * (1.0 - white) + luma[..., None] * white
    return out


def scale_about(layer: np.ndarray, factor: float, center: tuple[float, float]) -> np.ndarray:
    """La capa escalada `factor` veces alrededor de `center` (píxeles)."""
    if abs(factor - 1.0) < 1e-3:
        return layer
    cx, cy = center
    matrix = np.array([[factor, 0.0, (1.0 - factor) * cx], [0.0, factor, (1.0 - factor) * cy]], np.float32)
    height, width = layer.shape[:2]
    return cv2.warpAffine(layer, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
