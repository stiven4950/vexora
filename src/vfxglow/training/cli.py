"""vfxglow-train: etiquetar, revisar, armar, entrenar y exportar un detector.

    vfxglow-train label  --task training/tasks/blade.yaml   # etiquetas candidatas + hojas de revisión
    vfxglow-train build  --task training/tasks/blade.yaml   # dataset YOLO (sin las rechazadas)
    vfxglow-train train  --task training/tasks/blade.yaml   # entrena y copia los pesos a models/
    vfxglow-train export --task training/tasks/blade.yaml   # solo copia los mejores pesos
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from vfxglow.training import store
from vfxglow.training.task import load_task

log = logging.getLogger("vfxglow.training")


def label(task, only: set[str] | None) -> None:
    from vfxglow.analysis.blades import _KERNEL
    from vfxglow.training import openimages
    from vfxglow.training.pairs import label_pair
    from vfxglow.training.videos import prelabel_video

    out = task.data_dir / "labels" / task.name
    jobs = []
    for pair in task.pairs:
        jobs.append((pair.name, lambda p=pair: label_pair(p, task.frame_stride)))
    for video in task.videos:
        jobs.append((video.name, lambda v=video: prelabel_video(v, task.frame_stride)))
    for name, job in jobs:
        if only and name not in only:
            continue
        store.save(job(), out / name)
        pages = store.write_sheets(out / name, task.review_dir / name)
        log.info("%s: %d hojas de revisión en %s", name, pages, task.review_dir / name)
    if task.openimages.enabled and (not only or "openimages" in only):
        folder = task.data_dir / "openimages"
        openimages.fetch_boxes(folder, task.openimages.classes)
        found = openimages.fetch_images(folder, task.openimages)
        for split, items in openimages.label_images(found, _KERNEL).items():
            name = f"openimages_{split}"
            store.save(items, out / name)
            store.write_sheets(out / name, task.review_dir / name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vfxglow-train", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["label", "build", "train", "export"])
    parser.add_argument("--task", type=Path, default=Path("training/tasks/blade.yaml"))
    parser.add_argument("--only", default="", help="Solo estas fuentes (separadas por coma), p. ej. video_38,openimages")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        pass
    task = load_task(args.task)
    if args.command == "label":
        label(task, {s for s in args.only.split(",") if s} or None)
    elif args.command == "build":
        from vfxglow.training.dataset import build

        build(task)
    elif args.command == "train":
        from vfxglow.training.train import train

        print(train(task))
    else:
        from vfxglow.training.train import export

        print(export(task))
    return 0


if __name__ == "__main__":
    sys.exit(main())
