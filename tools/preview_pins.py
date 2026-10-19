"""Vista previa rápida: la referencia arriba y nuestro render abajo, en los segundos pedidos.

Renderiza solo los cuadros necesarios (sin codificar video) con un catálogo y un guion de prueba,
incluidos los efectos `always` del catálogo aunque el guion sea "solo estos".

    .venv/bin/python tools/preview_pins.py --run runs/video_18-94051f61 \\
        --video ../glowing/data/original/video_18.mp4 --ref ../glowing/data/glowing/video_18.mp4 \\
        --catalog avatar --pins guion.yaml --out /tmp/prev.jpg 3.4 3.5 3.6
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.schema import MotionBrief
from vfxglow.composite.composite import composite_frame
from vfxglow.config import EngineConfig
from vfxglow.director.choreography import always_effects, choreograph, load_catalog
from vfxglow.director.pins import load_pins
from vfxglow.director.schema import Effect, resolve_timing
from vfxglow.engine.engine import EffectEngine
from vfxglow.pipeline import load_tracks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--ref", type=Path, default=None, help="Referencia (opcional): va arriba")
    parser.add_argument("--catalog", required=True, help="Nombre en configs/catalogs o ruta a un .yaml")
    parser.add_argument("--pins", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--width", type=int, default=180)
    parser.add_argument("seconds", nargs="+", type=float)
    args = parser.parse_args()

    tracks = {t.frame: t for t in load_tracks(args.run / "analysis" / "tracks.jsonl")}
    brief = MotionBrief.model_validate_json((args.run / "analysis" / "motion_brief.json").read_text())
    fps, count, width, height = brief.video.fps, brief.video.frame_count, brief.video.width, brief.video.height
    path = Path(args.catalog) if args.catalog.endswith(".yaml") else Path("configs/catalogs") / f"{args.catalog}.yaml"
    catalog = load_catalog(path)
    script, _ = choreograph(catalog, brief, 1, load_pins(args.pins))
    extra = [Effect.model_validate(raw) for raw in always_effects(catalog, list(brief.events), count, fps, 1)]
    script = resolve_timing(script.model_copy(update={"effects": extra + list(script.effects)}), count)
    by_id = {e.id: e for e in script.effects}
    wanted = sorted({int(round(s * fps)) for s in args.seconds})
    first = max(wanted[0] - 40, 0)
    engine = EffectEngine(script, EngineConfig(), events=list(brief.events), fps=fps)
    original = cv2.VideoCapture(str(args.video))
    original.set(cv2.CAP_PROP_POS_FRAMES, first)
    reference = cv2.VideoCapture(str(args.ref)) if args.ref else None
    if reference is not None:
        reference.set(cv2.CAP_PROP_POS_FRAMES, first)
    size = (args.width, int(args.width * height / width))
    top, bottom = [], []
    for index in range(first, wanted[-1] + 1):
        ok, frame = original.read()
        ref = reference.read()[1] if reference is not None else None
        layers = engine.render_frame(tracks.get(index), index, width, height, count)
        if index not in wanted or not ok:
            continue
        out = composite_frame(frame, [(by_id[eid], layer) for eid, _g, layer in layers], script.grade)
        ours = cv2.resize(cv2.cvtColor(out, cv2.COLOR_RGB2BGR), size)
        label = cv2.resize(ref, size) if ref is not None else ours.copy()
        cv2.putText(label, f"{index / fps:.2f}", (4, 18), 0, 0.5, (0, 255, 255), 2)
        top.append(label)
        bottom.append(ours)
    rows = [np.hstack(top), np.hstack(bottom)] if reference is not None else [np.hstack(bottom)]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(args.out), np.vstack(rows))


if __name__ == "__main__":
    main()
