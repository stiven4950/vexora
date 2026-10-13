"""Pareja: cuándo bailan al unísono y quién lleva el turno (docs/criterio_de_analisis.md, P13).

Referencia video_34: dos bailarines que casi siempre hacen el mismo paso. Cuando bailan igual, el
creador dibuja lo mismo en los dos, cada uno con su color; cuando uno se aparta (se abre el saco,
se lleva la mano a la cabeza, gira), solo ese se enciende y el otro queda limpio.

- Unísono: las dos poses (articulaciones relativas a la cadera, en torsos) se parecen, con una
  tolerancia de LAG_S (no van sincronizados al cuadro) y en espejo o no (uno puede ir con la
  pierna contraria). Distancia media suavizada por debajo de UNISON_D; la de dos momentos al azar
  del mismo video ronda 0,38.
- Solo: el resto del tiempo. Lleva el turno quien más se mueve en ese tramo.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from vfxglow.analysis.schema import DuetSpan, FrameRecord
from vfxglow.analysis.touch import _people

JOINTS = (
    "left_wrist", "right_wrist", "left_elbow", "right_elbow",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)
MIRROR = [JOINTS.index(n.replace("left", "@").replace("right", "left").replace("@", "right")) for n in JOINTS]
UNISON_D = 0.2
LAG_S = 0.2
SMOOTH_S = 0.5
ENERGY_S = 0.8
MIN_SPAN_S = 0.5
# Con menos de esta fracción de fotogramas con las dos personas, no es una pareja.
MIN_TOGETHER = 0.5


def _poses(frames: list[FrameRecord], person: str, width: int, height: int) -> np.ndarray:
    """(fotogramas, articulaciones, 2): posición relativa a la cadera en torsos; NaN si no se ve."""
    out = np.full((len(frames), len(JOINTS), 2), np.nan)
    for index, record in enumerate(frames):
        owner = next((p for p in _people(record) if p.person_id == person), None)
        if owner is None:
            continue
        lm = {l.name: np.array([l.x * width, l.y * height]) for l in owner.pose if l.c > 0.3}
        if not all(k in lm for k in ("left_hip", "right_hip", "left_shoulder", "right_shoulder")):
            continue
        hip = (lm["left_hip"] + lm["right_hip"]) / 2
        torso = max(float(np.linalg.norm((lm["left_shoulder"] + lm["right_shoulder"]) / 2 - hip)), 1.0)
        for j, name in enumerate(JOINTS):
            if name in lm:
                out[index, j] = (lm[name] - hip) / torso
    return out


def _distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Distancia media por fotograma entre articulaciones visibles en las dos (NaN si hay pocas)."""
    d = np.linalg.norm(a - b, axis=-1)
    seen = ~np.isnan(d)
    total = np.where(seen, d, 0.0).sum(axis=1)
    count = seen.sum(axis=1)
    return np.where(count >= 5, total / np.maximum(count, 1), np.nan)


def _smooth(values: np.ndarray, size: int) -> np.ndarray:
    fill = np.where(np.isnan(values), np.nanmedian(values) if np.isfinite(values).any() else 0.0, values)
    kernel = np.ones(max(size, 1)) / max(size, 1)
    return np.convolve(fill, kernel, mode="same")


def _runs(labels: list, shortest: int) -> list[tuple[int, int, object]]:
    """Tramos de etiqueta constante; los más cortos que `shortest` se funden con el anterior."""
    runs: list[list] = []
    for index, label in enumerate(labels):
        if runs and runs[-1][2] == label:
            runs[-1][1] = index
        else:
            runs.append([index, index, label])
    merged: list[list] = []
    for run in runs:
        if merged and (run[1] - run[0] + 1 < shortest or merged[-1][2] == run[2]):
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    if len(merged) > 1 and merged[0][1] - merged[0][0] + 1 < shortest:
        merged[1][0] = merged[0][0]
        merged.pop(0)
    return [tuple(r) for r in merged]


def duet_timeline(frames: list[FrameRecord], fps: float, width: int, height: int) -> list[DuetSpan]:
    seen = Counter(p.person_id for record in frames for p in _people(record))
    together = sum(1 for record in frames if len(_people(record)) >= 2)
    if len(seen) < 2 or together < MIN_TOGETHER * max(len(frames), 1):
        return []
    first, second = sorted(name for name, _ in seen.most_common(2))
    a, b = _poses(frames, first, width, height), _poses(frames, second, width, height)
    mirrored = b[:, MIRROR].copy()
    mirrored[..., 0] *= -1
    n = len(frames)
    lag = max(int(round(LAG_S * fps)), 0)
    best = np.full(n, np.inf)
    for shift in range(-lag, lag + 1):
        moved = np.full_like(b, np.nan)
        moved_m = np.full_like(b, np.nan)
        lo, hi = max(0, -shift), min(n, n - shift)
        moved[lo:hi] = b[lo + shift:hi + shift]
        moved_m[lo:hi] = mirrored[lo + shift:hi + shift]
        for d in (_distance(a, moved), _distance(a, moved_m)):
            best = np.where(np.isnan(d), best, np.minimum(best, d))
    best[np.isinf(best)] = np.nan
    distance = _smooth(best, int(round(SMOOTH_S * fps)))

    def energy(p: np.ndarray) -> np.ndarray:
        v = np.full(n, np.nan)
        if n > 2:
            step = np.linalg.norm(p[2:] - p[:-2], axis=-1) / 2
            count = (~np.isnan(step)).sum(axis=1)
            v[1:-1] = np.where(count > 0, np.nansum(step, axis=1) / np.maximum(count, 1), np.nan)
        return _smooth(v, int(round(ENERGY_S * fps)))

    ea, eb = energy(a), energy(b)
    leaders = [first if ea[i] >= eb[i] else second for i in range(n)]
    shortest = max(int(round(MIN_SPAN_S * fps)), 1)
    modes = _runs(["unison" if distance[i] < UNISON_D else "solo" for i in range(n)], shortest)
    spans: list[DuetSpan] = []
    for start, end, mode in modes:
        if mode == "unison":
            pieces = [(start, end, Counter(leaders[start:end + 1]).most_common(1)[0][0])]
        else:
            pieces = [(start + s, start + e, who) for s, e, who in _runs(leaders[start:end + 1], shortest)]
        for s, e, who in pieces:
            spans.append(
                DuetSpan(start_frame=int(s), end_frame=int(e), mode=mode, leader=who, partner=second if who == first else first)
            )
    return spans


def duet_at(spans: list[DuetSpan], frame: int) -> DuetSpan | None:
    return next((s for s in spans if s.start_frame <= frame <= s.end_frame), None)
