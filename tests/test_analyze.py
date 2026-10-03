"""Análisis MediaPipe sobre un video sintético: JSON, brief y overlay."""

from __future__ import annotations

from pathlib import Path

import numpy as np

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
