"""Elementos del modo Avatar (glowing/video_51): estilos del fuego, tinte de capítulo y rayo cian."""

from __future__ import annotations

from types import SimpleNamespace

import cv2
import numpy as np

from vfxglow.director.schema import Effect
from vfxglow.engine import firebend
from vfxglow.engine.lightning import _edge_tip, _shard, build_bolt
from vfxglow.engine.noise import ValueNoise

H, W = 600, 400


def _painted(look: str, width: float) -> np.ndarray:
    """Pinta una cinta recta de medio ancho `width` con el estilo `look` y devuelve la capa."""
    firebend.set_look(look)
    layer = np.zeros((H, W, 4), np.float32)
    spine = np.stack([np.full(40, 200.0), np.linspace(500, 100, 40)], axis=1)
    poly = np.vstack([spine + [width, 0], (spine - [width, 0])[::-1]])
    firebend.cel(layer, lambda k: poly, None, 1.0)
    firebend.flush_fire(layer, 0)
    firebend.set_look("hot")
    return layer


def _straight(layer: np.ndarray, y: int, x: int) -> np.ndarray:
    return layer[y, x, :3] / max(float(layer[y, x, 3]), 1e-4)


def test_cel_fire_is_flat_yellow_without_white() -> None:
    layer = _painted("cel", 6.0)
    color = _straight(layer, 300, 200)
    assert color[0] > 0.8 and color[1] > 0.8 and color[2] < 0.1  # amarillo, sin azul: nada de blanco
    assert layer[300, 200, 3] > 0.95  # opaco


def test_wide_cel_fire_has_holes() -> None:
    inside = _painted("cel", 40.0)[120:480, 175:226, 3]
    assert 0.02 < float((inside < 0.5).mean()) < 0.6  # huecos por donde se ve el fondo, no un colador


def test_mix_fire_has_white_core_only_along_thick_parts() -> None:
    thick = _painted("mix", 14.0)
    assert _straight(thick, 300, 200)[2] > 0.5  # centro de una cinta gruesa: núcleo blanco
    assert _straight(thick, 300, 211)[2] < 0.3  # cerca del borde: amarillo
    thin = _painted("mix", 3.0)
    assert _straight(thin, 300, 200)[2] < 0.3  # cinta fina: toda amarilla


def test_chapter_tint_follows_the_element_and_fades() -> None:
    st: dict = {}
    firebend._LIGHTS["bolt"] = -99
    for i in range(10):
        fire = firebend._chapter_tint(st, i, True, 1.0)
    assert fire is not None and fire[0] > fire[2] * 2  # fuego: naranja
    firebend.note_bolt(10)
    for i in range(10, 20):
        firebend.note_bolt(i)
        both = firebend._chapter_tint(st, i, False, 1.0)
    assert both is not None and both[2] > both[0] * 2  # rayo: azul
    for i in range(20, 60):
        gone = firebend._chapter_tint(st, i, False, 1.0)
    assert gone is None  # sin elementos, sin tinte


def _bolt_effect(**lightning) -> Effect:
    return Effect.model_validate({
        "id": "rayo",
        "type": "lightning",
        "target": {"kind": "joint", "id": "right_wrist"},
        "style": {"colors": [[0.35, 0.92, 1.0], [0.1, 0.62, 0.85], [0.0, 0.3, 0.75]], "lightning": lightning},
    })


def test_bolt_ribbon_is_wider_at_the_bends() -> None:
    effect = _bolt_effect(jitter=0.38)
    tree = build_bolt(np.array([50.0, 300.0]), np.array([350.0, 300.0]), ValueNoise(3), 2, effect)
    layer = np.zeros((H, W, 4), np.float32)
    _shard(layer, tree.segments[0], 30.0, effect, 1.0, 0.0)
    columns = (layer[..., 3] > 0.5).sum(axis=0)[60:340]
    assert columns.max() > 2.0 * max(np.median(columns), 1)  # tramos anchos y finos, no un tubo
    rgb = _straight(layer, *np.unravel_index(np.argmax(layer[..., 3]), layer.shape[:2]))
    assert rgb[2] > rgb[0]  # cian, no blanco


def test_bolt_reaches_the_frame_edge_along_the_forearm() -> None:
    effect = _bolt_effect(to_edge=True)
    points = {"right_elbow": np.array([300.0, 300.0]), "right_wrist": np.array([250.0, 300.0])}
    tip = _edge_tip(points["right_wrist"], effect, points, None, (H, W))
    assert tip is not None and abs(tip[0]) < 1.0 and abs(tip[1] - 300.0) < 1.0  # borde izquierdo


class _Body(dict):
    prefix = "p0"

    def mid(self, a: str, b: str):
        return (self[a] + self[b]) / 2 if a in self and b in self else None


