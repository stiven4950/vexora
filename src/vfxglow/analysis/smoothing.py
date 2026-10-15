"""Suavizado temporal: huecos cortos con Catmull-Rom y One Euro por punto."""

from __future__ import annotations

import math

import numpy as np

from vfxglow.config import OneEuroConfig


class OneEuroFilter:
    """Filtro One Euro causal. En reposo aplasta el jitter; en un gesto rápido reduce el retardo."""

    def __init__(self, freq: float, min_cutoff: float, beta: float, d_cutoff: float) -> None:
        self.freq = max(freq, 1e-3)
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_prev: float | None = None
        self.dx_prev: float = 0.0

    def reset(self) -> None:
        self.x_prev = None
        self.dx_prev = 0.0

    def _alpha(self, cutoff: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
        te = 1.0 / self.freq
        return 1.0 / (1.0 + tau / te)

    def __call__(self, x: float) -> float:
        if self.x_prev is None:
            self.x_prev = x
            self.dx_prev = 0.0
            return x
        dx = (x - self.x_prev) * self.freq
        alpha_d = self._alpha(self.d_cutoff)
        dx_hat = alpha_d * dx + (1.0 - alpha_d) * self.dx_prev
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        alpha = self._alpha(cutoff)
        x_hat = alpha * x + (1.0 - alpha) * self.x_prev
        self.x_prev = x_hat
        self.dx_prev = dx_hat
        return x_hat


def catmull_uniform(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    """Catmull-Rom uniforme. El tiempo entre fotogramas ya es regular, así que el parámetro es t."""
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * t
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * t2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * t3
    )


def fill_short_gaps(values: np.ndarray, valid: np.ndarray, max_gap: int) -> tuple[np.ndarray, np.ndarray]:
    """Rellena huecos de hasta `max_gap` fotogramas. Un hueco más largo se queda inválido."""
    out = values.astype(np.float64).copy()
    mask = valid.astype(bool).copy()
    n = len(out)
    i = 0
    while i < n:
        if mask[i]:
            i += 1
            continue
        start = i
        while i < n and not mask[i]:
            i += 1
        gap = i - start
        left = start - 1
        right = i
        if gap <= max_gap and left >= 0 and right < n and mask[left] and mask[right]:
            p0 = out[left - 1] if left - 1 >= 0 and mask[left - 1] else out[left]
            p1 = out[left]
            p2 = out[right]
            p3 = out[right + 1] if right + 1 < n and mask[right + 1] else out[right]
            for k, t in enumerate(np.linspace(0.0, 1.0, gap + 2)[1:-1]):
                out[left + 1 + k] = catmull_uniform(float(p0), float(p1), float(p2), float(p3), float(t))
                mask[left + 1 + k] = True
    return out, mask


def reject_jumps(values: np.ndarray, valid: np.ndarray, max_jump: float, max_gap: int) -> np.ndarray:
    """Invalida saltos imposibles del tracker.

    Una muestra que se aleja más de `max_jump` de la última muestra buena se descarta.
    Si el salto persiste más de `max_gap` fotogramas, la nueva posición se acepta
    como línea base: el actor sí se movió, o el tracker cambió de persona y no
    hay forma de recuperar la anterior.
    """
    if max_jump <= 0:
        return valid.astype(bool).copy()
    out = valid.astype(bool).copy()
    last: float | None = None
    rejected = 0
    for i in range(len(values)):
        if not out[i] or not np.isfinite(values[i]):
            continue
        if last is not None and abs(float(values[i]) - last) > max_jump:
            rejected += 1
            if rejected <= max_gap:
                out[i] = False
                continue
        rejected = 0
        last = float(values[i])
    return out


def smooth_series(
    values: np.ndarray,
    confidence: np.ndarray,
    fps: float,
    min_confidence: float,
    max_gap: int,
    euro: OneEuroConfig,
    max_jump: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve la serie filtrada y la máscara de muestras utilizables."""
    valid = confidence >= min_confidence
    valid = reject_jumps(values, valid, max_jump, max_gap)
    filled, valid = fill_short_gaps(values, valid, max_gap)
    out = np.full(len(values), np.nan, dtype=np.float64)
    usable = valid & np.isfinite(filled)
    # El análisis no es en vivo: cada tramo se filtra hacia adelante y hacia atrás y se promedia,
    # así el retardo de una pasada se cancela con el adelanto de la otra (la cabeza de video_35
    # quedaba hasta 170 px detrás con una sola pasada).
    i = 0
    while i < len(filled):
        if not usable[i]:
            i += 1
            continue
        start = i
        while i < len(filled) and usable[i]:
            i += 1
        segment = filled[start:i]
        ahead = OneEuroFilter(fps, euro.min_cutoff, euro.beta, euro.d_cutoff)
        behind = OneEuroFilter(fps, euro.min_cutoff, euro.beta, euro.d_cutoff)
        forward = np.array([ahead(float(v)) for v in segment])
        backward = np.array([behind(float(v)) for v in segment[::-1]])[::-1]
        out[start:i] = (forward + backward) / 2.0
    return out, valid
