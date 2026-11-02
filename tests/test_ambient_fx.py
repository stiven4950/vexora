"""Lo que llena el espacio alrededor del rostro: regiones, ambiente, láser, mini yo y emociones."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from vfxglow.analysis.expressions import frown_spans
from vfxglow.analysis.gestures import GESTURE_DETECTORS, GESTURE_NAMES
from vfxglow.analysis.regions import BACKGROUND, GARMENT, HAIR, MODEL_CLOTHES, MODEL_OTHER, SKIN, clean_labels, load_regions, person_mask
from vfxglow.analysis.schema import FrameRecord, MotionBrief, MotionEvent, VideoMeta
from vfxglow.director.choreography import ambient_events, choreograph, load_catalog
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.ambient_fx import AMBIENT, _edges
from vfxglow.engine.bodyglow import Body, adornment
from vfxglow.engine.effects import EffectRuntime
from vfxglow.engine.engine import needs_regions
from vfxglow.engine.face_moods import EMOTION_OF
from vfxglow.engine.face_zone import on_face

ROOT = Path(__file__).resolve().parents[1]
W, H, FPS = 400, 600, 30.0


def _labels(size: tuple[int, int] = (H, W)) -> np.ndarray:
    """Una persona: pelo arriba, prenda abajo; el resto es fondo."""
    labels = np.zeros(size, np.uint8)
    labels[80:220, 130:270] = HAIR
    labels[220:600, 90:310] = GARMENT
    return labels


def _body() -> Body:
    points = {"nose": np.array([200.0, 150.0]), "right_iris": np.array([180.0, 130.0]), "left_iris": np.array([220.0, 130.0]),
              "left_shoulder": np.array([270.0, 240.0]), "right_shoulder": np.array([130.0, 240.0]),
              "left_hip": np.array([250.0, 500.0]), "right_hip": np.array([150.0, 500.0])}
    return Body(points, None)


def _draw_all(shape: str, labels: np.ndarray | None, event_name: str = "ambient") -> tuple[bool, np.ndarray]:
    body = _body()
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]), triggers=[{"event": event_name, "hold": 60}])
    event = MotionEvent(name=event_name, target="person_0", start_frame=0, end_frame=0, confidence=1.0)
    runtime = EffectRuntime(effect, 1, 10)
    runtime.expressions = {}
    runtime.regions = labels
    drew = False
    last = np.zeros((H, W, 4), np.float32)
    for f in range(1, 58, 2):
        runtime.active_frames = f
        layer = np.zeros((H, W, 4), np.float32)
        items = adornment(shape, body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        drew = drew or bool(items) or float(layer[..., 3].max()) > 0
        last = np.maximum(last, layer)
    return drew, last


def test_a_garment_split_by_the_model_comes_back_whole() -> None:
    raw = np.zeros((200, 200), np.uint8)
    raw[100:200, 40:160] = MODEL_CLOTHES
    raw[120:180, 40:90] = MODEL_OTHER  # facial_3, 11,5 s: medio suéter como "otros"
    labels = clean_labels(raw)
    assert (labels[raw > 0] == GARMENT).all()


def test_stains_outside_the_person_go_away() -> None:
    raw = np.zeros((200, 200), np.uint8)
    raw[60:200, 40:160] = MODEL_CLOTHES
    raw[5:15, 150:170] = MODEL_OTHER
    assert clean_labels(raw)[10, 160] == BACKGROUND


def test_a_stain_stuck_to_the_hair_is_not_the_person() -> None:
    raw = np.zeros((200, 200), np.uint8)
    raw[60:120, 60:140] = HAIR
    raw[120:200, 40:160] = MODEL_CLOTHES
    raw[20:60, 90:120] = MODEL_OTHER
    assert clean_labels(raw)[40, 100] == BACKGROUND


def test_a_close_up_has_no_garment() -> None:
    raw = np.zeros((200, 200), np.uint8)
    raw[20:190, 40:160] = 3  # la cara llena el cuadro
    raw[190:200, 40:80] = MODEL_CLOTHES  # el trozo de camiseta o el logo de facial_2
    labels = clean_labels(raw)
    assert not (labels == GARMENT).any()
    assert labels[195, 60] == SKIN  # sigue siendo la persona: el portal va detrás


def test_regions_travel_as_png_and_scale_to_the_frame(tmp_path: Path) -> None:
    folder = tmp_path / "analysis" / "regions"
    folder.mkdir(parents=True)
    cv2.imwrite(str(folder / "000003.png"), _labels((300, 200)))
    labels = load_regions(tmp_path, 3, W, H)
    assert labels.shape == (H, W) and set(np.unique(labels)) == {BACKGROUND, HAIR, GARMENT}
    assert load_regions(tmp_path, 4, W, H) is None
    assert load_regions(None, 3, W, H) is None


def test_the_person_mask_has_a_soft_edge() -> None:
    mask = person_mask(_labels())
    assert mask[300, 200] == pytest.approx(1.0) and mask[10, 10] == 0.0
    assert 0.0 < mask[300, 90] < 1.0


def test_only_scripts_with_ambient_effects_pay_for_the_regions() -> None:
    def script(shape: str) -> EffectScript:
        effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=[shape]))
        return EffectScript(title="x", theme="x", seed=1, effects=[effect])

    assert needs_regions(script("garment_wave"))
    assert not needs_regions(script("face_oval_trace"))


@pytest.mark.parametrize("shape", AMBIENT)
def test_ambient_shapes_draw_and_stay_off_the_face(shape: str) -> None:
    assert _draw_all(shape, _labels())[0]
    assert not on_face({"type": "adornment", "style": {"shapes": [shape]}})


def test_the_wave_keeps_to_the_garment() -> None:
    _, layer = _draw_all("garment_wave", _labels())
    assert layer[400, 200, 3] > 0.05
    assert layer[150, 200, 3] == 0.0  # sin tocar la cabeza


def test_without_a_garment_the_wave_becomes_a_halo() -> None:
    close_up = np.zeros((H, W), np.uint8)
    close_up[100:600, 60:340] = HAIR
    drew, layer = _draw_all("garment_wave", close_up)
    assert drew
    assert layer[H // 2 :, :, 3].max() == 0.0  # el aro va arriba, no en el cuerpo


def test_only_the_edge_against_the_background_lights_up() -> None:
    labels = _labels()
    labels[300:360, 90:200] = SKIN  # una mano sobre la prenda, hasta el borde
    runs = _edges(labels)
    assert runs
    for run in runs:
        assert not ((run[:, 1] > 305) & (run[:, 1] < 355) & (run[:, 0] > 100) & (run[:, 0] < 250)).any()


def test_ambient_moments_are_irregular_and_leave_the_ends_free() -> None:
    meta = VideoMeta(path="x", fps=FPS, width=W, height=H, frame_count=900, duration_s=30.0)
    brief = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=[], summary="", people=["person_0"])
    catalog = load_catalog(ROOT / "configs/catalogs/cara.yaml")
    events = ambient_events(catalog, brief, 3, FPS)
    starts = [e.start_frame for e in events]
    assert starts[0] > 0 and starts[-1] < 900 - 60
    assert len(set(np.diff(starts))) > 1
    assert ambient_events(catalog.model_copy(update={"ambient_every_s": 0.0}), brief, 3, FPS) == []


def test_ambient_goes_with_a_face_effect_but_not_on_top_of_another_ambient() -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/cara.yaml")
    events = [MotionEvent(name="smile", target="person_0", start_frame=f, end_frame=f + 15, confidence=1.0) for f in range(0, 280, 50)]
    meta = VideoMeta(path="x", fps=FPS, width=W, height=H, frame_count=300, duration_s=10.0)
    brief = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=events, summary="", people=["person_0"])
    _, choreo = choreograph(catalog, brief, 3)
    around = sorted((d.frame, d.until) for d in choreo.decisions if d.action == "ambient" and not d.choice.startswith("nada"))
    assert around
    assert all(b[0] > a[1] for a, b in zip(around, around[1:]))
    # La cara sigue con su efecto: el ambiente no le quita el lugar.
    assert any(d.action == "smile" and not d.choice.startswith("nada") for d in choreo.decisions)


def _frown_frames(**extra: float) -> list[FrameRecord]:
    calm = [{"eyeSquintLeft": 0.1, "eyeSquintRight": 0.1} for _ in range(30)]
    tense = [{"eyeSquintLeft": 0.5, "eyeSquintRight": 0.5, **extra} for _ in range(12)]
    return [FrameRecord(frame=k, time_s=k / FPS, person_id="person_0", expressions=row) for k, row in enumerate(calm + tense + calm)]


def test_frown_needs_narrowed_eyes_without_a_smile_or_a_blink() -> None:
    assert [e.name for e in frown_spans(_frown_frames(), FPS)] == ["frown"]
    assert frown_spans(_frown_frames(mouthSmileLeft=0.7, mouthSmileRight=0.7), FPS) == []
    assert frown_spans(_frown_frames(eyeBlinkLeft=0.8), FPS) == []


def test_frown_counts_as_a_gesture() -> None:
    assert "frown" in GESTURE_NAMES
    assert any(detect.__name__ == "frown_events" for detect in GESTURE_DETECTORS)


def test_the_laser_charges_first_and_then_fires_to_the_edge() -> None:
    body = _body()
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["laser_eyes"]), triggers=[{"event": "frown", "hold": 48}])
    event = MotionEvent(name="frown", target="person_0", start_frame=0, end_frame=9, confidence=1.0)
    runtime = EffectRuntime(effect, 1, 10)
    runtime.expressions = {"eyeSquintLeft": 0.5, "eyeSquintRight": 0.5}
    lengths = []
    for f in range(1, 40):
        runtime.active_frames = f
        layer = np.zeros((H, W, 4), np.float32)
        items = adornment("laser_eyes", body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        beams = [item[0] for item in items if isinstance(item, tuple)]
        lengths.append(max((float(np.linalg.norm(c[-1] - c[0])) for c in beams), default=0.0))
    assert lengths[0] == 0.0  # primero carga
    assert max(lengths) > W / 2  # luego el rayo cruza el cuadro


def test_the_laser_lets_go_when_the_eyes_open() -> None:
    def shot_at(squints: list[float]) -> int:
        body = _body()
        effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["laser_eyes"]), triggers=[{"event": "frown", "hold": 48}])
        event = MotionEvent(name="frown", target="person_0", start_frame=0, end_frame=9, confidence=1.0)
        runtime = EffectRuntime(effect, 1, 10)
        for f, squint in enumerate(squints, start=1):
            runtime.active_frames = f
            runtime.expressions = {"eyeSquintLeft": squint, "eyeSquintRight": squint}
            layer = np.zeros((H, W, 4), np.float32)
            if adornment("laser_eyes", body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event):
                return f
        return -1

    assert shot_at([0.5] * 12 + [0.1] * 30) < shot_at([0.5] * 40)


def test_mini_me_copies_the_face_beside_the_head_and_stays_inside_the_frame() -> None:
    drew, layer = _draw_all("mini_me", None)
    assert drew
    ys, xs = np.nonzero(layer[..., 3] > 0.01)
    assert xs.size and xs.min() >= 0 and xs.max() < W
    assert not on_face({"type": "adornment", "style": {"shapes": ["mini_me"]}})


@pytest.mark.parametrize("name", sorted(EMOTION_OF))
def test_every_expression_has_its_symbol(name: str) -> None:
    drew, _ = _draw_all("emotion_burst", None, name)
    assert drew


def test_symbols_stay_off_the_middle_of_the_face() -> None:
    _, layer = _draw_all("emotion_burst", None, "smile")
    assert layer[150, 200, 3] == 0.0


def test_black_holes_look_for_free_background_and_avoid_the_person() -> None:
    from vfxglow.engine.ambient_fx import _place_holes
    from vfxglow.engine.face_glow import Face

    body = _body()
    face = Face(body, body.scale)
    labels = _labels()
    head = np.array([200.0, 150.0])
    for seed in range(8):
        holes = _place_holes(face, labels, head, (H, W), seed)
        assert 2 <= len(holes) <= 3
        assert len({tuple(h["tint"].tolist()) for h in holes}) == len(holes)  # cada uno de un color
        for hole in holes:
            x, y = (head + hole["offset"]).astype(int)
            assert labels[y, x] == BACKGROUND


def test_black_holes_really_darken_and_stay_off_the_face() -> None:
    from vfxglow.engine.ambient_fx import _black_hole

    layer = np.zeros((H, W, 4), np.float32)
    layer[..., :3] = 0.8
    layer[..., 3] = 0.5
    tint = np.array([0.2, 1.0, 0.4], np.float32)
    _black_hole(layer, np.array([200.0, 300.0]), 30.0, tint, 0.0, 1.0)
    assert layer[300, 200, :3].max() == 0.0 and layer[300, 200, 3] == 1.0  # tapa lo que hay detrás
    assert layer[300, 236, 1] > 0.8  # el anillo de luz
    assert not on_face({"type": "adornment", "style": {"shapes": ["black_holes"]}})
    catalog = load_catalog(ROOT / "configs/catalogs/cara.yaml")
    option = next(o for r in catalog.reactions if r.action == "ambient" for o in r.options if o.name == "agujeros_negros")
    assert option.effects[0]["render"]["blend"] == "over"  # la luz sola no oscurece
    assert option.effects[0]["render"]["occlude"] is True


def _cleopatra_frames(blink_at: int | None = None) -> list[float]:
    """Lo encendido en cada cuadro, con un parpadeo opcional."""
    body = _body()
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["cleopatra_eyes"]), triggers=[{"event": "still", "hold": 120}])
    event = MotionEvent(name="still", target="person_0", start_frame=0, end_frame=0, confidence=1.0)
    runtime = EffectRuntime(effect, 1, 10)
    lit = []
    for f in range(1, 90):
        runtime.active_frames = f
        closed = blink_at is not None and blink_at <= f < blink_at + 5
        runtime.expressions = {"eyeBlinkLeft": 1.0, "eyeBlinkRight": 1.0} if closed else {}
        layer = np.zeros((H, W, 4), np.float32)
        adornment("cleopatra_eyes", body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        lit.append(float((layer[..., 3] > 0.3).sum()))
    return lit


def test_cleopatra_traces_the_gold_before_the_fire() -> None:
    lit = _cleopatra_frames()
    assert 0 < lit[8] < max(lit) * 0.5  # primero solo el maquillaje
    assert max(lit[40:]) > lit[8] * 2


def test_cleopatra_flames_shrink_with_a_blink_and_light_up_again() -> None:
    steady, blinking = _cleopatra_frames(), _cleopatra_frames(blink_at=60)
    closed = 63  # el último cuadro con los ojos cerrados
    assert blinking[closed] < steady[closed] * 0.95
    assert blinking[85] > blinking[closed]


def test_cleopatra_starts_at_the_outer_corner_of_each_eye() -> None:
    from vfxglow.engine.cleopatra import _corner
    from vfxglow.engine.face_glow import Face

    body = _body()
    face = Face(body, body.scale)
    assert _corner(face, "right", -1.0)[0] < 180.0 < 220.0 < _corner(face, "left", 1.0)[0]


def test_cleopatra_is_a_face_effect_and_masks_turn_it_off() -> None:
    assert on_face({"type": "adornment", "style": {"shapes": ["cleopatra_eyes"]}})


def _ghost_side(yaws: list[float]) -> list[float]:
    """El lado del fantasma en cada cuadro, con la cabeza girando según `yaws`."""
    body = _body()
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["behind_ghost"]), triggers=[{"event": "still", "hold": 200}])
    event = MotionEvent(name="still", target="person_0", start_frame=0, end_frame=0, confidence=1.0)
    runtime = EffectRuntime(effect, 1, 10)
    runtime.expressions = {}
    runtime.regions = _labels()
    sides = []
    for f, yaw in enumerate(yaws, start=1):
        runtime.active_frames = f
        runtime.head_pose = (yaw, 0.0, 0.0)
        layer = np.zeros((H, W, 4), np.float32)
        adornment("behind_ghost", body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
        sides.append(next(v["side"] for k, v in runtime.swoosh.items() if k.startswith("_behind_ghost")))
    return sides


def test_the_ghost_moves_away_when_the_person_looks_at_it() -> None:
    first = _ghost_side([0.0])[0]
    still = _ghost_side([0.0] * 60)
    assert set(still) == {first}
    looked = _ghost_side([0.0] * 30 + [first * 30.0] * 30)
    assert looked[-1] == -first


def test_the_ghost_ignores_a_turn_to_the_other_side() -> None:
    first = _ghost_side([0.0])[0]
    assert _ghost_side([0.0] * 30 + [-first * 30.0] * 30)[-1] == first


def test_hair_strands_come_from_the_real_hair_and_a_bald_frame_gets_a_halo() -> None:
    assert _draw_all("hair_energy", _labels())[0]
    no_hair = _labels()
    no_hair[no_hair == HAIR] = SKIN
    drew, layer = _draw_all("hair_energy", no_hair)
    assert drew and layer[H // 2 :, :, 3].max() == 0.0
    assert not on_face({"type": "adornment", "style": {"shapes": ["hair_energy"]}})


def test_hair_and_ghost_hide_behind_the_person() -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/cara.yaml")
    options = {o.name: o for r in catalog.reactions for o in r.options}
    assert options["cabello_energia"].effects[0]["render"]["occlude"] is True
    assert options["fantasma"].effects[0]["render"]["occlude"] is True


def _ice(blinks: dict[int, float]) -> EffectRuntime:
    body = _body()
    effect = Effect(id="a", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["ice_eyes"]), triggers=[{"event": "still", "hold": 100}])
    event = MotionEvent(name="still", target="person_0", start_frame=0, end_frame=0, confidence=1.0)
    runtime = EffectRuntime(effect, 1, 10)
    for f in range(1, 50):
        runtime.active_frames = f
        runtime.expressions = {"eyeBlinkLeft": blinks.get(f, 0.0), "eyeBlinkRight": blinks.get(f, 0.0)}
        layer = np.zeros((H, W, 4), np.float32)
        adornment("ice_eyes", body, body.frame(), body.scale, f, 1, runtime, layer, np.array([0, 1, 1], np.float32), 1.0, event=event)
    return runtime


def test_ice_eyes_let_crystals_go_after_a_blink() -> None:
    def shards(runtime: EffectRuntime) -> int:
        return len(next(v for k, v in runtime.swoosh.items() if k.startswith("_ice"))["shards"])

    assert shards(_ice({})) == 0
    assert shards(_ice({40: 0.9, 41: 0.9})) > 0
    assert on_face({"type": "adornment", "style": {"shapes": ["ice_eyes"]}})


def test_long_effects_get_their_place_away_from_key_gestures() -> None:
    from vfxglow.director.choreography import look_events

    catalog = load_catalog(ROOT / "configs/catalogs/cara.yaml")
    touch = MotionEvent(name="face_touch", target="person_0", start_frame=90, end_frame=120, confidence=1.0)
    meta = VideoMeta(path="x", fps=FPS, width=W, height=H, frame_count=600, duration_s=20.0)
    brief = MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=[touch], summary="", people=["person_0"])
    spots = look_events(catalog, brief, 3, FPS)
    assert spots
    assert spots[0].start_frame > 120  # se corrió para dejar pasar el gesto
    _, choreo = choreograph(catalog, brief, 3)
    long = {"ojos_cleopatra", "fantasma", "ojos_hielo", "mini_yo"}
    assert any(d.choice.split(" (")[0] in long for d in choreo.decisions)
    assert look_events(catalog.model_copy(update={"look_every_s": 0.0}), brief, 3, FPS) == []


def test_the_face_catalog_uses_every_new_effect() -> None:
    catalog = load_catalog(ROOT / "configs/catalogs/cara.yaml")
    names = {o.name for r in catalog.reactions for o in r.options}
    assert {"portal_cabeza", "aro_cabeza", "onda_prenda", "mini_yo", "ojos_laser", "emocion", "agujeros_negros", "ojos_cleopatra", "fantasma", "cabello_energia", "ojos_hielo"} <= names
    assert catalog.ambient_every_s > 0
