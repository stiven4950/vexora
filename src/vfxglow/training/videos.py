"""Videos sin glow: pre-etiquetado con el detector actual. Siempre requiere revisión."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.blades import BladeFinder
from vfxglow.analysis.schema import FrameRecord
from vfxglow.config import BladesConfig
from vfxglow.training.geometry import segment_to_obb
from vfxglow.training.pairs import Labeled, find_run
from vfxglow.training.task import VideoSource

log = logging.getLogger("vfxglow.training")


def prelabel_video(source: VideoSource, stride: int, cfg: BladesConfig | None = None) -> list[Labeled]:
    run = Path(source.run) if source.run else find_run(Path(source.video))
    if run is None:
        raise FileNotFoundError(f"No hay análisis de {source.video}. Corre antes: vfxglow analyze --video {source.video}")
    finder = BladeFinder(cfg or BladesConfig(mode="always"))
    tracks = [FrameRecord.model_validate_json(line) for line in (run / "analysis" / "tracks.jsonl").open(encoding="utf-8")]
    cap = cv2.VideoCapture(source.video)
    out = []
    for index, record in enumerate(tracks):
        ok, frame = cap.read()
        if not ok:
            break
        if index % max(stride, 1):
            continue
        height, width = frame.shape[:2]
        boxes = [
            segment_to_obb(
                np.array(blade.hilt) * [width, height],
                np.array(blade.tip) * [width, height],
            )
            for blade in finder.detect(record, frame)
        ]
        if boxes:
            out.append(Labeled(source=source.name, frame=index, image=frame, boxes=boxes))
    log.info("%s: %d fotogramas pre-etiquetados (revisar antes de entrenar)", source.name, len(out))
    return out
