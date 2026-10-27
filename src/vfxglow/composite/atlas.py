"""Capas por pista para la vista en vivo del editor (docs/analisis_mejoras_y_seguridad.md, §10.3).

Una versión se dibuja una vez más, a baja resolución, y se guarda como un solo MP4 en mosaico: el
plano original y, por cada pista del editor, una baldosa con lo que esa pista aporta a la imagen.
El navegador (web/src/components/editor/LayerPreview.tsx) rehace la mezcla con WebGL y puede apagar,
teñir, atenuar o agrandar cada pista al instante, sin volver a dibujar.

Lo que aporta una pista es (A, C) en luz lineal, con `después = antes * (1 - A) + C`
(composite.composite_frame, `parts`). La mezcla aditiva (la mayoría) tiene A = 0 y es exacta en
cualquier combinación de pistas; las demás (over, tint, multiply, refract) son exactas con todas
encendidas y aproximadas al apagar una que se solape con otra.

Codificación en 8 bits (H.264, un solo video: las baldosas no se desincronizan y Safari lo reproduce):
- C (energía HDR, puede pasar de 1): `srgb(C / (1 + C))`. Lo oscuro conserva detalle (la curva sRGB)
  y lo muy brillante se comprime sin recortar.
- A: gris lineal, en una baldosa aparte solo si la pista tiene mezclas no aditivas.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from pydantic import BaseModel, Field

from vfxglow.composite.color import linear_to_srgb

# Lado largo de cada baldosa de pista; el plano va al doble (2x2 baldosas).
TILE_LONG = 360
# Pistas con baldosa propia (las más largas); el resto comparte una ("rest").
MAX_LAYER_TRACKS = 16
REST = "__rest__"
ENCODING = "srgb-reinhard"


class TileRef(BaseModel):
    key: str
    # Esquina superior izquierda de la baldosa de energía (C) y, si la hay, de la de cobertura (A).
    c: tuple[int, int]
    a: tuple[int, int] | None = None
    # Centro de la energía por fotograma en el plano (x, y en milésimas; -1 = nada dibujado): el
    # punto alrededor del que se agranda la pista, como engine/tint.scale_about con el ancla.
    centers: list[int] = Field(default_factory=list)


class AtlasLayout(BaseModel):
    version: int = 1
    encoding: str = ENCODING
    fps: float
    frames: int
    width: int
    height: int
    tile: tuple[int, int]
    plate: tuple[int, int, int, int]
    tracks: list[TileRef]
    rest: TileRef | None = None


def _even(value: float) -> int:
    return max(2, int(round(value / 2.0)) * 2)


def plan_layout(width: int, height: int, fps: float, frames: int, keys: list[str], needs_alpha: dict[str, bool], has_rest: bool) -> AtlasLayout:
    """Dónde va cada baldosa: el plano ocupa 2x2 celdas arriba a la izquierda y las pistas llenan
    el resto de la cuadrícula, que se elige casi cuadrada (los navegadores decodifican hasta 4096 px)."""
    scale = TILE_LONG / max(width, height)
    tw, th = _even(width * scale), _even(height * scale)
    names = [*keys, *([REST] if has_rest else [])]
    cells = 4 + sum(1 + int(needs_alpha.get(name, False)) for name in names)
    cols = max(2, math.ceil(math.sqrt(cells * th / tw)))
    taken = {(0, 0), (0, 1), (1, 0), (1, 1)}
    free = ((r, c) for r in range(10_000) for c in range(cols) if (r, c) not in taken)
    refs: list[TileRef] = []
    rows = 2
    for name in names:
        r, c = next(free)
        a = None
        if needs_alpha.get(name, False):
            ra, ca = next(free)
            a = (ca * tw, ra * th)
            rows = max(rows, ra + 1)
        rows = max(rows, r + 1)
        refs.append(TileRef(key=name, c=(c * tw, r * th), a=a))
    rest = refs.pop() if has_rest else None
    return AtlasLayout(fps=fps, frames=frames, width=cols * tw, height=rows * th, tile=(tw, th), plate=(0, 0, 2 * tw, 2 * th), tracks=refs, rest=rest)


def fold(parts: list[tuple[str, np.ndarray | None, np.ndarray]], key_of: dict[str, str]) -> dict[str, tuple[np.ndarray | None, np.ndarray]]:
    """Las contribuciones de los efectos juntadas por pista, en el orden en que se mezclaron:
    aplicar (A1, C1) y luego (A2, C2) es A = 1 - (1 - A1)(1 - A2), C = C1 (1 - A2) + C2."""
    out: dict[str, tuple[np.ndarray | None, np.ndarray]] = {}
    for effect_id, a, c in parts:
        key = key_of.get(effect_id, REST)
        if key not in out:
            out[key] = (None if a is None else a.copy(), c.copy())
            continue
        a0, c0 = out[key]
        if a is None:
            out[key] = (a0, c0 + c)
        else:
            keep = (1.0 - a)[..., None]
            out[key] = (a if a0 is None else 1.0 - (1.0 - a0) * (1.0 - a), c0 * keep + c)
    return out


def encode_energy(c: np.ndarray) -> np.ndarray:
    """C (lineal, >= 0) → RGB uint8 con `srgb(C / (1 + C))`."""
    c = np.clip(c, 0.0, None)
    return np.round(linear_to_srgb(c / (1.0 + c)) * 255.0).astype(np.uint8)


def decode_energy(rgb: np.ndarray) -> np.ndarray:
    """La inversa (para pruebas; el navegador hace lo mismo en el shader)."""
    from vfxglow.composite.color import srgb_to_linear

    x = np.minimum(srgb_to_linear(rgb.astype(np.float32) / 255.0), 0.995)
    return x / (1.0 - x)


def encode_alpha(a: np.ndarray) -> np.ndarray:
    gray = np.round(np.clip(a, 0.0, 1.0) * 255.0).astype(np.uint8)
    return np.repeat(gray[..., None], 3, axis=-1)


def shrink(values: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Al tamaño de la baldosa con promedio de área: conserva la energía total de un trazo fino."""
    if (values.shape[1], values.shape[0]) == size:
        return values
    return cv2.resize(values, size, interpolation=cv2.INTER_AREA)


def center_of(c: np.ndarray) -> tuple[int, int]:
    """Centro de la energía (luma) en milésimas del cuadro, o (-1, -1) si no hay nada."""
    luma = c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722
    total = float(luma.sum())
    if total <= 1e-4:
        return -1, -1
    h, w = luma.shape
    x = float((luma.sum(axis=0) * (np.arange(w) + 0.5)).sum()) / total / w
    y = float((luma.sum(axis=1) * (np.arange(h) + 0.5)).sum()) / total / h
    return int(round(x * 1000)), int(round(y * 1000))
