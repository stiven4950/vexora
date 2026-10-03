"""Huella determinista del render de un preset sobre un run ya analizado.

Renderiza en memoria (sin video, sin ffmpeg) y guarda un hash por efecto cada N
fotogramas. Con --check compara contra la huella guardada: es el gate de
"face_neon sigue igual" cuando se toca el motor.

La primera captura congela una copia del análisis en `<run>/golden/analysis`. Las
comprobaciones usan esa copia, así que re-analizar el video no altera el gate:
solo mide el motor y el guion.

    python tools/snapshot.py --run runs/video_2-e27a6ae3 --preset face_neon
    python tools/snapshot.py --run runs/video_2-e27a6ae3 --preset face_neon --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

from vfxglow.analysis.beats import cut_frames
from vfxglow.analysis.schema import AnalysisHeader, MotionBrief
from vfxglow.config import load_config
from vfxglow.director.presets import load_preset
from vfxglow.engine.engine import EffectEngine, load_events, load_tracks
from vfxglow.io.store import read_model


def fingerprint(run: Path, preset: str, config: Path, every: int) -> dict[str, dict[str, str]]:
    cfg = load_config(config)
    meta = read_model(run / "analysis" / "header.json", AnalysisHeader).video
    script = load_preset(config.resolve().parent / "presets" / f"{preset}.yaml", meta.frame_count)
    brief_path = run / "analysis" / "motion_brief.json"
    cuts = cut_frames(read_model(brief_path, MotionBrief).beats) if brief_path.exists() else []
    tracks = {track.frame: track for track in load_tracks(run / "analysis" / "tracks.jsonl")}
    engine = EffectEngine(script, cfg.engine, load_events(run / "analysis" / "events.jsonl"), cuts=cuts, fps=meta.fps)
    out: dict[str, dict[str, str]] = {}
    for index in range(meta.frame_count):
        layers = engine.render_frame(tracks.get(index), index, meta.width, meta.height, meta.frame_count, run)
        if index % every:
            continue
        out[str(index)] = {
            effect_id: hashlib.sha256(layer.astype("float16").tobytes()).hexdigest()[:16]
            for effect_id, _group, layer in layers
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--preset", required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    parser.add_argument("--every", type=int, default=10)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    golden = args.run / "golden"
    if not (golden / "analysis").exists():
        shutil.copytree(args.run / "analysis", golden / "analysis", ignore=shutil.ignore_patterns("*.mp4"))
    dest = golden / f"{args.preset}.json"
    current = fingerprint(golden, args.preset, args.config, args.every)
    if not args.check:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(current, indent=1), encoding="utf-8")
        print(f"Huella guardada en {dest} ({len(current)} fotogramas)")
        return 0
    if not dest.exists():
        print(f"No hay huella en {dest}")
        return 2
    saved = json.loads(dest.read_text(encoding="utf-8"))
    diff = [
        (frame, effect_id)
        for frame in sorted(set(saved) | set(current), key=int)
        for effect_id in sorted(set(saved.get(frame, {})) | set(current.get(frame, {})))
        if saved.get(frame, {}).get(effect_id) != current.get(frame, {}).get(effect_id)
    ]
    if diff:
        print(f"{len(diff)} diferencias. Primeras: {diff[:10]}")
        return 1
    print(f"Idéntico a {dest} ({len(current)} fotogramas)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
