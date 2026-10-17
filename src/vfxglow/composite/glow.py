"""Bloom separable sobre la capa de efecto, nunca sobre el plano original."""

from __future__ import annotations

import cv2
import numpy as np


def _odd(radius: float) -> int:
    return max(3, int(max(1.0, round(radius))) * 2 + 1)


# Las dos últimas (12x y 24x) dan la caída larga tipo "Deep Glow"; solo las usa quien pide
# glow_layers 4-5 (el estilo Avatar) y se calculan a 1/4 de resolución.
_PASSES: tuple[tuple[float, float], ...] = ((1.0, 0.7), (2.5, 0.4), (6.0, 0.18), (12.0, 0.1), (24.0, 0.06))
WIDE = 12.0


def _bright(rgb: np.ndarray, threshold: float) -> tuple[np.ndarray, np.ndarray]:
    luma = rgb.max(axis=-1)
    weight = np.clip((luma - np.float32(threshold)) / np.float32(max(threshold, 1e-3)), 0.0, 1.0)
    return rgb * weight[..., None], luma


def bloom(
    layer: np.ndarray,
    radius: float,
    threshold: float,
    intensity: float,
    layers: int = 2,
) -> np.ndarray:
    """Suma halos con radios 1x, 2,5x y 6x (y 12x, 24x si se piden). El alfa crece con el derrame.

    Los halos cercanos se calculan solo en el recuadro con efecto (más su alcance) y los lejanos
    sobre el cuadro reducido a 1/4: casi todas las capas cubren una parte chica del cuadro y
    hacerlo sobre el cuadro entero llegaba a ser el 60% del render (video_18)."""
    if intensity <= 0 or radius <= 0:
        return layer
    height, width = layer.shape[:2]
    # El halo solo nace de lo que pasa el umbral (el fuego, el núcleo del neón), no del resplandor
    # tenue alrededor, que puede cubrir casi todo el cuadro.
    ys, xs = np.nonzero(layer[..., :3].max(axis=-1) > threshold)
    if len(xs) == 0:
        return layer
    passes = _PASSES[: max(1, min(layers, len(_PASSES)))]
    near = [p for p in passes if p[0] < WIDE]
    far = [p for p in passes if p[0] >= WIDE]
    out = layer.copy()
    reach = int(radius * max(scale for scale, _ in near) * 1.2) + 4
    x0, x1 = max(xs.min() - reach, 0), min(xs.max() + reach + 1, width)
    y0, y1 = max(ys.min() - reach, 0), min(ys.max() + reach + 1, height)
    crop = out[y0:y1, x0:x1]
    rgb = crop[..., :3]
    bright, _luma = _bright(rgb, threshold)
    acc = rgb.copy()
    spill = np.zeros(rgb.shape[:2], dtype=np.float32)
    for scale, fade in near:
        sigma = max(radius * 0.35 * scale, 0.5)
        k = _odd(radius * scale)
        blurred = cv2.GaussianBlur(bright, (k, k), sigmaX=sigma, sigmaY=sigma)
        acc += blurred * np.float32(intensity * fade)
        spill = np.maximum(spill, np.clip(blurred.max(axis=-1) * intensity * fade, 0.0, 1.0))
    crop[..., :3] = acc
    crop[..., 3] = np.maximum(crop[..., 3], spill)
    if far:  # halos enormes: a 1/4 de resolución sobre todo el cuadro
        small = cv2.resize(layer[..., :3], (max(width // 4, 1), max(height // 4, 1)), interpolation=cv2.INTER_AREA)
        bright_small, _ = _bright(small, threshold)
        glow = np.zeros_like(small)
        far_spill = np.zeros(small.shape[:2], dtype=np.float32)
        for scale, fade in far:
            sigma = max(radius * 0.35 * scale / 4, 0.5)
            k = _odd(radius * scale / 4)
            blurred = cv2.GaussianBlur(bright_small, (k, k), sigmaX=sigma, sigmaY=sigma)
            glow += blurred * np.float32(intensity * fade)
            far_spill = np.maximum(far_spill, np.clip(blurred.max(axis=-1) * intensity * fade, 0.0, 1.0))
        out[..., :3] += cv2.resize(glow, (width, height), interpolation=cv2.INTER_LINEAR)
        out[..., 3] = np.maximum(out[..., 3], cv2.resize(far_spill, (width, height), interpolation=cv2.INTER_LINEAR))
    return out
