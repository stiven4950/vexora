"""Saca los objetos de una hoja de assets (dibujos de neón sobre fondo oscuro) como sprites.

Los PNG sueltos del paquete de Halloween venían recortados con una caja fija (dibujos cortados en
un borde) y con halos oscuros. La hoja original tiene cada dibujo entero: aquí se estima el fondo
(mínimo local suavizado, que los trazos brillantes no alcanzan), se resta y queda solo la luz del
dibujo sobre negro, que `sprite_fx` suma sobre el video. Las etiquetas de texto (grises) no
entran: solo cuenta lo saturado.

    .venv/bin/python tools/sprites_from_sheet.py HOJA.png configs/sprites/halloween \\
        --filas 20:262,295:515,548:756,786:972 --cortes "235,468,636,897,1108,1287;..." \\
        --nombres pumpkin,ghost,...
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def light_only(sheet: np.ndarray) -> np.ndarray:
    """La luz de los dibujos: la hoja menos su fondo (con viñeta) estimado."""
    small = cv2.resize(sheet, None, fx=0.25, fy=0.25, interpolation=cv2.INTER_AREA)
    background = cv2.GaussianBlur(cv2.erode(small, np.ones((15, 15), np.uint8)), (0, 0), 6)
    background = cv2.resize(background, (sheet.shape[1], sheet.shape[0]), interpolation=cv2.INTER_LINEAR)
    return np.clip(sheet - background * 1.15, 0, 255)


def drawing_mask(light: np.ndarray) -> np.ndarray:
    peak = light.max(axis=2)
    saturation = (peak - light.min(axis=2)) / np.maximum(peak, 1)
    return ((peak > 35) & (saturation > 0.35)).astype(np.uint8)


def cut_out(light: np.ndarray, mask: np.ndarray, box: tuple[int, int, int, int], pad: int = 10) -> np.ndarray:
    """El dibujo de la celda `box` (x0, y0, x1, y1), ajustado a su contenido y con negro puro afuera."""
    x0, y0, x1, y1 = box
    m = cv2.morphologyEx(mask[y0:y1, x0:x1], cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    ys, xs = np.nonzero(m)
    a, b = max(xs.min() - pad, 0), min(xs.max() + pad, x1 - x0)
    c, d = max(ys.min() - pad, 0), min(ys.max() + pad, y1 - y0)
    keep = cv2.GaussianBlur(cv2.dilate(m[c:d, a:b], np.ones((9, 9), np.uint8)).astype(np.float32), (0, 0), 3)[..., None]
    return np.clip(light[y0 + c : y0 + d, x0 + a : x0 + b] * np.minimum(keep * 1.5, 1.0), 0, 255).astype(np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("hoja", type=Path)
    parser.add_argument("salida", type=Path)
    parser.add_argument("--filas", required=True, help="Bandas de cada fila de dibujos: y0:y1,y0:y1...")
    parser.add_argument("--cortes", required=True, help="Por fila, las x entre dibujos (filas separadas por ;)")
    parser.add_argument("--nombres", required=True, help="Nombres en orden de lectura, separados por coma")
    args = parser.parse_args()
    sheet = cv2.imread(str(args.hoja), cv2.IMREAD_UNCHANGED)[..., :3].astype(np.float32)
    light = light_only(sheet)
    mask = drawing_mask(light)
    names = args.nombres.split(",")
    args.salida.mkdir(parents=True, exist_ok=True)
    k = 0
    for band, cuts in zip(args.filas.split(","), args.cortes.split(";")):
        y0, y1 = (int(v) for v in band.split(":"))
        edges = [0, *(int(v) for v in cuts.split(",")), sheet.shape[1]]
        for x0, x1 in zip(edges, edges[1:]):
            cv2.imwrite(str(args.salida / f"{names[k]}.png"), cut_out(light, mask, (x0, y0, x1, y1)))
            k += 1
    print(f"{k} sprites en {args.salida}")


if __name__ == "__main__":
    main()
