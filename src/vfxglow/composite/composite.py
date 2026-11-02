"""Mezcla de capas HDR sobre el plano original en luz lineal."""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.composite.color import ROUND_TRIP, linear_to_srgb, plate_to_linear, shoulder
from vfxglow.composite.glow import bloom
from vfxglow.director.schema import Effect, Grade, effect_group

GROUP_ORDER: tuple[str, ...] = ("grade", "glow", "particles", "interaction", "lightning")


def _blend(base: np.ndarray, rgb: np.ndarray, alpha: np.ndarray, mode: str) -> np.ndarray:
    """`rgb` llega premultiplicado: ya incluye la cobertura. `add` suma esa energía."""
    a = np.clip(alpha, 0.0, 1.0)[..., None]
    if mode == "add":
        return base + rgb
    if mode == "multiply":
        straight = np.divide(rgb, np.maximum(a, 1e-4))
        tint = np.clip(straight, 0.0, 1.5)
        return base * (1.0 - a) + (base * tint) * a
    if mode == "screen":
        straight = np.divide(rgb, np.maximum(a, 1e-4))
        fg = np.clip(straight, 0.0, 1.0)
        screen = 1.0 - (1.0 - np.clip(base, 0.0, 1.0)) * (1.0 - fg)
        return base * (1.0 - a) + screen * a
    if mode == "tint":
        # Tiñe el plano conservando su luz (piel verde, ropa magenta) y deja que lo más caliente
        # del trazo (el núcleo blanco) sume luz encima.
        straight = np.divide(rgb, np.maximum(a, 1e-4))
        peak = np.maximum(straight.max(axis=-1, keepdims=True), 1e-4)
        hue = straight / peak
        luma = (base * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).sum(axis=-1, keepdims=True)
        dyed = (0.15 + luma * 2.0) * hue
        hot = np.clip(peak - 1.0, 0.0, None) * (hue * 0.4 + 0.6)
        return base * (1.0 - a) + (dyed + hot) * a
    return rgb + base * (1.0 - a)


def _refract(acc: np.ndarray, layer: np.ndarray) -> np.ndarray:
    """Refracción: la capa lleva desplazamientos (R=dx, G=dy en px) y máscara (A), no luz.

    Dentro de la máscara muestrea `acc` en (x+dx, y+dy); fuera queda idéntico.
    """
    h, w = acc.shape[:2]
    xs, ys = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_x = xs + layer[..., 0].astype(np.float32)
    map_y = ys + layer[..., 1].astype(np.float32)
    warped = cv2.remap(acc, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    a = np.clip(layer[..., 3], 0.0, 1.0).astype(np.float32)[..., None]
    return acc * (1.0 - a) + warped * a


def _record(parts: list | None, effect_id: str, before: np.ndarray, after: np.ndarray, alpha: np.ndarray | None) -> None:
    """Lo que aportó un efecto, como (A, C) con `after = before * (1 - A) + C`."""
    if parts is None:
        return
    if alpha is None:
        parts.append((effect_id, None, after - before))
        return
    a = np.clip(alpha, 0.0, 1.0).astype(np.float32)
    parts.append((effect_id, a, after - before * (1.0 - a)[..., None]))


def _box(layer: np.ndarray) -> tuple[slice, slice] | None:
    """El recuadro con algo distinto de cero. Afuera ninguna mezcla cambia el píxel (rgb = alfa = 0)."""
    height, width = layer.shape[:2]
    x, y, w, h = cv2.boundingRect((layer.reshape(height, width * 4) != 0).astype(np.uint8))
    if w == 0:
        return None
    return slice(y, y + h), slice(x // 4, (x + w - 1) // 4 + 1)


def composite_frame(
    plate_bgr: np.ndarray,
    layers: list[tuple[Effect, np.ndarray]],
    grade: Grade,
    soft_knee: float | None = None,
    enabled_groups: set[str] | None = None,
    parts: list[tuple[str, np.ndarray | None, np.ndarray]] | None = None,
) -> np.ndarray:
    """Devuelve RGB uint8. Los píxeles sin cobertura de efecto quedan idénticos al plano.

    `parts` (una lista vacía): se llena con lo que aporta cada efecto, en el orden en que se mezcla,
    como (id, A, C) tal que `después = antes * (1 - A) + C` en luz lineal (A = None: mezcla
    aditiva, A = 0). Es la base de las capas por pista del editor (composite/atlas.py)."""
    plate = plate_to_linear(plate_bgr)
    acc = plate.copy()
    height, width = plate.shape[:2]
    whole = slice(0, height), slice(0, width)
    coverage = np.zeros(plate.shape[:2], dtype=np.float32)
    knee = grade.soft_knee if soft_knee is None else soft_knee
    active = enabled_groups if enabled_groups is not None else set(GROUP_ORDER)
    ordered: list[tuple[Effect, np.ndarray]] = []
    for group in GROUP_ORDER:
        if group not in active:
            continue
        for effect, layer in layers:
            if effect_group(effect) == group and float(layer[..., 3].max()) > 1e-5:
                ordered.append((effect, layer))
    # Lo que no toca ninguna capa no se calcula. `parts` necesita el cuadro entero de cada efecto.
    top, left, bottom, right = height, width, 0, 0
    for effect, layer in ordered:
        before = None if parts is None else acc.copy()
        tinted = effect_group(effect) == "grade"
        refracted = not tinted and effect.render.blend == "refract"
        # Un tinte de pantalla completa (type grade) no tiene núcleo que irradie: sin bloom.
        # La refracción lleva desplazamientos, no luz: sin bloom ni shoulder.
        glowed = layer.astype(np.float32, copy=False) if tinted or refracted or effect.type == "grade" else bloom(
            layer.astype(np.float32, copy=False),
            grade.bloom_radius,
            grade.bloom_threshold,
            grade.bloom_intensity,
            effect.render.glow_layers,
        )
        box = whole if parts is not None else _box(glowed)
        if box is None:
            continue
        piece = glowed[box]
        alpha = piece[..., 3]
        if tinted:
            acc[box] = _blend(acc[box], piece[..., :3], alpha, "multiply")
        elif refracted:
            acc = _refract(acc, layer)
        else:
            acc[box] = _blend(acc[box], shoulder(piece[..., :3], knee), alpha, effect.render.blend)
        coverage[box] = np.maximum(coverage[box], np.clip(alpha, 0.0, 1.0))
        _record(parts, effect.id, before, acc, None if not tinted and not refracted and effect.render.blend == "add" else alpha)
        top, left, bottom, right = min(top, box[0].start), min(left, box[1].start), max(bottom, box[0].stop), max(right, box[1].stop)
    done = cv2.cvtColor(cv2.LUT(plate_bgr, ROUND_TRIP), cv2.COLOR_BGR2RGB)
    if top < bottom and left < right:
        box = slice(top, bottom), slice(left, right)
        drawn = acc[box]
        untouched = coverage[box] <= 1e-4
        drawn[untouched] = plate[box][untouched]
        done[box] = np.round(linear_to_srgb(drawn) * 255.0).astype(np.uint8)
    return done
