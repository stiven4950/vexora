"""Tierra control (engine/earthbend.py): escombros, grietas, roca sombreada y las figuras."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from vfxglow.engine import earthbend

H, W = 600, 400


class _Body:
    prefix = ""

    def __init__(self, **points) -> None:
        self.points = points

    def get(self, name):
        return self.points.get(name)


def _body() -> _Body:
    return _Body(
        nose=np.array([200.0, 160.0]), left_shoulder=np.array([170.0, 200.0]), right_shoulder=np.array([230.0, 200.0]),
        left_elbow=np.array([150.0, 250.0]), right_elbow=np.array([250.0, 250.0]),
        left_wrist=np.array([130.0, 300.0]), right_wrist=np.array([300.0, 260.0]),
        left_hip=np.array([180.0, 320.0]), right_hip=np.array([220.0, 320.0]),
        left_ankle=np.array([170.0, 480.0]), right_ankle=np.array([230.0, 480.0]),
    )


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(effect=SimpleNamespace(triggers=[SimpleNamespace(hold=10)]), active_frames=1, swoosh={}, fps=30.0, silhouettes=[], kernels={})


def _event() -> SimpleNamespace:
    return SimpleNamespace(start_frame=0, end_frame=29, kind="right", target="p0:right_wrist", name="fast_swing")


def _play(shape: str, frames: int, body=None):
    """Corre la figura `frames` cuadros; devuelve la capa del último, el estado y el cuerpo."""
    body, runtime, event = body or _body(), _runtime(), _event()
    layer = np.zeros((H, W, 4), np.float32)
    for f in range(frames):
        runtime.active_frames = f + 1
        layer = np.zeros((H, W, 4), np.float32)
        out = earthbend.earthbend(shape, body, (None, None, None), 60.0, f, runtime, layer, None, 1.0, event)
        assert out == []
    return layer, runtime.swoosh["_critters"]


def test_debris_falls_bounces_with_less_speed_and_settles() -> None:
    st = {"debris": [[np.array([200.0, 300.0]), np.array([4.0, 0.0]), 6.0, 0.0, 0.3, 0]]}
    impact = bounce = None
    settled_at = None
    for frame in range(60):
        before = st["debris"][0][1].copy()
        shards = earthbend.step_debris(st, H, floor=400.0)
        assert shards, "el escombro no debería desaparecer antes de asentarse"
        pos, vel = shards[0][0], shards[0][1]
        if impact is None and vel[1] < 0:
            impact, bounce = before[1], -vel[1]
        if not vel.any() and pos[1] >= 399.0:
            settled_at = frame
            break
    assert impact is not None and 0 < bounce < 0.5 * impact  # rebota con menos velocidad (restitución)
    assert settled_at is not None and settled_at < 60  # y se asienta
    assert st["debris"][0][0][1] == 400.0


def test_cracks_start_at_the_contact_and_grow_monotonically() -> None:
    origin = np.array([200.0, 480.0])
    for grow in (0.05, 0.5, 1.0):
        mains = earthbend.ground_cracks(origin, 60.0, 7, grow, subs=False)
        assert 5 <= len(mains) <= 8
        assert all(float(np.linalg.norm(c[0] - origin)) <= 2.0 for c in mains)  # nacen en el contacto
    totals = []
    for grow in np.linspace(0.05, 1.0, 12):
        cracks = earthbend.ground_cracks(origin, 60.0, 7, float(grow))
        totals.append(sum(float(np.linalg.norm(np.diff(c, axis=0), axis=1).sum()) for c in cracks))
    assert all(b >= a - 1e-6 for a, b in zip(totals, totals[1:])) and totals[-1] > 2 * totals[0]
    assert earthbend.ground_cracks(origin, 60.0, 7, 0.0) == []
    full = earthbend.ground_cracks(origin, 60.0, 7, 1.0, subs=False)
    assert max(float(np.ptp(c[:, 1])) for c in full) < max(float(np.ptp(c[:, 0])) for c in full)  # aplastadas por la perspectiva


def test_a_rock_is_shaded_and_opaque() -> None:
    layer = np.zeros((300, 300, 4), np.float32)
    center = np.array([150.0, 150.0])
    facets, outline = earthbend.rock_polygon(center, 100.0, 3, 0.0)
    assert 6 <= len(outline) <= 9 and 3 <= len(facets) <= 4
    earthbend.draw_rock(layer, facets, 1.0)

    def mean_rgb(facet) -> np.ndarray:
        poly = facet[0]
        p = poly[0] * 0.4 + poly[1:].mean(axis=0) * 0.6
        x, y = int(round(p[0])), int(round(p[1]))
        return layer[y - 1 : y + 2, x - 1 : x + 2, :3].mean(axis=(0, 1))

    lit, dark = max(facets, key=lambda f: f[1]), min(facets, key=lambda f: f[1])
    assert lit[1] - dark[1] > 0.2
    assert mean_rgb(lit).mean() > mean_rgb(dark).mean() + 0.05  # la que mira a la luz es más clara
    assert layer[150, 150, 3] >= 0.9  # opaca en el centro


def test_slam_cracks_the_floor_at_the_foot_and_throws_debris() -> None:
    layer, store = _play("earth_slam", 30)
    body = _body()
    foot_x, floor = 170.0, 480.0 + 0.02 * 60.0
    unit = max(60.0, 0.07 * H)
    near = layer[int(floor - unit) : int(floor + unit), int(foot_x - unit) : int(foot_x + unit), 3]
    assert near.max() > 0.3  # grietas junto al pie, sobre la línea del piso
    state = next(v for k, v in store.items() if k.startswith("earth:slam"))
    # Los escombros salen al cuadro 3: se mira a lo largo de la vida que estén por encima del piso.
    runtime, event = _runtime(), _event()
    highest = floor
    for f in range(12):
        runtime.active_frames = f + 1
        earthbend.earthbend("earth_slam", body, (None, None, None), 60.0, f, runtime, np.zeros((H, W, 4), np.float32), None, 1.0, event)
        key = next(k for k in runtime.swoosh["_critters"] if k.startswith("earth:slam"))
        for shard in runtime.swoosh["_critters"][key].get("debris", []):
            highest = min(highest, float(shard[0][1]))
    assert highest < floor - 0.3 * unit
    assert state["origin"][1] == pytest.approx(floor)


@pytest.mark.parametrize("shape", earthbend.EARTHBEND)
def test_every_shape_draws_something(shape: str) -> None:
    layer, _ = _play(shape, 12)
    assert float(layer[..., 3].max()) > 0.0
