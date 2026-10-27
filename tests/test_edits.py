"""Editor de efectos: cambios sobre el guion compilado y el tramo que hay que volver a dibujar."""

from __future__ import annotations

import pytest

from vfxglow.analysis.schema import MotionEvent
from vfxglow.director.edits import Edit, apply_edits, assign_tracks, changed_window, moments_from
from vfxglow.director.schema import Effect, EffectScript

FPS = 30.0
FRAMES = 900  # 30 s
T = "person_0:right_wrist"


def _effect(effect_id: str, action: str, frames: list[int], hold: int = 5) -> Effect:
    return Effect.model_validate(
        {
            "id": effect_id,
            "type": "swoosh",
            "target": {"kind": "joint", "id": "right_wrist"},
            "triggers": [{"event": action, "frames": frames, "targets": [T] * len(frames), "hold": hold, "cooldown": 0}],
        }
    )


def _event(action: str, frame: int, length: int = 4) -> MotionEvent:
    return MotionEvent(name=action, target=T, start_frame=frame, end_frame=frame + length, confidence=1.0)


def _setup():
    script = EffectScript(
        title="t",
        theme="t",
        effects=[
            Effect.model_validate({"id": "always_0_tramo0", "type": "particles", "target": {"kind": "joint", "id": "nose"}}),
            _effect("fast_swing_agua_0", "fast_swing", [100, 400]),
            _effect("jump_viento_0", "jump", [600]),
            _effect("point_rayo_0", "point", [700]),
        ],
    )
    events = [_event("fast_swing", 100), _event("fast_swing", 400), _event("jump", 600), _event("point", 700)]
    decisions = [
        {"frame": 100, "second": 100 / FPS, "action": "fast_swing", "target": T, "choice": "agua", "until": 109},
        {"frame": 400, "second": 400 / FPS, "action": "fast_swing", "target": T, "choice": "agua", "until": 409},
        {"frame": 500, "second": 500 / FPS, "action": "fast_swing", "target": T, "choice": "nada", "until": -1},
        {"frame": 600, "second": 600 / FPS, "action": "jump", "target": T, "choice": "viento", "until": 609},
        {"frame": 700, "second": 700 / FPS, "action": "point", "target": T, "choice": "rayo", "until": 709},
    ]
    moments = moments_from(script, decisions)
    elements = {"agua": "agua", "viento": "aire", "rayo": "rayo"}
    tracks = assign_tracks(moments, lambda option, _action: elements.get(option))
    return script, events, moments, tracks


def _ids(script: EffectScript) -> dict[str, Effect]:
    return {e.id: e for e in script.effects}


def test_moments_pair_with_their_effects_and_go_to_element_tracks() -> None:
    _script, _events, moments, tracks = _setup()
    assert [m.choice for m in moments] == ["agua", "agua", "viento", "rayo"]  # "nada" no enciende nada
    assert moments[0].effects == ["fast_swing_agua_0"] and moments[0].until == 109
    assert [(t.key, t.label, len(t.moments)) for t in tracks] == [("agua", "Agua", 2), ("aire", "Viento", 1), ("rayo", "Rayo", 1)]


def test_without_elements_tracks_are_effect_types() -> None:
    _script, _events, moments, _tracks = _setup()
    tracks = assign_tracks(moments, lambda _o, _a: None)
    assert [t.key for t in tracks] == ["agua", "viento", "rayo"] and all(t.element is None for t in tracks)


def test_removing_a_moment_leaves_every_other_effect_exactly_as_it_was() -> None:
    script, events, moments, tracks = _setup()
    first = moments[0]
    new, new_moments, _ = apply_edits(script, moments, tracks, [Edit(op="remove", moment=first.id)], events, FPS, FRAMES)
    after = _ids(new)
    assert after["fast_swing_agua_0"].triggers[0].frames == [400]
    for effect_id in ("always_0_tramo0", "jump_viento_0", "point_rayo_0"):
        assert after[effect_id] == _ids(script)[effect_id]
    assert first.id not in {m.id for m in new_moments}


def test_turning_a_track_off_removes_its_effects() -> None:
    script, events, moments, tracks = _setup()
    new, new_moments, _ = apply_edits(script, moments, tracks, [Edit(op="track_off", track="agua")], events, FPS, FRAMES)
    assert "fast_swing_agua_0" not in _ids(new) and {m.track for m in new_moments} == {"aire", "rayo"}


def test_moving_a_moment_copies_its_effect_to_the_new_time_with_a_new_gesture() -> None:
    script, events, moments, tracks = _setup()
    jump = next(m for m in moments if m.choice == "viento")
    new, new_moments, _ = apply_edits(script, moments, tracks, [Edit(op="move", moment=jump.id, start=21.0, end=22.0)], events, FPS, FRAMES)
    after = _ids(new)
    assert "jump_viento_0" not in after
    copy = after["jump_viento_0~m1"]
    assert copy.triggers[0].frames == [630] and copy.triggers[0].targets == [T]
    moved_event = new.extra_events[-1]
    assert (moved_event.name, moved_event.start_frame, moved_event.target) == ("jump", 630, T)
    assert moved_event.end_frame == 630 + 30 - 1 - 5  # la barra dura 1 s; el efecto se sostiene 5 fotogramas
    moved = next(m for m in new_moments if m.choice == "viento")
    assert (moved.frame, moved.until, moved.effects, moved.track) == (630, 659, ["jump_viento_0~m1"], "aire")
    assert after["fast_swing_agua_0"] == _ids(script)["fast_swing_agua_0"]


