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
