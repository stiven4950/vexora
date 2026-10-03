"""Color lineal y rodilla suave para que el fuego aditivo no recorte a blanco."""

from __future__ import annotations

import numpy as np


def srgb_to_linear(values: np.ndarray) -> np.ndarray:
    c = values.astype(np.float32, copy=False)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(values: np.ndarray) -> np.ndarray:
    c = np.clip(values.astype(np.float32, copy=False), 0.0, None)
    encoded = np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)
    return np.clip(encoded, 0.0, 1.0).astype(np.float32)


def shoulder(values: np.ndarray, threshold: float) -> np.ndarray:
    """Identidad por debajo del umbral. Por encima, comprime con derivada continua."""
    x = values.astype(np.float32, copy=False)
    if threshold <= 0:
        return (x / (1.0 + np.maximum(x, 0.0))).astype(np.float32)
    hi = np.maximum(x - threshold, 0.0)
    return (np.minimum(x, threshold) + hi / (1.0 + hi)).astype(np.float32)
