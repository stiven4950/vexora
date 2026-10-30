"""Efectos largos de la cara, reacciones, cabeza, hadas y la desintegración en polvo."""

from __future__ import annotations

import numpy as np
import pytest

from vfxglow.analysis.cast import _set_main
from vfxglow.analysis.expressions import expression_events, gaze_vector
from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent, PersonPose
from vfxglow.director.schema import Effect, EffectStyle, EffectTarget
from vfxglow.director.seasons import Moment, Season, apply_to_catalog, moment_effect
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.dissolve import disintegrate
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.face_creatures import CREATURES
from vfxglow.engine.face_moods import MOODS
from vfxglow.engine.face_wounds import WOUNDS
from vfxglow.engine.face_zone import on_face
from vfxglow.engine.head_beasts import BEASTS, _fairy_at
from vfxglow.engine.horror_masks import HORROR_MASKS
from vfxglow.engine.living_fx import LIVING
from vfxglow.engine.raven import raven_shape

KERNELS: dict = {}


def _body() -> Body:
    points = {"nose": np.array([200.0, 130.0]), "right_iris": np.array([180.0, 110.0]), "left_iris": np.array([220.0, 110.0]),
              "left_shoulder": np.array([250.0, 200.0]), "right_shoulder": np.array([150.0, 200.0]),
              "left_hip": np.array([240.0, 330.0]), "right_hip": np.array([160.0, 330.0])}
    return Body(points, None)


def _frames(rows: list[dict]) -> list[FrameRecord]:
    return [FrameRecord(frame=k, time_s=k / 30.0, person_id="person_0", expressions=row) for k, row in enumerate(rows)]


