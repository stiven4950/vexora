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


def match_lines(src: list[np.ndarray], dst: list[np.ndarray], t: float, n: int = SAMPLES) -> list[tuple[np.ndarray, int, int]]:
    """Como `morph_lines`, pero cada línea viaja a la más cercana del dibujo nuevo (por su centro), no a
    la del mismo orden: entre efectos distintos el orden no dice nada y los ojos cruzaban la cara. Una
    línea se recorre al revés si así viaja menos (no se retuerce). Las líneas de origen que sobran se
    funden con la de destino más cercana. Devuelve (línea, índice de origen, índice de destino)."""
    t = ease(t)
    if not src or not dst:
        return [(c, -1, k) for k, c in enumerate(dst)] if t >= 1.0 else []
    a_lines = [resample(c, n) for c in src]
    b_lines = [resample(c, n) for c in dst]
    a_mid = np.array([c.mean(axis=0) for c in a_lines])
    b_mid = np.array([c.mean(axis=0) for c in b_lines])
    dist = np.linalg.norm(a_mid[:, None, :] - b_mid[None, :, :], axis=2)
    pairs: list[tuple[int, int]] = []
    free_src, free_dst = set(range(len(src))), set(range(len(dst)))
    for i, j in sorted(np.ndindex(dist.shape), key=lambda ij: dist[ij]):  # primero las parejas más cercanas
        if i in free_src and j in free_dst:
            pairs.append((i, j))
            free_src.discard(i)
            free_dst.discard(j)
    pairs += [(int(np.argmin(dist[:, j])), j) for j in sorted(free_dst)]  # destino sin pareja: de la más cercana
    pairs += [(i, int(np.argmin(dist[i]))) for i in sorted(free_src)]  # origen que sobra: se funde
    out = []
    for i, j in pairs:
        a, b = a_lines[i], b_lines[j]
        if np.linalg.norm(a - b[::-1]) < np.linalg.norm(a - b):
            b = b[::-1]
        out.append((a + (b - a) * t, i, j))
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
