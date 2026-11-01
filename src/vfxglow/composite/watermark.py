"""Marca de agua de los planes que la llevan (configs/plans.yaml, `watermark`): el isotipo de Vexora y
el nombre, abajo a la derecha, semitransparentes.

Se pinta en cada fotograma que se compone (Pipeline._write), no con un filtro de ffmpeg: al editar
una versión, los fotogramas que se copian del video anterior ya la traen y no se pinta dos veces.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

MARK_SVG = Path(__file__).with_name("vexora-mark.svg")  # copia de web/public/vexora-mark.svg
# Alto de la marca respecto al lado corto del cuadro, margen y opacidad.
HEIGHT_SHARE = 0.045
MARGIN_SHARE = 0.035
OPACITY = 0.72
# La composición en paralelo llama a apply desde varios hilos: la marca se dibuja con skia una sola vez.
_LOCK = threading.Lock()


@lru_cache(maxsize=8)
def stamp(width: int, height: int) -> tuple[np.ndarray, int, int]:
    """La marca para un cuadro de width x height: RGBA float32 (alfa recto) y su esquina (x, y)."""
    import skia

    size = max(int(round(min(width, height) * HEIGHT_SHARE)), 12)
    mark_w = int(round(size * 128 / 96))
    font = skia.Font(skia.Typeface("Helvetica Neue", skia.FontStyle.Bold()), size * 0.62)
    text = "V E X O R A"
    text_w = int(np.ceil(font.measureText(text)))
    gap = int(size * 0.3)
    pad = max(size // 6, 2)
    w, h = pad * 2 + mark_w + gap + text_w, pad * 2 + size
    surface = skia.Surface(w, h)
    canvas = surface.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    # Sombra suave para que se lea sobre fondos claros.
    shadow = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(110, 0, 0, 0), ImageFilter=skia.ImageFilters.Blur(size * 0.12, size * 0.12))
    white = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(235, 255, 255, 255))
    baseline = pad + size * 0.5 + font.getSize() * 0.36
    canvas.drawString(text, pad + mark_w + gap, baseline + 1, font, shadow)
    canvas.drawString(text, pad + mark_w + gap, baseline, font, white)
    svg = skia.SVGDOM.MakeFromStream(skia.Stream.MakeFromFile(str(MARK_SVG)))
    svg.setContainerSize(skia.Size(mark_w, size))
    canvas.save()
    canvas.translate(pad, pad)
    svg.render(canvas)
    canvas.restore()
    rgba = surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType, alphaType=skia.kUnpremul_AlphaType).astype(np.float32) / 255.0
    rgba[..., 3] *= OPACITY
    margin = int(round(min(width, height) * MARGIN_SHARE))
    return rgba, max(width - w - margin, 0), max(height - h - margin, 0)


def apply(rgb: np.ndarray) -> np.ndarray:
    """Pinta la marca sobre un fotograma RGB uint8 (en sitio) y lo devuelve."""
    height, width = rgb.shape[:2]
    with _LOCK:
        mark, x, y = stamp(width, height)
    h, w = min(mark.shape[0], height - y), min(mark.shape[1], width - x)
    region = rgb[y : y + h, x : x + w].astype(np.float32)
    alpha = mark[:h, :w, 3:4]
    rgb[y : y + h, x : x + w] = np.round(region * (1.0 - alpha) + mark[:h, :w, :3] * 255.0 * alpha).astype(np.uint8)
    return rgb
