"""Curvas compartidas: Catmull-Rom centrípeta y Ramer–Douglas–Peucker."""

from __future__ import annotations

import numpy as np


def rdp(points: np.ndarray, epsilon: float) -> np.ndarray:
    """Simplifica una polilínea. `points` tiene forma (N, 2)."""
    if len(points) < 3:
        return np.asarray(points, dtype=np.float64)
    start = points[0]
    end = points[-1]
    segment = end - start
    length = float(np.linalg.norm(segment))
    if length < 1e-9:
        dists = np.linalg.norm(points - start, axis=1)
    else:
        rel = points - start
        dists = np.abs(rel[:, 0] * segment[1] - rel[:, 1] * segment[0]) / length
    index = int(np.argmax(dists))
    if dists[index] > epsilon:
        left = rdp(points[: index + 1], epsilon)
        right = rdp(points[index:], epsilon)
        return np.vstack([left[:-1], right])
    return np.vstack([start, end])


def _segment(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, count: int, alpha: float = 0.5) -> np.ndarray:
    def knot(ti: float, a: np.ndarray, b: np.ndarray) -> float:
        dist = float(np.linalg.norm(b - a))
        return ti + max(dist, 1e-4) ** alpha

    t0 = 0.0
    t1 = knot(t0, p0, p1)
    t2 = knot(t1, p1, p2)
    t3 = knot(t2, p2, p3)
    if abs(t2 - t1) < 1e-8:
        return np.repeat(p1[None, :], count, axis=0)
    ts = np.linspace(t1, t2, count, endpoint=False)
    out = np.empty((count, p0.shape[0]), dtype=np.float64)
    for i, t in enumerate(ts):
        a1 = _lerp(p0, p1, t, t0, t1)
        a2 = _lerp(p1, p2, t, t1, t2)
        a3 = _lerp(p2, p3, t, t2, t3)
        b1 = _lerp(a1, a2, t, t0, t2)
        b2 = _lerp(a2, a3, t, t1, t3)
        out[i] = _lerp(b1, b2, t, t1, t2)
    return out


def _lerp(a: np.ndarray, b: np.ndarray, t: float, t0: float, t1: float) -> np.ndarray:
    denom = t1 - t0
    if abs(denom) < 1e-8:
        return a
    w = (t - t0) / denom
    return (1.0 - w) * a + w * b


def catmull_rom(points: np.ndarray, samples_per_seg: int = 8) -> np.ndarray:
    """Centripeta. Atraviesa los puntos de control sin sobrepasar en gestos bruscos."""
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 2:
        return pts.copy()
    if len(pts) == 2:
        t = np.linspace(0.0, 1.0, samples_per_seg)[:, None]
        return (1.0 - t) * pts[0] + t * pts[1]
    padded = np.vstack([pts[0], pts, pts[-1]])
    chunks: list[np.ndarray] = []
    last = len(padded) - 3
    for i in range(1, last + 1):
        count = samples_per_seg + (1 if i == last else 0)
        seg = _segment(padded[i - 1], padded[i], padded[i + 1], padded[i + 2], count)
        if i == last:
            seg = np.vstack([seg, pts[-1]])
        chunks.append(seg)
    return np.vstack(chunks)


def normals(points: np.ndarray) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    if len(pts) < 2:
        return np.zeros_like(pts)
    delta = np.gradient(pts, axis=0)
    norm = np.maximum(np.linalg.norm(delta, axis=1, keepdims=True), 1e-6)
    delta = delta / norm
    return np.stack([-delta[:, 1], delta[:, 0]], axis=1)
