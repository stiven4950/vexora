"""Etiquetas como cajas rotadas (OBB) y su conversión a segmentos de hoja.

Una caja rotada no distingue extremos: sirve igual para una foto de una espada colgada que para
un video. La empuñadura se decide después, por cercanía a la mano.
"""

from __future__ import annotations

import numpy as np

# Ancho de la caja relativo al largo de la hoja cuando no se puede medir.
WIDTH_RATIO = 1 / 16
MIN_WIDTH = 4.0


def segment_to_obb(a: np.ndarray, b: np.ndarray, width: float | None = None) -> np.ndarray:
    """Cuatro esquinas (px) de la caja rotada que envuelve el segmento a-b."""
    d = np.asarray(b, dtype=np.float64) - np.asarray(a, dtype=np.float64)
    length = float(np.linalg.norm(d))
    if length < 1e-6:
        raise ValueError("Segmento de largo cero")
    u = d / length
    n = np.array([-u[1], u[0]])
    half = max(width if width is not None else length * WIDTH_RATIO, MIN_WIDTH) / 2
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return np.stack([a + n * half, b + n * half, b - n * half, a - n * half])


def obb_to_segment(corners: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Eje largo de una caja rotada: los puntos medios de sus dos lados cortos."""
    c = np.asarray(corners, dtype=np.float64).reshape(4, 2)
    sides = [(c[i], c[(i + 1) % 4]) for i in range(4)]
    lengths = [float(np.linalg.norm(q - p)) for p, q in sides]
    short = int(np.argmin(lengths[:2]))  # lados 0/2 y 1/3 son paralelos
    p0, q0 = sides[short]
    p1, q1 = sides[short + 2]
    return (p0 + q0) / 2, (p1 + q1) / 2


def yolo_obb_line(class_id: int, corners: np.ndarray, width: int, height: int) -> str:
    """Una línea del formato YOLO-OBB: clase y 4 esquinas normalizadas."""
    norm = np.clip(np.asarray(corners, dtype=np.float64) / [width, height], 0.0, 1.0)
    return f"{class_id} " + " ".join(f"{v:.6f}" for v in norm.reshape(-1))
