"""Beats, contacto entre personas, glifos y las estrategias nuevas."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from vfxglow.analysis.beats import segment_beats
from vfxglow.analysis.events import EventDetector
from vfxglow.analysis.kinematics import add_motion
from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent, PersonPose, VideoMeta
from vfxglow.analysis.scene_reader import read_scenes
from vfxglow.composite.composite import composite_frame
from vfxglow.config import EventsConfig
from vfxglow.director.presets import load_preset
from vfxglow.director.schema import Effect, EffectRender, EffectStyle, EffectTarget, EffectTime, Grade
from vfxglow.director.strategies import expand, preset_script
from vfxglow.director.strategies import StrategyPlan, Choice
from vfxglow.engine.effects import EffectRuntime, render_effect
from vfxglow.engine.glyphs import resolve_glyph, validate_svg
from vfxglow.io.video import write_silent_video

ROOT = Path(__file__).resolve().parents[1]
PRESETS = ROOT / "configs" / "presets"


def _meta(n: int = 24) -> VideoMeta:
    return VideoMeta(path="x.mp4", fps=30, width=64, height=96, frame_count=n, duration_s=n / 30)


def _lm(name: str, x: float, y: float) -> Landmark:
    return Landmark(name=name, x=x, y=y, c=0.99)


def test_histogram_finds_a_cut(tmp_path: Path) -> None:
    frames = []
    for i in range(12):
        image = np.zeros((96, 64, 3), dtype=np.uint8)
        image[:] = (20, 20, 20) if i < 6 else (220, 40, 10)
        frames.append(image)
    video = tmp_path / "cut.mp4"
    write_silent_video(video, frames, 30)
    records = [FrameRecord(frame=i, time_s=i / 30) for i in range(12)]
    beats, _onsets = segment_beats(records, video, _meta(12))
    assert any(beat.kind == "cut" for beat in beats)


def test_person_contact_marks_attacker_and_receiver() -> None:
    records = []
    meta = VideoMeta(path="x.mp4", fps=30, width=200, height=200, frame_count=8, duration_s=8 / 30)
    for i in range(8):
        x = 0.40 + i * 0.08
        attacker = PersonPose(
            person_id="person_0",
            pose=[
                _lm("right_wrist", x, 0.24),
                _lm("right_elbow", x - 0.08, 0.5),
                _lm("left_shoulder", 0.2, 0.3),
                _lm("right_shoulder", 0.32, 0.3),
                _lm("left_hip", 0.22, 0.6),
                _lm("right_hip", 0.32, 0.6),
                _lm("nose", 0.26, 0.2),
            ],
        )
        receiver = PersonPose(
            person_id="person_1",
            pose=[
                _lm("nose", 0.62, 0.22),
                _lm("left_shoulder", 0.52, 0.34),
                _lm("right_shoulder", 0.7, 0.34),
                _lm("left_hip", 0.54, 0.62),
                _lm("right_hip", 0.68, 0.62),
                _lm("left_wrist", 0.5, 0.5),
                _lm("right_wrist", 0.74, 0.5),
            ],
        )
        records.append(FrameRecord(frame=i, time_s=i / 30, pose=attacker.pose, people=[attacker, receiver]))
    add_motion(records, meta, glitch_speed=5)
    events = EventDetector(EventsConfig()).detect(records, meta)
    contacts = [event for event in events if event.name == "person_contact"]
    assert contacts
    assert contacts[0].attacker == "person_0"
    assert contacts[0].receiver == "person_1"
    assert contacts[0].position is not None


def test_svg_rejects_scripts_and_library_resolves() -> None:
    assert not validate_svg('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
    assert validate_svg('<svg viewBox="0 0 10 10"><path d="M 0 0 L 10 10"/></svg>')
    assert resolve_glyph("heart") is not None
    assert resolve_glyph("no-existe-pero-love") is not None


def test_impact_and_grade_change_the_frame() -> None:
    effect = Effect(
        id="hit",
        type="impact_accent",
        target=EffectTarget(kind="event_point", id="contact"),
        time=EffectTime(start_frame=0, end_frame=10),
        style=EffectStyle(colors=[(1.0, 0.4, 0.1)], thickness=0.2, boil_frames=2),
        triggers=[],
    )
    runtime = EffectRuntime(effect, 1, 4)
    runtime.anchor_point = np.array([32.0, 48.0])
    layer = render_effect(runtime, None, {}, 3, 64, 96, 1.0, None, 20, MotionEvent(name="person_contact", target="person_0:right_wrist", start_frame=3, end_frame=5, confidence=1))
    assert layer[..., :3].sum() > 0
    grade = Effect(
        id="grade_beat",
        type="grade",
        target=EffectTarget(kind="mask", id="person"),
        style=EffectStyle(colors=[(0.2, 0.2, 0.6)], intensity=1),
        render=EffectRender(group="grade", blend="multiply"),
    )
    graded = render_effect(EffectRuntime(grade, 1, 4), None, {}, 0, 8, 8, 1.0, None, 10)
    plate = np.full((8, 8, 3), 200, dtype=np.uint8)
    out = composite_frame(plate, [(grade, graded)], Grade())
    assert int(out.mean()) < 200


def test_presets_and_plan_expand() -> None:
    for name in ("fight_comic", "doodle_dance", "paint_reveal"):
        script = load_preset(PRESETS / f"{name}.yaml", 90)
        assert script.effects
        assert preset_script(name, 90).theme == script.theme
    brief_choices = StrategyPlan(title="t", theme="mixed", choices=[Choice(beat=0, strategy="symbol_react", glyph="cloud")])
    from vfxglow.analysis.schema import MotionBrief

    brief = MotionBrief(
        video=_meta(),
        person_id="person_0",
        anchors=["nose"],
        limbs=[],
        events=[],
        summary="quieto",
    )
    script = expand(brief_choices, brief)
    assert any(effect.type == "glyph" for effect in script.effects)


def test_scene_reader_skips_without_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from vfxglow.analysis.schema import Beat

    beats = [Beat(id=0, start_frame=0, end_frame=3, kind="gesture")]
    assert read_scenes(tmp_path / "missing.mp4", beats, tmp_path / "cache") == []


def test_scene_reader_logs_tokens_and_caches(tmp_path: Path, monkeypatch, caplog) -> None:
    import logging

    from vfxglow.analysis import scene_reader
    from vfxglow.analysis.schema import Beat

    video = tmp_path / "v.mp4"
    frames = [np.full((96, 64, 3), 40 * i, np.uint8) for i in range(6)]
    write_silent_video(video, frames, 30)
    beats = [
        Beat(id=0, start_frame=0, end_frame=2, kind="gesture"),
        Beat(id=1, start_frame=3, end_frame=5, kind="gesture"),
    ]
    reply = {
        "usage": {"prompt_tokens": 300, "completion_tokens": 40},
        "choices": [{"message": {"content": '{"scene": "baile", "gesture": "g", "intent": "i", "objects": []}'}}],
    }
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(scene_reader, "_post", lambda *_args: reply)
    with caplog.at_level(logging.INFO, logger="vfxglow.scene"):
        first = read_scenes(video, beats, tmp_path / "cache")
        second = read_scenes(video, beats, tmp_path / "cache")
    assert [scene.scene for scene in first] == ["baile", "baile"]
    assert len(second) == 2
    lines = [record.getMessage() for record in caplog.records if "VLM" in record.getMessage()]
    assert "2 llamadas, 0 beats desde caché, 600 tokens de entrada, 80 de salida" in lines[0]
    assert "0 llamadas, 2 beats desde caché, 0 tokens" in lines[1]
