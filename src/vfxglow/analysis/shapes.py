"""La figura geométrica que más se parece a un contorno (criterio de video_2: con la pintura se
juega con los contornos; primero la figura que mejor se aproxima y sobre ella se itera).

fit_shape prueba triángulo, elipse, rectángulo girado y círculo, mide el parecido de cada uno con
el contorno (intersección sobre unión de las áreas) y se queda con el mejor. Los efectos trabajan
sobre esa figura limpia (sus vértices o sus parámetros), no sobre el borde irregular.
"""

from __future__ import annotations

import cv2
import numpy as np

KINDS = ("triangle", "ellipse", "rectangle", "circle")


def _iou(contour: np.ndarray, shape: np.ndarray, size: tuple[int, int], offset: np.ndarray) -> float:
    a = np.zeros(size, np.uint8)
    b = np.zeros(size, np.uint8)
    cv2.fillPoly(a, [(contour - offset).astype(np.int32)], 1)
    cv2.fillPoly(b, [(shape - offset).astype(np.int32)], 1)
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def shape_points(shape: dict, count: int = 64) -> np.ndarray:
    """Contorno de la figura con `count` puntos repartidos por longitud de arco."""
    if shape["kind"] in ("ellipse", "circle"):
        (cx, cy), (w, h), angle = shape["center"], shape["axes"], shape["angle"]
        t = np.linspace(0, 2 * np.pi, count, endpoint=False)
        a = np.radians(angle)
        x, y = w / 2 * np.cos(t), h / 2 * np.sin(t)
        return np.stack([cx + x * np.cos(a) - y * np.sin(a), cy + x * np.sin(a) + y * np.cos(a)], axis=1)
    vertices = np.array(shape["vertices"], dtype=np.float64)
    closed = np.vstack([vertices, vertices[:1]])
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], count, endpoint=False)
    return np.stack([np.interp(t, arc, closed[:, 0]), np.interp(t, arc, closed[:, 1])], axis=1)


def fit_shape(contour: np.ndarray) -> dict | None:
    """{"kind", "fit" (0-1), y "vertices" o "center"/"axes"/"angle"} en las unidades del contorno."""
    contour = np.asarray(contour, dtype=np.float64).reshape(-1, 2)
    if len(contour) < 5:
        return None
    lo = np.floor(contour.min(axis=0)) - 2
    hi = np.ceil(contour.max(axis=0)) + 2
    scale = 200.0 / max(float((hi - lo).max()), 1.0)  # a una rejilla de ~200 px para medir rápido
    work = (contour - lo) * scale
    size = (int((hi - lo)[1] * scale) + 4, int((hi - lo)[0] * scale) + 4)
    pts32 = work.astype(np.float32)
    options = []
    _, triangle = cv2.minEnclosingTriangle(pts32)
    if triangle is not None:
        options.append({"kind": "triangle", "vertices": triangle.reshape(-1, 2).astype(np.float64)})
    if len(pts32) >= 5:
        (cx, cy), (w, h), angle = cv2.fitEllipse(pts32)
        options.append({"kind": "ellipse", "center": (cx, cy), "axes": (w, h), "angle": angle})
    box = cv2.boxPoints(cv2.minAreaRect(pts32))
    options.append({"kind": "rectangle", "vertices": box.astype(np.float64)})
    (cx, cy), radius = cv2.minEnclosingCircle(pts32)
    options.append({"kind": "circle", "center": (cx, cy), "axes": (2 * radius, 2 * radius), "angle": 0.0})
    best = None
    for option in options:
        score = _iou(work, shape_points(option, 96), size, np.zeros(2))
        if best is None or score > best[1]:
            best = (option, score)
    shape, score = best
    # De vuelta a las unidades del contorno.
    out = {"kind": shape["kind"], "fit": round(score, 3)}
    if "vertices" in shape:
        out["vertices"] = (shape["vertices"] / scale + lo).tolist()
    else:
        out["center"] = tuple((np.array(shape["center"]) / scale + lo).tolist())
        out["axes"] = tuple((np.array(shape["axes"]) / scale).tolist())
        out["angle"] = shape["angle"]
    return out
