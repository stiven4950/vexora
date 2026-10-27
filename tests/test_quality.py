"""Avisos de calidad del video con pistas y brief sintéticos."""

from __future__ import annotations

from vfxglow.analysis.quality import quality_warnings
from vfxglow.analysis.schema import FrameRecord, Landmark, MotionBrief, VideoMeta


def brief(duration: float = 10.0, people: list[str] | None = None) -> MotionBrief:
    video = VideoMeta(path="v.mp4", fps=30.0, width=720, height=1280, frame_count=int(duration * 30), duration_s=duration)
    return MotionBrief(video=video, person_id="person_0", anchors=[], limbs=[], events=[], summary="", people=people or ["person_0"])


def frame(i: int, top: float = 0.2, bottom: float = 0.8, posed: bool = True, **fields) -> FrameRecord:
    """Persona de pie entre `top` (nariz) y `bottom` (tobillos), con caja del mismo alto."""
    pose = [Landmark(name="nose", x=0.5, y=top, c=0.99), Landmark(name="left_ankle", x=0.45, y=bottom, c=0.99), Landmark(name="right_ankle", x=0.55, y=bottom, c=0.99)]
    return FrameRecord(frame=i, time_s=i / 30, pose=pose if posed else [], box=(0.3, top, 0.7, bottom) if posed else None, **fields)


def codes(b: MotionBrief, tracks: list[FrameRecord]) -> list[str]:
    return [w.code for w in quality_warnings(b, tracks)]


def test_a_well_framed_video_has_no_warnings() -> None:
    assert codes(brief(), [frame(i) for i in range(100)]) == []


def test_no_person() -> None:
    warnings = quality_warnings(brief(), [frame(i, posed=False) for i in range(100)])
    assert [(w.code, w.level) for w in warnings] == [("no_person", "warn")]
    assert "cuerpo entero" in warnings[0].detail
    assert codes(brief(), []) == ["no_person"]


def test_low_tracking_names_the_percentage() -> None:
    tracks = [frame(i, posed=i < 60) for i in range(100)]
    [warning] = quality_warnings(brief(), tracks)
    assert warning.code == "low_tracking" and warning.level == "warn" and "60 %" in warning.detail


def test_cut_off_when_feet_or_head_leave_the_frame() -> None:
    assert codes(brief(), [frame(i, bottom=1.0) for i in range(100)]) == ["cut_off"]
    assert codes(brief(), [frame(i, top=0.0) for i in range(100)]) == ["cut_off"]
    # Solo una parte pequeña del tiempo: sin aviso.
    assert codes(brief(), [frame(i, bottom=1.0 if i < 20 else 0.8) for i in range(100)]) == []


def test_small_person() -> None:
    assert codes(brief(), [frame(i, top=0.4, bottom=0.55) for i in range(100)]) == ["small_person"]


def test_many_people_by_tracked_count_or_silhouettes() -> None:
    assert codes(brief(people=[f"person_{i}" for i in range(4)]), [frame(i) for i in range(100)]) == ["many_people"]
    crowd = [[(0.0, 0.0), (0.1, 0.1), (0.0, 0.1)]] * 5
    assert codes(brief(), [frame(i, body_contours=crowd) for i in range(100)]) == ["many_people"]


def test_short_video_is_info() -> None:
    [warning] = quality_warnings(brief(duration=2.0), [frame(i) for i in range(60)])
    assert (warning.code, warning.level) == ("short", "info")
