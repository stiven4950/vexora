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
    return (layer[..., 3] > 0.5).astype(np.uint8)


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
    ys, xs = np.nonzero(_trail(there + back))
    # Solo el tramo de vuelta (exagerado 1,5 veces hacia atrás), sin el gancho de ida.
    assert xs.max() < there[-1][0] + 100 and xs.min() > there[0][0] + 60


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
