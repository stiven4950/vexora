"""Qué tan seguido sale cada opción del catálogo en un video: corre el coreógrafo con N semillas y
cuenta en cuántas coreografías aparece cada opción (y las cadenas pedidas).

    .venv/bin/python tools/option_odds.py runs/video_51-4e4fb85f --catalog avatar \\
        --opciones desbarate,fenix,dragon_lanzado --cadena flip:estelas,landing:desbarate
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from vfxglow.analysis.schema import MotionBrief
from vfxglow.director.choreography import choreograph, load_catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--catalog", default="avatar")
    parser.add_argument("--semillas", type=int, default=60)
    parser.add_argument("--opciones", default="", help="Opciones a contar, separadas por coma (vacío = todas)")
    parser.add_argument("--cadena", action="append", default=[], help="acción:opción,acción:opción: la segunda en los 1,5 s después de la primera")
    args = parser.parse_args()
    catalog = load_catalog(Path("configs/catalogs") / f"{args.catalog}.yaml")
    brief = MotionBrief.model_validate_json((args.run / "analysis" / "motion_brief.json").read_text())
    fps = brief.video.fps or 30.0
    seen: Counter = Counter()
    chains: Counter = Counter()
    firsts: Counter = Counter()
    for seed in range(args.semillas):
        _, log = choreograph(catalog, brief, seed)
        picks = [(d.frame, d.action, d.choice.split(" ")[0]) for d in log.decisions if not d.choice.startswith("nada")]
        for name in {c for _f, _a, c in picks}:
            seen[name] += 1
        for chain in args.cadena:
            first, second = (tuple(x.split(":")) for x in chain.split(","))
            starts = [f for f, a, c in picks if (a, c) == first]
            firsts[chain] += bool(starts)
            chains[chain] += any(0 <= f2 - f1 <= 1.5 * fps for f1 in starts for f2, a, c in picks if (a, c) == second)
    wanted = [o for o in args.opciones.split(",") if o] or sorted(seen)
    n = args.semillas
    print(f"{args.run.name}: {n} coreografías")
    for name in wanted:
        print(f"  {name:20s} {100 * seen[name] // n:3d}%")
    for chain in args.cadena:
        print(f"  cadena {chain}: la primera {100 * firsts[chain] // n}%; con la segunda después {100 * chains[chain] // max(firsts[chain], 1)}% de esas")


if __name__ == "__main__":
    main()
