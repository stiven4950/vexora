"""Símbolos de la cara (engine/face_symbols.py) y criaturas que acompañan a la cabeza
(engine/head_companions.py)."""

from __future__ import annotations

import numpy as np
import pytest

from test_eye_family import _frame, _ink, _runtime
from test_face_glow import _body
from vfxglow.engine.face_makeup import MAKEUP
from vfxglow.engine.face_symbols import SYMBOLS
from vfxglow.engine.face_zone import coverage
from vfxglow.engine.head_companions import COMPANIONS


@pytest.mark.parametrize("shape", SYMBOLS + COMPANIONS)
def test_every_shape_draws_with_and_without_the_mesh(shape: str) -> None:
    for body in (_body(), _body(mesh=False)):
        runtime = _runtime(shape)
        assert max(_ink(*_frame(shape, runtime, f, body=body)) for f in range(0, 30, 3)) > 1.0


def _lit(layer: np.ndarray, box) -> float:
    x0, y0, x1, y1 = (int(v) for v in box)
    return float(layer[max(y0, 0) : y1, max(x0, 0) : x1, 3].sum())


def test_the_third_eye_opens_wider_when_the_brows_go_up() -> None:
    calm, raised = _runtime("third_eye"), _runtime("third_eye")
    rest = {"browInnerUp": 0.5}
    for f in range(30):
        a = _frame("third_eye", calm, f, rest)
        b = _frame("third_eye", raised, f, rest if f < 15 else {"browInnerUp": 0.95})
    assert _ink(*b) > _ink(*a)


def test_the_third_eye_does_not_fire_rays_when_it_appears() -> None:
    runtime = _runtime("third_eye")
    for f in range(8):
        _frame("third_eye", runtime, f, {"browInnerUp": 0.6})
    assert "rays" not in runtime.swoosh["_symbol:third_eye:0:" + _body().prefix]


def test_the_runes_reorganize_after_a_blink() -> None:
    runtime = _runtime("rune_shift")
    shut = {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9}
    for f in range(20):
        _frame("rune_shift", runtime, f)
    state = runtime.swoosh["_symbol:rune_shift:0:" + _body().prefix]
    before = state["glyph"]
    _frame("rune_shift", runtime, 20, shut)
    assert state["glyph"] == before + 1


def _with_forehead():
    """La malla sintética deja el punto 10 (la frente) en el óvalo, a la altura de la mejilla: aquí va
    donde lo pone MediaPipe, arriba en la frente."""
    body = _body()
    left, right = body.points["left_iris"], body.points["right_iris"]
    body.points["forehead_top"] = (left + right) / 2 - np.array([0.0, 1.1 * float(np.linalg.norm(left - right))])
    return body


def test_the_crown_grows_with_a_smile_and_stays_above_the_eyes() -> None:
    calm, smiling = _runtime("light_crown"), _runtime("light_crown")
    body = _with_forehead()
    for f in range(20):
        a = _frame("light_crown", calm, f, body=body)
        b = _frame("light_crown", smiling, f, {"mouthSmileLeft": 0.9, "mouthSmileRight": 0.9}, body=body)
    eyes_y = min(body.points["left_iris"][1], body.points["right_iris"][1])
    assert _lit(b[0], (0, 0, 400, eyes_y)) > _lit(a[0], (0, 0, 400, eyes_y))
    rows = np.nonzero(b[0][..., 3].max(axis=1) > 0.05)[0]
    assert rows.max() < eyes_y  # nada de la corona baja a los ojos


def test_butterflies_leave_the_eyes_and_fly_above_them() -> None:
    runtime = _runtime("eye_butterflies")
    for f in range(40):
        layer, _ = _frame("eye_butterflies", runtime, f)
    eyes_y = min(_body().points["left_iris"][1], _body().points["right_iris"][1])
    rows = np.nonzero(layer[..., 3].max(axis=1) > 0.05)[0]
    assert rows.max() < eyes_y + 10  # por arriba: nunca sobre la boca o el mentón


def test_a_blink_releases_another_butterfly() -> None:
    runtime = _runtime("eye_butterflies")
    shut = {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9}
    for f, expressions in enumerate([{}] * 20 + [shut, {}]):
        _frame("eye_butterflies", runtime, f, expressions)
    born = runtime.swoosh["_companion:eye_butterflies:0:" + _body().prefix]["born"]
    assert born[-1][0] == 20


def test_the_snake_stays_outside_the_face_and_comes_closer_with_the_mouth_open() -> None:
    body = _body()
    center = (body.points["left_iris"] + body.points["right_iris"]) / 2
    unit = float(np.linalg.norm(body.points["left_iris"] - body.points["right_iris"]))

    def closest(expressions) -> float:
        runtime = _runtime("holo_snake")
        for f in range(25):
            layer, _ = _frame("holo_snake", runtime, f, expressions)
        ys, xs = np.nonzero(layer[..., 3] > 0.2)
        return float(np.min(np.hypot(xs - center[0], ys - center[1]))) / unit

    shut_mouth, open_mouth = closest({}), closest({"jawOpen": 0.8})
    assert shut_mouth > 1.15
    assert open_mouth < shut_mouth


