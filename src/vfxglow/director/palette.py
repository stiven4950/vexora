"""Colores que contrastan con la piel de la persona.

Una parte del cuerpo encendida se tiñe (`blend: tint`): la piel conserva su luz y toma el tono
del color, y encima va la línea blanca del neón. Con la fórmula del tinte (composite._blend),
la piel teñida queda en `(0.15 + 2 x luma) x tono`:

- Piel clara (luma ~0,3): un amarillo, un verde claro o un turquesa teñidos quedan casi blancos
  y la línea blanca se pierde; un magenta o un violeta quedan con cuerpo.
- Piel morena (luma ~0,07): todo queda más oscuro, y los tonos oscuros (violeta, azul) se apagan;
  los claros y vivos se leen mejor.

`skin_scores` puntúa cada color de la paleta (0-1) por el mínimo de las dos cosas: contraste de
la línea blanca con la piel teñida, y que el tinte no quede apagado.
"""

from __future__ import annotations

import numpy as np

from vfxglow.analysis.schema import MotionBrief

_LUMA = np.array([0.2126, 0.7152, 0.0722])
# Contraste (1,05 / (luma + 0,05)) con la línea blanca a partir del cual la línea se lee bien,
# y luminancia mínima del tinte para que no quede apagado.
GOOD_CONTRAST = 3.0
GOOD_GLOW = 0.2
# Ningún color queda fuera del todo: solo sale menos.
FLOOR = 0.15


def skin_luma(brief: MotionBrief) -> float | None:
    if not brief.skin:
        return None
    return float(np.mean([tone.luma for tone in brief.skin.values()]))


def skin_scores(palette, luma: float) -> np.ndarray:
    colors = np.asarray(palette, dtype=np.float64)
    hue = colors / np.maximum(colors.max(axis=1, keepdims=True), 1e-6)
    dyed = np.clip((0.15 + 2.0 * luma) * hue, 0.0, 1.0) @ _LUMA
    contrast = 1.05 / (dyed + 0.05)
    score = np.minimum(np.clip(contrast / GOOD_CONTRAST, 0.0, 1.0), np.clip(dyed / GOOD_GLOW, 0.0, 1.0))
    return np.maximum(score, FLOOR)
