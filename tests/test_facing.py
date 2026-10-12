"""Frente o espalda: el dibujo del torso tiene sentido según hacia dónde mira la persona."""

from __future__ import annotations

import numpy as np

from vfxglow.engine.bodyglow import Body, abs_lines, badge_lines, facing, torso_drawing


def _body(dx: float) -> Body:
    """Hombro izquierdo de la persona a `dx` px a la derecha del derecho (negativo = de espaldas)."""
    return Body(
        {
            "left_shoulder": np.array([200.0 + dx / 2, 300.0]),
            "right_shoulder": np.array([200.0 - dx / 2, 300.0]),
            "left_hip": np.array([200.0 + dx / 3, 560.0]),
            "right_hip": np.array([200.0 - dx / 3, 560.0]),
        },
        None,
    )


def test_facing_from_shoulder_order() -> None:
    assert facing(_body(150)) == "front"
    assert facing(_body(-120)) == "back"
    assert facing(_body(10)) == "side"


def test_no_abs_on_the_back_and_nothing_in_profile() -> None:
    rng = np.random.default_rng(0)
    back = torso_drawing(_body(-150), ["abs", "back_lines"], rng)
    front = abs_lines(_body(150))
    assert back and len(back) != len(front)
    assert torso_drawing(_body(10), ["abs"], rng) == []


def test_badge_is_round_and_centered_on_the_back() -> None:
    body = _body(-150)
    (outer, *_rest) = badge_lines(body, "radiation")
    width, height = np.ptp(outer[:, 0]), np.ptp(outer[:, 1])
    assert abs(width - height) < 0.15 * width
    assert 300 < outer[:, 1].mean() < 560


def test_partial_keeps_only_some_lines() -> None:
    full = torso_drawing(_body(150), ["abs"], np.random.default_rng(1))
    partial = torso_drawing(_body(150), ["abs", "partial"], np.random.default_rng(1))
    assert 2 <= len(partial) < len(full)