def test_symbols_and_companions_have_their_coverage() -> None:
    def cov(shape: str) -> str:
        return coverage({"type": "adornment", "style": {"shapes": [shape]}})

    assert cov("third_eye") == "low"
    assert cov("rune_shift") == "medium"
    assert {cov(s) for s in ("light_crown", "eye_butterflies", "holo_snake")} == {"peripheral"}


@pytest.mark.parametrize("shape", MAKEUP)
def test_every_makeup_draws_with_and_without_the_mesh(shape: str) -> None:
    for body in (_body(), _body(mesh=False)):
        runtime = _runtime(shape)
        assert max(_ink(*_frame(shape, runtime, f, body=body)) for f in range(0, 30, 3)) > 1.0


def test_the_butterfly_wings_fold_when_the_eyes_close() -> None:
    opened, closed = _runtime("butterfly_wings"), _runtime("butterfly_wings")
    for f in range(25):
        a = _frame("butterfly_wings", opened, f)
        b = _frame("butterfly_wings", closed, f, {"eyeBlinkLeft": 0.95, "eyeBlinkRight": 0.95})
    assert _ink(*b) < _ink(*a)


def test_the_pharaoh_mark_goes_on_the_forehead_and_under_the_eyes() -> None:
    body = _body()
    runtime = _runtime("pharaoh_mark")
    for f in range(30):
        layer, _ = _frame("pharaoh_mark", runtime, f, body=body)
    eyes_y = int(body.points["left_iris"][1])
    assert _lit(layer, (0, 0, 400, eyes_y - 15)) > 0 and _lit(layer, (0, eyes_y + 5, 400, eyes_y + 60)) > 0


def test_the_neon_pulse_runs_faster_with_a_smile() -> None:
    calm, smiling = _runtime("neon_veins"), _runtime("neon_veins")
    for f in range(30):
        _frame("neon_veins", calm, f)
        _frame("neon_veins", smiling, f, {"mouthSmileLeft": 0.9, "mouthSmileRight": 0.9})
    key = "_makeup:neon_veins:0:" + _body().prefix
    assert smiling.swoosh[key]["pulse"] > calm.swoosh[key]["pulse"]


def test_the_dissolve_wind_blows_harder_when_the_head_turns() -> None:
    still, turning = _runtime("face_dissolve"), _runtime("face_dissolve")
    for f in range(20):
        still.head_pose = (0.0, 0.0, 0.0)
        _frame("face_dissolve", still, f)
        turning.head_pose = (float(f * 4), 0.0, 0.0)
        _frame("face_dissolve", turning, f)
    key = "_makeup:face_dissolve:0:" + _body().prefix
    assert turning.swoosh[key]["time"] > still.swoosh[key]["time"]


def test_the_medusa_snakes_rise_with_the_mouth_open_and_stay_off_the_face() -> None:
    body = _body()
    center = (body.points["left_iris"] + body.points["right_iris"]) / 2
    unit = float(np.linalg.norm(body.points["left_iris"] - body.points["right_iris"]))
    shut, wide = _runtime("medusa_snakes"), _runtime("medusa_snakes")
    for f in range(30):
        a = _frame("medusa_snakes", shut, f)
        b = _frame("medusa_snakes", wide, f, {"jawOpen": 0.8})
    assert _ink(*b) > _ink(*a)
    ys, xs = np.nonzero(a[0][..., 3] > 0.2)
    below_eyes = ys > center[1]
    assert np.all(np.abs(xs[below_eyes] - center[0]) > 0.8 * unit)  # por debajo de los ojos, solo a los costados


def test_makeup_and_medusa_coverage() -> None:
    def cov(shape: str) -> str:
        return coverage({"type": "adornment", "style": {"shapes": [shape]}})

    assert {cov(s) for s in MAKEUP} == {"medium"}
    assert cov("medusa_snakes") == "peripheral"


def test_the_porcelain_cracks_open_with_a_strong_expression() -> None:
    calm, shouting = _runtime("porcelain_cracks"), _runtime("porcelain_cracks")
    for f in range(30):
        a = _frame("porcelain_cracks", calm, f)
        b = _frame("porcelain_cracks", shouting, f, {"jawOpen": 0.9})
    assert _ink(*b) > _ink(*a) * 1.5


def test_the_porcelain_cracks_never_enter_the_eyes_or_the_mouth() -> None:
    from vfxglow.engine.face_makeup import CRACK_KEEP_OUT, _crack_tree

    for seed in range(20):
        for side in (-1.0, 1.0):
            for local, _depth in _crack_tree(np.random.default_rng(seed), side):
                for (cx, cy), r in CRACK_KEEP_OUT:
                    assert np.all(np.hypot(local[1:, 0] - cx, local[1:, 1] - cy) >= r)


