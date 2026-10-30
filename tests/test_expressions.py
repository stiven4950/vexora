"""Expresiones de la cara como eventos (catálogo `cara`)."""

from __future__ import annotations

from vfxglow.analysis.expressions import expression_events
from vfxglow.analysis.schema import FrameRecord, Landmark

FPS = 30.0


def _frames(n: int, values=None, head=None) -> list[FrameRecord]:
    """`values(k)` y `head(k)` dan las expresiones y la cabeza del cuadro k."""
    out = []
    for k in range(n):
        expr = {"jawOpen": 0.05, "eyeBlinkLeft": 0.05, "eyeBlinkRight": 0.05, "mouthSmileLeft": 0.2, "mouthSmileRight": 0.2, "browInnerUp": 0.1}
        expr.update(values(k) if values else {})
        out.append(FrameRecord(frame=k, time_s=k / FPS, pose=[Landmark(name="nose", x=0.5, y=0.3, c=0.9)],
                               expressions=expr, head_pose=head(k) if head else (0.0, 0.0, 0.0)))
    return out


def _names(frames) -> list[tuple[str, str]]:
    return [(e.name, e.kind) for e in expression_events(frames, FPS)]


def test_mouth_open_and_a_blink() -> None:
    frames = _frames(60, lambda k: {"jawOpen": 0.7} if 10 <= k < 25 else {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9} if 40 <= k < 44 else {})
    # Sostenida, la boca bien abierta también cuenta como impresión.
    assert _names(frames) == [("mouth_open", ""), ("surprise", ""), ("blink", "")]


def test_eyes_closed_long_is_not_a_blink_and_one_eye_is_a_wink() -> None:
    closed = _frames(60, lambda k: {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9} if 10 <= k < 40 else {})
    assert ("blink", "") not in _names(closed)
    wink = _frames(40, lambda k: {"eyeBlinkLeft": 0.9} if 10 <= k < 20 else {})
    assert _names(wink) == [("wink", "left")]


def test_smile_counts_against_the_usual_face() -> None:
    # Siempre sonriendo un poco (0,55): no es un evento; solo cuando sube por encima de lo habitual.
    usual = _frames(90, lambda k: {"mouthSmileLeft": 0.55, "mouthSmileRight": 0.55})
    assert _names(usual) == []
    bigger = _frames(90, lambda k: {"mouthSmileLeft": 0.85, "mouthSmileRight": 0.85} if 30 <= k < 50 else {"mouthSmileLeft": 0.55, "mouthSmileRight": 0.55})
    assert _names(bigger) == [("smile", "")]


def test_head_turn_and_tilt() -> None:
    turn = _frames(60, head=lambda k: (0.0 if k < 20 else min((k - 20) * 3.0, 40.0), 0.0, 0.0))
    assert ("head_turn", "left") in _names(turn)
    tilt = _frames(60, head=lambda k: (0.0, 0.0, 20.0 if 20 <= k < 40 else 0.0))
    assert ("head_tilt", "left") in _names(tilt)


def test_no_expressions_no_events() -> None:
    assert expression_events([FrameRecord(frame=k, time_s=k / FPS) for k in range(30)], FPS) == []
