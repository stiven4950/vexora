"""Convertir unas líneas en otras: el dibujo de un efecto se vuelve el del siguiente.

Lo pidió el usuario al explicar video_52 (docs/referencias/video_52.md): los cuernos se aplastan en
corchetes, se juntan en una "V", bajan a los ojos y se vuelven ojos en X; las cintas se vuelven un
moño y el moño un reloj; la luna, una paloma y la paloma, el wifi. En vez de apagar un dibujo y
encender otro, cada línea viaja a su lugar en el dibujo nuevo.

`morph_lines(origen, destino, t)` empareja las líneas en orden (si un dibujo tiene menos líneas, las
suyas se reparten entre las del otro), las remuestrea al mismo número de puntos a lo largo y las
mezcla con `t` (0 = origen, 1 = destino), con aceleración suave.
"""

from __future__ import annotations

import numpy as np

SAMPLES = 36


def resample(line: np.ndarray, n: int = SAMPLES) -> np.ndarray:
    """La línea con `n` puntos repartidos por igual a lo largo de su recorrido."""
    line = np.asarray(line, dtype=np.float64)
    if len(line) == 1:
        return np.repeat(line, n, axis=0)
    seg = np.linalg.norm(np.diff(line, axis=0), axis=1)
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    if acc[-1] < 1e-9:
        return np.repeat(line[:1], n, axis=0)
    u = np.linspace(0.0, acc[-1], n)
    return np.stack([np.interp(u, acc, line[:, 0]), np.interp(u, acc, line[:, 1])], axis=1)


def ease(t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    return t * t * (3 - 2 * t)


def morph_lines(src: list[np.ndarray], dst: list[np.ndarray], t: float, n: int = SAMPLES) -> list[np.ndarray]:
    """Las líneas a mitad de camino entre `src` y `dst` (t de 0 a 1)."""
    t = ease(t)
    if not src:
        return list(dst) if t >= 1.0 else []
    if not dst:
        return list(src) if t <= 0.0 else []
    if t <= 0.0:
        return list(src)
    if t >= 1.0:
        return list(dst)
    count = max(len(src), len(dst))
    out = []
    for k in range(count):
        a = resample(src[k * len(src) // count], n)
        b = resample(dst[k * len(dst) // count], n)
        out.append(a + (b - a) * t)
    return out


def chain(stages: list[tuple[float, list[np.ndarray]]], u: float, blend: float = 0.5) -> tuple[list[np.ndarray], int]:
    """Una secuencia de dibujos: `stages` = [(desde_u, líneas), ...] en orden. Cada dibujo se
    sostiene y, en la última fracción `blend` de su tramo, se convierte en el siguiente.
    Devuelve (líneas, índice del dibujo en curso)."""
    for k in range(len(stages) - 1, -1, -1):
        if u >= stages[k][0]:
            break
    else:
        return list(stages[0][1]), 0
    if k == len(stages) - 1:
        return list(stages[k][1]), k
    start, nxt = stages[k][0], stages[k + 1][0]
    turn = nxt - (nxt - start) * blend
    if u < turn:
        return list(stages[k][1]), k
    return morph_lines(stages[k][1], stages[k + 1][1], (u - turn) / max(nxt - turn, 1e-6)), k
