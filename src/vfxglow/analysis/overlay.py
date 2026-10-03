"""Overlay de depuración: el esqueleto suavizado, todavía sin efectos."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.names import BONES
from vfxglow.analysis.schema import FrameRecord, MotionEvent, VideoMeta
from vfxglow.composite.encode import FrameEncoder
from vfxglow.io.video import VideoReader


def _px(lm_x: float, lm_y: float, meta: VideoMeta) -> tuple[int, int]:
    return int(round(lm_x * meta.width)), int(round(lm_y * meta.height))


def draw_overlay(
    frame_bgr: np.ndarray,
    record: FrameRecord,
    meta: VideoMeta,
    events: list[MotionEvent] | None = None,
) -> np.ndarray:
    canvas = frame_bgr.copy()
    pts = {lm.name: lm for lm in record.pose if lm.c > 0}
    for a, b in BONES:
        if a in pts and b in pts:
            cv2.line(canvas, _px(pts[a].x, pts[a].y, meta), _px(pts[b].x, pts[b].y, meta), (80, 220, 255), 2, cv2.LINE_AA)
    for lm in pts.values():
        cv2.circle(canvas, _px(lm.x, lm.y, meta), 3, (255, 180, 40), -1, cv2.LINE_AA)
    for hand, color in ((record.left_hand, (80, 80, 255)), (record.right_hand, (40, 180, 40))):
        if hand is None:
            continue
        for lm in hand.landmarks:
            if lm.c > 0:
                cv2.circle(canvas, _px(lm.x, lm.y, meta), 2, color, -1, cv2.LINE_AA)
    for obj in record.objects:
        x0, y0 = _px(obj.box[0], obj.box[1], meta)
        x1, y1 = _px(obj.box[2], obj.box[3], meta)
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (180, 80, 255), 1, cv2.LINE_AA)
    if events:
        y = 22
        for event in events:
            if event.start_frame <= record.frame <= event.end_frame:
                if event.position is not None:
                    cv2.circle(canvas, _px(event.position[0], event.position[1], meta), 7, (40, 40, 255), 2, cv2.LINE_AA)
                cv2.putText(
                    canvas,
                    event.name,
                    (8, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (240, 240, 240),
                    1,
                    cv2.LINE_AA,
                )
                y += 16
    return canvas


def write_debug_overlay(
    video_path: Path,
    frames: list[FrameRecord],
    meta: VideoMeta,
    dest: Path,
    events: list[MotionEvent] | None = None,
) -> None:
    by_index = {record.frame: record for record in frames}
    encoder = FrameEncoder(dest, meta.width, meta.height, meta.fps, codec="h264", crf=23)
    try:
        with VideoReader(video_path) as reader:
            for index, frame in reader:
                record = by_index.get(index)
                if record is None:
                    painted = frame
                else:
                    painted = draw_overlay(frame, record, meta, events)
                encoder.write(cv2.cvtColor(painted, cv2.COLOR_BGR2RGB))
    except BaseException:
        encoder.abort()
        raise
    encoder.close()
