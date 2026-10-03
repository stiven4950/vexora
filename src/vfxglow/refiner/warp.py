"""Deforma una capa con el flujo del plano. No toca el fotograma original."""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.analysis.flow import resize_flow


def warp_image(image: np.ndarray, flow: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    field = resize_flow(flow, width, height)
    grid_x, grid_y = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    # Flujo de prev a curr: el contenido que estaba en x ahora está en x + flow.
    map_x = np.ascontiguousarray((grid_x - field[..., 0]).astype(np.float32))
    map_y = np.ascontiguousarray((grid_y - field[..., 1]).astype(np.float32))
    return cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def alpha_mask(alpha: np.ndarray, dilate_px: int, thresh: float = 0.08) -> np.ndarray:
    mask = (alpha > thresh).astype(np.uint8) * 255
    if dilate_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (dilate_px * 2 + 1, dilate_px * 2 + 1))
        mask = cv2.dilate(mask, kernel)
    return mask
