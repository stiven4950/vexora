"""Vista previa rápida de un preset en fotogramas sueltos, sin renderizar el video entero.

Para cada fotograma pedido renderiza solo los `--warmup` anteriores (lo que necesitan las
estelas y los fundidos) y compone sobre el original. Con --ref añade una fila con el mismo
fotograma de un video de referencia.

    python tools/preview.py --run runs/video_1-34f2d20d --video ../glowing/data/original/video_1.mp4 \\
        --preset fight_comic --frames 300,500,584 --ref ../glowing/data/glowing/video_1.mp4 --out preview.jpg
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.beats import cut_frames
from vfxglow.analysis.schema import AnalysisHeader, MotionBrief
from vfxglow.composite.composite import composite_frame
from vfxglow.config import load_config
from vfxglow.director.presets import load_preset
from vfxglow.engine.engine import EffectEngine, load_events, load_tracks
from vfxglow.io.store import read_model


def grab(cap: cv2.VideoCapture, index: int) -> np.ndarray:
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f"No se pudo leer el fotograma {index}")
    return frame


def tile(image: np.ndarray, label: str, width: int) -> np.ndarray:
    out = cv2.resize(image, (width, int(width * image.shape[0] / image.shape[1])))
    cv2.putText(out, label, (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--frames", required=True, help="Lista separada por comas")
    parser.add_argument("--ref", type=Path, default=None)
    parser.add_argument("--warmup", type=int, default=15)
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    parser.add_argument("--out", type=Path, default=Path("preview.jpg"))
    parser.add_argument("--tile", type=int, default=270, help="Ancho de cada fotograma en la hoja")
    args = parser.parse_args()

    cfg = load_config(args.config)
    analysis = args.run / "analysis"
    meta = read_model(analysis / "header.json", AnalysisHeader).video
    script = load_preset(args.config.resolve().parent / "presets" / f"{args.preset}.yaml", meta.frame_count)
    cuts = cut_frames(read_model(analysis / "motion_brief.json", MotionBrief).beats)
    tracks = {track.frame: track for track in load_tracks(analysis / "tracks.jsonl")}
    events = load_events(analysis / "events.jsonl")
    by_id = {effect.id: effect for effect in script.effects}
    source = cv2.VideoCapture(str(args.video))
    reference = cv2.VideoCapture(str(args.ref)) if args.ref else None

    ours, refs = [], []
    for target in (int(item) for item in args.frames.split(",")):
        engine = EffectEngine(script, cfg.engine, events, cuts=cuts, fps=meta.fps)
        for index in range(max(0, target - args.warmup), target + 1):
            layers = engine.render_frame(tracks.get(index), index, meta.width, meta.height, meta.frame_count, args.run)
        rgb = composite_frame(
            grab(source, target),
            [(by_id[effect_id], layer) for effect_id, _group, layer in layers],
            script.grade,
            enabled_groups=cfg.composite.enabled_groups(),
        )
        ours.append(tile(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), f"{args.preset} {target}", args.tile))
        if reference is not None:
            refs.append(tile(grab(reference, target), f"REF {target}", args.tile))
    rows = [np.hstack(refs)] if refs else []
    rows.append(np.hstack(ours))
    cv2.imwrite(str(args.out), np.vstack(rows))
    print(f"Vista previa en {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