def _runtime(frames: int = 6) -> SimpleNamespace:
    return SimpleNamespace(effect=SimpleNamespace(triggers=[]), active_frames=frames, swoosh={}, silhouettes=[], kernels={})


def _body() -> _Body:
    return _Body(
        nose=np.array([200.0, 160.0]), left_shoulder=np.array([170.0, 200.0]), right_shoulder=np.array([230.0, 200.0]),
        left_elbow=np.array([150.0, 250.0]), right_elbow=np.array([250.0, 250.0]),
        left_wrist=np.array([130.0, 300.0]), right_wrist=np.array([300.0, 260.0]),
        left_hip=np.array([180.0, 320.0]), right_hip=np.array([220.0, 320.0]),
        left_ankle=np.array([170.0, 480.0]), right_ankle=np.array([230.0, 480.0]),
    )


def _shape_mask(shape: str) -> np.ndarray:
    firebend.set_look("mix")
    layer = np.zeros((H, W, 4), np.float32)
    body = _body()
    frame = (np.array([200.0, 200.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    event = SimpleNamespace(start_frame=0, end_frame=10, kind="right", target="p0:right_wrist", name="fast_swing")
    firebend.firebend(shape, body, frame, 60.0, 5, _runtime(), layer, None, 1.0, event)
    firebend.flush_fire(layer, 5)
    firebend.set_look("hot")
    return (layer[..., 3] > 0.5).astype(np.uint8)


def test_fire_blast_leaves_the_fist_along_the_forearm() -> None:
    mask = _shape_mask("fire_blast")
    ys, xs = np.nonzero(mask)
    assert len(xs) > 2000 and xs.max() > 300 + 60  # sale del puño hacia la derecha (codo → muñeca)


def test_fire_carpet_spreads_on_the_floor_around_the_feet() -> None:
    mask = _shape_mask("fire_carpet")
    ys, xs = np.nonzero(mask)
    assert len(xs) > 4000
    assert xs.max() - xs.min() > 0.6 * W  # ancha: casi todo el cuadro
    assert ys.max() > 470  # nace en el piso, junto a los pies


def test_fire_halo_surrounds_the_body() -> None:
    mask = _shape_mask("fire_halo")
    count, _ = cv2.connectedComponents(mask)
    ys, xs = np.nonzero(mask)
    assert count - 1 >= 1 and ys.min() < 160 and ys.max() > 400  # pasa sobre la cabeza y baja a los pies
    assert mask[300, 200] == 0  # el centro (el cuerpo) queda libre: es un aro


def _event(name: str, start: int, end: int):
    from vfxglow.analysis.schema import MotionEvent

    return MotionEvent.model_validate({"name": name, "target": "person_0", "start_frame": start, "end_frame": end, "confidence": 0.8, "detail": ""})


def test_fire_wall_only_when_the_person_ends_still() -> None:
    from vfxglow.director.choreography import ends_still

    quiet = [_event("fast_swing", 100, 120), _event("lull", 420, 483)]
    assert ends_still(quiet, 484, 30.0, 1.8)  # video_18: termina arrodillado, en pausa
    walking = [_event("lull", 530, 585), _event("step", 620, 630)]
    assert not ends_still(walking, 639, 30.0, 1.8)  # video_51: la pausa terminó y camina
    jumping = [_event("lull", 420, 483), _event("jump", 470, 475)]
    assert not ends_still(jumping, 484, 30.0, 1.8)  # un salto al final: no hay pared


def _head_body(shoulders: tuple, nose=(200.0, 140.0)) -> object:
    from vfxglow.engine.bodyglow import Body

    left, right = shoulders
    pts = {
        "nose": np.array(nose), "left_eye": np.array([212.0, 130.0]), "right_eye": np.array([188.0, 130.0]),
        "left_ear": np.array([225.0, 135.0]), "right_ear": np.array([175.0, 135.0]),
        "left_shoulder": np.array(left), "right_shoulder": np.array(right),
        "left_hip": np.array([220.0, 380.0]), "right_hip": np.array([180.0, 380.0]),
    }
    return Body(pts, None)


def test_avatar_arrow_points_at_the_face_from_the_front() -> None:
    body = _head_body(((250.0, 200.0), (150.0, 200.0)))  # de frente: el hombro izquierdo a la derecha
    path, tip, _ = firebend._arrow_path(body, body.frame(), body.scale)
    assert tip  # la punta de la frente se ve
    assert abs(path[0][0] - 200.0) < 6 and path[0][1] < 130.0  # centrada, arriba de los ojos
    assert path[-1][1] < path[0][1] - 30  # la banda sube hacia la coronilla


def test_avatar_arrow_runs_down_the_spine_from_the_back() -> None:
    body = _head_body(((150.0, 200.0), (250.0, 200.0)))  # de espaldas: el hombro izquierdo a la izquierda
    path, tip, _ = firebend._arrow_path(body, body.frame(), body.scale)
    assert not tip  # la frente no se ve
    assert path[0][1] < 120.0 and path[-1][1] > 300.0  # de la coronilla a la parte baja de la espalda


def test_fire_wall_needs_the_person_facing_front() -> None:
    def wall(shoulders) -> float:
        body = _head_body(shoulders)
        runtime = SimpleNamespace(swoosh={}, frame_count=100, fps=30.0, effect=SimpleNamespace(style=SimpleNamespace(size=1.8)), silhouettes=[], kernels={})
        layer = np.zeros((H, W, 4), np.float32)
        for f in range(60, 100):
            firebend._fire_wall(body, body.frame(), body.scale, f, runtime, layer, (1.0, 0.4, 0.05), 1.0, None)
        firebend.flush_fire(layer, 99)
        return float(layer[..., 3].mean())

    assert wall(((250.0, 200.0), (150.0, 200.0))) > 0.05  # de frente: hay pared
    assert wall(((150.0, 200.0), (250.0, 200.0))) == 0.0  # de espaldas: no


def _carpet_end(front_frames: int, total: int = 150, wall: bool = False) -> float:
    """Cobertura de la alfombra del cierre en el último cuadro, con la persona de frente en los
    últimos `front_frames` cuadros (antes, de espaldas)."""
    front, back = _head_body(((250.0, 200.0), (150.0, 200.0))), _head_body(((150.0, 200.0), (250.0, 200.0)))
    for body in (front, back):
        body.points.update(left_ankle=np.array([180.0, 480.0]), right_ankle=np.array([220.0, 480.0]))
    runtime = SimpleNamespace(swoosh={}, frame_count=total, fps=30.0, silhouettes=[], kernels={}, active_frames=0, effect=SimpleNamespace(triggers=[]))
    firebend._CLOSING["wall"] = (total, total - 1) if wall else (0, -99)
    layer = np.zeros((H, W, 4), np.float32)
    for f in range(total):
        layer[:] = 0
        body = front if f >= total - front_frames else back
        firebend._carpet_end(body, body.scale, f, runtime, layer, (1.0, 0.4, 0.05), 1.0)
        firebend.flush_fire(layer, f)
    firebend._CLOSING["wall"] = (0, -99)
    return float((layer[..., 3] > 0.5).mean())


def test_closing_carpet_only_after_two_seconds_facing_front() -> None:
    assert _carpet_end(75) > 0.05  # 2,5 s de frente al final: sale la alfombra
    assert _carpet_end(30) == 0.0  # solo 1 s de frente: no
    assert _carpet_end(0) == 0.0  # de espaldas: no
    assert _carpet_end(75, wall=True) == 0.0  # si salió la pared, la alfombra cede


def test_closing_carpet_rises_from_the_bottom_edge_only_at_the_very_end() -> None:
    total = 267  # video de 8,9 s: antes nacía a los 5,9 s, a media altura del cuadro
    front = _head_body(((250.0, 200.0), (150.0, 200.0)))
    front.points.update(left_ankle=np.array([180.0, 300.0]), right_ankle=np.array([220.0, 300.0]))  # pies a media altura
    runtime = SimpleNamespace(swoosh={}, frame_count=total, fps=30.0, silhouettes=[], kernels={}, active_frames=0, effect=SimpleNamespace(triggers=[]))
    firebend._CLOSING["wall"] = (0, -99)
    first = None
    layer = np.zeros((H, W, 4), np.float32)
    for f in range(total):
        layer[:] = 0
        firebend._carpet_end(front, front.scale, f, runtime, layer, (1.0, 0.4, 0.05), 1.0)
        firebend.flush_fire(layer, f)
        if first is None and layer[..., 3].max() > 0.5:
            first = f
    assert first is not None and first >= total * 0.8  # solo en el último 20% del video
    rows = np.nonzero((layer[..., 3] > 0.5).any(axis=1))[0]
    assert rows.max() >= H - 2 and rows.min() > H * 0.6  # pegada al borde de abajo, sube hasta un tercio


def _trail(path, joint: str = "right_wrist") -> np.ndarray:
    """Máscara del swoosh de fuego en el último cuadro, con la extremidad recorriendo `path`."""
    return _trail_frames(path, joint)[-1]


def _trail_frames(path, joint: str = "right_wrist") -> list[np.ndarray]:
    """Máscaras del swoosh de fuego cuadro a cuadro, con la extremidad recorriendo `path`."""
    out = []
    body = _body()
    frame = (np.array([200.0, 200.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    event = SimpleNamespace(start_frame=0, end_frame=60, kind="", target=f"p0:{joint}", name="fast_swing")
    runtime = _runtime(0)
    firebend.set_look("hot")
    layer = np.zeros((H, W, 4), np.float32)
    for f, point in enumerate(path):
        runtime.active_frames = f + 1
        body[joint] = np.array(point, dtype=np.float64)
        layer[:] = 0
        firebend._fire_trail(body, frame, 60.0, f, runtime, layer, None, 1.0, event)
        firebend.flush_fire(layer, f)
        out.append((layer[..., 3] > 0.5).astype(np.uint8))
    return out


def test_fire_trail_is_lit_still_and_chases_the_hand_when_it_moves() -> None:
    still = _trail([(300.0, 300.0)] * 12)
    ys, xs = np.nonzero(still)
    assert len(xs) > 0 and xs.max() - xs.min() < 60  # quieta: solo la llama prendida en la mano
    moving = _trail([(60.0 + 22 * i, 330.0) for i in range(12)])  # de izquierda a derecha
    ys, xs = np.nonzero(moving)
    assert xs.min() < 60.0 + 22 * 11 - 120 and xs.max() > 60.0 + 22 * 11 - 20  # la estela queda atrás, en el recorrido


def test_fire_trail_follows_a_kicking_foot() -> None:
    ys, xs = np.nonzero(_trail([(60.0 + 22 * i, 470.0) for i in range(12)], "right_ankle"))
    assert len(ys) and ys.mean() > 380  # el fuego va en el pie, no en la mano


def test_fire_trail_does_not_hook_after_a_sharp_turn() -> None:
    there = [(60.0 + 25 * i, 330.0) for i in range(8)]
    back = [(there[-1][0] - 25 * i, 330.0 - 3 * i) for i in range(1, 5)]
    ys, xs = np.nonzero(_main_piece(_trail(there + back)))  # sin las escamas sueltas
    # Solo el tramo de vuelta (exagerado 1,5 veces hacia atrás), sin el gancho de ida.
    assert xs.max() < there[-1][0] + 100 and xs.min() > there[0][0] + 60


def test_fire_trail_changes_smoothly_with_a_shaky_detector() -> None:
    # Un arco con el detector temblando ±4 px: la estela no salta de un cuadro al siguiente.
    rng = np.random.default_rng(3)
    t = np.linspace(0.0, np.pi, 16)
    path = [(200 - 130 * np.cos(a) + rng.uniform(-4, 4), 330 - 90 * np.sin(a) + rng.uniform(-4, 4)) for a in t]
    masks = _trail_frames(path)
    for (a, b), point in zip(zip(masks[6:-1], masks[7:]), path[7:]):
        ys, xs = np.nonzero(b)
        ya, xa = np.nonzero(a)
        # La forma vista desde la mano: su centro se corre poco de un cuadro al otro.
        prev_point = path[path.index(point) - 1]
        moved = np.hypot((xs.mean() - point[0]) - (xa.mean() - prev_point[0]), (ys.mean() - point[1]) - (ya.mean() - prev_point[1]))
        assert moved < 25


def test_fire_trail_recoils_into_the_hand_when_it_stops() -> None:
    run = [(60.0 + 22 * i, 330.0) for i in range(12)]
    stop = [run[-1]] * 10
    widths = [int(np.ptp(np.nonzero(m)[1])) for m in map(_main_piece, _trail_frames(run + stop))]
    moving, after = widths[11], widths[12:]
    assert after[1] > 0.5 * moving  # no se corta de golpe al frenar
    assert after[5] < 0.25 * moving  # en ~5 cuadros queda solo la llama de la mano
    shrinking = after[: after.index(min(after)) + 1]
    assert all(b <= a for a, b in zip(shrinking, shrinking[1:]))  # se recoge, sin estirarse de vuelta


def _main_piece(mask: np.ndarray) -> np.ndarray:
    """La pieza más grande de la máscara (sin las escamas que se desprenden)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    return (labels == 1 + int(np.argmax(stats[1:, 4]))).astype(np.uint8) if n > 1 else mask


def test_bolt_comes_only_from_the_hands() -> None:
    from vfxglow.engine.lightning import _hand

    points = {"left_wrist": np.array([100.0, 200.0]), "right_wrist": np.array([300.0, 200.0]),
              "vel:left_wrist": np.array([1.0, 0.0]), "vel:right_wrist": np.array([9.0, 0.0]), "left_ankle": np.array([150.0, 480.0])}
    left = SimpleNamespace(target="left_wrist")
    assert np.allclose(_hand(points, left), points["left_wrist"])  # la mano del gesto
    kick = SimpleNamespace(target="left_ankle")
    assert np.allclose(_hand(points, kick), points["right_wrist"])  # una patada: la mano que más se mueve, nunca el pie


def _feet_body() -> "_Body":
    body = _body()
    body.update({"vel:left_wrist": np.array([0.5, 0.0]), "vel:right_wrist": np.array([0.5, 0.0]),
                 "vel:left_ankle": np.array([14.0, -6.0]), "vel:right_ankle": np.array([12.0, -8.0])})
    return body


def test_fire_goes_to_the_feet_in_a_flip_and_travels_there_from_the_hands() -> None:
    frame = (np.array([200.0, 200.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    runtime = _runtime(0)
    firebend._FIRE_LIMBS.clear()
    hands = SimpleNamespace(start_frame=0, end_frame=10, kind="", target="p0", name="fast_swing")
    flip = SimpleNamespace(start_frame=12, end_frame=40, kind="", target="p0", name="flip")
    body = _body()
    for f in range(0, 10):  # el fuego en las manos
        layer = np.zeros((H, W, 4), np.float32)
        runtime.active_frames = f + 1
        firebend._fire_trail(body, frame, 60.0, f, runtime, layer, None, 1.0, hands)
        firebend.flush_fire(layer, f)
    feet = _feet_body()
    masks = []
    for f in range(12, 24):  # voltereta: el fuego pasa a los pies
        layer = np.zeros((H, W, 4), np.float32)
        runtime.active_frames = f - 11
        firebend._fire_trail(feet, frame, 60.0, f, runtime, layer, None, 1.0, flip)
        firebend.flush_fire(layer, f)
        masks.append(layer[..., 3] > 0.5)
    early, late = masks[3], masks[-1]
    ys, _ = np.nonzero(early)
    assert len(ys) and ys.min() < 400  # viajando: el fuego todavía está entre las manos y los pies
    ys, _ = np.nonzero(late)
    assert len(ys) and ys.mean() > 380  # ya llegó: prendido en los pies


def test_fire_stays_in_the_hands_when_they_lead() -> None:
    st: dict = {}
    body = _body()
    body.update({"vel:left_wrist": np.array([12.0, 0.0]), "vel:left_ankle": np.array([1.0, 0.0])})
    assert firebend._attention_limbs(body, None, st) == firebend.HANDS
    assert firebend._attention_limbs(_feet_body(), SimpleNamespace(target="p0", name="tumble", kind=""), {}) == firebend.FEET


def test_fire_travels_from_one_hand_to_the_other_in_curled_pieces() -> None:
    body = _body()  # muñecas en (130, 300) y (300, 260)
    firebend._FIRE_LIMBS.clear()
    firebend.note_fire(body, ("left_wrist",), 0)  # el fuego estaba en la mano izquierda
    st: dict = {}
    lit, between = [], []
    for f in range(1, 14):
        layer = np.zeros((H, W, 4), np.float32)
        lit.append(firebend.transfer_fire(body, ("right_wrist",), f, 60.0, layer, None, 1.0, _runtime(f), st)["right_wrist"])
        firebend.flush_fire(layer, f)
        mask = layer[..., 3] > 0.5
        between.append(int(mask[:, 170:260].sum()))  # entre las dos manos
    assert max(lit[:6]) == 0.0 and lit[-1] == 1.0  # el destino se prende recién al llegar
    assert max(between[3:9]) > 30  # a mitad de camino hay trocitos entre las manos
    assert firebend._FIRE_LIMBS["p0"][0] == ("right_wrist",)  # ahora el fuego está en la derecha


def test_no_transfer_when_the_fire_is_already_there() -> None:
    body = _body()
    firebend._FIRE_LIMBS.clear()
    firebend.note_fire(body, ("right_wrist",), 0)
    layer = np.zeros((H, W, 4), np.float32)
    assert firebend.transfer_fire(body, ("right_wrist",), 1, 60.0, layer, None, 1.0, _runtime(1), {}) == {"right_wrist": 1.0}


def _landing(feet_fire: bool) -> tuple[np.ndarray, SimpleNamespace]:
    body = _body()
    firebend._FIRE_LIMBS.clear()
    if feet_fire:
        firebend.note_fire(body, firebend.FEET, 10)  # venía con el fuego en los pies (voltereta)
    else:
        firebend.note_fire(body, firebend.HANDS, 10)
    runtime = _runtime(4)
    runtime.fps = 30.0
    event = SimpleNamespace(start_frame=14, end_frame=16, kind="", target="p0", name="landing")
    frame = (np.array([200.0, 200.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    layer = np.zeros((H, W, 4), np.float32)
    firebend.firebend("fire_landing", body, frame, 60.0, 18, runtime, layer, None, 1.0, event)
    firebend.flush_fire(layer, 18)
    return layer[..., 3] > 0.5, runtime


def test_fire_breaks_up_on_the_floor_only_if_it_came_in_the_feet() -> None:
    from vfxglow.engine.critters import _state

    mask, runtime = _landing(True)
    ys, xs = np.nonzero(mask)
    assert len(ys) and ys.mean() > 380 and xs.max() - xs.min() > 100  # se desbarata alrededor de los pies
    assert "p0" not in firebend._FIRE_LIMBS  # el fuego se gastó en el piso
    assert _state(runtime, "landing:p0:14").get("feet") is True
    _mask, runtime = _landing(False)
    assert _state(runtime, "landing:p0:14").get("feet") is False  # si no, el golpe de piso


def _orbit(frames: range, arm_out: bool) -> tuple[list[float], dict]:
    from vfxglow.engine.critters import _state

    body = _body()
    body.update(right_elbow=np.array([260.0, 260.0]), right_wrist=np.array([235.0, 215.0]))  # brazo doblado
    runtime = _runtime(0)
    event = SimpleNamespace(start_frame=0, end_frame=20, kind="right", target="p0:right_wrist", name="lunge")
    frame = (np.array([200.0, 200.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    xs = []
    for f in frames:
        if arm_out and f == 28:  # después de atraparlo, estira el brazo (el puñetazo)
            body.update(right_elbow=np.array([290.0, 205.0]), right_wrist=np.array([350.0, 210.0]))
        runtime.active_frames = f + 1
        layer = np.zeros((H, W, 4), np.float32)
        firebend._fire_orbit(body, frame, 60.0, f, runtime, layer, None, 1.0, event)
        firebend.flush_fire(layer, f)
        mask = layer[..., 3] > 0.5
        xs.append(float(np.nonzero(mask)[1].min()) if mask.any() else -1.0)
    return xs, _state(runtime, "orbit:right_wrist:p0:0")


def test_fire_orbit_circles_the_body_and_only_explodes_with_the_arm_out() -> None:
    xs, _st = _orbit(range(0, 12), arm_out=False)
    assert min(x for x in xs if x >= 0) < 150 and max(xs) > 200  # da la vuelta: llega al otro lado del cuerpo y vuelve
    _xs, bent = _orbit(range(0, 40), arm_out=False)
    assert bent.get("thrown") is None  # brazo doblado: la llama se apaga en la mano
    _xs, out = _orbit(range(0, 40), arm_out=True)
    assert out.get("thrown") is not None and out["burst_at"][0] > 350  # brazo estirado: explota hacia afuera


def test_beasts_fly_an_arc_return_to_the_hand_and_burst_on_the_punch() -> None:
    from vfxglow.engine.critters import _state
    from vfxglow.engine.fire_creatures import fire_creature

    for shape in ("fire_phoenix", "fire_dragon_launch"):
        body = _body()
        body.update(right_elbow=np.array([260.0, 260.0]), right_wrist=np.array([300.0, 240.0]))  # brazo doblado
        runtime = _runtime(0)
        runtime.fps = 30.0
        runtime.effect = SimpleNamespace(triggers=[SimpleNamespace(hold=72)])  # como en el catálogo
        event = SimpleNamespace(start_frame=0, end_frame=2, kind="right", target="p0:right_wrist", name="throw")
        frame = (np.array([200.0, 200.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
        hand = body["right_wrist"]
        far = []
        for f in range(0, 50):
            if f == 40:  # el puñetazo: el brazo se estira
                body.update(right_elbow=np.array([290.0, 205.0]), right_wrist=np.array([350.0, 210.0]))
            runtime.active_frames = f + 1
            layer = np.zeros((H, W, 4), np.float32)
            fire_creature(shape, body, frame, 60.0, f, runtime, layer, None, 1.0, event)
            firebend.flush_fire(layer, f)
            ys, xs = np.nonzero(layer[..., 3] > 0.5)
            far.append(float(np.max(np.hypot(xs - hand[0], ys - hand[1]))) if len(xs) else -1.0)
        assert max(far[8:22]) > 150, shape  # sale del puño y hace su arco lejos de la mano
        assert 0 <= far[34] < 0.6 * max(far[8:22]), shape  # volvió: queda como una llama en la mano
        punch = _state(runtime, "beast:right_wrist:p0:0").get("punch", {})
        assert punch.get("thrown") == 40, shape  # el puñetazo la usa


def _beast_run(shape: str, frames: int, punch_at: int | None = None) -> tuple[list[np.ndarray], SimpleNamespace]:
    from vfxglow.engine.fire_creatures import fire_creature

    body = _body()
    body.update(right_elbow=np.array([260.0, 260.0]), right_wrist=np.array([300.0, 240.0]))
    runtime = _runtime(0)
    runtime.fps = 30.0
    runtime.effect = SimpleNamespace(triggers=[SimpleNamespace(hold=72)])
    event = SimpleNamespace(start_frame=0, end_frame=2, kind="right", target="p0:right_wrist", name="spin_body")
    frame = (np.array([200.0, 200.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    masks = []
    for f in range(frames):
        if punch_at is not None and f == punch_at:
            body.update(right_elbow=np.array([290.0, 205.0]), right_wrist=np.array([350.0, 210.0]))
        runtime.active_frames = f + 1
        layer = np.zeros((H, W, 4), np.float32)
        fire_creature(shape, body, frame, 60.0, f, runtime, layer, None, 1.0, event)
        firebend.flush_fire(layer, f)
        masks.append(layer[..., 3] > 0.5)
    return masks, runtime


def test_coil_serpent_circles_the_body_and_returns_to_the_hand() -> None:
    masks, _rt = _beast_run("fire_coil", 40)
    xs = [np.nonzero(m)[1] for m in masks]
    assert min(x.min() for x in xs[10:20] if len(x)) < 150 and max(x.max() for x in xs[10:20] if len(x)) > 250  # rodea el cuerpo
    hand = np.array([300.0, 240.0])
    ys, xx = np.nonzero(masks[38])
    assert len(ys) and float(np.max(np.hypot(xx - hand[0], ys - hand[1]))) < 120  # vuelve: llama en la mano


def test_kitsune_fans_nine_tails_upward() -> None:
    masks, _rt = _beast_run("fire_kitsune", 12)
    ys, _xs = np.nonzero(masks[10])
    hips_y = 320.0
    assert len(ys) and np.mean(ys < hips_y) > 0.8  # las colas van hacia arriba de la cadera (no como patas)


def test_lion_slashes_only_on_the_punch() -> None:
    from vfxglow.engine.critters import _state

    _m, rt = _beast_run("fire_lion", 30)
    assert "slash" not in _state(rt, "lion:p0:0")  # sin golpe, no hay zarpazo
    _m, rt = _beast_run("fire_lion", 30, punch_at=20)
    assert _state(rt, "lion:p0:0")["slash"][0] == 20  # el zarpazo sale en el golpe


def test_fire_palette_and_pixel_change_how_the_fire_is_painted() -> None:
    def paint(palette_name: str, pixel: float = 0.0) -> np.ndarray:
        firebend.set_look("hot", palette_name, pixel)
        layer = np.zeros((H, W, 4), np.float32)
        spine = np.stack([np.full(40, 200.0), np.linspace(500, 100, 40)], axis=1)
        poly = np.vstack([spine + [14.0, 0], (spine - [14.0, 0])[::-1]])
        firebend.cel(layer, lambda k: poly, None, 1.0)
        firebend.flush_fire(layer, 0)
        firebend.set_look("hot")
        return layer

    orange, blue, green = paint("naranja"), paint("azul"), paint("verde")
    rim = (300, 216)  # justo afuera del cuerpo: el borde
    assert orange[rim][0] > orange[rim][2] and blue[rim][2] > blue[rim][0] and green[rim][1] > green[rim][2]
    blocky = paint("naranja", 0.03)[..., 3] > 0.5
    rows = np.nonzero(blocky.any(axis=1))[0]
    assert (rows.max() - rows.min() + 1) % 18 == 0 or len(np.unique(blocky.sum(axis=1)[rows])) <= 3  # bloques de píxel


def test_looks_apply_over_the_catalog_without_touching_it() -> None:
    from pathlib import Path

    from vfxglow.director.choreography import _effect, load_catalog
    from vfxglow.director.looks import apply_looks

    original = load_catalog(Path("configs/catalogs/avatar.yaml"))
    themed = apply_looks(original, "azul", "violeta")
    assert _effect(themed, themed.always[0], "x")["style"]["fire_palette"] == "azul"  # también la luz del fuego
    colors = {o.name: e["style"]["colors"][1] for r in themed.reactions for o in r.options for e in o.effects if e.get("type") == "lightning"}
    assert colors["rayo"] == [0.72, 0.3, 1.0] and colors["rayo_fuego"] == [1.0, 0.5, 0.1]  # el rayo de fuego no cambia
    assert "fire_palette" not in original.defaults.get("style", {})  # el original intacto


def test_a_dying_flame_goes_from_the_top_down_and_stays_opaque() -> None:
    st: dict = {}
    base = np.array([200.0, 520.0])
    tops, areas, peak = [], [], []
    for k, u in enumerate(np.linspace(0.6, 0.95, 8)):
        layer = np.zeros((600, 400, 4), np.float32)
        spine, widths = firebend.flame_parts(base, np.array([0.0, -1.0]), 360.0, 80.0, 10, 1.3)[0]
        firebend.living_ribbon(layer, spine, widths, float(u), st, 10 + k, None, 1.0, None, grow_from_end=False)
        firebend.flush_fire(layer, 10 + k)
        m = layer[..., 3] > 0.5
        ys = np.nonzero(m.any(axis=1))[0]
        tops.append(ys.min() if len(ys) else 600)
        areas.append(int(m.sum()))
        peak.append(float(layer[..., 3].max()))
    assert all(b >= a for a, b in zip(tops, tops[1:])) and tops[5] > tops[0] + 100  # baja desde arriba
    assert areas[-1] < 0.1 * areas[0] and areas[3] > 0.4 * areas[0]  # se consume poco a poco
    assert min(p for p, a in zip(peak, areas) if a > 50) > 0.8  # opaca mientras queda algo (no se vuelve transparente)


def test_the_floor_fire_is_a_wide_lace_that_dies_in_pieces() -> None:
    # Como la caída de video_51 (seg. 2,4-2,9): baja y ancha, con huecos, y muere en ~10 cuadros.
    st: dict = {}
    frames = 24
    holes, heights, areas, pieces = [], [], [], []
    for k in range(frames):
        u = (k + 0.5) / frames
        layer = np.zeros((1000, 560, 4), np.float32)
        grow = firebend._ease_out(min(u / 0.1, 1.0))
        firebend._floor_burst(layer, 280.0, 760.0, 250.0, 80.0, grow, 40 + k, 7, (1.0, 0.6, 0.1), 1.0, None)
        firebend.flush_fire(layer, 40 + k, u, st)
        m = (layer[..., 3] > 0.5).astype(np.uint8)
        _contours, tree = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        holes.append(0 if tree is None else int((tree[0][:, 3] >= 0).sum()))
        ys = np.nonzero(m.any(axis=1))[0]
        heights.append(760 - ys.min() if len(ys) else 0)
        areas.append(int(m.sum()))
        pieces.append(cv2.connectedComponents(m)[0] - 1)
    peak = int(np.argmax(areas))
    assert max(holes[2:14]) >= 8  # encaje: se ve el piso por los huecos
    assert max(heights) <= 0.22 * 1000  # baja: no pasa del 22% del cuadro
    alive = [k for k, a in enumerate(areas) if a > 0.05 * areas[peak]]
    assert alive[-1] - peak <= 14 and alive[-1] < frames - 1  # se apaga en pocos cuadros
    assert max(pieces[peak:]) >= 8  # al morir se parte en trozos


def _lion_ink(open_mouth: float = 0.0) -> np.ndarray:
    from vfxglow.engine.lion_head import ink_steps, lion_head, place

    img = np.zeros((500, 500), np.uint8)
    for poly, ink in ink_steps(lion_head(open_mouth)):
        q = place(poly, np.array([250.0, 250.0]), 100.0, np.array([0.0, -1.0]), np.array([1.0, 0.0]))
        cv2.fillPoly(img, [np.round(q).astype(np.int32)], 255 if ink else 0)
    return img > 0


def test_the_lion_head_is_symmetric_with_a_face_carved_in_the_ink() -> None:
    ink = _lion_ink()
    mirrored = ink[:, ::-1]
    assert (ink & mirrored).sum() / max(ink.sum(), 1) > 0.95  # simétrica (el copete en S apenas se corre)
    assert cv2.connectedComponents(ink.astype(np.uint8))[0] - 1 >= 20  # mechones separados por ranuras
    assert not ink[148:158, 242:258].any() and not ink[230:250, 160:180].any()  # frente y mejilla, vacías (la cara)
    assert (_lion_ink(1.0) ^ ink).sum() > 300  # al rugir, la boca se abre


def test_the_neon_lion_draws_the_tribal_mask() -> None:
    from vfxglow.engine.stories import _lion_roar

    body = _body()
    frame = (np.array([200.0, 300.0]), np.array([1.0, 0.0]), np.array([0.0, 1.0]))
    runtime = _runtime(0)
    event = SimpleNamespace(start_frame=0, end_frame=30, kind="", target="person_0", name="spotlight")
    layer = np.zeros((H, W, 4), np.float32)
    lines = _lion_roar(body, frame, 60.0, 10, runtime, layer, (0.3, 0.9, 1.0), 1.0, event, None)
    assert len(lines) > 20 and layer[..., 3].max() > 0  # mechones, rasgos y la masa tenue de la melena


def test_neon_on_the_face_has_a_short_faint_halo() -> None:
    from vfxglow.engine.swoosh import FACE_HALO, neon_layers

    curve = np.array([[0.0, 0.0], [50.0, 0.0]])
    full, face = neon_layers(curve, np.ones(3), 3.0, 1.0), neon_layers(curve, np.ones(3), 3.0, 1.0, halo=FACE_HALO)
    assert face[0][3] < 0.4 * full[0][3] and face[0][2] < full[0][2]  # el halo ancho: tenue y más corto
    assert face[-1][3] == full[-1][3]  # el filamento blanco no cambia
