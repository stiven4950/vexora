"""Tabla de regresión de la Etapa 3: un renglón por (video, preset).

Lee lo que ya está en disco (manifest, tracks, eventos, video final) y lo cruza con el código
actual. No renderiza nada salvo con --snapshots, que corre tools/snapshot.py --check.

    python tools/bench.py                 # escribe runs/bench.md
    python tools/bench.py --snapshots     # además compara las huellas doradas

La columna "Visual" se rellena a mano después de mirar el video.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

from vfxglow.composite.encode import find_ffmpeg
from vfxglow.io.store import load_manifest
from vfxglow.pipeline import _code

# (carpeta del run, preset). La suite del plan de mejoras.
SUITE: list[tuple[str, str]] = [
    ("video_1-34f2d20d", "fight_comic"),
    ("video_2-e27a6ae3", "face_neon"),
    ("video_2-e27a6ae3", "paint_reveal"),
    ("video_27-6dc78c0f", "doodle_dance"),
]
OK, WARN, FAIL = "✅", "⚠️", "❌"


def video_frames(path: Path) -> int | None:
    ffmpeg = find_ffmpeg(required=False)
    if ffmpeg is None or not path.exists():
        return None
    proc = subprocess.run([ffmpeg, "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"], capture_output=True, text=True, check=False)
    tail = proc.stderr.rsplit("frame=", 1)
    if len(tail) < 2:
        return None
    digits = tail[1].strip().split()[0]
    return int(digits) if digits.isdigit() else None


def coverage(run: Path) -> tuple[int, int, int, int]:
    total = face = pose = fallback = 0
    with (run / "analysis" / "tracks.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            total += 1
            face += bool(row.get("face"))
            pose += bool(row.get("pose"))
            fallback += bool(row.get("head_contour") or row.get("fallback"))
    return total, face, pose, fallback


def row(runs: Path, run_id: str, preset: str, snapshots: bool) -> list[str]:
    run = runs / run_id
    manifest = load_manifest(run / "manifest.json")
    if manifest is None:
        return [run_id, preset, FAIL, "", "", "", "sin manifest", ""]
    inputs = manifest.inputs.get(f"compose:{preset}", {})
    expected = None
    header = run / "analysis" / "header.json"
    if header.exists():
        expected = json.loads(header.read_text(encoding="utf-8"))["video"]["frame_count"]
    written = video_frames(run / "output" / f"{preset}.mp4")
    current = (
        inputs.get("code_render") == _code("render")[:12]
        and inputs.get("code_compose") == _code("compose")[:12]
        and manifest.inputs.get("analyze", {}).get("code") == _code("analyze")[:12]
    )
    total, face, pose, fallback = coverage(run)
    events = Counter(json.loads(line)["name"] for line in (run / "analysis" / "events.jsonl").open(encoding="utf-8"))
    contact = events.get("person_contact", 0)
    tracking = f"cara {face * 100 // max(total, 1)}% · pose {pose * 100 // max(total, 1)}% · respaldo {fallback}"
    event_text = ", ".join(f"{name} {count}" for name, count in events.most_common(4))
    if contact:
        event_text += f" · contactos {contact}"
    if written is None:
        render = FAIL + " sin video"
    elif written != expected:
        render = f"{FAIL} {written}/{expected}"
    else:
        render = f"{OK} {written}/{expected}"
    code = OK if current else f"{WARN} código cambió"
    snap = ""
    if snapshots:
        result = subprocess.run(
            [sys.executable, "tools/snapshot.py", "--run", str(run), "--preset", preset, "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        snap = {0: OK, 2: "sin huella"}.get(result.returncode, f"{WARN} difiere")
    return [run_id.split("-")[0], preset, render, code, tracking, event_text, snap, ""]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=Path("runs"))
    parser.add_argument("--snapshots", action="store_true")
    args = parser.parse_args()
    head = ["Video", "Preset", "Render (fotogramas)", "Código vigente", "Tracking", "Eventos", "Snapshot", "Visual"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for run_id, preset in SUITE:
        lines.append("| " + " | ".join(row(args.runs, run_id, preset, args.snapshots)) + " |")
    out = args.runs / "bench.md"
    out.write_text("# Benchmark de regresión\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
