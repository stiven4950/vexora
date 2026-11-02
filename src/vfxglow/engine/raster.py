"""Raster: trazos con antialiasing y estampas aditivas en un buffer HDR."""

from __future__ import annotations

import math

import cv2
import numpy as np

from vfxglow.director.schema import EffectStyle


def empty_layer(height: int, width: int) -> np.ndarray:
    return np.zeros((height, width, 4), dtype=np.float32)


def sample_gradient(colors: list[tuple[float, float, float]], t: float) -> np.ndarray:
    cols = np.asarray(colors, dtype=np.float32)
    if len(cols) == 1:
        return cols[0]
    x = float(np.clip(t, 0.0, 1.0)) * (len(cols) - 1)
    i = min(int(np.floor(x)), len(cols) - 2)
    f = x - i
    return cols[i] * (1.0 - f) + cols[i + 1] * f


def _pixels(surface) -> np.ndarray:
    """RGBA premultiplicado: el `toarray()` por defecto de Skia lo devuelve sin premultiplicar y
    entonces el alfa de cada trazo no atenúa su energía."""
    import skia

    return surface.makeImageSnapshot().toarray(alphaType=skia.kPremul_AlphaType)


def light_over(dst: np.ndarray, add: np.ndarray, weight: np.ndarray) -> None:
    """Suma `add` (RGBA con A a 0) a `dst` y cubre su alfa con `weight`. Da lo mismo que operar con
    `dst[..., :3] += ...`, pero recorrer los canales intercalados con NumPy cuesta unas 4 veces más."""
    cv2.add(dst, add, dst=dst)
    cv2.mixChannels([1.0 - (1.0 - cv2.extractChannel(dst, 3)) * (1.0 - weight)], [dst], [0, 3])


def _stamp(layer: np.ndarray, rgba: np.ndarray, gain: float) -> None:
    red, green, blue, alpha = cv2.split(rgba.astype(np.float32) / 255.0)
    keep = np.maximum(alpha, 1e-4)
    straight = red / keep, green / keep, blue / keep
    # La ganancia HDR empuja el color; el blanco se queda cerca de 1 para que el núcleo de un
    # neón siga siendo una línea fina y el bloom no lo convierta en una mancha blanca.
    peak = np.maximum(np.maximum(straight[0], straight[1]), straight[2])
    low = np.minimum(np.minimum(straight[0], straight[1]), straight[2])
    push = 1.0 + np.float32(gain - 1.0) * ((peak - low) / np.maximum(peak, 1e-4))
    light_over(layer, cv2.merge((*[channel * push * alpha for channel in straight], np.zeros_like(alpha))), alpha)


def _paint(color: np.ndarray | tuple[float, float, float], width: float, alpha: float, blur: float = 0.0):
    import skia

    paint = skia.Paint(
        AntiAlias=True,
        Style=skia.Paint.kStroke_Style,
        StrokeWidth=float(width),
        StrokeCap=skia.Paint.kRound_Cap,
        StrokeJoin=skia.Paint.kRound_Join,
        Color=skia.Color4f(float(color[0]), float(color[1]), float(color[2]), float(np.clip(alpha, 0.0, 1.0))),
    )
    if blur > 0.3:
        paint.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, float(blur)))
    return paint


def _path(points: np.ndarray):
    import skia

    path = skia.Path()
    path.moveTo(float(points[0, 0]), float(points[0, 1]))
    for x, y in points[1:]:
        path.lineTo(float(x), float(y))
    return path


def stroke_polyline(
    layer: np.ndarray,
    points: np.ndarray,
    color: tuple[float, float, float] | np.ndarray,
    width: float,
    gain: float,
    alpha: float = 1.0,
) -> None:
    stroke_batch(layer, [(np.asarray(points, dtype=np.float64), color, width, alpha)], gain)


def stroke_batch(
    layer: np.ndarray,
    strokes: list[tuple],
    gain: float,
) -> None:
    """Varios trazos (puntos, color, ancho, alfa[, desenfoque]) en una sola superficie y un solo
    volcado. El desenfoque (sigma en px) da halos suaves, como un box-shadow."""
    strokes = [
        item
        for item in strokes
        if len(item[0]) >= 2 and item[2] > 0.5 and item[3] > 0 and np.isfinite(item[0]).all()
    ]
    if not strokes or gain <= 0:
        return
    import skia

    height, width_px = layer.shape[:2]
    pad = max(item[2] + 3.0 * (item[4] if len(item) > 4 else 0.0) for item in strokes) + 2
    stacked = np.concatenate([item[0] for item in strokes])
    x0 = int(max(0, np.floor(stacked[:, 0].min() - pad)))
    y0 = int(max(0, np.floor(stacked[:, 1].min() - pad)))
    x1 = int(min(width_px, np.ceil(stacked[:, 0].max() + pad)))
    y1 = int(min(height, np.ceil(stacked[:, 1].max() + pad)))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    # Solo la caja que tocan los trazos: el volcado de Skia a numpy es lo caro.
    surface = skia.Surface(x1 - x0, y1 - y0)
    canvas = surface.getCanvas()
    canvas.clear(skia.Color4f(0, 0, 0, 0))
    canvas.translate(-x0, -y0)
    for points, color, width, alpha, *blur in strokes:
        canvas.drawPath(_path(points), _paint(color, width, alpha, blur[0] if blur else 0.0))
    _stamp(layer[y0:y1, x0:x1], _pixels(surface), gain)


