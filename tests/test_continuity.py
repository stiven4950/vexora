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
