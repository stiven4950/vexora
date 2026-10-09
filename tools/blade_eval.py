"""Acierto de la detección de hojas contra lo que pintó el editor en la referencia.

Por cada fotograma, la diferencia entre el original y la referencia con glow (dilatada) es la
zona donde un editor dibujó efectos. Una hoja detectada "acierta" si sus puntos caen sobre esa
zona. Es la medida usada para comparar detectores (clásico, YOLO-World, Grounding DINO, modelo
propio): mismo video, mismos fotogramas, misma regla.

    python tools/blade_eval.py --run runs/video_39-9961beb5 \\
        --original ../glowing/data/original/video_39.mp4 --reference ../glowing/data/glowing/video_39.mp4 --frames 132

--boxes gdino usa Grounding DINO como fuente de cajas de respaldo (como YOLO-World).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis import blades as B
from vfxglow.analysis.gdino import GroundingDino
from vfxglow.analysis.schema import FrameRecord
from vfxglow.config import load_config

# Píxeles de diferencia que cuentan como efecto pintado, y dilatación de esa zona.
DIFF = 50
DILATE = 17
GOOD = 0.6


def _inside(blade, boxes, width: int, height: int, pad: float = 0.15) -> bool:
    mid = (np.array(blade.hilt) + np.array(blade.tip)) * 0.5 * [width, height]
    for x0, y0, x1, y1 in boxes:
        dx, dy = (x1 - x0) * pad, (y1 - y0) * pad
        if x0 - dx <= mid[0] <= x1 + dx and y0 - dy <= mid[1] <= y1 + dy:
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=10_000, help="Evalúa los primeros N fotogramas")
    parser.add_argument("--boxes", choices=["none", "gdino"], default="none")
    parser.add_argument("--only-boxes", action="store_true", help="Sin líneas: solo cajas (mide el detector solo)")
    parser.add_argument("--model", type=Path, default=None, help="Pesos entrenados con vfxglow-train (detector 'model')")
    parser.add_argument("--gate", action="store_true", help="Descarta hojas cuyo centro cae fuera de las cajas de --boxes")
    parser.add_argument("--gdino-model", default="IDEA-Research/grounding-dino-base")
    parser.add_argument("--prompt", default="a sword. a katana. a metal blade.")
    parser.add_argument("--threshold", type=float, default=0.2)
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    args = parser.parse_args()

    cfg = load_config(args.config).analysis.blades
    finder = B.BladeFinder(cfg)
    if args.boxes == "gdino":
        detector = GroundingDino(args.gdino_model, args.prompt, args.threshold)
        finder._yolo = True  # activa la rama de cajas de BladeFinder
        finder._yolo_boxes = detector
    if args.only_boxes:
        B._best_line = lambda *a: None
        B._best_hough = lambda *a: None
    if args.model:
        finder = B.BladeFinder(cfg.model_copy(update={"detector": "model", "model_path": str(args.model)}))
    from vfxglow.training.pairs import Aligner

    aligner = Aligner()
    rows = [FrameRecord.model_validate_json(line) for line in (args.run / "analysis" / "tracks.jsonl").open()]
    original, reference = cv2.VideoCapture(str(args.original)), cv2.VideoCapture(str(args.reference))
    scores, framed = [], 0
    for index in range(min(args.frames, len(rows))):
        ok_a, frame = original.read()
        ok_b, painted = reference.read()
        if not (ok_a and ok_b):
            break
        # La referencia puede venir reencuadrada (video_38): se alinea antes de comparar.
        painted = aligner(frame, painted)
        if painted is None:
            continue
        zone = (np.abs(painted.astype(int) - frame.astype(int)).max(axis=2) > DIFF).astype(np.uint8)
        zone = cv2.dilate(zone, np.ones((DILATE, DILATE), np.uint8))
        found = finder.detect(rows[index], frame)
        if args.gate and args.boxes != "none":
            boxes = detector(frame)
            if boxes:
                found = [b for b in found if _inside(b, boxes, width=frame.shape[1], height=frame.shape[0])]
        framed += bool(found)
        height, width = frame.shape[:2]
        for blade in found:
            t = np.linspace(0.15, 1.0, 20)[:, None]
            pts = ((np.array(blade.hilt) + (np.array(blade.tip) - np.array(blade.hilt)) * t) * [width, height]).astype(int)
            inside = (pts[:, 0] >= 0) & (pts[:, 0] < width) & (pts[:, 1] >= 0) & (pts[:, 1] < height)
            scores.append(float(zone[pts[inside, 1], pts[inside, 0]].mean()) if inside.any() else 0.0)
    s = np.array(scores) if scores else np.zeros(1)
    print(f"hojas {len(scores)} | fotogramas con hoja {framed} | acierto medio {s.mean():.2f} | buenas (>{GOOD}) {(s > GOOD).mean():.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
