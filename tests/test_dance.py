"""Baile: parte del cuerpo encendida, adornos, modo tint y foco por parte."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.analysis.schema import FrameRecord, Landmark, PersonPose
from vfxglow.composite.composite import _blend
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.bodyglow import ADORNMENTS, PARTS, Body, adornment, part_mask
from vfxglow.engine.engine import EffectEngine


def _pose() -> list[Landmark]:
    pts = {
        "nose": (0.5, 0.2), "left_ear": (0.46, 0.21), "right_ear": (0.54, 0.21),
        "left_shoulder": (0.4, 0.3), "right_shoulder": (0.6, 0.3), "left_elbow": (0.32, 0.42), "right_elbow": (0.68, 0.42),
        "left_wrist": (0.3, 0.54), "right_wrist": (0.7, 0.54), "left_hip": (0.44, 0.55), "right_hip": (0.56, 0.55),
        "left_knee": (0.44, 0.72), "right_knee": (0.56, 0.72), "left_ankle": (0.44, 0.9), "right_ankle": (0.56, 0.9),
    }
    return [Landmark(name=k, x=x, y=y, c=0.95) for k, (x, y) in pts.items()]


def _points(scale: int = 200) -> dict[str, np.ndarray]:
    return {lm.name: np.array([lm.x * scale, lm.y * scale]) for lm in _pose()}


@pytest.mark.parametrize("part", PARTS)
def test_every_part_has_a_mask(part: str) -> None:
    mask = part_mask(Body(_points(), None), part, (200, 200), 40.0)
    assert mask is not None and mask.sum() > 50


@pytest.mark.parametrize("shape", ADORNMENTS)
def test_every_adornment_draws(shape: str) -> None:
    from vfxglow.engine.effects import EffectRuntime

    points = _points()
    from vfxglow.engine.costumes import FACE, NECK

    if shape in ("claws", "fire_whip"):
        pytest.skip("necesitan la velocidad o la trayectoria de la mano (se prueban con video)")
    if shape in ("fire_wall", "fire_light", "fire_carpet_end"):
        pytest.skip("se encienden solas (el cierre, o la luz del fuego de los demás efectos): se prueban con video")
    if shape in ("fire_phoenix", "fire_dragon_launch"):
        pytest.skip("nacen al lanzar (crecen en los primeros cuadros del gesto): se prueban en test_elements")
    if shape in ("water_ribbon", "water_stream", "water_ring", "water_splash", "water_refract", "air_slash", "air_dash", "air_vortex", "air_burst", "air_refract", "earth_fist", "earth_orbit", "earth_slam", "earth_crystals"):
        pytest.skip("crecen en los primeros cuadros, o refractan el agua o el aire de otro efecto: se prueban en test_water, test_air y test_earth")
    if shape in ("ecg_arm", "sky_bolt", "thought_cloud", "kick_bolt"):
        pytest.skip("se trazan o caen en los primeros cuadros del gesto: se prueban en test_solo_fx")
    if shape in FACE + NECK + ("battery", "hero_text", "venom", "iron_man"):
        # Van sobre la cara o el pecho: de frente (la pose de prueba está de espaldas).
        points = {name.replace("left", "@").replace("right", "left").replace("@", "right"): p for name, p in points.items()}
    body = Body(points, None)
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="nose"))
    runtime = EffectRuntime(effect, 1, 10)
    layer = np.zeros((200, 200, 4), np.float32)
    lines = adornment(shape, body, body.frame(), 40.0, 0, 1, runtime, layer, np.array([1, 0, 1], np.float32), 1.0)
    from vfxglow.engine.waterbend import flush_water

    flush_water(layer, 0)  # el agua se pinta al final, como el fuego
    assert lines or layer[..., 3].max() > 0


def test_body_glow_tint_and_outline_passes() -> None:
    track = FrameRecord(frame=0, time_s=0.0, pose=_pose(), people=[PersonPose(person_id="person_0", pose=_pose())])
    tint = Effect(id="t", type="body_glow", target=EffectTarget(kind="joint", id="torso"),
                  style=EffectStyle(colors=[(0, 1, 0)], shapes=["no_outline"], fill=0.85))
    line = Effect(id="l", type="body_glow", target=EffectTarget(kind="joint", id="torso"),
                  style=EffectStyle(colors=[(0, 1, 0)], shapes=["abs"], fill=0.0))
    layers = EffectEngine(EffectScript(title="t", theme="t", effects=[tint, line]), EngineConfig()).render_frame(track, 8, 200, 200, 20)  # pasado el fundido de entrada
    fill, outline = layers[0][2], layers[1][2]
    assert fill[int(0.42 * 200), 100, 3] > 0.5  # el torso queda teñido
    assert outline[int(0.42 * 200), 100, 3] > 0.2  # línea alba de los abdominales
    assert fill[10, 10, 3] == 0


def test_tint_blend_dyes_but_keeps_light() -> None:
    base = np.array([[[0.5, 0.5, 0.5], [0.1, 0.1, 0.1]]], np.float32)
    green = np.array([[[0.0, 0.9, 0.0], [0.0, 0.9, 0.0]]], np.float32)
    out = _blend(base, green, np.ones((1, 2), np.float32), "tint")
    assert out[0, 0, 1] > out[0, 0, 0] and out[0, 1, 1] > out[0, 1, 0]
    assert out[0, 0, 1] > out[0, 1, 1]  # lo claro sigue más claro que lo oscuro