def stroke_gradient(
    layer: np.ndarray,
    points: np.ndarray,
    style: EffectStyle,
    width: float,
    alpha: float,
) -> None:
    if len(points) < 2 or width <= 0.5 or alpha <= 0:
        return
    # Hasta 12 tramos, cada uno con su color del degradado, en un solo volcado del recuadro que
    # tocan (antes, una superficie del cuadro entero por trazo: el rayo tardaba 5 s por cuadro).
    points = np.asarray(points, dtype=np.float64)
    chunks = min(12, max(1, len(points) - 1))
    span = len(points) - 1
    strokes = []
    for index in range(chunks):
        start = int(index * span / chunks)
        end = int((index + 1) * span / chunks) + 1
        segment = points[start:end]
        if len(segment) < 2:
            continue
        strokes.append((segment, sample_gradient(style.colors, index / max(chunks - 1, 1)), width, alpha))
    stroke_batch(layer, strokes, style.hdr_gain)


def splat(layer: np.ndarray, x: float, y: float, radius: float, color: np.ndarray, alpha: float, kernels: dict[int, np.ndarray]) -> None:
    if radius < 0.5 or alpha <= 0:
        return
    r = max(1, int(round(radius)))
    kernel = kernels.get(r)
    if kernel is None:
        axis = np.arange(-r, r + 1, dtype=np.float32)
        xx, yy = np.meshgrid(axis, axis)
        kernel = np.exp(-(xx * xx + yy * yy) / (2.0 * (r * 0.45) ** 2)).astype(np.float32)
        kernels[r] = kernel
    height, width = layer.shape[:2]
    x0 = int(round(x)) - r
    y0 = int(round(y)) - r
    x1 = x0 + kernel.shape[1]
    y1 = y0 + kernel.shape[0]
    src_x0 = max(0, -x0)
    src_y0 = max(0, -y0)
    src_x1 = kernel.shape[1] - max(0, x1 - width)
    src_y1 = kernel.shape[0] - max(0, y1 - height)
    if src_x0 >= src_x1 or src_y0 >= src_y1:
        return
    dst = layer[y0 + src_y0 : y0 + src_y1, x0 + src_x0 : x0 + src_x1]
    weight = kernel[src_y0:src_y1, src_x0:src_x1] * np.float32(alpha)
    dst[..., :3] += color.astype(np.float32) * weight[..., None]
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - np.clip(weight, 0.0, 1.0))


def directional_blur(layer: np.ndarray, vx: float, vy: float, amount: float) -> None:
    """Desenfoque ligero a lo largo de la velocidad de la ancla. Opera sobre la capa, no sobre el plano."""
    if amount <= 0.02:
        return
    length = float(np.hypot(vx, vy)) * amount
    if length < 0.8:
        return
    steps = int(np.clip(round(length), 2, 9))
    angle = math.atan2(vy, vx)
    size = steps * 2 + 1
    kernel = np.zeros((size, size), dtype=np.float32)
    cx = cy = steps
    for i in range(steps + 1):
        dx = math.cos(angle) * i
        dy = math.sin(angle) * i
        for sign in (1.0, -1.0):
            x = int(round(cx + dx * sign))
            y = int(round(cy + dy * sign))
            if 0 <= x < size and 0 <= y < size:
                kernel[y, x] = 1.0
    total = float(kernel.sum())
    if total <= 0:
        return
    kernel /= total
    layer[:] = cv2.filter2D(layer, -1, kernel)


def soften_alpha(layer: np.ndarray, radius: float = 1.15) -> None:
    if layer[..., 3].max() <= 1e-5:
        return
    layer[..., 3] = cv2.GaussianBlur(layer[..., 3], (3, 3), radius)


def fill_polygon(
    layer: np.ndarray,
    points: np.ndarray,
    color: np.ndarray,
    alpha: float,
    gain: float,
    feather: float = 2.0,
    holes: list[np.ndarray] | None = None,
) -> None:
    """Rellena un polígono (menos sus huecos) con energía de color y borde suavizado."""
    if alpha <= 0 or len(points) < 3:
        return
    height, width = layer.shape[:2]
    # Solo el recuadro del polígono (más el margen del desenfoque): pintar una escama diminuta con
    # una máscara del cuadro entero costaba ~27 ms (video_18: el 40% del render).
    pad = int(np.ceil(max(feather, 0.0) * 3)) + 2
    lo = np.floor(points.min(axis=0)).astype(int) - pad
    hi = np.ceil(points.max(axis=0)).astype(int) + pad + 1
    x0, y0 = max(lo[0], 0), max(lo[1], 0)
    x1, y1 = min(hi[0], width), min(hi[1], height)
    if x0 >= x1 or y0 >= y1:
        return
    offset = np.array([x0, y0], dtype=np.float64)
    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(points - offset).astype(np.int32)], 255, lineType=cv2.LINE_AA)
    for hole in holes or []:
        cv2.fillPoly(mask, [np.round(hole - offset).astype(np.int32)], 0, lineType=cv2.LINE_AA)
    weight = mask.astype(np.float32) / 255.0
    if feather > 0:
        weight = cv2.GaussianBlur(weight, (0, 0), feather)
    weight *= np.float32(alpha)
    dst = layer[y0:y1, x0:x1]
    dst[..., :3] += np.asarray(color, dtype=np.float32) * np.float32(gain) * weight[..., None]
    dst[..., 3] = 1.0 - (1.0 - dst[..., 3]) * (1.0 - weight)
