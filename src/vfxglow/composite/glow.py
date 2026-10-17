"""Bloom separable sobre la capa de efecto, nunca sobre el plano original."""

from __future__ import annotations

import cv2
import numpy as np


def _odd(radius: float) -> int:
    return max(3, int(max(1.0, round(radius))) * 2 + 1)


# Las dos últimas (12x y 24x) dan la caída larga tipo "Deep Glow"; solo las usa quien pide
# glow_layers 4-5 (el estilo Avatar) y se calculan a 1/4 de resolución.
_PASSES: tuple[tuple[float, float], ...] = ((1.0, 0.7), (2.5, 0.4), (6.0, 0.18), (12.0, 0.1), (24.0, 0.06))


def bloom(
    layer: np.ndarray,
    radius: float,
    threshold: float,
    intensity: float,
    layers: int = 2,
) -> np.ndarray:
    """Suma uno a tres halos con radios 1x, 2.5x y 6x. El alfa crece con el derrame."""
    if intensity <= 0 or radius <= 0:
        return layer
    out = layer.copy()
    rgb = out[..., :3]
    luma = rgb.max(axis=-1)
    weight = np.clip((luma - np.float32(threshold)) / np.float32(max(threshold, 1e-3)), 0.0, 1.0)
    bright = rgb * weight[..., None]
    spill = np.zeros(luma.shape, dtype=np.float32)
    acc = rgb.copy()
    height, width = luma.shape
    for scale, fade in _PASSES[: max(1, min(layers, len(_PASSES)))]:
        sigma = max(radius * 0.35 * scale, 0.5)
        if scale >= 12.0:  # halo enorme: a 1/4 de resolución y de vuelta
            small = cv2.resize(bright, (max(width // 4, 1), max(height // 4, 1)), interpolation=cv2.INTER_AREA)
            k = _odd(radius * scale / 4)
            blurred = cv2.resize(cv2.GaussianBlur(small, (k, k), sigmaX=sigma / 4, sigmaY=sigma / 4), (width, height), interpolation=cv2.INTER_LINEAR)
        else:
            k = _odd(radius * scale)
            blurred = cv2.GaussianBlur(bright, (k, k), sigmaX=sigma, sigmaY=sigma)
        acc = acc + blurred * np.float32(intensity * fade)
        spill = np.maximum(spill, np.clip(blurred.max(axis=-1) * intensity * fade, 0.0, 1.0))
    out[..., :3] = acc
    out[..., 3] = np.maximum(out[..., 3], spill)
    return out
