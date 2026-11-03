"""Estilo desfile (docs/referencias/video_46.md): trazos de la prenda, outfits por toma y cortes deslizantes."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from vfxglow.analysis.garment import Tracker, frame_strokes, snap
from vfxglow.analysis.schema import Beat, MotionBrief, MotionEvent, VideoMeta
from vfxglow.engine.garment_fx import _choose

ROOT = Path(__file__).resolve().parents[1]


def test_a_border_snaps_to_the_real_edge_of_the_cloth() -> None:
    gradient = np.zeros((100, 100), np.float32)
    gradient[:, 53] = 255.0  # el borde real de la tela, en x = 53
    curve = np.stack([np.full(40, 50.0), np.linspace(10, 90, 40)], axis=1)  # la máscara lo puso en x = 50
    assert np.allclose(snap(curve, gradient)[5:-5, 0], 53.0, atol=0.6)


def test_a_seam_keeps_its_id_even_when_it_comes_in_pieces() -> None:
    tracker = Tracker()
    seam = np.stack([np.full(48, 300.0), np.linspace(200, 700, 48)], axis=1)
    first = [{"kind": "inner", "curve": seam, "score": 1.0}]
    tracker.assign(first, 1280)
    piece = [{"kind": "inner", "curve": seam[10:30] + [4.0, 0.0], "score": 0.8}]  # un tramo, corrido 4 px
    tracker.assign(piece, 1280)
    assert piece[0]["id"] == first[0]["id"]
    tracker.reset()
    again = [{"kind": "inner", "curve": seam, "score": 1.0}]
    tracker.assign(again, 1280)
    assert again[0]["id"] != first[0]["id"]  # un corte vuelve a empezar


def test_a_missing_stroke_keeps_its_id_for_a_few_frames() -> None:
    tracker = Tracker()
    shoe = np.stack([np.linspace(100, 160, 48), np.full(48, 1100.0)], axis=1)
    first = [{"kind": "accessory", "curve": shoe, "score": 1.0}]
    tracker.assign(first, 1280)
    tracker.assign([], 1280)
    tracker.assign([], 1280)
    back = [{"kind": "accessory", "curve": shoe, "score": 1.0}]
    tracker.assign(back, 1280)
    assert back[0]["id"] == first[0]["id"]


def test_shoes_bag_and_garment_borders_come_out_of_the_segmentation() -> None:
    frame = np.full((400, 200, 3), 200, np.uint8)
    cat = np.zeros((400, 200), np.uint8)
    cat[60:300, 60:140] = 4  # la prenda
    cat[300:360, 70:130] = 2  # la pierna (piel)
    cat[360:390, 70:130] = 5  # el zapato ("otros")
    frame[60:300, 60:140] = (60, 60, 60)
    frame[360:390, 70:130] = (20, 20, 20)
    kinds = {s["kind"] for s in frame_strokes(frame, cat)}
    assert {"border", "accessory"} <= kinds


def test_an_outfit_keeps_the_strokes_that_appear_most() -> None:
    def stroke(sid: int, kind: str, score: float) -> dict:
        return {"id": sid, "kind": kind, "score": score, "points": [[0.1, 0.1], [0.2, 0.2]]}

    frames = {f: {"strokes": [stroke(1, "accessory", 0.5), stroke(2, "inner", 0.9)] + ([stroke(3, "inner", 2.0)] if f == 0 else []), "zones": {}} for f in range(20)}
    chosen = _choose(frames, 0, 19, 1.0, seed=1)
    assert 1 in chosen and 2 in chosen
    assert 3 not in chosen  # salió en un solo cuadro: no es del outfit


def _brief(cuts: list[int], total: int = 160) -> MotionBrief:
    meta = VideoMeta(path="x", fps=30.0, width=720, height=1280, frame_count=total, duration_s=total / 30.0)
    beats = [Beat(id=k, start_frame=c, end_frame=min(c + 10, total - 1), kind="cut") for k, c in enumerate(cuts)]
    return MotionBrief(video=meta, person_id="person_0", anchors=[], limbs=[], events=[], summary="", people=["person_0"], beats=beats)


def test_each_take_is_an_outfit_with_its_own_colour() -> None:
    from vfxglow.director.choreography import choreograph, load_catalog

    catalog = load_catalog(ROOT / "configs/catalogs/desfile.yaml")
    script, choreo = choreograph(catalog, _brief([30, 60, 90, 120]), 3)
    outfits = sorted(d.frame for d in choreo.decisions if d.action == "outfit")
    assert outfits == [0, 30, 60, 90, 120]
    mains = [tuple(c.colors[0]) for c in script.chapters]
    assert len(mains) == 5 and len(set(mains)) == 5  # ningún color se repite entre outfits


def test_a_sliding_transition_is_one_cut(tmp_path: Path) -> None:
    from vfxglow.analysis.beats import _structure_cuts

    path = tmp_path / "slide.avi"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (96, 54))
    rng = np.random.default_rng(0)
    # Bloques grandes (una escena, no ruido: el ruido fino se promedia al achicar el cuadro).
    a, b = (cv2.resize(rng.integers(0, 255, (6, 8, 3), np.uint8), (96, 54), interpolation=cv2.INTER_NEAREST) for _ in range(2))
    for k in range(60):
        frame = a.copy()
        if 30 <= k < 33:  # el outfit nuevo entra de lado en tres cuadros
            frame[:, -(k - 29) * 32 :] = b[:, -(k - 29) * 32 :]
        elif k >= 33:
            frame = b.copy()
        out.write(cv2.GaussianBlur(frame, (5, 5), 0))
    out.release()
    cuts = _structure_cuts(path, 60)
    assert len(cuts) == 1 and 30 <= cuts[0] <= 33


def test_back_to_back_activations_start_over() -> None:
    """Dos outfits seguidos, sin pausa: el segundo vuelve a empezar (su fase y su color de capítulo)."""
    from vfxglow.config import EngineConfig
    from vfxglow.director.schema import Chapter, Effect, EffectScript, EffectStyle, EffectTarget
    from vfxglow.engine.engine import EffectEngine

    effect = Effect(id="e", type="adornment", target=EffectTarget(kind="joint", id="body"), style=EffectStyle(shapes=["horns"], focus=False, keep_on_cut=True),
                    triggers=[{"event": "outfit", "hold": 0, "cooldown": 0, "fade_in": 0, "fade_out": 0}])
    chapters = [Chapter(start_frame=0, end_frame=9, focus="a", colors=[(1.0, 0.0, 0.0), (1.0, 1.0, 1.0)]),
                Chapter(start_frame=10, end_frame=19, focus="b", colors=[(0.0, 1.0, 0.0), (1.0, 1.0, 1.0)])]
    script = EffectScript(title="t", theme="t", effects=[effect], chapters=chapters)
    events = [MotionEvent(name="outfit", target="person_0", start_frame=0, end_frame=9, confidence=1.0),
              MotionEvent(name="outfit", target="person_0", start_frame=10, end_frame=19, confidence=1.0)]
    engine = EffectEngine(script, EngineConfig(), events=events)
    for i in range(15):
        engine.render_frame(None, i, 100, 100, 20)
    runtime = engine.runtimes[0]
    assert runtime.chapter_frame == 10
    assert tuple(runtime.chapter_colors[0]) == (0.0, 1.0, 0.0)


def test_the_garment_splits_into_zones_with_the_pose() -> None:
    from vfxglow.analysis.garment import frame_zones

    h, w = 400, 200
    cat = np.zeros((h, w), np.uint8)
    cat[80:200, 60:140] = 4  # torso
    cat[80:200, 30:60] = 4  # manga derecha (izquierda del cuadro)
    cat[80:200, 140:170] = 4  # manga izquierda
    cat[200:360, 60:100] = 4  # pierna derecha
    cat[200:360, 100:140] = 4  # pierna izquierda
    cat[60:80, 80:120] = 3  # cara: la persona empieza ahí
    pose = {"right_shoulder": np.array([60.0, 85]), "left_shoulder": np.array([140.0, 85]), "right_elbow": np.array([45.0, 140]), "left_elbow": np.array([155.0, 140]),
            "right_wrist": np.array([45.0, 195]), "left_wrist": np.array([155.0, 195]), "right_hip": np.array([80.0, 200]), "left_hip": np.array([120.0, 200]),
            "right_knee": np.array([80.0, 280]), "left_knee": np.array([120.0, 280]), "right_ankle": np.array([80.0, 355]), "left_ankle": np.array([120.0, 355])}
    zones = frame_zones(cat, pose, w, h)
    assert {"torso", "sleeve_left", "sleeve_right", "leg_left", "leg_right"} <= set(zones)
    assert zones["leg_left"][:, 0].mean() > zones["leg_right"][:, 0].mean()


def test_the_painted_zone_takes_turns_and_a_sheen_crosses_it() -> None:
    from types import SimpleNamespace

    from vfxglow.engine.garment_fx import ZONE_TURN_S, garment_zones

    square = [[0.3, 0.3], [0.7, 0.3], [0.7, 0.6], [0.3, 0.6]]
    legs = [[0.3, 0.6], [0.7, 0.6], [0.7, 0.9], [0.3, 0.9]]
    rows = {f: {"strokes": [], "zones": {"torso": square, "leg_left": legs}} for f in range(90)}
    effect = SimpleNamespace(id="z", style=SimpleNamespace(variants={}))
    runtime = SimpleNamespace(garment=rows, frame_shape=(200, 100), fps=30.0, swoosh={}, kernels={}, effect=effect)
    event = MotionEvent(name="outfit_zone", target="person_0", start_frame=0, end_frame=89, confidence=1.0)
    lit = {}
    for f in (5, int(ZONE_TURN_S * 30) + 15):
        layer = np.zeros((200, 100, 4), np.float32)
        garment_zones("garment_zones", SimpleNamespace(prefix="p"), None, 40.0, f, runtime, layer, np.array([1.0, 0.0, 1.0], np.float32), 1.0, event)
        lit[f] = (float(layer[60:120, 30:70, 3].mean()), float(layer[120:180, 30:70, 3].mean()))
    first, second = lit.values()
    assert first[0] > first[1] and second[1] > second[0]  # el turno pasó del torso a la pierna


def test_the_outfit_changes_with_the_clothes_not_with_every_cut() -> None:
    from vfxglow.director.choreography import choreograph, load_catalog

    catalog = load_catalog(ROOT / "configs/catalogs/desfile.yaml")
    brief = _brief([30, 60, 90, 120]).model_copy(update={"outfits": [60]})  # los cortes 30, 90 y 120 suman capas
    script, choreo = choreograph(catalog, brief, 3)
    assert sorted(d.frame for d in choreo.decisions if d.action == "outfit") == [0, 60]
    assert [c.start_frame for c in script.chapters] == [0, 60]


def test_a_clothes_change_is_found_where_the_garment_colour_jumps() -> None:
    from vfxglow.analysis.garment import outfit_peaks

    rng = np.random.default_rng(0)
    red, blue, grey = (np.eye(48, dtype=np.float32)[k] for k in (0, 30, 12))
    noise = lambda base: [base * 0.9 + rng.random(48).astype(np.float32) * 0.1 / 48 for _ in range(40)]  # noqa: E731
    hists = np.array(noise(red) + noise(blue) + noise(blue * 0.85 + grey * 0.15))  # el último tramo: una capa chica
    assert outfit_peaks(hists, 30.0) == [40]
    assert outfit_peaks(hists, 30.0, cuts=[42]) == [42]  # un corte cercano se lleva el cambio


def test_a_new_outfit_is_revealed_by_a_wipe_and_then_worn_whole() -> None:
    from types import SimpleNamespace

    from vfxglow.engine.garment_fx import REVEAL_WIPE_S, garment_reveal

    zones = {"torso": [[0.3, 0.2], [0.7, 0.2], [0.7, 0.6], [0.3, 0.6]]}
    rows = {f: {"strokes": [], "zones": zones} for f in range(100)}
    runtime = SimpleNamespace(garment=rows, frame_shape=(200, 100), fps=30.0, swoosh={}, kernels={})

    def draw(frame: int, start: int) -> tuple[np.ndarray, list]:
        layer = np.zeros((200, 100, 4), np.float32)
        event = MotionEvent(name="outfit_reveal", target="person_0", start_frame=start, end_frame=99, confidence=1.0)
        lines = garment_reveal("garment_reveal", None, None, 40.0, frame, runtime, layer, np.array([1.0, 0.0, 1.0], np.float32), 1.0, event)
        return layer, lines

    mid, _ = draw(30 + int(REVEAL_WIPE_S * 30 / 2), 30)
    left, right = float(mid[50:110, 32:45, 3].mean()), float(mid[50:110, 56:68, 3].mean())
    assert left > right  # a mitad del barrido, de un lado ya está y del otro todavía no
    whole, lines = draw(30 + int(REVEAL_WIPE_S * 30) + 3, 30)
    assert float(whole[50:110, 32:68, 3].min()) > 0.2 and lines  # entera, con su silueta
    assert not draw(95, 30)[1] and float(draw(95, 30)[0][..., 3].max()) == 0.0  # después ya no está
    assert float(draw(5, 0)[0][..., 3].max()) == 0.0  # el outfit del comienzo no se revela


def test_a_holographic_outfit_splits_colour_and_paints_the_shoes_in_rainbow() -> None:
    from types import SimpleNamespace

    from vfxglow.engine.garment_fx import garment_lines

    seam = {"id": 1, "kind": "inner", "score": 1.0, "points": [[0.5, 0.3], [0.5, 0.5]]}
    shoe = {"id": 2, "kind": "accessory", "score": 1.0, "points": [[0.4, 0.9], [0.6, 0.9], [0.6, 0.95], [0.4, 0.95]]}
    rows = {f: {"strokes": [seam, shoe], "zones": {}} for f in range(40)}

    def lines(holo: int) -> list:
        effect = SimpleNamespace(id="g", style=SimpleNamespace(variants={"holo": [holo]}))
        runtime = SimpleNamespace(garment=rows, frame_shape=(400, 200), swoosh={}, effect=effect, take_start=0, next_cut=None)
        event = MotionEvent(name="outfit", target="person_0", start_frame=0, end_frame=39, confidence=1.0)
        return garment_lines("garment_lines", SimpleNamespace(prefix="p"), None, 40.0, 10, runtime, None, np.array([0.0, 1.0, 0.0], np.float32), 1.0, event)

    plain, holo = lines(0), lines(1)
    assert len(plain) == 2
    assert len(holo) > 6  # copias corridas y tramos de arcoíris en el zapato
    assert len({tuple(np.round(t, 2)) for _c, t in holo}) > 4