@pytest.mark.parametrize("shape", CREATURES + WOUNDS + MOODS + BEASTS + LIVING)
def test_every_new_shape_draws_something(shape: str) -> None:
    body = _body()
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": "x", "hold": 90}])
    event = MotionEvent(name="x", target="person_0", start_frame=0, end_frame=9, confidence=1.0, kind="left")
    runtime = EffectRuntime(effect, 1, 10)
    runtime.expressions = {}
    drew = False
    for f in range(1, 100, 3):
        runtime.active_frames = f
        layer = np.zeros((500, 500, 4), np.float32)
        items = adornment(shape, body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        drew = drew or bool(items) or float(layer[..., 3].max()) > 0
    assert drew


def test_creatures_walk_in_and_out_and_the_face_area_knows_them() -> None:
    for shape in CREATURES + WOUNDS + ("snake_band", "red_horns", "kiss_blow", "gaze_burst"):
        assert on_face({"type": "adornment", "style": {"shapes": [shape]}})
    for shape in ("fairies", "skeleton_dance", "death_hook"):
        assert not on_face({"type": "adornment", "style": {"shapes": [shape]}})


def test_dust_spreads_far_beyond_the_drawing_and_lines_go_away() -> None:
    line = np.stack([np.linspace(200, 300, 40), np.full(40, 250.0)], axis=1)
    sources = [(line, np.array([0.0, 1.0, 1.0], np.float32))]
    layer = np.zeros((500, 500, 4), np.float32)
    early = disintegrate(sources, 0.1, 50.0, layer, 1.0, {}, 3)
    assert early
    layer = np.zeros((500, 500, 4), np.float32)
    assert disintegrate(sources, 0.8, 50.0, layer, 1.0, {}, 3) == []
    ys, xs = np.nonzero(layer[..., 3] > 0.01)
    assert xs.max() - xs.min() > 200  # mucho más ancho que la línea de partida


def test_gaze_shift_and_what_is_not_one() -> None:
    def look(x: float) -> dict:
        return {"eyeLookOutLeft": max(x, 0.0), "eyeLookInRight": max(x, 0.0), "eyeLookInLeft": max(-x, 0.0), "eyeLookOutRight": max(-x, 0.0), "eyeBlinkLeft": 0.0, "eyeBlinkRight": 0.0}

    assert gaze_vector(look(0.5)) == pytest.approx((0.5, 0.0))
    rows = [look(0.0)] * 30 + [look(0.6)] * 30
    events = [e for e in expression_events(_frames(rows), 30.0) if e.name == "gaze_shift"]
    assert len(events) == 1 and events[0].kind == "left"
    # Al parpadear las expresiones marcan que mira abajo: no es un cambio de mirada.
    blink = [dict(look(0.0), eyeLookDownLeft=0.8, eyeLookDownRight=0.8, eyeBlinkLeft=0.9, eyeBlinkRight=0.9)] * 3
    rows = [look(0.0)] * 30 + blink + [look(0.0)] * 30
    assert not [e for e in expression_events(_frames(rows), 30.0) if e.name == "gaze_shift"]


def test_surprise_needs_brows_with_eyes_or_mouth() -> None:
    calm = {"browInnerUp": 0.1, "eyeWideLeft": 0.0, "eyeWideRight": 0.0, "jawOpen": 0.0}
    only_brows = dict(calm, browInnerUp=0.8)
    shocked = dict(only_brows, jawOpen=0.5)
    assert not [e for e in expression_events(_frames([calm] * 40 + [only_brows] * 20), 30.0) if e.name == "surprise"]
    assert [e for e in expression_events(_frames([calm] * 40 + [shocked] * 20), 30.0) if e.name == "surprise"]
    # La boca muy abierta basta (asombro con las cejas quietas), pero con los ojos entrecerrados es un grito.
    gasp = dict(calm, jawOpen=0.7)
    scream = dict(gasp, eyeSquintLeft=0.5, eyeSquintRight=0.5)
    assert [e for e in expression_events(_frames([calm] * 40 + [gasp] * 20), 30.0) if e.name == "surprise"]
    assert not [e for e in expression_events(_frames([calm] * 40 + [scream] * 20), 30.0) if e.name == "surprise"]


def test_eyes_wide_at_real_values_and_a_tense_mouth_is_no_kiss() -> None:
    calm = {"eyeWideLeft": 0.01, "eyeWideRight": 0.01, "mouthPucker": 0.01}
    wide = dict(calm, eyeWideLeft=0.15, eyeWideRight=0.14)  # así de bajo marca en una cara real
    assert [e for e in expression_events(_frames([calm] * 40 + [wide] * 10), 30.0) if e.name == "eyes_wide"]
    kiss = dict(calm, mouthPucker=0.9)
    assert [e for e in expression_events(_frames([calm] * 40 + [kiss] * 10), 30.0) if e.name == "pucker"]
    for tense in (dict(kiss, browDownLeft=0.5), dict(kiss, jawOpen=0.5)):  # enojo, o hablar con labios redondos
        assert not [e for e in expression_events(_frames([calm] * 40 + [tense] * 10), 30.0) if e.name == "pucker"]


def test_catalog_durations_follow_the_video_fps() -> None:
    from vfxglow.director.choreography import Catalog, Option, Reaction, at_fps

    option = Option(name="o", cooldown=300, effects=[{"type": "adornment", "trigger": {"hold": 90, "fade_in": 1, "fade_out": 6}}])
    catalog = Catalog(name="c", title="C", reactions=[Reaction(action="still", cooldown=60, options=[option])])
    assert at_fps(catalog, 29.97) is catalog
    slow = at_fps(catalog, 15.0)
    trigger = slow.reactions[0].options[0].effects[0]["trigger"]
    assert (trigger["hold"], trigger["fade_out"], trigger["fade_in"]) == (45, 3, 1)
    assert slow.reactions[0].options[0].cooldown == 150 and slow.reactions[0].cooldown == 30
    assert catalog.reactions[0].options[0].effects[0]["trigger"]["hold"] == 90  # el original no se toca


def test_time_is_counted_as_if_at_30_fps() -> None:
    from types import SimpleNamespace

    from vfxglow.engine.face_glow import paced, steps

    slow = SimpleNamespace(fps=15.0)
    assert paced(100, slow) == 200 and steps(slow) == 2
    assert paced(100, SimpleNamespace(fps=30.0)) == 100 and steps(SimpleNamespace(fps=60.0)) == 1


def test_the_face_mesh_survives_choosing_the_lead() -> None:
    mesh = [Landmark(name="face_1", x=0.5, y=0.3, z=0.0, c=0.9)]
    record = FrameRecord(frame=0, time_s=0.0, person_id="person_0", face=mesh)
    _set_main(record, PersonPose(person_id="person_0", box=(0.2, 0.1, 0.8, 0.9)))
    assert record.face == mesh
    _set_main(record, PersonPose(person_id="person_0", box=(0.6, 0.1, 0.9, 0.9)))
    assert record.face is None  # la cara era de otra persona
    record.face = mesh
    _set_main(record, None)
    assert record.face is None


def test_fairies_go_low_in_front_so_they_do_not_cross_the_face() -> None:
    center = np.array([0.0, 0.0])
    for frame in range(0, 400, 7):
        for k in range(4):
            at, depth = _fairy_at(center, 100.0, float(frame), k)
            if depth > 0.8:
                assert at[1] > 40.0


def test_terror_moment_draws_any_of_the_faces_and_season_adds_ambient() -> None:
    season = Season(id="s", title="S", ambient=[{"type": "adornment", "style": {"shapes": ["fairies"]}}])
    effect = moment_effect(season, Moment(action="still", moment="terror", size=2.4))
    assert set(effect["style"]["shapes"]) == set(HORROR_MASKS) and len(HORROR_MASKS) == 24
    from vfxglow.director.choreography import Catalog

    catalog = Catalog(name="c", title="C", reactions=[])
    assert apply_to_catalog(catalog, season).always[-1]["style"]["shapes"] == ["fairies"]


def test_loudness_is_relative_to_the_video() -> None:
    from vfxglow.analysis.voice import RATE, loudness

    tone = np.sin(np.linspace(0, 2000, RATE)) * 0.02  # un video grabado bajo
    levels = loudness(np.concatenate([tone, np.zeros(RATE)]), 30.0, 60)
    assert levels[:30].min() > 0.8 and levels[30:].max() == 0.0


def test_speaking_needs_sound_and_a_moving_mouth() -> None:
    def talk(moves: bool) -> list[FrameRecord]:
        rows = [{"jawOpen": 0.3 * (k % 4 == 0) if moves else 0.0} for k in range(60)]
        frames = _frames(rows)
        for frame in frames:
            frame.voice = 0.9
        return frames

    assert [e for e in expression_events(talk(True), 30.0) if e.name == "speaking"]
    assert not [e for e in expression_events(talk(False), 30.0) if e.name == "speaking"]  # música de fondo


def test_the_flame_follows_how_open_the_mouth_is() -> None:
    body = _body()
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["dragon_breath"]), triggers=[{"event": "x", "hold": 60}])
    event = MotionEvent(name="x", target="person_0", start_frame=0, end_frame=0, confidence=1.0)

    def reach(jaw: float) -> float:
        """Hasta dónde llega lo que brilla de verdad, medido desde la boca (el resplandor no cuenta)."""
        runtime = EffectRuntime(effect, 1, 10)
        runtime.expressions = {"jawOpen": jaw}
        far = 0.0
        for f in range(1, 40):
            runtime.active_frames = f
            layer = np.zeros((600, 700, 4), np.float32)
            adornment("dragon_breath", body, body.frame(), body.scale, f, 1, runtime, layer, np.array([1, 0.5, 0], np.float32), 1.0, event=event)
            ys, xs = np.nonzero(layer[..., 3] > 0.25)
            if len(xs):
                far = max(far, float(np.hypot(xs - 200.0, ys - 150.0).max()))
        return far

    assert reach(0.6) > reach(0.0)


def test_raven_morphs_between_flying_and_perched() -> None:
    at = np.array([100.0, 100.0])
    flying, perched = raven_shape(at, 50.0, 1.0, 0.5, 0.0), raven_shape(at, 50.0, 1.0, 0.5, 1.0)
    assert "far" in flying and "far" not in perched  # el ala de atrás se esconde
    assert perched["legs"] and not flying["legs"]
    assert len(flying["body"]) == len(perched["body"])  # la misma silueta, sin salto al aterrizar
    half = raven_shape(at, 50.0, 1.0, 0.5, 0.5)
    assert np.allclose(half["body"], (flying["body"] + perched["body"]) / 2)
