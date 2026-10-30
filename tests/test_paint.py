"""Pintura (video_2): trazos reales frente al borde que se corre, los acentos de la obra y los
efectos que los dibujan."""

from __future__ import annotations

import cv2
import numpy as np

from vfxglow.analysis.appearance import Appearance
from vfxglow.analysis.paint import _accent_lines, _real_strokes
from vfxglow.analysis.schema import FrameRecord
from vfxglow.config import EngineConfig
from vfxglow.director.schema import Effect, EffectScript, EffectStyle, EffectTarget
from vfxglow.engine.engine import EffectEngine

W, H = 360, 640


def test_border_drift_is_not_a_new_stroke() -> None:
    existing = np.zeros((100, 100), bool)
    existing[20:60, 20:60] = True
    drift = np.zeros_like(existing)
    drift[19, 20:60] = True  # el borde corrido un píxel
    stroke = np.zeros_like(existing)
    stroke[70:80, 20:40] = True  # una mancha nueva lejos
    kept = _real_strokes(drift | stroke, existing)
    assert kept[75, 30] and not kept[19, 30]


def test_accents_find_dark_lines_on_the_colored_head_by_zone() -> None:
    frame = np.zeros((H, W, 3), np.uint8)
    cv2.ellipse(frame, (180, 200), (110, 130), 0, 0, 360, (0, 110, 240), -1)  # cabeza naranja
    cv2.rectangle(frame, (60, 300), (300, 639), (0, 110, 240), -1)  # el cuerpo debajo
    cv2.line(frame, (150, 100), (150, 180), (10, 10, 10), 6)  # estría (alta y fina, arriba)
    cv2.line(frame, (130, 285), (230, 285), (10, 10, 10), 6)  # boca
    found = _accent_lines(frame, None)
    zones = {line["zone"] for line in found["lines"]}
    assert {"ribs", "mouth"} <= zones


def _engine(effect: Effect, appearance: Appearance) -> EffectEngine:
    engine = EffectEngine(EffectScript(title="t", theme="t", effects=[effect]), EngineConfig(), events=[])
    engine.appearance = appearance
    engine._appearance_dir = "x"
    return engine


def test_paint_trace_lights_fresh_edges_and_dashes_old_ones() -> None:
    ring = [(0.5 + 0.1 * np.cos(t), 0.5 + 0.05 * np.sin(t)) for t in np.linspace(0, 2 * np.pi, 80)]
    fresh = Appearance(paint={0: {"strokes": [[(x, y, 1.0) for x, y in ring]], "tip": (0.6, 0.5)}})
    old = Appearance(paint={0: {"strokes": [[(x, y, 18.0) for x, y in ring]], "tip": None}})
    effect = Effect(id="p", type="paint_trace", target=EffectTarget(kind="joint", id="face_center"), style=EffectStyle(colors=[(1.0, 0.8, 0.3)]))
    fresh.paint = {3: fresh.paint[0]}
    old.paint = {3: old.paint[0]}
    lit = _engine(effect, fresh).render_frame(FrameRecord(frame=3, time_s=0.1), 3, W, H, 10)[0][2][..., 3]
    faded = _engine(effect, old).render_frame(FrameRecord(frame=3, time_s=0.1), 3, W, H, 10)[0][2][..., 3]
    assert (lit > 0.1).sum() > (faded > 0.1).sum() > 0


def test_paint_accents_light_one_zone_at_a_time() -> None:
    lines = [{"zone": "eyes", "points": [(0.3, 0.3), (0.4, 0.3), (0.4, 0.32)]}, {"zone": "mouth", "points": [(0.3, 0.7), (0.6, 0.7), (0.6, 0.72)]}]
    appearance = Appearance(accents={f: {"head": (0.2, 0.1, 0.8, 0.8), "lines": lines} for f in range(30)})
    effect = Effect(id="a", type="paint_accents", target=EffectTarget(kind="joint", id="face_center"), style=EffectStyle(palette=[(0.3, 1.0, 0.4)]))
    engine = _engine(effect, appearance)
    layer = None
    for f in range(6):
        layer = engine.render_frame(FrameRecord(frame=f, time_s=f / 30), f, W, H, 30)[0][2][..., 3]
    ys, _ = np.nonzero(layer > 0.3)
    assert ys.size and ys.max() < 0.5 * H  # en el primer tramo solo los ojos


def test_tool_tip_is_the_moving_end_inside_the_face_whatever_its_color() -> None:
    from vfxglow.analysis.tool import tool_tip

    region = np.zeros((H, W), bool)
    region[150:450, 80:280] = True  # la cara
    before = np.full((H, W, 3), 140, np.uint8)
    after = before.copy()
    cv2.line(after, (300, 620), (190, 260), (60, 200, 30), 8)  # una herramienta verde que entra desde abajo
    tip = tool_tip(before, after, region)
    assert tip is not None and abs(tip[0] - 190) < 8 and abs(tip[1] - 260) < 8
    shaken = np.full((H, W, 3), 230, np.uint8)  # la alineación falló: toda la cara cambia
    assert tool_tip(before, shaken, region) is None


