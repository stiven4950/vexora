"""Efectos del puño en alto (engine/fist.py)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from vfxglow.engine.bodyglow import Body
from vfxglow.engine.fist import fist_effect


def _hourglass(wrist: tuple[float, float]) -> float:
    pts = {
        "left_shoulder": np.array([230.0, 200.0]), "right_shoulder": np.array([170.0, 200.0]),
        "left_hip": np.array([220.0, 330.0]), "right_hip": np.array([180.0, 330.0]),
        "right_elbow": np.array([wrist[0], wrist[1] + 50.0]), "right_wrist": np.array(wrist),
        "left_ankle": np.array([215.0, 460.0]), "right_ankle": np.array([185.0, 460.0]),
    }
    body = Body(pts, None)
    runtime = SimpleNamespace(effect=SimpleNamespace(triggers=[]), active_frames=20, swoosh={}, kernels={})
    event = SimpleNamespace(start_frame=0, end_frame=40, kind="right", target="right_wrist")
    layer = np.zeros((500, 400, 4), np.float32)
    lines = fist_effect("hourglass", body, body.frame(), 60.0, 20, runtime, layer, np.array([1.0, 0.8, 0.2], np.float32), 1.0, event)
    return float(layer[..., 3].max()) + len(lines)


def test_hourglass_only_with_the_fist_away_from_the_torso() -> None:
    assert _hourglass((120.0, 150.0)) > 0  # puño a un costado: sale el reloj de arena
    assert _hourglass((185.0, 150.0)) == 0  # puño pegado al torso: no (quedaba encima de la persona)