def test_style_changes_intensity_size_and_color_of_one_track_only() -> None:
    script, events, moments, tracks = _setup()
    edits = [Edit(op="style", track="agua", intensity=1.5, size=2.5, color="#ff0000")]
    new, _m, styles = apply_edits(script, moments, tracks, edits, events, FPS, FRAMES)
    water = _ids(new)["fast_swing_agua_0"].style
    base = _ids(script)["fast_swing_agua_0"].style
    assert water.intensity == pytest.approx(base.intensity * 1.5) and water.scale == pytest.approx(2.0)  # el tamaño se limita a 2
    assert water.tint == (1.0, 0.0, 0.0) and water.colors == base.colors
    assert _ids(new)["jump_viento_0"] == _ids(script)["jump_viento_0"]
    assert styles["agua"].size == 2.0


def test_impossible_edits_are_errors() -> None:
    script, events, moments, tracks = _setup()
    with pytest.raises(ValueError, match="No existe el momento"):
        apply_edits(script, moments, tracks, [Edit(op="remove", moment="nada")], events, FPS, FRAMES)
    with pytest.raises(ValueError, match="fuera del video"):
        apply_edits(script, moments, tracks, [Edit(op="move", moment=moments[0].id, start=40.0, end=41.0)], events, FPS, FRAMES)
    with pytest.raises(ValueError, match="Color no válido"):
        apply_edits(script, moments, tracks, [Edit(op="style", track="agua", color="rojo")], events, FPS, FRAMES)


def test_the_window_covers_what_changed_and_what_was_on_around_it() -> None:
    script, events, moments, tracks = _setup()
    assert changed_window(script, script, events, FRAMES, FPS) is None  # sin cambios, nada que dibujar
    rayo = next(m for m in moments if m.choice == "rayo")
    new, _m, _s = apply_edits(script, moments, tracks, [Edit(op="remove", moment=rayo.id)], events, FPS, FRAMES)
    start, end = changed_window(script, new, events, FRAMES, FPS)
    assert start == 700 and 709 <= end <= 709 + 30  # su activación y el margen de salida (1 s), nada más
    # Un efecto que estaba encendido en ese tramo extiende el tramo para no empezarlo en frío.
    script.effects.append(_effect("lunge_fuego_0", "lunge", [690], hold=40))
    events.append(_event("lunge", 690))
    new, _m, _s = apply_edits(script, moments, tracks, [Edit(op="remove", moment=rayo.id)], events, FPS, FRAMES)
    start, end = changed_window(script, new, events, FRAMES, FPS)
    assert start == 690 and end >= 734


def test_a_window_covering_most_of_the_video_renders_it_all() -> None:
    script, events, moments, tracks = _setup()
    script.effects.append(_effect("frenzy_fuego_0", "frenzy", [50], hold=800))
    events.append(_event("frenzy", 50))
    new, _m, _s = apply_edits(script, moments, tracks, [Edit(op="track_off", track="agua")], events, FPS, FRAMES)
    assert changed_window(script, new, events, FRAMES, FPS) == (0, FRAMES - 1)


def test_only_the_activation_that_changed_counts_not_the_rest_of_its_effect() -> None:
    script, events, moments, tracks = _setup()
    second = moments[1]  # el agua de 400; la de 100 sigue igual
    new, _m, _s = apply_edits(script, moments, tracks, [Edit(op="remove", moment=second.id)], events, FPS, FRAMES)
    start, end = changed_window(script, new, events, FRAMES, FPS)
    assert start == 400 and end < 450


def test_tint_keeps_brightness_and_white_cores_and_scale_grows_around_the_anchor() -> None:
    import numpy as np

    from vfxglow.engine.tint import LUMA, recolor, scale_about

    layer = np.zeros((20, 20, 4), np.float32)
    layer[5, 5] = [0.2, 0.8, 1.0, 1.0]  # cian (agua)
    layer[6, 6] = [1.5, 1.5, 1.5, 1.0]  # núcleo blanco
    red = recolor(layer.copy(), (1.0, 0.0, 0.0))  # tiñe en sitio
    assert red[5, 5, 0] > 10 * max(red[5, 5, 1], red[5, 5, 2])  # ahora es rojo (lo poco blanco que tenía se queda)...
    assert float(red[5, 5, :3] @ LUMA) == pytest.approx(float(layer[5, 5, :3] @ LUMA), rel=1e-4)  # ...igual de luminoso
    assert np.allclose(red[6, 6, :3], 1.5)  # el núcleo blanco sigue blanco
    assert red[5, 5, 3] == 1.0
    dot = np.zeros((40, 40, 4), np.float32)
    dot[18:22, 18:22] = 1.0
    big = scale_about(dot, 2.0, (20.0, 20.0))
    thin = np.zeros((64, 64, 4), np.float32)
    thin[37, 5:60] = [0.0, 0.0, 1.0, 1.0]  # un trazo de un píxel, fuera de la rejilla de muestreo
    painted = recolor(thin, (1.0, 0.0, 0.0))[37, 30]
    assert painted[0] > 0.3 and painted[2] < 0.01  # no se lo salta: queda rojo (con la luminosidad del azul)
    assert (big[..., 3] > 0.5).sum() > 2 * (dot[..., 3] > 0.5).sum() and big[20, 20, 3] > 0.9


def test_the_main_element_track_also_restyles_the_permanent_effects() -> None:
    script, events, moments, tracks = _setup()
    edits = [Edit(op="style", track="agua", color="#ff0000")]
    plain, _m, _s = apply_edits(script, moments, tracks, edits, events, FPS, FRAMES)
    main, _m, _s = apply_edits(script, moments, tracks, edits, events, FPS, FRAMES, main_track="agua")
    assert _ids(plain)["always_0_tramo0"].style.tint is None  # otra pista: lo permanente no cambia
    assert _ids(main)["always_0_tramo0"].style.tint == (1.0, 0.0, 0.0)  # la del elemento del catálogo: también
