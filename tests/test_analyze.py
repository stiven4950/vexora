"""Análisis MediaPipe sobre un video sintético: JSON, brief y overlay."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from vfxglow.analysis.analyzer import analyze_video
from vfxglow.analysis.schema import AnalysisHeader, FrameRecord, MotionBrief
from vfxglow.config import AppConfig
from vfxglow.io.store import read_jsonl, read_model
from vfxglow.io.video import write_silent_video

ROOT = Path(__file__).resolve().parents[1]


def test_fast_analysis_writes_reusable_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(ROOT)
    frames = []
    for i in range(6):
        image = np.zeros((96, 128, 3), dtype=np.uint8)
        image[:] = (30, 30, 30)
        cv = __import__("cv2")
        cv.circle(image, (64 + i, 40), 8, (180, 160, 140), -1)
        frames.append(image)
    video = tmp_path / "blank.mp4"
    write_silent_video(video, frames, 12)
    cfg = AppConfig()
    cfg.paths.models_dir = str(ROOT / "models")
    cfg.analysis.flow.enabled = True
    cfg.analysis.flow.method = "farneback"
    run = tmp_path / "run"
    meta = analyze_video(video, run, cfg, "cpu")
    assert meta.frame_count == 6
    header = read_model(run / "analysis" / "header.json", AnalysisHeader)
    assert header.level == "fast"
    assert header.models["pose"]
    tracks = read_jsonl(run / "analysis" / "tracks.jsonl", FrameRecord)
    assert len(tracks) == 6
    assert tracks[1].flow is not None
    brief = read_model(run / "analysis" / "motion_brief.json", MotionBrief)
    assert "actor" in brief.summary or brief.summary
    assert (run / "analysis" / "debug_overlay.mp4").exists()


def test_fallback_finds_head_outline_and_bright_eye() -> None:
    import cv2
    import numpy as np

    from vfxglow.analysis.fallback import locate_head

    frame = np.zeros((200, 100, 3), dtype=np.uint8)
    frame[:] = (20, 90, 230)  # naranja en BGR: azul bajo, no es un ojo claro
    mask = np.zeros((200, 100), dtype=np.uint8)
    cv2.ellipse(mask, (50, 40), (25, 30), 0, 0, 360, 1, -1)  # cabeza
    mask[60:200, 20:80] = 1  # cuerpo
    cv2.circle(frame, (40, 35), 4, (235, 240, 245), -1)  # lente blanco

    contour, glint = locate_head(frame, mask)
    assert contour is not None and len(contour) >= 4
    ys = [y * 200 for _x, y in contour]
    bottom = 10 + int((200 - 10) * 0.45)
    assert max(ys) < bottom - 2  # sin el borde del recorte: curva abierta
    assert glint is not None and glint.name == "eye_glint"
    assert abs(glint.x * 100 - 40) < 2 and abs(glint.y * 200 - 35) < 2

    empty, none = locate_head(frame, np.zeros_like(mask))
    assert empty is None and none is None


def test_stabilize_heads_replaces_bad_shapes_using_the_glint() -> None:
    import numpy as np

    from vfxglow.analysis.fallback import stabilize_heads
    from vfxglow.analysis.schema import FrameRecord, Landmark

    square = np.array([[0.4, 0.4], [0.4, 0.2], [0.6, 0.2], [0.6, 0.4]])
    half = np.array([[0.4, 0.4], [0.4, 0.2], [0.5, 0.2], [0.5, 0.4]])

    def record(frame: int, shape: np.ndarray, glint_x: float | None) -> FrameRecord:
        glint = [Landmark(name="eye_glint", x=glint_x, y=0.3, c=1.0)] if glint_x is not None else []
        return FrameRecord(frame=frame, time_s=0.0, head_contour=[tuple(p) for p in shape], fallback=glint)

    frames = [
        record(0, square, 0.45),
        record(1, square, 0.45),
        record(2, half, 0.47),  # el segmentador perdió media cabeza; el ojo se movió 0.02
        record(3, square, 0.45),
        record(4, half, None),  # forma mala y sin ojo: no se inventa
    ]
    stabilize_heads(frames, 100, 100)
    assert frames[4].head_contour is None
    shifted = np.asarray(frames[2].head_contour)
    assert shifted[:, 0].max() > 0.6  # recuperó el ancho completo, desplazado hacia el ojo
    assert np.asarray(frames[1].head_contour) == pytest.approx(square)
