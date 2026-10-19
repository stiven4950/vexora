"""Mide, cuadro a cuadro, el fuego dibujado de una referencia estilo glowing.

Separa el fuego por color (cuerpo casi blanco y borde amarillo; el resto del cuadro es naranja
oscuro) y, por cada pieza conectada, da área, largo, ancho medio y máximo, posición y fracción
blanca. También cuenta cuántos cuadros dura cada dibujo (si se anima a uno o a dos).

    .venv/bin/python tools/measure_fire.py ../glowing/data/glowing/video_18.mp4 --hasta 3 --json out.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

import cv2
import numpy as np


def fire_mask(frame: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    b, g, r = (frame[..., k].astype(int) for k in range(3))
    core = (b > 185) & (g > 215) & (r > 215)
    rim = (r > 225) & (g > 150) & (b < 185) & ~core
    fire = cv2.morphologyEx((core | rim).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return fire, core


def pieces(fire: np.ndarray, core: np.ndarray, min_area: int = 25) -> list[dict]:
    count, labels, stats, centers = cv2.connectedComponentsWithStats(fire, 8)
    out = []
    for k in range(1, count):
        area = int(stats[k, 4])
        if area < min_area:
            continue
        mask = (labels == k).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        length = cv2.arcLength(max(contours, key=cv2.contourArea), True) / 2
        out.append({
            "area": area,
            "x": round(float(centers[k][0])),
            "y": round(float(centers[k][1])),
            "largo": round(length),
            "ancho_medio": round(area / max(length, 1), 1),
            "ancho_max": round(float(cv2.distanceTransform(mask, cv2.DIST_L2, 5).max() * 2), 1),
            "blanco": round(float(core[labels == k].mean()), 2),
        })
    return sorted(out, key=lambda p: -p["area"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--desde", type=float, default=0.0)
    parser.add_argument("--hasta", type=float, default=3.0)
    parser.add_argument("--json", default=None)
    args = parser.parse_args()
    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    first, last = int(args.desde * fps), int(args.hasta * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, first)
    rows, previous, runs, run = [], None, [], 1
    for index in range(first, last + 1):
        ok, frame = cap.read()
        if not ok:
            break
        fire, core = fire_mask(frame)
        found = pieces(fire, core)
        rows.append({"cuadro": index, "seg": round(index / fps, 2), "piezas": len(found), "area": sum(p["area"] for p in found), "formas": found[:8]})
        if previous is not None:
            union = (fire | previous).sum()
            if union and (fire & previous).sum() / union > 0.97:
                run += 1
            else:
                runs.append(run)
                run = 1
        previous = fire
    runs.append(run)
    for row in rows:
        top = " ; ".join(f"A{p['area']} L{p['largo']} w{p['ancho_medio']}/{p['ancho_max']} ({p['x']},{p['y']}) b{p['blanco']}" for p in row["formas"][:3])
        print(f"{row['cuadro']:4d} {row['seg']:6.2f}s piezas={row['piezas']:3d} area={row['area']:7d} | {top}")
    print(f"Dibujos distintos: {len(runs)} en {len(rows)} cuadros; cuadros por dibujo: {dict(Counter(runs))}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as out:
            json.dump(rows, out, ensure_ascii=False)


if __name__ == "__main__":
    main()
