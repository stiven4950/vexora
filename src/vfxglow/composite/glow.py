"""Bloom separable sobre la capa de efecto, nunca sobre el plano original."""

from __future__ import annotations

import cv2
import numpy as np


def _odd(radius: float) -> int:
    return max(3, int(max(1.0, round(radius))) * 2 + 1)


_PASSES: tuple[tuple[float, float], ...] = ((1.0, 0.7), (2.5, 0.4), (6.0, 0.18))


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
    for scale, fade in _PASSES[: max(1, min(layers, 3))]:
        sigma = max(radius * 0.35 * scale, 0.5)
        k = _odd(radius * scale)
        blurred = cv2.GaussianBlur(bright, (k, k), sigmaX=sigma, sigmaY=sigma)
        acc = acc + blurred * np.float32(intensity * fade)
        spill = np.maximum(spill, np.clip(blurred.max(axis=-1) * intensity * fade, 0.0, 1.0))
    out[..., :3] = acc
    out[..., 3] = np.maximum(out[..., 3], spill)
    return out
