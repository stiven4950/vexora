"""Continuidad entre dibujos: el adorno que se va se convierte en el que llega (pedido del usuario)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from vfxglow.engine.bodyglow import CONTINUITY, MORPH_FRAMES, _continuity, _handed_off


def _runtime(effect_id: str, relay: dict) -> SimpleNamespace:
    return SimpleNamespace(effect=SimpleNamespace(id=effect_id), relay=relay, swoosh={}, active_frames=0)


def _line(y: float) -> list:
    return [(np.array([[0.0, y], [10.0, y]]), np.array([1.0, 0.0, 0.0], np.float32))]


def _runs_into(effect_id: str) -> bool:
    """Si el adorno `effect_id`, al empezar justo después de otro, arranca convirtiendo su dibujo."""
    relay: dict = {}
    old, new = _runtime("old", relay), _runtime(effect_id, relay)
    for f in range(5):
        old.active_frames = f + 1
        _continuity(old, "person_0", f, _line(0.0), 0)
    new.active_frames = 1
    pairs, morphing = _continuity(new, "person_0", 6, _line(100.0), 6)
    if morphing:
        assert 0.0 < pairs[0][0][0, 1] < 100.0  # a mitad de camino entre los dos dibujos
    return morphing


def test_about_forty_percent_of_changes_are_continuous() -> None:
    share = np.mean([_runs_into(f"effect_{k}") for k in range(400)])
    assert abs(share - CONTINUITY) < 0.07


def test_the_morph_ends_on_the_new_drawing_and_the_old_one_stops() -> None:
    effect_id = next(f"effect_{k}" for k in range(400) if _runs_into(f"effect_{k}"))
    relay: dict = {}
    old, new = _runtime("old", relay), _runtime(effect_id, relay)
    for f in range(5):
        old.active_frames = f + 1
        _continuity(old, "person_0", f, _line(0.0), 0)
    new.active_frames = 1
    _continuity(new, "person_0", 6, _line(100.0), 6)
    assert _handed_off(old, "person_0", 7)  # el anterior ya no se dibuja
    new.active_frames = MORPH_FRAMES + 1
    pairs, morphing = _continuity(new, "person_0", 6 + MORPH_FRAMES, _line(100.0), 6)
    assert not morphing and np.allclose(pairs[0][0][:, 1], 100.0)


def test_a_late_start_does_not_morph() -> None:
    relay: dict = {}
    old, new = _runtime("old", relay), _runtime("x", relay)
    old.active_frames = 1
    _continuity(old, "person_0", 0, _line(0.0), 0)
    new.active_frames = 1
    assert _continuity(new, "person_0", 200, _line(100.0), 200)[1] is False


def _relay(effect_id: str, old_pairs: list, new_pairs: list, zone_old=None, zone_new=None, fps: float = 30.0):
    relay: dict = {}
    old, new = _runtime("old", relay), _runtime(effect_id, relay)
    new.fps = fps
    for f in range(5):
        old.active_frames = f + 1
        _continuity(old, "person_0", f, old_pairs, 0, zone_old)
    new.active_frames = 1
    return new, _continuity(new, "person_0", 6, new_pairs, 6, zone_new)


MORPHING = next(f"effect_{k}" for k in range(400) if _runs_into(f"effect_{k}"))
RED = np.array([1.0, 0.0, 0.0], np.float32)


def _dot(x: float, y: float, *style) -> tuple:
    return (np.array([[x - 1.0, y], [x + 1.0, y]]), RED, *style)


def test_each_line_travels_to_the_nearest_one_not_to_the_same_order() -> None:
    """Entre efectos distintos el orden no dice nada: el ojo izquierdo va al izquierdo."""
    old = [_dot(0.0, 0.0), _dot(100.0, 0.0)]
    new = [_dot(102.0, 5.0), _dot(2.0, 5.0)]  # el mismo par, en el orden contrario
    _, (pairs, morphing) = _relay(MORPHING, old, new)
    assert morphing
    xs = sorted(float(p[0][:, 0].mean()) for p in pairs)
    assert xs[0] < 10.0 and xs[1] > 90.0  # nadie cruzó al otro lado


def test_a_fine_line_keeps_its_stroke_while_it_morphs() -> None:
    _, (pairs, morphing) = _relay(MORPHING, _line(0.0), [(np.array([[0.0, 100.0], [10.0, 100.0]]), RED, 1.5)])
    assert morphing and all(len(p) == 3 and p[2] == 1.5 for p in pairs)


def test_a_head_drawing_does_not_turn_into_a_body_one() -> None:
    _, (_, morphing) = _relay(MORPHING, _line(0.0), _line(100.0), "head", "body")
    assert not morphing


def test_the_morph_lasts_the_same_time_at_any_frame_rate() -> None:
    new, _ = _relay(MORPHING, _line(0.0), _line(100.0), fps=15.0)
    half = MORPH_FRAMES // 2  # a 15 fps, la mitad de cuadros
    new.active_frames = half + 1
    _, morphing = _continuity(new, "person_0", 6 + half, _line(100.0), 6)
    assert not morphing