def test_pumpkin_eyes_are_the_lens_pair_inside_dark_sockets() -> None:
    from vfxglow.analysis.paint import _lens_pair, _steady_eyes

    frame = np.zeros((1280, 720, 3), np.uint8)
    cv2.ellipse(frame, (360, 500), (260, 320), 0, 0, 360, (0, 110, 240), -1)  # cabeza naranja
    for x in (250, 470):
        cv2.ellipse(frame, (x, 450), (70, 50), 0, 0, 360, (10, 10, 10), -1)  # cuenca
        cv2.circle(frame, (x, 450), 12, (230, 230, 230), -1)  # lente
    eyes = _lens_pair(frame)
    assert eyes is not None and abs(eyes[0][0] * 720 - 250) < 4 and abs(eyes[1][0] * 720 - 470) < 4
    accents = {f: {"head": (0, 0, 1, 1), "lines": [], "eyes": [[0.35, 0.35], [0.65, 0.35]]} for f in range(9)}
    accents[4]["eyes"] = [[0.4, 0.8], [0.6, 0.8]]  # un salto: los dientes
    _steady_eyes(accents)
    assert abs(accents[4]["eyes"][0][1] - 0.35) < 1e-6


def test_socket_contour_ignores_thin_stripes_touching_it() -> None:
    from vfxglow.analysis.paint import _sockets

    frame = np.full((1280, 720, 3), (0, 110, 240), np.uint8)
    for x in (250, 470):
        cv2.ellipse(frame, (x, 450), (70, 55), 0, 0, 360, (10, 10, 10), -1)
        cv2.line(frame, (x, 300), (x, 400), (10, 10, 10), 6)  # estría que toca la cuenca
        cv2.circle(frame, (x, 450), 12, (230, 230, 230), -1)
    sockets = _sockets(frame, [[250 / 720, 450 / 1280], [470 / 720, 450 / 1280]])
    top = min(p[1] for p in sockets[0]) * 1280
    assert len(sockets[0]) >= 4 and top > 380  # la cuenca, sin la estría de arriba


def test_fit_shape_picks_the_closest_figure() -> None:
    from vfxglow.analysis.shapes import fit_shape

    triangle = np.array([[100, 300], [200, 100], [300, 300]], np.float64)
    noisy = np.vstack([np.linspace(triangle[i], triangle[(i + 1) % 3], 30) for i in range(3)]) + np.random.default_rng(0).normal(0, 2, (90, 2))
    assert fit_shape(noisy)["kind"] == "triangle"
    t = np.linspace(0, 2 * np.pi, 80, endpoint=False)
    ellipse = np.stack([200 + 120 * np.cos(t), 200 + 60 * np.sin(t)], axis=1)
    found = fit_shape(ellipse)
    assert found["kind"] in ("ellipse", "circle") and found["fit"] > 0.9


def test_nose_hole_between_and_below_the_eyes() -> None:
    from vfxglow.analysis.paint import _nose

    frame = np.full((1280, 720, 3), (0, 110, 240), np.uint8)
    cv2.fillPoly(frame, [np.array([[330, 640], [360, 570], [390, 640]], np.int32)], (10, 10, 10))
    cv2.circle(frame, (600, 620), 30, (10, 10, 10), -1)  # otra mancha, fuera del centro
    nose = np.array(_nose(frame, [[250 / 720, 450 / 1280], [470 / 720, 450 / 1280]])) * [720, 1280]
    assert len(nose) >= 3 and abs(nose[:, 0].mean() - 360) < 15


def test_mouth_needs_teeth_not_a_smooth_blob() -> None:
    from vfxglow.analysis.paint import _mouth

    eyes = [[250 / 720, 450 / 1280], [470 / 720, 450 / 1280]]
    frame = np.full((1280, 720, 3), (0, 110, 240), np.uint8)
    cv2.rectangle(frame, (250, 640), (470, 730), (10, 10, 10), -1)  # la boca, dentro de la zona
    for k in range(7):  # dientes que bajan desde arriba
        cv2.fillPoly(frame, [np.array([[255 + 31 * k, 640], [270 + 31 * k, 715], [285 + 31 * k, 640]], np.int32)], (0, 110, 240))
    assert _mouth(frame, eyes)
    blob = np.full((1280, 720, 3), (0, 110, 240), np.uint8)
    cv2.ellipse(blob, (360, 685), (110, 45), 0, 0, 360, (10, 10, 10), -1)
    assert _mouth(blob, eyes) == []


def test_a_makeup_stroke_is_an_event_with_its_figure_and_zone() -> None:
    from vfxglow.analysis.appearance import Appearance, paint_stroke_events
    from vfxglow.analysis.schema import FrameRecord, Landmark

    face = [Landmark(name="face_468", x=0.42, y=0.4, c=0.9), Landmark(name="face_473", x=0.58, y=0.4, c=0.9),
            Landmark(name="face_13", x=0.5, y=0.62, c=0.9), Landmark(name="face_4", x=0.5, y=0.5, c=0.9),
            Landmark(name="face_10", x=0.5, y=0.2, c=0.9)]
    triangle = [(0.62 + 0.06 * t, 0.5 + 0.0) for t in (0.0, 0.5, 1.0)] + [(0.65, 0.44), (0.62, 0.5)]
    appearance = Appearance()
    for f in range(4, 14):  # diez fotogramas de pintura en la mejilla izquierda
        appearance.contours[f] = triangle
    frames = [FrameRecord(frame=f, time_s=f / 30, face=face) for f in range(20)]
    events = paint_stroke_events(appearance, frames, 400, 400)
    assert [(e.name, e.kind) for e in events] == [("paint_stroke", "cheek")]
    assert events[0].detail.startswith("figura=")
    # Un toque suelto no es un trazo.
    appearance.contours = {5: triangle, 6: triangle}
    assert paint_stroke_events(appearance, frames, 400, 400) == []