def test_what_goes_behind_the_head_hides_only_over_the_person() -> None:
    from vfxglow.engine.head_companions import _front

    mask = np.zeros((100, 100), np.uint8)
    mask[20:80, 40:60] = 1  # la persona, en el medio
    center = np.array([50.0, 50.0])
    above = np.stack([np.linspace(0, 99, 50), np.full(50, 30.0)], axis=1)  # por detrás de la cabeza
    below = np.stack([np.linspace(0, 99, 50), np.full(50, 70.0)], axis=1)  # por delante
    hidden = _front(above, None, center, mask)
    assert len(hidden) == 2 and all(not (45 < piece[:, 0].mean() < 55) for piece, _ in hidden)
    assert len(_front(below, None, center, mask)) == 1


def test_the_ambient_steps_aside_while_a_big_face_effect_is_on() -> None:
    from test_face_glow import FPS, H, N, POSE, W, _mesh
    from vfxglow.analysis.schema import FrameRecord, Landmark, MotionEvent, PersonPose
    from vfxglow.config import EngineConfig
    from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
    from vfxglow.engine.engine import EffectEngine

    pose = [Landmark(name=n, x=x, y=y, c=0.95) for n, (x, y) in POSE.items()]
    frames = [FrameRecord(frame=i, time_s=i / FPS, pose=pose, face=_mesh(), people=[PersonPose(person_id="person_0", pose=pose, face=_mesh())]) for i in range(N)]

    def effect(eid: str, shape: str) -> Effect:
        return Effect(id=eid, type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape], focus=False), triggers=[{"event": eid, "hold": 0}])

    script = EffectScript(title="t", theme="t", effects=[effect("halo", "head_halo"), effect("big", "pharaoh_mark")])
    events = [MotionEvent(name="halo", target="person_0", start_frame=0, end_frame=N - 1, confidence=1.0),
              MotionEvent(name="big", target="person_0", start_frame=20, end_frame=39, confidence=1.0)]
    engine = EffectEngine(script, EngineConfig(), events=events, fps=FPS)
    halo = {}
    for i in range(N):
        halo[i] = next(float(layer[..., 3].sum()) for eid, _g, layer in engine.render_frame(frames[i], i, W, H, N) if eid == "halo")
    assert halo[15] > 0  # solo, el halo se ve
    assert halo[32] < 0.05 * halo[15]  # con el emblema puesto, se apartó
    assert max(halo[k] for k in range(45, 55)) > 0.5 * halo[15]  # al irse el emblema, vuelve


def test_butterflies_come_in_several_species() -> None:
    from vfxglow.engine.head_companions import BUTTERFLY_SPECIES, _butterfly

    shapes = {}
    for species in BUTTERFLY_SPECIES:
        wings, details, _spots = _butterfly(np.zeros(2), 50.0, 1.0, -np.pi / 2, species)
        assert len(wings) == 4 and details
        shapes[species] = np.round(np.ptp(np.vstack(wings), axis=0), 0).tolist()
    assert len({tuple(v) for v in shapes.values()}) >= 5  # siluetas distintas


def test_older_eye_effects_vary_between_appearances() -> None:
    from vfxglow.engine.bodyglow import VARIED
    from vfxglow.engine.eye_family import pick_knobs

    assert "eye_flames" in VARIED and "cleopatra_eyes" in VARIED
    assert len({pick_knobs("eye_flames", "p0", s, {})["intensity"] for s in range(0, 300, 7)}) > 1


def _ear_top(lines, eyes_y: float) -> float:
    """La punta más alta de lo que dibuja la mirada felina sobre los ojos (las orejas)."""
    tops = [float(np.asarray(item[0])[:, 1].min()) for item in lines if np.asarray(item[0])[:, 1].min() < eyes_y - 30]
    return min(tops) if tops else eyes_y


def test_the_feline_ears_sit_on_the_head_and_flatten_with_a_frown() -> None:
    body = _with_forehead()
    eyes_y = float(body.points["left_iris"][1])
    calm, angry = _runtime("eyes_feline"), _runtime("eyes_feline")
    for f in range(25):
        _, a = _frame("eyes_feline", calm, f, body=body)
        _, b = _frame("eyes_feline", angry, f, {"browDownLeft": 0.9, "browDownRight": 0.9}, body=body)
    assert _ear_top(a, eyes_y) < body.points["forehead_top"][1]  # por encima de la frente
    assert _ear_top(b, eyes_y) > _ear_top(a, eyes_y)  # con el ceño se aplanan (la punta baja)


def test_the_feline_ears_twitch_after_a_blink() -> None:
    body = _with_forehead()
    runtime = _runtime("eyes_feline")
    shut = {"eyeBlinkLeft": 0.9, "eyeBlinkRight": 0.9}
    for f, expressions in enumerate([{}] * 20 + [shut]):
        _frame("eyes_feline", runtime, f, expressions, body=body)
    state = runtime.swoosh["_eyes:eyes_feline:0:" + body.prefix]
    assert state["twitch"] == 20
